#!/usr/bin/env python3
"""Validate P-and-E-and-A authorization and its downstream provenance."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from community_execution_readiness import (
    validate_execution_readiness as validate_canonical_execution_readiness,
)
from community_knowledge import read_object, sha256_file
from community_meta_cycle_report import validate_report
from community_pre_gpu_readiness import (
    validate_readiness as validate_canonical_pre_gpu_readiness,
)
from community_work_cycle_observation import validate_observation
from schema_utils import validate_json_file

REQUEST_SCHEMA = "community_execution_authorization_request.schema.json"
AUTHORIZATION_SCHEMA = "community_combined_execution_authorization.schema.json"
RECEIPT_SCHEMA = "community_dispatch_receipt.schema.json"
OBSERVATION_PROVENANCE_SCHEMA = (
    "community_work_cycle_observation_provenance.schema.json"
)
REPORT_PROVENANCE_SCHEMA = "community_meta_cycle_report_provenance.schema.json"


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def resolve_inside(base: Path, relative: str) -> Path:
    base = base.resolve()
    path = (base / relative).resolve()
    try:
        path.relative_to(base)
    except ValueError as error:
        raise ValueError(
            f"identity path escapes the artifact root: {relative}"
        ) from error
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


def require_commit(commit: str) -> None:
    result = subprocess.run(
        ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
        cwd=repository_root(),
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise ValueError("authorization validator commit is unavailable")


def git_blob_sha256(commit: str, relative_path: str) -> str:
    result = subprocess.run(
        ["git", "show", f"{commit}:{relative_path}"],
        cwd=repository_root(),
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise ValueError(
            f"authorization validator blob is unavailable: {relative_path}"
        )
    return hashlib.sha256(result.stdout).hexdigest()


def canonical_schedule(entries: list[dict]) -> list[dict]:
    fields = ("order_index", "task_id", "repeat_index", "arm", "schedule_key")
    return [{field: entry.get(field) for field in fields} for entry in entries]


def same_identity(left: dict | None, right: dict | None) -> bool:
    if left is None or right is None:
        return left is right
    return left.get("path") == right.get("path") and left.get("sha256") == right.get(
        "sha256"
    )


def validate_request(request_path: Path, artifact_root: Path) -> dict:
    request = validate_schema(request_path, REQUEST_SCHEMA, "authorization request")
    artifact_root = artifact_root.resolve()
    pre_path = validate_identity(artifact_root, request["pre_gpu_gate"], "pre-GPU gate")
    execution_path = validate_identity(
        artifact_root, request["execution_contract_gate"], "execution-contract gate"
    )
    cohort_path = validate_identity(artifact_root, request["cohort"], "cohort freeze")
    suite_path = validate_identity(artifact_root, request["suite"], "temporal suite")
    pre_validation = validate_canonical_pre_gpu_readiness(pre_path, pre_path.parent)
    execution_validation = validate_canonical_execution_readiness(
        execution_path, artifact_root
    )
    pre = read_object(pre_path)
    execution = read_object(execution_path)
    cohort = read_object(cohort_path)
    suite = read_object(suite_path)

    if not (
        request["cycle_id"]
        == pre.get("cycle_id")
        == execution.get("cycle_id")
        == cohort.get("cycle_id")
    ):
        raise ValueError("request mixes cycle identities")
    if not same_identity(execution.get("base_readiness"), request["pre_gpu_gate"]):
        raise ValueError(
            "execution-contract gate is not bound to the requested pre-GPU gate"
        )
    pre_suite_identity = pre.get("protocol_binding", {}).get("temporal_suite")
    if not isinstance(pre_suite_identity, dict):
        raise ValueError("pre-GPU readiness has no temporal suite identity")
    pre_suite_path = validate_identity(
        pre_path.parent, pre_suite_identity, "pre-GPU temporal suite"
    )
    if pre_suite_path != suite_path:
        raise ValueError("request suite differs from pre-GPU readiness")
    if (
        pre.get("cohort_binding", {}).get("cohort_freeze_sha256")
        != request["cohort"]["sha256"]
    ):
        raise ValueError("request cohort differs from pre-GPU readiness")
    if request["formal_resource_id"] != pre.get("formal_resource", {}).get(
        "resource_id"
    ):
        raise ValueError("request formal resource differs from pre-GPU readiness")

    pre_tasks = pre.get("task_freezes", {})
    execution_tasks = execution.get("tasks", {})
    request_tasks = request["tasks"]
    if set(request_tasks) != set(pre_tasks) or set(request_tasks) != set(
        execution_tasks
    ):
        raise ValueError("request task keys differ across P/E gates")
    for key, task in request_tasks.items():
        if task["task_id"] != pre_tasks[key].get("task_id") or task[
            "task_id"
        ] != execution_tasks[key].get("task_id"):
            raise ValueError(f"request task identity drift: {key}")
        if task["formal_gpu_uuids"] != pre_tasks[key].get("formal_gpu_uuids"):
            raise ValueError(f"request GPU UUID drift: {key}")
        if not same_identity(
            task["sealed_argv"], execution_tasks[key].get("sealed_argv")
        ):
            raise ValueError(f"request sealed argv drift: {key}")
        validate_identity(artifact_root, task["sealed_argv"], f"{key} sealed argv")

    frozen_schedule = cohort.get("randomized_schedule", {}).get("entries")
    if not isinstance(frozen_schedule, list) or canonical_schedule(
        request["schedule"]
    ) != canonical_schedule(frozen_schedule):
        raise ValueError("request schedule differs from the frozen cohort")
    if sorted(row["order_index"] for row in request["schedule"]) != list(
        range(1, len(request["schedule"]) + 1)
    ):
        raise ValueError("request schedule order_index must be contiguous")
    scheduled_tasks = {row["task_id"] for row in request["schedule"]}
    cohort_task_ids = {task.get("task_id") for task in cohort.get("primary_tasks", [])}
    if scheduled_tasks != cohort_task_ids:
        raise ValueError("request schedule task set differs from the cohort")
    if suite_path.stat().st_size == 0:
        raise ValueError("temporal suite is empty")

    return {
        "request": request,
        "pre": pre,
        "pre_validation": pre_validation,
        "execution": execution,
        "execution_validation": execution_validation,
        "cohort": cohort,
        "suite": suite,
    }


def validate_authorization(authorization_path: Path, artifact_root: Path) -> dict:
    authorization = validate_schema(
        authorization_path, AUTHORIZATION_SCHEMA, "combined authorization"
    )
    artifact_root = artifact_root.resolve()
    binding = authorization["validator_binding"]
    require_commit(binding["repository_commit"])
    root = repository_root()
    paths = {
        "request_schema_sha256": f"schemas/{REQUEST_SCHEMA}",
        "authorization_schema_sha256": f"schemas/{AUTHORIZATION_SCHEMA}",
        "validator_sha256": "scripts/community_execution_authorization.py",
    }
    declared_commit_expected = {
        key: git_blob_sha256(binding["repository_commit"], relative_path)
        for key, relative_path in paths.items()
    }
    for key, value in declared_commit_expected.items():
        if binding[key] != value:
            raise ValueError(f"authorization declared commit binding changed: {key}")

    worktree_expected = {
        "request_schema_sha256": sha256_file(root / "schemas" / REQUEST_SCHEMA),
        "authorization_schema_sha256": sha256_file(
            root / "schemas" / AUTHORIZATION_SCHEMA
        ),
        "validator_sha256": sha256_file(Path(__file__)),
    }
    for key, value in worktree_expected.items():
        if binding[key] != value:
            raise ValueError(f"authorization worktree binding changed: {key}")

    request_path = validate_identity(
        artifact_root, authorization["authorization_request"], "authorization request"
    )
    bundle = validate_request(request_path, artifact_root)
    request = bundle["request"]
    if authorization["cycle_id"] != request["cycle_id"]:
        raise ValueError("authorization cycle differs from request")
    if not same_identity(authorization["pre_gpu_gate"], request["pre_gpu_gate"]):
        raise ValueError("authorization pre-GPU identity differs from request")
    if not same_identity(
        authorization["execution_contract_gate"], request["execution_contract_gate"]
    ):
        raise ValueError(
            "authorization execution-contract identity differs from request"
        )

    pre_ready = (
        bundle["pre_validation"].get("state") == "PRE_GPU_GATE_READY"
        and bundle["pre_validation"].get("eligible_to_execute_arms") is True
    )
    execution_ready = (
        bundle["execution_validation"].get("state") == "EXECUTION_CONTRACT_READY"
        and bundle["execution_validation"].get("eligible_by_this_gate") is True
    )
    approval_identity = authorization["supervisor_approval"]
    supervisor_ready = False
    if approval_identity is not None:
        raise ValueError(
            "combined authorization v1 cannot consume a supervisor approval: "
            "the request does not bind the supervisor registry, exact budget, "
            "role artifacts, or resolved decision/measurability/frontier/objective "
            "contracts; use a versioned semantic-approval contract"
        )

    actual = {
        "pre_gpu_ready": pre_ready,
        "execution_contract_ready": execution_ready,
        "independent_supervisor_approved": supervisor_ready,
    }
    if authorization["gate_decisions"] != actual:
        raise ValueError("declared gate decisions differ from recomputed P/E/A state")
    allowed = all(actual.values())
    if authorization["gpu_dispatch_authorized"] is not allowed:
        raise ValueError("gpu_dispatch_authorized must equal P AND E AND A")
    if allowed:
        if (
            authorization["state"] != "DISPATCH_AUTHORIZED"
            or authorization["remaining_blockers"]
        ):
            raise ValueError("authorized state requires no remaining blockers")
    elif (
        authorization["state"] != "DISPATCH_BLOCKED"
        or not authorization["remaining_blockers"]
    ):
        raise ValueError("blocked state requires at least one remaining blocker")
    return {
        "authorization": authorization,
        "request": request,
        "suite": bundle["suite"],
        "allowed": allowed,
    }


def validate_dispatch_receipt(receipt_path: Path, artifact_root: Path) -> dict:
    receipt = validate_schema(receipt_path, RECEIPT_SCHEMA, "dispatch receipt")
    artifact_root = artifact_root.resolve()
    authorization_path = validate_identity(
        artifact_root, receipt["combined_authorization"], "combined authorization"
    )
    bundle = validate_authorization(authorization_path, artifact_root)
    if not bundle["allowed"]:
        raise ValueError("dispatch receipt cannot consume a blocked authorization")
    if not same_identity(
        receipt["authorization_request"],
        bundle["authorization"]["authorization_request"],
    ):
        raise ValueError("dispatch receipt request differs from authorization")
    request = bundle["request"]
    if receipt["cycle_id"] != request["cycle_id"]:
        raise ValueError("dispatch receipt cycle differs from authorization request")
    if receipt["suite_id"] != bundle["suite"].get("suite_id"):
        raise ValueError("dispatch receipt suite differs from authorization request")
    rows = [
        row
        for row in request["schedule"]
        if receipt["task_key"] == row["task_id"]
        and all(
            receipt[key] == row[key]
            for key in ("repeat_index", "arm", "order_index", "schedule_key")
        )
    ]
    if len(rows) != 1:
        raise ValueError("dispatch receipt is not one exact frozen schedule entry")
    task = request["tasks"].get(receipt["task_key"])
    if (
        task is None
        or task["task_id"] != receipt["task_id"]
        or not same_identity(receipt["sealed_argv"], task["sealed_argv"])
    ):
        raise ValueError("dispatch receipt sealed argv differs from the frozen task")
    validate_identity(artifact_root, receipt["sealed_argv"], "dispatch sealed argv")
    return {"receipt": receipt, "authorization": bundle["authorization"]}


def validate_observation_provenance(path: Path, artifact_root: Path) -> dict:
    envelope = validate_schema(
        path, OBSERVATION_PROVENANCE_SCHEMA, "observation provenance"
    )
    artifact_root = artifact_root.resolve()
    observation_path = validate_identity(
        artifact_root, envelope["observation"], "observation"
    )
    receipt_path = validate_identity(
        artifact_root, envelope["dispatch_receipt"], "dispatch receipt"
    )
    observation = validate_observation(observation_path, repository_root())[
        "observation"
    ]
    receipt = validate_dispatch_receipt(receipt_path, artifact_root)["receipt"]
    for key in ("suite_id", "task_id", "repeat_index", "arm"):
        if observation[key] != receipt[key]:
            raise ValueError(f"observation differs from dispatch receipt: {key}")
    return {"envelope": envelope, "observation": observation, "receipt": receipt}


def validate_report_provenance(path: Path, artifact_root: Path) -> dict:
    envelope = validate_schema(path, REPORT_PROVENANCE_SCHEMA, "report provenance")
    artifact_root = artifact_root.resolve()
    report_path = validate_identity(
        artifact_root, envelope["report"], "meta-cycle report"
    )
    authorization_path = validate_identity(
        artifact_root, envelope["combined_authorization"], "combined authorization"
    )
    authorization = validate_authorization(authorization_path, artifact_root)
    if not authorization["allowed"]:
        raise ValueError("final report cannot consume a blocked authorization")
    report = validate_report(report_path, artifact_root)
    expected = set()
    for framework in report["framework_results"]:
        for rows in framework["observations"].values():
            expected.update(row["observation"]["sha256"] for row in rows)
    observed = set()
    for index, identity in enumerate(envelope["observation_provenance"]):
        provenance_path = validate_identity(
            artifact_root, identity, f"observation provenance {index + 1}"
        )
        bundle = validate_observation_provenance(provenance_path, artifact_root)
        if (
            bundle["receipt"]["combined_authorization"]
            != envelope["combined_authorization"]
        ):
            raise ValueError("report mixes combined authorization identities")
        observed.add(bundle["envelope"]["observation"]["sha256"])
    if observed != expected or len(envelope["observation_provenance"]) != len(expected):
        raise ValueError(
            "report provenance does not cover every exact observation once"
        )
    return {"envelope": envelope, "report": report}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=[
            "validate-request",
            "validate-authorization",
            "validate-receipt",
            "validate-observation",
            "validate-report",
        ],
    )
    parser.add_argument("--artifact", required=True, type=Path)
    parser.add_argument("--artifact-root", required=True, type=Path)
    args = parser.parse_args()
    functions = {
        "validate-request": validate_request,
        "validate-authorization": validate_authorization,
        "validate-receipt": validate_dispatch_receipt,
        "validate-observation": validate_observation_provenance,
        "validate-report": validate_report_provenance,
    }
    result = functions[args.command](args.artifact, args.artifact_root)
    print(
        json.dumps(
            {"status": "PASS", "command": args.command, "keys": sorted(result)},
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
