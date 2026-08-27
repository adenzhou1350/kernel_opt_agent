#!/usr/bin/env python3
"""Apply the scheduler-authorized final SCREENING-v5 summary repairs."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


REQUEST_ID = "req-s3-tile-causal-production-ab"
EXPECTED_CATALOG_SHA = "1896916544d97600f7c482074feebc52ec9a94ad001981ace053867711607e0e"
EXPECTED_RECEIPT_SHA = "cd98edceff99e8f8f06b0d546edd2245cc6f6561e7eae9da5684a2bf6d143e28"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def identity(path: Path) -> dict:
    return {"path": str(path.resolve()), "sha256": sha256(path)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--project", type=Path, required=True)
    args = parser.parse_args()
    run = args.run.resolve()
    project = args.project.resolve()
    plan_path = run / "models/microbenchmark_plan.json"
    queue_path = run / "models/experiment_queue.json"
    receipt_path = run / f"experiments/{REQUEST_ID}/catalog_query_receipt.json"
    catalog_path = project / "microbench/catalog.json"
    if sha256(catalog_path) != EXPECTED_CATALOG_SHA:
        raise RuntimeError("catalog identity changed after scheduler audit")
    if sha256(receipt_path) != EXPECTED_RECEIPT_SHA:
        raise RuntimeError("catalog receipt identity changed after scheduler audit")

    before = {
        "microbenchmark_plan": identity(plan_path),
        "experiment_queue": identity(queue_path),
    }
    plan = json.loads(plan_path.read_text())
    removed = [
        item
        for item in plan["cross_layer_prediction_gates"]
        if "graph/direct" in str(item.get("gate", "")).lower()
    ]
    if len(removed) != 1 or removed[0].get("status") != "PENDING":
        raise RuntimeError(f"expected exactly one stale active graph/direct PENDING gate: {removed}")
    plan["cross_layer_prediction_gates"] = [
        item
        for item in plan["cross_layer_prediction_gates"]
        if "graph/direct" not in str(item.get("gate", "")).lower()
    ]
    if not any(
        item.get("quantity_id") == "graph_to_direct_ranking_transfer"
        and item.get("status") == "NOT_AUTHORIZED_BY_SCREENING_V5"
        for item in plan.get("deferred_qualification_questions", [])
    ):
        raise RuntimeError("deferred qualification transfer question is missing")
    dump(plan_path, plan)

    queue = json.loads(queue_path.read_text())
    request = next(item for item in queue["requests"] if item["request_id"] == REQUEST_ID)
    request_receipt = request.get("catalog_resolution", {}).get("receipt", {})
    if request_receipt.get("sha256") != EXPECTED_RECEIPT_SHA:
        raise RuntimeError("request does not bind the current catalog receipt")
    queue["catalog_snapshot"] = {
        "status": "CURRENT",
        "catalog_identity": {
            "path": str(catalog_path),
            "sha256": EXPECTED_CATALOG_SHA,
        },
        "request_receipts": [
            {
                "request_id": REQUEST_ID,
                "path": f"experiments/{REQUEST_ID}/catalog_query_receipt.json",
                "sha256": EXPECTED_RECEIPT_SHA,
                "decision": "CREATE_RUN_LOCAL",
            }
        ],
    }
    dump(queue_path, queue)

    result = {
        "schema_version": "model-ready-summary-repair-receipt-v1",
        "status": "PASS",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "authorized_by": {
            "role": "GLOBAL_SCHEDULER",
            "owner_id": "global-scheduler-linear-v2",
        },
        "before": before,
        "after": {
            "microbenchmark_plan": identity(plan_path),
            "experiment_queue": identity(queue_path),
        },
        "removed_active_gate": removed[0],
        "catalog_receipt": identity(receipt_path),
        "gpu_or_dispatch_authorized": False,
    }
    dump(run / "traces/model_ready_summary_repair_v5.json", result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
