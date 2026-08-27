#!/usr/bin/env python3
"""Close a result only after the global scheduler updates every affected model."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from evidence_utils import read_object, resolve_evidence_path, sha256, validate_identity
from model_patch_utils import evaluate_calculation, pointer_get
from schema_utils import validate_json_file


def atomic_json(path: Path, data: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--request-id", required=True)
    parser.add_argument("--decision", choices=("ACCEPT", "REJECT", "INCONCLUSIVE"), required=True)
    parser.add_argument("--explanation", required=True)
    parser.add_argument("--model-update-receipt", type=Path, required=True)
    args = parser.parse_args()
    run = args.run.resolve()
    queue_path = run / "models/experiment_queue.json"
    queue = read_object(queue_path)
    request = next((item for item in queue.get("requests", []) if item.get("request_id") == args.request_id), None)
    if request is None or request.get("status") != "RESOLVED":
        raise ValueError("only a RESOLVED request can be reconciled")
    reference = request.get("result_binding", {}).get("model_reconciliation", {})
    reconciliation_path = Path(reference.get("path", ""))
    if not reconciliation_path.is_absolute():
        reconciliation_path = run / reconciliation_path
    reconciliation = read_object(reconciliation_path)
    identity_errors: list[str] = []
    validate_identity(run, reference, "pending model reconciliation", identity_errors, containment_root=run)
    if identity_errors:
        raise ValueError("; ".join(identity_errors))
    if reconciliation.get("status") != "PENDING_GLOBAL_SCHEDULER":
        raise ValueError("reconciliation is not pending")
    model_paths = {
        "resource_balance": run / "models/resource_balance.json",
        "schedule_model": run / "models/schedule_model.json",
        "tradeoff_frontier": run / "models/tradeoff_frontier.json",
        "experiment_queue": queue_path,
    }
    semantic_path = args.model_update_receipt.resolve()
    schema = Path(__file__).resolve().parents[1] / "schemas/semantic_model_update_receipt.schema.json"
    schema_errors = validate_json_file(semantic_path, schema)
    if schema_errors:
        raise ValueError("invalid semantic model update receipt schema: " + "; ".join(schema_errors))
    semantic = read_object(semantic_path)
    if semantic.get("schema_version") != "semantic-model-update-receipt-v1" or semantic.get("status") != "APPLIED":
        raise ValueError("invalid semantic model update receipt")
    if semantic.get("request_id") != args.request_id:
        raise ValueError("semantic model update receipt request mismatch")
    if semantic.get("result_identity", {}).get("sha256") != reconciliation.get("result_identity", {}).get("sha256"):
        raise ValueError("semantic model update receipt result mismatch")
    pre = reconciliation.get("pre_model_identities", {})
    for name in ("resource_balance", "schedule_model", "tradeoff_frontier"):
        if semantic.get("before_model_identities", {}).get(name, {}).get("sha256") != pre.get(name, {}).get("sha256"):
            raise ValueError(f"semantic model update does not start from bound pre-model identity: {name}")
        if semantic.get("after_model_identities", {}).get(name, {}).get("sha256") != sha256(model_paths[name]):
            raise ValueError(f"semantic model update receipt is stale or does not match current model: {name}")
    result_path = resolve_evidence_path(run, str(reconciliation.get("result_identity", {}).get("path", "")))
    result = read_object(result_path)
    touched = set()
    current_models = {name: read_object(model_paths[name]) for name in ("resource_balance", "schedule_model", "tradeoff_frontier")}
    for index, update in enumerate(semantic.get("updates", [])):
        artifact = str(update.get("artifact"))
        if artifact not in current_models:
            raise ValueError(f"semantic model update {index} has invalid artifact")
        touched.add(artifact)
        expected_after = evaluate_calculation(update.get("calculation", {}), result)
        if update.get("after") != expected_after or pointer_get(current_models[artifact], str(update.get("target_pointer", ""))) != expected_after:
            raise ValueError(f"semantic model update {index} is not reproduced by result and current model")
    if touched != {"resource_balance", "schedule_model", "tradeoff_frontier"}:
        raise ValueError("semantic update receipt must cover all affected global models")
    balance = read_object(model_paths["resource_balance"])
    still_bound = [
        f"{case.get('case_id')}/{row.get('resource_id')}"
        for case in balance.get("cases", [])
        for row in case.get("resource_rows", [])
        if args.request_id in row.get("unresolved_request_ids", [])
    ]
    if args.decision in {"ACCEPT", "REJECT"} and still_bound:
        raise ValueError(f"terminal decision still appears as unresolved in resource rows: {still_bound}")
    if args.decision == "INCONCLUSIVE":
        replacements = [
            item for item in queue.get("requests", [])
            if item.get("request_id") != args.request_id
            and item.get("status") in {"PROPOSED", "PLANNED", "DISPATCHED"}
            and set(item.get("resource_ids", [])) & set(request.get("resource_ids", []))
        ]
        if not replacements:
            raise ValueError("INCONCLUSIVE reconciliation requires a replacement falsification request")
    revisions = {
        name: {"path": str(path), "sha256": sha256(path)}
        for name, path in model_paths.items() if name != "experiment_queue"
    }
    reconciliation.update({
        "status": "APPLIED",
        "applied_at": datetime.now(timezone.utc).isoformat(),
        "issued_by_role": "GLOBAL_SCHEDULER",
        "decision": args.decision,
        "explanation": args.explanation,
        "model_revision_identities": revisions,
        "semantic_update_identity": {"path": str(semantic_path), "sha256": sha256(semantic_path)},
    })
    atomic_json(reconciliation_path, reconciliation)
    request["result_binding"]["model_reconciliation"] = {
        "path": str(reconciliation_path),
        "sha256": sha256(reconciliation_path),
        "status": "APPLIED",
        "model_revision_identities": revisions,
        "semantic_update_identity": {"path": str(semantic_path), "sha256": sha256(semantic_path)},
    }
    if args.decision == "INCONCLUSIVE":
        request["status"] = "REJECTED"
    atomic_json(queue_path, queue)
    rank = subprocess.run(
        [sys.executable, str(Path(__file__).with_name("rank_experiments.py")), "--run", str(run)],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if rank.returncode:
        raise RuntimeError(rank.stdout + rank.stderr)
    print(json.dumps({"status": "APPLIED", "request_id": args.request_id, "decision": args.decision, "revisions": revisions}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
