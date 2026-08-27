#!/usr/bin/env python3
"""Apply the global-scheduler RUN_LOCAL promotion decision atomically."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


RUN = Path(
    "/workspace/dance/qwen35/kernel_opt_agent/runs/"
    "20260827_qwen35_gdn_layout_replan_v3"
)
REQUEST = "req-n2-layout-view-static-v2"
QUEUE = RUN / "models/experiment_queue.json"
RESULT = RUN / f"experiments/{REQUEST}/result.json"
RECEIPT = RUN / f"experiments/{REQUEST}/promotion_review_receipt.json"
RESULT_SHA = "5940383003a0dc22a690b9e0281abea1b24ff38adc4d3c98efae84e94fbaae66"
REASON = (
    "Retain run-local: this valid static PASS proof is application-shaped and "
    "hash-binds the Qwen35 short/long production constructors plus exact "
    "FlashInfer, CuTe and CUDA-toolchain source identities and absolute task "
    "paths. It establishes only N2 logical same-backing layout/type "
    "admissibility; application terms have not been removed, the mechanism is "
    "not exposed as an application-independent parameterized package, and the "
    "required two independent cold-start reproduction receipts and "
    "promotion/purity qualification are absent. It makes no "
    "production-implementation, numerical, performance, dynamic-resource or "
    "portable-hardware claim."
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def identity(path: Path) -> dict:
    return {"path": str(path), "sha256": sha(path)}


def atomic_json(path: Path, data: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


if sha(RESULT) != RESULT_SHA:
    raise RuntimeError("bound result identity changed")
queue = json.loads(QUEUE.read_text())
request = next(item for item in queue["requests"] if item["request_id"] == REQUEST)
if request["status"] != "RESOLVED":
    raise RuntimeError("promotion review requires a RESOLVED request")
if request["result_binding"]["model_reconciliation"]["status"] != "APPLIED":
    raise RuntimeError("promotion review requires APPLIED reconciliation")
if request["catalog_resolution"]["decision"] != "CREATE_RUN_LOCAL":
    raise RuntimeError("promotion review is only for the run-local candidate")
if request["promotion_disposition"].get("status") != "PENDING":
    raise RuntimeError("promotion disposition is not pending")
if any(item.get("request_id") == REQUEST for item in queue["promotion_review"]):
    raise RuntimeError("promotion review already exists")

before_identity = identity(QUEUE)
request["promotion_disposition"] = {"status": "RUN_LOCAL", "reason": REASON}
review = {
    "request_id": REQUEST,
    "candidate_path": f"runs/20260827_qwen35_gdn_layout_replan_v3/microbench_candidates/{REQUEST}",
    "catalog_resolution": "CREATE_RUN_LOCAL",
    "status": "RUN_LOCAL",
    "promotion_attempted": False,
    "qualification_observed": "STATIC_VALIDATED_RUN_LOCAL",
    "result_identity": {
        "path": f"runs/20260827_qwen35_gdn_layout_replan_v3/experiments/{REQUEST}/result.json",
        "sha256": RESULT_SHA,
    },
    "reason": REASON,
    "claims_allowed": [
        "N2 static logical same-backing/type admission for the hash-bound Qwen35 constructors and toolchain"
    ],
    "claims_forbidden": [
        "application-independent mechanism",
        "portable hardware fact",
        "production implementation acceptance",
        "numerical correctness",
        "performance or latency",
        "dynamic resource or transport behavior",
    ],
    "future_promotion_requires": [
        "create a separately validated generalized candidate if removing Qwen35 bindings changes the tested mechanism",
        "remove production imports, model vocabulary, fixed application paths and fixed constructor hashes",
        "parameterize layout domains and toolchain constraints without weakening the causal question",
        "produce structured clean-build/control/static-check artifacts",
        "produce two distinct cold-start reproduction receipts",
        "pass microbench promotion and repository-purity audits",
    ],
}
queue["promotion_review"].append(review)
atomic_json(QUEUE, queue)
after_identity = identity(QUEUE)
atomic_json(RECEIPT, {
    "schema_version": "promotion-review-receipt-v1",
    "status": "APPLIED",
    "applied_at": datetime.now(timezone.utc).isoformat(),
    "issued_by_role": "GLOBAL_SCHEDULER",
    "request_id": REQUEST,
    "result_identity": identity(RESULT),
    "queue_before_identity": before_identity,
    "queue_after_identity": after_identity,
    "promotion_disposition": request["promotion_disposition"],
    "review": review,
})
print(json.dumps({"status": "APPLIED", "receipt": str(RECEIPT), "queue": after_identity}, sort_keys=True))
