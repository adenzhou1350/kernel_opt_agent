from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import community_execution_authorization_v2 as authorization_module  # noqa: E402
from community_claim_contracts import digest  # noqa: E402
from community_execution_authorization_v2 import (  # noqa: E402
    expand_execution_schedule,
    validate_authorization,
)


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def identity(path: Path, root: Path) -> dict[str, str]:
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": sha256_file(path),
    }


def with_self_id(value: dict, field: str) -> dict:
    result = dict(value)
    result[field] = digest(value)
    return result


def validator_binding() -> dict[str, str]:
    paths = {
        "authorization_schema_sha256": ROOT
        / "schemas"
        / "community_combined_execution_authorization_v2.schema.json",
        "request_schema_sha256": ROOT
        / "schemas"
        / "community_execution_authorization_request_v2.schema.json",
        "approval_schema_sha256": ROOT
        / "schemas"
        / "community_semantic_supervisor_approval.schema.json",
        "deployment_schema_sha256": ROOT
        / "schemas"
        / "community_claim_store_deployment.schema.json",
        "validator_sha256": ROOT
        / "scripts"
        / "community_execution_authorization_v2.py",
        "semantic_validator_sha256": ROOT
        / "scripts"
        / "community_semantic_approval.py",
        "deployment_validator_sha256": ROOT
        / "scripts"
        / "community_claim_store_deployment.py",
        "pre_gpu_validator_sha256": ROOT / "scripts" / "community_pre_gpu_readiness.py",
        "execution_validator_sha256": ROOT
        / "scripts"
        / "community_execution_readiness.py",
        "claim_contracts_sha256": ROOT / "scripts" / "community_claim_contracts.py",
        "atomic_claim_sha256": ROOT / "scripts" / "community_atomic_claim.py",
    }
    return {
        "repository_commit": "1" * 40,
        **{key: sha256_file(path) for key, path in paths.items()},
    }


def build_bundle(root: Path, *, ready: bool = True) -> tuple[Path, dict]:
    pre_path = root / "pre.json"
    execution_path = root / "execution.json"
    suite_path = root / "suite.json"
    sealed_path = root / "sealed.json"
    request_path = root / "request.json"
    approval_path = root / "approval.json"
    deployment_path = root / "deployment.json"
    write_json(pre_path, {"placeholder": "canonical pre gate"})
    write_json(suite_path, {"suite_id": "suite-1"})
    write_json(sealed_path, ["python3", "runner.py", "--arm", "CONTROL"])
    write_json(
        execution_path,
        {
            "tasks": {
                "task-a": {
                    "task_id": "stable-task-a",
                    "sealed_argv": identity(sealed_path, root),
                }
            }
        },
    )
    request = {
        "request_id": "request-1",
        "cycle_id": "cycle-1",
        "formal_resource_id": "resource-1",
        "pre_gpu_gate": identity(pre_path, root),
        "execution_contract_gate": identity(execution_path, root),
        "suite": identity(suite_path, root),
        "tasks": {
            "task-a": {
                "task_id": "stable-task-a",
                "formal_gpu_uuids": ["GPU-11111111-1111-1111-1111-111111111111"],
                "sealed_argv": identity(sealed_path, root),
            }
        },
        "schedule": [
            {
                "order_index": 1,
                "task_id": "task-a",
                "repeat_index": 1,
                "arm": "CONTROL",
                "schedule_key": "2" * 64,
            }
        ],
    }
    write_json(request_path, request)
    approval = {
        "authorization_request": identity(request_path, root),
        "expires_at": "2030-01-01T00:00:00Z",
        "single_use_token": "3" * 64,
    }
    write_json(approval_path, approval)
    deployment = {
        "formal_resource_id": "resource-1",
        "claim_store_identity_sha256": "4" * 64,
        "claim_store_epoch_sha256": "5" * 64,
        "dispatcher_executable": {"path": "dispatcher.py", "sha256": "6" * 64},
    }
    write_json(deployment_path, deployment)
    schedule = expand_execution_schedule(request, root)
    gate_decisions = {
        "pre_gpu_ready": ready,
        "execution_contract_ready": ready,
        "semantic_approval_ready": True,
        "claim_store_deployment_ready": True,
    }
    authorization = with_self_id(
        {
            "schema_version": "community-combined-execution-authorization-v2",
            "generated_at": "2026-09-10T00:00:00Z",
            "claim_boundary": (
                "P_AND_E_AND_A_AND_STORE_RECOMPUTED_READY_FOR_ATOMIC_CLAIM_NOT_DISPATCH"
            ),
            "validator_binding": validator_binding(),
            "authorization_request": identity(request_path, root),
            "semantic_supervisor_approval": identity(approval_path, root),
            "claim_store_deployment": identity(deployment_path, root),
            "cycle_id": "cycle-1",
            "suite_id": "suite-1",
            "formal_resource_id": "resource-1",
            "execution_schedule": schedule,
            "gate_decisions": gate_decisions,
            "state": "READY_FOR_ATOMIC_CLAIM" if ready else "ATOMIC_CLAIM_BLOCKED",
            "ready_for_atomic_claim": ready,
            "gpu_dispatch_authorized": False,
            "remaining_blockers": [] if ready else ["pre/execution gate blocked"],
            "hidden_oracle_exposed": False,
        },
        "combined_authorization_id",
    )
    authorization_path = root / "authorization.json"
    write_json(authorization_path, authorization)
    return authorization_path, {
        "authorization": authorization,
        "request": request,
        "request_path": request_path,
        "approval": approval,
        "approval_path": approval_path,
        "deployment": deployment,
        "deployment_path": deployment_path,
        "ready": ready,
    }


