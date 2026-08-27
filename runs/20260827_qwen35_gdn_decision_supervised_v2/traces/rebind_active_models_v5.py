#!/usr/bin/env python3
"""Rebind active modeling questions to SCREENING v5 and defer qualification work."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


SCREEN_QUANTITY = "screening_two_path_mean_delta_c1_minus_c0"
WEIGHTED_QUANTITY = "weighted_full_pipeline_candidate_delta_c1_minus_c0"
TRANSFER_QUANTITY = "graph_to_direct_ranking_transfer"


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
    microarch_path = models / "microarchitecture_model.json"
    plan_path = models / "microbenchmark_plan.json"
    now = datetime.now(timezone.utc).isoformat()

    archive = run / "traces/contract_archive/v5_pre_active_model_rebind"
    archive.mkdir(parents=True, exist_ok=False)
    for source in (microarch_path, plan_path):
        shutil.copy2(source, archive / source.name)
    dump(
        archive / "manifest.json",
        {
            "schema_version": "active-model-archive-receipt-v1",
            "status": "PASS",
            "archived_at": now,
            "artifacts": [
                identity(archive / microarch_path.name),
                identity(archive / plan_path.name),
            ],
            "reason": "Active model still exposed deferred seven-shape and graph/direct qualification questions.",
        },
    )

    microarch = json.loads(microarch_path.read_text())
    retained_latency = []
    deferred_latency = list(microarch.get("deferred_qualification_constraints", []))
    for item in microarch["latency_constraints"]:
        text = str(item.get("constraint", ""))
        if "graph/direct" in text:
            deferred_latency.append(
                {
                    "quantity_id": TRANSFER_QUANTITY,
                    "constraint": "Graph/direct deltas must agree in sign and the delta-difference 95% CI must fit [-0.10,+0.10] us before production acceptance.",
                    "status": "NOT_AUTHORIZED_BY_SCREENING_V5",
                    "activation_condition": "C1 receives ADMIT_TO_NEW_QUALIFICATION_CONTRACT and a separate qualification contract is issued",
                }
            )
        else:
            retained_latency.append(item)
    microarch["latency_constraints"] = retained_latency
    microarch["deferred_qualification_constraints"] = deferred_latency

    active_unknowns = []
    deferred_unknowns = list(microarch.get("deferred_qualification_unknowns", []))
    for item in microarch["unknowns"]:
        if item.get("quantity_id") == WEIGHTED_QUANTITY:
            active_unknowns.append(
                {
                    "decision_relevance": "CURRENT_SCREENING_TOP_TWO_SENSITIVE",
                    "quantity_id": SCREEN_QUANTITY,
                    "resolution": "req-s3-tile-causal-production-ab: paired-mean CANDIDATE_AB at s404 and s768 under screening-v5",
                }
            )
            deferred_unknowns.append(
                {
                    "quantity_id": WEIGHTED_QUANTITY,
                    "status": "NOT_AUTHORIZED_BY_SCREENING_V5",
                    "activation_condition": "C1 receives ADMIT_TO_NEW_QUALIFICATION_CONTRACT and a separate qualification contract is issued",
                    "resolution": "seven-shape production-objective qualification",
                }
            )
        else:
            active_unknowns.append(item)
    microarch["unknowns"] = active_unknowns
    microarch["deferred_qualification_unknowns"] = deferred_unknowns
    dump(microarch_path, microarch)

    bench = json.loads(plan_path.read_text())
    bench["target_questions"] = [
        {
            "method": "CANDIDATE_AB_PAIRED_MEAN",
            "quantity_id": SCREEN_QUANTITY,
            "question": "At s404 and s768, does q_screen=0.5*(mean paired delta_s404+mean paired delta_s768) satisfy the frozen +0.25 us SCREENING boundary under the v5 precision/outcome rules?",
        }
    ]
    bench["cross_layer_prediction_gates"] = [
        item
        for item in bench["cross_layer_prediction_gates"]
        if "graph/direct" not in str(item.get("gate", ""))
    ]
    bench["deferred_qualification_questions"] = [
        {
            "method": "PAIRED_TRANSFER_GATE",
            "quantity_id": TRANSFER_QUANTITY,
            "status": "NOT_AUTHORIZED_BY_SCREENING_V5",
            "activation_condition": "new supervised QUALIFICATION contract",
            "question": "Does graph-batched ranking transfer to uncaptured-direct execution?",
        }
    ]
    dump(plan_path, bench)

    receipt = {
        "schema_version": "active-model-rebind-receipt-v1",
        "status": "PASS",
        "created_at": now,
        "authorized_by": {
            "role": "GLOBAL_SCHEDULER",
            "owner_id": "global-scheduler-linear-v2",
        },
        "active_quantity": SCREEN_QUANTITY,
        "microarchitecture_model": identity(microarch_path),
        "microbenchmark_plan": identity(plan_path),
        "archived_pre_rebind": identity(archive / "manifest.json"),
        "gpu_or_dispatch_authorized": False,
    }
    dump(run / "traces/active_models_rebind_v5.json", receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
