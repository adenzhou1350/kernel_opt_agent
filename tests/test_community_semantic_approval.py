from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import community_semantic_approval as approval_module  # noqa: E402
from community_knowledge import sha256_file  # noqa: E402
from community_semantic_approval import scope_sha256, validate_approval  # noqa: E402

REAL_VALIDATE_BINDING = approval_module.validate_validator_binding


def write_json(path: Path, value: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def identity(path: Path, base: Path) -> dict:
    return {"path": path.relative_to(base).as_posix(), "sha256": sha256_file(path)}


def role(cycle_id: str, role_name: str, actor_id: str) -> dict:
    return {
        "schema_version": "community-role-assignment-v1",
        "generated_at": "2026-09-09T00:00:00Z",
        "cycle_id": cycle_id,
        "claim_boundary": "FROZEN_ROLE_IDENTITY_NOT_APPROVAL",
        "role": role_name,
        "actor_id": actor_id,
        "status": "ACTIVE",
    }


def build_decision(
    base: Path,
    task_key: str,
    scheduler_id: str,
    frontier_identity: dict,
    objective_identity: dict,
) -> dict:
    candidate_paths = [base / f"{task_key}-candidate-{index}.json" for index in (1, 2)]
    for index, path in enumerate(candidate_paths, start=1):
        write_json(path, {"candidate_id": f"{task_key}-candidate-{index}"})
    return {
        "schema_version": "decision-contract-v1",
        "decision_id": f"{task_key}-decision",
        "status": "READY_FOR_SUPERVISOR",
        "issued_by": {"role": "GLOBAL_SCHEDULER", "owner_id": scheduler_id},
        "objective_identity": objective_identity,
        "frontier_identity": frontier_identity,
        "candidate_bindings": [
            {
                "candidate_id": f"{task_key}-candidate-{index}",
                "artifact_identity": identity(path, base),
                "predicted_objective": {
                    "lower": float(index),
                    "upper": float(index + 2),
                    "unit": "ms",
                },
            }
            for index, path in enumerate(candidate_paths, start=1)
        ],
        "top_two_candidate_ids": [
            f"{task_key}-candidate-1",
            f"{task_key}-candidate-2",
        ],
        "decision_metric": {"name": "latency", "unit": "ms", "direction": "minimize"},
        "measurement_need": {
            "quantity_id": f"{task_key}-quantity",
            "model_location": "frozen theory-first model",
            "equation": "candidate ordering as a function of measured latency",
            "current_interval": {"lower": 0.0, "upper": 10.0, "unit": "us"},
            "top_two_delta_interval": {"lower": -1.0, "upper": 1.0, "unit": "ms"},
            "decision_boundary": {"value": 5.0, "unit": "us"},
            "required_precision": {"value": 1.0, "unit": "us"},
            "outcome_mapping": [{"outcome": "A"}, {"outcome": "B"}],
            "maximum_decision_value": {"value": 1.0, "unit": "ms"},
            "decision_flip_probability": 0.5,
            "expected_uncertainty_reduction": 0.5,
        },
        "experiment_budget": {
            "screening": {
                "max_configurations": 1,
                "max_samples_per_configuration": 1,
                "max_process_launches": 1,
                "max_wall_clock_minutes": 1,
            },
            "qualification": {
                "max_configurations": 1,
                "max_samples_per_configuration": 2,
                "max_process_launches": 2,
                "max_wall_clock_minutes": 5,
            },
            "max_revisions": 0,
        },
        "stop_rules": ["Stop after the frozen bounded measurement."],
        "evidence": [],
    }


def build_bundle(base: Path) -> dict:
    cycle_id = "cycle-1"
    request_id = "request-1"
    task_key = "task-a"
    files: dict[str, Path] = {}
    for name, value in {
        "pre": {"state": "PRE_GPU_GATE_READY"},
        "execution": {"state": "EXECUTION_CONTRACT_READY"},
        "cohort": {"cycle_id": cycle_id},
        "suite": {"suite_id": "suite-1"},
        "sealed": ["python", "runner.py"],
        "frontier": {"status": "FROZEN", "task_id": "stable-task-a"},
        "objective": {"task_id": "stable-task-a", "metric": "latency"},
    }.items():
        files[name] = base / f"{name}.json"
        write_json(files[name], value)

    role_specs = {
        "scheduler": ("GLOBAL_SCHEDULER", "scheduler-1"),
        "analyst": ("MICROARCHITECTURE_ANALYST", "analyst-1"),
        "experimenter": ("EXPERIMENT_AGENT", "experimenter-1"),
    }
    role_paths: dict[str, Path] = {}
    for key, (role_name, actor_id) in role_specs.items():
        role_paths[key] = base / f"role-{key}.json"
        write_json(role_paths[key], role(cycle_id, role_name, actor_id))

    files["registry"] = base / "registry.json"
    write_json(
        files["registry"],
        {
            "schema_version": "community-supervisor-registry-v1",
            "generated_at": "2026-09-09T00:00:00Z",
            "cycle_id": cycle_id,
            "claim_boundary": "FROZEN_TRUST_REGISTRY_NOT_APPROVAL",
            "supervisors": [
                {
                    "supervisor_id": "supervisor-1",
                    "role": "GLOBAL_SUPERVISOR",
                    "status": "ACTIVE",
                    "authorities": ["APPROVE_COMMUNITY_COHORT_DISPATCH"],
                }
            ],
        },
    )
    files["budget"] = base / "budget.json"
    requested_budget = {
        "max_dispatches": 1,
        "max_process_launches": 2,
        "max_wall_clock_seconds": 300.0,
        "max_gpu_seconds": 120.0,
    }
    write_json(
        files["budget"],
        {
            "schema_version": "community-execution-budget-v1",
            "generated_at": "2026-09-09T00:00:00Z",
            "request_id": request_id,
            "cycle_id": cycle_id,
            "claim_boundary": "FROZEN_EXECUTION_BUDGET_NOT_AUTHORIZATION",
            "requested": requested_budget,
            "maximum": {
                "max_dispatches": 1,
                "max_process_launches": 3,
                "max_wall_clock_seconds": 600.0,
                "max_gpu_seconds": 240.0,
            },
        },
    )

    files["decision"] = base / "decision.json"
    write_json(
        files["decision"],
        build_decision(
            base,
            task_key,
            "scheduler-1",
            identity(files["frontier"], base),
            identity(files["objective"], base),
        ),
    )
    files["measurability"] = base / "measurability.json"
    write_json(
        files["measurability"],
        {
            "schema_version": "measurability-contract-v1",
            "status": "READY_FOR_SUPERVISOR",
            "issued_by": {
                "role": "MICROARCHITECTURE_ANALYST",
                "analyst_id": "analyst-1",
            },
            "decision_contract_identity": identity(files["decision"], base),
            "quantity_id": f"{task_key}-quantity",
            "identifiability": "ATOMIC_IDENTIFIABLE",
            "selected_method": "CANDIDATE_AB",
            "observable": {
                "name": "latency",
                "unit": "us",
                "measurement_window": "frozen qualification window",
            },
            "causal_mapping": {
                "formula": "paired control divided by candidate latency",
                "assumptions": [],
                "confounders": [],
                "controls": ["unchanged control"],
                "falsification_condition": "outputs differ",
            },
            "expected_precision": {"absolute": 0.5, "unit": "us"},
            "required_tier": "QUALIFICATION",
            "evidence": [],
        },
    )

    schedule = [
        {
            "order_index": 1,
            "task_id": task_key,
            "repeat_index": 1,
            "arm": "CONTROL",
            "schedule_key": "1" * 64,
        }
    ]
    request = {
        "schema_version": "community-execution-authorization-request-v2",
        "generated_at": "2026-09-09T00:00:00Z",
        "approval_expires_at": "2026-09-09T01:00:00Z",
        "request_id": request_id,
        "cycle_id": cycle_id,
        "claim_boundary": (
            "SEMANTIC_APPROVAL_REQUEST_NOT_AUTHORIZATION_OR_TOKEN_CONSUMPTION"
        ),
        "pre_gpu_gate": identity(files["pre"], base),
        "execution_contract_gate": identity(files["execution"], base),
        "cohort": identity(files["cohort"], base),
        "suite": identity(files["suite"], base),
        "formal_resource_id": "resource-1",
        "tasks": {
            task_key: {
                "task_id": "stable-task-a",
                "experimenter_id": "experimenter-1",
                "formal_gpu_uuids": ["GPU-11111111-1111-1111-1111-111111111111"],
                "sealed_argv": identity(files["sealed"], base),
            }
        },
        "schedule": schedule,
        "supervisor_registry": identity(files["registry"], base),
        "role_artifacts": {
            key: identity(path, base) for key, path in role_paths.items()
        },
        "execution_budget": identity(files["budget"], base),
        "contract_bindings": {
            task_key: {
                "task_id": "stable-task-a",
                "decision_contract": identity(files["decision"], base),
                "measurability_contract": identity(files["measurability"], base),
                "frontier": identity(files["frontier"], base),
                "objective": identity(files["objective"], base),
            }
        },
        "approval_scope_sha256": "0" * 64,
        "single_use_token": "2" * 64,
        "hidden_oracle_exposed": False,
    }
    request["approval_scope_sha256"] = scope_sha256(request)
    files["request"] = base / "request.json"
    write_json(files["request"], request)
    approval = {
        "schema_version": "community-semantic-supervisor-approval-v2",
        "approval_id": "approval-1",
        "status": "APPROVED",
        "issued_at": "2026-09-09T00:01:00Z",
        "expires_at": "2026-09-09T00:30:00Z",
        "claim_boundary": "READY_FOR_ATOMIC_CONSUMPTION_NOT_DISPATCH_AUTHORIZATION",
        "validator_binding": {
            "repository_commit": "f" * 40,
            "request_schema_sha256": "0" * 64,
            "approval_schema_sha256": "0" * 64,
            "registry_schema_sha256": "0" * 64,
            "role_schema_sha256": "0" * 64,
            "budget_schema_sha256": "0" * 64,
            "validator_sha256": "0" * 64,
        },
        "authorization_request": identity(files["request"], base),
        "request_id": request_id,
        "cycle_id": cycle_id,
        "issued_by": {
            "role": "GLOBAL_SUPERVISOR",
            "supervisor_id": "supervisor-1",
        },
        "action": "DISPATCH_FROZEN_COHORT_QUALIFICATION",
        "supervisor_registry": request["supervisor_registry"],
        "role_artifacts": request["role_artifacts"],
        "approved_budget": requested_budget,
        "contract_bindings": request["contract_bindings"],
        "approval_scope_sha256": request["approval_scope_sha256"],
        "single_use_token": request["single_use_token"],
        "single_use": True,
        "hidden_oracle_exposed": False,
    }
    files["approval"] = base / "approval.json"
    write_json(files["approval"], approval)
    return {
        "base": base,
        "files": files,
        "role_paths": role_paths,
        "request": request,
        "approval": approval,
    }


def refresh_request_and_approval(bundle: dict) -> None:
    write_json(bundle["files"]["request"], bundle["request"])
    bundle["approval"]["authorization_request"] = identity(
        bundle["files"]["request"], bundle["base"]
    )
    write_json(bundle["files"]["approval"], bundle["approval"])


@pytest.fixture(autouse=True)
def stub_validator_binding(monkeypatch) -> None:
    monkeypatch.setattr(approval_module, "validate_validator_binding", lambda _: None)


def test_semantic_approval_is_ready_for_atomic_claim_but_never_dispatch() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        bundle = build_bundle(Path(temporary))
        result = validate_approval(bundle["files"]["approval"], bundle["base"])
        assert result["state"] == "READY_FOR_ATOMIC_CONSUMPTION"
        assert result["semantic_approval_ready"] is True
        assert result["atomic_claim_required"] is True
        assert result["gpu_dispatch_authorized"] is False


@pytest.mark.parametrize("mutation", ["issuer", "budget", "predates", "expiry"])
def test_approval_substitutions_fail_closed(mutation: str) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        bundle = build_bundle(Path(temporary))
        if mutation == "issuer":
            bundle["approval"]["issued_by"]["supervisor_id"] = "unknown"
        elif mutation == "budget":
            bundle["approval"]["approved_budget"]["max_gpu_seconds"] = 121.0
        elif mutation == "predates":
            bundle["approval"]["issued_at"] = "2026-09-08T23:59:59Z"
        else:
            bundle["approval"]["expires_at"] = "2026-09-09T02:00:00Z"
        write_json(bundle["files"]["approval"], bundle["approval"])
        with pytest.raises(ValueError):
            validate_approval(bundle["files"]["approval"], bundle["base"])


def test_inactive_supervisor_fails_closed() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        bundle = build_bundle(Path(temporary))
        registry = json.loads(bundle["files"]["registry"].read_text(encoding="utf-8"))
        registry["supervisors"][0]["status"] = "REVOKED"
        write_json(bundle["files"]["registry"], registry)
        bundle["request"]["supervisor_registry"] = identity(
            bundle["files"]["registry"], bundle["base"]
        )
        bundle["approval"]["supervisor_registry"] = bundle["request"][
            "supervisor_registry"
        ]
        refresh_request_and_approval(bundle)
        with pytest.raises(ValueError, match="active registered supervisor"):
            validate_approval(bundle["files"]["approval"], bundle["base"])


def test_role_collision_fails_closed() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        bundle = build_bundle(Path(temporary))
        analyst = role("cycle-1", "MICROARCHITECTURE_ANALYST", "scheduler-1")
        write_json(bundle["role_paths"]["analyst"], analyst)
        measurability = json.loads(
            bundle["files"]["measurability"].read_text(encoding="utf-8")
        )
        measurability["issued_by"]["analyst_id"] = "scheduler-1"
        write_json(bundle["files"]["measurability"], measurability)
        bundle["request"]["role_artifacts"]["analyst"] = identity(
            bundle["role_paths"]["analyst"], bundle["base"]
        )
        bundle["request"]["contract_bindings"]["task-a"]["measurability_contract"] = (
            identity(bundle["files"]["measurability"], bundle["base"])
        )
        bundle["approval"]["role_artifacts"] = copy.deepcopy(
            bundle["request"]["role_artifacts"]
        )
        bundle["approval"]["contract_bindings"] = copy.deepcopy(
            bundle["request"]["contract_bindings"]
        )
        refresh_request_and_approval(bundle)
        with pytest.raises(ValueError, match="must differ"):
            validate_approval(bundle["files"]["approval"], bundle["base"])


def test_budget_cap_and_scope_digest_fail_closed() -> None:
    for mutation in ("cap", "scope"):
        with tempfile.TemporaryDirectory() as temporary:
            bundle = build_bundle(Path(temporary))
            if mutation == "cap":
                budget = json.loads(
                    bundle["files"]["budget"].read_text(encoding="utf-8")
                )
                budget["requested"]["max_gpu_seconds"] = 241.0
                write_json(bundle["files"]["budget"], budget)
                bundle["request"]["execution_budget"] = identity(
                    bundle["files"]["budget"], bundle["base"]
                )
                bundle["approval"]["approved_budget"] = budget["requested"]
            else:
                bundle["request"]["approval_scope_sha256"] = "9" * 64
                bundle["approval"]["approval_scope_sha256"] = "9" * 64
            refresh_request_and_approval(bundle)
            with pytest.raises(ValueError):
                validate_approval(bundle["files"]["approval"], bundle["base"])


def test_contract_bytes_and_relationship_drift_fail_closed() -> None:
    for mutation in ("bytes", "relationship"):
        with tempfile.TemporaryDirectory() as temporary:
            bundle = build_bundle(Path(temporary))
            decision = json.loads(
                bundle["files"]["decision"].read_text(encoding="utf-8")
            )
            if mutation == "bytes":
                decision["stop_rules"].append("changed after approval")
                write_json(bundle["files"]["decision"], decision)
            else:
                alternate = bundle["base"] / "alternate-frontier.json"
                write_json(alternate, {"status": "FROZEN", "alternate": True})
                decision["frontier_identity"] = identity(alternate, bundle["base"])
                write_json(bundle["files"]["decision"], decision)
                measurability = json.loads(
                    bundle["files"]["measurability"].read_text(encoding="utf-8")
                )
                measurability["decision_contract_identity"] = identity(
                    bundle["files"]["decision"], bundle["base"]
                )
                write_json(bundle["files"]["measurability"], measurability)
                binding = bundle["request"]["contract_bindings"]["task-a"]
                binding["decision_contract"] = identity(
                    bundle["files"]["decision"], bundle["base"]
                )
                binding["measurability_contract"] = identity(
                    bundle["files"]["measurability"], bundle["base"]
                )
                bundle["approval"]["contract_bindings"] = copy.deepcopy(
                    bundle["request"]["contract_bindings"]
                )
                refresh_request_and_approval(bundle)
            with pytest.raises(ValueError):
                validate_approval(bundle["files"]["approval"], bundle["base"])


def test_v1_approval_never_auto_upgrades() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        bundle = build_bundle(Path(temporary))
        bundle["approval"]["schema_version"] = "supervisor-approval-v1"
        write_json(bundle["files"]["approval"], bundle["approval"])
        with pytest.raises(ValueError, match="invalid semantic supervisor approval"):
            validate_approval(bundle["files"]["approval"], bundle["base"])


def test_validator_binding_checks_declared_commit_and_worktree(monkeypatch) -> None:
    paths = {
        "request_schema_sha256": f"schemas/{approval_module.REQUEST_SCHEMA}",
        "approval_schema_sha256": f"schemas/{approval_module.APPROVAL_SCHEMA}",
        "registry_schema_sha256": f"schemas/{approval_module.REGISTRY_SCHEMA}",
        "role_schema_sha256": f"schemas/{approval_module.ROLE_SCHEMA}",
        "budget_schema_sha256": f"schemas/{approval_module.BUDGET_SCHEMA}",
        "validator_sha256": approval_module.VALIDATOR_PATH,
    }
    expected = {
        key: sha256_file(ROOT / relative_path) for key, relative_path in paths.items()
    }
    binding = {"repository_commit": "f" * 40, **expected}
    monkeypatch.setattr(approval_module, "require_commit", lambda _: None)
    monkeypatch.setattr(
        approval_module,
        "git_blob_sha256",
        lambda _commit, relative_path: expected[
            next(key for key, value in paths.items() if value == relative_path)
        ],
    )
    REAL_VALIDATE_BINDING(binding)

    declared_drift = copy.deepcopy(binding)
    declared_drift["validator_sha256"] = "e" * 64
    with pytest.raises(ValueError, match="declared commit binding changed"):
        REAL_VALIDATE_BINDING(declared_drift)

    original_sha256_file = approval_module.sha256_file

    def drift_worktree(path: Path) -> str:
        if path.resolve() == (ROOT / approval_module.VALIDATOR_PATH).resolve():
            return "d" * 64
        return original_sha256_file(path)

    monkeypatch.setattr(approval_module, "sha256_file", drift_worktree)
    with pytest.raises(ValueError, match="worktree binding changed"):
        REAL_VALIDATE_BINDING(binding)


def test_real_declared_commit_binding_validates_end_to_end(monkeypatch) -> None:
    monkeypatch.setattr(
        approval_module, "validate_validator_binding", REAL_VALIDATE_BINDING
    )
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        check=True,
        text=True,
    ).stdout.strip()
    paths = {
        "request_schema_sha256": f"schemas/{approval_module.REQUEST_SCHEMA}",
        "approval_schema_sha256": f"schemas/{approval_module.APPROVAL_SCHEMA}",
        "registry_schema_sha256": f"schemas/{approval_module.REGISTRY_SCHEMA}",
        "role_schema_sha256": f"schemas/{approval_module.ROLE_SCHEMA}",
        "budget_schema_sha256": f"schemas/{approval_module.BUDGET_SCHEMA}",
        "validator_sha256": approval_module.VALIDATOR_PATH,
    }
    binding = {"repository_commit": commit}
    for key, relative_path in paths.items():
        blob = subprocess.run(
            ["git", "show", f"{commit}:{relative_path}"],
            cwd=ROOT,
            capture_output=True,
            check=True,
        ).stdout
        binding[key] = hashlib.sha256(blob).hexdigest()

    with tempfile.TemporaryDirectory() as temporary:
        bundle = build_bundle(Path(temporary))
        bundle["approval"]["validator_binding"] = binding
        write_json(bundle["files"]["approval"], bundle["approval"])
        result = validate_approval(bundle["files"]["approval"], bundle["base"])
        assert result["state"] == "READY_FOR_ATOMIC_CONSUMPTION"
        assert result["gpu_dispatch_authorized"] is False
