#!/usr/bin/env python3
"""Consume one authorized schedule entry and launch its exact sealed argv."""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol

from artifact_io import atomic_json, sha256_file
from community_atomic_claim import ClaimStore
from community_claim_contracts import (
    ClaimError,
    SessionBinding,
    digest,
    timestamp_text,
    trusted_utc_now,
    validate_receipt,
    with_id,
)
from community_execution_authorization_v2 import validate_authorization


RESULT_SCHEMA = "community_atomic_dispatch_result.schema.json"


class Child(Protocol):
    pid: int

    def wait(self, timeout: float | None = None) -> int: ...

    def poll(self) -> int | None: ...


class Runtime(Protocol):
    def gpu_inventory(self) -> list[str]: ...

    def spawn(
        self, argv: list[str], cwd: Path, stdout: BinaryIO, stderr: BinaryIO
    ) -> Child: ...

    def attest(self, child: Child, entry: dict) -> dict: ...

    def terminate(self, child: Child) -> int | None: ...


def timeout_from_argv(argv: list[str]) -> int:
    positions = [
        index for index, value in enumerate(argv) if value == "--timeout-seconds"
    ]
    if len(positions) != 1 or positions[0] + 1 >= len(argv):
        raise ClaimError("SEALED_ARGV_REQUIRES_ONE_TIMEOUT_SECONDS")
    try:
        value = int(argv[positions[0] + 1])
    except ValueError as error:
        raise ClaimError("SEALED_ARGV_TIMEOUT_INVALID") from error
    if value <= 0:
        raise ClaimError("SEALED_ARGV_TIMEOUT_INVALID")
    return value


def validate_planned_budget(schedule: list[dict], approval: dict) -> list[int]:
    budget = approval["approved_budget"]
    if (
        len(schedule) > budget["max_dispatches"]
        or len(schedule) > budget["max_process_launches"]
    ):
        raise ClaimError("SCHEDULE_EXCEEDS_PROCESS_OR_DISPATCH_BUDGET")
    timeouts = [timeout_from_argv(entry["resolved_argv"]) for entry in schedule]
    if sum(timeouts) > budget["max_wall_clock_seconds"]:
        raise ClaimError("SEALED_SCHEDULE_EXCEEDS_WALL_BUDGET")
    gpu_seconds = sum(
        timeout * len(entry["formal_gpu_uuids"])
        for timeout, entry in zip(timeouts, schedule, strict=True)
    )
    if gpu_seconds > budget["max_gpu_seconds"]:
        raise ClaimError("SEALED_SCHEDULE_EXCEEDS_GPU_BUDGET")
    return timeouts


def session_binding(bundle: dict) -> SessionBinding:
    authorization = bundle["authorization"]
    request = bundle["request"]
    approval = bundle["approval"]
    deployment = bundle["deployment"]
    return SessionBinding(
        request_id=request["request_id"],
        cycle_id=request["cycle_id"],
        suite_id=authorization["suite_id"],
        authorization_request_sha256=authorization["authorization_request"]["sha256"],
        semantic_approval_sha256=approval["approval_id"],
        combined_authorization_sha256=authorization["combined_authorization_id"],
        single_use_token=approval["single_use_token"],
        authorization_schedule_sha256=bundle["authorization_schedule_sha256"],
        execution_schedule_sha256=bundle["execution_schedule_sha256"],
        dispatcher_sha256=deployment["dispatcher_executable"]["sha256"],
        claim_store_identity_sha256=deployment["claim_store_identity_sha256"],
        claim_store_epoch_sha256=deployment["claim_store_epoch_sha256"],
        formal_resource_id=authorization["formal_resource_id"],
        expires_at=approval["expires_at"],
        max_dispatches=approval["approved_budget"]["max_dispatches"],
    )


def require_dispatcher_identity(bundle: dict) -> None:
    declared = bundle["deployment"]["dispatcher_executable"]
    current = Path(__file__).resolve()
    if (
        bundle["dispatcher_path"] != current
        or sha256_file(current) != declared["sha256"]
    ):
        raise ClaimError("LIVE_DISPATCHER_IDENTITY_MISMATCH")


def relative_identity(path: Path, root: Path) -> dict:
    path = path.resolve()
    try:
        relative = path.relative_to(root.resolve())
    except ValueError as error:
        raise ClaimError("DISPATCH_OUTPUT_ESCAPES_ARTIFACT_ROOT") from error
    return {"path": relative.as_posix(), "sha256": sha256_file(path)}


