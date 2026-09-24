#!/usr/bin/env python3
"""Dispatch one *reviewed* Scout GPU screen to a task-private Linux worker.

Kimi may propose code and repairs, but it cannot create the reviewed hash
manifest accepted here. This worker never publishes a PR or performance claim.
The remote verifier bounds child time, memory, output, and GPU identity.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
import subprocess
from pathlib import Path

from kimi_scout_gpu_verify import UUID_RE, reviewed_inputs

HOST_RE = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9.-]*\Z")
MAX_REMOTE_OUTPUT = 131_072
REMOTE_ROOT = "/workspace/kernel-opt/kimi-scout-gpu"


def dispatch_plan(args):
    if not HOST_RE.fullmatch(args.host) or ".." in args.host:
        raise ValueError("host must be a DNS name or IP literal without options")
    if not 1 <= args.port <= 65535:
        raise ValueError("invalid SSH port")
    if not re.fullmatch(UUID_RE, args.gpu_uuid):
        raise ValueError("a full GPU UUID is required")
    if not args.python.startswith("/") or not re.fullmatch(
        r"/[a-zA-Z0-9_./-]+", args.python
    ):
        raise ValueError("worker Python must be an absolute literal path")
    paths = {
        "baseline": args.baseline,
        "candidate": args.candidate,
        "test": args.test,
    }
    _, hashes = reviewed_inputs(paths, args.reviewed_sha256)
    verifier = Path(__file__).with_name("kimi_scout_gpu_verify.py").resolve()
    verifier_hash = hashlib.sha256(verifier.read_bytes()).hexdigest()
    review_hash = hashlib.sha256(Path(args.reviewed_sha256).read_bytes()).hexdigest()
    remote = f"{REMOTE_ROOT}/{review_hash[:24]}"
    ssh_options = [
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=8",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
    ]
    target = f"root@{args.host}"
    ssh = ["ssh", *ssh_options, "-p", str(args.port), target]
    scp = ["scp", *ssh_options, "-P", str(args.port)]
    files = [
        Path(args.baseline).resolve(),
        Path(args.candidate).resolve(),
        Path(args.test).resolve(),
        Path(args.reviewed_sha256).resolve(),
        verifier,
    ]
    names = ["baseline.py", "candidate.py", "test.py", "reviewed.json", "verify.py"]
    file_hashes = {
        name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path, name in zip(files, names, strict=True)
    }
    remote_command = shlex.join(
        [
            args.python,
            "-B",
            "verify.py",
            "--baseline",
            "baseline.py",
            "--candidate",
            "candidate.py",
            "--test",
            "test.py",
            "--gpu-uuid",
            args.gpu_uuid,
            "--reviewed-sha256",
            "reviewed.json",
            "--lock-dir",
            "/workspace/kernel-opt/direct-gpu-locks",
        ]
    )
    return {
        "scope": "REVIEWED_SINGLE_MODULE_GPU_SCREEN",
        "host": args.host,
        "port": args.port,
        "gpu_uuid": args.gpu_uuid,
        "reviewed_sha256": hashes,
        "review_file_sha256": review_hash,
        "verifier_sha256": verifier_hash,
        "remote_dir": remote,
        "local_files": [str(path) for path in files],
        "remote_names": names,
        "remote_file_sha256": file_hashes,
        "ssh": ssh,
        "scp": scp,
        "command": remote_command,
    }


def bounded_run(command, timeout):
    result = subprocess.run(command, capture_output=True, timeout=timeout, check=False)
    if len(result.stdout) > MAX_REMOTE_OUTPUT or len(result.stderr) > MAX_REMOTE_OUTPUT:
        raise RuntimeError("worker output exceeded bound")
    return result


def execute(plan):
    remote = plan["remote_dir"]
    ssh = plan["ssh"]
    scp = plan["scp"]
    if bounded_run([*ssh, shlex.join(["mkdir", "-p", remote])], 20).returncode:
        raise RuntimeError("worker directory setup failed")
    # Copy under fixed names so no model-generated path enters the remote shell.
    for local, name in zip(plan["local_files"], plan["remote_names"], strict=True):
        result = bounded_run([*scp, local, f"root@{plan['host']}:{remote}/{name}"], 30)
        if result.returncode:
            raise RuntimeError("worker input transfer failed")
    hash_command = (
        shlex.join(["cd", remote])
        + " && "
        + shlex.join(["sha256sum", *plan["remote_names"]])
    )
    hashes = bounded_run([*ssh, hash_command], 20)
    if hashes.returncode:
        raise RuntimeError("worker input hashes unavailable")
    observed = {}
    for line in hashes.stdout.decode("ascii").splitlines():
        digest, separator, name = line.partition("  ")
        if not separator or name in observed:
            raise RuntimeError("worker input hash output malformed")
        observed[name] = digest
    if observed != plan["remote_file_sha256"]:
        raise RuntimeError("worker input hash mismatch")
    command = shlex.join(["cd", remote]) + " && " + plan["command"]
    result = bounded_run([*ssh, command], 120)
    try:
        report = json.loads(result.stdout.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise RuntimeError("worker did not return one JSON report") from exc
    if not isinstance(report, dict):
        raise TypeError("worker report is not an object")
    if report.get("reviewed_sha256") != plan["reviewed_sha256"]:
        raise RuntimeError("worker reviewed identity mismatch")
    if report.get("gpu_uuid", "").lower() != plan["gpu_uuid"].lower():
        raise RuntimeError("worker GPU identity mismatch")
    if (
        report.get("scope")
        != "OWNER_REVIEWED_SINGLE_MODULE_GPU_SCREEN_NOT_UPSTREAM_SUITE"
    ):
        raise RuntimeError("worker scope mismatch")
    if report.get("qualified") is not False:
        raise RuntimeError("worker scope incorrectly claims qualification")
    if type(report.get("screen_passed")) is not bool:
        raise RuntimeError("worker screen verdict missing")
    if (result.returncode == 0) != report["screen_passed"]:
        raise RuntimeError("worker exit/verdict mismatch")
    return {
        "plan": {
            k: plan[k]
            for k in (
                "scope",
                "host",
                "port",
                "gpu_uuid",
                "reviewed_sha256",
                "review_file_sha256",
                "verifier_sha256",
                "remote_dir",
            )
        },
        "worker_exit_code": result.returncode,
        "report": report,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "baseline",
        "candidate",
        "test",
        "reviewed-sha256",
        "host",
        "gpu-uuid",
    ):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--python", default="/usr/bin/python3")
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--result", type=Path)
    args = parser.parse_args(argv)
    if not args.check_only and args.result is None:
        parser.error("--result is required for execution")
    plan = dispatch_plan(args)
    output = plan if args.check_only else execute(plan)
    serialized = json.dumps(output, ensure_ascii=False, sort_keys=True) + "\n"
    if args.result is not None:
        destination = args.result.resolve()
        if destination.exists():
            raise ValueError("result path already exists")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(serialized, encoding="utf-8")
    print(serialized, end="")
    return 0 if args.check_only or output["report"].get("screen_passed") else 2


if __name__ == "__main__":
    raise SystemExit(main())
