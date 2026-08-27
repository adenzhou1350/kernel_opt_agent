#!/usr/bin/env python3
"""Atomically copy the validated static disposition into admissibility_status."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


RUN = Path(
    "/workspace/dance/qwen35/kernel_opt_agent/runs/"
    "20260827_qwen35_gdn_layout_replan_v3"
)
RESULT = RUN / "experiments/req-n2-layout-view-static-v2/result.json"
STATUS = RUN / "models/admissibility_status.json"
RECEIPT = RUN / "experiments/req-n2-layout-view-static-v2/admissibility_status_sync_receipt.json"
EXPECTED_RESULT = "5940383003a0dc22a690b9e0281abea1b24ff38adc4d3c98efae84e94fbaae66"
EXPECTED_BEFORE = "84e13a2cd480a50f474e8d41fac3b932627db0c2304195b5899b99742107c4c1"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def identity(path: Path) -> dict:
    return {"path": str(path), "sha256": sha(path)}


def atomic_json(path: Path, data: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


if sha(RESULT) != EXPECTED_RESULT:
    raise RuntimeError("bound result identity changed")
if sha(STATUS) != EXPECTED_BEFORE:
    raise RuntimeError("admissibility status before-identity changed")
result = json.loads(RESULT.read_text())
status = json.loads(STATUS.read_text())
before = status["status"]
after = result["summary"]["n2_disposition"]
if before != "STATIC_ADMISSIBILITY_PENDING":
    raise RuntimeError(f"unexpected status before value: {before}")
if after != "LAYOUT_VIEW_FEASIBLE_PENDING_IMPLEMENTATION":
    raise RuntimeError(f"unexpected result disposition: {after}")
if status["performance_top_two_frozen"] is not False:
    raise RuntimeError("performance Top2 changed before static sync")
if status["survivor_set_not_yet_changed"] != ["N0", "N1", "N2"]:
    raise RuntimeError("survivor set changed before static sync")
before_identity = identity(STATUS)
status["status"] = after
atomic_json(STATUS, status)
after_identity = identity(STATUS)
atomic_json(RECEIPT, {
    "schema_version": "admissibility-status-sync-receipt-v1",
    "status": "APPLIED",
    "applied_at": datetime.now(timezone.utc).isoformat(),
    "request_id": "req-n2-layout-view-static-v2",
    "result_identity": identity(RESULT),
    "before_identity": before_identity,
    "after_identity": after_identity,
    "update": {
        "target_pointer": "/status",
        "before": before,
        "calculation": {"op": "COPY_RESULT", "result_pointer": "/summary/n2_disposition"},
        "verified_result_value": after,
        "after": after,
    },
    "invariants": {
        "performance_top_two_frozen": False,
        "survivor_set_not_yet_changed": ["N0", "N1", "N2"],
        "latency_or_dynamic_resource_update": False,
        "production_candidate_acceptance": False,
    },
})
print(json.dumps({"status": "APPLIED", "receipt": str(RECEIPT), "after": after_identity}, sort_keys=True))
