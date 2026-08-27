#!/usr/bin/env python3
"""Rebind the current request to the scheduler/analyst SCREENING contracts."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


DECISION_ID = "decision-s3-tile-causal-screening-v3"
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
    now = datetime.now(timezone.utc).isoformat()

    decision = json.loads(decision_path.read_text())
    decision["decision_id"] = DECISION_ID
    decision["measurement_need"] = {
        "quantity_id": QUANTITY_ID,
        "model_location": "models/tradeoff_frontier.json::screening C1-C0 two-path mean delta",
        "equation": "q_screen=0.5*(Delta_s404+Delta_s768), Delta_s=median(graph_batched_device_elapsed_C1,s)-median(graph_batched_device_elapsed_C0,s)",
        "current_interval": {"lower": -3.6795, "upper": 9.5355, "unit": "us"},
        "top_two_delta_interval": {"lower": -3.6795, "upper": 9.5355, "unit": "us"},
        "decision_boundary": {"value": 0.25, "unit": "us"},
        "required_precision": {"value": 0.10, "unit": "us"},
        "outcome_mapping": [
            {
                "condition": "all hard gates pass, 95% CI half-width <=0.10 us, and 95% CI upper < +0.25 us",
                "outcome": "ADMIT_TO_NEW_QUALIFICATION_CONTRACT",
            },
            {
                "condition": "95% CI lower > +0.25 us or any hard gate fails",
                "outcome": "REJECT",
            },
            {
                "condition": "95% CI intersects +0.25 us or half-width >0.10 us at the frozen screening budget",
                "outcome": "INCONCLUSIVE",
            },
        ],
        "maximum_decision_value": {"value": 3.6795, "unit": "us"},
        "decision_flip_probability": 0.5,
        "expected_uncertainty_reduction": 1.0,
    }
    decision["stop_rules"] = [
        "Identity, compilation, correctness, final-SASS, resource, stream-containment or P0 failure rejects/invalidates screening and forbids timing.",
        "CI lower above +0.25 us rejects C1 as a material representative-path regression.",
        "A valid non-rejected result only admits a separately issued and supervised QUALIFICATION contract; it never accepts C1.",
        "CI half-width above 0.10 us at 15 pairs/shape is INCONCLUSIVE; no sample or configuration expansion is allowed.",
        "One technical implementation revision requires fresh supervisor review; no automatic retry.",
    ]
    dump(decision_path, decision)

    old_meas = json.loads(meas_path.read_text())
    meas = {
        "schema_version": "measurability-contract-v1",
        "status": "READY_FOR_SUPERVISOR",
        "issued_by": old_meas["issued_by"],
        "decision_contract_identity": identity(decision_path),
        "quantity_id": QUANTITY_ID,
        "identifiability": "PARTIALLY_IDENTIFIABLE",
        "selected_method": "CANDIDATE_AB",
        "observable": {
            "name": "two-path screening mean of paired full-pipeline deltas: 0.5*(Delta_s404+Delta_s768)",
            "unit": "us",
            "measurement_window": (
                "At S404 and S768, randomized interleaved C0/C1 exact four-kernel measurement-only graph blocks; "
                "each block times 64 replays with CUDA events on the same explicit stream. Fifteen paired blocks "
                "per shape in one warm independent process. Compile/static/correctness gates precede timing."
            ),
        },
        "causal_mapping": {
            "formula": (
                "For S in {404,768}, d_S,i=t_C1,S,i-t_C0,S,i from matched randomized AB/BA pair i; "
                "x_screen=0.5*(mean_i d_404,i + mean_i d_768,i). Use a paired two-sided 95% Studentized/bootstrap CI. "
                "CI_low>+0.25us rejects; otherwise a valid CI half-width<=0.10us only admits a new qualification contract."
            ),
            "assumptions": [
                "S404 and S768 exercise the short/tail and long production dispatch families.",
                "C0/C1 inputs, ABI, stream, four-kernel topology and timing semantics differ only in registered S3 scheduling.",
                "One-process systematic error is acceptable only because screening cannot accept C1.",
                "Candidate paired variance remains compatible with the preregistered precision expectation; otherwise screening is INCONCLUSIVE.",
            ],
            "confounders": [
                "Wrong Harrix/FlashInfer import path, stale JIT cache or identical C0/C1 cubin",
                "Unregistered S01/S2/post, launch, input, layout, alignment, stream or graph change",
                "Clock/load/order drift, cold compilation/allocation or CPU enqueue gaps",
                "S404 tail masking or stale upper-score shared values",
                "ptxas register/spill/shared/control changes that invalidate a narrow tile-cost attribution",
            ],
            "controls": [
                "Use distinct C0/C1 ABI/cache keys; archive source/cubin/SASS and prove loaded cubins differ.",
                "Require PYTHONPATH prefix /workspace/dance/qwen35/new/harrix/python:/workspace/dance/qwen35/flashinfer and reject old Harrix/site-packages resolution.",
                "Bitwise stage-boundary/final-BF16 plus deterministic graph/direct correctness at S404 and S768; prove skipped score tiles are never read.",
                "SASS gate proves upper-tile QK and score-times-V work removal, unchanged S01/S2/post, resources, barriers and launch geometry.",
                "Balanced randomized AB/BA, identical seeds/addresses/alignment, same explicit stream/GPU UUID, warm plans, graph_batch=64 and P0 PASS.",
                "CUPTI is collected separately and never mixed into the screening distribution.",
            ],
            "falsification_condition": (
                "Identity/static/bitwise failure rejects or invalidates C1. CI half-width>0.10us at 15 pairs/shape is "
                "SCREENING_INCONCLUSIVE with no budget expansion. No screening outcome may accept C1 or update production."
            ),
        },
        "expected_precision": {"absolute": 0.10, "unit": "us"},
        "required_tier": "SCREENING",
        "evidence": old_meas["evidence"],
    }
    dump(meas_path, meas)

    queue = json.loads(queue_path.read_text())
    request = next(item for item in queue["requests"] if item["request_id"] == REQUEST_ID)
    request["status"] = "PROPOSED"
    request["model_field"] = "tradeoff_frontier screening admission for C1 versus C0"
    request["decision_contract"] = identity(decision_path)
    request["measurability_contract"] = identity(meas_path)
    request["experiment_class"] = "SCREENING"
    request["workload_cases"] = ["s404", "s768"]
    request["sensitivity"].update({
        "candidate_specific_decision_value_us": 3.6795,
        "decision_flip_probability": 0.5,
        "expected_uncertainty_reduction": 1.0,
        "experiment_cost_weight": 1.0,
        "ranking_score": 1.83975,
    })
    request["measurement_contract"].update({
        "screening_cases": ["s404", "s768"],
        "qualification_cases": [],
        "screening_boundary_us": 0.25,
        "screening_outcomes": ["REJECT", "ADMIT_TO_NEW_QUALIFICATION_CONTRACT", "INCONCLUSIVE"],
    })
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
        "reason": "Decision/measurability contracts were revised; rematerialization and fresh hash binding are required.",
    }
    queue["status"] = "EXECUTABLE"
    queue["catalog_snapshot"] = {"status": "REQUERY_REQUIRED_AFTER_CONTRACT_REVISION", "decision": "No atomic probe is eligible."}
    dump(queue_path, queue)

    balance_path = models / "resource_balance.json"
    balance = json.loads(balance_path.read_text())
    for case in balance["cases"]:
        for row in case["resource_rows"]:
            if row["decision_relevance"]["status"] == "TOP_TWO_SENSITIVE":
                row["decision_relevance"]["decision_contract_ids"] = [DECISION_ID]
    dump(balance_path, balance)

    plan_path = models / "optimization_plan.json"
    plan = json.loads(plan_path.read_text())
    plan["open_uncertainties"] = [{"quantity_id": QUANTITY_ID, "decision_contract": identity(decision_path)}]
    plan["acceptance_rule"] = "SCREENING may only reject, admit to a new supervised QUALIFICATION contract, or remain inconclusive; it cannot accept C1."
    plan["revision_history"].append({"revision": 2, "at": now, "reason": "Split two-path SCREENING admission from the later seven-shape QUALIFICATION decision."})
    dump(plan_path, plan)

    state_path = models / "global_schedule_state.json"
    state = json.loads(state_path.read_text())
    state["revision_history"].append({"revision": 2, "at": now, "reason": "Scheduler issued bounded two-path SCREENING contract; no production acceptance authority."})
    dump(state_path, state)

    receipt = {
        "schema_version": "screening-contract-revision-receipt-v1",
        "status": "PASS",
        "created_at": now,
        "decision_contract": identity(decision_path),
        "measurability_contract": identity(meas_path),
        "experiment_queue": identity(queue_path),
        "rule": "No SCREENING outcome accepts or deploys C1.",
    }
    dump(run / "traces" / "screening_contract_revision_v3.json", receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
