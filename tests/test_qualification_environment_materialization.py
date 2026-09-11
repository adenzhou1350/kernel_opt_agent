#!/usr/bin/env python3
"""Tests for CPU-only qualification environment materialization approval."""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from qualification_environment_materialization import (  # noqa: E402
    issue_approval,
    validate_approval,
    validate_plan_bundle,
)


NOW = datetime(2026, 9, 11, 9, 30, tzinfo=UTC)


def write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    tree = "a" * 40
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
            "workflow_sha256": "1" * 64,
            "test_contract_sha256": "2" * 64,
            "image_digest": "sha256:" + "3" * 64,
            "dependency_lock_sha256": "4" * 64,
            "toolchain_lock_sha256": "5" * 64,
            "native_extension_required": True,
        },
        "candidate_source": {"tree_sha": tree, "module_sha256": "6" * 64},
        "allow_native_rebuild": True,
    }
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
    request_path = tmp_path / "experiments" / "request.json"
    job_path = tmp_path / "experiments" / "job.json"
    write(request_path, request)
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
            "superseding_environment_request": {
                "path": "experiments/request.json",
                "sha256": digest(request_path),
            },
            "superseding_resource_job": {
                "path": "experiments/job.json",
                "sha256": digest(job_path),
            },
            "workflow": {"path": "workflow.py", "sha256": "1" * 64},
            "test_contract": {"path": "workload.json", "sha256": "2" * 64},
        },
        "source": {"git_tree": tree},
        "runtime_image": {"platform_manifest_digest": "sha256:" + "3" * 64},
        "dependency_and_toolchain": {
            "dependency_lock": {"sha256": "4" * 64},
            "toolchain_lock": {"sha256": "5" * 64},
        },
        "materialization_steps": [{"id": "prepare", "gpu": False}],
    }
    plan_path = tmp_path / "experiments" / "plan.json"
    write(plan_path, plan)
    approval_path = tmp_path / "experiments" / "approval.json"
    return plan_path, request_path, job_path, approval_path


def issue(tmp_path: Path) -> tuple[dict, Path]:
    plan, request, job, approval_path = fixture(tmp_path)
    approval = issue_approval(
        plan_path=plan,
        request_path=request,
        job_path=job,
        artifact_root=tmp_path,
        supervisor_id="root-controller",
        approval_id="candidate-cpu-materialization-v1",
        issued_at=NOW,
        expires_at=NOW + timedelta(hours=2),
        max_wall_seconds=3600,
        network_policy="DEPENDENCY_MATERIALIZATION_ONLY",
    )
    write(approval_path, approval)
    return approval, approval_path


def test_issue_and_validate_preserves_non_gpu_boundary(tmp_path: Path) -> None:
    approval, approval_path = issue(tmp_path)
    result = validate_approval(approval_path, tmp_path, now=NOW)
    assert result["state"] == "CPU_ONLY_ENVIRONMENT_MATERIALIZATION_AUTHORIZED"
    assert result["gpu_authorized"] is False
    assert result["workload_authorized"] is False
    assert result["broker_submission_authorized"] is False
    assert set(approval["constraints"].values()) == {False}


@pytest.mark.parametrize(
    "mutation, message",
    [
        (
            lambda plan, request, job: plan["materialization_steps"][0].__setitem__(
                "gpu", True
            ),
            "gpu=false",
        ),
        (
            lambda plan, request, job: plan["authorization"].__setitem__(
                "forbid_broker_acquire", False
            ),
            "CPU-only",
        ),
        (
            lambda plan, request, job: job.__setitem__(
                "dispatch_gate", {"state": "READY", "identity_sha256": "9" * 64}
            ),
            "blocked resource job",
        ),
        (
            lambda plan, request, job: (
                request["candidate_source"].__setitem__("tree_sha", "b" * 40),
                job["environment_request"]["candidate_source"].__setitem__(
                    "tree_sha", "b" * 40
                ),
            ),
            "Git tree",
        ),
        (
            lambda plan, request, job: job["environment_request"].__setitem__(
                "candidate_id", "other"
            ),
            "different environment request",
        ),
    ],
)
def test_issue_rejects_authorization_or_identity_drift(
    tmp_path: Path, mutation, message: str
) -> None:
    plan_path, request_path, job_path, _ = fixture(tmp_path)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    request = json.loads(request_path.read_text(encoding="utf-8"))
    job = json.loads(job_path.read_text(encoding="utf-8"))
    mutation(plan, request, job)
    write(request_path, request)
    write(job_path, job)
    plan["bound_inputs"]["superseding_environment_request"]["sha256"] = digest(
        request_path
    )
    plan["bound_inputs"]["superseding_resource_job"]["sha256"] = digest(job_path)
    write(plan_path, plan)
    with pytest.raises(ValueError, match=message):
        issue_approval(
            plan_path=plan_path,
            request_path=request_path,
            job_path=job_path,
            artifact_root=tmp_path,
            supervisor_id="root-controller",
            approval_id="candidate-cpu-materialization-v1",
            issued_at=NOW,
            expires_at=NOW + timedelta(hours=1),
            max_wall_seconds=3600,
            network_policy="DEPENDENCY_MATERIALIZATION_ONLY",
        )


def test_validation_rejects_expiry_and_changed_artifact(tmp_path: Path) -> None:
    _, approval_path = issue(tmp_path)
    with pytest.raises(ValueError, match="not currently valid"):
        validate_approval(approval_path, tmp_path, now=NOW + timedelta(hours=3))

    approval = json.loads(approval_path.read_text(encoding="utf-8"))
    request_path = tmp_path / approval["environment_request"]["path"]
    request = json.loads(request_path.read_text(encoding="utf-8"))
    request["candidate_id"] = "changed"
    write(request_path, request)
    with pytest.raises(ValueError, match="hash changed"):
        validate_approval(approval_path, tmp_path, now=NOW)


