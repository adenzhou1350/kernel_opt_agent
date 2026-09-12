#!/usr/bin/env python3
"""Tests for governed controller-to-worker CPU materialization transport."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from qualification_environment_materialization import issue_approval  # noqa: E402
from qualification_environment_remote_dispatch import (  # noqa: E402
    dispatch,
    issue_authorization,
    self_identified,
)


NOW = datetime(2026, 9, 13, 1, 0, tzinfo=UTC)
REMOTE_ROOT = "/workspace/kernel-opt/runs/test-run"


def write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, (dict, list)):
        path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    else:
        path.write_text(str(value), encoding="utf-8")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def artifact(path: Path, root: Path) -> dict:
    return {"path": path.relative_to(root).as_posix(), "sha256": digest(path)}


def fixture(tmp_path: Path) -> dict[str, Path]:
    workflow = tmp_path / "workflow.py"
    contract = tmp_path / "workload.json"
    executor = tmp_path / "tools" / "executor.py"
    attestation = tmp_path / "evidence" / "worker.json"
    for path, content in (
        (workflow, "# workflow\n"),
        (contract, "{}\n"),
        (executor, "raise SystemExit(0)\n"),
    ):
        write(path, content)
    write(
        attestation,
        {
            "worker_id": "worker-sm120",
            "host_id": "sm120-a",
            "runtime": {"toolchain": {}},
        },
    )
    request = {
        "schema_version": "qualification-environment-request-v1",
        "candidate_id": "candidate",
        "platform": {
            "os": "linux",
            "architecture": "x86_64",
            "required_cpu_features": [],
            "gpu_visible": True,
        },
        "execution": {
            "workflow_sha256": digest(workflow),
            "test_contract_sha256": digest(contract),
            "image_digest": None,
            "dependency_lock_sha256": "4" * 64,
            "toolchain_lock_sha256": "5" * 64,
            "native_extension_required": False,
            "runtime_provenance": {
                "kind": "ATTESTED_PREPROVISIONED_WORKER",
                "identity_sha256": digest(attestation),
                "worker_id": "worker-sm120",
            },
        },
        "candidate_source": {"tree_sha": "a" * 40, "module_sha256": "6" * 64},
        "allow_native_rebuild": False,
    }
    request_path = tmp_path / "experiments" / "request.json"
    write(request_path, request)
    job = {
        "schema_version": "resource-broker-job-v1",
        "job_id": "candidate-sm120",
        "origin": {
            "thread_id": "thread",
            "lane_id": "megatron-lm",
            "repository": "NVIDIA/Megatron-LM",
            "candidate_id": "candidate",
        },
        "priority_score": 500,
        "dispatch_gate": {"state": "BLOCKED", "identity_sha256": None},
        "resource": {
            "gpu_count": 1,
            "min_memory_gib": 30,
            "architectures": ["sm120"],
            "required_capabilities": ["CUDA"],
            "exclusive_host": False,
        },
        "environment_request": request,
        "budget": {"max_wall_seconds": 1800, "max_gpu_seconds": 1800},
        "callback": {"thread_id": "thread"},
    }
    job_path = tmp_path / "experiments" / "job.json"
    write(job_path, job)
    plan = {
        "schema_version": "qualification-environment-materialization-plan-v2",
        "state": "READY_FOR_SUPERVISOR_REVIEW_NOT_EXECUTED",
        "authorization": {
            "new_job_submission_authorized": False,
            "cpu_only_materialization_authorized": False,
            "forbid_direct_ssh": True,
            "forbid_broker_bind_gate": True,
            "forbid_broker_acquire": True,
            "forbid_gpu_device_mount": True,
            "forbid_workload_launch": True,
        },
        "bound_inputs": {
            "superseding_environment_request": artifact(request_path, tmp_path),
            "superseding_resource_job": artifact(job_path, tmp_path),
            "workflow": artifact(workflow, tmp_path),
            "test_contract": artifact(contract, tmp_path),
        },
        "source": {"git_tree": "a" * 40},
        "runtime_worker": {
            "worker_id": "worker-sm120",
            "host_id": "sm120-a",
            "attestation": artifact(attestation, tmp_path),
        },
        "dependency_and_toolchain": {
            "dependency_lock": {"sha256": "4" * 64},
            "toolchain_lock": {"sha256": "5" * 64},
        },
        "executor": artifact(executor, tmp_path),
        "paths": {"artifact_root": REMOTE_ROOT},
        "budget": {"executor_hard_timeout_seconds": 30},
        "materialization_steps": [
            {
                "id": "prepare",
                "gpu": False,
                "argv": [
                    "/usr/bin/python3",
                    f"{REMOTE_ROOT}/tools/executor.py",
                    "--workflow",
                    f"{REMOTE_ROOT}/workflow.py",
                ],
            }
        ],
    }
    plan_path = tmp_path / "experiments" / "plan.json"
    write(plan_path, plan)
    approval_path = tmp_path / "experiments" / "approval.json"
    approval = issue_approval(
        plan_path=plan_path,
        request_path=request_path,
        job_path=job_path,
        artifact_root=tmp_path,
        supervisor_id="root-controller",
        approval_id="candidate-cpu-materialization-v2",
        issued_at=NOW,
        expires_at=NOW + timedelta(hours=1),
        max_wall_seconds=120,
        network_policy="NONE",
        dispatcher_bound=True,
    )
    write(approval_path, approval)

    tools = {}
    for name in ("ssh", "scp", "known_hosts", "identity"):
        path = tmp_path / "controller" / name
        write(path, name)
        tools[name] = path
    task_files = [
        artifact(path, tmp_path)
        for path in (
            plan_path,
            request_path,
            job_path,
            workflow,
            contract,
            executor,
            attestation,
        )
    ]
    transport = {
        "schema_version": "qualification-environment-remote-transport-plan-v1",
        "plan_id": "test-worker-transport-v1",
        "state": "READY_FOR_SUPERVISOR_REVIEW_NOT_EXECUTED",
        "worker": {
            "worker_id": "worker-sm120",
            "host_id": "sm120-a",
            "address": "worker.example.test",
            "port": 22,
            "user": "root",
            "python": "/usr/bin/python3",
        },
        "controller": {
            "ssh": {"path": str(tools["ssh"]), "sha256": digest(tools["ssh"])},
            "scp": {"path": str(tools["scp"]), "sha256": digest(tools["scp"])},
            "known_hosts": {
                "path": str(tools["known_hosts"]),
                "sha256": digest(tools["known_hosts"]),
            },
            "identity_file": {
                "path": str(tools["identity"]),
                "sha256": digest(tools["identity"]),
            },
        },
        "remote_artifact_root": REMOTE_ROOT,
        "task_files": task_files,
        "budget": {
            "connect_timeout_seconds": 5,
            "transfer_timeout_seconds": 30,
            "total_wall_seconds": 120,
        },
        "claim_boundary": (
            "PINNED_CPU_ONLY_CONTROLLER_TO_WORKER_TRANSPORT_NOT_GPU_BROKER_"
            "WORKLOAD_OR_ENVIRONMENT_SUCCESS_AUTHORIZATION"
        ),
    }
    transport_path = tmp_path / "experiments" / "transport.json"
    write(transport_path, transport)
    authorization_path = tmp_path / "experiments" / "remote-authorization.json"
    authorization = issue_authorization(
        artifact_root=tmp_path,
        approval_path=approval_path,
        transport_plan_path=transport_path,
        supervisor_id="root-controller",
        authorization_id="test-remote-transport-v1",
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=10),
    )
    write(authorization_path, authorization)
    return {
        "approval": approval_path,
        "authorization": authorization_path,
        "plan": plan_path,
        "transport": transport_path,
        "executor": executor,
        "ssh": tools["ssh"],
        "scp": tools["scp"],
    }


def staged_fixture(tmp_path: Path) -> dict[str, Path]:
    paths = fixture(tmp_path)
    plan = json.loads(paths["plan"].read_text(encoding="utf-8"))
    stage_root = "/workspace/kernel-opt/staging/test-run-v2"
    plan["paths"] = {"stage_root": stage_root}
    plan["staged_inputs"] = {
        "executor": {
            "filename": "executor.py",
            "sha256": digest(paths["executor"]),
        },
        "workflow": {
            "filename": "workflow.py",
            "sha256": digest(tmp_path / "workflow.py"),
        },
    }
    plan["materialization_steps"] = [
        {
            "id": "stage-exact-inputs",
            "gpu": False,
            "destination": stage_root,
        },
        {
            "id": "prepare",
            "gpu": False,
            "argv": [
                "/usr/bin/python3",
                f"{stage_root}/executor.py",
                "--workflow",
                f"{stage_root}/workflow.py",
                "--plan",
                f"{stage_root}/plan.json",
                "--approval",
                f"{stage_root}/approval.json",
            ],
        },
    ]
    write(paths["plan"], plan)
    request_path = tmp_path / "experiments" / "request.json"
    job_path = tmp_path / "experiments" / "job.json"
    approval = issue_approval(
        plan_path=paths["plan"],
        request_path=request_path,
        job_path=job_path,
        artifact_root=tmp_path,
        supervisor_id="root-controller",
        approval_id="candidate-staged-cpu-materialization-v2",
        issued_at=NOW,
        expires_at=NOW + timedelta(hours=1),
        max_wall_seconds=120,
        network_policy="NONE",
        dispatcher_bound=True,
    )
    write(paths["approval"], approval)

    transport = json.loads(paths["transport"].read_text(encoding="utf-8"))
    transport["task_files"] = [
        artifact(paths["plan"], tmp_path)
        if item["path"] == "experiments/plan.json"
        else item
        for item in transport["task_files"]
    ]
    transport["staging_copies"] = [
        {
            "source": artifact(source, tmp_path),
            "destination": f"{stage_root}/{destination}",
        }
        for source, destination in (
            (paths["executor"], "executor.py"),
            (tmp_path / "workflow.py", "workflow.py"),
            (paths["plan"], "plan.json"),
            (paths["approval"], "approval.json"),
        )
    ]
    write(paths["transport"], transport)
    authorization = issue_authorization(
        artifact_root=tmp_path,
        approval_path=paths["approval"],
        transport_plan_path=paths["transport"],
        supervisor_id="root-controller",
        authorization_id="test-staged-remote-transport-v1",
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=10),
    )
    write(paths["authorization"], authorization)
    return paths


class FakeTransport:
    def __init__(
        self,
        paths: dict[str, Path],
        *,
        worker_exit: int = 0,
        worker_terminal: bool = True,
    ) -> None:
        self.paths = paths
        self.worker_exit = worker_exit
        self.worker_terminal = worker_terminal
        self.remote: dict[str, bytes] = {}
        self.calls: list[list[str]] = []

    def worker_artifacts(self) -> None:
        approval = json.loads(self.paths["approval"].read_text(encoding="utf-8"))
        approval_sha = digest(self.paths["approval"])
        claim_relative = f".kernel-opt/materialization-claims/{approval_sha}.claim.json"
        claim = self_identified(
            {
                "schema_version": "qualification-environment-materialization-claim-v1",
                "claimed_at": "2026-09-13T01:00:01Z",
                "approval": {
                    "path": self.paths["approval"]
                    .relative_to(self.paths["approval"].parents[1])
                    .as_posix(),
                    "sha256": approval_sha,
                },
                "materialization_plan": approval["materialization_plan"],
                "dispatcher_sha256": approval["dispatcher_sha256"],
                "argv_sha256": "a" * 64,
                "single_use": True,
                "claim_boundary": (
                    "ATOMIC_SINGLE_USE_CPU_ONLY_MATERIALIZATION_CLAIM_NOT_"
                    "ENVIRONMENT_SUCCESS_GPU_OR_WORKLOAD_AUTHORIZATION"
                ),
            },
            "claim_id",
        )
        claim_bytes = (json.dumps(claim, indent=2, sort_keys=True) + "\n").encode()
        receipt = self_identified(
            {
                "schema_version": (
                    "qualification-environment-materialization-dispatch-receipt-v2"
                ),
                "started_at": "2026-09-13T01:00:01Z",
                "completed_at": "2026-09-13T01:00:02Z",
                "duration_seconds": 1.0,
                "claim": {
                    "path": claim_relative,
                    "sha256": hashlib.sha256(claim_bytes).hexdigest(),
                },
                "state": "EXECUTOR_COMPLETED",
                "exit_code": 0,
                "timed_out": False,
                "stdout": {"bytes": 0, "sha256": hashlib.sha256(b"").hexdigest()},
                "stderr": {"bytes": 0, "sha256": hashlib.sha256(b"").hexdigest()},
                "gpu_authorized": False,
                "workload_authorized": False,
                "broker_mutated": False,
                "claim_boundary": (
                    "EXECUTOR_PROCESS_TERMINAL_STATUS_ONLY_NOT_ENVIRONMENT_"
                    "CORRECTNESS_PERFORMANCE_GPU_OR_WORKLOAD_EVIDENCE"
                ),
            },
            "receipt_id",
        )
        self.remote[f"{REMOTE_ROOT}/{claim_relative}"] = claim_bytes
        self.remote[
            f"{REMOTE_ROOT}/.kernel-opt/materialization-claims/{approval_sha}.receipt.json"
        ] = (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode()

    def __call__(self, argv: list[str], **kwargs) -> subprocess.CompletedProcess[bytes]:
        self.calls.append(argv)
        executable = Path(argv[0])
        if executable == self.paths["ssh"]:
            command = argv[-1]
            if "if test -e" in command:
                return subprocess.CompletedProcess(argv, 0, b"ABSENT\n", b"")
            if command.startswith("/usr/bin/python3 ") and (
                "qualification_environment_materialization_dispatch.py" in command
            ):
                if self.worker_terminal:
                    self.worker_artifacts()
                return subprocess.CompletedProcess(
                    argv, self.worker_exit, b"", b"worker"
                )
            return subprocess.CompletedProcess(argv, 0, b"", b"")
        if executable == self.paths["scp"]:
            source, destination = argv[-2:]
            if source.startswith("root@"):
                remote_path = source.split(":", 1)[1]
                Path(destination).write_bytes(self.remote[remote_path])
            else:
                remote_path = destination.split(":", 1)[1]
                self.remote[remote_path] = Path(source).read_bytes()
            return subprocess.CompletedProcess(argv, 0, b"", b"")
        raise AssertionError(f"unexpected executable: {executable}")


def test_issue_binds_worker_and_task_file_closure(tmp_path: Path) -> None:
    paths = fixture(tmp_path)
    authorization = json.loads(paths["authorization"].read_text(encoding="utf-8"))
    assert authorization["decision"] == "APPROVED"
    assert authorization["constraints"] == {
        "gpu": False,
        "workload": False,
        "broker": False,
        "service_mutation": False,
        "retry_after_claim": False,
    }

    transport = json.loads(paths["transport"].read_text(encoding="utf-8"))
    transport["task_files"] = [
        item for item in transport["task_files"] if item["path"] != "workflow.py"
    ]
    write(paths["transport"], transport)
    with pytest.raises(ValueError, match="omits bound task files"):
        issue_authorization(
            artifact_root=tmp_path,
            approval_path=paths["approval"],
            transport_plan_path=paths["transport"],
            supervisor_id="root-controller",
            authorization_id="invalid",
            issued_at=NOW,
            expires_at=NOW + timedelta(minutes=10),
        )


def test_dispatch_retrieves_worker_terminal_and_consumes_once(tmp_path: Path) -> None:
    paths = fixture(tmp_path)
    fake = FakeTransport(paths)
    result = dispatch(
        artifact_root=tmp_path,
        authorization_path=paths["authorization"],
        expected_authorization_sha256=digest(paths["authorization"]),
        now=NOW,
        runner=fake,
    )
    assert result["state"] == "WORKER_TERMINAL_RETRIEVED"
    assert result["gpu_authorized"] is False
    assert result["workload_authorized"] is False
    assert result["broker_mutated"] is False
    assert result["retry_authorized"] is False
    assert result["worker_terminal_receipt"] is not None
    assert any(row["stage"] == "WORKER_DISPATCH" for row in result["commands"])
    assert all("StrictHostKeyChecking=yes" in call for call in fake.calls)

    with pytest.raises(FileExistsError, match="already has a receipt"):
        dispatch(
            artifact_root=tmp_path,
            authorization_path=paths["authorization"],
            expected_authorization_sha256=digest(paths["authorization"]),
            now=NOW,
            runner=fake,
        )


def test_explicit_staging_layout_runs_without_rewriting_frozen_plan(
    tmp_path: Path,
) -> None:
    paths = staged_fixture(tmp_path)
    fake = FakeTransport(paths)
    result = dispatch(
        artifact_root=tmp_path,
        authorization_path=paths["authorization"],
        expected_authorization_sha256=digest(paths["authorization"]),
        now=NOW,
        runner=fake,
    )
    assert result["state"] == "WORKER_TERMINAL_RETRIEVED"
    transferred = [call[-1] for call in fake.calls if Path(call[0]) == paths["scp"]]
    assert any(
        "/workspace/kernel-opt/staging/test-run-v2/executor.py" in row
        for row in transferred
    )
    assert any(
        "/workspace/kernel-opt/staging/test-run-v2/approval.json" in row
        for row in transferred
    )


def test_staging_layout_requires_every_declared_input(tmp_path: Path) -> None:
    paths = staged_fixture(tmp_path)
    transport = json.loads(paths["transport"].read_text(encoding="utf-8"))
    transport["staging_copies"] = [
        row
        for row in transport["staging_copies"]
        if not row["destination"].endswith("/workflow.py")
    ]
    write(paths["transport"], transport)
    with pytest.raises(ValueError, match="omit declared staged inputs: workflow.py"):
        issue_authorization(
            artifact_root=tmp_path,
            approval_path=paths["approval"],
            transport_plan_path=paths["transport"],
            supervisor_id="root-controller",
            authorization_id="missing-staged-input",
            issued_at=NOW,
            expires_at=NOW + timedelta(minutes=10),
        )


def test_staging_layout_requires_plan_and_approval_argv_inputs(tmp_path: Path) -> None:
    paths = staged_fixture(tmp_path)
    transport = json.loads(paths["transport"].read_text(encoding="utf-8"))
    transport["staging_copies"] = [
        row
        for row in transport["staging_copies"]
        if not row["destination"].endswith("/approval.json")
    ]
    write(paths["transport"], transport)
    with pytest.raises(ValueError, match="omit sealed argv inputs: .*approval.json"):
        issue_authorization(
            artifact_root=tmp_path,
            approval_path=paths["approval"],
            transport_plan_path=paths["transport"],
            supervisor_id="root-controller",
            authorization_id="missing-approval-copy",
            issued_at=NOW,
            expires_at=NOW + timedelta(minutes=10),
        )


def test_staging_layout_rejects_destination_outside_declared_root(
    tmp_path: Path,
) -> None:
    paths = staged_fixture(tmp_path)
    transport = json.loads(paths["transport"].read_text(encoding="utf-8"))
    transport["staging_copies"][0]["destination"] = "/tmp/executor.py"
    write(paths["transport"], transport)
    with pytest.raises(ValueError, match="outside declared staging roots"):
        issue_authorization(
            artifact_root=tmp_path,
            approval_path=paths["approval"],
            transport_plan_path=paths["transport"],
            supervisor_id="root-controller",
            authorization_id="escaped-staging-input",
            issued_at=NOW,
            expires_at=NOW + timedelta(minutes=10),
        )


def test_identity_drift_fails_before_claim(tmp_path: Path) -> None:
    paths = fixture(tmp_path)
    paths["executor"].write_text("raise SystemExit(1)\n", encoding="utf-8")
    with pytest.raises(ValueError, match="hash changed"):
        dispatch(
            artifact_root=tmp_path,
            authorization_path=paths["authorization"],
            expected_authorization_sha256=digest(paths["authorization"]),
            now=NOW,
            runner=FakeTransport(paths),
        )
    assert not (tmp_path / ".kernel-opt" / "remote-materialization-claims").exists()


def test_worker_runtime_drift_fails_before_claim(tmp_path: Path) -> None:
    paths = fixture(tmp_path)
    authorization = json.loads(paths["authorization"].read_text(encoding="utf-8"))
    authorization["worker_runtime_sha256"] = "0" * 64
    write(paths["authorization"], authorization)
    with pytest.raises(ValueError, match="another worker runtime"):
        dispatch(
            artifact_root=tmp_path,
            authorization_path=paths["authorization"],
            expected_authorization_sha256=digest(paths["authorization"]),
            now=NOW,
            runner=FakeTransport(paths),
        )
    assert not (tmp_path / ".kernel-opt" / "remote-materialization-claims").exists()


def test_prelaunch_failure_is_terminal_and_not_retryable(tmp_path: Path) -> None:
    paths = fixture(tmp_path)

    calls = 0

    def fail_first(argv: list[str], **kwargs) -> subprocess.CompletedProcess[bytes]:
        nonlocal calls
        calls += 1
        return subprocess.CompletedProcess(
            argv, 0 if calls == 1 else 2, b"" if calls == 1 else b"", b"offline"
        )

    result = dispatch(
        artifact_root=tmp_path,
        authorization_path=paths["authorization"],
        expected_authorization_sha256=digest(paths["authorization"]),
        now=NOW,
        runner=fail_first,
    )
    assert result["state"] == "FAILED_PRELAUNCH_CONSUMED"
    assert result["retry_authorized"] is False


def test_offline_worker_does_not_consume_authorization(tmp_path: Path) -> None:
    paths = fixture(tmp_path)

    def offline(argv: list[str], **kwargs) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(argv, 255, b"", b"offline")

    with pytest.raises(Exception, match="command exited 255"):
        dispatch(
            artifact_root=tmp_path,
            authorization_path=paths["authorization"],
            expected_authorization_sha256=digest(paths["authorization"]),
            now=NOW,
            runner=offline,
        )
    assert not (tmp_path / ".kernel-opt" / "remote-materialization-claims").exists()


def test_worker_launch_without_terminal_is_ambiguous_consumed(tmp_path: Path) -> None:
    paths = fixture(tmp_path)
    result = dispatch(
        artifact_root=tmp_path,
        authorization_path=paths["authorization"],
        expected_authorization_sha256=digest(paths["authorization"]),
        now=NOW,
        runner=FakeTransport(paths, worker_exit=2, worker_terminal=False),
    )
    assert result["state"] == "AMBIGUOUS_POSTLAUNCH_CONSUMED"
    assert result["worker_terminal_receipt"] is None
    assert result["retry_authorized"] is False


def test_nonzero_worker_exit_still_retrieves_terminal_receipt(tmp_path: Path) -> None:
    paths = fixture(tmp_path)
    result = dispatch(
        artifact_root=tmp_path,
        authorization_path=paths["authorization"],
        expected_authorization_sha256=digest(paths["authorization"]),
        now=NOW,
        runner=FakeTransport(paths, worker_exit=1),
    )
    assert result["state"] == "WORKER_TERMINAL_RETRIEVED"
    assert (
        next(row for row in result["commands"] if row["stage"] == "WORKER_DISPATCH")[
            "exit_code"
        ]
        == 1
    )


def test_controller_or_authorization_expiry_fails_before_claim(tmp_path: Path) -> None:
    paths = fixture(tmp_path)
    with pytest.raises(ValueError, match="not currently valid"):
        dispatch(
            artifact_root=tmp_path,
            authorization_path=paths["authorization"],
            expected_authorization_sha256=digest(paths["authorization"]),
            now=NOW + timedelta(hours=2),
            runner=FakeTransport(paths),
        )
