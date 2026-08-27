#!/usr/bin/env python3
"""Resolve one queued request against the catalog and create an executable-plan scaffold."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from evidence_utils import read_object, sha256
from experiment_utils import catalog_matches
from supervision_utils import artifact_path, validate_decision_contract, validate_measurability_contract


def atomic_json(path: Path, data: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--request-id", required=True)
    parser.add_argument("--catalog", type=Path)
    args = parser.parse_args()
    run = args.run.resolve()
    project_root = Path(__file__).resolve().parents[1]
    catalog_path = (args.catalog or project_root / "microbench/catalog.json").resolve()
    catalog = read_object(catalog_path)
    queue_path = run / "models/experiment_queue.json"
    queue = read_object(queue_path)
    request = next((item for item in queue.get("requests", []) if item.get("request_id") == args.request_id), None)
    if request is None:
        raise ValueError(f"request not found: {args.request_id}")
    if request.get("status") not in {"PROPOSED", "PLANNED"}:
        raise ValueError(f"request must be PROPOSED or PLANNED, got {request.get('status')}")
    if queue.get("schema_version") != "experiment-request-queue-v2":
        raise ValueError("legacy resource-centric requests are read-only; create a v2 candidate-driven request")
    decision_path = artifact_path(run, request.get("decision_contract", {}))
    measurability_path = artifact_path(run, request.get("measurability_contract", {}))
    errors = validate_decision_contract(decision_path, run) if decision_path.is_file() else ["decision contract is missing"]
    errors.extend(validate_measurability_contract(measurability_path, run, decision_path) if measurability_path.is_file() and decision_path.is_file() else ["measurability contract is missing"])
    if errors:
        raise ValueError("candidate decision is not executable: " + "; ".join(errors))
    raw_query = request.get("catalog_resolution", {}).get("query", {})
    query = {
        "resources": sorted(set(raw_query.get("resources", request.get("resource_ids", [])))),
        "mechanisms": sorted(set(raw_query.get("mechanisms", []))),
        "boundaries": sorted(set(raw_query.get("boundaries", []))),
        "qualification": raw_query.get("qualification", "PRODUCTION_PREDICTIVE"),
    }
    matches = catalog_matches(catalog, query)
    experiment_root = run / "experiments" / args.request_id
    experiment_root.mkdir(parents=True, exist_ok=True)
    receipt_path = experiment_root / "catalog_query_receipt.json"
    receipt = {
        "schema_version": "catalog-query-receipt-v1",
        "queried_at": datetime.now(timezone.utc).isoformat(),
        "catalog_identity": {"path": str(catalog_path), "sha256": sha256(catalog_path)},
        "query": query,
        "matching_package_ids": [entry["id"] for entry in matches],
        "decision": "REUSE" if matches else "CREATE_RUN_LOCAL",
        "selected_package_id": matches[0]["id"] if matches else None,
    }
    atomic_json(receipt_path, receipt)
    source = {
        "mode": receipt["decision"],
        "package_id": receipt["selected_package_id"],
        "identities": [],
    }
    if matches:
        package = project_root / "microbench" / matches[0]["path"]
        definition = read_object(package / "benchmark.json")
        declared = ["benchmark.json", *definition.get("source_files", []), *definition.get("driver_files", []), *definition.get("analyzer_files", [])]
        source["identities"] = [
            {"path": str((package / relative).resolve()), "sha256": sha256(package / relative)}
            for relative in declared
        ]
    else:
        candidate = run / "microbench_candidates" / args.request_id
        candidate.mkdir(parents=True, exist_ok=True)
        source["candidate_path"] = str(candidate)
    experiment = {
        "schema_version": "executable-experiment-v1",
        "request_id": args.request_id,
        "status": "PLANNED",
        "question": request["causal_question"],
        "level": request.get("level"),
        "model_update_contract": {
            "model_field": request["model_field"],
            "summary_fields": [],
            "decision_changed": request["candidate_decision"],
        },
        "decision_contract_identity": request["decision_contract"],
        "measurability_contract_identity": request["measurability_contract"],
        "experiment_class": request["experiment_class"],
        "tested_candidate_ids": request["tested_candidate_ids"],
        "prepared_by": request["implementation_owner"],
        "execution_budget": request.get("execution_budget", {}),
        "source": source,
        "commands": {name: [] for name in ("clean_build", "static_audit", "correctness", "warmup", "measure", "analyze")},
        "parameter_matrix": request.get("parameter_matrix", []),
        "controls": request.get("controls", []),
        "measurement_contract": request["measurement_contract"],
        "expected_sass": request["expected_sass"],
        "artifacts": {
            "raw_samples": f"experiments/{args.request_id}/raw/samples.json",
            "result": f"experiments/{args.request_id}/result.json",
            "static_audit": f"experiments/{args.request_id}/static/instruction_audit.json",
            "reproduction_log": f"experiments/{args.request_id}/reproduction.json",
        },
        "evidence": [{"path": str(receipt_path), "sha256": sha256(receipt_path)}],
    }
    experiment_path = experiment_root / "experiment.json"
    atomic_json(experiment_path, experiment)
    request["status"] = "PLANNED"
    request.pop("supervisor_approval", None)
    request["catalog_resolution"] = {
        "catalog_queried": True,
        "query": query,
        "decision": receipt["decision"],
        "package_id": receipt["selected_package_id"],
        "reason": "deterministic catalog matcher receipt",
        "receipt": {"path": str(receipt_path), "sha256": sha256(receipt_path)},
    }
    request["materialized_experiment"] = {"path": str(experiment_path), "sha256": sha256(experiment_path), "status": "PLANNED"}
    queue["status"] = "ACTIVE"
    atomic_json(queue_path, queue)
    print(json.dumps({"status": "PLANNED", "experiment": str(experiment_path), "catalog_decision": receipt["decision"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
