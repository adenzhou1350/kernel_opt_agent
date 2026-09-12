#!/usr/bin/env python3
"""Tests for preprovisioned worker runtime attestations."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from qualification_environment_worker import (  # noqa: E402
    DEFAULT_TOOLCHAIN_NAMES,
    compiled_arches,
    cpu_only_cache_environment,
    main,
    parse_final_json_object,
    tool_identity,
    validate,
    validate_cpu_only_process_transition,
)

import qualification_environment_worker as worker_module  # noqa: E402


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


def test_compiled_arches_falls_back_when_cuda_is_hidden() -> None:
    class FakeCuda:
        @staticmethod
        def get_arch_list() -> list[str]:
            return []

    class FakeC:
        @staticmethod
        def _cuda_getArchFlags() -> str:
            return "sm_90 sm_120 sm_100"

    class FakeTorch:
        cuda = FakeCuda()
        _C = FakeC()

    assert compiled_arches(FakeTorch()) == ["sm_100", "sm_120", "sm_90"]


def test_default_toolchain_covers_late_worker_build_failures() -> None:
    assert {"git", "cmake", "make"} <= set(DEFAULT_TOOLCHAIN_NAMES)


def test_tool_identity_binds_resolved_bytes_and_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = tmp_path / "cmake"
    executable.write_bytes(b"synthetic executable\n")
    monkeypatch.setattr(worker_module.shutil, "which", lambda name: str(executable))
    monkeypatch.setattr(
        worker_module,
        "run",
        lambda argv: subprocess.CompletedProcess(
            argv, 0, stdout="cmake version 4.1.0\n", stderr=""
        ),
    )

    identity = tool_identity("cmake")

    assert identity == {
        "path": executable.resolve().as_posix(),
        "sha256": worker_module.sha256_file(executable),
        "version": "cmake version 4.1.0",
    }


def test_final_json_probe_allows_framework_logs_before_object() -> None:
    stdout = '[INFO] DeepSpeed accelerator initialized\n{"cuda": false}\n'

    assert parse_final_json_object(stdout) == {"cuda": False}


@pytest.mark.parametrize(
    "stdout",
    [
        "",
        '{"phase": "log"}\n{"cuda": false}\n',
        '{"cuda": false}\ntrailing diagnostic\n',
        "[1, 2, 3]\n",
    ],
)
def test_final_json_probe_rejects_missing_or_ambiguous_result(stdout: str) -> None:
    with pytest.raises(ValueError):
        parse_final_json_object(stdout)


def test_cpu_only_transition_accepts_stable_post_attestation_processes() -> None:
    before = ["GPU-a, 42, VLLM::Worker_PP0, 18454 MiB"]
    after = ["GPU-a, 42, VLLM::Worker_PP0, 18512 MiB"]

    result = validate_cpu_only_process_transition([], before, after)

    assert result["attestation_snapshot_changed_before_execution"] is True
    assert result["stable_process_identities"] == [["GPU-a", "42", "VLLM::Worker_PP0"]]


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ([], ["GPU-a, 42, worker, 1 MiB"]),
        (["GPU-a, 42, worker, 1 MiB"], []),
        (["GPU-a, 42, worker, 1 MiB"], ["GPU-a, 43, worker, 1 MiB"]),
    ],
)
def test_cpu_only_transition_rejects_process_identity_changes(
    before: list[str], after: list[str]
) -> None:
    with pytest.raises(ValueError, match="GPU process identities changed"):
        validate_cpu_only_process_transition([], before, after)


def test_cpu_only_cache_environment_is_confined_to_closure() -> None:
    closure = "/workspace/kernel-opt/closures/run-v1"

    result = cpu_only_cache_environment(closure)

    assert result["TRITON_CACHE_DIR"] == f"{closure}/cache/triton-autotune"
    assert result["XDG_CACHE_HOME"] == f"{closure}/cache/xdg"
    assert result["TMPDIR"] == f"{closure}/tmp"
    assert all(value.startswith(f"{closure}/") for value in result.values())


def test_cache_environment_cli_emits_machine_readable_contract(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    closure = "/workspace/kernel-opt/closures/run-v1"
    monkeypatch.setattr(
        sys,
        "argv",
        ["qualification_environment_worker.py", "--cache-environment", closure],
    )

    assert main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result == {
        "status": "PASS",
        "closure_root": closure,
        "environment": cpu_only_cache_environment(closure),
        "gpu_authorized": False,
    }


@pytest.mark.parametrize(
    "closure",
    ["relative/closure", "/workspace", "/root/closure", "/workspaces/escape"],
)
def test_cpu_only_cache_environment_rejects_unconfined_roots(closure: str) -> None:
    with pytest.raises(ValueError):
        cpu_only_cache_environment(closure)


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
