#!/usr/bin/env python3
"""Tests for preprovisioned worker runtime attestations."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from qualification_environment_worker import validate  # noqa: E402


def attestation() -> dict:
    identity = "a" * 64
    return {
        "schema_version": "qualification-environment-worker-attestation-v1",
        "observed_at": "2026-09-11T09:30:00Z",
        "worker_id": "worker-shared-sm120",
        "host_id": "shared-8x-sm120-32g",
        "platform": {
            "os": "linux",
            "architecture": "x86_64",
            "hostname": "worker",
        },
        "storage": {
            "requested_root": "/workspace",
            "resolved_root": "/workspace",
            "free_bytes": 128 * 1024**3,
            "total_bytes": 484 * 1024**3,
            "mount": {
                "available": True,
                "target": "/",
                "source": "overlay",
                "fstype": "overlay",
            },
        },
        "runtime": {
            "python": {
                "version": "3.12.13",
                "path": "/usr/bin/python3",
                "sha256": identity,
            },
            "torch": {
                "version": "2.11.0+cu130",
                "cuda_version": "13.0",
                "module_path": "/usr/lib/python3/dist-packages/torch/__init__.py",
                "module_sha256": identity,
                "build_config_sha256": identity,
                "compiled_arches": ["sm_120"],
                "nccl_available": True,
                "native_libraries": [
                    {"path": "/usr/lib/libtorch_cuda.so", "sha256": identity}
                ],
            },
            "toolchain": {"nvcc": None},
        },
        "isolation": {
            "cuda_visible_devices": "-1",
            "torch_cuda_available": False,
            "gpu_device_nodes": ["/dev/nvidia0", "/dev/nvidiactl"],
            "nested_container_runtimes": [],
            "gpu_processes": [],
        },
        "claim_boundary": "READ_ONLY_WORKER_RUNTIME_AND_STORAGE_ATTESTATION_NOT_ENVIRONMENT_MATERIALIZATION_GPU_OR_WORKLOAD_AUTHORIZATION",
    }


def write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")


def test_valid_attestation_allows_premounted_devices_but_no_visible_cuda(
    tmp_path: Path,
) -> None:
    path = tmp_path / "worker.json"
    write(path, attestation())
    validate(path)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value["isolation"].__setitem__("cuda_visible_devices", "0"),
        lambda value: value["isolation"].__setitem__("torch_cuda_available", True),
        lambda value: value["runtime"]["torch"].__setitem__("module_sha256", "bad"),
        lambda value: value.__setitem__("hidden", True),
    ],
)
def test_attestation_drift_fails_closed(tmp_path: Path, mutation) -> None:
    value = attestation()
    mutation(value)
    path = tmp_path / "worker.json"
    write(path, value)
    with pytest.raises(ValueError, match="invalid worker attestation"):
        validate(path)
