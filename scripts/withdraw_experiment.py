#!/usr/bin/env python3
"""Withdraw before execution and require fresh independent supervisor review."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path: Path, data: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--request-id", required=True)
    parser.add_argument("--reason", required=True)
    args = parser.parse_args()
    run = args.run.resolve()
    queue_path = run / "models/experiment_queue.json"
    queue = json.loads(queue_path.read_text())
    request = next((item for item in queue.get("requests", []) if item.get("request_id") == args.request_id), None)
    if request is None or request.get("status") != "DISPATCHED":
        raise ValueError("only a DISPATCHED request can be withdrawn before execution")
    experiment_path = run / "experiments" / args.request_id / "experiment.json"
    receipt_path = experiment_path.parent / "execution_receipt.json"
    if receipt_path.exists() or request.get("execution_receipt"):
        raise ValueError("executed requests must use revise_experiment.py and preserve an attempt archive")
    previous = request.get("materialized_experiment", {})
    if previous.get("sha256") != sha(experiment_path):
        # Source-identity invalidation does not change experiment.json itself;
        # the dispatched contract hash must still match before withdrawal.
        raise ValueError("dispatched experiment JSON identity changed")
    request.setdefault("dispatch_history", []).append({
        "status": "WITHDRAWN_BEFORE_EXECUTION",
        "reason": args.reason,
        "withdrawn_at": datetime.now(timezone.utc).isoformat(),
        "materialized_experiment": previous,
    })
    request["status"] = "AWAITING_SUPERVISOR_REVIEW"
    request.pop("supervisor_approval", None)
    experiment = json.loads(experiment_path.read_text())
    experiment["status"] = "AWAITING_SUPERVISOR_REVIEW"
    experiment.setdefault("revision_history", []).append({
        "status": "WITHDRAWN_BEFORE_EXECUTION", "reason": args.reason,
    })
    atomic_json(experiment_path, experiment)
    request["materialized_experiment"] = {
        "path": str(experiment_path), "sha256": sha(experiment_path), "status": "AWAITING_SUPERVISOR_REVIEW",
    }
    atomic_json(queue_path, queue)
    print(json.dumps({"status": "AWAITING_SUPERVISOR_REVIEW", "request_id": args.request_id}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
