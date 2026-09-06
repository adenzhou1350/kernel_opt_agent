#!/usr/bin/env python3
"""Manage the fast, repairable candidate-discovery lane for production kernels."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from candidate_execution_plan import (
    create_execution_plan,
    validate_execution_plan,
    validate_persistent_session_receipt,
    validate_shared_switching_receipt,
)
from opportunity_map import load_map as load_opportunity_map, map_path as opportunity_map_path, validate_map as validate_opportunity_map


POOL_SCHEMA = "candidate-pool-v1"
SMOKE_SCHEMA = "candidate-smoke-result-v6"
ACTIVE_STATUSES = {"PROPOSED", "DEVELOPING"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def elapsed_minutes(timestamp: str | None) -> float:
    if not timestamp:
        return 0.0
    started = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - started).total_seconds() / 60.0)


def read_object(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def atomic_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def run_path(run: Path, value: str, label: str, *, must_exist: bool = False) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty run-relative path")
    path = (run / value).resolve()
    if not inside(path, run):
        raise ValueError(f"{label} escapes the run: {value!r}")
    if must_exist and not path.exists():
        raise ValueError(f"{label} does not exist: {value!r}")
    return path


def pool_path(run: Path) -> Path:
    return run / "models" / "candidate_pool.json"


def load_pool(run: Path) -> dict:
    path = pool_path(run)
    if not path.is_file():
        raise ValueError(f"candidate pool is missing; run `kernel_opt.py candidate init --run {run}`")
    pool = read_object(path)
    if pool.get("schema_version") != POOL_SCHEMA:
        raise ValueError("candidate pool uses an unsupported schema")
    return pool


def candidate(pool: dict, candidate_id: str) -> dict:
    item = next((row for row in pool.get("candidates", []) if row.get("candidate_id") == candidate_id), None)
    if item is None:
        raise ValueError(f"unknown candidate: {candidate_id}")
    return item


def validate_command(command: dict, label: str) -> None:
    if not isinstance(command, dict):
        raise ValueError(f"{label} must be an object")
    argv = command.get("argv")
    if not isinstance(argv, list) or not argv or not all(isinstance(value, str) and value for value in argv):
        raise ValueError(f"{label}.argv must be a non-empty string array")
    timeout = command.get("timeout_seconds")
    if not isinstance(timeout, int) or timeout <= 0:
        raise ValueError(f"{label}.timeout_seconds must be a positive integer")
    if not isinstance(command.get("cwd"), str) or not command["cwd"]:
        raise ValueError(f"{label}.cwd must be a run-relative directory")


def validate_spec(run: Path, spec: dict) -> None:
    required = (
        "candidate_id", "opportunity_id", "name", "family", "change_axes", "hypothesis",
        "expected_global_effect", "source_paths", "commands", "smoke_result_path",
        "predicted_global_gain_us", "dependency_contract", "execution_plan",
        "persistent_session_specs",
    )
    missing = [
        field
        for field in required
        if field not in spec
        or (field != "persistent_session_specs" and not spec.get(field))
    ]
    if missing:
        raise ValueError(f"candidate spec is missing fields: {missing}")
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", str(spec["candidate_id"])):
        raise ValueError("candidate_id must use lowercase stable characters")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", str(spec["family"])):
        raise ValueError("family must use lowercase kebab-case")
    prediction = spec["predicted_global_gain_us"]
    if not isinstance(prediction, dict) or set(prediction) != {"lower", "upper"}:
        raise ValueError("predicted_global_gain_us must contain exactly lower and upper")
    try:
        lower, upper = float(prediction["lower"]), float(prediction["upper"])
    except (TypeError, ValueError) as error:
        raise ValueError("predicted_global_gain_us bounds must be numeric") from error
    if not 0 <= lower <= upper:
        raise ValueError("predicted_global_gain_us requires 0 <= lower <= upper")
    axes = spec["change_axes"]
    if not isinstance(axes, list) or not axes or len(axes) != len(set(map(str, axes))):
        raise ValueError("change_axes must be a non-empty unique array")
    sources = spec["source_paths"]
    if not isinstance(sources, list) or not sources:
        raise ValueError("source_paths must be a non-empty array")
    for index, value in enumerate(sources):
        path = run_path(run, value, f"source_paths[{index}]", must_exist=True)
        if not path.is_file():
            raise ValueError(f"source_paths[{index}] must name a file")
    dependency = spec["dependency_contract"]
    if not isinstance(dependency, dict) or dependency.get("status") != "PROVEN_LEGAL":
        raise ValueError("dependency_contract.status must be PROVEN_LEGAL")
    for field in (
        "preserved_dependencies",
        "changed_boundaries",
        "prohibited_rewrites",
    ):
        values = dependency.get(field)
        if (
            not isinstance(values, list)
            or not values
            or not all(isinstance(value, str) and value.strip() for value in values)
        ):
            raise ValueError(f"dependency_contract.{field} must be a non-empty string array")
    if not isinstance(dependency.get("numerical_ordering"), str) or not dependency[
        "numerical_ordering"
    ].strip():
        raise ValueError("dependency_contract.numerical_ordering is required")
    dependency_evidence = dependency.get("evidence")
    if not isinstance(dependency_evidence, list) or not dependency_evidence:
        raise ValueError("dependency_contract.evidence must be a non-empty array")
    for index, identity in enumerate(dependency_evidence):
        if not isinstance(identity, dict) or set(identity) != {"path", "sha256", "claim"}:
            raise ValueError(
                f"dependency_contract.evidence[{index}] must contain exactly path, sha256, and claim"
            )
        evidence_path = run_path(
            run,
            identity.get("path"),
            f"dependency_contract.evidence[{index}]",
            must_exist=True,
        )
        if not evidence_path.is_file():
            raise ValueError(f"dependency_contract.evidence[{index}] must name a file")
        if identity.get("sha256") != digest(evidence_path):
            raise ValueError(f"dependency_contract.evidence[{index}] SHA256 mismatch")
        if not isinstance(identity.get("claim"), str) or not identity["claim"].strip():
            raise ValueError(f"dependency_contract.evidence[{index}].claim is required")
    commands = spec["commands"]
    if not isinstance(commands, dict):
        raise ValueError("commands must be an object")
    for stage in ("build", "correctness", "smoke"):
        validate_command(commands.get(stage), f"commands.{stage}")
        cwd = run_path(run, commands[stage]["cwd"], f"commands.{stage}.cwd", must_exist=True)
        if not cwd.is_dir():
            raise ValueError(f"commands.{stage}.cwd must name a directory")
    run_path(run, spec["smoke_result_path"], "smoke_result_path")
    _, plan = validate_execution_plan(
        run, spec["execution_plan"], str(spec["candidate_id"])
    )
    persistent_specs(run, spec, plan)


def source_identities(run: Path, item: dict) -> list[dict]:
    return [
        {"path": value, "sha256": digest(run_path(run, value, "source", must_exist=True))}
        for value in item["source_paths"]
    ]


def persistent_specs(run: Path, item: dict, plan: dict) -> list[Path]:
    identities = item.get("persistent_session_specs")
    if not isinstance(identities, list):
        raise ValueError("persistent_session_specs must be an array")
    expected = (
        plan["estimates"]["selected_session_count"]
        if plan["selection"]["requires_persistent_session_protocol"]
        else 0
    )
    if len(identities) != expected:
        raise ValueError("persistent_session_specs count differs from the execution plan")
    paths = []
    for index, identity in enumerate(identities):
        if not isinstance(identity, dict) or set(identity) != {"path", "sha256"}:
            raise ValueError(
                f"persistent_session_specs[{index}] must contain path and sha256"
            )
        path = run_path(
            run,
            identity.get("path"),
            f"persistent_session_specs[{index}]",
            must_exist=True,
        )
        if not path.is_file() or identity.get("sha256") != digest(path):
            raise ValueError(f"persistent_session_specs[{index}] SHA256 mismatch")
        paths.append(path)
    return paths


def substitute(value: str, run: Path, item: dict, attempt: Path) -> str:
    replacements = {
        "{python}": sys.executable,
        "{run}": str(run),
        "{candidate}": str(run / "candidates" / item["candidate_id"]),
        "{attempt}": str(attempt),
    }
    for token, replacement in replacements.items():
        value = value.replace(token, replacement)
    return value


def execute_stage(
    run: Path,
    item: dict,
    attempt: Path,
    stage: str,
    extra_environment: dict[str, str] | None = None,
) -> dict:
    contract = item["commands"][stage]
    argv = [substitute(value, run, item, attempt) for value in contract["argv"]]
    cwd = run_path(run, contract["cwd"], f"commands.{stage}.cwd", must_exist=True)
    stdout_path = attempt / f"{stage}.stdout.txt"
    stderr_path = attempt / f"{stage}.stderr.txt"
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment.update({
        "KERNEL_OPT_RUN": str(run),
        "KERNEL_OPT_CANDIDATE_ID": item["candidate_id"],
        "KERNEL_OPT_ATTEMPT_DIR": str(attempt),
    })
    environment.update(extra_environment or {})
    started = time.monotonic()
    timed_out = False
    try:
        completed = subprocess.run(
            argv,
            cwd=cwd,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=contract["timeout_seconds"],
        )
        exit_code = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
    except subprocess.TimeoutExpired as error:
        timed_out = True
        exit_code = -1
        stdout = error.stdout or ""
        stderr = (error.stderr or "") + f"\nTIMEOUT after {contract['timeout_seconds']} seconds\n"
    stdout_path.write_text(stdout, encoding="utf-8")
    stderr_path.write_text(stderr, encoding="utf-8")
    return {
        "stage": stage,
        "argv": argv,
        "cwd": cwd.relative_to(run).as_posix(),
        "exit_code": exit_code,
        "timed_out": timed_out,
        "duration_seconds": round(time.monotonic() - started, 6),
        "stdout": {"path": stdout_path.relative_to(run).as_posix(), "sha256": digest(stdout_path)},
        "stderr": {"path": stderr_path.relative_to(run).as_posix(), "sha256": digest(stderr_path)},
    }


def execute_persistent_session_stage(
    run: Path,
    attempt: Path,
    spec_path: Path,
    index: int,
) -> tuple[dict, Path]:
    spec = read_object(spec_path)
    requests = spec.get("requests")
    if not isinstance(requests, list) or not requests:
        raise ValueError("persistent session spec requires requests")
    timeout = (
        float(spec.get("startup_timeout_seconds", 0))
        + len(requests) * float(spec.get("request_timeout_seconds", 0))
        + float(spec.get("shutdown_timeout_seconds", 0))
        + 10.0
    )
    if timeout <= 10.0:
        raise ValueError("persistent session spec timeouts are invalid")
    receipt = attempt / f"persistent-session-{index:02d}.json"
    argv = [
        sys.executable,
        str(Path(__file__).resolve().with_name("persistent_session_runner.py")),
        "--root",
        str(run),
        "--spec",
        str(spec_path),
        "--output",
        str(receipt),
    ]
    stage = f"persistent-session-{index:02d}"
    stdout_path = attempt / f"{stage}.stdout.txt"
    stderr_path = attempt / f"{stage}.stderr.txt"
    started = time.monotonic()
    timed_out = False
    try:
        completed = subprocess.run(
            argv,
            cwd=run,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
        exit_code = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
    except subprocess.TimeoutExpired as error:
        timed_out = True
        exit_code = -1
        stdout = error.stdout or ""
        stderr = (error.stderr or "") + f"\nTIMEOUT after {timeout} seconds\n"
    stdout_path.write_text(stdout, encoding="utf-8")
    stderr_path.write_text(stderr, encoding="utf-8")
    return ({
        "stage": stage,
        "argv": argv,
        "cwd": ".",
        "exit_code": exit_code,
        "timed_out": timed_out,
        "duration_seconds": round(time.monotonic() - started, 6),
        "stdout": {
            "path": stdout_path.relative_to(run).as_posix(),
            "sha256": digest(stdout_path),
        },
        "stderr": {
            "path": stderr_path.relative_to(run).as_posix(),
            "sha256": digest(stderr_path),
        },
    }, receipt)


def record_failure(pool: dict, item: dict, attempt_record: dict, reason: str) -> None:
    attempt_record["status"] = "TECHNICAL_FAILURE"
    attempt_record["reason"] = reason
    item.setdefault("attempts", []).append(attempt_record)
    used = sum(row.get("status") == "TECHNICAL_FAILURE" for row in item["attempts"])
    limit = int(item["development_budget"]["max_technical_attempts"])
    wall_used = sum(
        float(stage.get("duration_seconds", 0.0))
        for attempt in item["attempts"]
        for stage in attempt.get("stages", [])
    ) / 60.0
    wall_limit = float(item["development_budget"]["max_wall_clock_minutes"])
    blocked = used >= limit or wall_used >= wall_limit
    item["status"] = "TECHNICALLY_BLOCKED" if blocked else "DEVELOPING"
    item["latest_failure"] = {
        "at": now(), "reason": reason,
        "technical_attempts_used": used, "technical_attempts_limit": limit,
        "wall_clock_minutes_used": wall_used, "wall_clock_minutes_limit": wall_limit,
    }
    pool.setdefault("events", []).append({
        "at": now(), "candidate_id": item["candidate_id"], "event": item["status"], "reason": reason,
    })


def validate_smoke_result(run: Path, path: Path, item: dict) -> tuple[dict, float]:
    result = read_object(path)
    if result.get("schema_version") != SMOKE_SCHEMA or result.get("status") != "PASS":
        raise ValueError("smoke result must record candidate-smoke-result-v6 PASS")
    if result.get("candidate_id") != item["candidate_id"]:
        raise ValueError("smoke result candidate_id mismatch")
    cases = result.get("cases")
    if not isinstance(cases, list) or len(cases) < 2:
        raise ValueError("smoke result requires at least one anchor and one edge case")
    roles = {case.get("role") for case in cases if isinstance(case, dict)}
    if not {"ANCHOR", "EDGE"} <= roles:
        raise ValueError("smoke result must cover ANCHOR and EDGE roles")
    correctness = result.get("correctness")
    if not isinstance(correctness, dict) or correctness.get("status") != "PASS":
        raise ValueError("smoke result requires correctness.status PASS")
    contract = correctness.get("contract")
    if contract not in {"EXACT_IDENTITY", "TOLERANCE_BOUNDED", "PROPERTY_BASED"}:
        raise ValueError("smoke correctness contract is missing or unsupported")
    if not isinstance(correctness.get("oracle"), str) or not correctness["oracle"].strip():
        raise ValueError("smoke correctness oracle must be non-empty")
    case_results = correctness.get("case_results")
    if not isinstance(case_results, list) or len(case_results) < 2:
        raise ValueError("smoke correctness requires at least two case results")
    declared_cases = {
        (case.get("case_id"), case.get("role"))
        for case in cases
        if isinstance(case, dict)
    }
    observed_cases = set()
    for index, case_result in enumerate(case_results):
        if not isinstance(case_result, dict):
            raise ValueError(f"correctness case result {index} must be an object")
        binding = (case_result.get("case_id"), case_result.get("role"))
        if binding not in declared_cases:
            raise ValueError(f"correctness case result {index} is not bound to a declared smoke case")
        if binding in observed_cases:
            raise ValueError(f"duplicate correctness case result: {binding[0]}")
        observed_cases.add(binding)
        if case_result.get("status") != "PASS":
            raise ValueError(f"correctness case result {index} did not PASS")
        baseline_digest = case_result.get("baseline_digest")
        candidate_digest = case_result.get("candidate_digest")
        if contract == "EXACT_IDENTITY":
            if (
                not isinstance(baseline_digest, str)
                or not re.fullmatch(r"[0-9a-f]{64}", baseline_digest)
                or candidate_digest != baseline_digest
            ):
                raise ValueError(
                    "EXACT_IDENTITY requires equal lowercase SHA-256 baseline and candidate digests"
                )
        evidence = case_result.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            raise ValueError(f"correctness case result {index} requires hash-bound evidence")
        for evidence_index, identity in enumerate(evidence):
            if not isinstance(identity, dict):
                raise ValueError(
                    f"correctness case result {index} evidence {evidence_index} must be an object"
                )
            evidence_path = run_path(
                run,
                identity.get("path"),
                f"correctness case result {index} evidence {evidence_index}",
                must_exist=True,
            )
            if identity.get("sha256") != digest(evidence_path):
                raise ValueError(
                    f"correctness case result {index} evidence {evidence_index} SHA256 mismatch"
                )
    if not {"ANCHOR", "EDGE"} <= {role for _, role in observed_cases}:
        raise ValueError("smoke correctness must cover ANCHOR and EDGE roles")
    reachability = result.get("reachability")
    if not isinstance(reachability, dict) or reachability.get("status") != "PASS":
        raise ValueError("smoke result requires reachability.status PASS")
    expected_path = reachability.get("expected_path")
    observed_path = reachability.get("observed_path")
    if not isinstance(expected_path, str) or not expected_path:
        raise ValueError("reachability.expected_path must be non-empty")
    if observed_path != expected_path:
        raise ValueError("candidate execution path was not reached")
    if reachability.get("compile_cache_policy") not in {
        "FRESH",
        "SOURCE_HASHED",
        "NOT_COMPILED",
    }:
        raise ValueError("reachability.compile_cache_policy is missing or unsupported")
    execution_proof = reachability.get("execution_proof")
    if not isinstance(execution_proof, dict):
        raise ValueError("reachability requires runtime execution_proof")
    proof_kind = execution_proof.get("kind")
    allowed_proof_kinds = {
        "KERNEL_INSTANCE_COUNT",
        "INSTRUMENTED_CALL_COUNT",
        "DIRECT_SENTINEL",
    }
    if proof_kind not in allowed_proof_kinds:
        raise ValueError("reachability execution_proof.kind is unsupported")
    if (
        reachability.get("compile_cache_policy") in {"FRESH", "SOURCE_HASHED"}
        and proof_kind == "DIRECT_SENTINEL"
    ):
        raise ValueError(
            "compiled candidates require a kernel or instrumented call count"
        )
    observed_count = execution_proof.get("observed_count")
    minimum_count = execution_proof.get("minimum_count")
    if (
        isinstance(observed_count, bool)
        or not isinstance(observed_count, int)
        or isinstance(minimum_count, bool)
        or not isinstance(minimum_count, int)
        or minimum_count < 1
        or observed_count < minimum_count
    ):
        raise ValueError("candidate runtime execution count did not reach its minimum")
    if not isinstance(execution_proof.get("scope"), str) or not execution_proof[
        "scope"
    ]:
        raise ValueError("reachability execution_proof.scope must be non-empty")
    evidence_index = execution_proof.get("evidence_index")
    if isinstance(evidence_index, bool) or not isinstance(evidence_index, int):
        raise ValueError("reachability execution_proof.evidence_index must be an integer")
    reachability_evidence = reachability.get("evidence")
    if not isinstance(reachability_evidence, list) or not reachability_evidence:
        raise ValueError("reachability requires hash-bound evidence")
    if evidence_index < 0 or evidence_index >= len(reachability_evidence):
        raise ValueError("reachability execution proof is not bound to evidence")
    for index, identity in enumerate(reachability_evidence):
        if not isinstance(identity, dict):
            raise ValueError(f"reachability evidence {index} must be an object")
        evidence_path = run_path(
            run,
            identity.get("path"),
            f"reachability evidence {index}",
            must_exist=True,
        )
        if identity.get("sha256") != digest(evidence_path):
            raise ValueError(f"reachability evidence {index} SHA256 mismatch")
    runtime_contract = result.get("runtime_contract")
    if not isinstance(runtime_contract, dict):
        raise ValueError("smoke result requires runtime_contract")
    production_mode = runtime_contract.get("production_execution_mode")
    observed_mode = runtime_contract.get("observed_execution_mode")
    allowed_modes = {"EAGER", "COMPILED", "CUDA_GRAPH"}
    if production_mode not in allowed_modes or observed_mode not in allowed_modes:
        raise ValueError("runtime execution mode is missing or unsupported")
    if observed_mode != production_mode:
        raise ValueError("smoke execution mode does not match production")
    materialization = runtime_contract.get("treatment_materialization")
    if materialization not in {
        "SOURCE_FILE",
        "GENERATED_ARTIFACT",
        "RUNTIME_MONKEYPATCH",
        "DIRECT_CALL",
    }:
        raise ValueError("treatment materialization is missing or unsupported")
    cache_binds_treatment = runtime_contract.get(
        "compile_cache_key_includes_treatment"
    )
    if not isinstance(cache_binds_treatment, bool):
        raise ValueError("runtime contract must declare compile-cache treatment binding")
    is_compiled = observed_mode in {"COMPILED", "CUDA_GRAPH"}
    if is_compiled:
        if reachability.get("compile_cache_policy") == "NOT_COMPILED":
            raise ValueError("compiled runtime cannot declare NOT_COMPILED cache policy")
        if materialization == "RUNTIME_MONKEYPATCH":
            raise ValueError("compiled runtime cannot rely on a runtime monkeypatch")
        if not cache_binds_treatment:
            raise ValueError("compiled cache key must include the treatment identity")
    extent_source = runtime_contract.get("logical_extent_source")
    if extent_source not in {
        "EXPLICIT_RUNTIME_METADATA",
        "STATIC_SPECIALIZATION",
        "PHYSICAL_TENSOR_SHAPE",
        "NOT_APPLICABLE",
    }:
        raise ValueError("logical extent source is missing or unsupported")
    requires_logical_extent = runtime_contract.get("requires_logical_extent")
    if not isinstance(requires_logical_extent, bool):
        raise ValueError("runtime contract must declare logical-extent dependence")
    if (
        is_compiled
        and requires_logical_extent
        and extent_source not in {
            "EXPLICIT_RUNTIME_METADATA",
            "STATIC_SPECIALIZATION",
        }
    ):
        raise ValueError(
            "compiled logical extents require explicit metadata or static specialization"
        )
    treatment_evidence_index = runtime_contract.get(
        "treatment_identity_evidence_index"
    )
    if (
        isinstance(treatment_evidence_index, bool)
        or not isinstance(treatment_evidence_index, int)
        or treatment_evidence_index < 0
        or treatment_evidence_index >= len(reachability_evidence)
    ):
        raise ValueError("runtime treatment identity is not bound to reachability evidence")
    timing = result.get("timing_accounting")
    if not isinstance(timing, dict):
        raise ValueError("smoke result requires timing_accounting")
    for field in (
        "setup_seconds",
        "compile_seconds",
        "warmup_seconds",
        "steady_state_seconds",
    ):
        value = timing.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            raise ValueError(f"timing_accounting.{field} must be non-negative")
    if timing["steady_state_seconds"] <= 0:
        raise ValueError("timing_accounting.steady_state_seconds must be positive")
    samples = timing.get("steady_state_samples")
    if isinstance(samples, bool) or not isinstance(samples, int) or samples < 1:
        raise ValueError("timing_accounting.steady_state_samples must be positive")
    objective_window = timing.get("objective_window")
    if objective_window not in {"STEADY_STATE_ONLY", "END_TO_END_WITH_SETUP"}:
        raise ValueError("timing objective window is missing or unsupported")
    process_model = timing.get("process_model")
    if process_model not in {
        "COLD_PER_ARM",
        "PERSISTENT_SHARED_ENGINE",
        "PERSISTENT_PER_ARM",
    }:
        raise ValueError("timing process model is missing or unsupported")
    plan_path, plan = validate_execution_plan(
        run, item.get("execution_plan"), item["candidate_id"]
    )
    selected_model = plan["selection"]["process_model"]
    if process_model != selected_model:
        raise ValueError("smoke process model differs from the sealed execution plan")
    plan_evidence_index = timing.get("execution_plan_evidence_index")
    if (
        isinstance(plan_evidence_index, bool)
        or not isinstance(plan_evidence_index, int)
        or plan_evidence_index < 0
        or plan_evidence_index >= len(reachability_evidence)
    ):
        raise ValueError("timing execution plan is not bound to reachability evidence")
    plan_evidence = reachability_evidence[plan_evidence_index]
    if (
        plan_evidence.get("path") != plan_path.relative_to(run).as_posix()
        or plan_evidence.get("sha256") != item["execution_plan"]["sha256"]
    ):
        raise ValueError("smoke evidence does not bind the sealed execution plan")
    persistent_eligible = timing.get("persistent_session_eligible")
    switching_preserves_identity = timing.get(
        "switching_preserves_treatment_identity"
    )
    if not isinstance(persistent_eligible, bool) or not isinstance(
        switching_preserves_identity, bool
    ):
        raise ValueError("timing accounting must declare persistent-session safety")
    if persistent_eligible != plan["selection"]["persistent_session_eligible"]:
        raise ValueError("persistent eligibility differs from the sealed execution plan")
    if (
        switching_preserves_identity
        != plan["selection"]["switching_preserves_treatment_identity"]
    ):
        raise ValueError("switching safety differs from the sealed execution plan")
    receipt_indices = timing.get("persistent_session_receipt_evidence_indices")
    if (
        not isinstance(receipt_indices, list)
        or any(
            isinstance(index, bool) or not isinstance(index, int)
            for index in receipt_indices
        )
        or len(receipt_indices) != len(set(receipt_indices))
    ):
        raise ValueError("timing persistent-session receipt indices are invalid")
    if process_model == "COLD_PER_ARM":
        if receipt_indices:
            raise ValueError("cold process model cannot claim persistent-session receipts")
    else:
        expected_receipts = (
            1
            if process_model == "PERSISTENT_SHARED_ENGINE"
            else plan["workload"]["arm_count"]
        )
        if len(receipt_indices) != expected_receipts:
            raise ValueError("persistent process model has the wrong receipt count")
        receipts = []
        for index in receipt_indices:
            if index < 0 or index >= len(reachability_evidence):
                raise ValueError("persistent-session receipt is not bound to evidence")
            identity = reachability_evidence[index]
            receipt_path = run_path(
                run,
                identity.get("path"),
                "persistent-session receipt evidence",
                must_exist=True,
            )
            if not receipt_path.is_file() or digest(receipt_path) != identity.get("sha256"):
                raise ValueError("persistent-session receipt evidence SHA256 mismatch")
            receipts.append(validate_persistent_session_receipt(run, receipt_path))
        if process_model == "PERSISTENT_SHARED_ENGINE":
            validate_shared_switching_receipt(
                run,
                run_path(
                    run,
                    reachability_evidence[receipt_indices[0]]["path"],
                    "shared persistent-session receipt",
                    must_exist=True,
                ),
            )
            if receipts[0]["request_count"] < plan["workload"]["total_requests"]:
                raise ValueError("shared persistent receipt covers too few requests")
        else:
            for receipt in receipts:
                treatment_ids = {
                    row["treatment_identity"] for row in receipt["requests"]
                }
                if (
                    receipt.get("session_scope") != "SINGLE_TREATMENT"
                    or len(treatment_ids) != 1
                    or receipt["request_count"]
                    < plan["workload"]["requests_per_arm"]
                ):
                    raise ValueError(
                        "persistent-per-arm receipt must prove one treatment and enough requests"
                    )
    if process_model == "PERSISTENT_SHARED_ENGINE" and (
        not persistent_eligible or not switching_preserves_identity
    ):
        raise ValueError(
            "shared persistent engine requires safe treatment-identity switching"
        )
    objective = result.get("objective", {})
    direction = objective.get("direction")
    if direction not in {"minimize", "maximize"}:
        raise ValueError("smoke objective direction must be minimize or maximize")
    if objective.get("measurement_window") != objective_window:
        raise ValueError("smoke objective and timing measurement windows differ")
    try:
        baseline = float(objective["baseline"])
        observed = float(objective["candidate"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("smoke objective requires numeric baseline and candidate") from error
    if baseline == 0:
        raise ValueError("smoke objective baseline must be non-zero")
    improvement = ((baseline - observed) / abs(baseline) if direction == "minimize" else (observed - baseline) / abs(baseline)) * 100.0
    return result, improvement


def command_plan_execution(args: argparse.Namespace) -> dict:
    run = args.run.resolve()
    if args.persistent_session_spec and not args.attach:
        raise ValueError("--persistent-session-spec is only valid with --attach")
    attach_pool = None
    attach_item = None
    if args.attach:
        attach_pool = load_pool(run)
        attach_item = candidate(attach_pool, args.candidate_id)
        if attach_item.get("status") not in ACTIVE_STATUSES:
            raise ValueError("only an active legacy candidate can attach an execution plan")
    plan, output = create_execution_plan(
        run=run,
        candidate_id=args.candidate_id,
        phase_timing=args.phase_timing,
        output=args.output,
        arm_count=args.arm_count,
        requests_per_arm=args.requests_per_arm,
        fixed_share_threshold=args.fixed_share_threshold,
        shared_switching_receipt=args.shared_switching_receipt,
    )
    if attach_item is not None and attach_pool is not None:
        attached_specs = []
        for index, value in enumerate(args.persistent_session_spec):
            path = run_path(
                run,
                value,
                f"persistent-session-spec[{index}]",
                must_exist=True,
            )
            if not path.is_file():
                raise ValueError("attached persistent-session spec must name a file")
            attached_specs.append({
                "path": path.relative_to(run).as_posix(),
                "sha256": digest(path),
            })
        persistent_specs(
            run,
            {"persistent_session_specs": attached_specs},
            plan,
        )
        attach_item["execution_plan"] = {
            "path": output.relative_to(run).as_posix(),
            "sha256": digest(output),
        }
        attach_item["persistent_session_specs"] = attached_specs
        attach_pool.setdefault("events", []).append({
            "at": now(),
            "candidate_id": args.candidate_id,
            "event": "EXECUTION_PLAN_ATTACHED",
            "process_model": plan["selection"]["process_model"],
        })
        atomic_json(pool_path(run), attach_pool)
    return plan


def command_init(args: argparse.Namespace) -> dict:
    run = args.run.resolve()
    path = pool_path(run)
    if path.exists() and not args.if_missing:
        raise FileExistsError(f"candidate pool already exists: {path}")
    if path.exists():
        return read_object(path)
    if args.min_candidates < 1 or args.max_candidates < args.min_candidates:
        raise ValueError("candidate bounds are invalid")
    if args.min_families < 1 or args.min_families > args.min_candidates:
        raise ValueError("min_families must be between one and min_candidates")
    if args.max_promotions < 1 or args.max_promotions > args.max_candidates:
        raise ValueError("max_promotions must be between one and max_candidates")
    pool = {
        "schema_version": POOL_SCHEMA,
        "status": "ACTIVE",
        "created_at": now(),
        "discovery_started_at": None,
        "policy": {
            "min_candidates": args.min_candidates,
            "max_candidates": args.max_candidates,
            "min_families": args.min_families,
            "max_promotions": args.max_promotions,
            "max_technical_attempts_per_candidate": args.max_technical_attempts,
            "max_candidate_wall_clock_minutes": args.max_candidate_wall_clock_minutes,
            "max_total_wall_clock_minutes": args.max_total_wall_clock_minutes,
            "promotion_threshold_percent": args.promotion_threshold_percent,
            "screening_claim_scope": "DISCOVERY_ONLY_NOT_PRODUCTION_ACCEPTANCE",
        },
        "candidates": [],
        "events": [],
    }
    atomic_json(path, pool)
    return pool


def command_add(args: argparse.Namespace) -> dict:
    run = args.run.resolve()
    pool = load_pool(run)
    spec = read_object(args.spec.resolve())
    validate_spec(run, spec)
    opportunities = load_opportunity_map(run)
    if opportunities.get("status") != "READY":
        raise ValueError("opportunity map must be READY before candidates are registered")
    validate_opportunity_map(opportunities, require_ready=True, run=run)
    opportunity = next(
        (row for row in opportunities.get("opportunities", []) if row.get("opportunity_id") == spec["opportunity_id"]),
        None,
    )
    if opportunity is None:
        raise ValueError(f"unknown opportunity_id: {spec['opportunity_id']}")
    if opportunity.get("status") == "CLOSED":
        raise ValueError(
            "candidate cannot target a CLOSED opportunity; satisfy a recorded "
            "reopen condition and use `kernel_opt.py opportunity reopen` first"
        )
    if spec["family"] not in opportunity.get("rewrite_families", []):
        raise ValueError("candidate family is not allowed by the linked opportunity")
    if float(spec["predicted_global_gain_us"]["upper"]) > float(opportunity["optimistic_gain_ceiling_us"]):
        raise ValueError("candidate prediction exceeds the linked opportunity gain ceiling")
    if any(row.get("candidate_id") == spec["candidate_id"] for row in pool.get("candidates", [])):
        raise ValueError(f"duplicate candidate_id: {spec['candidate_id']}")
    if len(pool.get("candidates", [])) >= int(pool["policy"]["max_candidates"]):
        raise ValueError("candidate pool maximum is reached")
    item = {key: spec[key] for key in (
        "candidate_id", "opportunity_id", "name", "family", "change_axes", "hypothesis",
        "expected_global_effect", "source_paths", "commands", "smoke_result_path",
        "predicted_global_gain_us", "dependency_contract", "execution_plan",
        "persistent_session_specs",
    )}
    item.update({
        "status": "PROPOSED",
        "created_at": now(),
        "development_budget": {
            "max_technical_attempts": int(spec.get("development_budget", {}).get(
                "max_technical_attempts", pool["policy"]["max_technical_attempts_per_candidate"]
            )),
            "max_wall_clock_minutes": float(spec.get("development_budget", {}).get(
                "max_wall_clock_minutes", pool["policy"]["max_candidate_wall_clock_minutes"]
            )),
        },
        "attempts": [],
    })
    if item["development_budget"]["max_technical_attempts"] < 1:
        raise ValueError("max_technical_attempts must be positive")
    if item["development_budget"]["max_wall_clock_minutes"] <= 0:
        raise ValueError("max_wall_clock_minutes must be positive")
    _, plan = validate_execution_plan(
        run, item["execution_plan"], item["candidate_id"]
    )
    if (
        float(plan["estimates"]["selected_seconds"]) / 60.0
        > item["development_budget"]["max_wall_clock_minutes"]
    ):
        raise ValueError("execution plan exceeds the candidate wall-clock budget")
    pool["candidates"].append(item)
    opportunity.setdefault("candidate_ids", []).append(item["candidate_id"])
    opportunity["status"] = "IMPLEMENTING"
    if not pool.get("discovery_started_at"):
        pool["discovery_started_at"] = now()
    pool["events"].append({"at": now(), "candidate_id": item["candidate_id"], "event": "ADDED"})
    atomic_json(pool_path(run), pool)
    atomic_json(opportunity_map_path(run), opportunities)
    return item


def command_run(args: argparse.Namespace) -> dict:
    run = args.run.resolve()
    pool = load_pool(run)
    item = candidate(pool, args.candidate_id)
    if item.get("status") not in ACTIVE_STATUSES:
        raise ValueError(f"candidate {args.candidate_id} is not development-runnable: {item.get('status')}")
    _, plan = validate_execution_plan(
        run, item.get("execution_plan"), item["candidate_id"]
    )
    session_specs = persistent_specs(run, item, plan)
    opportunities = load_opportunity_map(run)
    validate_opportunity_map(opportunities, require_ready=True, run=run)
    opportunity = next(
        (
            row for row in opportunities.get("opportunities", [])
            if row.get("opportunity_id") == item.get("opportunity_id")
        ),
        None,
    )
    if opportunity is None:
        raise ValueError(f"candidate references an unknown opportunity_id: {item.get('opportunity_id')}")
    if opportunity.get("status") == "CLOSED":
        raise ValueError(
            "candidate opportunity was CLOSED after registration; reopen it "
            "explicitly before spending more development budget"
        )
    candidate_execution_minutes = sum(
        float(stage.get("duration_seconds", 0.0))
        for attempt_record in item.get("attempts", [])
        for stage in attempt_record.get("stages", [])
    ) / 60.0
    candidate_wall_used = max(candidate_execution_minutes, elapsed_minutes(item.get("created_at")))
    if candidate_wall_used >= float(item["development_budget"]["max_wall_clock_minutes"]):
        item["status"] = "TECHNICALLY_BLOCKED"
        item["latest_failure"] = {"at": now(), "reason": "CANDIDATE_WALL_CLOCK_BUDGET_EXHAUSTED"}
        atomic_json(pool_path(run), pool)
        raise ValueError("candidate wall-clock budget is exhausted")
    total_execution_minutes = sum(
        float(stage.get("duration_seconds", 0.0))
        for row in pool.get("candidates", [])
        for attempt_record in row.get("attempts", [])
        for stage in attempt_record.get("stages", [])
    ) / 60.0
    total_wall_used = max(total_execution_minutes, elapsed_minutes(pool.get("discovery_started_at")))
    if total_wall_used >= float(pool["policy"]["max_total_wall_clock_minutes"]):
        pool["status"] = "PAUSED"
        pool.setdefault("events", []).append({"at": now(), "event": "TOTAL_WALL_CLOCK_BUDGET_EXHAUSTED"})
        atomic_json(pool_path(run), pool)
        raise ValueError("discovery total wall-clock budget is exhausted")
    candidate_root = run / "candidates" / item["candidate_id"]
    attempts_root = candidate_root / "attempts"
    attempts_root.mkdir(parents=True, exist_ok=True)
    attempt_number = len(item.get("attempts", [])) + 1
    attempt = attempts_root / f"attempt-{attempt_number:02d}"
    attempt.mkdir()
    before = source_identities(run, item)
    smoke_path = run_path(run, item["smoke_result_path"], "smoke_result_path")
    smoke_before = digest(smoke_path) if smoke_path.is_file() else None
    record = {"attempt": attempt_number, "started_at": now(), "source_before": before, "stages": []}
    for stage in ("build", "correctness"):
        stage_result = execute_stage(run, item, attempt, stage)
        record["stages"].append(stage_result)
        if stage_result["exit_code"] != 0:
            record_failure(pool, item, record, f"{stage.upper()}_FAILED")
            atomic_json(attempt / "attempt.json", record)
            atomic_json(pool_path(run), pool)
            return {"candidate_id": item["candidate_id"], "status": item["status"], "reason": record["reason"]}
    receipt_paths = []
    for index, spec_path in enumerate(session_specs, start=1):
        try:
            stage_result, receipt_path = execute_persistent_session_stage(
                run, attempt, spec_path, index
            )
        except ValueError as error:
            record_failure(
                pool, item, record, f"PERSISTENT_SESSION_INVALID: {error}"
            )
            atomic_json(attempt / "attempt.json", record)
            atomic_json(pool_path(run), pool)
            return {
                "candidate_id": item["candidate_id"],
                "status": item["status"],
                "reason": record["reason"],
            }
        record["stages"].append(stage_result)
        if stage_result["exit_code"] != 0:
            record_failure(pool, item, record, "PERSISTENT_SESSION_FAILED")
            atomic_json(attempt / "attempt.json", record)
            atomic_json(pool_path(run), pool)
            return {
                "candidate_id": item["candidate_id"],
                "status": item["status"],
                "reason": record["reason"],
            }
        receipt_paths.append(receipt_path)
    stage_result = execute_stage(
        run,
        item,
        attempt,
        "smoke",
        {
            "KERNEL_OPT_PERSISTENT_RECEIPTS": json.dumps(
                [str(path) for path in receipt_paths]
            )
        },
    )
    record["stages"].append(stage_result)
    if stage_result["exit_code"] != 0:
        record_failure(pool, item, record, "SMOKE_FAILED")
        atomic_json(attempt / "attempt.json", record)
        atomic_json(pool_path(run), pool)
        return {
            "candidate_id": item["candidate_id"],
            "status": item["status"],
            "reason": record["reason"],
        }
    persistent_specs(run, item, plan)
    after = source_identities(run, item)
    record["source_after"] = after
    if before != after:
        record_failure(pool, item, record, "SOURCE_MUTATED_DURING_EVALUATION")
        atomic_json(attempt / "attempt.json", record)
        atomic_json(pool_path(run), pool)
        return {"candidate_id": item["candidate_id"], "status": item["status"], "reason": record["reason"]}
    smoke_path = run_path(run, item["smoke_result_path"], "smoke_result_path", must_exist=True)
    if smoke_before is not None and digest(smoke_path) == smoke_before:
        record_failure(pool, item, record, "STALE_SMOKE_RESULT")
        atomic_json(attempt / "attempt.json", record)
        atomic_json(pool_path(run), pool)
        return {"candidate_id": item["candidate_id"], "status": item["status"], "reason": record["reason"]}
    try:
        smoke, improvement = validate_smoke_result(run, smoke_path, item)
    except ValueError as error:
        record_failure(pool, item, record, f"INVALID_SMOKE_RESULT: {error}")
        atomic_json(attempt / "attempt.json", record)
        atomic_json(pool_path(run), pool)
        return {"candidate_id": item["candidate_id"], "status": item["status"], "reason": record["reason"]}
    record.update({
        "status": "VALID_SCREEN",
        "completed_at": now(),
        "improvement_percent": improvement,
        "smoke_result": {"path": smoke_path.relative_to(run).as_posix(), "sha256": digest(smoke_path)},
    })
    item.setdefault("attempts", []).append(record)
    threshold = float(pool["policy"]["promotion_threshold_percent"])
    item["screening"] = {
        "status": "PASS" if improvement >= threshold else "BELOW_THRESHOLD",
        "improvement_percent": improvement,
        "threshold_percent": threshold,
        "result": record["smoke_result"],
        "objective": smoke["objective"],
    }
    prediction = item["predicted_global_gain_us"]
    predicted_midpoint = (float(prediction["lower"]) + float(prediction["upper"])) / 2.0
    observed_gain_us = None
    if smoke["objective"].get("unit") in {"us", "us_weighted"}:
        baseline = float(smoke["objective"]["baseline"])
        observed = float(smoke["objective"]["candidate"])
        observed_gain_us = baseline - observed if smoke["objective"]["direction"] == "minimize" else observed - baseline
    item["prediction_check"] = {
        "predicted_midpoint_us": predicted_midpoint,
        "observed_global_gain_us": observed_gain_us,
        "residual_us": None if observed_gain_us is None else observed_gain_us - predicted_midpoint,
        "claim_scope": "DISCOVERY_ONLY",
    }
    item["status"] = "QUALIFICATION_READY" if improvement >= threshold else "SCREENED_OUT"
    pool["events"].append({
        "at": now(), "candidate_id": item["candidate_id"], "event": item["status"],
        "improvement_percent": improvement,
    })
    atomic_json(attempt / "attempt.json", record)
    atomic_json(pool_path(run), pool)
    opportunity.setdefault("observations", []).append({
        "at": now(), "candidate_id": item["candidate_id"], **item["prediction_check"],
    })
    opportunity["status"] = "HAS_SURVIVOR" if item["status"] == "QUALIFICATION_READY" else "OBSERVED"
    atomic_json(opportunity_map_path(run), opportunities)
    return {"candidate_id": item["candidate_id"], "status": item["status"], "improvement_percent": improvement}


def command_promote(args: argparse.Namespace) -> dict:
    run = args.run.resolve()
    pool = load_pool(run)
    item = candidate(pool, args.candidate_id)
    if item.get("status") != "QUALIFICATION_READY":
        raise ValueError("only a QUALIFICATION_READY candidate can be promoted")
    policy = pool["policy"]
    families = {row.get("family") for row in pool.get("candidates", []) if row.get("family")}
    opportunities = load_opportunity_map(run)
    validate_opportunity_map(opportunities, require_ready=True, run=run)
    covered_opportunities = {
        row.get("opportunity_id")
        for row in pool.get("candidates", [])
        if row.get("opportunity_id")
    }
    if len(pool.get("candidates", [])) < int(policy["min_candidates"]):
        raise ValueError("candidate portfolio is smaller than min_candidates")
    if len(families) < int(policy["min_families"]):
        raise ValueError("candidate portfolio lacks the required architecture-family diversity")
    if len(covered_opportunities) < int(opportunities["policy"]["min_candidate_opportunities"]):
        raise ValueError("candidate portfolio lacks the required opportunity diversity")
    unevaluated = [
        row.get("candidate_id")
        for row in pool.get("candidates", [])
        if row.get("status") in ACTIVE_STATUSES
    ]
    if unevaluated:
        raise ValueError(f"all registered candidates must finish discovery screening before promotion: {unevaluated}")
    promoted_count = sum(row.get("status") == "PROMOTED_TO_QUALIFICATION" for row in pool.get("candidates", []))
    if promoted_count >= int(policy.get("max_promotions", 2)):
        raise ValueError("discovery promotion limit is reached")
    promotion = {
        "schema_version": "discovery-promotion-v1",
        "candidate_id": item["candidate_id"],
        "opportunity_id": item["opportunity_id"],
        "promoted_at": now(),
        "status": "QUALIFICATION_CONTRACT_REQUIRED",
        "family": item["family"],
        "change_axes": item["change_axes"],
        "hypothesis": item["hypothesis"],
        "expected_global_effect": item["expected_global_effect"],
        "source_identities": source_identities(run, item),
        "execution_plan": item["execution_plan"],
        "screening": item["screening"],
        "reachability": read_object(
            run_path(run, item["screening"]["result"]["path"], "screening result", must_exist=True)
        )["reachability"],
        "prediction_check": item["prediction_check"],
        "claims_allowed": ["candidate survived discovery screening and may enter supervised qualification"],
        "claims_forbidden": ["production acceptance", "SOTA", "theoretical limit", "portable hardware fact"],
    }
    path = run / "models" / "discovery_promotions" / f"{item['candidate_id']}.json"
    atomic_json(path, promotion)
    item["status"] = "PROMOTED_TO_QUALIFICATION"
    item["promotion"] = {"path": path.relative_to(run).as_posix(), "sha256": digest(path)}
    pool["events"].append({"at": now(), "candidate_id": item["candidate_id"], "event": item["status"]})
    atomic_json(pool_path(run), pool)
    return {"candidate_id": item["candidate_id"], "status": item["status"], "promotion": item["promotion"]}


def command_status(args: argparse.Namespace) -> dict:
    pool = load_pool(args.run.resolve())
    candidates = pool.get("candidates", [])
    return {
        "status": pool.get("status"),
        "candidate_count": len(candidates),
        "family_count": len({item.get("family") for item in candidates if item.get("family")}),
        "candidates": [
            {
                "candidate_id": item.get("candidate_id"),
                "opportunity_id": item.get("opportunity_id"),
                "family": item.get("family"),
                "status": item.get("status"),
                "attempts": len(item.get("attempts", [])),
                "improvement_percent": item.get("screening", {}).get("improvement_percent"),
                "process_model": (
                    validate_execution_plan(
                        args.run.resolve(), item["execution_plan"], item["candidate_id"]
                    )[1]["selection"]["process_model"]
                    if item.get("execution_plan")
                    else "LEGACY_UNPLANNED"
                ),
            }
            for item in candidates
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="operation", required=True)
    init = subparsers.add_parser("init", help="initialize a discovery candidate pool")
    init.add_argument("--run", type=Path, required=True)
    init.add_argument("--min-candidates", type=int, default=6)
    init.add_argument("--max-candidates", type=int, default=12)
    init.add_argument("--min-families", type=int, default=4)
    init.add_argument("--max-promotions", type=int, default=2)
    init.add_argument("--max-technical-attempts", type=int, default=8)
    init.add_argument("--max-candidate-wall-clock-minutes", type=float, default=20.0)
    init.add_argument("--max-total-wall-clock-minutes", type=float, default=120.0)
    init.add_argument("--promotion-threshold-percent", type=float, default=1.0)
    init.add_argument("--if-missing", action="store_true")
    plan = subparsers.add_parser(
        "plan-execution", help="select a phase-aware candidate process model"
    )
    plan.add_argument("--run", type=Path, required=True)
    plan.add_argument("--candidate-id", required=True)
    plan.add_argument("--phase-timing", required=True)
    plan.add_argument("--output", required=True)
    plan.add_argument("--arm-count", type=int, default=2)
    plan.add_argument("--requests-per-arm", type=int, default=3)
    plan.add_argument("--fixed-share-threshold", type=float, default=0.5)
    plan.add_argument("--shared-switching-receipt")
    plan.add_argument(
        "--attach",
        action="store_true",
        help="attach the immutable plan to an existing active legacy candidate",
    )
    plan.add_argument(
        "--persistent-session-spec",
        action="append",
        default=[],
        help="run-relative session spec to attach; repeat once per planned session",
    )
    add = subparsers.add_parser("add", help="register one run-local production candidate")
    add.add_argument("--run", type=Path, required=True)
    add.add_argument("--spec", type=Path, required=True)
    execute = subparsers.add_parser("run", help="build, check and cheaply screen one candidate")
    execute.add_argument("--run", type=Path, required=True)
    execute.add_argument("--candidate-id", required=True)
    promote = subparsers.add_parser("promote", help="promote a discovery survivor to strict qualification")
    promote.add_argument("--run", type=Path, required=True)
    promote.add_argument("--candidate-id", required=True)
    status = subparsers.add_parser("status", help="summarize the candidate portfolio")
    status.add_argument("--run", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    handlers = {
        "init": command_init,
        "plan-execution": command_plan_execution,
        "add": command_add,
        "run": command_run,
        "promote": command_promote,
        "status": command_status,
    }
    try:
        result = handlers[args.operation](args)
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