@pytest.fixture(autouse=True)
def canonical_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(authorization_module, "require_commit", lambda commit: None)
    monkeypatch.setattr(
        authorization_module,
        "git_blob_sha256",
        lambda commit, relative: sha256_file(ROOT / relative),
    )

    def semantic(path: Path, root: Path) -> dict:
        approval = json.loads(path.read_text(encoding="utf-8"))
        request_path = root / approval["authorization_request"]["path"]
        request = json.loads(request_path.read_text(encoding="utf-8"))
        return {
            "approval": approval,
            "request": request,
            "semantic_approval_ready": True,
        }

    def deployment(path: Path, root: Path, *, require_live_host: bool) -> dict:
        value = json.loads(path.read_text(encoding="utf-8"))
        return {
            "deployment": value,
            "dispatcher_path": (root / value["dispatcher_executable"]["path"]).resolve(),
            "ready_for_atomic_claim": True,
        }

    monkeypatch.setattr(authorization_module, "validate_semantic_approval", semantic)
    monkeypatch.setattr(authorization_module, "validate_deployment", deployment)


def set_gate_validators(monkeypatch: pytest.MonkeyPatch, ready: bool) -> None:
    monkeypatch.setattr(
        authorization_module,
        "validate_canonical_pre_gpu_readiness",
        lambda path, root: {
            "state": "PRE_GPU_GATE_READY" if ready else "PRE_GPU_GATE_BLOCKED",
            "eligible_to_execute_arms": ready,
        },
    )
    monkeypatch.setattr(
        authorization_module,
        "validate_canonical_execution_readiness",
        lambda path, root: {
            "state": "EXECUTION_CONTRACT_READY"
            if ready
            else "EXECUTION_CONTRACT_BLOCKED",
            "eligible_by_this_gate": ready,
        },
    )


@pytest.mark.parametrize("ready", [True, False])
def test_authorization_recomputes_all_gates_without_dispatch(
    monkeypatch: pytest.MonkeyPatch, ready: bool
) -> None:
    set_gate_validators(monkeypatch, ready)
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        path, _ = build_bundle(root, ready=ready)
        result = validate_authorization(path, root, require_live_store_host=False)
        assert result["ready_for_atomic_claim"] is ready
        assert result["gpu_dispatch_authorized"] is False
        assert len(result["execution_schedule"]) == 1
        assert result["dispatcher_path"] == (root / "dispatcher.py").resolve()


def test_invocation_set_resolves_exact_schedule_entry() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        _, bundle = build_bundle(root)
        sealed_path = root / "sealed.json"
        write_json(
            sealed_path,
            {
                "task_id": "stable-task-a",
                "invocations": [
                    {
                        "order_index": 1,
                        "repeat_index": 1,
                        "arm": "CONTROL",
                        "argv": ["python3", "runner.py", "--exact"],
                    }
                ],
            },
        )
        bundle["request"]["tasks"]["task-a"]["sealed_argv"] = identity(
            sealed_path, root
        )
        rows = expand_execution_schedule(bundle["request"], root)
        assert rows[0]["resolved_argv"][-1] == "--exact"


