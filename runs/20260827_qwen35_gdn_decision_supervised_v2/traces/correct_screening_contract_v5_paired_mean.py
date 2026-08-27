#!/usr/bin/env python3
"""Archive v4 and issue the scheduler-authorized paired-mean v5 contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


DECISION_ID = "decision-s3-tile-causal-screening-v5-paired-mean"
QUANTITY_ID = "screening_two_path_mean_delta_c1_minus_c0"
REQUEST_ID = "req-s3-tile-causal-production-ab"
EQUATION = (
    "For s in {404,768}, d_s,i=event_elapsed_us(C1,s,i)/64-event_elapsed_us(C0,s,i)/64 "
    "for matched randomized-order pair i; q_screen=0.5*(E_i[d_404,i]+E_i[d_768,i]); "
    "estimate q_hat=0.5*(mean_i d_404,i+mean_i d_768,i)."
)
CI_FORMULA = (
    "For each s, v_s is the unbiased sample variance of 15 paired d_s,i. "
    "SE(q_hat)=0.5*sqrt(v_404/15+v_768/15); "
    "nu=(v_404/15+v_768/15)^2/((v_404/15)^2/14+(v_768/15)^2/14); "
    "CI95=q_hat +/- t_(0.975,nu)*SE(q_hat)."
)


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
    paths = {
        "decision_contract": models / "decision_contract.json",
        "measurability_contract": models / "measurability_contract.json",
        "experiment_queue": models / "experiment_queue.json",
        "optimization_plan": models / "optimization_plan.json",
        "global_schedule_state": models / "global_schedule_state.json",
    }
    now = datetime.now(timezone.utc).isoformat()

    archive = run / "traces/contract_archive/v4"
    archive.mkdir(parents=True, exist_ok=False)
    archived = {}
    for name, source in paths.items():
        destination = archive / source.name
        shutil.copy2(source, destination)
        archived[name] = identity(destination)
    archive_manifest = {
        "schema_version": "contract-archive-receipt-v1",
        "status": "PASS",
        "archived_at": now,
        "decision_id": "decision-s3-tile-causal-screening-v4",
        "artifacts": archived,
        "reason": "v4 mixed a median equation with a paired-mean Studentized precision model.",
    }
    dump(archive / "manifest.json", archive_manifest)

    decision_path = paths["decision_contract"]
    decision = json.loads(decision_path.read_text())
    if decision.get("decision_id") != "decision-s3-tile-causal-screening-v4":
        raise RuntimeError("expected archived v4 decision before issuing v5")
    decision["decision_id"] = DECISION_ID
    need = decision["measurement_need"]
    need["equation"] = EQUATION
    need["outcome_mapping"] = [
        {
            "condition": "any identity, compilation, correctness, SASS, resource, stream-containment or P0 hard gate fails",
            "outcome": "REJECT; timing cannot rescue the candidate",
        },
        {
            "condition": "all hard gates pass and CI lower L > +0.25 us",
            "outcome": "REJECT",
        },
        {
            "condition": "all hard gates pass, CI half-width <=0.10 us, and CI upper U < +0.25 us",
            "outcome": "ADMIT_TO_NEW_QUALIFICATION_CONTRACT",
        },
        {
            "condition": "otherwise, including L <=0.25<=U, equality at either boundary, or CI half-width >0.10 us",
            "outcome": "INCONCLUSIVE",
        },
    ]
    decision["stop_rules"] = [
        "Any identity, compilation, correctness, final-SASS, resource, stream-containment or P0 hard-gate failure rejects C1 and forbids timing from rescuing it.",
        "After hard gates pass, CI lower L > +0.25 us rejects C1 even if the CI half-width exceeds 0.10 us.",
        "After hard gates pass, CI half-width <=0.10 us and CI upper U < +0.25 us only admits a new supervised QUALIFICATION contract; SCREENING never accepts C1.",
        "Every other statistical result is INCONCLUSIVE, including equality/overlap at +0.25 us or half-width >0.10 us; no budget expansion is allowed.",
        "One technical implementation revision requires fresh supervisor review; no automatic retry.",
    ]
    dump(decision_path, decision)

    meas_path = paths["measurability_contract"]
    meas = json.loads(meas_path.read_text())
    meas["decision_contract_identity"] = identity(decision_path)
    meas["observable"]["name"] = (
        "two-path screening paired-mean delta: 0.5*(E[d_404]+E[d_768])"
    )
    meas["causal_mapping"]["formula"] = EQUATION + " " + CI_FORMULA
    meas["causal_mapping"]["falsification_condition"] = (
        "Hard-gate failure rejects C1. Otherwise L>+0.25us rejects; half-width<=0.10us and "
        "U<+0.25us only admits a new QUALIFICATION contract; every other result is INCONCLUSIVE. "
        "Median, unpaired, pooled, or post-hoc bootstrap inference is forbidden."
    )
    meas["causal_mapping"]["controls"].append(
        "Primary inference is the preregistered two-shape paired-mean Welch-Studentized CI; do not switch estimands or CI methods after observing data."
    )
    dump(meas_path, meas)

    queue_path = paths["experiment_queue"]
    queue = json.loads(queue_path.read_text())
    request = next(item for item in queue["requests"] if item["request_id"] == REQUEST_ID)
    request["status"] = "PROPOSED"
    request["decision_contract"] = identity(decision_path)
    request["measurability_contract"] = identity(meas_path)
    request["sensitivity"]["benefit_derivation"].update(
        {
            "decision_contract_identity": identity(decision_path),
            "quantity_id": QUANTITY_ID,
            "decision_boundary": {"value": 0.25, "unit": "us"},
            "maximum_decision_value": {"value": 3.6795, "unit": "us"},
            "method": "paired-mean two-path screening decision sensitivity from the frozen v5 screening contract",
            "top_two_candidate_ids": ["C1", "C0"],
        }
    )
    request["measurement_contract"].update(
        {
            "estimand": "q_screen=0.5*(E[d_404]+E[d_768])",
            "estimator": "q_hat=0.5*(mean(d_404)+mean(d_768))",
            "primary_ci": CI_FORMULA,
            "decision_precedence": [
                "hard gate failure -> REJECT",
                "L > +0.25 us -> REJECT",
                "half-width <=0.10 us and U < +0.25 us -> ADMIT_TO_NEW_QUALIFICATION_CONTRACT",
                "otherwise -> INCONCLUSIVE",
            ],
        }
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
        "reason": "v5 paired-mean estimand requires deterministic rematerialization and fresh hash binding.",
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

    plan_path = paths["optimization_plan"]
    plan = json.loads(plan_path.read_text())
    plan["open_uncertainties"] = [
        {"quantity_id": QUANTITY_ID, "decision_contract": identity(decision_path)}
    ]
    plan["revision_history"].append(
        {
            "revision": 4,
            "at": now,
            "reason": "Freeze SCREENING as a paired-mean admission estimand with a Welch-Studentized CI.",
        }
    )
    dump(plan_path, plan)

    state_path = paths["global_schedule_state"]
    state = json.loads(state_path.read_text())
    state["revision_history"].append(
        {
            "revision": 4,
            "at": now,
            "reason": "Scheduler issued v5 paired-mean SCREENING; no GPU or dispatch authority granted.",
        }
    )
    dump(state_path, state)

    receipt = {
        "schema_version": "screening-contract-repair-receipt-v2",
        "status": "PASS",
        "created_at": now,
        "authorized_by": {
            "role": "GLOBAL_SCHEDULER",
            "owner_id": "global-scheduler-linear-v2",
        },
        "decision_id": DECISION_ID,
        "archived_v4_manifest": identity(archive / "manifest.json"),
        "decision_contract": identity(decision_path),
        "measurability_contract": identity(meas_path),
        "optimization_plan": identity(plan_path),
        "experiment_queue": identity(queue_path),
        "inference": {"estimand": need["equation"], "ci": CI_FORMULA},
        "gpu_or_dispatch_authorized": False,
    }
    receipt_path = run / "traces/screening_contract_repair_v5_paired_mean.json"
    dump(receipt_path, receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
