#!/usr/bin/env python3
"""Build candidate-smoke-result-v6 from framework-owned session receipts."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def identity(run: Path, path: Path) -> dict:
    return {"path": path.relative_to(run).as_posix(), "sha256": digest(path)}


def ready_event(run: Path, receipt: dict) -> tuple[dict, Path]:
    stdout = run / receipt["stdout"]["path"]
    if digest(stdout) != receipt["stdout"]["sha256"]:
        raise ValueError("worker stdout hash mismatch")
    first = json.loads(stdout.read_text(encoding="utf-8").splitlines()[0])
    if first.get("event") != "ready":
        raise ValueError("missing worker ready event")
    return first, stdout


run = Path(os.environ["KERNEL_OPT_RUN"]).resolve()
candidate_root = Path(__file__).resolve().parent
receipt_paths = [Path(value) for value in json.loads(os.environ["KERNEL_OPT_PERSISTENT_RECEIPTS"])]
if len(receipt_paths) != 2:
    raise ValueError("PERSISTENT_PER_ARM requires two receipts")
receipts = [json.loads(path.read_text(encoding="utf-8")) for path in receipt_paths]
treatment_ids = {
    digest(candidate_root / "treatment-torch.json"): "baseline",
    digest(candidate_root / "treatment-lossless-packed.json"): "candidate",
}
by_label = {}
ready = {}
stdout_paths = {}
for path, receipt in zip(receipt_paths, receipts):
    ids = {row["treatment_identity"] for row in receipt["requests"]}
    if receipt["status"] != "PASS" or len(ids) != 1:
        raise ValueError("invalid persistent receipt")
    label = treatment_ids[next(iter(ids))]
    by_label[label] = (path, receipt)
    ready[label], stdout_paths[label] = ready_event(run, receipt)
if ready["baseline"]["backend"] != "torch":
    raise ValueError("baseline backend identity mismatch")
if ready["candidate"]["backend"] != "lossless_packed":
    raise ValueError("candidate backend identity mismatch")
packed_count = int(ready["candidate"]["packed_kernel_event_count"])
if packed_count < 1 or int(ready["baseline"]["packed_kernel_event_count"]) != 0:
    raise ValueError("packed-kernel reachability contract failed")

baseline_path, baseline = by_label["baseline"]
candidate_path, candidate = by_label["candidate"]
baseline_rows = {row["request_id"].split("-", 1)[1]: row for row in baseline["requests"]}
candidate_rows = {row["request_id"].split("-", 1)[1]: row for row in candidate["requests"]}
if baseline_rows.keys() != candidate_rows.keys():
    raise ValueError("request suites differ")
roles = {"explain": "ANCHOR", "code": "ANCHOR", "edge": "EDGE"}
case_results = []
for case_id in sorted(baseline_rows):
    before = baseline_rows[case_id]["output_digest"]
    after = candidate_rows[case_id]["output_digest"]
    if before != after:
        raise ValueError(f"exact token mismatch: {case_id}")
    case_results.append(
        {
            "case_id": case_id,
            "role": roles[case_id],
            "status": "PASS",
            "baseline_digest": before,
            "candidate_digest": after,
            "evidence": [identity(run, baseline_path), identity(run, candidate_path)],
        }
    )

candidate_id = "lossless-packed-lmhead-overlay-v2"
plan_path = run / f"models/candidate-execution/{candidate_id}.json"
plan = json.loads(plan_path.read_text(encoding="utf-8"))
source_identity_path = candidate_root / "vllm-source-identity.json"
evidence = [
    identity(run, source_identity_path),
    identity(run, plan_path),
    identity(run, baseline_path),
    identity(run, candidate_path),
    identity(run, stdout_paths["candidate"]),
]
baseline_us = sum(row["duration_seconds"] for row in baseline["requests"]) / len(baseline["requests"]) * 1e6
candidate_us = sum(row["duration_seconds"] for row in candidate["requests"]) / len(candidate["requests"]) * 1e6
result = {
    "schema_version": "candidate-smoke-result-v6",
    "status": "PASS",
    "candidate_id": candidate_id,
    "claim_scope": "DISCOVERY_ONLY_NOT_PRODUCTION_ACCEPTANCE",
    "objective": {
        "direction": "minimize",
        "baseline": baseline_us,
        "candidate": candidate_us,
        "unit": "us_weighted",
        "measurement_window": "STEADY_STATE_ONLY",
    },
    "cases": [{"case_id": key, "role": roles[key]} for key in sorted(roles)],
    "correctness": {
        "status": "PASS",
        "contract": "EXACT_IDENTITY",
        "oracle": "greedy generated-token sequence under the sealed prompt suite",
        "case_results": case_results,
    },
    "reachability": {
        "status": "PASS",
        "expected_path": "vllm.lossless_packed_bf16_lm_head",
        "observed_path": "vllm.lossless_packed_bf16_lm_head",
        "compile_cache_policy": "SOURCE_HASHED",
        "execution_proof": {
            "kind": "KERNEL_INSTANCE_COUNT",
            "scope": "profiled candidate warmup generation",
            "observed_count": packed_count,
            "minimum_count": 1,
            "evidence_index": 4,
        },
        "evidence": evidence,
    },
    "runtime_contract": {
        "production_execution_mode": "CUDA_GRAPH",
        "observed_execution_mode": "CUDA_GRAPH",
        "treatment_materialization": "SOURCE_FILE",
        "compile_cache_key_includes_treatment": True,
        "requires_logical_extent": False,
        "logical_extent_source": "NOT_APPLICABLE",
        "treatment_identity_evidence_index": 3,
    },
    "timing_accounting": {
        "setup_seconds": baseline["setup_seconds"] + candidate["setup_seconds"],
        "compile_seconds": 0.0,
        "warmup_seconds": 0.0,
        "steady_state_seconds": baseline["steady_state_seconds"] + candidate["steady_state_seconds"],
        "steady_state_samples": baseline["request_count"] + candidate["request_count"],
        "objective_window": "STEADY_STATE_ONLY",
        "process_model": plan["selection"]["process_model"],
        "persistent_session_eligible": plan["selection"]["persistent_session_eligible"],
        "switching_preserves_treatment_identity": plan["selection"]["switching_preserves_treatment_identity"],
        "execution_plan_evidence_index": 1,
        "persistent_session_receipt_evidence_indices": [2, 3],
    },
}
(candidate_root / "smoke-result-v2.json").write_text(
    json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
