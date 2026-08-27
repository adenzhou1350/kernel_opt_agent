#!/usr/bin/env python3
"""Apply a restricted field-level result-to-model plan and emit a semantic receipt."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from evidence_utils import read_object, sha256
from model_patch_utils import evaluate_calculation, pointer_get, pointer_set
from schema_utils import validate_json_file


MODEL_PATHS = {
    "resource_balance": "models/resource_balance.json",
    "schedule_model": "models/schedule_model.json",
    "tradeoff_frontier": "models/tradeoff_frontier.json",
}


def atomic_json(path: Path, data: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--request-id", required=True)
    parser.add_argument("--plan", type=Path, required=True)
    args = parser.parse_args()
    run = args.run.resolve()
    schema = Path(__file__).resolve().parents[1] / "schemas/model_update_plan.schema.json"
    schema_errors = validate_json_file(args.plan, schema)
    if schema_errors:
        raise ValueError("invalid model update plan schema: " + "; ".join(schema_errors))
    plan = read_object(args.plan)
    if plan.get("schema_version") != "model-update-plan-v1" or plan.get("request_id") != args.request_id:
        raise ValueError("invalid model update plan identity")
    queue = read_object(run / "models/experiment_queue.json")
    request = next((item for item in queue.get("requests", []) if item.get("request_id") == args.request_id), None)
    if request is None or request.get("status") != "RESOLVED":
        raise ValueError("model updates require a bound RESOLVED result")
    result_ref = request.get("result_binding", {}).get("evidence", [None])[0]
    result_path = Path(result_ref.get("path", ""))
    if not result_path.is_absolute():
        result_path = run / result_path
    if result_ref.get("sha256") != sha256(result_path):
        raise ValueError("bound result identity changed")
    if plan.get("result_identity", {}).get("sha256") != sha256(result_path):
        raise ValueError("model update plan is not bound to the queued result")
    result = read_object(result_path)
    updates = plan.get("updates", [])
    touched = {str(item.get("artifact")) for item in updates}
    if touched != set(MODEL_PATHS):
        raise ValueError(f"model update plan must causally update exactly {sorted(MODEL_PATHS)}")
    models = {name: read_object(run / relative) for name, relative in MODEL_PATHS.items()}
    before_identities = {name: {"path": relative, "sha256": sha256(run / relative)} for name, relative in MODEL_PATHS.items()}
    applied = []
    for index, update in enumerate(updates):
        artifact = str(update.get("artifact"))
        pointer = str(update.get("target_pointer", ""))
        before = pointer_get(models[artifact], pointer)
        if before != update.get("before"):
            raise ValueError(f"model update {index} before-value mismatch")
        after = evaluate_calculation(update.get("calculation", {}), result)
        if after == before:
            raise ValueError(f"model update {index} is a no-op")
        if update.get("after") != after:
            raise ValueError(f"model update {index} after-value is not produced by the declared calculation")
        for field in ("units", "uncertainty", "reason"):
            if not update.get(field):
                raise ValueError(f"model update {index} requires {field}")
        pointer_set(models[artifact], pointer, after)
        applied.append({**update, "verified_result_value": pointer_get(result, update["calculation"]["result_pointer"])})
    for name, data in models.items():
        atomic_json(run / MODEL_PATHS[name], data)
    after_identities = {name: {"path": relative, "sha256": sha256(run / relative)} for name, relative in MODEL_PATHS.items()}
    receipt = {
        "schema_version": "semantic-model-update-receipt-v1",
        "status": "APPLIED",
        "request_id": args.request_id,
        "applied_at": datetime.now(timezone.utc).isoformat(),
        "plan_identity": {"path": str(args.plan.resolve()), "sha256": sha256(args.plan)},
        "result_identity": {"path": str(result_path), "sha256": sha256(result_path)},
        "before_model_identities": before_identities,
        "after_model_identities": after_identities,
        "updates": applied,
    }
    output = run / "experiments" / args.request_id / "semantic_model_update_receipt.json"
    atomic_json(output, receipt)
    print(json.dumps({"status": "APPLIED", "receipt": str(output), "updates": len(applied)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
