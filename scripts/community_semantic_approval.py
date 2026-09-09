#!/usr/bin/env python3
"""Validate semantic supervisor approval without claiming or dispatching work."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path

from community_knowledge import read_object, sha256_file
from schema_utils import validate_json_file
from supervision_utils import (
    validate_decision_contract,
    validate_measurability_contract,
)

REQUEST_SCHEMA = "community_execution_authorization_request_v2.schema.json"
APPROVAL_SCHEMA = "community_semantic_supervisor_approval.schema.json"
REGISTRY_SCHEMA = "community_supervisor_registry.schema.json"
ROLE_SCHEMA = "community_role_assignment.schema.json"
BUDGET_SCHEMA = "community_execution_budget.schema.json"
VALIDATOR_PATH = "scripts/community_semantic_approval.py"


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


def same_identity(left: dict | None, right: dict | None) -> bool:
    if left is None or right is None:
        return left is right
    return left.get("path") == right.get("path") and left.get("sha256") == right.get(
        "sha256"
    )


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


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def canonical_scope(request: dict) -> dict:
    return {
        "request_id": request["request_id"],
        "cycle_id": request["cycle_id"],
        "pre_gpu_gate": request["pre_gpu_gate"],
        "execution_contract_gate": request["execution_contract_gate"],
        "cohort": request["cohort"],
        "suite": request["suite"],
        "formal_resource_id": request["formal_resource_id"],
        "tasks": request["tasks"],
        "schedule": request["schedule"],
    }


def scope_sha256(request: dict) -> str:
    encoded = json.dumps(
        canonical_scope(request), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def require_commit(commit: str) -> None:
    result = subprocess.run(
        ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
        cwd=repository_root(),
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise ValueError("semantic approval validator commit is unavailable")


def git_blob_sha256(commit: str, relative_path: str) -> str:
    result = subprocess.run(
        ["git", "show", f"{commit}:{relative_path}"],
        cwd=repository_root(),
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise ValueError(f"semantic approval blob is unavailable: {relative_path}")
    return hashlib.sha256(result.stdout).hexdigest()


def validate_validator_binding(binding: dict) -> None:
    require_commit(binding["repository_commit"])
    paths = {
        "request_schema_sha256": f"schemas/{REQUEST_SCHEMA}",
        "approval_schema_sha256": f"schemas/{APPROVAL_SCHEMA}",
        "registry_schema_sha256": f"schemas/{REGISTRY_SCHEMA}",
        "role_schema_sha256": f"schemas/{ROLE_SCHEMA}",
        "budget_schema_sha256": f"schemas/{BUDGET_SCHEMA}",
        "validator_sha256": VALIDATOR_PATH,
    }
    for key, relative_path in paths.items():
        if binding[key] != git_blob_sha256(binding["repository_commit"], relative_path):
            raise ValueError(
                f"semantic approval declared commit binding changed: {key}"
            )
        if binding[key] != sha256_file(repository_root() / relative_path):
            raise ValueError(f"semantic approval worktree binding changed: {key}")


def validate_budget(path: Path, request: dict) -> dict:
    budget = validate_schema(path, BUDGET_SCHEMA, "execution budget")
    if budget["cycle_id"] != request["cycle_id"]:
        raise ValueError("execution budget cycle differs from request")
    if budget["request_id"] != request["request_id"]:
        raise ValueError("execution budget request differs from request")
    for key, requested in budget["requested"].items():
        if float(requested) > float(budget["maximum"][key]):
            raise ValueError(f"requested execution budget exceeds maximum: {key}")
    if budget["requested"]["max_dispatches"] != len(request["schedule"]):
        raise ValueError("requested max_dispatches must equal the frozen schedule")
    return budget


def validate_roles(request: dict, artifact_root: Path) -> dict[str, dict]:
    expected = {
        "scheduler": "GLOBAL_SCHEDULER",
        "analyst": "MICROARCHITECTURE_ANALYST",
        "experimenter": "EXPERIMENT_AGENT",
    }
    roles: dict[str, dict] = {}
    for key, role in expected.items():
        path = validate_identity(
            artifact_root, request["role_artifacts"][key], f"{key} role artifact"
        )
        value = validate_schema(path, ROLE_SCHEMA, f"{key} role artifact")
        if value["cycle_id"] != request["cycle_id"] or value["role"] != role:
            raise ValueError(f"{key} role artifact differs from request semantics")
        roles[key] = value
    experimenter_id = roles["experimenter"]["actor_id"]
    if any(
        task["experimenter_id"] != experimenter_id for task in request["tasks"].values()
    ):
        raise ValueError("task experimenter differs from the bound role artifact")
    return roles


def validate_contracts(request: dict, artifact_root: Path, roles: dict) -> None:
    if set(request["contract_bindings"]) != set(request["tasks"]):
        raise ValueError("contract task keys differ from request tasks")
    decision_ids: set[str] = set()
    for key, binding in request["contract_bindings"].items():
        if binding["task_id"] != request["tasks"][key]["task_id"]:
            raise ValueError(f"contract task identity differs from request: {key}")
        paths = {
            name: validate_identity(artifact_root, binding[name], f"{key} {name}")
            for name in (
                "decision_contract",
                "measurability_contract",
                "frontier",
                "objective",
            )
        }
        decision_errors = validate_decision_contract(
            paths["decision_contract"], artifact_root
        )
        if decision_errors:
            raise ValueError(
                f"invalid {key} decision contract: " + "; ".join(decision_errors)
            )
        measurability_errors = validate_measurability_contract(
            paths["measurability_contract"], artifact_root, paths["decision_contract"]
        )
        if measurability_errors:
            raise ValueError(
                f"invalid {key} measurability contract: "
                + "; ".join(measurability_errors)
            )
        decision = read_object(paths["decision_contract"])
        measurability = read_object(paths["measurability_contract"])
        if decision["decision_id"] in decision_ids:
            raise ValueError("decision ids must be unique across tasks")
        decision_ids.add(decision["decision_id"])
        if decision["issued_by"]["owner_id"] != roles["scheduler"]["actor_id"]:
            raise ValueError(f"{key} decision issuer differs from scheduler role")
        if measurability["issued_by"]["analyst_id"] != roles["analyst"]["actor_id"]:
            raise ValueError(f"{key} measurability issuer differs from analyst role")
        if measurability["selected_method"] == "NO_MEASUREMENT":
            raise ValueError(f"{key} measurability cannot authorize NO_MEASUREMENT")
        if not same_identity(decision["frontier_identity"], binding["frontier"]):
            raise ValueError(f"{key} decision-to-frontier binding differs")
        if not same_identity(decision["objective_identity"], binding["objective"]):
            raise ValueError(f"{key} decision-to-objective binding differs")
        if not same_identity(
            measurability["decision_contract_identity"], binding["decision_contract"]
        ):
            raise ValueError(f"{key} measurability-to-decision binding differs")


def validate_request(request_path: Path, artifact_root: Path) -> dict:
    request = validate_schema(request_path, REQUEST_SCHEMA, "semantic approval request")
    artifact_root = artifact_root.resolve()
    for label in (
        "pre_gpu_gate",
        "execution_contract_gate",
        "cohort",
        "suite",
        "supervisor_registry",
        "execution_budget",
    ):
        validate_identity(artifact_root, request[label], label.replace("_", " "))
    for key, task in request["tasks"].items():
        validate_identity(artifact_root, task["sealed_argv"], f"{key} sealed argv")
    if sorted(row["order_index"] for row in request["schedule"]) != list(
        range(1, len(request["schedule"]) + 1)
    ):
        raise ValueError("request schedule order_index must be contiguous")
    if {row["task_id"] for row in request["schedule"]} != set(request["tasks"]):
        raise ValueError("request schedule task set differs from request tasks")
    if parse_time(request["approval_expires_at"]) <= parse_time(
        request["generated_at"]
    ):
        raise ValueError("request approval expiry must be after generation")
    if request["approval_scope_sha256"] != scope_sha256(request):
        raise ValueError("request approval scope digest differs from frozen scope")
    roles = validate_roles(request, artifact_root)
    budget_path = validate_identity(
        artifact_root, request["execution_budget"], "execution budget"
    )
    budget = validate_budget(budget_path, request)
    validate_contracts(request, artifact_root, roles)
    return {"request": request, "roles": roles, "budget": budget}


def validate_approval(approval_path: Path, artifact_root: Path) -> dict:
    approval = validate_schema(
        approval_path, APPROVAL_SCHEMA, "semantic supervisor approval"
    )
    validate_validator_binding(approval["validator_binding"])
    artifact_root = artifact_root.resolve()
    request_path = validate_identity(
        artifact_root, approval["authorization_request"], "authorization request"
    )
    bundle = validate_request(request_path, artifact_root)
    request = bundle["request"]
    exact_fields = (
        "request_id",
        "cycle_id",
        "approval_scope_sha256",
        "single_use_token",
    )
    for field in exact_fields:
        if approval[field] != request[field]:
            raise ValueError(f"approval differs from request: {field}")
    if not same_identity(
        approval["supervisor_registry"], request["supervisor_registry"]
    ):
        raise ValueError("approval registry differs from request")
    if approval["role_artifacts"] != request["role_artifacts"]:
        raise ValueError("approval role artifacts differ from request")
    if approval["contract_bindings"] != request["contract_bindings"]:
        raise ValueError("approval contract bindings differ from request")
    if approval["approved_budget"] != bundle["budget"]["requested"]:
        raise ValueError("approval budget differs from the exact requested budget")

    registry_path = validate_identity(
        artifact_root, request["supervisor_registry"], "supervisor registry"
    )
    registry = validate_schema(registry_path, REGISTRY_SCHEMA, "supervisor registry")
    if registry["cycle_id"] != request["cycle_id"]:
        raise ValueError("supervisor registry cycle differs from request")
    supervisor_ids = [item["supervisor_id"] for item in registry["supervisors"]]
    if len(supervisor_ids) != len(set(supervisor_ids)):
        raise ValueError("supervisor registry contains duplicate ids")
    issuer = approval["issued_by"]["supervisor_id"]
    trusted = [
        item
        for item in registry["supervisors"]
        if item["supervisor_id"] == issuer
        and item["status"] == "ACTIVE"
        and "APPROVE_COMMUNITY_COHORT_DISPATCH" in item["authorities"]
    ]
    if len(trusted) != 1:
        raise ValueError("approval issuer is not one active registered supervisor")
    actor_ids = [role["actor_id"] for role in bundle["roles"].values()] + [issuer]
    if len(actor_ids) != len(set(actor_ids)):
        raise ValueError("scheduler, analyst, experimenter and supervisor must differ")

    request_generated = parse_time(request["generated_at"])
    request_expiry = parse_time(request["approval_expires_at"])
    approval_issued = parse_time(approval["issued_at"])
    approval_expiry = parse_time(approval["expires_at"])
    if approval_issued < request_generated:
        raise ValueError("approval predates the authorization request")
    if approval_expiry <= approval_issued or approval_expiry > request_expiry:
        raise ValueError("approval expiry is outside the request policy")

    return {
        "state": "READY_FOR_ATOMIC_CONSUMPTION",
        "semantic_approval_ready": True,
        "single_use_token": approval["single_use_token"],
        "atomic_claim_required": True,
        "gpu_dispatch_authorized": False,
        "approval": approval,
        "request": request,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate semantic approval without dispatch authorization"
    )
    parser.add_argument("approval", type=Path)
    parser.add_argument("--artifact-root", required=True, type=Path)
    args = parser.parse_args()
    result = validate_approval(args.approval, args.artifact_root)
    print(
        json.dumps(
            {
                "status": "PASS",
                "state": result["state"],
                "semantic_approval_ready": result["semantic_approval_ready"],
                "atomic_claim_required": result["atomic_claim_required"],
                "gpu_dispatch_authorized": result["gpu_dispatch_authorized"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
