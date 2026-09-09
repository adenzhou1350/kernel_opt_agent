from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import community_execution_authorization as authorization_module  # noqa: E402
import community_meta_cycle_report as legacy_report_module  # noqa: E402
import kernel_opt  # noqa: E402
from community_execution_authorization import (  # noqa: E402
    AUTHORIZATION_SCHEMA,
    REQUEST_SCHEMA,
    validate_authorization,
    validate_dispatch_receipt,
    validate_observation_provenance,
)
from community_knowledge import sha256_file  # noqa: E402


def write_json(path: Path, value: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def identity(path: Path, base: Path) -> dict:
    return {"path": path.relative_to(base).as_posix(), "sha256": sha256_file(path)}


def approval(request_identity: dict) -> dict:
    placeholder = {"path": "not-resolved-by-this-layer.json", "sha256": "0" * 64}
    return {
        "schema_version": "supervisor-approval-v1",
        "approval_id": "approval-1",
        "status": "APPROVED",
        "issued_at": "2026-09-09T00:00:00Z",
        "issued_by": {"role": "GLOBAL_SUPERVISOR", "supervisor_id": "supervisor-1"},
        "request_id": "request-1",
        "action": "DISPATCH_QUALIFICATION",
        "experiment_identity": request_identity,
        "decision_contract_identity": placeholder,
        "measurability_contract_identity": placeholder,
        "frontier_identity": placeholder,
        "objective_identity": placeholder,
        "approved_budget": {
            "max_configurations": 1,
            "max_samples_per_configuration": 1,
            "max_process_launches": 1,
            "max_wall_clock_minutes": 1,
        },
        "separation_of_duties": {
            "scheduler_id": "scheduler-1",
            "analyst_id": "analyst-1",
            "experimenter_id": "experimenter-1",
            "all_distinct": True,
        },
        "gate_results": [{"gate": "P_AND_E", "status": "PASS"}],
        "rationale": "Synthetic approval for validator coverage.",
        "single_use": True,
    }


def stub_canonical_gate_validators(monkeypatch) -> None:
    def validate_pre(path: Path, _root: Path) -> dict:
        value = json.loads(path.read_text(encoding="utf-8"))
        return {
            "state": value["state"],
            "eligible_to_execute_arms": value["eligible_to_execute_arms"],
        }

    def validate_execution(path: Path, _root: Path) -> dict:
        value = json.loads(path.read_text(encoding="utf-8"))
        return {
            "state": value["state"],
            "eligible_by_this_gate": value["eligible_by_this_gate"],
        }

    monkeypatch.setattr(
        authorization_module, "validate_canonical_pre_gpu_readiness", validate_pre
    )
    monkeypatch.setattr(
        authorization_module,
        "validate_canonical_execution_readiness",
        validate_execution,
    )
    blob_hashes = {
        f"schemas/{REQUEST_SCHEMA}": sha256_file(ROOT / "schemas" / REQUEST_SCHEMA),
        f"schemas/{AUTHORIZATION_SCHEMA}": sha256_file(
            ROOT / "schemas" / AUTHORIZATION_SCHEMA
        ),
        "scripts/community_execution_authorization.py": sha256_file(
            ROOT / "scripts" / "community_execution_authorization.py"
        ),
    }
    monkeypatch.setattr(
        authorization_module,
        "git_blob_sha256",
        lambda _commit, relative_path: blob_hashes[relative_path],
    )


def stub_authorized_bundle(monkeypatch, bundle: dict) -> None:
    monkeypatch.setattr(
        authorization_module,
        "validate_authorization",
        lambda _path, _root: {
            "authorization": bundle["authorization"],
            "request": bundle["request"],
            "suite": {"suite_id": "suite-1"},
            "allowed": True,
        },
    )


def build_bundle(
    base: Path, p_ready: bool, e_ready: bool, a_ready: bool
) -> tuple[Path, dict]:
    suite_path = base / "suite.json"
    sealed_path = base / "sealed-argv.json"
    write_json(suite_path, {"suite_id": "suite-1"})
    write_json(sealed_path, ["python", "runner.py"])
    schedule = [
        {
            "order_index": 1,
            "task_id": "task-key",
            "repeat_index": 1,
            "arm": "CONTROL",
            "schedule_key": "1" * 64,
        }
    ]
    cohort_path = base / "cohort.json"
    write_json(
        cohort_path,
        {
            "cycle_id": "cycle-1",
            "primary_tasks": [{"task_id": "task-key"}],
            "randomized_schedule": {"entries": schedule},
        },
    )
    pre_path = base / "pre.json"
    pre = {
        "cycle_id": "cycle-1",
        "state": "PRE_GPU_GATE_READY" if p_ready else "PRE_GPU_GATE_BLOCKED",
        "eligible_to_execute_arms": p_ready,
        "protocol_binding": {"temporal_suite": identity(suite_path, base)},
        "cohort_binding": {"cohort_freeze_sha256": sha256_file(cohort_path)},
        "formal_resource": {"resource_id": "resource-1"},
        "task_freezes": {
            "task-key": {
                "task_id": "stable-task-id",
                "formal_gpu_uuids": ["GPU-11111111-1111-1111-1111-111111111111"],
            }
        },
    }
    write_json(pre_path, pre)
    execution_path = base / "execution.json"
    execution = {
        "cycle_id": "cycle-1",
        "state": "EXECUTION_CONTRACT_READY"
        if e_ready
        else "EXECUTION_CONTRACT_BLOCKED",
        "eligible_by_this_gate": e_ready,
        "base_readiness": identity(pre_path, base),
        "tasks": {
            "task-key": {
                "task_id": "stable-task-id",
                "sealed_argv": identity(sealed_path, base),
            }
        },
    }
    write_json(execution_path, execution)
    request_path = base / "request.json"
    request = {
        "schema_version": "community-execution-authorization-request-v1",
        "generated_at": "2026-09-09T00:00:00Z",
        "cycle_id": "cycle-1",
        "claim_boundary": "FROZEN_DISPATCH_REQUEST_NOT_AUTHORIZATION_OR_EXECUTION",
        "pre_gpu_gate": identity(pre_path, base),
        "execution_contract_gate": identity(execution_path, base),
        "cohort": identity(cohort_path, base),
        "suite": identity(suite_path, base),
        "formal_resource_id": "resource-1",
        "tasks": {
            "task-key": {
                "task_id": "stable-task-id",
                "formal_gpu_uuids": ["GPU-11111111-1111-1111-1111-111111111111"],
                "sealed_argv": identity(sealed_path, base),
            }
        },
        "schedule": schedule,
        "hidden_oracle_exposed": False,
    }
    write_json(request_path, request)
    request_identity = identity(request_path, base)
    approval_identity = None
    if a_ready:
        approval_path = base / "approval.json"
        write_json(approval_path, approval(request_identity))
        approval_identity = identity(approval_path, base)
    authorization_path = base / "authorization.json"
    allowed = p_ready and e_ready and a_ready
    authorization = {
        "schema_version": "community-combined-execution-authorization-v1",
        "generated_at": "2026-09-09T00:00:01Z",
        "cycle_id": "cycle-1",
        "state": "DISPATCH_AUTHORIZED" if allowed else "DISPATCH_BLOCKED",
        "claim_boundary": (
            "P_AND_E_AND_A_DISPATCH_GATE_NOT_EXECUTION_OR_RESULT_EVIDENCE"
        ),
        "validator_binding": {
            "repository_commit": "96f86f0444f6ad354167f4c2a7e2dd00277f3d73",
            "request_schema_sha256": sha256_file(ROOT / "schemas" / REQUEST_SCHEMA),
            "authorization_schema_sha256": sha256_file(
                ROOT / "schemas" / AUTHORIZATION_SCHEMA
            ),
            "validator_sha256": sha256_file(
                ROOT / "scripts" / "community_execution_authorization.py"
            ),
        },
        "authorization_request": request_identity,
        "pre_gpu_gate": request["pre_gpu_gate"],
        "execution_contract_gate": request["execution_contract_gate"],
        "supervisor_approval": approval_identity,
        "gate_decisions": {
            "pre_gpu_ready": p_ready,
            "execution_contract_ready": e_ready,
            "independent_supervisor_approved": a_ready,
        },
        "remaining_blockers": [] if allowed else ["P_AND_E_AND_A_NOT_ALL_TRUE"],
        "gpu_dispatch_authorized": allowed,
        "hidden_oracle_exposed": False,
        "execution": {
            "compile_started": False,
            "gpu_started": False,
            "gpu_seconds": 0.0,
        },
    }
    write_json(authorization_path, authorization)
    return authorization_path, {
        "request": request,
        "authorization": authorization,
        "base": base,
    }


def test_v1_never_authorizes_unbound_supervisor_approval(monkeypatch) -> None:
    stub_canonical_gate_validators(monkeypatch)
    for p_ready in (False, True):
        for e_ready in (False, True):
            for a_ready in (False, True):
                with tempfile.TemporaryDirectory() as temporary:
                    path, _ = build_bundle(Path(temporary), p_ready, e_ready, a_ready)
                    if a_ready:
                        try:
                            validate_authorization(path, Path(temporary))
                        except ValueError as error:
                            assert "semantic-approval contract" in str(error)
                        else:
                            raise AssertionError(
                                "v1 must reject an unbound supervisor approval"
                            )
                    else:
                        result = validate_authorization(path, Path(temporary))
                        assert result["allowed"] is False


def test_request_rejects_uuid_and_sealed_argv_drift(monkeypatch) -> None:
    stub_canonical_gate_validators(monkeypatch)
    for mutation in ("uuid", "argv"):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            path, bundle = build_bundle(base, True, True, True)
            request_path = (
                base / bundle["authorization"]["authorization_request"]["path"]
            )
            request = copy.deepcopy(bundle["request"])
            if mutation == "uuid":
                request["tasks"]["task-key"]["formal_gpu_uuids"] = [
                    "GPU-22222222-2222-2222-2222-222222222222"
                ]
            else:
                alternate = base / "alternate-argv.json"
                write_json(alternate, ["python", "other.py"])
                request["tasks"]["task-key"]["sealed_argv"] = identity(alternate, base)
            write_json(request_path, request)
            authorization = bundle["authorization"]
            authorization["authorization_request"] = identity(request_path, base)
            approval_path = base / authorization["supervisor_approval"]["path"]
            write_json(approval_path, approval(authorization["authorization_request"]))
            authorization["supervisor_approval"] = identity(approval_path, base)
            write_json(path, authorization)
            try:
                validate_authorization(path, base)
            except ValueError as error:
                assert "drift" in str(error)
            else:
                raise AssertionError(f"{mutation} drift must fail closed")


def test_dispatch_receipt_requires_authorized_exact_schedule(monkeypatch) -> None:
    stub_canonical_gate_validators(monkeypatch)
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        authorization_path, bundle = build_bundle(base, True, True, True)
        stub_authorized_bundle(monkeypatch, bundle)
        receipt_path = base / "receipt.json"
        write_json(
            receipt_path,
            {
                "schema_version": "community-dispatch-receipt-v1",
                "dispatched_at": "2026-09-09T00:01:00Z",
                "claim_boundary": "IMMUTABLE_DISPATCH_PROVENANCE_NOT_RESULT_EVIDENCE",
                "cycle_id": "cycle-1",
                "suite_id": "suite-1",
                "task_key": "task-key",
                "task_id": "stable-task-id",
                "repeat_index": 1,
                "arm": "CONTROL",
                "order_index": 1,
                "schedule_key": "1" * 64,
                "combined_authorization": identity(authorization_path, base),
                "authorization_request": bundle["authorization"][
                    "authorization_request"
                ],
                "sealed_argv": bundle["request"]["tasks"]["task-key"]["sealed_argv"],
                "dispatcher_id": "community-dispatcher-1",
                "state": "DISPATCHED",
            },
        )
        assert (
            validate_dispatch_receipt(receipt_path, base)["receipt"]["state"]
            == "DISPATCHED"
        )
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["schedule_key"] = "2" * 64
        write_json(receipt_path, receipt)
        try:
            validate_dispatch_receipt(receipt_path, base)
        except ValueError as error:
            assert "schedule" in str(error)
        else:
            raise AssertionError("schedule drift must fail closed")


def test_dispatch_receipt_rejects_cycle_and_suite_substitution(monkeypatch) -> None:
    stub_canonical_gate_validators(monkeypatch)
    for field, replacement in (
        ("cycle_id", "foreign-cycle"),
        ("suite_id", "foreign-suite"),
    ):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            authorization_path, bundle = build_bundle(base, True, True, True)
            stub_authorized_bundle(monkeypatch, bundle)
            receipt_path = base / "receipt.json"
            receipt = {
                "schema_version": "community-dispatch-receipt-v1",
                "dispatched_at": "2026-09-09T00:01:00Z",
                "claim_boundary": "IMMUTABLE_DISPATCH_PROVENANCE_NOT_RESULT_EVIDENCE",
                "cycle_id": "cycle-1",
                "suite_id": "suite-1",
                "task_key": "task-key",
                "task_id": "stable-task-id",
                "repeat_index": 1,
                "arm": "CONTROL",
                "order_index": 1,
                "schedule_key": "1" * 64,
                "combined_authorization": identity(authorization_path, base),
                "authorization_request": bundle["authorization"][
                    "authorization_request"
                ],
                "sealed_argv": bundle["request"]["tasks"]["task-key"]["sealed_argv"],
                "dispatcher_id": "community-dispatcher-1",
                "state": "DISPATCHED",
            }
            receipt[field] = replacement
            write_json(receipt_path, receipt)
            try:
                validate_dispatch_receipt(receipt_path, base)
            except ValueError as error:
                assert field.removesuffix("_id") in str(error)
            else:
                raise AssertionError(f"{field} substitution must fail closed")


def test_authorization_rejects_noncanonical_gate_artifacts(monkeypatch) -> None:
    blob_hashes = {
        f"schemas/{REQUEST_SCHEMA}": sha256_file(ROOT / "schemas" / REQUEST_SCHEMA),
        f"schemas/{AUTHORIZATION_SCHEMA}": sha256_file(
            ROOT / "schemas" / AUTHORIZATION_SCHEMA
        ),
        "scripts/community_execution_authorization.py": sha256_file(
            ROOT / "scripts" / "community_execution_authorization.py"
        ),
    }
    monkeypatch.setattr(
        authorization_module,
        "git_blob_sha256",
        lambda _commit, relative_path: blob_hashes[relative_path],
    )
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        authorization_path, _ = build_bundle(base, True, True, True)
        try:
            validate_authorization(authorization_path, base)
        except ValueError as error:
            assert "pre-GPU readiness schema" in str(error)
        else:
            raise AssertionError("noncanonical P/E artifacts must fail closed")


def test_git_blob_hash_reads_declared_commit_bytes() -> None:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        check=True,
        text=True,
    ).stdout.strip()
    relative_path = f"schemas/{REQUEST_SCHEMA}"
    blob = subprocess.run(
        ["git", "show", f"{commit}:{relative_path}"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    ).stdout
    assert (
        authorization_module.git_blob_sha256(commit, relative_path)
        == hashlib.sha256(blob).hexdigest()
    )


def test_authorization_rejects_declared_commit_blob_drift(monkeypatch) -> None:
    stub_canonical_gate_validators(monkeypatch)
    monkeypatch.setattr(
        authorization_module,
        "git_blob_sha256",
        lambda _commit, _relative_path: "f" * 64,
    )
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        path, _ = build_bundle(base, False, True, False)
        try:
            validate_authorization(path, base)
        except ValueError as error:
            assert "declared commit binding changed" in str(error)
        else:
            raise AssertionError("declared commit blob drift must fail closed")


def test_authorization_rejects_worktree_binding_drift(monkeypatch) -> None:
    stub_canonical_gate_validators(monkeypatch)
    original_sha256_file = authorization_module.sha256_file

    def drift_validator(path: Path) -> str:
        if path.resolve() == Path(authorization_module.__file__).resolve():
            return "e" * 64
        return original_sha256_file(path)

    monkeypatch.setattr(authorization_module, "sha256_file", drift_validator)
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        path, _ = build_bundle(base, False, True, False)
        try:
            validate_authorization(path, base)
        except ValueError as error:
            assert "worktree binding changed" in str(error)
        else:
            raise AssertionError("worktree binding drift must fail closed")


def test_observation_provenance_rejects_missing_dispatch_receipt() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        path = base / "observation-provenance.json"
        write_json(
            path,
            {
                "schema_version": "community-work-cycle-observation-provenance-v2",
                "generated_at": "2026-09-09T00:02:00Z",
                "claim_boundary": "OBSERVATION_WITH_AUTHORIZED_DISPATCH_PROVENANCE",
                "observation": {"path": "observation.json", "sha256": "0" * 64},
            },
        )
        try:
            validate_observation_provenance(path, base)
        except ValueError as error:
            assert "dispatch_receipt" in str(error)
        else:
            raise AssertionError(
                "observation without a dispatch receipt must fail closed"
            )


def test_public_policy_report_command_requires_provenance() -> None:
    canonical = kernel_opt.COMMANDS["community-cycle-report"]
    assert canonical.script == "community_execution_authorization.py"
    assert canonical.prefix_args == ("validate-report",)
    legacy = kernel_opt.COMMANDS["community-cycle-report-legacy"]
    assert legacy.script == "community_meta_cycle_report.py"
    assert legacy.prefix_args == ()


def test_legacy_report_cli_is_explicitly_non_actionable(
    monkeypatch, capsys, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        legacy_report_module,
        "validate_report",
        lambda _report, _root: {
            "cycle_id": "cycle-1",
            "decision": {"outcome": "PROMOTE_DEFAULT"},
        },
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "community_meta_cycle_report.py",
            "validate",
            "--report",
            str(tmp_path / "report.json"),
            "--evidence-root",
            str(tmp_path),
        ],
    )
    assert legacy_report_module.main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output["mode"] == "LEGACY_HISTORICAL_REPLAY"
    assert output["actionable_policy_decision"] is False
    assert output["historical_outcome"] == "PROMOTE_DEFAULT"
