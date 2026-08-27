#!/usr/bin/env python3
"""Build the first evidence-closed planning ledger without importing timings."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path


EXPECTED_RESOURCES = {
    "async_copy_engine", "constant_memory_path", "conversion_pipe", "cta_allocation",
    "device_memory_boundary", "instruction_front_end", "integer_address_pipe",
    "kernel_dispatch", "l1_shared_boundary", "l2_boundary", "load_store_request",
    "predicate_compute", "predicate_storage", "register_storage", "scoreboard_wait",
    "shared_bank_service", "shared_memory", "simt_compute", "special_function",
    "synchronization", "system_register_path", "tensor_compute", "tensor_issue",
    "warp_collective", "warp_issue",
}

RESOURCE_KIND = {
    "tensor_compute": "TENSOR_CORE", "tensor_issue": "TENSOR_CORE",
    "simt_compute": "SIMT", "conversion_pipe": "SIMT", "integer_address_pipe": "SIMT",
    "predicate_compute": "SIMT", "predicate_storage": "SIMT", "register_storage": "SIMT",
    "system_register_path": "SIMT", "warp_collective": "SIMT",
    "special_function": "SFU", "async_copy_engine": "TMA",
    "load_store_request": "REQUEST_SERVICE", "constant_memory_path": "REQUEST_SERVICE",
    "l1_shared_boundary": "SHARED_L1", "shared_memory": "SHARED_L1",
    "shared_bank_service": "SHARED_L1", "l2_boundary": "L2",
    "device_memory_boundary": "DEVICE_MEMORY", "instruction_front_end": "FRONT_END",
    "kernel_dispatch": "FRONT_END", "cta_allocation": "FRONT_END", "warp_issue": "FRONT_END",
    "scoreboard_wait": "SYNCHRONIZATION", "synchronization": "SYNCHRONIZATION",
}

REQUESTS = {
    "req-compute-service": {
        "resources": ["conversion_pipe", "integer_address_pipe", "predicate_compute", "simt_compute", "special_function", "tensor_compute", "tensor_issue"],
        "stages": ["s01", "s2", "s3", "post"],
        "field": "resource_balance.*.matched_saturation and utilization for arithmetic resources",
        "question": "What are matched production-shaped latency/throughput curves for tensor, SIMT, SFU, conversion, address, and predicate work, including their concurrency limits?",
        "decision": "Choose stage tiling, warp roles, instruction mix, and arithmetic-for-memory tradeoffs.",
        "controls": ["dependent and independent chains", "matched datatype and instruction family", "fixed clocks/power policy", "zero-work control", "warm code and allocation"],
        "sass": ["UTMALDG/UTMACCTL", "FFMA/FADD/FMUL", "MUFU", "F2FP", "IADD3/IMAD", "ISETP/PLOP3"],
        "levels": ["P1", "P2"],
    },
    "req-memory-hierarchy-service": {
        "resources": ["device_memory_boundary", "l2_boundary"],
        "stages": ["s01", "s2", "s3", "post"],
        "field": "resource_balance.*.utilization for L2 and device-memory boundaries",
        "question": "What are production-shaped useful-byte and transferred-byte service curves at the L2 and device-memory boundaries for this working-set and access geometry?",
        "decision": "Choose materialization, reuse, padding, and fusion boundaries.",
        "controls": ["warm-L2 and cold/streaming regimes", "read/write separation", "matched vector width and stride", "transaction accounting", "competing-load gate"],
        "sass": ["LDG", "STG"],
        "levels": ["P1", "P2"],
    },
    "req-p0-measurement-system": {
        "resources": ["cta_allocation", "instruction_front_end", "kernel_dispatch", "warp_issue"],
        "stages": ["measurement_system"],
        "field": "baseline measurement error and front-end/launch floor",
        "question": "Is the GPU-event timing system stable and what launch/front-end floor is visible under matched grid/block geometry?",
        "decision": "Accept or reject all later latency samples and select repetition/batching policy.",
        "controls": ["empty and near-empty kernels", "event overhead subtraction check", "same stream", "warmup convergence", "idle-device gate", "raw immutable samples"],
        "sass": ["EXIT", "BRA", "NOP"],
        "levels": ["P0"],
    },
    "req-register-collective": {
        "resources": ["predicate_storage", "register_storage", "system_register_path", "warp_collective"],
        "stages": ["s01", "s2", "s3", "post"],
        "field": "resource_balance.*.utilization and allocation sensitivity for register/collective resources",
        "question": "How do register allocation, spills, occupancy, system-register access, and warp collectives constrain the production schedule?",
        "decision": "Choose warp count, role-specific registers, unrolling, and collective layout.",
        "controls": ["register-count sweep", "spill-free final binary gate", "occupancy/residency sweep", "dependent/independent collective chains", "same useful work"],
        "sass": ["R2P/P2R", "S2R", "SHFL", "VOTE", "REDUX", "ELECT"],
        "levels": ["P1", "P2", "P3"],
    },
    "req-shared-request-service": {
        "resources": ["constant_memory_path", "l1_shared_boundary", "load_store_request", "shared_bank_service", "shared_memory"],
        "stages": ["s01", "s2", "s3", "post"],
        "field": "resource_balance.*.matched_saturation and request amplification for L1/shared/request paths",
        "question": "What request-service, L1/shared, bank-conflict, and constant-broadcast behavior is produced by the exact tile and layout?",
        "decision": "Choose shared layouts, padding/swizzles, vector width, and reuse policy.",
        "controls": ["bank-index sweep", "stride/vector-width sweep", "broadcast and divergent constant loads", "same payload bytes", "dependent and throughput chains"],
        "sass": ["LDS", "STS", "LDC", "LDG", "STG"],
        "levels": ["P1", "P2"],
    },
    "req-sync-async-overlap": {
        "resources": ["async_copy_engine", "scoreboard_wait", "synchronization"],
        "stages": ["s01", "s2", "s3", "post"],
        "field": "resource_balance.*.critical_path overlap and synchronization truncation",
        "question": "Which copy/compute and producer/consumer dependencies overlap, and which waits or barriers remain on the critical path?",
        "decision": "Choose pipeline depth, warp specialization, barrier placement, and legal cross-stage fusion.",
        "controls": ["A-only/B-only/AB coupling", "dependency-preserving order", "pipeline-depth sweep", "same payload and occupancy", "barrier/wait SASS accounting"],
        "sass": ["UTMALDG", "DEPBAR", "BAR", "WARPGROUP", "SYNCS"],
        "levels": ["P2", "P3"],
    },
}


def load(path: Path) -> dict:
    return json.loads(path.read_text())


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def identity(run: Path, path: Path) -> dict:
    return {"path": str(path.relative_to(run)), "sha256": sha(path)}


def request_for_resource(resource_id: str) -> str:
    matches = [request_id for request_id, request in REQUESTS.items() if resource_id in request["resources"]]
    if len(matches) != 1:
        raise RuntimeError(f"resource {resource_id} maps to {matches}, expected exactly one request")
    return matches[0]


def unknown_resource_row(resource_id: str, discovery_identity: dict) -> dict:
    kind = RESOURCE_KIND[resource_id]
    row = {
        "resource_id": resource_id,
        "resource_kind": kind,
        "material": True,
        "mandatory_work": {"status": "UNKNOWN", "value": 0, "unit": "unresolved_dynamic_work_units"},
        "actual_work": {"status": "UNKNOWN", "value": 0, "unit": "unresolved_dynamic_work_units"},
        "production_point": {"status": "UNKNOWN", "value": None, "unit": "unknown"},
        "matched_saturation": {"status": "UNKNOWN", "value": None, "unit": "unknown", "conditions": []},
        "utilization": {
            "status": "UNKNOWN", "value_percent": None, "numerator": None, "denominator": None,
            "time_window": "unmeasured production kernel-active window", "boundary": kind,
        },
        "critical_path": {"status": "UNKNOWN", "contribution_us": None, "coupling_model": "UNMEASURED", "probability": 1.0},
        "non_saturation_causes": ["NOT_ESTABLISHED"],
        "evidence": [discovery_identity],
        "unresolved_request_ids": [request_for_resource(resource_id)],
    }
    if kind == "TENSOR_CORE":
        row["compute_efficiency"] = {
            "device_coverage": None,
            "eligible_time_fraction": None,
            "eligible_window_issue_efficiency": None,
            "composition_status": "UNKNOWN",
        }
    return row


def current_schedule(case: dict) -> dict:
    params = case["parameters"]
    return {
        "schedule_id": "current-production-four-stage-unmeasured",
        "correctness": "PENDING_BASELINE",
        "valid_compute": {"status": "UNKNOWN", "operations": None},
        "padded_compute": {"status": "UNKNOWN", "operations": None, "P": params["P"], "S": params["S"]},
        "bytes_by_boundary": {"status": "UNKNOWN", "request": None, "L2": None, "device_memory": None},
        "allocation": {"status": "UNKNOWN", "registers_per_thread": None, "shared_bytes": None, "grid": None, "block": None},
        "device_coverage": {"status": "UNKNOWN", "fraction": None},
        "synchronization": {"status": "UNKNOWN", "barriers": None, "waits": None},
        "predicted_dag_us": None,
        "measured_us": None,
        "uncertainty": {"status": "UNKNOWN", "us": None},
        "decision": "PENDING_BASELINE",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    args = parser.parse_args()
    run = args.run.resolve()
    project = args.project_root.resolve()
    workload = load(run / "workload.json")
    hardware = load(run / "hardware.json")
    discovery_path = run / "models/resource_discovery.json"
    discovery = load(discovery_path)
    if discovery.get("status") != "READY" or discovery.get("unresolved_mappings"):
        raise RuntimeError("resource discovery is not evidence-closed READY")
    resources = set(map(str, discovery.get("required_resource_ids", [])))
    if resources != EXPECTED_RESOURCES or set(RESOURCE_KIND) != resources:
        raise RuntimeError(f"unexpected exact material resource set: {sorted(resources)}")
    if set().union(*(set(item["resources"]) for item in REQUESTS.values())) != resources:
        raise RuntimeError("request partition does not cover the exact material resource set")
    cases = workload["cases"]
    case_ids = [str(case["id"]) for case in cases]
    if abs(sum(float(case["weight"]) for case in cases) - 1.0) > 1e-12:
        raise RuntimeError("workload weights must sum to one")
    discovery_identity = identity(run, discovery_path)
    hardware_identity = identity(run, run / "hardware.json")
    hardware_evidence_identity = identity(run, run / "hardware_evidence.json")
    catalog_path = project / "microbench/catalog.json"
    catalog_hash = sha(catalog_path)
    owner = "qwen35-gdn-global-scheduler-v1"

    priorities = [{"case_id": case["id"], "weight": case["weight"]} for case in cases]
    sorted_request_ids = sorted(REQUESTS)
    optimization_plan = {
        "schema_version": "optimization-plan-v1", "status": "EXECUTABLE",
        "objective": {
            "metric": "equal-weight mean production-exact GPU-active latency over the seven prefill shapes",
            "direction": "minimize", "primary_anchor": "s404", "weights_source": "workload.json; equal weights pending production frequency input",
        },
        "global_scheduler_owner": owner,
        "baseline_identities": [],
        "workload_priorities": priorities,
        "model_dependencies": ["mandatory-work ledger", "mathematical/current DAG", "target resource graph", "P0-P3 calibrated matched service curves", "P4 production validation"],
        "experiment_queue": sorted_request_ids,
        "correctness_gates": [
            "Bitwise preserve the current stage-boundary tensors and final output unless a separate numerical-tolerance change is authorized.",
            "Preserve current ABI, physical layouts, initial_state=None, and output_final_state=False.",
            "Reject any final binary with local-memory spills or an unexplained SASS change.",
        ],
        "evidence_gates": [
            "All timing must be GPU-event, raw-sample backed, P0-qualified, and separately report CPU dispatch and end-to-end time.",
            "Every measured/bounded model row must bind immutable evidence and exact source/binary identities.",
            "Final acceptance requires correctness, matched final-binary SASS, production-exact P4 timing, and prediction-error closure.",
        ],
        "acceptance_rule": "Only the GLOBAL_SCHEDULER may accept a candidate, and only if the weighted production objective improves with uncertainty resolved and no workload case regresses outside the declared tolerance.",
        "model_error_tolerances_percent": {"p1_p2_to_p3": 10.0, "schedule_to_p4": 5.0, "achieved_to_feasible_bound": 5.0},
        "stop_criteria": [
            "All material resource rows are MEASURED, BOUNDED, or NOT_APPLICABLE with immutable evidence.",
            "All experiment requests are terminal and the production DAG prediction error is within tolerance.",
            "The achieved production curve is within 5% of the evidence-backed feasible lower bound, or the residual gap has a SASS plus microarchitectural explanation.",
        ],
        "open_uncertainties": ["All latency, throughput, utilization, dynamic work, overlap, and critical-path values remain intentionally unknown before baseline/P0."],
        "revision_history": [{"revision": 1, "reason": "Blind evidence-closed planning from exact workload, source, binary SASS, and official hardware evidence; no historical timings imported."}],
    }

    discovery_nodes = {node["resource_id"]: node for node in discovery["resource_nodes"]}
    architecture = {
        "schema_version": "microarchitecture-model-v1", "status": "INITIALIZED",
        "target_identity": {**hardware["target"], "snapshot_sha256": hardware_identity["sha256"]},
        "scope": sorted(resources),
        "resource_nodes": [{
            "resource_id": resource_id, "resource_kind": RESOURCE_KIND[resource_id], "status": "DETECTED",
            "service_status": "UNKNOWN", "observed_triggers": discovery_nodes[resource_id].get("triggers", []),
            "official_evidence": discovery_nodes[resource_id].get("official_evidence", []),
        } for resource_id in sorted(resources)],
        "resource_edges": [
            {"from": "device_memory_boundary", "to": "l2_boundary", "relation": "data path; numeric service/latency unknown"},
            {"from": "l2_boundary", "to": "l1_shared_boundary", "relation": "data path; cache policy and service unknown"},
            {"from": "l1_shared_boundary", "to": "load_store_request", "relation": "request/transaction coupling unknown"},
            {"from": "load_store_request", "to": "warp_issue", "relation": "issue and scoreboard coupling unknown"},
            {"from": "register_storage", "to": "cta_allocation", "relation": "allocation/residency coupling"},
            {"from": "warp_issue", "to": "tensor_issue", "relation": "front-end issue to tensor instruction issue"},
            {"from": "async_copy_engine", "to": "synchronization", "relation": "producer/consumer completion dependency"},
        ],
        "allocation_constraints": [{"source": "hardware.json", "status": "DOCUMENTED", "values": {key: hardware["target"][key] for key in ("sm_count", "warp_size", "max_threads_per_block", "max_threads_per_sm", "registers_per_sm", "shared_memory_per_sm_bytes", "shared_memory_per_block_optin_bytes")}}],
        "service_curves": [], "latency_constraints": [],
        "workload_mappings": [{"case_id": case_id, "material_resource_ids": sorted(resources), "status": "UNMEASURED"} for case_id in case_ids],
        "overlap_constraints": [{"status": "UNKNOWN", "question": REQUESTS["req-sync-async-overlap"]["question"]}],
        "unknowns": [{"resource_id": resource_id, "request_id": request_for_resource(resource_id), "unknown": "matched throughput, latency, utilization, and critical-path contribution"} for resource_id in sorted(resources)],
        "evidence": [hardware_identity, hardware_evidence_identity, discovery_identity],
    }

    microbench = {
        "schema_version": "microbenchmark-plan-v1", "status": "EXECUTABLE",
        "target_questions": [REQUESTS[key]["question"] for key in sorted_request_ids],
        "qualification_order": ["DRAFT", "STATIC_VALIDATED", "MECHANISM_VALIDATED", "DEVICE_CALIBRATED", "PRODUCTION_PREDICTIVE"],
        "levels": {
            level: {
                "required": True, "status": "PENDING",
                "reason": {
                    "P0": "Qualify timing, warmup, device-identity, idle-device, and launch-floor behavior before accepting any latency.",
                    "P1": "Measure isolated latency/throughput/service mechanisms with exact instruction-family SASS checks.",
                    "P2": "Measure resource coupling, contention, cache/bank/occupancy sensitivity, and overlap using A/B/AB controls.",
                    "P3": "Predict and test production-shaped stage and multi-stage behavior using the P1/P2 model.",
                    "P4": "Validate the selected candidate in production-exact Harrix/service boundaries and separate GPU, CPU dispatch, and end-to-end latency.",
                }[level],
                "experiments": [key for key in sorted_request_ids if level in REQUESTS[key]["levels"]] if level != "P4" else ["production-exact-seven-case-validation"],
            } for level in ("P0", "P1", "P2", "P3", "P4")
        },
        "coupling_tests": ["A-only/B-only/AB for copy-compute, memory-compute, front-end-payload, shared-bank, and synchronization dependencies."],
        "cross_layer_prediction_gates": ["P1/P2 predicts P3 within 10%; schedule model predicts P4 within 5%; deviations trigger model revision rather than post-hoc explanation."],
        "unresolved_questions": [REQUESTS[key]["question"] for key in sorted_request_ids],
    }

    global_state = {
        "schema_version": "global-schedule-state-v1", "status": "PLANNED",
        "owner": {"role": "GLOBAL_SCHEDULER", "owner_id": owner, "exclusive_authority": ["RANK_EXPERIMENTS", "CLOSE_RESOURCE_MODEL", "ACCEPT_GLOBAL_CANDIDATE", "AUTHORIZE_LIMIT_REPORT"]},
        "material_resources": sorted(resources),
        "stage_assignments": [
            {"scope": "measurement_system", "stage_ids": ["measurement_system"], "constraint": "must close P0 before timing acceptance"},
            {"scope": "production_pipeline", "stage_ids": ["s01", "s2", "s3", "post"], "constraint": "local speedup cannot authorize global acceptance"},
        ],
        "owned_artifacts": {"resource_balance": "models/resource_balance.json", "tradeoff_frontier": "models/tradeoff_frontier.json", "experiment_queue": "models/experiment_queue.json", "schedule_model": "models/schedule_model.json"},
        "decision_policy": {"objective": optimization_plan["objective"], "ranking": "max_weighted_benefit_us * critical_path_probability * uncertainty_weight / experiment_cost_weight", "local_speedup_is_not_global_acceptance": True},
        "human_report_gate": {"status": "BLOCKED", "requires": ["validated resource balance", "validated tradeoff frontier", "validated production model"]},
        "revision_history": [{"revision": 1, "reason": "Exact resource set discovered from the current s404 production composite binary; all numeric service facts remain unknown."}],
    }

    requests = []
    for priority, request_id in enumerate(sorted_request_ids):
        spec = REQUESTS[request_id]
        contributions = [{"case_id": case_id, "stages": spec["stages"], "max_removable_us": 0.0, "critical_path_probability": 0.0} for case_id in case_ids]
        requests.append({
            "request_id": request_id, "status": "PROPOSED", "issued_by_role": "GLOBAL_SCHEDULER",
            "workload_cases": case_ids, "model_field": spec["field"], "candidate_decision": spec["decision"],
            "causal_question": spec["question"], "resource_ids": spec["resources"], "affected_stage_ids": spec["stages"], "priority": priority,
            "sensitivity": {
                "max_weighted_benefit_us": 0.0, "critical_path_probability": 0.0,
                "uncertainty": "maximal-before-baseline", "experiment_cost": "unestimated-before-P0",
                "uncertainty_weight": 1.0, "experiment_cost_weight": 1.0, "ranking_score": 0.0,
                "benefit_derivation": {"status": "UNMEASURED_BASELINE", "case_contributions": contributions},
            },
            "controls": spec["controls"],
            "measurement_contract": {"timer": "P0-qualified CUDA GPU events for GPU-active; separate host clock for CPU dispatch and end-to-end", "cache": "explicit per experiment", "geometry": "production-matched or declared sensitivity sweep", "samples": "immutable raw samples with warmup/convergence and competing-load receipts"},
            "expected_sass": spec["sass"],
            "catalog_resolution": {"catalog_queried": False, "query": {"target_cc": "12.0", "resource_ids": spec["resources"], "levels": spec["levels"], "production_shape": {"B": 1, "H": 16, "D": 128, "S": case_ids}}, "decision": "PENDING_QUERY", "package_id": None, "reason": "Query is required at dispatch; PROPOSED status preserves blind planning."},
            "result_binding": {"status": "PENDING", "evidence": []},
            "promotion_disposition": {"status": "PENDING", "reason": "Promotion review follows mechanism validation and removal of application-specific tokens."},
        })
    queue = {
        "schema_version": "experiment-request-queue-v1", "status": "EXECUTABLE",
        "ranking_policy": {"primary": "max_weighted_benefit_us", "secondary": ["critical_path_probability", "uncertainty", "experiment_cost"], "formula": "max_weighted_benefit_us * critical_path_probability * uncertainty_weight / experiment_cost_weight", "issued_by_role": "GLOBAL_SCHEDULER", "prebaseline_tie_break": "lexicographic request_id; all benefit windows are zero until baseline"},
        "requests": requests,
        "catalog_snapshot": {"path": str(catalog_path), "sha256": catalog_hash, "status": "SNAPSHOT_ONLY_NOT_QUERIED"},
        "promotion_review": [],
    }

    stage_zeros = {"measurement_system": 0.0, "s01": 0.0, "s2": 0.0, "s3": 0.0, "post": 0.0}
    balance = {
        "schema_version": "resource-balance-ledger-v1", "status": "INITIALIZED",
        "cases": [{
            "case_id": case_id,
            "resource_rows": [unknown_resource_row(resource_id, discovery_identity) for resource_id in sorted(resources)],
            "device_coverage": {"status": "UNKNOWN", "fraction": None, "reason": "production grid and residency not yet measured"},
            "critical_path": {"status": "UNMEASURED", "stage_gpu_active_us": stage_zeros, "total_us": 0.0},
            "model_residual": {"status": "UNKNOWN", "value_us": None},
        } for case_id in case_ids],
        "cross_resource_coupling": [{"status": "UNKNOWN", "request_id": request_id, "resource_ids": REQUESTS[request_id]["resources"]} for request_id in sorted_request_ids],
        "unresolved_material_resources": [{"resource_id": resource_id, "request_id": request_for_resource(resource_id)} for resource_id in sorted(resources)],
        "evidence": [discovery_identity],
    }

    frontier = {
        "schema_version": "tradeoff-frontier-v1", "status": "INITIALIZED",
        "objective": optimization_plan["objective"],
        "cases": [{
            "case_id": case["id"],
            "legal_minimum": {"status": "UNKNOWN", "valid_math": "fixed by operator contract", "mandatory_bytes_by_boundary": None, "mandatory_compute": None, "reason": "work ledger not yet constructed"},
            "current_schedule": current_schedule(case), "candidates": [], "pareto_frontier": [],
        } for case in cases],
        "global_decision": {"status": "PENDING_BASELINE", "selected_schedule": None, "reason": "No timing or calibrated feasible bound exists yet.", "issued_by_role": "GLOBAL_SCHEDULER"},
        "evidence": [discovery_identity],
    }

    outputs = {
        "optimization_plan.json": optimization_plan,
        "microarchitecture_model.json": architecture,
        "microbenchmark_plan.json": microbench,
        "global_schedule_state.json": global_state,
        "experiment_queue.json": queue,
        "resource_balance.json": balance,
        "tradeoff_frontier.json": frontier,
    }
    for name, value in outputs.items():
        atomic_write(run / "models" / name, value)
    print(json.dumps({"status": "READY", "run": str(run), "artifacts": sorted(outputs), "resources": len(resources), "cases": len(cases), "requests": len(requests)}, indent=2))


if __name__ == "__main__":
    main()
