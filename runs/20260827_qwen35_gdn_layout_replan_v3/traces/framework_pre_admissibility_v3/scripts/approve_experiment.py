#!/usr/bin/env python3
"""Issue a hash-bound approval after independent global-supervisor review."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from evidence_utils import read_object, sha256
from experiment_utils import validate_materialized_experiment
from supervision_utils import (
    artifact_path,
    validate_decision_contract,
    validate_experiment_budget,
    validate_global_budget,
    validate_measurability_contract,
)


def identity(path: Path, run: Path) -> dict:
    return {"path": str(path.relative_to(run)), "sha256": sha256(path)}


def atomic_json(path: Path, data: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--request-id", required=True)
    parser.add_argument("--supervisor-id", required=True)
    parser.add_argument("--rationale", required=True)
    args = parser.parse_args()
    run = args.run.resolve()
    queue_path = run / "models/experiment_queue.json"
    queue = read_object(queue_path)
    request = next((item for item in queue.get("requests", []) if item.get("request_id") == args.request_id), None)
    if request is None or request.get("status") not in {"PLANNED", "AWAITING_SUPERVISOR_REVIEW"}:
        raise ValueError("approval requires a PLANNED or AWAITING_SUPERVISOR_REVIEW request")
    state = read_object(run / "models/global_schedule_state.json")
    supervisor = state.get("supervisor", {})
    if supervisor.get("role") != "GLOBAL_SUPERVISOR" or supervisor.get("owner_id") != args.supervisor_id:
        raise ValueError("--supervisor-id is not the registered GLOBAL_SUPERVISOR")
    experiment_path = run / "experiments" / args.request_id / "experiment.json"
    decision_path = artifact_path(run, request.get("decision_contract", {}))
    measurability_path = artifact_path(run, request.get("measurability_contract", {}))
    errors = validate_materialized_experiment(experiment_path, run)
    errors.extend(validate_decision_contract(decision_path, run) if decision_path.is_file() else ["decision contract is missing"])
    errors.extend(validate_measurability_contract(measurability_path, run, decision_path) if measurability_path.is_file() and decision_path.is_file() else ["measurability contract is missing"])
    if errors:
        print(json.dumps({"status": "REJECTED", "errors": errors}, indent=2, sort_keys=True))
        return 1
    experiment = read_object(experiment_path)
    decision = read_object(decision_path)
    measurability = read_object(measurability_path)
    errors.extend(validate_experiment_budget(experiment, decision))
    errors.extend(validate_global_budget(run, decision))
    scheduler_id = decision.get("issued_by", {}).get("owner_id")
    analyst_id = measurability.get("issued_by", {}).get("analyst_id")
    experimenter_id = experiment.get("prepared_by", {}).get("actor_id")
    actors = [args.supervisor_id, scheduler_id, analyst_id, experimenter_id]
    if None in actors or len(actors) != len(set(actors)):
        errors.append("separation of duties requires distinct supervisor, scheduler, analyst and experimenter ids")
    required_tier = measurability.get("required_tier")
    if experiment.get("experiment_class") != required_tier:
        errors.append("experiment class differs from the measurability-required tier")
    if measurability.get("selected_method") == "NO_MEASUREMENT":
        errors.append("NO_MEASUREMENT is a stop/replan result, not an executable experiment")
    revisions = len(request.get("attempt_history", []))
    if revisions > int(decision.get("experiment_budget", {}).get("max_revisions", -1)):
        errors.append("decision-contract revision budget is exhausted")
    if errors:
        print(json.dumps({"status": "REJECTED", "errors": errors}, indent=2, sort_keys=True))
        return 1
    tier_budget = decision["experiment_budget"][required_tier.lower()]
    approval = {
        "schema_version": "supervisor-approval-v1",
        "approval_id": f"approval-{args.request_id}-{sha256(experiment_path)[:12]}",
        "status": "APPROVED",
        "issued_at": datetime.now(timezone.utc).isoformat(),
        "issued_by": {"role": "GLOBAL_SUPERVISOR", "supervisor_id": args.supervisor_id},
        "request_id": args.request_id,
        "action": f"DISPATCH_{required_tier}",
        "experiment_identity": identity(experiment_path, run),
        "decision_contract_identity": identity(decision_path, run),
        "measurability_contract_identity": identity(measurability_path, run),
        "frontier_identity": decision["frontier_identity"],
        "objective_identity": decision["objective_identity"],
        "approved_budget": tier_budget,
        "separation_of_duties": {
            "scheduler_id": scheduler_id,
            "analyst_id": analyst_id,
            "experimenter_id": experimenter_id,
            "all_distinct": True,
        },
        "gate_results": [
            {"gate": "CANDIDATE_COUNT_2_TO_4", "status": "PASS"},
            {"gate": "TOP_TWO_ORDER_CAN_FLIP", "status": "PASS"},
            {"gate": "ONE_DECISION_UNCERTAINTY", "status": "PASS"},
            {"gate": "METHOD_IDENTIFIABLE", "status": "PASS"},
            {"gate": "EXPECTED_PRECISION_SUFFICIENT", "status": "PASS"},
            {"gate": "BUDGET_WITHIN_CONTRACT", "status": "PASS"},
            {"gate": "SEPARATION_OF_DUTIES", "status": "PASS"},
        ],
        "rationale": args.rationale,
        "single_use": True,
    }
    approval_path = experiment_path.parent / "supervisor_approval.json"
    atomic_json(approval_path, approval)
    request["supervisor_approval"] = identity(approval_path, run)
    request["status"] = "PLANNED"
    atomic_json(queue_path, queue)
    print(json.dumps({"status": "APPROVED", "approval": str(approval_path)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
