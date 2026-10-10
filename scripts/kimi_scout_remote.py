"""Opt-in SSH transport for tool-free Scout calls; the queue stays local.

Provision the exact SDK and a minimal provider config separately, in a private
remote root. No credentials are accepted in this controller transport file.
No request is retried after a broken connection or an ambiguous timeout.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path, PurePosixPath
import queue
import re
import shlex
import shutil
import sys
import threading
import time

from kimi_scout_resident import BackendPool, MAX_FRAME_BYTES, MAX_REQUESTS, load_backend


def ssh_command(path):
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(config, dict) or set(config) != {
        "host", "port", "root", "known_hosts"
    }:
        raise ValueError("invalid_remote_transport")
    host, port = config["host"], config["port"]
    if not isinstance(host, str) or not re.fullmatch(r"[\w.-]+@[\w.-]+", host):
        raise ValueError("invalid_remote_host")
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("invalid_remote_port")
    root = config["root"]
    if (not isinstance(root, str) or not root.startswith("/")
            or ".." in PurePosixPath(root).parts or root == "/"
            or not re.fullmatch(r"/[A-Za-z0-9_./-]+", root)):
        raise ValueError("invalid_remote_root")
    known_hosts = Path(config["known_hosts"])
    if not known_hosts.is_absolute() or not known_hosts.is_file():
        raise ValueError("pinned_known_hosts_required")
    remote = ["env", "CUDA_VISIBLE_DEVICES=", "PYTHONDONTWRITEBYTECODE=1",
              f"TMPDIR={root}/tmp", f"XDG_CACHE_HOME={root}/cache",
              f"{root}/venv/bin/python", "-I", "-B", "-X", "utf8",
              f"{root}/scripts/kimi_scout_remote.py", "--serve",
              "--config-file", f"{root}/provider.toml", "--root", root]
    # Isolated Python omits script sys.path. The bootstrap below inserts only the
    # controller-owned scripts directory, never a model-supplied path.
    script = remote.index(f"{root}/scripts/kimi_scout_remote.py")
    remote[script:script + 1] = ["-c", (
        "import runpy,sys;sys.path.insert(0," + repr(root + "/scripts") + ");"
        "runpy.run_path(" + repr(root + "/scripts/kimi_scout_remote.py")
        + ",run_name='__main__')"
    )]
    return ["ssh", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
            "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=2",
            "-o", "StrictHostKeyChecking=yes", "-o",
            f"UserKnownHostsFile={known_hosts}", "-p", str(port), host,
            "exec " + shlex.join(remote)]


class RemotePool(BackendPool):
    def __init__(self, transport, root, env, capacity):
        super().__init__(None, root, env, capacity, command=ssh_command(transport))

    def run(self, request, progress_file, timeout):
        # Stream text stays remote until the terminal response. The dashboard
        # still gets local requesting/completed/failed phases, without sending a
        # Windows filesystem path to a remote file writer.
        backend = load_backend()
        progress = backend.ProgressFile(Path(progress_file))
        backend.report_progress(progress, "", "requesting")
        try:
            result = super().run(request, progress_file, timeout)
            payload = json.loads(result.stdout)
            backend.report_progress(progress, payload.get("text", ""),
                                    "completed" if result.returncode == 0 else "failed")
            return result
        except BaseException:
            backend.report_progress(progress, "", "failed")
            raise


def resource_ready(root):
    """CPU-only headroom, including finite container limits, before each call."""
    mem = dict(line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines())
    available = int(mem["MemAvailable"].split()[0]) * 1024
    cg = Path("/sys/fs/cgroup")
    if (cg / "memory.max").exists():
        limit = (cg / "memory.max").read_text().strip()
        if limit != "max":
            available = min(available, int(limit) - int((cg / "memory.current").read_text()))
    return available >= 1024 ** 3 and shutil.disk_usage(root).free >= 1024 ** 3


def serve(config_file, root, source, output, *, exit_on_eof=os._exit):
    backend = load_backend()
    if not sys.flags.isolated:
        raise backend.BackendError("isolated_python_required_use_dash_I")
    if config_file.is_symlink() or config_file.stat().st_mode & 0o077:
        raise backend.BackendError("private_provider_file_required")
    provider = backend.load_provider(config_file)
    incoming = queue.Queue(maxsize=1)

    def read():
        while True:
            raw = source.readline(MAX_FRAME_BYTES + 1)
            if not raw:
                # SSH disconnect closes stdin even during an API call. There
                # are no native subprocesses to orphan: end this owned worker
                # immediately, rather than billing until the API timeout.
                exit_on_eof(0)
                return
            incoming.put(raw)
            if len(raw) > MAX_FRAME_BYTES or not raw.endswith(b"\n"):
                return

    threading.Thread(target=read, daemon=True).start()
    for _ in range(MAX_REQUESTS):
        try:
            raw = incoming.get(timeout=300)
        except queue.Empty:
            return
        if len(raw) > MAX_FRAME_BYTES or not raw.endswith(b"\n"):
            return
        started = time.monotonic()
        request_id = None
        try:
            envelope = json.loads(raw)
            if not isinstance(envelope, dict) or set(envelope) != {
                "request_id", "request", "progress_file"
            }:
                raise backend.BackendError("invalid_envelope")
            request_id = envelope["request_id"]
            if not isinstance(request_id, str) or not re.fullmatch(r"[a-f0-9]{32}", request_id):
                raise backend.BackendError("invalid_request_id")
            request = backend.read_request(json.dumps(envelope["request"]).encode())
            # progress_file is deliberately ignored, never opened on this host.
            if not resource_ready(root):
                raise backend.BackendError("remote_resource_headroom_unavailable")
            payload = asyncio.run(backend.complete(request, provider, None))
            payload.update(kimi_version=backend.SUPPORTED_KIMI_VERSION,
                           model_alias=provider["model_alias"], provider_type="kimi")
        except Exception as error:
            payload = backend.safe_error(error)
        payload["elapsed_seconds"] = round(time.monotonic() - started, 3)
        output.write(json.dumps({"request_id": request_id, "payload": payload}) + "\n")
        output.flush()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve", action="store_true", required=True)
    parser.add_argument("--config-file", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    try:
        serve(args.config_file, args.root, sys.stdin.buffer, sys.stdout)
    except Exception:
        return 1  # Never print configuration or provider exception text.
    return 0


if __name__ == "__main__":
    os._exit(main())
