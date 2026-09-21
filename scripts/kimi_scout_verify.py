#!/usr/bin/env python3
"""Opt-in, two-run CPU evidence for three explicitly selected public Python files.

Run on Linux/WSL with an existing Docker daemon and the pinned cached image.
No model calls, dependency installation, queue dispatch, or publication occurs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

IMAGE = "sha256:a041b350d5d9483b538d5af07e9553ee8cbc7fc7fa90c2f7d20d93f18ce9bbd1"
TORCH_CPU_IMAGE = (
    "sha256:83727efdf2e8586e9193b08efb5c334c4b52abae93319c5db3cc34b3bd2295c0"
)
PROFILES = {
    "stdlib": (IMAGE, "/usr/local/bin/python3", "512m"),
    "torch-cpu": (TORCH_CPU_IMAGE, "/opt/venv/bin/python", "2g"),
}
CLAIM_SCOPE = "ADAPTED_SINGLE_MODULE_CPU_SCREEN_NOT_UPSTREAM_SUITE"
DOCKER = [
    "/usr/bin/docker",
    "--host",
    "unix:///var/run/docker.sock",
    "--config",
    "/nonexistent",
]
ENV = {"PATH": "/usr/bin:/bin", "HOME": "/nonexistent"}
MAX_FILE_BYTES = 262_144
MAX_OUTPUT_BYTES = 32_768
MARKER = "KIMI_VERIFY_TEST_COUNT="
HARNESS = """import sys, unittest
sys.path.insert(0, '/input')
suite = unittest.defaultTestLoader.discover('/input', pattern='test_subject.py')
count = suite.countTestCases()
if not count:
    print('KIMI_VERIFY_TEST_COUNT=0', flush=True)
    sys.exit(5)
