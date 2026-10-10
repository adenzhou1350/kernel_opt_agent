"""Opt-in, bounded tool-free backend reuse; never retries an ambiguous request.

Only Python/SDK imports and configuration are reused, not conversation state.
Each child retires after 32 requests. Provider clients/streams still close after
each completion. No listener, agent tools, workspace scans or shared log daemon.
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import uuid

MAX_REQUESTS = 32
MAX_FRAME_BYTES = 1_000_000
SCRIPT = Path(__file__).resolve()


def load_backend():
    spec = importlib.util.spec_from_file_location(
        "scout_tool_free_backend", SCRIPT.with_name("kimi_scout_backend.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def serve(config_file, source, output):
    """Controller-only JSONL envelopes; supplied source never selects a path."""
    backend = load_backend()
    if not sys.flags.isolated:
        raise backend.BackendError("isolated_python_required_use_dash_I")
    provider = backend.load_provider(config_file)
    for _ in range(MAX_REQUESTS):
        raw = source.readline(MAX_FRAME_BYTES + 1)
        if not raw:
            return
        # A truncated/oversized frame makes subsequent framing ambiguous.
        if len(raw) > MAX_FRAME_BYTES or not raw.endswith(b"\n"):
            return
        started = time.monotonic()
        request_id = None
        progress = None
        try:
            envelope = json.loads(raw)
            if not isinstance(envelope, dict) or set(envelope) != {
                "request_id", "request", "progress_file"
            }:
                raise backend.BackendError("invalid_envelope")
            request_id = envelope["request_id"]
            if not isinstance(request_id, str) or len(request_id) != 32:
                raise backend.BackendError("invalid_request_id")
            request = backend.read_request(json.dumps(envelope["request"]).encode())
            path = envelope["progress_file"]
            if not isinstance(path, str) or not Path(path).is_absolute():
                raise backend.BackendError("absolute_progress_file_required")
            progress = backend.ProgressFile(Path(path))
            payload = asyncio.run(backend.complete(request, provider, progress))
            payload.update(kimi_version=backend.SUPPORTED_KIMI_VERSION,
                           model_alias=provider["model_alias"], provider_type="kimi")
        except Exception as error:
            payload = backend.safe_error(error)
            if progress is not None and progress.phase not in {"completed", "failed"}:
                backend.report_progress(progress, "", "failed")
        payload["elapsed_seconds"] = round(time.monotonic() - started, 3)
        output.write(json.dumps({"request_id": request_id, "payload": payload}) + "\n")
        output.flush()


class Worker:
    def __init__(self, command, cwd, env):
        self.process = subprocess.Popen(
            command, cwd=cwd, env=env, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        self.responses = queue.Queue(maxsize=2)
        self.calls = 0
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self):
        try:
            for _ in range(MAX_REQUESTS + 1):
                raw = self.process.stdout.readline(MAX_FRAME_BYTES + 1)
                self.responses.put_nowait(raw)
                if not raw or len(raw) > MAX_FRAME_BYTES:
                    return
        except (OSError, ValueError, queue.Full):
            # The controller rejects a missing frame at its deadline.
            return

    def call(self, request, progress_file, timeout):
        request_id = uuid.uuid4().hex
        frame = json.dumps({"request_id": request_id, "request": request,
                            "progress_file": str(progress_file)}).encode() + b"\n"
        if len(frame) > MAX_FRAME_BYTES:
            raise ValueError("resident_request_too_large")
        self.calls += 1

        def write():
            try:
                self.process.stdin.write(frame)
                self.process.stdin.flush()
            except (OSError, ValueError):
                try:
                    self.responses.put_nowait(b"")
                except queue.Full:
                    pass

        # A child stalled before reading stdin must not bypass the parent deadline.
        self.writer = threading.Thread(target=write, daemon=True)
        self.writer.start()
        try:
            raw = self.responses.get(timeout=timeout)
        except queue.Empty:
            raise subprocess.TimeoutExpired("resident_backend", timeout) from None
        if not raw or len(raw) > MAX_FRAME_BYTES or not raw.endswith(b"\n"):
            raise ValueError("invalid_resident_protocol")
        try:
            response = json.loads(raw)
        except (ValueError, UnicodeError):
            raise ValueError("invalid_resident_protocol") from None
        if (not isinstance(response, dict)
                or set(response) != {"request_id", "payload"}
                or response["request_id"] != request_id
                or not isinstance(response["payload"], dict)):
            raise ValueError("invalid_resident_protocol")
        payload = response["payload"]
        code = 0 if payload.get("ok") is True else (75 if payload.get("retryable") else 1)
        return subprocess.CompletedProcess("resident_backend", code,
                                           json.dumps(payload), "")

    def close(self):
        process = self.process
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
        for stream in (process.stdin, process.stdout):
            try:
                stream.close()
            except (OSError, ValueError):
                pass
        self.reader.join(timeout=3)
        if hasattr(self, "writer"):
            self.writer.join(timeout=3)


class BackendPool:
    """At most capacity owned children; caller closes after its task threads drain."""
    def __init__(self, python, root, env, capacity, *, command=None):
        if type(capacity) is not int or not 1 <= capacity <= 16:
            raise ValueError("invalid_resident_capacity")
        self.command = command or [str(python), "-I", "-B", "-X", "utf8",
                                   str(SCRIPT), "--serve"]
        self.cwd, self.env = root, env
        # Reuse a warm returned slot before untouched empty capacity. FIFO
        # cold-starts every slot even when only one request is active at a time.
        self.idle = queue.LifoQueue(maxsize=capacity)
        for _ in range(capacity):
            self.idle.put(None)
        self.closed = False
        self.process_starts = 0

    def run(self, request, progress_file, timeout):
        if self.closed:
            raise ValueError("resident_pool_closed")
        started = time.monotonic()
        try:
            worker = self.idle.get(timeout=timeout)
        except queue.Empty:
            raise subprocess.TimeoutExpired("resident_pool", timeout) from None
        try:
            if worker is not None and worker.process.poll() is not None:
                # A remotely idle worker may have retired. No frame for this
                # call has been sent yet, so replacing it is not a replay.
                worker.close()
                worker = None
            if worker is None:
                worker = Worker(self.command, self.cwd, self.env)
                self.process_starts += 1
            remaining = timeout - (time.monotonic() - started)
            if remaining <= 0:
                raise subprocess.TimeoutExpired("resident_pool", timeout)
            result = worker.call(request, progress_file, remaining)
            if worker.calls >= MAX_REQUESTS or result.returncode:
                worker.close()
                worker = None
            return result
        except BaseException:
            if worker is not None:
                worker.close()
                worker = None
            raise
        finally:
            self.idle.put(worker)

    def close(self):
        self.closed = True
        while not self.idle.empty():
            worker = self.idle.get_nowait()
            if worker is not None:
                worker.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve", action="store_true", required=True)
    parser.add_argument("--config-file", type=Path, default=Path.home() / ".kimi/config.toml")
    args = parser.parse_args()
    try:
        serve(args.config_file, sys.stdin.buffer, sys.stdout)
    except Exception:
        # Startup/configuration diagnostics must never contain credentials.
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