def test_authorization_rejects_declared_gate_or_schedule_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_gate_validators(monkeypatch, True)
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        path, bundle = build_bundle(root)
        authorization = bundle["authorization"]
        authorization["gate_decisions"]["pre_gpu_ready"] = False
        unsigned = {
            key: value
            for key, value in authorization.items()
            if key != "combined_authorization_id"
        }
        authorization["combined_authorization_id"] = digest(unsigned)
        write_json(path, authorization)
        with pytest.raises(ValueError, match="declared gate decisions"):
            validate_authorization(path, root, require_live_store_host=False)

        path, bundle = build_bundle(root)
        authorization = bundle["authorization"]
        authorization["execution_schedule"][0]["resolved_argv"][-1] = "--drift"
        unsigned = {
            key: value
            for key, value in authorization.items()
            if key != "combined_authorization_id"
        }
        authorization["combined_authorization_id"] = digest(unsigned)
        write_json(path, authorization)
        with pytest.raises(ValueError, match="differs from sealed argv"):
            validate_authorization(path, root, require_live_store_host=False)


def test_authorization_rejects_sealed_argv_not_bound_by_execution_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_gate_validators(monkeypatch, True)
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        path, bundle = build_bundle(root)
        execution_path = root / "execution.json"
        execution = json.loads(execution_path.read_text(encoding="utf-8"))
        execution["tasks"]["task-a"]["sealed_argv"]["sha256"] = "0" * 64
        write_json(execution_path, execution)
        request = bundle["request"]
        request["execution_contract_gate"] = identity(execution_path, root)
        write_json(bundle["request_path"], request)
        approval = bundle["approval"]
        approval["authorization_request"] = identity(bundle["request_path"], root)
        write_json(bundle["approval_path"], approval)
        authorization = bundle["authorization"]
        authorization["authorization_request"] = identity(
            bundle["request_path"], root
        )
        authorization["semantic_supervisor_approval"] = identity(
            bundle["approval_path"], root
        )
        unsigned = {
            key: value
            for key, value in authorization.items()
            if key != "combined_authorization_id"
        }
        authorization["combined_authorization_id"] = digest(unsigned)
        write_json(path, authorization)
        with pytest.raises(ValueError, match="sealed argv differs from execution"):
            validate_authorization(path, root, require_live_store_host=False)


def test_authorization_rejects_approval_or_store_substitution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_gate_validators(monkeypatch, True)
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        path, bundle = build_bundle(root)
        approval = copy.deepcopy(bundle["approval"])
        foreign_path = root / "foreign.json"
        write_json(foreign_path, bundle["request"])
        approval["authorization_request"] = identity(foreign_path, root)
        write_json(bundle["approval_path"], approval)
        authorization = bundle["authorization"]
        authorization["semantic_supervisor_approval"] = identity(
            bundle["approval_path"], root
        )
        unsigned = {
            key: value
            for key, value in authorization.items()
            if key != "combined_authorization_id"
        }
        authorization["combined_authorization_id"] = digest(unsigned)
        write_json(path, authorization)
        with pytest.raises(ValueError, match="binds a different authorization request"):
            validate_authorization(path, root, require_live_store_host=False)

        path, bundle = build_bundle(root)
        deployment = bundle["deployment"]
        deployment["formal_resource_id"] = "foreign-resource"
        write_json(bundle["deployment_path"], deployment)
        authorization = bundle["authorization"]
        authorization["claim_store_deployment"] = identity(
            bundle["deployment_path"], root
        )
        unsigned = {
            key: value
            for key, value in authorization.items()
            if key != "combined_authorization_id"
        }
        authorization["combined_authorization_id"] = digest(unsigned)
        write_json(path, authorization)
        with pytest.raises(ValueError, match="deployment resource differs"):
            validate_authorization(path, root, require_live_store_host=False)


def test_authorization_rejects_self_id_and_validator_binding_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_gate_validators(monkeypatch, True)
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        path, bundle = build_bundle(root)
        authorization = bundle["authorization"]
        authorization["suite_id"] = "suite-forged"
        write_json(path, authorization)
        with pytest.raises(ValueError, match="self identity changed"):
            validate_authorization(path, root, require_live_store_host=False)

        path, bundle = build_bundle(root)
        authorization = bundle["authorization"]
        authorization["validator_binding"]["atomic_claim_sha256"] = "0" * 64
        unsigned = {
            key: value
            for key, value in authorization.items()
            if key != "combined_authorization_id"
        }
        authorization["combined_authorization_id"] = digest(unsigned)
        write_json(path, authorization)
        with pytest.raises(ValueError, match="declared commit binding changed"):
            validate_authorization(path, root, require_live_store_host=False)
