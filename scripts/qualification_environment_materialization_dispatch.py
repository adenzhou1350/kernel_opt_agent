#!/usr/bin/env python3
"""Consume one CPU-only materialization approval and run its sealed argv once."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from qualification_environment_materialization import (
    identity,
    parse_time,
    read_object,
    sha256_file,
    validate_approval,
    validate_identity,
    validate_plan_bundle,
)
from schema_utils import validate_instance


APPROVAL_VERSION = "qualification-environment-materialization-approval-v2"
CLAIM_SCHEMA = "qualification_environment_materialization_claim.schema.json"
RECEIPT_SCHEMA = (
    "qualification_environment_materialization_dispatch_receipt_v2.schema.json"
)
CLAIM_BOUNDARY = (
    "ATOMIC_SINGLE_USE_CPU_ONLY_MATERIALIZATION_CLAIM_NOT_ENVIRONMENT_SUCCESS_"
    "GPU_OR_WORKLOAD_AUTHORIZATION"
)
RECEIPT_BOUNDARY = (
    "EXECUTOR_PROCESS_TERMINAL_STATUS_ONLY_NOT_ENVIRONMENT_CORRECTNESS_"
    "PERFORMANCE_GPU_OR_WORKLOAD_EVIDENCE"
)
FORBIDDEN_TOP_LEVEL_EXECUTABLES = {
    "docker",
    "enroot",
    "nerdctl",
    "podman",
    "scp",
    "ssh",
    "systemctl",
}


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def self_identified(value: dict, field: str) -> dict:
    result = dict(value)
    result[field] = canonical_sha256(value)
    return result


def validate_generated(value: dict, schema_name: str) -> None:
    schema = read_object(repository_root() / "schemas" / schema_name)
    errors = validate_instance(value, schema)
    if errors:
        raise ValueError("invalid generated dispatch artifact: " + "; ".join(errors))


def atomic_publish_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary_name, path)
    except BaseException:
        raise
    finally:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass


def claims_root(artifact_root: Path) -> Path:
    root = artifact_root.resolve()
    path = (root / ".kernel-opt" / "materialization-claims").resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise ValueError("materialization claim path escapes artifact root") from error
    return path


def executor_identity(plan: dict) -> dict:
    candidates = (
        plan.get("executor"),
        plan.get("bound_inputs", {}).get("materialization_executor"),
    )
    for candidate in candidates:
        if (
            isinstance(candidate, dict)
            and isinstance(candidate.get("path"), str)
            and isinstance(candidate.get("sha256"), str)
        ):
            return {"path": candidate["path"], "sha256": candidate["sha256"]}
    raise ValueError("materialization plan has no hash-bound executor identity")


def planned_wall_seconds(plan: dict, approved_max: int) -> int:
    budget = plan.get("budget", {})
    candidates = (
        budget.get("external_hard_timeout_seconds"),
        budget.get("cpu_only_materialization_max_wall_seconds"),
        budget.get("executor_hard_timeout_seconds"),
    )
    value = next(
        (candidate for candidate in candidates if isinstance(candidate, int)),
        approved_max,
    )
    if value < 1 or value > approved_max:
        raise ValueError("plan wall budget exceeds materialization approval")
    return value


def sealed_argv(plan: dict, executor_path: Path) -> list[str]:
    steps = plan.get("materialization_steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError("dispatcher requires materialization steps")
    executable_steps = [
        step
        for step in steps
        if isinstance(step, dict) and step.get("argv") is not None
    ]
    if len(executable_steps) != 1:
        raise ValueError(
            "dispatcher requires exactly one executable materialization step"
        )
    step = executable_steps[0]
    argv = step.get("argv")
    if (
        step.get("gpu") is not False
        or not isinstance(argv, list)
        or not argv
        or not all(isinstance(token, str) and token for token in argv)
    ):
        raise ValueError("materialization step must contain a CPU-only argv list")
    executable = Path(argv[0]).name.lower()
    if executable in FORBIDDEN_TOP_LEVEL_EXECUTABLES:
        raise ValueError(
            f"forbidden top-level materialization executable: {executable}"
        )
    resolved_tokens = {
        Path(token).resolve() for token in argv if Path(token).is_absolute()
    }
    if executor_path.resolve() not in resolved_tokens:
        raise ValueError("sealed argv does not invoke the hash-bound executor")
    return argv


def stream_identity(payload: bytes) -> dict:
    return {"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}


def dispatch(
    *,
    artifact_root: Path,
    approval_path: Path,
    expected_approval_sha256: str,
    now: datetime | None = None,
) -> dict:
    artifact_root = artifact_root.resolve(strict=True)
    approval_path = approval_path.resolve(strict=True)
    approval_identity = identity(approval_path, artifact_root)
    if approval_identity["sha256"] != expected_approval_sha256:
        raise ValueError("materialization approval hash differs from controller input")
    approval = read_object(approval_path)
    if approval.get("schema_version") != APPROVAL_VERSION:
        raise ValueError(
            "only dispatcher-bound materialization approval v2 is executable"
        )
    current_dispatcher_sha256 = sha256_file(Path(__file__).resolve())
    if approval.get("dispatcher_sha256") != current_dispatcher_sha256:
        raise ValueError("materialization approval binds a different dispatcher")

    claimed_at = (now or datetime.now(UTC)).astimezone(UTC)
    validation = validate_approval(approval_path, artifact_root, now=claimed_at)
    if not validation["dispatcher_bound"] or not validation["single_use"]:
        raise ValueError("materialization approval is not dispatcher-bound single-use")
    plan_path = validate_identity(
        artifact_root, approval["materialization_plan"], "materialization plan"
    )
    request_path = validate_identity(
        artifact_root, approval["environment_request"], "environment request"
    )
    job_path = validate_identity(
        artifact_root, approval["resource_job"], "resource job"
    )
    plan, _, _ = validate_plan_bundle(plan_path, request_path, job_path, artifact_root)
    executor = executor_identity(plan)
    executor_path = validate_identity(
        artifact_root, executor, "materialization executor"
    )
    argv = sealed_argv(plan, executor_path)
    timeout_seconds = planned_wall_seconds(
        plan, approval["approved_budget"]["max_wall_seconds"]
    )
    expires_at = parse_time(approval["expires_at"])
    if claimed_at + timedelta(seconds=timeout_seconds) >= expires_at:
        raise ValueError("approval expires before the sealed materialization deadline")

    claim_dir = claims_root(artifact_root)
    claim_path = claim_dir / f"{approval_identity['sha256']}.claim.json"
    receipt_path = claim_dir / f"{approval_identity['sha256']}.receipt.json"
    if receipt_path.exists():
        raise FileExistsError("materialization approval already has a terminal receipt")
    claim = self_identified(
        {
            "schema_version": "qualification-environment-materialization-claim-v1",
            "claimed_at": timestamp(claimed_at),
            "approval": approval_identity,
            "materialization_plan": identity(plan_path, artifact_root),
            "dispatcher_sha256": current_dispatcher_sha256,
            "argv_sha256": canonical_sha256(argv),
            "single_use": True,
            "claim_boundary": CLAIM_BOUNDARY,
        },
        "claim_id",
    )
    validate_generated(claim, CLAIM_SCHEMA)
    try:
        atomic_publish_json(claim_path, claim)
    except FileExistsError as error:
        raise FileExistsError("materialization approval was already claimed") from error

    environment = os.environ.copy()
    environment["CUDA_VISIBLE_DEVICES"] = "-1"
    environment["NVIDIA_VISIBLE_DEVICES"] = "void"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    process_started_at = datetime.now(UTC)
    monotonic_started = time.monotonic()
    timed_out = False
    exit_code: int | None
    try:
        completed = subprocess.run(
            argv,
            cwd=artifact_root,
            env=environment,
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
            start_new_session=os.name != "nt",
        )
        exit_code = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
        state = "EXECUTOR_COMPLETED" if exit_code == 0 else "EXECUTOR_FAILED"
    except subprocess.TimeoutExpired as error:
        timed_out = True
        exit_code = None
        stdout = error.stdout or b""
        stderr = error.stderr or b""
        state = "EXECUTOR_TIMED_OUT"

    process_completed_at = datetime.now(UTC)
    duration_seconds = max(0.0, time.monotonic() - monotonic_started)
    receipt = self_identified(
        {
            "schema_version": (
                "qualification-environment-materialization-dispatch-receipt-v2"
            ),
            "started_at": timestamp(process_started_at),
            "completed_at": timestamp(process_completed_at),
            "duration_seconds": duration_seconds,
            "claim": identity(claim_path, artifact_root),
            "state": state,
            "exit_code": exit_code,
            "timed_out": timed_out,
            "stdout": stream_identity(stdout),
            "stderr": stream_identity(stderr),
            "gpu_authorized": False,
            "workload_authorized": False,
            "broker_mutated": False,
            "claim_boundary": RECEIPT_BOUNDARY,
        },
        "receipt_id",
    )
    validate_generated(receipt, RECEIPT_SCHEMA)
    atomic_publish_json(receipt_path, receipt)
    return {**receipt, "receipt_path": receipt_path.as_posix()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", required=True, type=Path)
    parser.add_argument("--approval", required=True, type=Path)
    parser.add_argument("--approval-sha256", required=True)
    args = parser.parse_args()
    result = dispatch(
        artifact_root=args.artifact_root,
        approval_path=args.approval,
        expected_approval_sha256=args.approval_sha256,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["state"] == "EXECUTOR_COMPLETED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
