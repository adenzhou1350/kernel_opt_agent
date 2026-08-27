#!/usr/bin/env python3
"""Apply a conservative P1-only shared-service update to the global model."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def identity(path: Path) -> dict:
    return {"path": str(path.resolve()), "sha256": sha(path)}


def read(path: Path):
    return json.loads(path.read_text())


def write(path: Path, data) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def add_identity(records: list, record: dict) -> list:
    return list({item["path"]: item for item in records + [record]}.values())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    run = args.run.resolve()
    models = run / "models"
    root = run / "experiments/req-shared-request-service"
    result_path = root / "p1_service_curve.json"
    permission_path = root / "ncu_permission_receipt.json"
    result, permission = read(result_path), read(permission_path)
    if result.get("status") != "PASS" or result.get("qualification") != "MECHANISM_VALIDATED":
        raise RuntimeError("P1 service curve is not mechanism-validated PASS")
    for field in ("raw_identity", "static_audit_identity", "execution_receipt_identity"):
        record = result[field]
        if sha(Path(record["path"])) != record["sha256"]:
            raise RuntimeError(f"stale P1 identity: {field}")
    if permission.get("status") != "BLOCKED_PERMISSION":
        raise RuntimeError("P2 counter state must be explicitly captured")
    result_identity, permission_identity = identity(result_path), identity(permission_path)
    model_paths = {
        "resource_balance": models / "resource_balance.json",
        "schedule_model": models / "schedule_model.json",
        "tradeoff_frontier": models / "tradeoff_frontier.json",
    }
    before = {name: identity(path) for name, path in model_paths.items()}

    architecture_path = models / "microarchitecture_model.json"
    architecture = read(architecture_path)
    curve_id = "qwen35-shared-constant-request-p1-attempt06"
    architecture["service_curves"] = [item for item in architecture.get("service_curves", []) if item.get("curve_id") != curve_id]
    architecture["service_curves"].append({
        "curve_id": curve_id,
        "status": "MECHANISM_VALIDATED",
        "qualification_scope": "run-local probe only",
        "resource_ids": ["constant_memory_path", "l1_shared_boundary", "shared_bank_service", "shared_memory"],
        "independent_variables": ["production launch geometry", "shared stride", "constant address divergence", "repeat count"],
        "measured_range": {"repeat_count": [64, 128, 256], "shared_stride": [1, 2, 4, 8, 16, 32]},
        "summary": result["summary"],
        "evidence": [result_identity],
        "production_mapping_status": "UNKNOWN_PENDING_P2_COUNTERS_AND_PRODUCTION_LAYOUT_MAPPING",
        "claims_forbidden": result["claims_forbidden"],
    })
    architecture["evidence"] = add_identity(architecture.get("evidence", []), result_identity)
    architecture["evidence"] = add_identity(architecture["evidence"], permission_identity)
    architecture["unknowns"].append({
        "request_id": "req-shared-request-service",
        "resource_id": "shared_bank_service",
        "unknown": "production bank/request counts and service utilization remain unmeasured because NCU counters are permission-blocked",
        "blocking_evidence": permission_identity,
    })
    write(architecture_path, architecture)

    schedule = read(model_paths["schedule_model"])
    for coupling in schedule.get("coupled_resource_models", []):
        if coupling.get("request_id") == "req-shared-request-service":
            coupling.update({
                "status": "P1_MECHANISM_VALIDATED_P2_PERMISSION_BLOCKED",
                "p1_evidence": result_identity,
                "p2_blocking_evidence": permission_identity,
                "production_prediction_status": "UNKNOWN",
            })
    schedule["evidence"] = add_identity(schedule.get("evidence", []), result_identity)
    schedule["evidence"] = add_identity(schedule["evidence"], permission_identity)
    write(model_paths["schedule_model"], schedule)

    balance = read(model_paths["resource_balance"])
    affected = {"constant_memory_path", "l1_shared_boundary", "shared_bank_service", "shared_memory"}
    for case in balance["cases"]:
        for row in case["resource_rows"]:
            if row["resource_id"] in affected:
                row["evidence"] = add_identity(row.get("evidence", []), result_identity)
                row["evidence"] = add_identity(row["evidence"], permission_identity)
                row["production_point"]["status"] = "UNKNOWN"
                row["production_point"]["reason"] = "P1 probe slope exists, but production dynamic bank/request mapping and P2 counter coupling are not closed"
                row["critical_path"]["coupling_model"] = "P1 mechanism curve measured; production mapping P2 blocked by NCU permission"
                row["non_saturation_causes"] = ["NOT_ESTABLISHED"]
    balance["evidence"] = add_identity(balance.get("evidence", []), result_identity)
    balance["evidence"] = add_identity(balance["evidence"], permission_identity)
    write(model_paths["resource_balance"], balance)

    frontier = read(model_paths["tradeoff_frontier"])
    for case in frontier["cases"]:
        case["current_schedule"]["shared_request_mechanism"] = {
            "status": "P1_MECHANISM_VALIDATED_PRODUCTION_MAPPING_UNKNOWN",
            "evidence": result_identity,
            "P2_blocking_evidence": permission_identity,
        }
    frontier["evidence"] = add_identity(frontier.get("evidence", []), result_identity)
    frontier["evidence"] = add_identity(frontier["evidence"], permission_identity)
    write(model_paths["tradeoff_frontier"], frontier)

    microbench_path = models / "microbenchmark_plan.json"
    microbench = read(microbench_path)
    microbench["levels"]["P1"]["status"] = "PARTIAL"
    microbench["levels"]["P1"]["evidence"] = add_identity(microbench["levels"]["P1"].get("evidence", []), result_identity)
    microbench["levels"]["P2"]["blocking_evidence"] = add_identity(microbench["levels"]["P2"].get("blocking_evidence", []), permission_identity)
    microbench["levels"]["P2"]["status"] = "PENDING_PERMISSION_AND_OTHER_RESOURCES"
    write(microbench_path, microbench)

    global_path = models / "global_schedule_state.json"
    global_state = read(global_path)
    global_state["revision_history"].append({
        "revision": max(item["revision"] for item in global_state["revision_history"]) + 1,
        "reason": "Shared/constant P1 mechanism service curves passed all validity gates. No production utilization or critical-path closure was inferred; P2 counter mapping is explicitly permission-blocked.",
    })
    write(global_path, global_state)

    after = {name: identity(path) for name, path in model_paths.items()}
    receipt = {
        "schema_version": "semantic-model-update-receipt-v1",
        "status": "APPLIED",
        "request_id": "req-shared-request-service",
        "applied_at": datetime.now(timezone.utc).isoformat(),
        "plan_identity": identity(microbench_path),
        "result_identity": result_identity,
        "before_model_identities": before,
        "after_model_identities": after,
        "updates": [
            {"artifact": "resource_balance", "semantic": "evidence attached; numeric utilization and critical contribution remain UNKNOWN"},
            {"artifact": "schedule_model", "semantic": "P1 mechanism curve registered; production mapping remains UNKNOWN"},
            {"artifact": "tradeoff_frontier", "semantic": "current schedule annotated with P1 evidence and P2 blocker; no candidate decision"},
            {"artifact": "microarchitecture_model", "semantic": "run-local service slopes registered at MECHANISM_VALIDATED qualification"},
        ],
    }
    receipt_path = root / "p1_semantic_model_update_receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": "APPLIED_P1_ONLY", "receipt": str(receipt_path), "production_utilization": "UNKNOWN", "P2": "BLOCKED_PERMISSION"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
