#!/usr/bin/env python3
"""Close the current SCREENING run after the scheduler's hard-gate rejection."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


REQUEST_ID = "req-s3-tile-causal-production-ab"
REASON = "C1_COMPILE_LAYOUT_HARD_GATE_FAIL_REVISION_BUDGET_EXHAUSTED"
RECEIPT_SHA = "14e337173a919c223daede3e8871d970fc5a6d35630cfdb059cc941df156bcca"
STDERR_SHA = "bf19afd98d49dbb167a1ff3935e7be6e3cb6a1621ceda68405b3cc011147f887"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def identity(path: Path, run: Path) -> dict:
    return {"path": str(path.relative_to(run)), "sha256": sha256(path)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    run = args.run.resolve()
    queue_path = run / "models/experiment_queue.json"
    state_path = run / "models/global_schedule_state.json"
    experiment_dir = run / f"experiments/{REQUEST_ID}"
    execution_path = experiment_dir / "execution_receipt.json"
    stderr_path = experiment_dir / "execution_logs/clean_build-0.stderr.txt"
    if sha256(execution_path) != RECEIPT_SHA or sha256(stderr_path) != STDERR_SHA:
        raise RuntimeError("attempt-2 rejection evidence identity changed")
    execution = json.loads(execution_path.read_text())
    if execution.get("status") != "FAIL" or execution.get("failure") != "clean_build[0] exited 1":
        raise RuntimeError("attempt-2 is not the registered clean-build hard-gate failure")

    queue = json.loads(queue_path.read_text())
    request = next(item for item in queue["requests"] if item["request_id"] == REQUEST_ID)
    if request.get("status") != "BLOCKED":
        raise RuntimeError("closure requires the framework BLOCKED state")
    if len(request.get("attempt_history", [])) != 1:
        raise RuntimeError("the sole technical revision was not consumed exactly once")
    evidence = [
        identity(execution_path, run),
        identity(stderr_path, run),
    ]
    now = datetime.now(timezone.utc).isoformat()
    request["status"] = "REJECTED"
    request["rejection_reason"] = REASON
    request["rejected_at"] = now
    request["result_binding"] = {
        "status": "REJECTED_HARD_GATE",
        "decision": "REJECT",
        "candidate_id": "C1",
        "baseline_candidate_id": "C0",
        "reason": REASON,
        "evidence": evidence,
        "performance_samples_emitted": 0,
        "promotion": "NOT_APPLICABLE",
        "production_update": False,
    }
    queue["status"] = "CLOSED"
    dump(queue_path, queue)

    state = json.loads(state_path.read_text())
    if state.get("human_report_gate", {}).get("status") != "BLOCKED":
        raise RuntimeError("human report gate must remain BLOCKED")
    state["status"] = "BLOCKED"
    state["halt_disposition"] = {
        "status": "HALT_AND_REPLAN",
        "reason": REASON,
        "rejected_candidate_id": "C1",
        "retained_production_baseline_id": "C0",
        "evidence": evidence,
        "production_validation_authorized": False,
    }
    dump(state_path, state)

    closure = {
        "schema_version": "hard-gate-rejection-closure-v1",
        "status": "HALT_AND_REPLAN",
        "created_at": now,
        "authorized_by": {
            "role": "GLOBAL_SCHEDULER",
            "owner_id": "global-scheduler-linear-v2",
        },
        "request_id": REQUEST_ID,
        "decision": "REJECT",
        "reason": REASON,
        "evidence": evidence,
        "performance_samples_emitted": 0,
        "retained_baseline": "C0",
        "new_global_accept_recorded": False,
        "queue": identity(queue_path, run),
        "global_schedule_state": identity(state_path, run),
        "next_candidate_ids": ["N0", "N1", "N2"],
    }
    dump(run / "traces/c1_hard_gate_rejection_closure.json", closure)
    print(json.dumps(closure, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
