#!/usr/bin/env python3
"""Materialize candidate-first planning for the Qwen3.5 GDN layout replan.

No source is compiled and no GPU work is launched.  The only proposed probe is
an exact compiler/type-level accumulator-layout admissibility proof for N2.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


CASES = ["s256", "s384", "s404", "s512", "s640", "s768", "s1024"]
SEQUENCES = [256, 384, 404, 512, 640, 768, 1024]
WEIGHT = 1.0 / len(CASES)

# Exact scheduled dense tensor work of the frozen production pipeline.
N0_FLOP = [
    738_197_504, 1_107_296_256, 1_291_845_632, 1_476_395_008,
    1_845_493_760, 2_214_592_512, 2_952_790_016,
]
N0_PADDING_FLOP = [
    233_308_160, 316_407_808, 442_212_352, 399_507_456,
    482_607_104, 565_706_752, 731_906_048,
]
# QK-only 16x16 strict-upper/tail tile work which N1 can remove without
# changing scoreV ownership or output layout.  N2 can remove the same amount
# from both QK and scoreV, if and only if the static layout gate passes.
N1_REMOVED_FLOP = [
    25_165_824, 37_748_736, 51_380_224, 50_331_648,
    62_914_560, 75_497_472, 100_663_296,
]
N2_REMOVED_FLOP = [value * 2 for value in N1_REMOVED_FLOP]
LOGICAL_BYTES = [
    23_134_592, 34_701_696, 38_860_416, 46_268_800,
    57_835_904, 69_403_008, 92_537_216,
]

SCHEDULER = "global-scheduler-linear-v3"
SUPERVISOR = "global-supervisor-root-v3"
ANALYST = "microarchitecture-analyst-linear-v3"
EXPERIMENTER = "experiment-agent-linear-v3"
DECISION_ID = "decision-n2-layout-admissibility-v1"
REQUEST_ID = "req-n2-static-layout-admissibility"
QUANTITY_ID = "n2_zero_copy_layout_decision_value_us"

RESOURCE_KIND = {
    "tensor_compute": "TENSOR_CORE",
    "simt_compute": "SIMT",
    "conversion_pipe": "SIMT",
    "integer_address_pipe": "SIMT",
    "predicate_compute": "SIMT",
    "special_function": "SFU",
    "async_copy_engine": "TMA",
    "constant_memory_path": "REQUEST_SERVICE",
    "load_store_request": "REQUEST_SERVICE",
    "predicate_storage": "REQUEST_SERVICE",
    "register_storage": "REQUEST_SERVICE",
    "scoreboard_wait": "REQUEST_SERVICE",
    "system_register_path": "REQUEST_SERVICE",
    "tensor_issue": "REQUEST_SERVICE",
    "warp_collective": "REQUEST_SERVICE",
    "warp_issue": "REQUEST_SERVICE",
    "l1_shared_boundary": "SHARED_L1",
    "shared_bank_service": "SHARED_L1",
    "shared_memory": "SHARED_L1",
    "l2_boundary": "L2",
    "device_memory_boundary": "DEVICE_MEMORY",
    "cta_allocation": "FRONT_END",
    "instruction_front_end": "FRONT_END",
    "kernel_dispatch": "FRONT_END",
    "synchronization": "SYNCHRONIZATION",
}

# These resources can change N2 admissibility because a hidden fragment copy,
# alternate shared handoff, extra barrier, or ownership permutation is a hard
# candidate change.  Other absolute utilization unknowns cannot affect this
# static admission decision and therefore do not authorize a probe.
LAYOUT_SENSITIVE = {
    "register_storage", "tensor_compute", "tensor_issue", "warp_issue",
    "instruction_front_end", "integer_address_pipe", "predicate_compute",
    "predicate_storage", "load_store_request", "l1_shared_boundary",
    "shared_bank_service", "shared_memory", "synchronization", "cta_allocation",
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def identity(path: Path) -> dict:
    return {"path": str(path.resolve()), "sha256": sha256(path)}


def dump(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def interval(lower: float, upper: float, unit: str = "us") -> dict:
    return {"lower": lower, "upper": upper, "unit": unit}


def quantity(value: float, unit: str) -> dict:
    return {"value": value, "unit": unit}


def weighted(values: list[float]) -> float:
    return sum(values) / len(values)


def baseline_vectors(baseline: dict) -> tuple[list[float], list[float], list[float], list[float]]:
    indexed = {case["case_id"]: case for case in baseline["cases"]}
    p05 = [float(indexed[case]["gpu_active"]["p05_us"]) for case in CASES]
    median = [float(indexed[case]["gpu_active"]["median_us"]) for case in CASES]
    p95 = [float(indexed[case]["gpu_active"]["p95_us"]) for case in CASES]
    s3 = []
    for case in CASES:
        stages = indexed[case]["stage_profile"]["stages"]
        record = stages["s3_short"] or stages["s3_long"]
        s3.append(float(record["median_us"]))
    return p05, median, p95, s3


def candidate_spec(candidate: str) -> dict:
    if candidate == "N0":
        return {
            "candidate_id": "N0",
            "name": "frozen-production-baseline",
            "status": "MEASURED_BASELINE",
            "pipeline": ["s01", "s2", "s3_raw", "gated_rms_post"],
            "architectural_change": "none",
            "removed_flop_by_case": [0] * len(CASES),
        }
    if candidate == "N1":
        return {
            "candidate_id": "N1",
            "name": "qk-only-causal-tile-pruning",
            "status": "ADMISSIBLE_UNRANKED",
            "pipeline": ["s01", "s2", "s3_raw", "gated_rms_post"],
            "architectural_change": (
                "In S3 QK only, issue the 10 causal 16x16 pairs per full 64-token chunk; "
                "at S404 the 20-token tail issues exactly 3 of its 2x2 pairs."
            ),
            "removed_flop_by_case": N1_REMOVED_FLOP,
            "hard_invariants": [
                "score-times-V schedule and accumulator layout are byte-for-byte unchanged",
                "S01, S2, post, ABI, grid, block, BF16 score/raw_o boundaries are unchanged",
                "no latency benefit is assumed before production candidate A/B",
            ],
        }
    return {
        "candidate_id": "N2",
        "name": "layout-codesigned-dual-causal-tile-pruning",
        "status": "STATIC_ADMISSIBILITY_PENDING",
        "pipeline": ["s01", "s2", "s3_raw", "gated_rms_post"],
        "architectural_change": (
            "Co-design O1 state-GEMM and score-times-V ownership so each true N16 output "
            "tile is already a compatible scoreV MMA accumulator fragment."
        ),
        "removed_flop_by_case": N2_REMOVED_FLOP,
        "static_hard_gate": {
            "pass": (
                "For exact short and long production tiled-MMA objects, every logical (d,n) "
                "in each N16 tile has a bijective equal lane and equal register offset under a "
                "same-iterator view, with no alias and preserved K accumulation order."
            ),
            "reject": (
                "Any register permutation/copy, shared/global handoff, barrier, extra allocation, "
                "changed per-element K order, or changed BF16 boundary rejects N2 before materialization."
            ),
            "preferred_construction": (
                "logical_divide(real_output_fragment,(None,None,2)); select one MMA_N tile; "
                "reuse output.iterator and compare against the exact scoreV fragment layout"
            ),
        },
        "removed_flop_claim_condition": "N2 savings are conditional and have zero decision weight until the static hard gate passes.",
    }


def schedule_point(candidate: str, i: int, p05: list[float], median: list[float], p95: list[float], s3: list[float]) -> dict:
    removed = {"N0": 0, "N1": N1_REMOVED_FLOP[i], "N2": N2_REMOVED_FLOP[i]}[candidate]
    sequence = SEQUENCES[i]
    chunks = (sequence + 63) // 64
    grid = chunks * 16 if sequence <= 640 else (192 if sequence == 768 else 256)
    if candidate == "N0":
        predicted = {"status": "MEASURED", **interval(p05[i], p95[i])}
        measured = {"status": "MEASURED", "median": median[i], "unit": "us"}
        uncertainty = {"status": "MEASURED", "reason": "immutable production baseline"}
        decision = "BASELINE"
    else:
        predicted = {
            "status": "UNRANKED_NO_LATENCY_BENEFIT_ASSUMED",
            **interval(0.0, p95[i] + s3[i]),
            "note": "decision window only; not a silicon performance bound",
        }
        measured = {"status": "NOT_MEASURED", "median": None, "unit": "us"}
        uncertainty = {
            "status": "STATIC_GATE_PENDING" if candidate == "N2" else "PRODUCTION_AB_REQUIRED",
            "reason": "scheduled FLOP removal does not determine latency under issue/control/resource coupling",
        }
        decision = "CONDITIONAL_CANDIDATE"
    return {
        "schedule_id": candidate,
        "correctness": {
            "status": "PASS" if candidate == "N0" else "PENDING",
            "semantic_boundaries": ["BF16_score", "BF16_raw_o", "independent_gated_RMS_post"],
        },
        "valid_compute": {
            "dense_tensor_flop": N0_FLOP[i] - removed,
            "removed_vs_n0_flop": removed,
            "status": "EXACT_SCHEDULED_TILE_WORK" if candidate != "N2" else "CONDITIONAL_ON_STATIC_GATE",
        },
        "padded_compute": {
            "dense_tensor_flop": N0_PADDING_FLOP[i] - removed,
            "status": "EXPLICIT_16x16_TILE_GRANULARITY",
        },
        "bytes_by_boundary": {
            "logical_request_bytes": LOGICAL_BYTES[i],
            "global_bytes_change_vs_n0": 0,
            "physical_transactions": "UNKNOWN_NOT_NEEDED_FOR_STATIC_ADMISSION",
        },
        "allocation": {
            "grid": grid,
            "block": 512 if sequence <= 640 else 256,
            "unchanged_from_n0": candidate != "N0",
            "hard_gate": "no spill and no resource-cap regression",
        },
        "device_coverage": {
            "sm_count": 170,
            "one_wave_grid_fraction": min(1.0, grid / 170.0),
            "status": "GEOMETRIC_BOUND_NOT_UTILIZATION",
        },
        "synchronization": {
            "kernel_count": 4,
            "cross_kernel_edges": ["s01_to_s2", "s2_to_s3", "s3_to_post"],
            "candidate_extra_barriers": 0,
        },
        "predicted_dag_us": predicted,
        "measured_us": measured,
        "uncertainty": uncertainty,
        "decision": decision,
    }


def resource_row(resource: str, i: int, decision_value: float, baseline_case: dict) -> dict:
    kind = RESOURCE_KIND[resource]
    if resource == "tensor_compute":
        mandatory = quantity(N0_FLOP[i] - N0_PADDING_FLOP[i], "dense_tensor_flop")
        actual = quantity(N0_FLOP[i], "dense_tensor_flop")
    elif resource in {"device_memory_boundary", "l2_boundary"}:
        mandatory = quantity(LOGICAL_BYTES[i], "logical_bytes")
        actual = quantity(LOGICAL_BYTES[i], "logical_bytes")
    elif resource == "kernel_dispatch":
        mandatory = quantity(4, "kernel_launch")
        actual = quantity(4, "kernel_launch")
    else:
        mandatory = quantity(0, "unresolved_dynamic_service_unit")
        actual = quantity(0, "unresolved_dynamic_service_unit")
    sensitive = resource in LAYOUT_SENSITIVE
    row = {
        "resource_id": resource,
        "resource_kind": kind,
        "material": True,
        "mandatory_work": mandatory,
        "actual_work": actual,
        "production_point": {
            "case_id": CASES[i],
            "gpu_active_median_us": baseline_case["gpu_active"]["median_us"],
            "n0_flop": N0_FLOP[i],
            "n1_flop": N0_FLOP[i] - N1_REMOVED_FLOP[i],
            "n2_flop_if_admitted": N0_FLOP[i] - N2_REMOVED_FLOP[i],
        },
        "matched_saturation": {"status": "UNKNOWN", "value": None, "unit": None, "conditions": []},
        "utilization": {
            "status": "UNKNOWN", "value_percent": None,
            "numerator": None, "denominator": None,
            "time_window": "production_graph_device_elapsed",
            "boundary": kind,
        },
        "critical_path": {
            "status": "UNKNOWN", "contribution_us": None,
            "probability": 0.5 if sensitive else 0.0,
            "coupling_model": (
                "N2 static zero-copy admissibility" if sensitive
                else "absolute service unknown cannot change static N2 admissibility"
            ),
        },
        "non_saturation_causes": ["NOT_ESTABLISHED"],
        "evidence": [],
        "unresolved_request_ids": [REQUEST_ID] if sensitive else [],
        "decision_relevance": {
            "status": "TOP_TWO_SENSITIVE" if sensitive else "NOT_TOP_TWO_SENSITIVE",
            "decision_contract_ids": [DECISION_ID] if sensitive else [],
            "explanation": (
                "A hidden transport/allocation/issue dependency rejects N2."
                if sensitive else
                "N0/N1/N2 preserve this boundary for the static admission decision; quantify only after final Top2 is frozen."
            ),
        },
    }
    if kind == "TENSOR_CORE":
        row["compute_efficiency"] = {
            "device_coverage": None,
            "eligible_time_fraction": None,
            "eligible_window_issue_efficiency": None,
            "composition_status": "UNKNOWN",
        }
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    run = args.run.resolve()
    models = run / "models"
    if not (run / "run_state.json").is_file():
        raise ValueError(f"not an optimization run: {run}")
    now = datetime.now(timezone.utc).isoformat()

    baseline = json.loads((models / "baseline.json").read_text())
    baseline_cases = {case["case_id"]: case for case in baseline["cases"]}
    p05, median, p95, s3 = baseline_vectors(baseline)
    weighted_s3 = weighted(s3)
    weighted_p05 = weighted(p05)
    weighted_median = weighted(median)
    weighted_p95 = weighted(p95)

    discovery = json.loads((models / "resource_discovery.json").read_text())
    resources = list(discovery["required_resource_ids"])
    missing_kinds = sorted(set(resources) - set(RESOURCE_KIND))
    if missing_kinds:
        raise ValueError(f"resource kind mapping missing: {missing_kinds}")

    baseline_id = identity(models / "baseline.json")
    operator_id = identity(run / "operator.json")
    workload_id = identity(run / "workload.json")
    hardware_id = identity(run / "hardware.json")
    hardware_evidence_id = identity(run / "hardware_evidence.json")
    discovery_id = identity(models / "resource_discovery.json")
    p0_id = identity(run / "experiments/p0-reused/p0_receipt.json")
    binary_id = identity(run / "static/baseline_s404_composite.cubin")
    sass_id = identity(run / "static/final.sass")

    objective = {
        "schema_version": "registered-objective-v1",
        "objective_id": "qwen35-gdn-prefill-equal-weight-device-execution-v3",
        "metric": "equal-weight mean of per-shape production-exact four-kernel GPU device-elapsed medians",
        "unit": "us", "direction": "minimize",
        "workload_cases": [{"case_id": case, "weight": WEIGHT} for case in CASES],
        "measurement_semantics": {
            "primary": "CUDA-event device elapsed after P0; CPU dispatch is reported separately",
            "static_gate": "compiler/type-level proof has no GPU timing and may only admit or reject N2",
            "transfer_gate": "future performance acceptance requires paired graph and direct-execution agreement",
        },
        "decision_indifference_band_us": 0.10,
        "created_at": now,
    }
    objective_path = models / "objective.json"
    dump(objective_path, objective)

    candidates_dir = models / "architecture_candidates"
    candidate_paths = {}
    for candidate in ("N0", "N1", "N2"):
        path = candidates_dir / f"{candidate.lower()}.json"
        dump(path, candidate_spec(candidate))
        candidate_paths[candidate] = path

    frontier_cases = []
    for i, case in enumerate(CASES):
        frontier_cases.append({
            "case_id": case,
            "legal_minimum": {
                "dense_tensor_flop": N0_FLOP[i] - N0_PADDING_FLOP[i],
                "tile_feasible_n1_flop": N0_FLOP[i] - N1_REMOVED_FLOP[i],
                "tile_feasible_n2_flop_if_static_gate_passes": N0_FLOP[i] - N2_REMOVED_FLOP[i],
                "note": "mathematical minimum, realizable tile work and measured latency are distinct quantities",
            },
            "current_schedule": schedule_point("N0", i, p05, median, p95, s3),
            "candidates": [
                schedule_point("N1", i, p05, median, p95, s3),
                schedule_point("N2", i, p05, median, p95, s3),
            ],
            "pareto_frontier": ["N0", "N1", "N2_CONDITIONAL_ON_STATIC_GATE"],
        })
    frontier = {
        "schema_version": "tradeoff-frontier-v1", "status": "INITIALIZED",
        "objective": objective, "cases": frontier_cases,
        "global_decision": {
            "status": "STATIC_ADMISSION_PENDING", "selected_schedule": None,
            "reason": "N2 must pass exact zero-copy layout proof before final Top2 performance ranking.",
            "issued_by_role": "GLOBAL_SCHEDULER",
        },
        "evidence": [baseline_id, operator_id, workload_id],
    }
    frontier_path = models / "tradeoff_frontier.json"
    dump(frontier_path, frontier)

    decision = {
        "schema_version": "decision-contract-v1", "decision_id": DECISION_ID,
        "status": "READY_FOR_SUPERVISOR",
        "issued_by": {"role": "GLOBAL_SCHEDULER", "owner_id": SCHEDULER},
        "objective_identity": identity(objective_path),
        "frontier_identity": identity(frontier_path),
        "candidate_bindings": [
            {"candidate_id": "N0", "artifact_identity": identity(candidate_paths["N0"]), "predicted_objective": interval(weighted_p05, weighted_p95)},
            {"candidate_id": "N1", "artifact_identity": identity(candidate_paths["N1"]), "predicted_objective": interval(0.0, weighted_p95 + weighted_s3)},
            {"candidate_id": "N2", "artifact_identity": identity(candidate_paths["N2"]), "predicted_objective": interval(0.0, weighted_p95 + weighted_s3)},
        ],
        "top_two_candidate_ids": ["N2", "N0"],
        "decision_metric": {"name": objective["metric"], "unit": "us", "direction": "minimize"},
        "measurement_need": {
            "quantity_id": QUANTITY_ID,
            "model_location": "models/tradeoff_frontier.json::N2 static admissibility",
            "equation": f"x={weighted_s3:.12f} us if exact zero-copy layout proof passes, else x=0",
            "current_interval": interval(0.0, weighted_s3),
            "top_two_delta_interval": interval(-weighted_s3, weighted_s3),
            "decision_boundary": quantity(0.0, "us"),
            "required_precision": quantity(0.10, "us"),
            "outcome_mapping": [
                {"condition": "exact short+long lane/register bijection and no-launch compile pass", "outcome": "ADMIT_N2_TO_BOUND_RANKING"},
                {"condition": "any alias, owner/offset mismatch, copy/traffic/barrier or compile failure", "outcome": "REJECT_N2_BEFORE_MATERIALIZATION"},
            ],
            "maximum_decision_value": quantity(weighted_s3, "us"),
            "decision_flip_probability": 0.5,
            "expected_uncertainty_reduction": 1.0,
        },
        "experiment_budget": {
            "screening": {"max_configurations": 3, "max_samples_per_configuration": 1, "max_process_launches": 6, "max_wall_clock_minutes": 15},
            "qualification": {"max_configurations": 14, "max_samples_per_configuration": 31, "max_process_launches": 21, "max_wall_clock_minutes": 60},
            "max_revisions": 1,
        },
        "stop_rules": [
            "The static proof may admit or reject N2; it cannot claim a latency speedup.",
            "Any hidden transport, changed accumulation order/BF16 boundary, or resource-cap regression rejects N2.",
            "No GPU launch or production source mutation is authorized by this decision.",
            "After disposition, rebuild bounds and freeze one final Top2 plus one ranking-flip uncertainty under a fresh contract.",
        ],
        "evidence": [baseline_id, discovery_id, binary_id, sass_id],
    }
    decision_path = models / "decision_contract.json"
    dump(decision_path, decision)

    measurability = {
        "schema_version": "measurability-contract-v1", "status": "READY_FOR_SUPERVISOR",
        "issued_by": {"role": "MICROARCHITECTURE_ANALYST", "analyst_id": ANALYST},
        "decision_contract_identity": identity(decision_path),
        "quantity_id": QUANTITY_ID,
        "identifiability": "ATOMIC_IDENTIFIABLE",
        "selected_method": "ATOMIC_MICROBENCH",
        "observable": {
            "name": "exact per-lane logical (d,n) to accumulator register-offset equality for N16 views",
            "unit": "us decision value (binary static predicate)",
            "measurement_window": "CuTe JIT compiler/type construction only; kernel launch and GPU timing are forbidden",
        },
        "causal_mapping": {
            "formula": f"proof_pass maps to {weighted_s3:.12f} us decision value; proof_fail maps to 0",
            "assumptions": [
                "exact production short and long tiled-MMA objects are instantiated",
                "the view reuses the existing output iterator",
            ],
            "confounders": ["make_fragment_C allocation mistaken for a view", "logical coordinates mistaken for per-thread fragment coordinates"],
            "controls": [
                "compare owner lane, register offset, alias cardinality and layout equality for every N16 tile",
                "compile/type-check without launch",
                "reject any explicit copy, shared/global handoff, barrier or changed K order",
            ],
            "falsification_condition": "any short/long tile lacks a bijective same-owner same-offset view or compilation fails",
        },
        "expected_precision": {"absolute": 0.0 + 1e-12, "unit": "us"},
        "required_tier": "SCREENING",
        "evidence": [],
    }
    measurability_path = models / "measurability_contract.json"
    dump(measurability_path, measurability)

    request_resources = sorted(LAYOUT_SENSITIVE)
    request = {
        "request_id": REQUEST_ID, "status": "PROPOSED", "issued_by_role": "GLOBAL_SCHEDULER",
        "workload_cases": CASES,
        "model_field": "N2 static admissibility before candidate performance ranking",
        "candidate_decision": "Admit or reject N2; retain N0 and N1 regardless.",
        "causal_question": "Does the exact production accumulator admit a same-iterator N16 scoreV MMA view with no transport or ordering change?",
        "decision_contract": identity(decision_path),
        "measurability_contract": identity(measurability_path),
        "experiment_class": "SCREENING", "tested_candidate_ids": ["N2", "N0"],
        "implementation_owner": {"role": "EXPERIMENT_AGENT", "actor_id": EXPERIMENTER},
        "resource_ids": request_resources, "affected_stage_ids": ["s3"], "priority": 0,
        "sensitivity": {
            "candidate_specific_decision_value_us": weighted_s3,
            "decision_flip_probability": 0.5,
            "expected_uncertainty_reduction": 1.0,
            "experiment_cost": "LOW", "experiment_cost_weight": 1.0,
            "ranking_score": weighted_s3 * 0.5,
        },
        "controls": [
            "No CUDA launch, timing sample, production source edit or candidate performance claim.",
            "Instantiate exact short and long production tiled-MMA types.",
            "Use logical_divide on the actual MMA_N fragment mode and reuse the same iterator.",
            "Enumerate lane/register mapping and reject alias, owner or offset mismatch.",
            "Treat make_fragment_C as prototype only; it may not replace the existing accumulator storage.",
        ],
        "measurement_contract": {
            "primary": "binary compiler/type-level pass/fail",
            "decision_precedence": ["compile failure -> reject N2", "mapping mismatch -> reject N2", "all exact checks pass -> admit N2 to bound ranking"],
            "gpu_launches": 0, "performance_samples": 0,
        },
        "expected_sass": ["NOT_APPLICABLE_STATIC_GATE; candidate SASS is required only after N2 admission"],
        "catalog_resolution": {
            "catalog_queried": False,
            "query": {"mechanisms": ["cute_accumulator_same_iterator_view"], "resources": request_resources, "qualification": "STATIC_VALIDATED"},
            "decision": None, "package_id": None, "reason": "deterministic catalog query pending materialization",
        },
        "result_binding": {"status": "PENDING", "target": "models/tradeoff_frontier.json::N2"},
        "promotion_disposition": {"status": "PENDING", "reason": "review genericity only after a resolved static proof"},
    }
    catalog = run.parents[1] / "microbench/catalog.json"
    queue = {
        "schema_version": "experiment-request-queue-v2", "status": "EXECUTABLE",
        "ranking_policy": {
            "formula": "candidate_specific_decision_value_us * decision_flip_probability * expected_uncertainty_reduction / experiment_cost_weight",
            "benefit_bound": "current measured weighted S3 device time; no candidate speedup assumed",
            "issued_by_role": "GLOBAL_SCHEDULER", "ranked_at": now,
        },
        "requests": [request],
        "catalog_snapshot": {"status": "PENDING_QUERY", "catalog_identity": identity(catalog), "request_receipts": []},
        "promotion_review": [],
    }
    dump(models / "experiment_queue.json", queue)

    stage_ids = ["s01", "s2", "s3", "post"]
    global_state = {
        "schema_version": "global-schedule-state-v2", "status": "PLANNED",
        "owner": {"role": "GLOBAL_SCHEDULER", "owner_id": SCHEDULER, "exclusive_authority": ["RANK_EXPERIMENTS", "CLOSE_RESOURCE_MODEL", "ACCEPT_GLOBAL_CANDIDATE", "AUTHORIZE_LIMIT_REPORT"]},
        "supervisor": {"role": "GLOBAL_SUPERVISOR", "owner_id": SUPERVISOR, "exclusive_authority": ["VETO_EXPERIMENT", "APPROVE_EXPERIMENT_DISPATCH", "ENFORCE_BUDGET", "HALT_AND_REPLAN"], "must_be_distinct_from": ["GLOBAL_SCHEDULER", "MICROARCHITECTURE_ANALYST", "EXPERIMENT_AGENT"]},
        "material_resources": resources,
        "stage_assignments": [{"resource_id": resource, "stage_ids": stage_ids} for resource in resources],
        "owned_artifacts": {"resource_balance": "models/resource_balance.json", "tradeoff_frontier": "models/tradeoff_frontier.json", "experiment_queue": "models/experiment_queue.json", "schedule_model": "models/schedule_model.json"},
        "decision_policy": {"candidate_driven_experiments_only": True, "unknown_does_not_imply_measure": True, "local_speedup_is_not_global_acceptance": True, "objective": objective, "ranking": queue["ranking_policy"]["formula"], "supervisor_approval_required": True},
        "human_report_gate": {"status": "BLOCKED", "requires": ["N2 static disposition", "final Top2 performance decision", "validated resource balance"]},
        "revision_history": [{"revision": 1, "at": now, "reason": "Fresh N0/N1/N2 layout replan; no old candidate budget or approval inherited."}],
    }
    dump(models / "global_schedule_state.json", global_state)

    balance_cases = []
    for i, case in enumerate(CASES):
        baseline_case = baseline_cases[case]
        sequence = SEQUENCES[i]
        chunks = (sequence + 63) // 64
        grid = chunks * 16 if sequence <= 640 else (192 if sequence == 768 else 256)
        balance_cases.append({
            "case_id": case,
            "resource_rows": [resource_row(resource, i, weighted_s3, baseline_case) for resource in resources],
            "device_coverage": {"sm_count": 170, "s3_grid_cta": grid, "geometric_grid_over_sm": grid / 170.0, "status": "BOUNDED_NOT_UTILIZATION"},
            "critical_path": {"status": "MEASURED_BASELINE", "total_us": median[i], "stage_gpu_active_us": {"s3": s3[i]}, "note": "stage is separate CUPTI diagnostic; total is graph device elapsed"},
            "model_residual": {"status": "UNKNOWN", "reason": "no candidate timing model before static admission"},
        })
    balance = {
        "schema_version": "resource-balance-ledger-v2", "status": "INITIALIZED",
        "cases": balance_cases,
        "cross_resource_coupling": [{"coupling": "fragment ownership -> register transport/shared/barrier/front-end", "request_id": REQUEST_ID}],
        "unresolved_material_resources": sorted(LAYOUT_SENSITIVE),
        "evidence": [baseline_id, discovery_id],
    }
    dump(models / "resource_balance.json", balance)

    architecture = {
        "schema_version": "microarchitecture-model-v1", "status": "INITIALIZED",
        "target_identity": {"vendor": "NVIDIA", "device": "NVIDIA GeForce RTX 5090", "compute_capability": "12.0", "architecture": "sm_120", "device_index": 6, "sm_count": 170},
        "scope": "resources observed in the exact production S404 composite cubin plus official target resources",
        "resource_nodes": discovery["resource_nodes"],
        "resource_edges": [{"from": "register_storage", "to": "tensor_compute", "status": "N2_STATIC_LAYOUT_UNRESOLVED"}, {"from": "shared_memory", "to": "tensor_compute", "status": "FORBIDDEN_N2_FALLBACK"}],
        "allocation_constraints": [{"resource": "cta_allocation", "sm_count": 170, "evidence": hardware_evidence_id}],
        "service_curves": [{"status": "UNKNOWN", "reason": "defer service calibration until the final Top2 has one ranking-sensitive resource"}],
        "latency_constraints": [{"status": "UNKNOWN", "reason": "not needed to resolve the exact static layout predicate"}],
        "workload_mappings": [{"case_id": case, "sequence": sequence, "n0_flop": N0_FLOP[i], "n1_removed_flop": N1_REMOVED_FLOP[i], "n2_removed_flop_if_admitted": N2_REMOVED_FLOP[i], "logical_bytes_unchanged": LOGICAL_BYTES[i]} for i, (case, sequence) in enumerate(zip(CASES, SEQUENCES))],
        "overlap_constraints": [{"status": "UNCHANGED_BY_STATIC_GATE", "scope": "four-kernel topology"}],
        "unknowns": [{"quantity_id": "exact_o1_n16_fragment_view", "request_id": REQUEST_ID, "decision_relevance": "N2 admission"}],
        "evidence": [hardware_id, hardware_evidence_id, discovery_id, binary_id, sass_id],
    }
    dump(models / "microarchitecture_model.json", architecture)

    ledger_cases = []
    for i, case in enumerate(CASES):
        ledger_cases.append({
            "case_id": case,
            "valid_work": {"mathematical_dense_tensor_flop": N0_FLOP[i] - N0_PADDING_FLOP[i], "n0_scheduled_flop": N0_FLOP[i], "n1_scheduled_flop": N0_FLOP[i] - N1_REMOVED_FLOP[i], "n2_scheduled_flop_if_admitted": N0_FLOP[i] - N2_REMOVED_FLOP[i], "logical_boundary_bytes": LOGICAL_BYTES[i]},
            "padded_or_redundant_work": {"n0_flop": N0_PADDING_FLOP[i], "n1_flop": N0_PADDING_FLOP[i] - N1_REMOVED_FLOP[i], "n2_flop_if_admitted": N0_PADDING_FLOP[i] - N2_REMOVED_FLOP[i], "qk_removed_flop": N1_REMOVED_FLOP[i], "scorev_removed_flop_if_admitted": N1_REMOVED_FLOP[i]},
            "assumptions": ["m16n16 tile work counts 2*M*N*K dense tensor FLOP", "N1/N2 preserve all global tensor boundaries", "N2 scoreV saving is conditional on exact zero-copy layout proof"],
            "evidence": [operator_id, workload_id],
        })
    ledger = {"schema_version": "mandatory-work-ledger-v1", "workload_case": None, "cases": ledger_cases, "valid_work": {"cases": CASES}, "padded_or_redundant_work": {"classification": "16x16 causal upper/tail tile work"}, "assumptions": ["B=1,H=16,D=128,chunk=64,BF16 boundaries frozen"], "evidence": [operator_id, workload_id]}
    dump(models / "work_ledger.json", ledger)

    critical_paths = []
    for i, case in enumerate(CASES):
        stages = baseline_cases[case]["stage_profile"]["stages"]
        critical_paths.append({"case_id": case, "production_order": ["s01", "s2", "s3", "post"], "acceptance_gpu_graph_median_us": median[i], "separate_cupti_stage_median_us": {key: ((value or {}).get("median_us") if value else None) for key, value in stages.items()}, "measurement_semantics": "CUPTI stage values are diagnostic; graph median is acceptance timing"})
    dag = {
        "schema_version": "operator-dag-v1",
        "nodes": [{"node_id": "inputs", "meaning": "Q/K/V/g/beta/decay/RMS weights"}, {"node_id": "s01", "meaning": "QK norm, decay and chunk-local transforms"}, {"node_id": "s2", "meaning": "chunk recurrent state propagation"}, {"node_id": "s3", "meaning": "state contribution plus local causal scoreV"}, {"node_id": "post", "meaning": "gated RMS normalization"}, {"node_id": "output", "meaning": "BF16 output"}],
        "mathematical_edges": [{"from": "inputs", "to": "s01"}, {"from": "s01", "to": "s2"}, {"from": "s01", "to": "s3"}, {"from": "s2", "to": "s3"}, {"from": "s3", "to": "post"}, {"from": "post", "to": "output"}],
        "schedule_only_edges": [{"from": "s3_O1_accumulator", "to": "s3_scoreV_accumulator", "candidate": "N2", "requirement": "same iterator, lane and register offset; no transport edge"}],
        "resource_constraints": [{"request_id": REQUEST_ID, "resource_ids": sorted(LAYOUT_SENSITIVE), "status": "STATIC_ADMISSIBILITY_PENDING"}],
        "critical_paths": critical_paths,
        "unproven_edges": [{"edge": "O1_N64_fragment_to_scoreV_N16_fragment", "unknown": "zero-copy same-owner same-offset view exists for exact short and long layouts", "request_id": REQUEST_ID}],
    }
    dump(models / "dag.json", dag)

    schedule = {
        "schema_version": "resource-schedule-model-v1", "status": "INITIALIZED",
        "binary_identity": binary_id,
        "sass_control_flow": [{"scope": "N0 exact baseline", "sass_identity": sass_id, "status": "STATIC_CLASSIFIED"}],
        "dynamic_instruction_method": {"status": "DEFERRED", "reason": "N2 is not admitted; static site counts cannot be treated as dynamic work"},
        "resource_mapping": [{"resource_id": resource, "status": "DISCOVERED_FROM_FINAL_BINARY"} for resource in resources],
        "dependency_graph": [{"from": "O1_accumulator", "to": "scoreV_accumulator", "status": "STATIC_VIEW_GATE"}],
        "workload_cases": [{"case_id": case, "dynamic_instruction_work": {"status": "UNKNOWN"}, "bounds": {"silicon_lower": {"status": "UNKNOWN"}, "resource_service": {"status": "UNKNOWN"}, "dependency": {"status": "STATIC_GATE_PENDING"}, "feasible_schedule": {"status": "N0_MEASURED_N1_N2_UNRANKED"}}, "predicted_production_us": {"n0_median": median[i], "n1": None, "n2": None}, "uncertainty": {"single_quantity": "N2 zero-copy layout admissibility"}} for i, case in enumerate(CASES)],
        "coupled_resource_models": [{"resources": sorted(LAYOUT_SENSITIVE), "request_id": REQUEST_ID}],
        "unknown_scheduler_or_cache_behavior": ["deferred because it cannot alter the compiler/type-level N2 gate"],
        "evidence": [binary_id, sass_id, discovery_id],
    }
    dump(models / "schedule_model.json", schedule)

    microbench = json.loads((models / "microbenchmark_plan.json").read_text())
    microbench.update({
        "status": "EXECUTABLE",
        "target_questions": [{"quantity_id": QUANTITY_ID, "question": request["causal_question"], "method": "COMPILER_TYPE_LAYOUT_PROOF_NO_GPU"}],
        "coupling_tests": [{"request_id": REQUEST_ID, "coupling": "accumulator lane/register ownership across O1 and scoreV tiled MMA"}],
        "cross_layer_prediction_gates": [{"gate": "Static proof may only change N2 admissibility; no latency prediction or acceptance.", "status": "ENFORCED"}],
        "unresolved_questions": [],
    })
    microbench["levels"]["P1"] = {"required": True, "status": "PLANNED", "reason": "exact static layout predicate", "experiments": [REQUEST_ID], "evidence": []}
    microbench["levels"]["P2"] = {"required": False, "status": "NOT_APPLICABLE", "reason": "no dynamic coupling claim is made by the static admission gate", "experiments": [], "evidence": []}
    microbench["levels"]["P3"] = {"required": True, "status": "DEFERRED_UNTIL_FINAL_TOP2", "reason": "production candidate A/B only after N2 disposition and bound ranking", "experiments": [], "evidence": []}
    microbench["levels"]["P4"] = {"required": True, "status": "DEFERRED_UNTIL_CANDIDATE_SELECTION", "reason": "production validation is not part of static admission", "experiments": [], "evidence": []}
    dump(models / "microbenchmark_plan.json", microbench)

    plan = {
        "schema_version": "optimization-plan-v1", "status": "EXECUTABLE", "objective": objective,
        "global_scheduler_owner": SCHEDULER, "global_supervisor_owner": SUPERVISOR,
        "candidate_limit": 3,
        "screening_budget": decision["experiment_budget"]["screening"],
        "qualification_budget": decision["experiment_budget"]["qualification"],
        "max_revisions_per_decision": 1,
        "experiment_queue": [REQUEST_ID],
        "correctness_gates": ["N0 semantics are frozen", "N1/N2 preserve per-element accumulation order and BF16 score/raw_o boundaries", "S404 20-token tail is explicit"],
        "evidence_gates": ["exact production short and long CuTe layouts", "same-iterator lane/register bijection", "no copy, traffic, barrier, spill or allocation regression", "fresh decision contract after static disposition"],
        "model_error_tolerances_percent": {"p1_p2_to_p3": 10.0, "schedule_to_p4": 10.0, "achieved_to_feasible_bound": 15.0},
        "acceptance_rule": "The current request may only admit/reject N2; it cannot accept a production candidate.",
        "stop_criteria": decision["stop_rules"],
        "revision_history": [{"revision": 1, "at": now, "reason": "Fresh candidate-first layout replan after old C1 rejection."}],
        "workload_priorities": [{"case_id": case, "rank": i, "reason": ("tail/static-layout anchor" if case == "s404" else "equal-weight production coverage")} for i, case in enumerate(["s404", "s1024", "s256", "s640", "s768", "s384", "s512"])],
        "baseline_identities": [baseline_id, operator_id, workload_id, hardware_id, p0_id],
        "open_uncertainties": [{"quantity_id": QUANTITY_ID, "decision_contract": identity(decision_path)}],
    }
    dump(models / "optimization_plan.json", plan)

    receipt = {
        "schema_version": "layout-replan-planning-v1", "status": "PASS", "created_at": now,
        "candidate_ids": ["N0", "N1", "N2"], "proposed_request_ids": [REQUEST_ID],
        "gpu_launches": 0, "performance_samples": 0,
        "artifacts": {path.name: identity(path) for path in [objective_path, frontier_path, decision_path, measurability_path, models / "experiment_queue.json", models / "global_schedule_state.json", models / "resource_balance.json", models / "microarchitecture_model.json", models / "work_ledger.json", models / "dag.json", models / "schedule_model.json", models / "microbenchmark_plan.json", models / "optimization_plan.json"]},
    }
    dump(run / "traces/layout_replan_planning.json", receipt)
    print(json.dumps({"status": "PASS", "run": str(run), "weighted_baseline_us": weighted_median, "weighted_s3_decision_value_us": weighted_s3, "request": REQUEST_ID}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
