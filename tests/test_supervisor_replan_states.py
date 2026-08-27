#!/usr/bin/env python3
"""Verify that failed experiments cannot silently re-enter PLANNED."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def exercise(receipt_status: str, request_status: str, expected: str) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        run = Path(temporary) / "run"
        experiment = run / "experiments/request"
        experiment.mkdir(parents=True)
        write(run / "models/experiment_queue.json", {
            "schema_version": "experiment-request-queue-v2",
            "requests": [{
                "request_id": "request", "status": request_status,
                "supervisor_approval": {"path": "experiments/request/supervisor_approval.json", "sha256": "0" * 64},
            }],
        })
        write(experiment / "experiment.json", {"request_id": "request", "status": "MATERIALIZED"})
        write(experiment / "supervisor_approval.json", {"approval": "fixture"})
        write(experiment / "execution_receipt.json", {"request_id": "request", "status": receipt_status})
        review = run / "traces/review.json"
        write(review, {"review": "fixture"})
        completed = subprocess.run([
            sys.executable, str(ROOT / "scripts/revise_experiment.py"),
            "--run", str(run), "--request-id", "request",
            "--reason", "fixture rejection", "--review-evidence", str(review),
        ], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        assert completed.returncode == 0, (completed.stdout, completed.stderr)
        assert json.loads(completed.stdout)["status"] == expected
        queue = json.loads((run / "models/experiment_queue.json").read_text())
        request = queue["requests"][0]
        assert request["status"] == expected and "supervisor_approval" not in request
        assert json.loads((experiment / "experiment.json").read_text())["status"] == expected


def main() -> None:
    exercise("FAIL", "BLOCKED", "AWAITING_SUPERVISOR_REVIEW")
    exercise("PASS", "RUNNING", "HALT_AND_REPLAN")
    print("supervisor replan-state test: PASS")


if __name__ == "__main__":
    main()
