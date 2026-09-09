#!/usr/bin/env python3
"""Validate store-bound P-and-E-and-A readiness for atomic consumption."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from community_claim_contracts import (
    authorization_schedule,
    digest,
)
from community_claim_store_deployment import validate_deployment
from community_execution_readiness import (
    validate_execution_readiness as validate_canonical_execution_readiness,
)
from community_pre_gpu_readiness import (
    validate_readiness as validate_canonical_pre_gpu_readiness,
)
from community_semantic_approval import validate_approval as validate_semantic_approval
from schema_utils import validate_json_file

AUTHORIZATION_SCHEMA = "community_combined_execution_authorization_v2.schema.json"
REQUEST_SCHEMA = "community_execution_authorization_request_v2.schema.json"
APPROVAL_SCHEMA = "community_semantic_supervisor_approval.schema.json"
DEPLOYMENT_SCHEMA = "community_claim_store_deployment.schema.json"
VALIDATOR_PATH = "scripts/community_execution_authorization_v2.py"
SEMANTIC_VALIDATOR_PATH = "scripts/community_semantic_approval.py"
DEPLOYMENT_VALIDATOR_PATH = "scripts/community_claim_store_deployment.py"
PRE_GPU_VALIDATOR_PATH = "scripts/community_pre_gpu_readiness.py"
EXECUTION_VALIDATOR_PATH = "scripts/community_execution_readiness.py"
CLAIM_CONTRACTS_PATH = "scripts/community_claim_contracts.py"
ATOMIC_CLAIM_PATH = "scripts/community_atomic_claim.py"


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def read_object(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected one JSON object: {path}")
    return value


def sha256_file(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


def resolve_inside(base: Path, relative: str) -> Path:
    base = base.resolve()
    path = (base / relative).resolve()
    try:
        path.relative_to(base)
    except ValueError as error:
        raise ValueError(f"identity path escapes artifact root: {relative}") from error
    return path


def validate_identity(base: Path, identity: dict, label: str) -> Path:
    path = resolve_inside(base, identity["path"])
    if not path.is_file():
        raise FileNotFoundError(f"{label} is missing: {path}")
    if sha256_file(path) != identity["sha256"]:
        raise ValueError(f"{label} hash changed: {identity['path']}")
    return path


def validate_schema(path: Path, schema: str, label: str) -> dict:
    errors = validate_json_file(path, repository_root() / "schemas" / schema)
    if errors:
        raise ValueError(f"invalid {label}: " + "; ".join(errors))
    return read_object(path)


def same_identity(left: dict | None, right: dict | None) -> bool:
    if left is None or right is None:
        return left is right
    return left.get("path") == right.get("path") and left.get("sha256") == right.get(
        "sha256"
    )


def require_self_id(value: dict, field: str, label: str) -> None:
    unsigned = {key: item for key, item in value.items() if key != field}
    if value[field] != digest(unsigned):
        raise ValueError(f"{label} self identity changed")


def require_commit(commit: str) -> None:
    result = subprocess.run(
        ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
        cwd=repository_root(),
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise ValueError("combined authorization v2 commit is unavailable")


def git_blob_sha256(commit: str, relative_path: str) -> str:
    result = subprocess.run(
        ["git", "show", f"{commit}:{relative_path}"],
        cwd=repository_root(),
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise ValueError(
            f"combined authorization v2 blob is unavailable: {relative_path}"
        )
    return hashlib.sha256(result.stdout).hexdigest()


def validate_validator_binding(binding: dict) -> None:
    require_commit(binding["repository_commit"])
    paths = {
        "authorization_schema_sha256": f"schemas/{AUTHORIZATION_SCHEMA}",
        "request_schema_sha256": f"schemas/{REQUEST_SCHEMA}",
        "approval_schema_sha256": f"schemas/{APPROVAL_SCHEMA}",
        "deployment_schema_sha256": f"schemas/{DEPLOYMENT_SCHEMA}",
        "validator_sha256": VALIDATOR_PATH,
        "semantic_validator_sha256": SEMANTIC_VALIDATOR_PATH,
        "deployment_validator_sha256": DEPLOYMENT_VALIDATOR_PATH,
        "pre_gpu_validator_sha256": PRE_GPU_VALIDATOR_PATH,
        "execution_validator_sha256": EXECUTION_VALIDATOR_PATH,
        "claim_contracts_sha256": CLAIM_CONTRACTS_PATH,
        "atomic_claim_sha256": ATOMIC_CLAIM_PATH,
    }
    root = repository_root()
    for field, relative in paths.items():
        if binding[field] != git_blob_sha256(binding["repository_commit"], relative):
            raise ValueError(f"declared commit binding changed: {field}")
        if binding[field] != sha256_file(root / relative):
            raise ValueError(f"worktree binding changed: {field}")


def invocation_argv(
    sealed_path: Path, schedule_entry: dict, stable_task_id: str
) -> list[str]:
    sealed = json.loads(sealed_path.read_text(encoding="utf-8"))
    if isinstance(sealed, list):
        argv = sealed
    elif isinstance(sealed, dict):
        if sealed.get("task_id") != stable_task_id:
            raise ValueError("sealed argv task identity differs from request")
        rows = [
            row
            for row in sealed.get("invocations", [])
            if row.get("order_index") == schedule_entry["order_index"]
            and row.get("repeat_index") == schedule_entry["repeat_index"]
            and row.get("arm") == schedule_entry["arm"]
        ]
        if len(rows) != 1:
            raise ValueError("sealed argv does not contain one exact schedule entry")
        argv = rows[0].get("argv")
    else:
        raise ValueError("sealed argv artifact must be a list or invocation set")
    if (
        not isinstance(argv, list)
        or not argv
        or not all(isinstance(item, str) and item for item in argv)
    ):
        raise ValueError("resolved argv is invalid")
    return argv


def expand_execution_schedule(request: dict, artifact_root: Path) -> list[dict]:
    rows: list[dict] = []
    for scheduled in request["schedule"]:
        task_key = scheduled["task_id"]
        task = request["tasks"].get(task_key)
        if task is None:
            raise ValueError(f"scheduled task is absent from request: {task_key}")
        sealed_path = validate_identity(
            artifact_root, task["sealed_argv"], f"{task_key} sealed argv"
        )
        argv = invocation_argv(sealed_path, scheduled, task["task_id"])
        rows.append(
            {
                **scheduled,
                "sealed_argv_sha256": task["sealed_argv"]["sha256"],
                "resolved_argv": argv,
                "resolved_argv_sha256": digest(argv),
                "formal_gpu_uuids": task["formal_gpu_uuids"],
            }
        )
    return rows


def validate_authorization(
    authorization_path: Path,
    artifact_root: Path,
    *,
    require_live_store_host: bool = True,
) -> dict:
    artifact_root = artifact_root.resolve()
    authorization = validate_schema(
        authorization_path, AUTHORIZATION_SCHEMA, "combined authorization v2"
    )
    require_self_id(
        authorization, "combined_authorization_id", "combined authorization v2"
    )
    validate_validator_binding(authorization["validator_binding"])

    validate_identity(
        artifact_root, authorization["authorization_request"], "authorization request"
    )
    approval_path = validate_identity(
        artifact_root,
        authorization["semantic_supervisor_approval"],
        "semantic supervisor approval",
    )
    deployment_path = validate_identity(
        artifact_root,
        authorization["claim_store_deployment"],
        "claim-store deployment",
    )
    approval_bundle = validate_semantic_approval(approval_path, artifact_root)
    if not same_identity(
        approval_bundle["approval"]["authorization_request"],
        authorization["authorization_request"],
    ):
        raise ValueError("semantic approval binds a different authorization request")
    request = approval_bundle["request"]
    deployment_bundle = validate_deployment(
        deployment_path,
        artifact_root,
        require_live_host=require_live_store_host,
    )
    deployment = deployment_bundle["deployment"]

    pre_path = validate_identity(
        artifact_root, request["pre_gpu_gate"], "pre-GPU readiness"
    )
    execution_path = validate_identity(
        artifact_root, request["execution_contract_gate"], "execution readiness"
    )
    pre = validate_canonical_pre_gpu_readiness(pre_path, pre_path.parent)
    execution = validate_canonical_execution_readiness(execution_path, artifact_root)
    pre_ready = (
        pre.get("state") == "PRE_GPU_GATE_READY"
        and pre.get("eligible_to_execute_arms") is True
    )
    execution_ready = (
        execution.get("state") == "EXECUTION_CONTRACT_READY"
        and execution.get("eligible_by_this_gate") is True
    )
    semantic_ready = approval_bundle.get("semantic_approval_ready") is True
    store_ready = deployment_bundle.get("ready_for_atomic_claim") is True

    suite_path = validate_identity(artifact_root, request["suite"], "temporal suite")
    suite = read_object(suite_path)
    suite_id = suite.get("suite_id")
    if not isinstance(suite_id, str) or not suite_id:
        raise ValueError("temporal suite has no stable suite_id")
    if authorization["cycle_id"] != request["cycle_id"]:
        raise ValueError("authorization cycle differs from request")
    if authorization["suite_id"] != suite_id:
        raise ValueError("authorization suite differs from request")
    if authorization["formal_resource_id"] != request["formal_resource_id"]:
        raise ValueError("authorization resource differs from request")
    if deployment["formal_resource_id"] != request["formal_resource_id"]:
        raise ValueError("claim-store deployment resource differs from request")

    expected_schedule = expand_execution_schedule(request, artifact_root)
    if authorization["execution_schedule"] != expected_schedule:
        raise ValueError("authorization execution schedule differs from sealed argv")
    expected_gates = {
        "pre_gpu_ready": pre_ready,
        "execution_contract_ready": execution_ready,
        "semantic_approval_ready": semantic_ready,
        "claim_store_deployment_ready": store_ready,
    }
    if authorization["gate_decisions"] != expected_gates:
        raise ValueError("declared gate decisions differ from canonical validation")
    ready = all(expected_gates.values())
    if authorization["ready_for_atomic_claim"] is not ready:
        raise ValueError("ready_for_atomic_claim must equal P AND E AND A AND store")
    if ready:
        if (
            authorization["state"] != "READY_FOR_ATOMIC_CLAIM"
            or authorization["remaining_blockers"]
        ):
            raise ValueError("ready authorization must have no remaining blockers")
    elif (
        authorization["state"] != "ATOMIC_CLAIM_BLOCKED"
        or not authorization["remaining_blockers"]
    ):
        raise ValueError("blocked authorization requires at least one blocker")

    authorization_schedule_sha256 = digest(authorization_schedule(expected_schedule))
    execution_schedule_sha256 = digest(expected_schedule)
    return {
        "authorization": authorization,
        "request": request,
        "approval": approval_bundle["approval"],
        "deployment": deployment,
        "suite": suite,
        "execution_schedule": expected_schedule,
        "authorization_schedule_sha256": authorization_schedule_sha256,
        "execution_schedule_sha256": execution_schedule_sha256,
        "ready_for_atomic_claim": ready,
        "gpu_dispatch_authorized": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("authorization", type=Path)
    parser.add_argument("--artifact-root", required=True, type=Path)
    parser.add_argument("--offline-store-host-check", action="store_true")
    args = parser.parse_args()
    result = validate_authorization(
        args.authorization,
        args.artifact_root,
        require_live_store_host=not args.offline_store_host_check,
    )
    print(
        json.dumps(
            {
                "status": "PASS",
                "ready_for_atomic_claim": result["ready_for_atomic_claim"],
                "gpu_dispatch_authorized": result["gpu_dispatch_authorized"],
                "authorization_schedule_sha256": result[
                    "authorization_schedule_sha256"
                ],
                "execution_schedule_sha256": result["execution_schedule_sha256"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
