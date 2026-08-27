#!/usr/bin/env python3
"""Bind a validated immutable result and create a global-model reconciliation request."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from evidence_utils import read_object, sha256
from experiment_utils import validate_benchmark_result, validate_execution_receipt


def atomic_json(path: Path, data: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--request-id", required=True)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()
    run = args.run.resolve()
    result_path = args.result.resolve()
    queue_path = run / "models/experiment_queue.json"
    queue = read_object(queue_path)
    request = next((item for item in queue.get("requests", []) if item.get("request_id") == args.request_id), None)
    if request is None or request.get("status") != "RUNNING":
        raise ValueError("result can bind only after a PASS execution receipt leaves the request RUNNING")
    experiment_ref = request.get("materialized_experiment", {})
    experiment_path = Path(experiment_ref.get("path", ""))
    if not experiment_path.is_absolute():
        experiment_path = run / experiment_path
    if experiment_ref.get("sha256") != sha256(experiment_path):
        raise ValueError("materialized experiment identity changed after dispatch")
    execution_ref = request.get("execution_receipt", {})
    execution_path = Path(execution_ref.get("path", ""))
    if not execution_path.is_absolute():
        execution_path = run / execution_path
    errors = []
    if execution_ref.get("sha256") != sha256(execution_path):
        errors.append("execution receipt identity mismatch")
    errors.extend(validate_execution_receipt(execution_path, run, experiment_path, args.request_id))
    errors.extend(validate_benchmark_result(result_path, run, request_id=args.request_id, experiment_path=experiment_path))
    experiment = read_object(experiment_path)
    expected_result = Path(experiment.get("artifacts", {}).get("result", ""))
    if not expected_result.is_absolute():
        expected_result = run / expected_result
    if expected_result.resolve() != result_path:
        errors.append("benchmark result path does not match the materialized artifact contract")
    if errors:
        print(json.dumps({"status": "FAIL", "errors": errors}, indent=2, sort_keys=True))
        return 1
    result = read_object(result_path)
    identity = {"path": str(result_path), "sha256": sha256(result_path)}
    model_paths = {
        "resource_balance": run / "models/resource_balance.json",
        "schedule_model": run / "models/schedule_model.json",
        "tradeoff_frontier": run / "models/tradeoff_frontier.json",
        "experiment_queue": queue_path,
    }
    pre_model_identities = {
        name: {"path": str(path), "sha256": sha256(path)}
        for name, path in model_paths.items()
    }
    reconciliation_path = run / "experiments" / args.request_id / "model_reconciliation.json"
    reconciliation = {
        "schema_version": "model-reconciliation-v1",
        "status": "PENDING_GLOBAL_SCHEDULER",
        "request_id": args.request_id,
        "issued_at": datetime.now(timezone.utc).isoformat(),
        "model_field": request["model_field"],
        "candidate_decision": request["candidate_decision"],
        "result_identity": identity,
        "experiment_identity": {"path": str(experiment_path), "sha256": sha256(experiment_path)},
        "execution_identity": {"path": str(execution_path), "sha256": sha256(execution_path)},
        "result_summary": result.get("summary", {}),
        "required_updates": ["resource_balance", "schedule_model", "tradeoff_frontier", "experiment_queue"],
        "pre_model_identities": pre_model_identities,
        "automatic_numeric_patch_forbidden": True,
        "reason": "arbitrary benchmark summaries must be interpreted against the declared boundary and production DAG by the global scheduler",
    }
    atomic_json(reconciliation_path, reconciliation)
    request["status"] = "RESOLVED"
    request["result_binding"] = {
        "status": "BOUND",
        "evidence": [identity],
        "model_reconciliation": {"path": str(reconciliation_path), "sha256": sha256(reconciliation_path), "status": "PENDING_GLOBAL_SCHEDULER"},
    }
    atomic_json(queue_path, queue)
    print(json.dumps({"status": "BOUND", "request_id": args.request_id, "reconciliation": str(reconciliation_path)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
