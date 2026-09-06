#!/usr/bin/env python3
"""Run bounded requests through one hash-bound persistent worker process."""

from __future__ import annotations

import argparse
import json
import os
import queue
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TextIO

from evidence_utils import path_is_within, read_object, sha256


PROTOCOL = "persistent-session-v1"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_sha256(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return value == value.lower()


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def contained_path(root: Path, value: str, label: str) -> Path:
    path = Path(value)
    resolved = path.resolve() if path.is_absolute() else (root / path).resolve()
    if not path_is_within(resolved, root):
        raise ValueError(f"{label} escapes root: {resolved}")
    return resolved


def validate_spec(root: Path, spec_path: Path) -> dict:
    if not path_is_within(spec_path, root):
        raise ValueError("persistent-session spec must be inside root")
    spec = read_object(spec_path)
    if spec.get("schema_version") != "persistent-session-spec-v1":
        raise ValueError("unsupported persistent-session spec")
    argv = spec.get("argv")
    if not isinstance(argv, list) or not argv or not all(
        isinstance(value, str) and value for value in argv
    ):
        raise ValueError("persistent-session argv must be a non-empty string array")
    contained_path(root, str(spec.get("cwd", ".")), "persistent-session cwd")
    session_scope = spec.get("session_scope")
    if session_scope not in {"SINGLE_TREATMENT", "SHARED_TREATMENTS"}:
        raise ValueError("persistent-session scope is missing or unsupported")
    session_identity = spec.get("expected_session_identity")
    if not is_sha256(session_identity):
        raise ValueError("persistent-session expected_session_identity must be SHA-256")
    requests = spec.get("requests")
    if not isinstance(requests, list) or not requests:
        raise ValueError("persistent-session requires at least one request")
    request_ids: set[str] = set()
    treatment_ids: set[str] = set()
    for index, request in enumerate(requests):
        if not isinstance(request, dict):
            raise ValueError(f"persistent-session request {index} must be an object")
        request_id = request.get("request_id")
        treatment_identity = request.get("treatment_identity")
        if not isinstance(request_id, str) or not request_id:
            raise ValueError(f"persistent-session request {index} has no request_id")
        if request_id in request_ids:
            raise ValueError(f"duplicate persistent-session request_id: {request_id}")
        if not is_sha256(treatment_identity):
            raise ValueError(f"persistent-session request {index} treatment identity is invalid")
        if not isinstance(request.get("payload"), dict):
            raise ValueError(f"persistent-session request {index} payload must be an object")
        request_ids.add(request_id)
        treatment_ids.add(treatment_identity)
    if session_scope == "SINGLE_TREATMENT" and len(treatment_ids) != 1:
        raise ValueError("single-treatment session contains multiple treatment identities")
    for name in ("startup_timeout_seconds", "request_timeout_seconds", "shutdown_timeout_seconds"):
        value = spec.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise ValueError(f"{name} must be positive")
    return spec


def stream_reader(stream: TextIO, destination: queue.Queue[str | None]) -> None:
    try:
        for line in stream:
            destination.put(line)
    finally:
        destination.put(None)


def stderr_reader(stream: TextIO, lines: list[str]) -> None:
    lines.extend(stream.readlines())


def receive(
    messages: queue.Queue[str | None],
    timeout_seconds: float,
    raw_stdout: list[str],
) -> dict:
    try:
        line = messages.get(timeout=timeout_seconds)
    except queue.Empty as error:
        raise TimeoutError(f"worker response exceeded {timeout_seconds}s") from error
    if line is None:
        raise RuntimeError("worker stdout closed before the expected response")
    raw_stdout.append(line)
    try:
        value = json.loads(line)
    except json.JSONDecodeError as error:
        raise ValueError("worker emitted non-JSON protocol output") from error
    if not isinstance(value, dict):
        raise ValueError("worker protocol message must be an object")
    return value


def stop_worker(
    process: subprocess.Popen[str],
    timeout_seconds: float,
    graceful: bool,
) -> int:
    if process.poll() is not None:
        return int(process.returncode)
    if graceful and process.stdin is not None:
        try:
            process.stdin.write(json.dumps({"event": "shutdown"}) + "\n")
            process.stdin.flush()
        except BrokenPipeError:
            pass
    try:
        return process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            return process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            process.kill()
            return process.wait()


def execute(root: Path, spec_path: Path, output_path: Path) -> dict:
    spec = validate_spec(root, spec_path)
    if not path_is_within(output_path, root):
        raise ValueError("persistent-session output must be inside root")
    cwd = contained_path(root, spec["cwd"], "persistent-session cwd")
    logs_dir = output_path.parent / f"{output_path.stem}.logs"
    if output_path.exists() or logs_dir.exists():
        raise FileExistsError(
            "persistent-session evidence already exists; use a new output path"
        )
    logs_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = logs_dir / "worker.stdout.ndjson"
    stderr_path = logs_dir / "worker.stderr.txt"
    raw_stdout: list[str] = []
    raw_stderr: list[str] = []
    started_at = now()
    launch_started = time.monotonic()
    process = subprocess.Popen(
        spec["argv"],
        cwd=cwd,
        env=os.environ.copy(),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        bufsize=1,
    )
    assert process.stdout is not None and process.stderr is not None
    messages: queue.Queue[str | None] = queue.Queue()
    stdout_thread = threading.Thread(
        target=stream_reader, args=(process.stdout, messages), daemon=True
    )
    stderr_thread = threading.Thread(
        target=stderr_reader, args=(process.stderr, raw_stderr), daemon=True
    )
    stdout_thread.start()
    stderr_thread.start()
    failure: str | None = None
    ready: dict | None = None
    records: list[dict] = []
    exit_code = -1
    try:
        ready = receive(messages, spec["startup_timeout_seconds"], raw_stdout)
        setup_seconds = time.monotonic() - launch_started
        if ready.get("event") != "ready" or ready.get("protocol") != PROTOCOL:
            raise ValueError("worker did not emit the persistent-session ready contract")
        if ready.get("session_identity") != spec["expected_session_identity"]:
            raise ValueError("worker session identity does not match the sealed spec")
        if ready.get("engine_init_count") != 1:
            raise ValueError("persistent worker must report exactly one engine initialization")
        switching_supported = ready.get("switching_supported")
        if not isinstance(switching_supported, bool):
            raise ValueError("worker ready message must declare switching_supported")
        if spec["session_scope"] == "SHARED_TREATMENTS" and not switching_supported:
            raise ValueError("shared-treatment session requires safe switching support")
        assert process.stdin is not None
        for request in spec["requests"]:
            sent = {
                "event": "request",
                "request_id": request["request_id"],
                "treatment_identity": request["treatment_identity"],
                "payload": request["payload"],
            }
            request_started = time.monotonic()
            process.stdin.write(json.dumps(sent, separators=(",", ":")) + "\n")
            process.stdin.flush()
            response = receive(messages, spec["request_timeout_seconds"], raw_stdout)
            duration_seconds = time.monotonic() - request_started
            if response.get("event") != "result":
                raise ValueError("worker response is not a result")
            if response.get("request_id") != request["request_id"]:
                raise ValueError("worker response request_id mismatch")
            if response.get("treatment_identity") != request["treatment_identity"]:
                raise ValueError("worker response treatment identity mismatch")
            output_digest = response.get("output_digest")
            if not is_sha256(output_digest):
                raise ValueError("worker result output_digest must be SHA-256")
            records.append(
                {
                    "request_id": request["request_id"],
                    "treatment_identity": request["treatment_identity"],
                    "duration_seconds": duration_seconds,
                    "output_digest": output_digest,
                    "measurement": response.get("measurement"),
                }
            )
        exit_code = stop_worker(
            process, spec["shutdown_timeout_seconds"], graceful=True
        )
        if exit_code != 0:
            raise RuntimeError(f"persistent worker exited {exit_code}")
    except Exception as error:  # Preserve every protocol failure in the receipt.
        failure = f"{type(error).__name__}: {error}"
        setup_seconds = time.monotonic() - launch_started
        exit_code = stop_worker(
            process, spec["shutdown_timeout_seconds"], graceful=False
        )
    finally:
        stdout_thread.join(timeout=1.0)
        stderr_thread.join(timeout=1.0)
        stdout_path.write_text("".join(raw_stdout), encoding="utf-8")
        stderr_path.write_text("".join(raw_stderr), encoding="utf-8")
    receipt = {
        "schema_version": "persistent-session-receipt-v1",
        "status": "FAIL" if failure else "PASS",
        "started_at": started_at,
        "finished_at": now(),
        "spec_identity": {
            "path": spec_path.relative_to(root).as_posix(),
            "sha256": sha256(spec_path),
        },
        "session_scope": spec["session_scope"],
        "session_identity": (
            ready.get("session_identity") if isinstance(ready, dict) else None
        ),
        "switching_supported": (
            ready.get("switching_supported") if isinstance(ready, dict) else None
        ),
        "process_launches": 1,
        "engine_init_count": (
            ready.get("engine_init_count") if isinstance(ready, dict) else None
        ),
        "setup_seconds": setup_seconds,
        "steady_state_seconds": sum(row["duration_seconds"] for row in records),
        "request_count": len(records),
        "requests": records,
        "worker_exit_code": exit_code,
        "stdout": {
            "path": stdout_path.relative_to(root).as_posix(),
            "sha256": sha256(stdout_path),
        },
        "stderr": {
            "path": stderr_path.relative_to(root).as_posix(),
            "sha256": sha256(stderr_path),
        },
        "failure": failure,
    }
    atomic_json(output_path, receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    spec_path = args.spec.resolve()
    output_path = args.output.resolve()
    receipt = execute(root, spec_path, output_path)
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "receipt": str(output_path),
                "failure": receipt["failure"],
            },
            sort_keys=True,
        )
    )
    return 0 if receipt["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
