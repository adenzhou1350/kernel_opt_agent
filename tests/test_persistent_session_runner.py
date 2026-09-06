#!/usr/bin/env python3
"""Exercise persistent-session reuse and fail-closed identity handling."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "persistent_session_runner.py"
WORKER = ROOT / "tests" / "fixtures" / "persistent_worker.py"
SESSION_ID = hashlib.sha256(WORKER.read_bytes()).hexdigest()
TREATMENT_A = hashlib.sha256(b"treatment-a").hexdigest()
TREATMENT_B = hashlib.sha256(b"treatment-b").hexdigest()


def write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def spec(switching: bool = False) -> dict:
    argv = [sys.executable, str(WORKER), "--session-identity", SESSION_ID]
    if switching:
        argv.append("--switching")
    return {
        "schema_version": "persistent-session-spec-v1",
        "argv": argv,
        "cwd": ".",
        "session_scope": "SINGLE_TREATMENT",
        "expected_session_identity": SESSION_ID,
        "startup_timeout_seconds": 5.0,
        "request_timeout_seconds": 5.0,
        "shutdown_timeout_seconds": 2.0,
        "requests": [
            {
                "request_id": f"request-{index}",
                "treatment_identity": TREATMENT_A,
                "payload": {"value": index},
            }
            for index in range(3)
        ],
    }


def run(root: Path, specification: dict, expected: int) -> dict:
    spec_path = root / "session.json"
    output_path = root / "receipt.json"
    write(spec_path, specification)
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--root",
            str(root),
            "--spec",
            str(spec_path),
            "--output",
            str(output_path),
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
    )
    assert completed.returncode == expected, (completed.stdout, completed.stderr)
    return json.loads(output_path.read_text(encoding="utf-8"))


def main() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        receipt = run(root, spec(), 0)
        assert receipt["status"] == "PASS"
        assert receipt["process_launches"] == 1
        assert receipt["engine_init_count"] == 1
        assert receipt["request_count"] == 3
        assert len(receipt["requests"]) == 3
        assert receipt["setup_seconds"] >= 0
        assert receipt["steady_state_seconds"] > 0
        assert all(
            row["treatment_identity"] == TREATMENT_A
            for row in receipt["requests"]
        )
        completed = subprocess.run(
            [
                sys.executable,
                str(RUNNER),
                "--root",
                str(root),
                "--spec",
                str(root / "session.json"),
                "--output",
                str(root / "receipt.json"),
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        assert completed.returncode != 0
        assert "evidence already exists" in completed.stderr

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        malformed = spec()
        malformed["requests"][0]["treatment_identity"] = "z" * 64
        spec_path = root / "session.json"
        write(spec_path, malformed)
        completed = subprocess.run(
            [
                sys.executable,
                str(RUNNER),
                "--root",
                str(root),
                "--spec",
                str(spec_path),
                "--output",
                str(root / "receipt.json"),
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        assert completed.returncode != 0
        assert "treatment identity is invalid" in completed.stderr

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        unsafe = spec()
        unsafe["session_scope"] = "SHARED_TREATMENTS"
        unsafe["requests"][1]["treatment_identity"] = TREATMENT_B
        receipt = run(root, unsafe, 1)
        assert receipt["status"] == "FAIL"
        assert "safe switching support" in receipt["failure"]
        assert receipt["request_count"] == 0

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        wrong_identity = spec(switching=True)
        wrong_identity["session_scope"] = "SHARED_TREATMENTS"
        wrong_identity["requests"][1]["treatment_identity"] = TREATMENT_B
        wrong_identity["requests"][1]["payload"][
            "returned_treatment_identity"
        ] = TREATMENT_A
        receipt = run(root, wrong_identity, 1)
        assert receipt["status"] == "FAIL"
        assert "treatment identity mismatch" in receipt["failure"]
        assert receipt["request_count"] == 1

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        timeout = spec()
        timeout["request_timeout_seconds"] = 0.01
        timeout["requests"][0]["payload"]["sleep_seconds"] = 0.1
        receipt = run(root, timeout, 1)
        assert receipt["status"] == "FAIL"
        assert "worker response exceeded" in receipt["failure"]

    print("persistent session runner test: PASS")


if __name__ == "__main__":
    main()