result = unittest.TextTestRunner(verbosity=2).run(suite)
print('KIMI_VERIFY_TEST_COUNT=' + str(result.testsRun), flush=True)
sys.exit(0 if result.wasSuccessful() else 1)
"""


def read_input(value):
    path = Path(value).absolute()
    if path.suffix != ".py" or any(c in str(path) for c in ",\n\r\x00"):
        raise ValueError("inputs must be individual .py files with safe mount paths")
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("symlink inputs or parent directories are not supported")
    if not stat.S_ISREG(path.stat().st_mode):
        raise ValueError("inputs must be regular files")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("inputs must be regular files")
        content = stream.read(MAX_FILE_BYTES + 1)
    if len(content) > MAX_FILE_BYTES:
        raise ValueError("input file exceeds 256 KiB")
    return content


def command(subject, test, name, *, profile="stdlib"):
    if not re.fullmatch(r"kimi-verify-[0-9a-f]{32}", name):
        raise ValueError("container name must be controller-generated")
    if profile not in PROFILES:
        raise ValueError("profile must be stdlib or torch-cpu")
    image, python, memory = PROFILES[profile]
    return DOCKER + [
        "run",
        "--pull",
        "never",
        "--name",
        name,
        "--runtime",
        "runc",
        "--log-driver",
        "none",
        "--network",
        "none",
        "--read-only",
        "--user",
        "65534:65534",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges=true",
        "--memory",
        memory,
        "--memory-swap",
        memory,
        "--cpus",
        "1",
        "--pids-limit",
        "64",
        "--ulimit",
        "core=0",
        "--ulimit",
        "nofile=64:64",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777",
        "--env",
        "HOME=/tmp",
        "--env",
        "LD_PRELOAD=",
        "--env",
        "CUDA_VISIBLE_DEVICES=",
        "--workdir",
        "/tmp",
        "--mount",
        f"type=bind,src={subject},dst=/input/subject.py,readonly",
        "--mount",
        f"type=bind,src={test},dst=/input/test_subject.py,readonly",
        "--entrypoint",
        python,
        image,
        "-I",
        "-B",
        "-c",
        HARNESS,
    ]


def run_case(subject, test, timeout, *, profile="stdlib"):
    name = "kimi-verify-" + uuid.uuid4().hex
    started = time.monotonic()
    captured = bytearray()
    truncated = False
    timed_out = False
    cleanup_ok = False
    process = None
    reader = None

    def drain():
        nonlocal truncated
        while chunk := process.stdout.read(4096):
            remaining = MAX_OUTPUT_BYTES - len(captured)
            captured.extend(chunk[:remaining])
            truncated |= len(chunk) > remaining

    try:
        process = subprocess.Popen(
            command(subject, test, name, profile=profile),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=ENV,
        )
        reader = threading.Thread(target=drain, daemon=True)
        reader.start()
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            process.kill()
            process.wait(timeout=5)
    finally:
        if process is not None:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            try:
                cleanup = subprocess.run(
                    DOCKER + ["rm", "--force", name],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env=ENV,
                    timeout=10,
                    check=False,
                )
                cleanup_ok = cleanup.returncode == 0
            except (OSError, subprocess.TimeoutExpired):
                cleanup_ok = False
            if reader:
                reader.join(timeout=2)
    output = captured.decode("utf-8", errors="replace")
    counts = re.findall(r"(?m)^" + MARKER + r"(\d+)$", output)
    count = int(counts[-1]) if counts else None
    return {
        "profile": profile,
        "claim_scope": CLAIM_SCOPE,
        "exit_code": None if timed_out else process.returncode,
        "seconds": round(time.monotonic() - started, 3),
        "timed_out": timed_out,
        "output_truncated": truncated,
        "cleanup_ok": cleanup_ok,
        "reported_tests_run": count,
        "output": output,
        "inconclusive": timed_out
        or truncated
        or not cleanup_ok
        or not count
        or bool(reader and reader.is_alive()),
    }


def verify(baseline, candidate, test, *, timeout=60, profile="stdlib"):
    if sys.platform != "linux":
        raise ValueError("run this opt-in verifier inside Linux/WSL")
    if type(timeout) not in (int, float) or not 1 <= timeout <= 120:
        raise ValueError("timeout must be 1..120 seconds per run")
    if profile not in PROFILES:
        raise ValueError("profile must be stdlib or torch-cpu")
    contents = {
        key: read_input(value)
        for key, value in (
            ("baseline", baseline),
            ("candidate", candidate),
            ("test", test),
        )
    }
    # Immutable byte snapshots prevent source edits between hashing and mounting.
    with tempfile.TemporaryDirectory(prefix="kimi-verify-") as directory:
        files = {}
        for key, content in contents.items():
            path = Path(directory) / (key + ".py")
            path.write_bytes(content)
            path.chmod(0o444)
            files[key] = path
        before = run_case(files["baseline"], files["test"], timeout, profile=profile)
        fixed = (
            run_case(files["candidate"], files["test"], timeout, profile=profile)
            if before["cleanup_ok"]
            else {
                "exit_code": None,
                "inconclusive": True,
                "skipped": "baseline cleanup failed",
            }
        )
    return {
        "label": "TEST_RESULT_NOT_PR_READY",
        "profile": profile,
        "claim_scope": CLAIM_SCOPE,
        "image": PROFILES[profile][0],
        "input_sha256": {
            key: hashlib.sha256(data).hexdigest() for key, data in contents.items()
        },
        "before": before,
        "fixed": fixed,
        "inconclusive": before["inconclusive"] or fixed["inconclusive"],
        "meaning": "Exit codes and untrusted test output only; a reviewer must judge test relevance and assertions.",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--test", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--profile", choices=tuple(PROFILES), default="stdlib")
    args = parser.parse_args(argv)
    try:
        result = verify(
            args.baseline,
            args.candidate,
            args.test,
            timeout=args.timeout,
            profile=args.profile,
        )
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        result = {
            "label": "TEST_RESULT_NOT_PR_READY",
            "profile": args.profile,
            "claim_scope": CLAIM_SCOPE,
            "inconclusive": True,
            "error": type(error).__name__,
        }
    print(json.dumps(result, ensure_ascii=True))
    return int(result["inconclusive"])


if __name__ == "__main__":
    raise SystemExit(main())
