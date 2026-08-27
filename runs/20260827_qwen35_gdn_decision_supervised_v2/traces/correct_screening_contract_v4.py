#!/usr/bin/env python3
"""Apply the scheduler-authorized v4 SCREENING contract repair."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


DECISION_ID = "decision-s3-tile-causal-screening-v4"
QUANTITY_ID = "screening_two_path_mean_delta_c1_minus_c0"
REQUEST_ID = "req-s3-tile-causal-production-ab"


def dump(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def identity(path: Path) -> dict:
    return {"path": str(path.resolve()), "sha256": sha256(path)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True)
    args = parser.parse_args()
    run = Path(args.run).resolve()
    models = run / "models"
    decision_path = models / "decision_contract.json"
    meas_path = models / "measurability_contract.json"
    queue_path = models / "experiment_queue.json"
    plan_path = models / "optimization_plan.json"
    state_path = models / "global_schedule_state.json"
    now = datetime.now(timezone.utc).isoformat()

    decision = json.loads(decision_path.read_text())
    decision["decision_id"] = DECISION_ID
    decision["experiment_budget"]["screening"]["max_process_launches"] = 6
    dump(decision_path, decision)

    plan = json.loads(plan_path.read_text())
    plan["screening_budget"]["max_process_launches"] = 6
    plan["open_uncertainties"] = [
        {"quantity_id": QUANTITY_ID, "decision_contract": identity(decision_path)}
    ]
    plan["revision_history"].append(
        {
            "revision": 3,
            "at": now,
            "reason": (
                "Repair SCREENING process budget to the framework-defined six mandatory phase argv; "
                "only measure[0] may emit decision samples."
            ),
        }
    )
    dump(plan_path, plan)

    meas = json.loads(meas_path.read_text())
    meas["decision_contract_identity"] = identity(decision_path)
    meas["observable"]["measurement_window"] = (
        "At S404 and S768, randomized interleaved C0/C1 exact four-kernel measurement-only graph blocks; "
        "each block times 64 replays with CUDA events on the same explicit stream. The single measure[0] "
        "process performs its own in-process warmup and emits fifteen paired blocks per shape. The five "
        "other mandatory lifecycle phase processes emit no decision samples."
    )
    meas["causal_mapping"]["assumptions"] = [
        item.replace(
            "One-process systematic error is acceptable only because screening cannot accept C1.",
            "One statistical measurement process is acceptable only because screening cannot accept C1; lifecycle gate processes emit no decision samples.",
        )
        for item in meas["causal_mapping"]["assumptions"]
    ]
    dump(meas_path, meas)

    queue = json.loads(queue_path.read_text())
    request = next(item for item in queue["requests"] if item["request_id"] == REQUEST_ID)
    request["status"] = "PROPOSED"
    request["decision_contract"] = identity(decision_path)
    request["measurability_contract"] = identity(meas_path)
    request["experiment_class"] = "SCREENING"
    request["workload_cases"] = ["s404", "s768"]
    request["execution_budget"] = {
        "configurations": 4,
        "samples_per_configuration": 15,
        "process_launches": 6,
        "max_wall_clock_minutes": 20,
    }
    request["parameter_matrix"] = [
        {"candidate_id": candidate, "workload_case": shape, "paired_blocks": 15}
        for shape in ("s404", "s768")
        for candidate in ("C0", "C1")
    ]
    request["sensitivity"].update(
        {
            "candidate_specific_decision_value_us": 3.6795,
            "decision_flip_probability": 0.5,
            "expected_uncertainty_reduction": 1.0,
            "experiment_cost_weight": 1.0,
            "ranking_score": 1.83975,
            "benefit_derivation": {
                "decision_contract_identity": identity(decision_path),
                "quantity_id": QUANTITY_ID,
                "decision_boundary": {"value": 0.25, "unit": "us"},
                "maximum_decision_value": {"value": 3.6795, "unit": "us"},
                "method": "screening two-path mean-delta decision sensitivity from the frozen screening decision contract",
                "top_two_candidate_ids": ["C1", "C0"],
            },
        }
    )
    measurement = request["measurement_contract"]
    measurement["direct_transfer_gate"] = False
    measurement["primary"] = (
        "Only measure[0] contributes samples: same explicit stream; CUDA events bracket 64 warmed exact "
        "four-kernel graph replays per randomized interleaved AB/BA block. CUPTI and uncaptured-direct are "
        "preflight/diagnostic only and never enter the screening distribution."
    )
    request["controls"] = [
        item
        for item in request["controls"]
        if "graph/direct deltas" not in item and "delta_graph-delta_direct" not in item
    ]
    request["controls"].append(
        "Uncaptured-direct is allowed only for bitwise semantic correctness or a labeled non-decision diagnostic; it emits no latency distribution."
    )
    request.pop("materialized_experiment", None)
    request.pop("supervisor_approval", None)
    request["catalog_resolution"] = {
        "catalog_queried": False,
        "query": {
            "resources": request["resource_ids"],
            "mechanisms": ["production_candidate_ab", "causal_16x16_tile_schedule"],
            "boundaries": ["BF16_score", "BF16_raw_o", "four_kernel_device_elapsed"],
            "qualification": "APPLICATION_SHAPED_SCREENING",
        },
        "decision": None,
        "package_id": None,
        "reason": "v4 contract repair requires deterministic rematerialization and fresh hash binding.",
    }
    queue["status"] = "EXECUTABLE"
    queue["catalog_snapshot"] = {
        "status": "REQUERY_REQUIRED_AFTER_CONTRACT_REVISION",
        "decision": "No atomic probe is eligible.",
    }
    dump(queue_path, queue)

    balance_path = models / "resource_balance.json"
    balance = json.loads(balance_path.read_text())
    for case in balance["cases"]:
        for row in case["resource_rows"]:
            if row["decision_relevance"]["status"] == "TOP_TWO_SENSITIVE":
                row["decision_relevance"]["decision_contract_ids"] = [DECISION_ID]
    dump(balance_path, balance)

    state = json.loads(state_path.read_text())
    state["revision_history"].append(
        {
            "revision": 3,
            "at": now,
            "reason": (
                "Scheduler authorized six mandatory lifecycle argv for SCREENING; no GPU, dispatch, "
                "qualification, or production acceptance authority was granted."
            ),
        }
    )
    dump(state_path, state)

    receipt = {
        "schema_version": "screening-contract-repair-receipt-v1",
        "status": "PASS",
        "created_at": now,
        "authorized_by": {
            "role": "GLOBAL_SCHEDULER",
            "owner_id": "global-scheduler-linear-v2",
        },
        "decision_id": DECISION_ID,
        "decision_contract": identity(decision_path),
        "measurability_contract": identity(meas_path),
        "optimization_plan": identity(plan_path),
        "experiment_queue": identity(queue_path),
        "invariants": {
            "mandatory_phase_argv": 6,
            "decision_sample_processes": 1,
            "screening_direct_transfer_gate": False,
            "gpu_or_dispatch_authorized": False,
        },
    }
    receipt_path = run / "traces" / "screening_contract_repair_v4.json"
    dump(receipt_path, receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
