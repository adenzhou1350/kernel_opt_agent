#!/usr/bin/env python3
"""Normalize one pre-materialization request cost to the framework enum."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    run = args.run.resolve()
    queue_path = run / "models/experiment_queue.json"
    queue = json.loads(queue_path.read_text())
    old_sha = sha256(queue_path)
    requests = [item for item in queue["requests"] if item.get("request_id") == "req-n2-static-layout-admissibility"]
    if len(requests) != 1:
        raise ValueError("expected exactly one static layout request")
    request = requests[0]
    if request.get("status") != "PROPOSED":
        raise ValueError("cost normalization is allowed only before materialization")
    old_cost = request["sensitivity"].get("experiment_cost")
    if old_cost not in {"LOW_STATIC_ONLY", "LOW"}:
        raise ValueError(f"unexpected cost value: {old_cost}")
    request["sensitivity"]["experiment_cost"] = "LOW"
    request["sensitivity"]["experiment_cost_weight"] = 1.0
    queue_path.write_text(json.dumps(queue, indent=2, sort_keys=True) + "\n")
    receipt = {
        "schema_version": "pre-materialization-technical-correction-v1",
        "status": "PASS",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "request_id": request["request_id"],
        "changed_field": "sensitivity.experiment_cost",
        "old_value": old_cost,
        "new_value": "LOW",
        "reason": "rank_experiments accepts only LOW/MEDIUM/HIGH; decision semantics, candidates, budget and observable are unchanged",
        "old_queue_sha256": old_sha,
        "new_queue_sha256": sha256(queue_path),
        "gpu_launches": 0,
        "performance_samples": 0,
    }
    output = run / "traces/static_request_cost_correction.json"
    output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": "PASS", "receipt": str(output), "queue_sha256": sha256(queue_path)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
