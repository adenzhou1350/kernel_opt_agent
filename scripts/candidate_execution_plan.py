#!/usr/bin/env python3
"""Create and validate phase-aware, receipt-proven candidate execution plans."""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path


PLAN_SCHEMA = "candidate-execution-plan-v1"
PROCESS_MODELS = {
    "COLD_PER_ARM",
    "PERSISTENT_SHARED_ENGINE",
    "PERSISTENT_PER_ARM",
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_object(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def is_sha256(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def run_path(run: Path, value: object, label: str, *, must_exist: bool = False) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty run-relative path")
    path = (run / value).resolve()
    try:
        path.relative_to(run.resolve())
    except ValueError as error:
        raise ValueError(f"{label} escapes the run: {value!r}") from error
    if must_exist and not path.exists():
        raise ValueError(f"{label} does not exist: {value!r}")
    return path


def phase_value(timing: dict, primary: str, fallback: str | None = None) -> float:
    value = timing.get(primary)
    if value is None and fallback is not None:
        value = timing.get(fallback)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ValueError(f"phase timing requires non-negative {primary}")
    return float(value)


def validate_persistent_session_receipt(run: Path, path: Path) -> dict:
    receipt = read_object(path)
    if (
        receipt.get("schema_version") != "persistent-session-receipt-v1"
        or receipt.get("status") != "PASS"
        or receipt.get("failure") is not None
        or receipt.get("process_launches") != 1
        or receipt.get("engine_init_count") != 1
        or not is_sha256(receipt.get("session_identity"))
    ):
        raise ValueError("persistent receipt does not prove one initialized engine")
    requests = receipt.get("requests")
    if (
        not isinstance(requests, list)
        or receipt.get("request_count") != len(requests)
        or not requests
    ):
        raise ValueError("persistent receipt request count is invalid")
    for row in requests:
        if (
            not isinstance(row, dict)
            or not is_sha256(row.get("treatment_identity"))
            or not is_sha256(row.get("output_digest"))
        ):
            raise ValueError("persistent receipt request identity is invalid")
    for label in ("stdout", "stderr"):
        identity = receipt.get(label)
        if not isinstance(identity, dict) or not is_sha256(identity.get("sha256")):
            raise ValueError(f"persistent receipt has invalid {label} identity")
        artifact = run_path(
            run, identity.get("path"), f"persistent receipt {label}", must_exist=True
        )
        if not artifact.is_file() or digest(artifact) != identity["sha256"]:
            raise ValueError(f"persistent receipt {label} SHA256 mismatch")
    return receipt


def validate_shared_switching_receipt(run: Path, path: Path) -> dict:
    receipt = validate_persistent_session_receipt(run, path)
    if (
        receipt.get("session_scope") != "SHARED_TREATMENTS"
        or receipt.get("switching_supported") is not True
        or len({row["treatment_identity"] for row in receipt["requests"]}) < 2
    ):
        raise ValueError("shared switching receipt must exercise two treatments safely")
    return receipt


def expected_selection(
    *,
    fixed_share: float,
    threshold: float,
    safe_shared: bool,
    arms: int,
    requests_per_arm: int,
) -> tuple[str, str, str]:
    if fixed_share >= threshold and safe_shared and arms > 1:
        return (
            "PERSISTENT_SHARED_ENGINE",
            "SHARED_TREATMENTS",
            "fixed cost dominates and a hash-bound receipt proves safe switching",
        )
    if fixed_share >= threshold and requests_per_arm > 1:
        return (
            "PERSISTENT_PER_ARM",
            "SINGLE_TREATMENT",
            "fixed cost dominates but shared switching is unproven",
        )
    return (
        "COLD_PER_ARM",
        "NONE",
        "persistent reuse has no proved material advantage for this request shape",
    )


def derived_estimates(
    *,
    fixed: float,
    steady: float,
    samples: int,
    arms: int,
    requests_per_arm: int,
    process_model: str,
) -> tuple[float, float, int]:
    total_requests = arms * requests_per_arm
    steady_per_request = steady / samples
    legacy_seconds = total_requests * (fixed + steady_per_request)
    if process_model == "PERSISTENT_SHARED_ENGINE":
        return legacy_seconds, fixed + total_requests * steady_per_request, 1
    return (
        legacy_seconds,
        arms * (fixed + requests_per_arm * steady_per_request),
        arms,
    )


def create_execution_plan(
    *,
    run: Path,
    candidate_id: str,
    phase_timing: str,
    output: str,
    arm_count: int,
    requests_per_arm: int,
    fixed_share_threshold: float,
    shared_switching_receipt: str | None,
) -> tuple[dict, Path]:
    run = run.resolve()
    timing_path = run_path(run, phase_timing, "phase_timing", must_exist=True)
    if not timing_path.is_file():
        raise ValueError("phase_timing must name a file")
    output_path = run_path(run, output, "execution plan output")
    if output_path.exists():
        raise FileExistsError("execution plan output already exists")
    if arm_count < 1 or requests_per_arm < 1:
        raise ValueError("arm-count and requests-per-arm must be positive")
    if not 0 <= fixed_share_threshold <= 1:
        raise ValueError("fixed-share-threshold must be between zero and one")
    document = read_object(timing_path)
    timing = document.get("timing_accounting", document)
    if not isinstance(timing, dict):
        raise ValueError("phase timing must contain timing_accounting")
    setup = phase_value(timing, "setup_seconds", "tokenizer_setup_seconds")
    compile_seconds = phase_value(
        timing, "compile_seconds", "engine_init_compile_capture_seconds"
    )
    warmup = phase_value(timing, "warmup_seconds")
    steady = phase_value(timing, "steady_state_seconds")
    samples = timing.get("steady_state_samples")
    if isinstance(samples, bool) or not isinstance(samples, int) or samples < 1:
        raise ValueError("phase timing requires positive steady_state_samples")
    if steady <= 0:
        raise ValueError("phase timing steady_state_seconds must be positive")
    fixed = setup + compile_seconds + warmup
    fixed_share = fixed / (fixed + steady)
    switching_identity = None
    safe_shared = False
    if shared_switching_receipt:
        switching_path = run_path(
            run,
            shared_switching_receipt,
            "shared_switching_receipt",
            must_exist=True,
        )
        validate_shared_switching_receipt(run, switching_path)
        switching_identity = {
            "path": switching_path.relative_to(run).as_posix(),
            "sha256": digest(switching_path),
        }
        safe_shared = True
    process_model, session_scope, reason = expected_selection(
        fixed_share=fixed_share,
        threshold=fixed_share_threshold,
        safe_shared=safe_shared,
        arms=arm_count,
        requests_per_arm=requests_per_arm,
    )
    total_requests = arm_count * requests_per_arm
    legacy_seconds, selected_seconds, session_count = derived_estimates(
        fixed=fixed,
        steady=steady,
        samples=samples,
        arms=arm_count,
        requests_per_arm=requests_per_arm,
        process_model=process_model,
    )
    plan = {
        "schema_version": PLAN_SCHEMA,
        "candidate_id": candidate_id,
        "created_at": now(),
        "inputs": {
            "phase_timing": {
                "path": timing_path.relative_to(run).as_posix(),
                "sha256": digest(timing_path),
            },
            "shared_switching_receipt": switching_identity,
        },
        "workload": {
            "arm_count": arm_count,
            "requests_per_arm": requests_per_arm,
            "total_requests": total_requests,
        },
        "phase_timing": {
            "setup_seconds": setup,
            "compile_seconds": compile_seconds,
            "warmup_seconds": warmup,
            "steady_state_seconds": steady,
            "steady_state_samples": samples,
            "fixed_seconds": fixed,
            "fixed_share": fixed_share,
        },
        "policy": {"fixed_share_threshold": fixed_share_threshold},
        "selection": {
            "process_model": process_model,
            "session_scope": session_scope,
            "persistent_session_eligible": process_model != "COLD_PER_ARM",
            "switching_preserves_treatment_identity": safe_shared,
            "requires_persistent_session_protocol": process_model != "COLD_PER_ARM",
            "reason": reason,
        },
        "estimates": {
            "legacy_cold_per_request_seconds": legacy_seconds,
            "selected_seconds": selected_seconds,
            "selected_session_count": session_count,
            "estimated_experiment_speedup": legacy_seconds / selected_seconds,
        },
        "claim_scope": "EXECUTION_ROUTING_ONLY_NOT_CANDIDATE_PERFORMANCE",
    }
    atomic_json(output_path, plan)
    return plan, output_path


def validate_execution_plan(
    run: Path, identity: object, candidate_id: str
) -> tuple[Path, dict]:
    if not isinstance(identity, dict) or set(identity) != {"path", "sha256"}:
        raise ValueError("execution_plan must contain exactly path and sha256")
    path = run_path(run, identity.get("path"), "execution_plan", must_exist=True)
    if not path.is_file() or not is_sha256(identity.get("sha256")):
        raise ValueError("execution_plan must bind a run-local file by SHA-256")
    if digest(path) != identity["sha256"]:
        raise ValueError("execution_plan SHA256 mismatch")
    plan = read_object(path)
    if plan.get("schema_version") != PLAN_SCHEMA:
        raise ValueError("execution_plan uses an unsupported schema")
    if plan.get("candidate_id") != candidate_id:
        raise ValueError("execution_plan candidate_id mismatch")
    selected = plan.get("selection", {}).get("process_model")
    if selected not in PROCESS_MODELS:
        raise ValueError("execution_plan process model is unsupported")
    inputs = plan.get("inputs")
    if not isinstance(inputs, dict):
        raise ValueError("execution_plan inputs are missing")
    timing_identity = inputs.get("phase_timing")
    if (
        not isinstance(timing_identity, dict)
        or set(timing_identity) != {"path", "sha256"}
        or not is_sha256(timing_identity.get("sha256"))
    ):
        raise ValueError("execution_plan phase timing identity is invalid")
    timing_path = run_path(
        run, timing_identity.get("path"), "execution plan phase timing", must_exist=True
    )
    if not timing_path.is_file() or digest(timing_path) != timing_identity["sha256"]:
        raise ValueError("execution_plan phase timing SHA256 mismatch")
    source_document = read_object(timing_path)
    source_timing = source_document.get("timing_accounting", source_document)
    if not isinstance(source_timing, dict):
        raise ValueError("execution_plan source timing is invalid")
    workload = plan.get("workload")
    phase = plan.get("phase_timing")
    policy = plan.get("policy")
    selection = plan.get("selection")
    estimates = plan.get("estimates")
    if not all(
        isinstance(value, dict)
        for value in (workload, phase, policy, selection, estimates)
    ):
        raise ValueError("execution_plan is missing routing fields")
    arms = workload.get("arm_count")
    requests_per_arm = workload.get("requests_per_arm")
    if (
        isinstance(arms, bool)
        or not isinstance(arms, int)
        or arms < 1
        or isinstance(requests_per_arm, bool)
        or not isinstance(requests_per_arm, int)
        or requests_per_arm < 1
        or workload.get("total_requests") != arms * requests_per_arm
    ):
        raise ValueError("execution_plan workload counts are inconsistent")
    numeric_phase = {}
    for field in (
        "setup_seconds",
        "compile_seconds",
        "warmup_seconds",
        "steady_state_seconds",
        "fixed_seconds",
        "fixed_share",
    ):
        value = phase.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            raise ValueError(f"execution_plan phase_timing.{field} is invalid")
        numeric_phase[field] = float(value)
    samples = phase.get("steady_state_samples")
    if isinstance(samples, bool) or not isinstance(samples, int) or samples < 1:
        raise ValueError("execution_plan steady-state sample count is invalid")
    if numeric_phase["steady_state_seconds"] <= 0:
        raise ValueError("execution_plan steady-state time must be positive")
    source_values = {
        "setup_seconds": phase_value(
            source_timing, "setup_seconds", "tokenizer_setup_seconds"
        ),
        "compile_seconds": phase_value(
            source_timing,
            "compile_seconds",
            "engine_init_compile_capture_seconds",
        ),
        "warmup_seconds": phase_value(source_timing, "warmup_seconds"),
        "steady_state_seconds": phase_value(
            source_timing, "steady_state_seconds"
        ),
    }
    source_samples = source_timing.get("steady_state_samples")
    if (
        isinstance(source_samples, bool)
        or not isinstance(source_samples, int)
        or source_samples < 1
    ):
        raise ValueError("execution_plan source sample count is invalid")
    if any(
        not math.isclose(numeric_phase[field], expected)
        for field, expected in source_values.items()
    ) or samples != source_samples:
        raise ValueError("execution_plan phase timing differs from its bound source")
    fixed = (
        numeric_phase["setup_seconds"]
        + numeric_phase["compile_seconds"]
        + numeric_phase["warmup_seconds"]
    )
    fixed_share = fixed / (fixed + numeric_phase["steady_state_seconds"])
    if not math.isclose(numeric_phase["fixed_seconds"], fixed) or not math.isclose(
        numeric_phase["fixed_share"], fixed_share
    ):
        raise ValueError("execution_plan phase derivation is inconsistent")
    threshold = policy.get("fixed_share_threshold")
    if (
        isinstance(threshold, bool)
        or not isinstance(threshold, (int, float))
        or not 0 <= threshold <= 1
    ):
        raise ValueError("execution_plan fixed-share threshold is invalid")
    switching_identity = inputs.get("shared_switching_receipt")
    safe_shared = False
    if switching_identity is not None:
        if (
            not isinstance(switching_identity, dict)
            or set(switching_identity) != {"path", "sha256"}
            or not is_sha256(switching_identity.get("sha256"))
        ):
            raise ValueError("execution_plan shared-switching identity is invalid")
        switching_path = run_path(
            run,
            switching_identity.get("path"),
            "execution plan shared switching receipt",
            must_exist=True,
        )
        if (
            not switching_path.is_file()
            or digest(switching_path) != switching_identity["sha256"]
        ):
            raise ValueError("execution_plan shared-switching receipt SHA256 mismatch")
        validate_shared_switching_receipt(run, switching_path)
        safe_shared = True
    expected_model, expected_scope, _ = expected_selection(
        fixed_share=fixed_share,
        threshold=float(threshold),
        safe_shared=safe_shared,
        arms=arms,
        requests_per_arm=requests_per_arm,
    )
    if selected != expected_model or selection.get("session_scope") != expected_scope:
        raise ValueError("execution_plan selection does not follow its measured inputs")
    expected_persistent = expected_model != "COLD_PER_ARM"
    if (
        selection.get("persistent_session_eligible") is not expected_persistent
        or selection.get("requires_persistent_session_protocol") is not expected_persistent
        or selection.get("switching_preserves_treatment_identity") is not safe_shared
    ):
        raise ValueError("execution_plan safety flags are inconsistent")
    legacy_seconds, selected_seconds, selected_sessions = derived_estimates(
        fixed=fixed,
        steady=numeric_phase["steady_state_seconds"],
        samples=samples,
        arms=arms,
        requests_per_arm=requests_per_arm,
        process_model=expected_model,
    )
    expected_estimates = {
        "legacy_cold_per_request_seconds": legacy_seconds,
        "selected_seconds": selected_seconds,
        "estimated_experiment_speedup": legacy_seconds / selected_seconds,
    }
    for field, expected in expected_estimates.items():
        value = estimates.get(field)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isclose(float(value), expected)
        ):
            raise ValueError(f"execution_plan estimate {field} is inconsistent")
    if estimates.get("selected_session_count") != selected_sessions:
        raise ValueError("execution_plan selected session count is inconsistent")
    if plan.get("claim_scope") != "EXECUTION_ROUTING_ONLY_NOT_CANDIDATE_PERFORMANCE":
        raise ValueError("execution_plan claim scope is invalid")
    return path, plan
