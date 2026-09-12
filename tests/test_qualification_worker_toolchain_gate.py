#!/usr/bin/env python3
"""Tests for the pre-lease worker toolchain gate."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from qualification_worker_toolchain_gate import evaluate  # noqa: E402


NOW = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)


def write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")


def attestation(observed_at: datetime = NOW) -> dict:
    digest = "a" * 64
    tool = {
        "path": "/usr/local/bin/nsys",
        "sha256": digest,
        "version": "NVIDIA Nsight Systems version 2026.1",
    }
    return {
        "schema_version": "qualification-environment-worker-attestation-v1",
        "observed_at": observed_at.isoformat().replace("+00:00", "Z"),
        "worker_id": "worker-shared-sm120",
        "host_id": "shared-8x-sm120-32g",
        "platform": {"os": "linux", "architecture": "x86_64", "hostname": "worker"},
        "storage": {
            "requested_root": "/workspace",
            "resolved_root": "/workspace",
            "free_bytes": 100,
            "total_bytes": 200,
            "mount": {},
        },
        "runtime": {
            "python": {"version": "3.12", "path": "/usr/bin/python3", "sha256": digest},
            "torch": {
                "version": "2.11.0+cu130",
                "cuda_version": "13.0",
                "module_path": "/opt/torch/__init__.py",
                "module_sha256": digest,
                "build_config_sha256": digest,
                "compiled_arches": ["sm_120"],
                "nccl_available": True,
                "native_libraries": [{"path": "/opt/torch/_C.so", "sha256": digest}],
            },
            "toolchain": {"nsys": tool, "cmake": None},
        },
        "isolation": {
            "cuda_visible_devices": "-1",
            "torch_cuda_available": False,
            "gpu_device_nodes": [],
            "nested_container_runtimes": [],
            "gpu_processes": [],
        },
        "claim_boundary": "READ_ONLY_WORKER_RUNTIME_AND_STORAGE_ATTESTATION_NOT_ENVIRONMENT_MATERIALIZATION_GPU_OR_WORKLOAD_AUTHORIZATION",
    }


def run_gate(
    tmp_path: Path,
    value: dict,
    required_tools: list[str],
    *,
    observed_at: datetime = NOW,
) -> dict:
    attestation_path = tmp_path / "worker.json"
    consumer_path = tmp_path / "plan.json"
    write(attestation_path, value)
    write(consumer_path, {"plan": "sealed"})
    return evaluate(
        attestation_path=attestation_path,
        consumer_path=consumer_path,
        worker_id="worker-shared-sm120",
        host_id="shared-8x-sm120-32g",
        required_tools=required_tools,
        max_age_seconds=300,
        observed_at=observed_at,
    )


def test_ready_gate_binds_exact_present_tool_and_consumer(tmp_path: Path) -> None:
    result = run_gate(tmp_path, attestation(), ["nsys"])

    assert result["status"] == "READY_FOR_PRELEASE_BINDING"
    assert result["blockers"] == []
    assert result["tools"][0]["identity"]["sha256"] == "a" * 64
    assert result["lease_authorized"] is False


def test_missing_tool_blocks_before_lease(tmp_path: Path) -> None:
    result = run_gate(tmp_path, attestation(), ["cmake"])

    assert result["status"] == "BLOCKED_PRELEASE"
    assert result["blockers"] == ["REQUIRED_TOOL_MISSING:cmake"]
    assert result["tools"][0]["state"] == "MISSING"


def test_stale_attestation_blocks_even_when_tool_exists(tmp_path: Path) -> None:
    old = NOW - timedelta(seconds=301)
    result = run_gate(tmp_path, attestation(old), ["nsys"])

    assert result["status"] == "BLOCKED_PRELEASE"
    assert result["blockers"] == ["ATTESTATION_STALE"]


@pytest.mark.parametrize(
    "required_tools",
    [[], ["nsys", "nsys"], ["not a tool"]],
)
def test_invalid_tool_requirements_fail_closed(
    tmp_path: Path, required_tools: list[str]
) -> None:
    with pytest.raises(ValueError):
        run_gate(tmp_path, attestation(), required_tools)


def test_worker_identity_mismatch_fails_closed(tmp_path: Path) -> None:
    value = attestation()
    value["worker_id"] = "other-worker"
    with pytest.raises(ValueError, match="worker_id"):
        run_gate(tmp_path, value, ["nsys"])
