#!/usr/bin/env python3
"""Read-only audit of the exact sealed PASS-only experiment and active model scope."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


RUN = Path(
    "/workspace/dance/qwen35/kernel_opt_agent/runs/"
    "20260827_qwen35_gdn_layout_replan_v3"
)
REQUEST = "req-n2-layout-view-static-v2"
EXPECTED_EXPERIMENT = "98d882c42bf6939cd57c1458c300ab1782f0392854e55053c804dc3ad69c85f1"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text())


def audit_identity(item: dict) -> None:
    path = Path(item["path"])
    if not path.is_file() or sha(path) != item["sha256"]:
        raise RuntimeError(f"stale identity: {item}")


experiment_path = RUN / f"experiments/{REQUEST}/experiment.json"
experiment = load(experiment_path)
if sha(experiment_path) != EXPECTED_EXPERIMENT:
    raise RuntimeError("experiment SHA differs from review target")
if experiment["status"] != "MATERIALIZED":
    raise RuntimeError("experiment is not MATERIALIZED")
for item in experiment["source"]["identities"]:
    audit_identity(item)
for item in experiment["evidence"]:
    audit_identity(item)

source_paths = {item["path"] for item in experiment["source"]["identities"]}
required_suffixes = {
    "cutlass/cute/nvgpu/warp/mma.py",
    "cutlass/base_dsl/ast_preprocessor.py",
    "cutlass/base_dsl/ast_helpers.py",
    "cutlass/_mlir/_mlir_libs/_cutlass_ir.cu13.cpython-312-x86_64-linux-gnu.so",
    "/usr/local/cuda/bin/ptxas",
    "/usr/local/cuda/bin/cuobjdump",
    "traces/static_admissibility_revision_02/legacy_attempt2_short_source.py",
}
for suffix in required_suffixes:
    if not any(path.endswith(suffix) for path in source_paths):
        raise RuntimeError(f"required frozen identity absent: {suffix}")

phases = ("clean_build", "static_audit", "correctness", "warmup", "measure", "analyze")
if set(experiment["commands"]) != set(phases):
    raise RuntimeError("phase command set differs")
if any(len(experiment["commands"][phase]) != 1 for phase in phases):
    raise RuntimeError("each phase must have exactly one process")

queue = load(RUN / "models/experiment_queue.json")
request = next(item for item in queue["requests"] if item["request_id"] == REQUEST)
if request["resource_ids"] != ["register_storage"]:
    raise RuntimeError("request still claims dynamic resource set")
if request["catalog_resolution"]["query"]["resources"] != ["register_storage"]:
    raise RuntimeError("catalog query still claims dynamic resource set")
audit_identity(request["catalog_resolution"]["receipt"])
audit_identity(request["admissibility_contract"])
audit_identity(request["materialized_experiment"])

resource = load(RUN / "models/resource_balance.json")
for case in resource["cases"]:
    for row in case["resource_rows"]:
        if REQUEST in row.get("unresolved_request_ids", []):
            raise RuntimeError("static request remains attached to dynamic resource row")
        relevance = row["decision_relevance"]
        if "decision-n2-layout-admissibility-v1" in relevance.get("decision_contract_ids", []):
            raise RuntimeError("old decision contract remains attached to dynamic resource row")
        if "rejects N2" in relevance.get("explanation", ""):
            raise RuntimeError("dynamic resource row retains rejection semantics")
if resource.get("cross_resource_coupling"):
    raise RuntimeError("static request retains dynamic cross-resource coupling")

active_names = (
    "dag.json", "microarchitecture_model.json", "microbenchmark_plan.json",
    "schedule_model.json", "optimization_plan.json", "objective.json",
    "tradeoff_frontier.json", "global_schedule_state.json",
)
for name in active_names:
    text = (RUN / "models" / name).read_text()
    if "req-n2-static-layout-admissibility" in text:
        raise RuntimeError(f"stale request in active model: {name}")
    if "may only admit or reject N2" in text:
        raise RuntimeError(f"PASS-only lifecycle contradiction in active model: {name}")

seal = load(RUN / "traces/static_admissibility_experiment_seal_v3.json")
audit_identity(seal["experiment_identity"])
audit_identity(seal["queue_identity"])
audit_identity(seal["contract_identity"])
for item in seal["source_identities"]:
    audit_identity(item)
if seal["source_audit"]["lifecycle"] != "PASS_ONLY_INVALID":
    raise RuntimeError("seal lifecycle differs")
if any((RUN / "microbench_candidates" / REQUEST).rglob("__pycache__")):
    raise RuntimeError("candidate contains generated Python cache")

print(json.dumps({
    "status": "PASS",
    "experiment_sha256": sha(experiment_path),
    "source_identities": len(experiment["source"]["identities"]),
    "dynamic_resource_request_bindings": 0,
    "process_launches_planned": 6,
    "compiled_callable_invocations": 0,
    "cuda_kernel_launches": 0,
    "gpu_performance_samples": 0,
}, sort_keys=True))
