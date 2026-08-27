#!/usr/bin/env python3
"""Archive the vetoed plan and issue an independent static-admissibility gate."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path("/workspace/dance/qwen35/kernel_opt_agent")
RUN = ROOT / "runs/20260827_qwen35_gdn_layout_replan_v3"
ARCHIVE = RUN / "traces/preapproval_veto_revision_01"
OLD_REQUEST = "req-n2-static-layout-admissibility"
NEW_REQUEST = "req-n2-layout-view-static-v2"
CASES = ["s256", "s384", "s404", "s512", "s640", "s768", "s1024"]
RESOURCES = [
    "cta_allocation", "instruction_front_end", "integer_address_pipe",
    "l1_shared_boundary", "load_store_request", "predicate_compute",
    "predicate_storage", "register_storage", "shared_bank_service",
    "shared_memory", "synchronization", "tensor_compute", "tensor_issue",
    "warp_issue",
]
PRODUCTION = {
    "short": Path("/workspace/dance/qwen35/flashinfer/flashinfer/gdn_kernels/delta_rule_dsl/qwen35_fla_s3_short_raw_sm120.py"),
    "long": Path("/workspace/dance/qwen35/flashinfer/flashinfer/gdn_kernels/delta_rule_dsl/qwen35_fla_s3_long_raw_sm120.py"),
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def identity(path: Path) -> dict:
    return {"path": str(path), "sha256": digest(path)}


def archive_old_state() -> None:
    if ARCHIVE.exists():
        raise FileExistsError(f"refusing to overwrite prior veto archive: {ARCHIVE}")
    ARCHIVE.mkdir(parents=True)
    for relative in (
        "models/decision_contract.json",
        "models/measurability_contract.json",
        "models/experiment_queue.json",
        f"experiments/{OLD_REQUEST}/experiment.json",
        f"experiments/{OLD_REQUEST}/catalog_query_receipt.json",
        "traces/experiment_ranking_receipt.json",
        "traces/static_layout_experiment_seal.json",
    ):
        source = RUN / relative
        if source.is_file():
            target = ARCHIVE / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    source_tree = RUN / "microbench_candidates" / OLD_REQUEST
    if source_tree.is_dir():
        shutil.copytree(source_tree, ARCHIVE / "microbench_candidates" / OLD_REQUEST)


def main() -> None:
    archive_old_state()
    now = datetime.now(timezone.utc).isoformat()
    review_path = ARCHIVE / "review_receipt.json"
    write(review_path, {
        "schema_version": "preapproval-veto-receipt-v1",
        "reviewed_at": now,
        "request_id": OLD_REQUEST,
        "disposition": "REPLAN_REQUIRED_NO_CANDIDATE_DISPOSITION",
        "execution_observed": {
            "supervisor_approval": False, "dispatch": False, "compilation": False,
            "cuda_kernel_launch": False, "gpu_performance_samples": 0,
        },
        "independent_reviews": [
            {"role": "GLOBAL_SUPERVISOR", "decision": "VETO", "reason": "boolean feasibility was assigned latency value and performance Top2 was frozen prematurely"},
            {"role": "MICROARCHITECTURE_ANALYST", "decision": "VETO", "reason": "local layout equality did not prove global coordinates, owner, offset, disjointness, union, or actual GEMM consumption"},
            {"role": "EXPERIMENT_AGENT", "decision": "VETO", "reason": "negative predicate lifecycle, production-source prebinding, and queue experiment identity were not closed"},
        ],
        "forbidden_in_revision": [
            "performance Top2", "latency or speedup value", "performance sensitivity or ranking score",
            "duplicated deterministic samples", "toolchain failure interpreted as candidate rejection",
        ],
    })

    old_decision_path = RUN / "models/decision_contract.json"
    if old_decision_path.is_file():
        old_decision = json.loads(old_decision_path.read_text())
        old_decision["status"] = "REPLAN_REQUIRED"
        write(old_decision_path, old_decision)
    old_meas_path = RUN / "models/measurability_contract.json"
    if old_meas_path.is_file():
        old_meas = json.loads(old_meas_path.read_text())
        old_meas["status"] = "REJECTED"
        write(old_meas_path, old_meas)
    old_experiment_path = RUN / "experiments" / OLD_REQUEST / "experiment.json"
    if old_experiment_path.is_file():
        old_experiment = json.loads(old_experiment_path.read_text())
        old_experiment["status"] = "HALT_AND_REPLAN"
        write(old_experiment_path, old_experiment)

    expected_hashes = {
        "short": "2b61b0da46b13802fcc75620fe7f87fe50d4de6660259327ee08696b0b83929f",
        "long": "2b647e3971a36929a2239c1ade1b4afec33894e0cb6ec638d6b0b046871e149f",
    }
    for name, path in PRODUCTION.items():
        if digest(path) != expected_hashes[name]:
            raise RuntimeError(f"production {name} source changed before static-contract issuance")
    binding_path = RUN / "models/production_constructor_bindings.json"
    write(binding_path, {
        "schema_version": "production-constructor-binding-v1",
        "status": "SOURCE_HASH_BOUND_AST_EXTRACTION_PENDING_EXPERIMENT",
        "bindings": [
            {"production_path": name, "source_identity": identity(path), "active_thread_domain": "tidx<256 of block512" if name == "short" else "tidx<256 of block256"}
            for name, path in PRODUCTION.items()
        ],
        "required_ast_nodes": [
            "BT", "D", "THREADS", "MAIN_THREADS", "accumulator dtype",
            "o1 make_tiled_mma", "get_slice(tidx)", "partition_shape_C((D,BT))",
        ],
        "regex_only_binding_forbidden": True,
    })

    status_path = RUN / "models/admissibility_status.json"
    write(status_path, {
        "schema_version": "candidate-admissibility-status-v1",
        "candidate_id": "N2", "status": "STATIC_ADMISSIBILITY_PENDING",
        "survivor_set_not_yet_changed": ["N0", "N1", "N2"],
        "performance_top_two_frozen": False,
    })

    contract_path = RUN / "models/admissibility_contracts/n2_zero_copy_layout_v1.json"
    contract = {
        "schema_version": "candidate-admissibility-contract-v1",
        "subdecision_id": "admit-n2-zero-copy-layout-v1",
        "status": "READY_FOR_SUPERVISOR",
        "issued_by": {"role": "GLOBAL_SCHEDULER", "owner_id": "global-scheduler-linear-v3"},
        "analysis_owner": {"role": "MICROARCHITECTURE_ANALYST", "analyst_id": "microarchitecture-analyst-linear-v3"},
        "run_id": RUN.name,
        "phase": "MODELING",
        "candidate_binding": {"candidate_id": "N2", "artifact_identity": identity(RUN / "models/architecture_candidates/n2.json")},
        "predicate": {
            "quantity_id": "n2_layout_view_feasible", "unit": "binary_pass",
            "domain": {"lower": 0, "upper": 1},
            "equation": "x=1 iff G1&&G2&&G3&&G4&&G5&&G6 pass for both short and long; x=0 only for a recognized deterministic predicate failure",
            "pass_condition": "x == 1", "fail_condition": "x == 0",
            "statistical_precision": "NOT_APPLICABLE_DETERMINISTIC",
        },
        "gates": [
            {"gate_id": "G1_EXACT_PATH_IDENTITY", "requirement": "hash-bind short/long sources and normalized AST of D=128, BT=64, dtype, FP32 accumulator, O1 MMA, slice, fragment construction and short active-thread guard"},
            {"gate_id": "G2_SAME_ITERATOR", "requirement": "all four N16 tensors share the exact O1 backing engine with only static fragment offsets; no second accumulator or copy"},
            {"gate_id": "G3_BIJECTIVE_MAPPING", "requirement": "enumerate 256*4*8 records and prove identical global coordinate, owner tid/lane, logical backing offset, per-tile disjointness and full union"},
            {"gate_id": "G4_SCOREV_FRAGMENT_COMPATIBILITY", "requirement": "short-512-active256 and long-256 each compile a live O1 producer whose same-backing slices are scoreV cute.gemm C/D operands"},
            {"gate_id": "G5_NEGATIVE_CONTROL", "requirement": "legacy one-warp append mapping is unequal and deterministically detected as REJECT"},
            {"gate_id": "G6_ZERO_DYNAMIC_EXECUTION", "requirement": "compiled callable invocations=0, CUDA kernel launches=0, GPU timing samples=0"},
        ],
        "explicit_non_claims": [
            "no latency value", "no speedup value", "no performance Top2 ordering",
            "no numerical correctness conclusion", "no K-loop accumulation-order proof",
            "no production physical-register, SASS, resource-usage or acceptance claim",
        ],
        "observations": {
            "short": {"count": 1, "unit": "binary_pass"},
            "long": {"count": 1, "unit": "binary_pass"},
            "aggregate": "logical_and(short,long)", "duplicated_samples_forbidden": True,
        },
        "host_budget": {
            "max_configurations": 2, "max_samples_per_configuration": 1,
            "max_process_launches": 6, "max_wall_clock_minutes": 15, "max_revisions": 1,
        },
        "device_budget": {"cuda_kernel_launches": 0, "gpu_performance_samples": 0},
        "outcomes": [
            {"condition": "all G1..G6 pass", "outcome": "ADMIT_N2_LAYOUT_VIEW_PENDING_IMPLEMENTATION"},
            {"condition": "recognized deterministic mapping/layout/alias/coverage predicate false", "outcome": "REJECT_N2_STATIC_LAYOUT"},
            {"condition": "identity/import/tool/compiler infrastructure failure", "outcome": "INVALID_HALT_WITHOUT_N2_DISPOSITION"},
        ],
        "allowed_model_updates": ["N2 static admissibility status", "survivor candidate set", "trigger fresh performance-bound rebuild"],
        "forbidden_model_updates": ["latency interval", "objective value", "performance Top2", "ranking score", "production source", "global candidate acceptance"],
        "evidence": [identity(review_path), identity(binding_path), identity(status_path)],
    }
    write(contract_path, contract)

    request = {
        "request_id": NEW_REQUEST, "status": "PROPOSED", "issued_by_role": "GLOBAL_SCHEDULER",
        "workload_cases": CASES,
        "model_field": "models/admissibility_status.json::status",
        "candidate_decision": "resolve only N2 static layout-view admissibility; do not rank N0/N1/N2 performance",
        "causal_question": "Do exact short and long production O1 fragments admit four same-backing N16 scoreV C/D views?",
        "experiment_kind": "STATIC_ADMISSIBILITY",
        "admissibility_contract": identity(contract_path),
        "experiment_class": "SCREENING", "tested_candidate_ids": ["N2"],
        "implementation_owner": {"role": "EXPERIMENT_AGENT", "actor_id": "experiment-agent-linear-v3"},
        "resource_ids": RESOURCES, "affected_stage_ids": ["s3"], "priority": 0,
        "controls": [
            "Zero dynamic execution: no compiled callable invocation, CUDA launch, event or timer.",
            "Positive control: canonical eight-warp N16 same-backing layout must pass.",
            "Negative control: legacy one-warp append layout must reject.",
            "Live codegen control: O1 producer and all scoreV consumers write the original accumulator to a typed sink.",
        ],
        "measurement_contract": {
            "primary": "deterministic static admissibility predicate",
            "timer": "none_compiler_typecheck", "unit": "binary_pass",
            "configurations": ["short", "long"], "samples_per_configuration": 1,
            "gpu_launches": 0, "performance_samples": 0,
            "classification": {
                "predicate_pass": "VALID binary_pass=1",
                "recognized_predicate_reject": "VALID binary_pass=0",
                "infrastructure_failure": "BLOCKED without candidate disposition",
            },
        },
        "expected_sass": ["static marker/control cubin only; proof cubin cannot support production performance claims"],
        "execution_budget": {"samples_per_configuration": 1, "process_launches": 6, "max_wall_clock_minutes": 15},
        "parameter_matrix": [
            {"candidate_id": "N2", "production_path": "short", "block_threads": 512, "active_threads": 256, "gpu_launches": 0},
            {"candidate_id": "N2", "production_path": "long", "block_threads": 256, "active_threads": 256, "gpu_launches": 0},
        ],
        "catalog_resolution": {
            "catalog_queried": False,
            "query": {"resources": RESOURCES, "mechanisms": ["cute_accumulator_same_backing_view"], "boundaries": [], "qualification": "STATIC_VALIDATED"},
            "decision": "PENDING", "package_id": None, "reason": "awaiting deterministic catalog query",
        },
        "result_binding": {"status": "PENDING", "target": "models/admissibility_status.json::status"},
        "promotion_disposition": {"status": "PENDING", "reason": "review genericity only after a resolved static proof"},
    }
    queue_path = RUN / "models/experiment_queue.json"
    write(queue_path, {
        "schema_version": "experiment-request-queue-v3", "status": "ACTIVE",
        "ranking_policy": {
            "issued_by_role": "GLOBAL_SCHEDULER",
            "formula": "NO_PERFORMANCE_RANKING_SINGLE_STATIC_GATE",
            "benefit_bound": "NOT_APPLICABLE_STATIC_ADMISSIBILITY", "ranked_at": now,
        },
        "requests": [request],
        "catalog_snapshot": {"status": "PENDING_QUERY", "catalog_identity": identity(ROOT / "microbench/catalog.json"), "request_receipts": []},
        "promotion_review": [],
    })

    receipt_path = RUN / "traces/static_admissibility_replan_receipt.json"
    write(receipt_path, {
        "schema_version": "static-admissibility-replan-receipt-v2", "created_at": now,
        "old_request_id": OLD_REQUEST, "old_request_disposition": "STOPPED_PREAPPROVAL_VETO",
        "new_request_id": NEW_REQUEST,
        "review_identity": identity(review_path), "contract_identity": identity(contract_path),
        "queue_identity": identity(queue_path), "production_binding_identity": identity(binding_path),
        "performance_top_two_frozen": False, "performance_ranking_score_present": False,
        "cuda_kernel_launches": 0, "gpu_performance_samples": 0,
    })
    print(json.dumps({"status": "PASS", "receipt": str(receipt_path)}, sort_keys=True))


if __name__ == "__main__":
    main()
