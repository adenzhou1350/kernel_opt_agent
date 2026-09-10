#!/usr/bin/env python3
"""Fail-closed tests for one-entry atomic process launch orchestration."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from community_atomic_claim import ClaimStore  # noqa: E402
from community_atomic_dispatcher import (  # noqa: E402
    ClaimError,
    PosixRuntime,
    dispatch_one,
    session_binding,
    timeout_from_argv,
    validate_planned_budget,
)
from community_claim_contracts import authorization_schedule, digest  # noqa: E402


def schedule() -> list[dict]:
    rows = []
    for index, arm in ((1, "CONTROL"), (2, "COMMUNITY_AUGMENTED")):
        argv = ["python3", "runner.py", "--timeout-seconds", "10", "--arm", arm]
        rows.append(
            {
                "order_index": index,
                "task_id": "task-a",
                "repeat_index": 1,
                "arm": arm,
                "schedule_key": str(index) * 64,
                "sealed_argv_sha256": chr(96 + index) * 64,
                "resolved_argv": argv,
                "resolved_argv_sha256": digest(argv),
                "formal_gpu_uuids": ["GPU-11111111-1111-1111-1111-111111111111"],
            }
        )
    return rows


def bundle(rows: list[dict], store: ClaimStore) -> dict:
    environment = {
        "PATH": "/runtime/bin",
        "HOME": "/runtime/home",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "CUDA_VISIBLE_DEVICES": "0",
        "NVIDIA_VISIBLE_DEVICES": "void",
        "XDG_CACHE_HOME": "/runtime/cache",
    }
    return {
        "authorization": {
            "combined_authorization_id": "c" * 64,
            "authorization_request": {"path": "request.json", "sha256": "a" * 64},
            "suite_id": "suite-1",
            "formal_resource_id": "gpu-host",
            "gate_decisions": {
                "pre_gpu_ready": True,
                "execution_contract_ready": True,
                "semantic_approval_ready": True,
                "claim_store_deployment_ready": True,
            },
        },
        "request": {"request_id": "request-1", "cycle_id": "cycle-1"},
        "approval": {
            "approval_id": "b" * 64,
            "single_use_token": "f" * 64,
            "expires_at": "2030-01-01T00:00:00Z",
            "approved_budget": {
                "max_dispatches": 2,
                "max_process_launches": 2,
                "max_wall_clock_seconds": 20,
                "max_gpu_seconds": 20,
            },
        },
        "deployment": {
            "dispatcher_executable": {
                "path": "dispatcher.py",
                "sha256": "d" * 64,
            },
            "claim_store_identity_sha256": store.identity_sha256,
            "claim_store_epoch_sha256": store.store_epoch_sha256,
        },
        "base_authorization": {"combined_authorization_id": "8" * 64},
        "execution_schedule": rows,
        "runtime_schedule": [
            {
                "order_index": row["order_index"],
                "task_id": row["task_id"],
                "arm": row["arm"],
                "execution_profile_id": "7" * 64,
                "treatment_id": ("6" if row["arm"] == "CONTROL" else "5") * 64,
                "implementation_identity": ("4" if row["arm"] == "CONTROL" else "3")
                * 64,
                "launch_argv": row["resolved_argv"],
                "launch_argv_sha256": row["resolved_argv_sha256"],
                "working_directory": "/runtime/work",
                "command_executable": {
                    "path": "/runtime/bin/python3",
                    "sha256": "e" * 64,
                },
                "process_executable": {
                    "path": "/usr/bin/python3",
                    "sha256": "e" * 64,
                },
                "environment": environment,
                "environment_sha256": digest(environment),
            }
            for row in rows
        ],
        "authorization_schedule_sha256": digest(authorization_schedule(rows)),
        "execution_schedule_sha256": digest(rows),
    }


class FakeChild:
    pid = 123

    def __init__(self, *, exit_code: int = 0, timeout: bool = False) -> None:
        self.exit_code = exit_code
        self.timeout = timeout

    def wait(self, timeout: float | None = None) -> int:
        if self.timeout:
            raise subprocess.TimeoutExpired("fake", timeout)
        return self.exit_code

    def poll(self) -> int | None:
        return self.exit_code


class FakeRuntime:
    def __init__(
        self,
        *,
        exit_code: int = 0,
        timeout: bool = False,
        spawn_error: bool = False,
        attest_error: bool = False,
        preflight_error: bool = False,
        inventory: list[str] | None = None,
    ) -> None:
        self.child = FakeChild(exit_code=exit_code, timeout=timeout)
        self.spawn_error = spawn_error
        self.attest_error = attest_error
        self.preflight_error = preflight_error
        self.inventory = inventory or ["GPU-11111111-1111-1111-1111-111111111111"]
        self.terminated = False

    def gpu_inventory(self) -> list[str]:
        return self.inventory

    def preflight(self, runtime_entry):
        del runtime_entry
        if self.preflight_error:
            raise ClaimError("LIVE_COMMAND_EXECUTABLE_IDENTITY_MISMATCH")

    def spawn(self, runtime_entry, stdout, stderr):
        del runtime_entry, stdout, stderr
        if self.spawn_error:
            raise OSError("synthetic spawn failure")
        return self.child

    def attest(self, child, entry, runtime_entry):
        del child
        del runtime_entry
        if self.attest_error:
            raise ClaimError("CHILD_EXITED_BEFORE_PROCESS_ATTESTATION")
        return {
            "pid": 123,
            "hostname": "gpu-host",
            "boot_id": "boot-1",
            "proc_start_ticks": 99,
            "argv_sha256": entry["resolved_argv_sha256"],
            "executable_path": "/usr/bin/python3",
            "executable_sha256": "e" * 64,
            "gpu_uuids": entry["formal_gpu_uuids"],
        }

    def terminate(self, child):
        del child
        self.terminated = True
        return 124


def run(root: Path, runtime: FakeRuntime) -> tuple[dict, ClaimStore]:
    rows = schedule()
    store = ClaimStore(root / "claims.sqlite", store_epoch_sha256="9" * 64)
    inputs = bundle(rows, store)
    result = dispatch_one(
        inputs,
        store,
        session_binding(inputs),
        1,
        root,
        root / "stdout.log",
        root / "stderr.log",
        runtime,
    )
    return result, store


def test_zero_exit_waits_for_validated_observation_instead_of_success() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        result, store = run(root, FakeRuntime(exit_code=0))
        assert result["state"] == "PROCESS_EXITED_AWAITING_VALIDATED_OBSERVATION"
        assert result["terminal_receipt_id"] is None
        assert result["process_exit_code"] == 0
        assert result["arm"] == "CONTROL"
        assert result["treatment_id"] == "6" * 64
        assert store.load_binding(result["session_id"])
        assert (
            store.snapshot(store.load_binding(result["session_id"]))["state"]
            == "ACTIVE"
        )
        assert store.snapshot(store.load_binding(result["session_id"]))["entries"] == [
            {"order_index": 1, "state": "DISPATCHED"}
        ]


def test_nonzero_exit_also_waits_for_observation_or_explicit_failure() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        result, _ = run(Path(temporary), FakeRuntime(exit_code=7))
        assert result["state"] == "PROCESS_EXITED_AWAITING_VALIDATED_OBSERVATION"
        assert result["process_exit_code"] == 7
        assert result["automatic_retry_allowed"] is False


def test_timeout_terminates_and_records_terminal_failure() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        runtime = FakeRuntime(timeout=True)
        result, store = run(Path(temporary), runtime)
        assert runtime.terminated is True
        assert result["state"] == "TERMINAL_TIMEOUT"
        assert result["terminal_receipt_id"] is not None
        binding = store.load_binding(result["session_id"])
        assert store.snapshot(binding)["state"] == "ABORTED"


@pytest.mark.parametrize(
    ("runtime", "expected"),
    [
        (FakeRuntime(spawn_error=True), "TERMINAL_AMBIGUOUS_PRELAUNCH"),
        (FakeRuntime(attest_error=True), "TERMINAL_AMBIGUOUS_LAUNCH"),
    ],
)
def test_crash_windows_are_consumed_without_retry(
    runtime: FakeRuntime, expected: str
) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        result, store = run(Path(temporary), runtime)
        assert result["state"] == expected
        binding = store.load_binding(result["session_id"])
        assert store.snapshot(binding)["state"] == "ABORTED"
        with pytest.raises(ClaimError, match="SESSION_NOT_ACTIVE"):
            store.claim_entry(binding, schedule()[0])


def test_missing_formal_gpu_fails_before_token_consumption() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        rows = schedule()
        store = ClaimStore(root / "claims.sqlite", store_epoch_sha256="9" * 64)
        inputs = bundle(rows, store)
        with pytest.raises(
            ClaimError, match="FORMAL_GPU_UUID_NOT_PRESENT_IN_LIVE_INVENTORY"
        ):
            dispatch_one(
                inputs,
                store,
                session_binding(inputs),
                1,
                root,
                root / "stdout.log",
                root / "stderr.log",
                FakeRuntime(inventory=["GPU-foreign"]),
            )
        assert not (root / "stdout.log").exists()


def test_runtime_drift_fails_before_token_consumption() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        rows = schedule()
        store = ClaimStore(root / "claims.sqlite", store_epoch_sha256="9" * 64)
        inputs = bundle(rows, store)
        with pytest.raises(
            ClaimError, match="LIVE_COMMAND_EXECUTABLE_IDENTITY_MISMATCH"
        ):
            dispatch_one(
                inputs,
                store,
                session_binding(inputs),
                1,
                root,
                root / "stdout.log",
                root / "stderr.log",
                FakeRuntime(preflight_error=True),
            )
        assert not (root / "stdout.log").exists()


def test_existing_or_aliased_logs_fail_before_token_consumption() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        rows = schedule()
        store = ClaimStore(root / "claims.sqlite", store_epoch_sha256="9" * 64)
        inputs = bundle(rows, store)
        existing = root / "existing.log"
        existing.write_text("do not overwrite\n", encoding="utf-8")
        with pytest.raises(ClaimError, match="DISPATCH_OUTPUT_ALREADY_EXISTS"):
            dispatch_one(
                inputs,
                store,
                session_binding(inputs),
                1,
                root,
                existing,
                root / "stderr.log",
                FakeRuntime(),
            )
        with pytest.raises(ClaimError, match="DISPATCH_OUTPUT_PATHS_MUST_BE_DISTINCT"):
            dispatch_one(
                inputs,
                store,
                session_binding(inputs),
                1,
                root,
                root / "same.log",
                root / "same.log",
                FakeRuntime(),
            )


def test_timeout_and_aggregate_budget_are_derived_from_sealed_argv() -> None:
    rows = schedule()
    assert timeout_from_argv(rows[0]["resolved_argv"]) == 10
    approval = bundle(
        rows,
        ClaimStore(
            Path(tempfile.mkdtemp()) / "claims.sqlite", store_epoch_sha256="9" * 64
        ),
    )["approval"]
    assert validate_planned_budget(rows, approval) == [10, 10]
    approval["approved_budget"]["max_gpu_seconds"] = 19
    with pytest.raises(ClaimError, match="SEALED_SCHEDULE_EXCEEDS_GPU_BUDGET"):
        validate_planned_budget(rows, approval)


def test_timeout_flag_must_be_exactly_once() -> None:
    with pytest.raises(ClaimError, match="SEALED_ARGV_REQUIRES_ONE_TIMEOUT_SECONDS"):
        timeout_from_argv(["python3", "runner.py"])
    with pytest.raises(ClaimError, match="SEALED_ARGV_REQUIRES_ONE_TIMEOUT_SECONDS"):
        timeout_from_argv(
            ["python3", "x", "--timeout-seconds", "1", "--timeout-seconds", "2"]
        )


@pytest.mark.skipif(os.name != "posix", reason="requires Linux procfs")
def test_posix_runtime_attests_exact_executable_argv_and_environment() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        executable = Path(sys.executable).resolve()
        argv = ["python3", "-c", "import time; time.sleep(10)"]
        environment = {
            "PATH": str(executable.parent),
            "HOME": str(root),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "CUDA_VISIBLE_DEVICES": "",
            "NVIDIA_VISIBLE_DEVICES": "void",
            "XDG_CACHE_HOME": str(root / "cache"),
        }
        runtime_entry = {
            "launch_argv": argv,
            "launch_argv_sha256": digest(argv),
            "working_directory": str(root),
            "command_executable": {
                "path": str(executable),
                "sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
            },
            "process_executable": {
                "path": str(executable),
                "sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
            },
            "environment": environment,
            "environment_sha256": digest(environment),
        }
        entry = {
            "resolved_argv_sha256": digest(argv),
            "formal_gpu_uuids": ["GPU-11111111-1111-1111-1111-111111111111"],
        }
        runtime = PosixRuntime()
        with (
            (root / "stdout").open("wb") as stdout,
            (root / "stderr").open("wb") as stderr,
        ):
            child = runtime.spawn(runtime_entry, stdout, stderr)
            try:
                process = runtime.attest(child, entry, runtime_entry)
                assert process["argv_sha256"] == digest(argv)
                assert process["executable_path"] == str(executable)
            finally:
                runtime.terminate(child)