def test_preprovisioned_worker_plan_binds_attestation(tmp_path: Path) -> None:
    plan_path, request_path, job_path, _ = fixture(tmp_path)
    attestation_path = tmp_path / "evidence" / "worker.json"
    cmake = {
        "path": "/usr/bin/cmake",
        "version": "cmake version 4.1.0",
        "sha256": "7" * 64,
    }
    write(
        attestation_path,
        {
            "worker_id": "worker-shared-sm120",
            "host_id": "shared-8x-sm120-32g",
            "runtime": {"toolchain": {"cmake": cmake, "git": None}},
        },
    )
    runtime = {
        "kind": "ATTESTED_PREPROVISIONED_WORKER",
        "identity_sha256": digest(attestation_path),
        "worker_id": "worker-shared-sm120",
    }
    request = json.loads(request_path.read_text(encoding="utf-8"))
    request["execution"]["image_digest"] = None
    request["execution"]["runtime_provenance"] = runtime
    write(request_path, request)
    job = json.loads(job_path.read_text(encoding="utf-8"))
    job["environment_request"] = request
    write(job_path, job)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan.pop("runtime_image")
    plan["runtime_worker"] = {
        "worker_id": "worker-shared-sm120",
        "host_id": "shared-8x-sm120-32g",
        "attestation": {
            "path": "evidence/worker.json",
            "sha256": digest(attestation_path),
        },
        "required_toolchain": {"cmake": dict(cmake)},
    }
    plan["bound_inputs"]["superseding_environment_request"]["sha256"] = digest(
        request_path
    )
    plan["bound_inputs"]["superseding_resource_job"]["sha256"] = digest(job_path)
    write(plan_path, plan)

    approval = issue_approval(
        plan_path=plan_path,
        request_path=request_path,
        job_path=job_path,
        artifact_root=tmp_path,
        supervisor_id="root-controller",
        approval_id="worker-cpu-materialization-v1",
        issued_at=NOW,
        expires_at=NOW + timedelta(hours=1),
        max_wall_seconds=3600,
        network_policy="DEPENDENCY_MATERIALIZATION_ONLY",
    )
    assert approval["decision"] == "APPROVED"

    plan["runtime_worker"]["attestation"]["sha256"] = "8" * 64
    write(plan_path, plan)
    with pytest.raises((FileNotFoundError, ValueError), match="attestation"):
        issue_approval(
            plan_path=plan_path,
            request_path=request_path,
            job_path=job_path,
            artifact_root=tmp_path,
            supervisor_id="root-controller",
            approval_id="worker-cpu-materialization-v1",
            issued_at=NOW,
            expires_at=NOW + timedelta(hours=1),
            max_wall_seconds=3600,
            network_policy="DEPENDENCY_MATERIALIZATION_ONLY",
        )


@pytest.mark.parametrize(
    "mutation, message",
    [
        (
            lambda plan, attestation: attestation["runtime"]["toolchain"].__setitem__(
                "cmake", None
            ),
            "required worker tool is unavailable: cmake",
        ),
        (
            lambda plan, attestation: attestation["runtime"]["toolchain"][
                "cmake"
            ].__setitem__("version", "cmake version 3.0.0"),
            "required worker tool identity differs: cmake",
        ),
        (
            lambda plan, attestation: attestation.__setitem__(
                "host_id", "another-host"
            ),
            "worker attestation host_id differs from plan",
        ),
    ],
)
def test_preprovisioned_worker_plan_rejects_missing_or_drifted_required_tool(
    tmp_path: Path, mutation, message: str
) -> None:
    plan_path, request_path, job_path, _ = fixture(tmp_path)
    attestation_path = tmp_path / "evidence" / "worker.json"
    cmake = {
        "path": "/usr/bin/cmake",
        "version": "cmake version 4.1.0",
        "sha256": "7" * 64,
    }
    attestation = {
        "worker_id": "worker-shared-sm120",
        "host_id": "shared-8x-sm120-32g",
        "runtime": {"toolchain": {"cmake": cmake}},
    }
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan.pop("runtime_image")
    plan["runtime_worker"] = {
        "worker_id": "worker-shared-sm120",
        "host_id": "shared-8x-sm120-32g",
        "attestation": {"path": "evidence/worker.json", "sha256": ""},
        "required_toolchain": {"cmake": dict(cmake)},
    }
    mutation(plan, attestation)
    write(attestation_path, attestation)
    plan["runtime_worker"]["attestation"]["sha256"] = digest(attestation_path)

    request = json.loads(request_path.read_text(encoding="utf-8"))
    request["execution"]["image_digest"] = None
    request["execution"]["runtime_provenance"] = {
        "kind": "ATTESTED_PREPROVISIONED_WORKER",
        "identity_sha256": digest(attestation_path),
        "worker_id": "worker-shared-sm120",
    }
    write(request_path, request)
    job = json.loads(job_path.read_text(encoding="utf-8"))
    job["environment_request"] = request
    write(job_path, job)
    plan["bound_inputs"]["superseding_environment_request"]["sha256"] = digest(
        request_path
    )
    plan["bound_inputs"]["superseding_resource_job"]["sha256"] = digest(job_path)
    write(plan_path, plan)

    with pytest.raises(ValueError, match=message):
        validate_plan_bundle(plan_path, request_path, job_path, tmp_path)