@dataclass
class PosixRuntime:
    """Live Linux process and GPU identity provider."""

    def gpu_inventory(self) -> list[str]:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=uuid", "--format=csv,noheader"],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise ClaimError("LIVE_GPU_INVENTORY_UNAVAILABLE")
        values = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if not values or len(values) != len(set(values)):
            raise ClaimError("LIVE_GPU_INVENTORY_INVALID")
        return values

    def spawn(
        self, argv: list[str], cwd: Path, stdout: BinaryIO, stderr: BinaryIO
    ) -> subprocess.Popen[bytes]:
        if os.name != "posix" or not Path("/proc").is_dir():
            raise ClaimError("ATOMIC_DISPATCHER_REQUIRES_PROCFS_POSIX_HOST")
        return subprocess.Popen(
            argv,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            start_new_session=True,
        )

    def attest(self, child: Child, entry: dict) -> dict:
        proc = Path("/proc") / str(child.pid)
        try:
            command = (proc / "cmdline").read_bytes().rstrip(b"\0").split(b"\0")
            argv = [item.decode("utf-8") for item in command]
            stat_text = (proc / "stat").read_text(encoding="utf-8")
            stat_tail = stat_text[stat_text.rindex(")") + 2 :].split()
            executable = (proc / "exe").resolve(strict=True)
            boot_id = (
                Path("/proc/sys/kernel/random/boot_id")
                .read_text(encoding="utf-8")
                .strip()
            )
        except (FileNotFoundError, OSError, UnicodeDecodeError) as error:
            raise ClaimError("CHILD_EXITED_BEFORE_PROCESS_ATTESTATION") from error
        if digest(argv) != entry["resolved_argv_sha256"]:
            raise ClaimError("LIVE_PROCESS_ARGV_DIFFERS_FROM_SEALED_ENTRY")
        return {
            "pid": child.pid,
            "hostname": socket.gethostname(),
            "boot_id": boot_id,
            "proc_start_ticks": int(stat_tail[19]),
            "argv_sha256": digest(argv),
            "executable_path": str(executable),
            "executable_sha256": sha256_file(executable),
            "gpu_uuids": entry["formal_gpu_uuids"],
        }

    def terminate(self, child: Child) -> int | None:
        try:
            os.killpg(child.pid, signal.SIGTERM)
            return child.wait(timeout=10)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                return child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                return None


