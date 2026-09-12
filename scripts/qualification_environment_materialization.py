#!/usr/bin/env python3
"""Issue or validate a CPU-only qualification-environment materialization approval."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from schema_utils import validate_instance, validate_json_file


APPROVAL_SCHEMA_V1 = "qualification_environment_materialization_approval.schema.json"
APPROVAL_SCHEMA_V2 = "qualification_environment_materialization_approval_v2.schema.json"
REQUEST_SCHEMA = "qualification_environment_request.schema.json"
JOB_SCHEMA = "resource_broker_job.schema.json"
APPROVAL_VERSION_V1 = "qualification-environment-materialization-approval-v1"
APPROVAL_VERSION_V2 = "qualification-environment-materialization-approval-v2"
CLAIM_BOUNDARY = (
    "CPU_ONLY_ENVIRONMENT_MATERIALIZATION_NOT_GPU_OR_WORKLOAD_AUTHORIZATION"
)


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def dispatcher_path() -> Path:
    return Path(__file__).with_name(
        "qualification_environment_materialization_dispatch.py"
    )


def read_object(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, value: dict) -> None:
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
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def parse_time(value: str) -> datetime:
    observed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if observed.tzinfo is None:
        raise ValueError("materialization approval times must include a timezone")
    return observed.astimezone(UTC)


def resolve_inside(root: Path, relative: str) -> Path:
    root = root.resolve()
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise ValueError(f"identity path escapes artifact root: {relative}") from error
    return path


def identity(path: Path, artifact_root: Path) -> dict:
    path = path.resolve()
    try:
        relative = path.relative_to(artifact_root.resolve()).as_posix()
    except ValueError as error:
        raise ValueError(f"artifact is outside artifact root: {path}") from error
    return {"path": relative, "sha256": sha256_file(path)}


def validate_identity(artifact_root: Path, value: dict, label: str) -> Path:
    path = resolve_inside(artifact_root, value["path"])
    if not path.is_file():
        raise FileNotFoundError(f"{label} is missing: {path}")
    if sha256_file(path) != value["sha256"]:
        raise ValueError(f"{label} hash changed: {value['path']}")
    return path


def validate_schema(path: Path, schema_name: str, label: str) -> dict:
    errors = validate_json_file(path, repository_root() / "schemas" / schema_name)
    if errors:
        raise ValueError(f"invalid {label}: " + "; ".join(errors))
    return read_object(path)


def same_identity(left: dict, right: dict) -> bool:
    return left.get("path") == right.get("path") and left.get("sha256") == right.get(
        "sha256"
    )


def validate_required_toolchain(runtime_worker: dict, attestation_path: Path) -> None:
    required = runtime_worker.get("required_toolchain")
    if required is None:
        return
    if not isinstance(required, dict) or not required:
        raise ValueError("required worker toolchain must be a non-empty object")
    attestation = read_object(attestation_path)
    if attestation.get("worker_id") != runtime_worker.get("worker_id"):
        raise ValueError("worker attestation worker_id differs from plan")
    expected_host = runtime_worker.get("host_id")
    if expected_host is not None and attestation.get("host_id") != expected_host:
        raise ValueError("worker attestation host_id differs from plan")
    observed = attestation.get("runtime", {}).get("toolchain")
    if not isinstance(observed, dict):
        raise ValueError("worker attestation has no toolchain identities")
    for name, expected in sorted(required.items()):
        if not isinstance(name, str) or not name:
            raise ValueError("required worker tool name must be non-empty")
        if not isinstance(expected, dict):
            raise ValueError(f"required worker tool identity is invalid: {name}")
        actual = observed.get(name)
        if actual is None:
            raise ValueError(f"required worker tool is unavailable: {name}")
        if actual != expected:
            raise ValueError(f"required worker tool identity differs: {name}")


def validate_plan_bundle(
    plan_path: Path,
    request_path: Path,
    job_path: Path,
    artifact_root: Path,
) -> tuple[dict, dict, dict]:
    plan = read_object(plan_path)
    request = validate_schema(request_path, REQUEST_SCHEMA, "environment request")
    job = validate_schema(job_path, JOB_SCHEMA, "resource job")
    if plan.get("state") != "READY_FOR_SUPERVISOR_REVIEW_NOT_EXECUTED":
        raise ValueError("materialization plan is not ready for supervisor review")
    authorization = plan.get("authorization")
    if not isinstance(authorization, dict):
        raise ValueError("materialization plan authorization boundary is missing")
    required_false = (
        "new_job_submission_authorized",
        "cpu_only_materialization_authorized",
    )
    required_true = (
        "forbid_direct_ssh",
        "forbid_broker_bind_gate",
        "forbid_broker_acquire",
        "forbid_gpu_device_mount",
        "forbid_workload_launch",
    )
    if any(authorization.get(field) is not False for field in required_false):
        raise ValueError("materialization plan already claims external authorization")
    if any(authorization.get(field) is not True for field in required_true):
        raise ValueError("materialization plan does not preserve the CPU-only boundary")
    steps = plan.get("materialization_steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError("materialization plan has no bounded steps")
    if any(
        not isinstance(step, dict) or step.get("gpu") is not False for step in steps
    ):
        raise ValueError("every materialization step must explicitly set gpu=false")

    bound = plan.get("bound_inputs", {})
    plan_request = bound.get("superseding_environment_request")
    plan_job = bound.get("superseding_resource_job")
    if not isinstance(plan_request, dict) or not isinstance(plan_job, dict):
        raise ValueError(
            "materialization plan does not bind request and job identities"
        )
    if not same_identity(plan_request, identity(request_path, artifact_root)):
        raise ValueError("materialization plan environment request identity differs")
    if not same_identity(plan_job, identity(job_path, artifact_root)):
        raise ValueError("materialization plan resource job identity differs")
    if job["environment_request"] != request:
        raise ValueError("resource job embeds a different environment request")
    if job["dispatch_gate"] != {"state": "BLOCKED", "identity_sha256": None}:
        raise ValueError("environment materialization requires a blocked resource job")

    if (
        plan.get("source", {}).get("git_tree")
        != request["candidate_source"]["tree_sha"]
    ):
        raise ValueError("plan Git tree differs from environment request")
    request_runtime = request["execution"].get("runtime_provenance")
    if request_runtime and request_runtime["kind"] == "ATTESTED_PREPROVISIONED_WORKER":
        runtime_worker = plan.get("runtime_worker")
        if not isinstance(runtime_worker, dict):
            raise ValueError("preprovisioned worker plan is missing runtime_worker")
        if runtime_worker.get("worker_id") != request_runtime["worker_id"]:
            raise ValueError("plan worker differs from environment request")
        attestation = runtime_worker.get("attestation")
        if not isinstance(attestation, dict):
            raise ValueError("preprovisioned worker plan is missing attestation")
        attestation_path = validate_identity(
            artifact_root,
            attestation,
            "preprovisioned worker attestation",
        )
        if attestation["sha256"] != request_runtime["identity_sha256"]:
            raise ValueError("plan worker attestation differs from environment request")
        validate_required_toolchain(runtime_worker, attestation_path)
        if request["execution"]["image_digest"] is not None:
            raise ValueError(
                "preprovisioned worker request must not bind an image digest"
            )
    elif (
        plan.get("runtime_image", {}).get("platform_manifest_digest")
        != request["execution"]["image_digest"]
    ):
        raise ValueError("plan image digest differs from environment request")
    locks = plan.get("dependency_and_toolchain", {})
    expected = {
        "dependency_lock": "dependency_lock_sha256",
        "toolchain_lock": "toolchain_lock_sha256",
    }
    for plan_key, request_key in expected.items():
        if locks.get(plan_key, {}).get("sha256") != request["execution"][request_key]:
            raise ValueError(f"plan {plan_key} differs from environment request")
    if (
        bound.get("workflow", {}).get("sha256")
        != request["execution"]["workflow_sha256"]
    ):
        raise ValueError("plan workflow differs from environment request")
    if (
        bound.get("test_contract", {}).get("sha256")
        != request["execution"]["test_contract_sha256"]
    ):
        raise ValueError("plan test contract differs from environment request")
    return plan, request, job


def issue_approval(
    *,
    plan_path: Path,
    request_path: Path,
    job_path: Path,
    artifact_root: Path,
    supervisor_id: str,
    approval_id: str,
    issued_at: datetime,
    expires_at: datetime,
    max_wall_seconds: int,
    network_policy: str,
    dispatcher_bound: bool = False,
) -> dict:
    validate_plan_bundle(plan_path, request_path, job_path, artifact_root)
    if expires_at <= issued_at:
        raise ValueError("materialization approval expiry must follow issuance")
    if max_wall_seconds <= 0:
        raise ValueError("materialization approval budget must be positive")
    approval = {
        "schema_version": (
            APPROVAL_VERSION_V2 if dispatcher_bound else APPROVAL_VERSION_V1
        ),
        "approval_id": approval_id,
        "issued_at": issued_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "expires_at": expires_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "issued_by": {
            "role": "GLOBAL_SUPERVISOR",
            "supervisor_id": supervisor_id,
        },
        "action": "CPU_ONLY_ENVIRONMENT_MATERIALIZATION",
        "materialization_plan": identity(plan_path, artifact_root),
        "environment_request": identity(request_path, artifact_root),
        "resource_job": identity(job_path, artifact_root),
        "approved_budget": {"max_wall_seconds": max_wall_seconds},
        "network_policy": network_policy,
        "constraints": {
            "gpu_device_mount": False,
            "gpu_workload": False,
            "workload_launch": False,
            "service_mutation": False,
            "broker_submit": False,
            "broker_bind_gate": False,
            "broker_acquire": False,
        },
        "decision": "APPROVED",
        "claim_boundary": CLAIM_BOUNDARY,
    }
    if dispatcher_bound:
        approval["dispatcher_sha256"] = sha256_file(dispatcher_path())
        approval["single_use"] = True
    schema_name = APPROVAL_SCHEMA_V2 if dispatcher_bound else APPROVAL_SCHEMA_V1
    schema = read_object(repository_root() / "schemas" / schema_name)
    errors = validate_instance(approval, schema)
    if errors:
        raise ValueError(
            "invalid generated materialization approval: " + "; ".join(errors)
        )
    return approval


def validate_approval(
    approval_path: Path, artifact_root: Path, *, now: datetime | None = None
) -> dict:
    unvalidated = read_object(approval_path)
    version = unvalidated.get("schema_version")
    if version == APPROVAL_VERSION_V1:
        schema_name = APPROVAL_SCHEMA_V1
    elif version == APPROVAL_VERSION_V2:
        schema_name = APPROVAL_SCHEMA_V2
    else:
        raise ValueError(f"unsupported materialization approval version: {version}")
    approval = validate_schema(
        approval_path, schema_name, "environment materialization approval"
    )
    plan_path = validate_identity(
        artifact_root, approval["materialization_plan"], "materialization plan"
    )
    request_path = validate_identity(
        artifact_root, approval["environment_request"], "environment request"
    )
    job_path = validate_identity(
        artifact_root, approval["resource_job"], "resource job"
    )
    validate_plan_bundle(plan_path, request_path, job_path, artifact_root)
    issued_at = parse_time(approval["issued_at"])
    expires_at = parse_time(approval["expires_at"])
    observed = (now or datetime.now(UTC)).astimezone(UTC)
    if expires_at <= issued_at:
        raise ValueError("materialization approval expiry must follow issuance")
    if observed < issued_at or observed >= expires_at:
        raise ValueError("materialization approval is not currently valid")
    return {
        "status": "PASS",
        "state": "CPU_ONLY_ENVIRONMENT_MATERIALIZATION_AUTHORIZED",
        "approval_id": approval["approval_id"],
        "expires_at": approval["expires_at"],
        "gpu_authorized": False,
        "workload_authorized": False,
        "broker_submission_authorized": False,
        "dispatcher_bound": version == APPROVAL_VERSION_V2,
        "single_use": approval.get("single_use") is True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--issue", action="store_true")
    mode.add_argument("--approval", type=Path)
    parser.add_argument("--artifact-root", required=True, type=Path)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--request", type=Path)
    parser.add_argument("--job", type=Path)
    parser.add_argument("--supervisor-id")
    parser.add_argument("--approval-id")
    parser.add_argument("--ttl-seconds", type=int, default=3600)
    parser.add_argument("--max-wall-seconds", type=int)
    parser.add_argument(
        "--dispatcher-bound",
        action="store_true",
        help="issue a v2 approval bound to the single-use worker dispatcher",
    )
    parser.add_argument(
        "--network-policy",
        choices=("NONE", "DEPENDENCY_MATERIALIZATION_ONLY"),
        default="DEPENDENCY_MATERIALIZATION_ONLY",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    artifact_root = args.artifact_root.resolve()
    if args.issue:
        required = {
            "--plan": args.plan,
            "--request": args.request,
            "--job": args.job,
            "--supervisor-id": args.supervisor_id,
            "--approval-id": args.approval_id,
            "--max-wall-seconds": args.max_wall_seconds,
            "--output": args.output,
        }
        missing = [label for label, value in required.items() if value is None]
        if missing:
            parser.error("--issue requires " + ", ".join(missing))
        issued_at = datetime.now(UTC)
        approval = issue_approval(
            plan_path=args.plan.resolve(),
            request_path=args.request.resolve(),
            job_path=args.job.resolve(),
            artifact_root=artifact_root,
            supervisor_id=args.supervisor_id,
            approval_id=args.approval_id,
            issued_at=issued_at,
            expires_at=issued_at + timedelta(seconds=args.ttl_seconds),
            max_wall_seconds=args.max_wall_seconds,
            network_policy=args.network_policy,
            dispatcher_bound=args.dispatcher_bound,
        )
        atomic_json(args.output.resolve(), approval)
        result = validate_approval(args.output.resolve(), artifact_root, now=issued_at)
    else:
        if any(value is not None for value in (args.plan, args.request, args.job)):
            parser.error("validation reads plan, request and job from the approval")
        result = validate_approval(args.approval.resolve(), artifact_root)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
