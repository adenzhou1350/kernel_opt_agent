#!/usr/bin/env python3
"""Consume hash-reviewed Scout GPU jobs without giving Kimi shell access.

Only a separate controller/reviewer may place approval JSON in
``delivery/gpu-approved``. Kimi-generated proposals alone are never executed.
Each approval is attempted at most once; a terminal receipt is kept even on
failure, so an uncertain launch cannot silently retry.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from pathlib import Path
from types import SimpleNamespace

from kimi_scout import single_runner
from kimi_scout_gpu_dispatch import dispatch_plan, execute

JOB_RE = re.compile(r"[0-9a-f]{24}\Z")
ATTEMPT_RE = re.compile(r"([0-9a-f]{24})-v([2-9][0-9]*)\Z")
NAME_RE = re.compile(r"[a-zA-Z0-9_-]+\.py\Z")
SCHEMA = "kimi-scout-gpu-reviewed-job-v1"
SCHEMA_V2 = "kimi-scout-gpu-reviewed-job-v2"


def parse_approval(root: Path, path: Path):
    approval = json.loads(path.read_text(encoding="utf-8"))
    base_fields = {
        "schema_version",
        "job_id",
        "host",
        "port",
        "gpu_uuid",
        "python",
        "files",
        "reviewed_manifest_sha256",
    }
    if not isinstance(approval, dict):
        raise TypeError("approval must be an object")
    schema = approval.get("schema_version")
    extra = (
        {"attempt_id", "supersedes_terminal_sha256"} if schema == SCHEMA_V2 else set()
    )
    if schema not in {SCHEMA, SCHEMA_V2} or set(approval) != base_fields | extra:
        raise ValueError("approval fields are not exact")
    if not isinstance(approval["job_id"], str) or not JOB_RE.fullmatch(
        approval["job_id"]
    ):
        raise ValueError("approval job identity invalid")
    if schema == SCHEMA:
        if path.stem != approval["job_id"]:
            raise ValueError("approval filename must equal job id")
    else:
        attempt = approval["attempt_id"]
        match = ATTEMPT_RE.fullmatch(attempt) if isinstance(attempt, str) else None
        if not match or match.group(1) != approval["job_id"] or path.stem != attempt:
            raise ValueError("versioned approval identity invalid")
        number = int(match.group(2))
        predecessor = approval["job_id"] + (f"-v{number - 1}" if number > 2 else "")
        previous = root / "delivery" / "gpu-results" / f"{predecessor}.json"
        prior_bytes = previous.read_bytes()
        expected_previous = approval["supersedes_terminal_sha256"]
        if (
            not isinstance(expected_previous, str)
            or not re.fullmatch(r"[0-9a-f]{64}", expected_previous)
            or hashlib.sha256(prior_bytes).hexdigest() != expected_previous
        ):
            raise ValueError("superseded terminal identity invalid")
        prior = json.loads(prior_bytes)
        arms = prior.get("result", {}).get("report", {}).get("arms", {})
        if (
            prior.get("state") != "SCREEN_FAIL"
            or not arms
            or not all(arm.get("cleanup") is True for arm in arms.values())
        ):
            raise ValueError("prior attempt is not a clean terminal failure")
    files = approval["files"]
    if not isinstance(files, dict) or set(files) != {
        "baseline",
        "candidate",
        "test",
        "reviewed",
    }:
        raise ValueError("approval files are not exact")
    if not all(
        isinstance(value, str) and NAME_RE.fullmatch(value)
        for key, value in files.items()
        if key != "reviewed"
    ):
        raise ValueError("approval code filenames invalid")
    if not isinstance(files["reviewed"], str) or not re.fullmatch(
        r"[a-zA-Z0-9_-]+\.json", files["reviewed"]
    ):
        raise ValueError("reviewed manifest filename invalid")
    job = root / "delivery" / "jobs" / approval["job_id"]
    manifest = job / files["reviewed"]
    expected = approval["reviewed_manifest_sha256"]
    if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ValueError("reviewed manifest digest invalid")
    if hashlib.sha256(manifest.read_bytes()).hexdigest() != expected:
        raise ValueError("reviewed manifest digest changed")
    args = SimpleNamespace(
        baseline=str(job / files["baseline"]),
        candidate=str(job / files["candidate"]),
        test=str(job / files["test"]),
        reviewed_sha256=str(manifest),
        host=approval["host"],
        port=approval["port"],
        gpu_uuid=approval["gpu_uuid"],
        python=approval["python"],
    )
    return args, approval


def process_one(root: Path, approval_path: Path):
    results = root / "delivery" / "gpu-results"
    results.mkdir(parents=True, exist_ok=True)
    terminal = results / approval_path.name
    if terminal.exists():
        return None
    approval_hash = hashlib.sha256(approval_path.read_bytes()).hexdigest()
    record = {
        "schema_version": "kimi-scout-gpu-queue-terminal-v1",
        "approval_sha256": approval_hash,
        "approval_path": str(approval_path),
        "state": "STARTED_UNCERTAIN",
    }
    # Claim before any remote command. A crash leaves STARTED_UNCERTAIN and
    # cannot silently relaunch a possibly running GPU child.
    with terminal.open("x", encoding="utf-8") as stream:
        json.dump(record, stream, ensure_ascii=False, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    try:
        args, _ = parse_approval(root, approval_path)
        plan = dispatch_plan(args)
        record["result"] = execute(plan)
        record["state"] = (
            "SCREEN_PASS_NOT_UPSTREAM_QUALIFIED"
            if record["result"]["report"]["screen_passed"]
            else "SCREEN_FAIL"
        )
    except Exception as exc:  # noqa: BLE001 - terminal boundary: never retry unknown launch
        record["error_type"] = type(exc).__name__
        record["error"] = str(exc)[:512]
    temporary = results / f".{approval_path.name}.{os.getpid()}.tmp"
    with temporary.open("x", encoding="utf-8") as stream:
        json.dump(record, stream, ensure_ascii=False, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, terminal)
    if "result" in record:
        publish_latest(root, approval_path, record)
    return record


def publish_latest(root: Path, approval_path: Path, record: dict):
    """Expose a compact historical receipt to the existing dashboard."""
    report = record["result"]["report"]
    arms = report.get("arms", {})
    baseline, candidate = arms.get("baseline", {}), arms.get("candidate", {})
    source = root / "delivery" / "jobs" / approval_path.stem[:24] / "source.json"
    try:
        repo = (
            json.loads(source.read_text(encoding="utf-8"))
            .get("context", {})
            .get("repo", "")
        )
    except (OSError, ValueError, AttributeError):
        repo = ""
    latest = {
        "at": time.time(),
        "repo": repo,
        "lead_id": approval_path.stem[:24],
        "gpu_uuid": report.get("gpu_uuid"),
        "baseline_exit": baseline.get("exit_code"),
        "candidate_exit": candidate.get("exit_code"),
        "tests_run": (candidate.get("tests") or {}).get("tests_run"),
        "cleanup_ok": bool(arms)
        and all(arm.get("cleanup") is True for arm in arms.values()),
        "scope": report.get("scope"),
        "screen_passed": report.get("screen_passed") is True,
        "terminal_sha256": hashlib.sha256(
            (root / "delivery" / "gpu-results" / approval_path.name).read_bytes()
        ).hexdigest(),
    }
    path = root / "delivery" / "gpu-latest.json"
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(latest, stream, ensure_ascii=False, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except OSError:
        temporary.unlink(missing_ok=True)


def run_once(root: Path):
    approvals = root / "delivery" / "gpu-approved"
    approvals.mkdir(parents=True, exist_ok=True)
    results = root / "delivery" / "gpu-results"
    results.mkdir(parents=True, exist_ok=True)
    with single_runner(results):
        for path in sorted(approvals.glob("*.json")):
            result = process_one(root, path)
            if result is not None:
                return result
    return None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--poll-seconds", type=int, default=30)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    if not 1 <= args.poll_seconds <= 300:
        parser.error("poll interval must be 1..300 seconds")
    root = args.root.resolve()
    while True:
        result = run_once(root)
        if result is not None:
            print(json.dumps(result, ensure_ascii=False), flush=True)
        if args.once or (root / "delivery" / "GPU_STOP").exists():
            return 0
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