def dispatch_one(
    bundle: dict,
    store: ClaimStore,
    binding: SessionBinding,
    order_index: int,
    artifact_root: Path,
    stdout_path: Path,
    stderr_path: Path,
    runtime: Runtime,
) -> dict:
    resolved_logs = [stdout_path.resolve(), stderr_path.resolve()]
    if len(set(resolved_logs)) != 2:
        raise ClaimError("DISPATCH_OUTPUT_PATHS_MUST_BE_DISTINCT")
    for path in resolved_logs:
        try:
            path.relative_to(artifact_root.resolve())
        except ValueError as error:
            raise ClaimError("DISPATCH_OUTPUT_ESCAPES_ARTIFACT_ROOT") from error
        if path.exists():
            raise ClaimError("DISPATCH_OUTPUT_ALREADY_EXISTS")
    schedule = bundle["execution_schedule"]
    timeouts = validate_planned_budget(schedule, bundle["approval"])
    rows = [entry for entry in schedule if entry["order_index"] == order_index]
    if len(rows) != 1:
        raise ClaimError("ORDER_INDEX_NOT_IN_FROZEN_SCHEDULE")
    entry = rows[0]
    timeout_seconds = timeouts[order_index - 1]
    live_inventory = runtime.gpu_inventory()
    if not set(entry["formal_gpu_uuids"]).issubset(live_inventory):
        raise ClaimError("FORMAL_GPU_UUID_NOT_PRESENT_IN_LIVE_INVENTORY")
    gates = {
        "pre_gpu_ready": bundle["authorization"]["gate_decisions"]["pre_gpu_ready"],
        "execution_contract_ready": bundle["authorization"]["gate_decisions"][
            "execution_contract_ready"
        ],
        "semantic_approval_ready": bundle["authorization"]["gate_decisions"][
            "semantic_approval_ready"
        ],
    }
    store.create_or_resume_session(binding, schedule, gates)
    claim = store.claim_entry(binding, entry)
    started = trusted_utc_now()
    dispatch = None
    terminal = None
    exit_code = None
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            try:
                child = runtime.spawn(
                    entry["resolved_argv"], artifact_root, stdout, stderr
                )
            except Exception:
                terminal = store.record_ambiguous(
                    binding, order_index, "AMBIGUOUS_PRELAUNCH"
                )
                state = "TERMINAL_AMBIGUOUS_PRELAUNCH"
            else:
                try:
                    process = runtime.attest(child, entry)
                    dispatch = store.record_dispatch(binding, order_index, process)
                except Exception:
                    runtime.terminate(child)
                    terminal = store.record_ambiguous(
                        binding, order_index, "AMBIGUOUS_LAUNCH"
                    )
                    state = "TERMINAL_AMBIGUOUS_LAUNCH"
                else:
                    try:
                        exit_code = child.wait(timeout=timeout_seconds)
                        state = "PROCESS_EXITED_AWAITING_VALIDATED_OBSERVATION"
                    except subprocess.TimeoutExpired:
                        exit_code = runtime.terminate(child)
                        terminal = store.record_terminal(
                            binding, order_index, "TIMEOUT"
                        )
                        state = "TERMINAL_TIMEOUT"
    finally:
        if not stdout_path.is_file():
            stdout_path.write_bytes(b"")
        if not stderr_path.is_file():
            stderr_path.write_bytes(b"")
    ended = trusted_utc_now()
    result = with_id(
        {
            "schema_version": "community-atomic-dispatch-result-v1",
            "generated_at": timestamp_text(ended),
            "claim_boundary": (
                "ONE_ATOMIC_LAUNCH_ATTEMPT_NOT_EXPERIMENT_SUCCESS_OR_POLICY_EVIDENCE"
            ),
            "combined_authorization_id": bundle["authorization"][
                "combined_authorization_id"
            ],
            "session_id": binding.session_id,
            "order_index": order_index,
            "schedule_key": entry["schedule_key"],
            "entry_claim_id": claim["entry_claim_id"],
            "dispatch_receipt_id": (
                dispatch["dispatch_receipt_id"] if dispatch else None
            ),
            "terminal_receipt_id": (
                terminal["terminal_receipt_id"] if terminal else None
            ),
            "state": state,
            "launch_authorized_by_atomic_claim": True,
            "automatic_retry_allowed": False,
            "timeout_seconds": timeout_seconds,
            "started_at": timestamp_text(started),
            "ended_at": timestamp_text(ended),
            "process_exit_code": exit_code,
            "formal_gpu_uuids": entry["formal_gpu_uuids"],
            "live_gpu_inventory": live_inventory,
            "stdout_identity": relative_identity(stdout_path, artifact_root),
            "stderr_identity": relative_identity(stderr_path, artifact_root),
        },
        "dispatch_result_id",
    )
    validate_receipt(result, RESULT_SCHEMA)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorization", required=True, type=Path)
    parser.add_argument("--artifact-root", required=True, type=Path)
    parser.add_argument("--order-index", required=True, type=int)
    parser.add_argument("--result", required=True, type=Path)
    parser.add_argument("--stdout", required=True, type=Path)
    parser.add_argument("--stderr", required=True, type=Path)
    args = parser.parse_args()
    artifact_root = args.artifact_root.resolve()
    outputs = [output.resolve() for output in (args.result, args.stdout, args.stderr)]
    if len(set(outputs)) != 3:
        raise ClaimError("DISPATCH_OUTPUT_PATHS_MUST_BE_DISTINCT")
    for output in outputs:
        try:
            output.relative_to(artifact_root)
        except ValueError as error:
            raise ClaimError("DISPATCH_OUTPUT_ESCAPES_ARTIFACT_ROOT") from error
        if output.exists():
            raise ClaimError("DISPATCH_OUTPUT_ALREADY_EXISTS")
    bundle = validate_authorization(
        args.authorization.resolve(), artifact_root, require_live_store_host=True
    )
    if not bundle["ready_for_atomic_claim"]:
        raise ClaimError("COMBINED_AUTHORIZATION_NOT_READY_FOR_ATOMIC_CLAIM")
    require_dispatcher_identity(bundle)
    binding = session_binding(bundle)
    store = ClaimStore(
        Path(bundle["deployment"]["canonical_database_path"]),
        store_epoch_sha256=bundle["deployment"]["claim_store_epoch_sha256"],
    )
    result = dispatch_one(
        bundle,
        store,
        binding,
        args.order_index,
        artifact_root,
        outputs[1],
        outputs[2],
        PosixRuntime(),
    )
    atomic_json(outputs[0], result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
