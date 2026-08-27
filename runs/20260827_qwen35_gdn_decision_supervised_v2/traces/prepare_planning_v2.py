#!/usr/bin/env python3
"""Materialize the corrected candidate-first PLANNING artifacts for one frozen run.

This script only writes inside the explicitly supplied run directory.  It does
not compile, launch CUDA work, or modify production sources.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


CASES = ["s256", "s384", "s404", "s512", "s640", "s768", "s1024"]
SEQUENCES = [256, 384, 404, 512, 640, 768, 1024]
WEIGHT = 1.0 / 7.0

C0_FLOP = [
    738_197_504,
    1_107_296_256,
    1_291_845_632,
    1_476_395_008,
    1_845_493_760,
    2_214_592_512,
    2_952_790_016,
]
TILE_FEASIBLE_REMOVED_FLOP = [
    50_331_648,
    75_497_472,
    102_760_448,
    100_663_296,
    125_829_120,
    150_994_944,
    201_326_592,
]
LOGICAL_BYTES = [
    23_134_592,
    34_701_696,
    38_860_416,
    46_268_800,
    57_835_904,
    69_403_008,
    92_537_216,
]
C2_LOGICAL_BYTES = [
    21_037_440,
    31_555_968,
    35_550_848,
    42_074_496,
    52_593_024,
    63_111_552,
    84_148_608,
]
GPU_P05 = [26.6240, 28.7760, 28.8265, 30.8930, 34.9220, 46.4240, 51.3100]
GPU_MEDIAN = [26.6680, 28.8195, 28.8670, 30.9555, 34.9365, 46.9080, 51.3470]
GPU_P95 = [26.7065, 28.8410, 28.9510, 31.0320, 34.9600, 47.1425, 51.3835]
S3_STAGE_US = [7.8725, 8.0000, 8.0640, 8.1760, 8.4170, 11.0070, 11.1360]
C2_INTERVAL = [37.7859, 38.9287]
C0_TOTAL_PADDING_FLOP = [233_308_160, 316_407_808, 442_212_352, 399_507_456, 482_607_104, 565_706_752, 731_906_048]
C1_S3_SCHEDULED_FLOP = [218_103_808, 327_155_712, 367_001_600, 436_207_616, 545_259_520, 654_311_424, 872_415_232]
C1_S3_PADDING_FLOP = [15_728_640, 23_592_960, 51_232_768, 31_457_280, 39_321_600, 47_185_920, 62_914_560]
C1_TOTAL_PADDING_FLOP = [182_976_512, 240_910_336, 339_451_904, 298_844_160, 356_777_984, 414_711_808, 530_579_456]
C1_OPERATIONAL_LOWER_US = [23.4035, 25.4755, 25.4750, 27.6755, 31.7360, 42.9410, 47.2830]
C1_REGRESSION_CAP_US = [34.5405, 36.8195, 36.9310, 39.1315, 43.3535, 57.9150, 62.4830]

SCHEDULER_ID = "global-scheduler-linear-v2"
SUPERVISOR_ID = "global-supervisor-root-v2"
ANALYST_ID = "microarchitecture-analyst-linear-v2"
EXPERIMENTER_ID = "experiment-agent-linear-v2"
DECISION_ID = "decision-s3-tile-causal-v2"
REQUEST_ID = "req-s3-tile-causal-production-ab"
QUANTITY_ID = "weighted_full_pipeline_candidate_delta_c1_minus_c0"


def dump(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def identity(path: Path) -> dict:
    return {"path": str(path.resolve()), "sha256": sha256(path)}


def quantity(value: float | int, unit: str) -> dict:
    return {"value": value, "unit": unit}


def interval(lower: float, upper: float, unit: str = "us") -> dict:
    return {"lower": lower, "upper": upper, "unit": unit}


def weighted(values: list[float]) -> float:
    return sum(values) / len(values)


def schedule_point(
    schedule_id: str,
    case_index: int,
    *,
    flop: int,
    logical_bytes: int,
    predicted: dict,
    measured: dict,
    decision: str,
    padded_flop: int,
) -> dict:
    sequence = SEQUENCES[case_index]
    chunks = (sequence + 63) // 64
    short = sequence <= 640
    return {
        "schedule_id": schedule_id,
        "correctness": {
            "status": "PASS" if schedule_id in {"C0", "C2"} else "PENDING",
            "semantic_boundaries": ["BF16 score", "BF16 raw_o", "independent gated RMS post"],
        },
        "valid_compute": {"dense_tensor_flop": flop, "status": "EXACT_SCHEDULED_TILE_WORK"},
        "padded_compute": {
            "dense_tensor_flop": padded_flop,
            "status": "EXPLICIT_16x16_TILE_GRANULARITY",
        },
        "bytes_by_boundary": {
            "logical_request_bytes": logical_bytes,
            "global_bytes_change_vs_c0": logical_bytes - LOGICAL_BYTES[case_index],
            "physical_transactions": "UNKNOWN",
        },
        "allocation": {
            "grid": chunks * 16 if short else (192 if sequence == 768 else 256),
            "block": 512 if short else 256,
            "candidate_constraints": {
                "short_registers_per_thread_max": 126,
                "short_shared_bytes_max": 73984,
                "long_registers_per_thread_max": 128,
                "long_shared_bytes_max": 49408,
                "stack_and_spill_bytes": 0,
            },
        },
        "device_coverage": {
            "sm_count": 170,
            "one_wave_grid_fraction": min(1.0, (chunks * 16) / 170.0),
            "status": "GEOMETRIC_BOUND_NOT_UTILIZATION",
        },
        "synchronization": {
            "kernel_count": 4 if schedule_id != "C2" else 3,
            "cross_kernel_edges": ["s01_to_s2", "s2_to_s3", "s3_to_post"] if schedule_id != "C2" else ["s01_to_s2", "s2_to_s3post"],
        },
        "predicted_dag_us": predicted,
        "measured_us": measured,
        "uncertainty": {
            "status": "MEASURED" if schedule_id == "C0" else ("BOUNDED" if schedule_id == "C2" else "UNKNOWN"),
            "reason": "C1 control/address/register/issue coupling can cause positive regression; no zero-regression assumption is allowed.",
        },
        "decision": decision,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True)
    args = parser.parse_args()
    run = Path(args.run).resolve()
    models = run / "models"
    if not (run / "run_state.json").is_file():
        raise SystemExit(f"not an optimization run: {run}")

    now = datetime.now(timezone.utc).isoformat()
    archive = run / "traces" / "planning_draft_before_candidate_v2"
    archive.mkdir(parents=True, exist_ok=True)
    for name in (
        "optimization_plan.json",
        "global_schedule_state.json",
        "resource_balance.json",
        "tradeoff_frontier.json",
        "experiment_queue.json",
        "microarchitecture_model.json",
        "microbenchmark_plan.json",
    ):
        source = models / name
        target = archive / name
        if source.is_file() and not target.exists():
            shutil.copy2(source, target)

    baseline_id = identity(models / "baseline.json")
    discovery_id = identity(models / "resource_discovery.json")
    p0_id = identity(run / "experiments" / "p0-reused" / "p0_receipt.json")
    operator_id = identity(run / "operator.json")
    workload_id = identity(run / "workload.json")
    hardware_id = identity(run / "hardware.json")
    discovery = json.loads((models / "resource_discovery.json").read_text())
    resources = list(discovery["required_resource_ids"])

    objective = {
        "schema_version": "registered-objective-v1",
        "objective_id": "qwen35-gdn-prefill-equal-weight-device-execution-v2",
        "metric": "equal-weight mean of per-shape production-exact four-kernel GPU device-elapsed medians",
        "unit": "us",
        "direction": "minimize",
        "workload_cases": [{"case_id": case, "weight": WEIGHT} for case in CASES],
        "measurement_semantics": {
            "primary": "CUDA-event device elapsed around 64 warmed native graph replays; graph is only a timing envelope to remove CPU enqueue gaps, not deployment graph latency",
            "transfer_gate": "graph/direct deltas must have the same sign and the 95% CI of delta_graph-delta_direct must lie in [-0.10,+0.10] us",
            "cpu_dispatch": "reported separately and never folded into the kernel-ranking metric",
        },
        "decision_indifference_band_us": 0.10,
        "created_at": now,
    }
    objective_path = models / "objective.json"
    dump(objective_path, objective)

    candidate_dir = models / "architecture_candidates"
    c0_spec = {
        "candidate_id": "C0",
        "name": "current-four-kernel-production",
        "status": "MEASURED_BASELINE",
        "pipeline": ["s01", "s2", "s3_raw", "gated_rms_post"],
        "abi_tag": "fla_l017_s01wstoreu4_s384to640_m104_headmajor_s2hcta_s3native_s3u4u8split_poststatic1_b384_v5",
        "source_contract": "frozen production source identities in models/baseline.json",
    }
    c1_spec = {
        "candidate_id": "C1",
        "name": "s3-block-causal-tile-schedule",
        "status": "UNRESOLVED_TOP_TWO",
        "pipeline": ["s01", "s2", "s3_raw", "gated_rms_post"],
        "single_architectural_change": (
            "In S3 QK and score-times-V only, schedule the 10 lower-triangular 16x16 token-tile pairs "
            "instead of all 16 pairs for every full 64-token chunk. For the S404 20-token tail, use a 2x2 "
            "tile grid and schedule its 3 causal pairs. Keep full fixed-shape MMA work and masking inside each "
            "diagonal/tail tile; no element-level tensor-work saving is claimed."
        ),
        "explicit_non_changes": [
            "S01, S2, post, cross-kernel ABI and four-kernel topology",
            "BF16 score rounding and BF16 raw_o rounding boundaries",
            "current shared score handoff; no register-fragment handoff in this candidate",
            "grid and block geometry",
            "nonzero accumulation order within each output element",
        ],
        "scheduled_work": [
            {
                "case_id": case,
                "c0_flop": C0_FLOP[i],
                "removed_flop": TILE_FEASIBLE_REMOVED_FLOP[i],
                "c1_flop": C0_FLOP[i] - TILE_FEASIBLE_REMOVED_FLOP[i],
                "c1_s3_scheduled_flop": C1_S3_SCHEDULED_FLOP[i],
                "c1_s3_schedule_padding_flop": C1_S3_PADDING_FLOP[i],
                "c1_total_schedule_padding_flop": C1_TOTAL_PADDING_FLOP[i],
            }
            for i, case in enumerate(CASES)
        ],
        "hard_resource_gates": {
            "short": {"registers_per_thread_max": 126, "shared_bytes_max": 73984},
            "long": {"registers_per_thread_max": 128, "shared_bytes_max": 49408},
            "stack_bytes": 0,
            "spill_bytes": 0,
        },
        "tail_gate": "S404 must prove that no wholly invalid tile is issued/read and that intra-tile masking remains exact.",
    }
    c2_spec = {
        "candidate_id": "C2",
        "name": "s3-post-true-fusion",
        "status": "REJECTED_DOMINATED",
        "pipeline": ["s01", "s2", "s3_plus_gated_rms_post"],
        "reason": "Existing seven-shape exact-BF16-boundary paired evidence is slower for every target shape; no remeasurement authorized.",
        "weighted_objective_interval_us": C2_INTERVAL,
    }
    for spec in (c0_spec, c1_spec, c2_spec):
        dump(candidate_dir / f"{spec['candidate_id'].lower()}.json", spec)

    weighted_p05 = weighted(GPU_P05)
    weighted_median = weighted(GPU_MEDIAN)
    weighted_p95 = weighted(GPU_P95)
    weighted_s3 = weighted(S3_STAGE_US)
    c1_weighted_lower = weighted(C1_OPERATIONAL_LOWER_US)
    admission_cap = weighted(C1_REGRESSION_CAP_US)
    delta_lower = c1_weighted_lower - weighted_median
    delta_upper = admission_cap - weighted_median
    maximum_decision_value = abs(delta_lower)

    frontier_cases = []
    for i, case in enumerate(CASES):
        c0 = schedule_point(
            "C0", i, flop=C0_FLOP[i], logical_bytes=LOGICAL_BYTES[i],
            predicted={"status": "MEASURED", **interval(GPU_P05[i], GPU_P95[i])},
            measured={"status": "MEASURED", "median": GPU_MEDIAN[i], "unit": "us"},
            decision="TOP_TWO_MEASURED",
            padded_flop=C0_TOTAL_PADDING_FLOP[i],
        )
        c1 = schedule_point(
            "C1", i,
            flop=C0_FLOP[i] - TILE_FEASIBLE_REMOVED_FLOP[i],
            logical_bytes=LOGICAL_BYTES[i],
            predicted={
                "status": "UNKNOWN_ADMISSIBILITY_CAPPED",
                **interval(C1_OPERATIONAL_LOWER_US[i], C1_REGRESSION_CAP_US[i]),
                "lower_meaning": "existing matched-component operational lower envelope, not a silicon lower bound",
                "upper_meaning": "C1 S3 may regress to twice current S3 before fail-fast rejection; not a hardware upper bound",
            },
            measured={"status": "NOT_MEASURED", "median": None, "unit": "us"},
            decision="TOP_TWO_UNRESOLVED",
            padded_flop=C1_TOTAL_PADDING_FLOP[i],
        )
        c2 = schedule_point(
            "C2", i, flop=C0_FLOP[i], logical_bytes=C2_LOGICAL_BYTES[i],
            predicted={"status": "BOUNDED_DOMINATED", **interval(C2_INTERVAL[0], C2_INTERVAL[1])},
            measured={"status": "HISTORICAL_PRODUCTION_SHAPED_PAIRED", "median": None, "unit": "us"},
            decision="REJECT_DOMINATED",
            padded_flop=C0_TOTAL_PADDING_FLOP[i],
        )
        frontier_cases.append({
            "case_id": case,
            "legal_minimum": {
                "status": "TILE_FEASIBLE_CANDIDATE_WORK",
                "dense_tensor_flop": C0_FLOP[i] - C0_TOTAL_PADDING_FLOP[i],
                "tile_feasible_candidate_flop": C0_FLOP[i] - TILE_FEASIBLE_REMOVED_FLOP[i],
                "note": "The mathematical minimum and tile-feasible candidate are distinct; diagonal/tail 16x16 tile padding is retained in C1.",
            },
            "current_schedule": c0,
            "candidates": [c1, c2],
            "pareto_frontier": ["C1", "C0"],
        })
    frontier = {
        "schema_version": "tradeoff-frontier-v1",
        "status": "INITIALIZED",
        "objective": objective,
        "cases": frontier_cases,
        "global_decision": {
            "status": "PENDING",
            "selected_schedule": None,
            "reason": "C1/C0 ranking depends on one production-matched candidate A/B; C2 is already dominated.",
            "issued_by_role": "GLOBAL_SCHEDULER",
        },
        "evidence": [baseline_id, operator_id, workload_id],
    }
    frontier_path = models / "tradeoff_frontier.json"
    dump(frontier_path, frontier)

    decision = {
        "schema_version": "decision-contract-v1",
        "decision_id": DECISION_ID,
        "status": "READY_FOR_SUPERVISOR",
        "issued_by": {"role": "GLOBAL_SCHEDULER", "owner_id": SCHEDULER_ID},
        "objective_identity": identity(objective_path),
        "frontier_identity": identity(frontier_path),
        "candidate_bindings": [
            {"candidate_id": "C0", "artifact_identity": identity(candidate_dir / "c0.json"), "predicted_objective": interval(weighted_p05, weighted_p95)},
            {"candidate_id": "C1", "artifact_identity": identity(candidate_dir / "c1.json"), "predicted_objective": interval(c1_weighted_lower, admission_cap)},
            {"candidate_id": "C2", "artifact_identity": identity(candidate_dir / "c2.json"), "predicted_objective": interval(*C2_INTERVAL)},
        ],
        "top_two_candidate_ids": ["C1", "C0"],
        "decision_metric": {
            "name": "equal-weight graph-batched production-exact device elapsed; graph is timing envelope only",
            "unit": "us",
            "direction": "minimize",
        },
        "measurement_need": {
            "quantity_id": QUANTITY_ID,
            "model_location": "models/tradeoff_frontier.json::global C1-C0 objective delta",
            "equation": "x=(1/7)*sum_S[median(device_elapsed_C1,S)-median(device_elapsed_C0,S)]",
            "current_interval": interval(delta_lower, delta_upper),
            "top_two_delta_interval": interval(delta_lower, delta_upper),
            "decision_boundary": quantity(0.0, "us"),
            "required_precision": quantity(0.10, "us"),
            "outcome_mapping": [
                {"condition": "qualification 95% CI upper < -0.10 us and all hard gates pass", "outcome": "ACCEPT_C1"},
                {"condition": "qualification 95% CI lower > +0.10 us or any hard gate fails", "outcome": "REJECT_C1_KEEP_C0"},
                {"condition": "95% CI intersects [-0.10,+0.10] us at frozen budget", "outcome": "INCONCLUSIVE_KEEP_C0_NO_SWEEP"},
            ],
            "maximum_decision_value": quantity(maximum_decision_value, "us"),
            "decision_flip_probability": 0.5,
            "expected_uncertainty_reduction": 1.0,
        },
        "experiment_budget": {
            "screening": {
                "max_configurations": 4,
                "max_samples_per_configuration": 15,
                "max_process_launches": 1,
                "max_wall_clock_minutes": 20,
            },
            "qualification": {
                "max_configurations": 14,
                "max_samples_per_configuration": 31,
                "max_process_launches": 21,
                "max_wall_clock_minutes": 60,
            },
            "max_revisions": 1,
        },
        "stop_rules": [
            "Identity, correctness, final-SASS, resource, stream-containment or P0 failure halts and replans.",
            "Screening can reject but cannot globally accept C1.",
            "Qualification CI half-width above 0.10 us is INCONCLUSIVE; do not expand the budget or start a parameter sweep.",
            "One implementation revision is allowed before fresh supervisor review; no post-result source change stays under this decision.",
        ],
        "evidence": [baseline_id, p0_id, discovery_id],
    }
    decision_path = models / "decision_contract.json"
    dump(decision_path, decision)

    measurability = {
        "schema_version": "measurability-contract-v1",
        "status": "READY_FOR_SUPERVISOR",
        "issued_by": {"role": "MICROARCHITECTURE_ANALYST", "analyst_id": ANALYST_ID},
        "decision_contract_identity": identity(decision_path),
        "quantity_id": QUANTITY_ID,
        "identifiability": "PARTIALLY_IDENTIFIABLE",
        "selected_method": "CANDIDATE_AB",
        "observable": {
            "name": "equal-weight mean of per-shape paired median device-elapsed difference C1-C0",
            "unit": "us",
            "measurement_window": (
                "Same explicit stream; CUDA events bracket 64 warmed exact four-kernel replays per randomized interleaved AB/BA block. "
                "Graph is a timing mechanism only. CUPTI stage activity and uncaptured-direct transfer are collected separately."
            ),
        },
        "causal_mapping": {
            "formula": (
                "delta_S=median(t_C1,S)-median(t_C0,S) over paired blocks; x_hat=(1/7)*sum(delta_S). "
                "Use hierarchical paired bootstrap over blocks and cold processes for the 95% CI."
            ),
            "assumptions": [
                "Only the registered S3 block-causal tile schedule changes; ABI, input, workspace, stream and four-kernel topology are identical.",
                "All retained nonzero terms preserve current accumulation order and exact BF16 score/raw_o rounding boundaries.",
                "Paired ordering removes common drift and no competing workload crosses a pair.",
            ],
            "confounders": [
                "Wrong Harrix/FlashInfer import path or stale editable install",
                "C0/C1 JIT cache-key collision or identical loaded cubin",
                "Unregistered source, launch geometry, input, layout, alignment, stream or graph change",
                "Cold compilation/allocation, CPU starvation, clock/thermal drift or competing GPU work",
                "Tail masking or stale upper-triangle shared values",
            ],
            "controls": [
                "Hash-bind source, argv, inputs and cubins; use distinct C0/C1 ABI/cache keys and prove cubin hashes differ.",
                "Record runtime __file__/find_spec and ABI tag; require PYTHONPATH prefix /workspace/dance/qwen35/new/harrix/python:/workspace/dance/qwen35/flashinfer.",
                "Reject resolution to /workspace/dance/qwen35/harrix or .venv-cu13/site-packages for the modified modules.",
                "Bitwise compare all observable boundaries and final output at all seven shapes, with explicit S404 tail coverage.",
                "Archive final cubin/SASS/ptxas; prove expected upper-tile MMA removal, unchanged S01/S2/post, zero spills, and registered resource caps.",
                "Keep P0 clock/load/timer/live-sink controls PASS and balance randomized AB/BA order.",
                "Collect CUPTI diagnostics separately; require graph/direct deltas to have the same sign and the 95% CI of delta_graph-delta_direct to lie in [-0.10,+0.10] us.",
            ],
            "falsification_condition": (
                "Invalid if any identity/bitwise/resource gate fails, the expected tile work is not removed, any unregistered kernel changes, "
                "or graph/direct rankings disagree or their delta-difference CI leaves [-0.10,+0.10] us. "
                "CI half-width >0.10 us at the frozen budget is INCONCLUSIVE."
            ),
        },
        "expected_precision": {"absolute": 0.10, "unit": "us"},
        "required_tier": "QUALIFICATION",
        "evidence": [operator_id, workload_id, baseline_id, p0_id],
    }
    measurability_path = models / "measurability_contract.json"
    dump(measurability_path, measurability)

    sensitive_resources = {
        "conversion_pipe",
        "cta_allocation",
        "instruction_front_end",
        "integer_address_pipe",
        "l1_shared_boundary",
        "load_store_request",
        "predicate_compute",
        "predicate_storage",
        "register_storage",
        "scoreboard_wait",
        "shared_bank_service",
        "shared_memory",
        "simt_compute",
        "synchronization",
        "tensor_compute",
        "tensor_issue",
        "warp_collective",
        "warp_issue",
    }
    kind = {
        "async_copy_engine": "TMA",
        "constant_memory_path": "REQUEST_SERVICE",
        "conversion_pipe": "SIMT",
        "cta_allocation": "FRONT_END",
        "device_memory_boundary": "DEVICE_MEMORY",
        "instruction_front_end": "FRONT_END",
        "integer_address_pipe": "SIMT",
        "kernel_dispatch": "FRONT_END",
        "l1_shared_boundary": "SHARED_L1",
        "l2_boundary": "L2",
        "load_store_request": "REQUEST_SERVICE",
        "predicate_compute": "SIMT",
        "predicate_storage": "FRONT_END",
        "register_storage": "REQUEST_SERVICE",
        "scoreboard_wait": "SYNCHRONIZATION",
        "shared_bank_service": "REQUEST_SERVICE",
        "shared_memory": "SHARED_L1",
        "simt_compute": "SIMT",
        "special_function": "SFU",
        "synchronization": "SYNCHRONIZATION",
        "system_register_path": "FRONT_END",
        "tensor_compute": "TENSOR_CORE",
        "tensor_issue": "TENSOR_CORE",
        "warp_collective": "SIMT",
        "warp_issue": "FRONT_END",
    }
    resource_cases = []
    for i, case in enumerate(CASES):
        rows = []
        for resource in resources:
            sensitive = resource in sensitive_resources
            row = {
                "resource_id": resource,
                "resource_kind": kind[resource],
                "material": True,
                "mandatory_work": quantity(0, "candidate_specific_dynamic_work_units_unresolved"),
                "actual_work": quantity(0, "candidate_specific_dynamic_work_units_unresolved"),
                "production_point": {"status": "UNKNOWN", "value": None, "unit": "candidate_specific_dynamic_work_units"},
                "matched_saturation": {"status": "UNKNOWN", "value": None, "unit": "unknown", "conditions": []},
                "utilization": {
                    "status": "UNKNOWN",
                    "value_percent": None,
                    "numerator": None,
                    "denominator": None,
                    "time_window": "registered paired full-pipeline device-elapsed window",
                    "boundary": kind[resource],
                },
                "critical_path": {
                    "status": "UNKNOWN",
                    "contribution_us": None,
                    "probability": 0.5 if sensitive else 0.0,
                    "coupling_model": "Resolved only through the single registered candidate A/B" if sensitive else "Unchanged by C1 candidate contract",
                },
                "non_saturation_causes": ["NOT_ESTABLISHED"],
                "evidence": [],
                "unresolved_request_ids": [REQUEST_ID] if sensitive else [],
                "decision_relevance": {
                    "status": "TOP_TWO_SENSITIVE" if sensitive else "NOT_TOP_TWO_SENSITIVE",
                    "decision_contract_ids": [DECISION_ID] if sensitive else [],
                    "explanation": (
                        "Candidate effect is deliberately measured jointly; no resource-isolated microbenchmark is authorized."
                        if sensitive
                        else "C1 freezes this resource boundary/work at C0; it cannot flip C1/C0 except through a contract violation."
                    ),
                },
            }
            if kind[resource] == "TENSOR_CORE":
                row["compute_efficiency"] = {
                    "device_coverage": None,
                    "eligible_time_fraction": None,
                    "eligible_window_issue_efficiency": None,
                    "composition_status": "UNKNOWN",
                }
            rows.append(row)
        resource_cases.append({
            "case_id": case,
            "resource_rows": rows,
            "device_coverage": {"status": "BOUNDED_GEOMETRIC", "sm_count": 170},
            "critical_path": {
                "status": "MEASURED_BASELINE_CANDIDATE_UNKNOWN",
                "total_us": GPU_MEDIAN[i],
                "stage_gpu_active_us": {"s3": S3_STAGE_US[i]},
            },
            "model_residual": {"status": "UNKNOWN_UNTIL_CANDIDATE_AB", "value_us": None},
        })
    resource_balance = {
        "schema_version": "resource-balance-ledger-v2",
        "status": "INITIALIZED",
        "cases": resource_cases,
        "cross_resource_coupling": [{
            "decision_id": DECISION_ID,
            "resources": sorted(sensitive_resources),
            "reason": "Tile removal jointly changes tensor issue, control/address work, score handoff, live ranges and CTA residency; individual service curves are not additive.",
            "resolution": "production-matched CANDIDATE_AB",
        }],
        "unresolved_material_resources": sorted(sensitive_resources),
        "evidence": [baseline_id, discovery_id],
    }
    dump(models / "resource_balance.json", resource_balance)

    nodes_by_id = {item["resource_id"]: item for item in discovery["resource_nodes"]}
    microarchitecture = {
        "schema_version": "microarchitecture-model-v1",
        "status": "INITIALIZED",
        "target_identity": {
            "name": "NVIDIA GeForce RTX 5090",
            "compute_capability": "12.0",
            "sm_count": 170,
            "hardware_identity": hardware_id,
        },
        "scope": {
            "stages": ["s01", "s2", "s3", "post"],
            "decision_focus": "C1 versus C0 S3 block-causal tensor schedule",
            "material_resource_ids": resources,
        },
        "resource_nodes": [nodes_by_id[resource] for resource in resources],
        "resource_edges": [
            {"from": "device_memory_boundary", "to": "l2_boundary", "status": "MATERIAL"},
            {"from": "l2_boundary", "to": "l1_shared_boundary", "status": "MATERIAL"},
            {"from": "shared_memory", "to": "tensor_compute", "status": "MATERIAL"},
            {"from": "register_storage", "to": "tensor_issue", "status": "MATERIAL"},
            {"from": "instruction_front_end", "to": "warp_issue", "status": "MATERIAL"},
            {"from": "synchronization", "to": "scoreboard_wait", "status": "MATERIAL"},
        ],
        "allocation_constraints": [
            {"stage": "s3_short", "block_threads": 512, "registers_per_thread_max": 126, "shared_bytes_max": 73984, "residency": "one CTA/SM"},
            {"stage": "s3_long", "block_threads": 256, "registers_per_thread_max": 128, "shared_bytes_max": 49408, "residency": "two CTA/SM"},
            {"all_stages": True, "stack_bytes": 0, "spill_bytes": 0},
        ],
        "service_curves": [
            {"service_id": "p0-device-timing", "status": "CALIBRATED", "evidence": [p0_id]},
            {"service_id": "c0-production-device-elapsed", "status": "MEASURED", "values_us": dict(zip(CASES, GPU_MEDIAN)), "evidence": [baseline_id]},
            {"service_id": "c1-joint-candidate-effect", "status": "UNKNOWN", "resolution": REQUEST_ID},
        ],
        "latency_constraints": [
            {"constraint": "C1 net latency cannot be inferred from removed tensor FLOP because issue/control/live-range/coverage effects are coupled", "status": "UNKNOWN"},
            {"constraint": "graph timing is not deployment graph latency; graph/direct delta signs must agree and their delta-difference CI must fit +/-0.10 us", "status": "REQUIRED_GATE"},
        ],
        "workload_mappings": [
            {
                "case_id": case,
                "sequence": SEQUENCES[i],
                "chunks": (SEQUENCES[i] + 63) // 64,
                "c0_flop": C0_FLOP[i],
                "c1_tile_feasible_flop": C0_FLOP[i] - TILE_FEASIBLE_REMOVED_FLOP[i],
                "logical_bytes_unchanged": LOGICAL_BYTES[i],
            }
            for i, case in enumerate(CASES)
        ],
        "overlap_constraints": [
            {"scope": "s3", "constraint": "Tensor issue, shared-score transport, integer/predicate work and scoreboard waits overlap; do not sum isolated times."},
            {"scope": "pipeline", "constraint": "S01/S2/post identities and four-kernel topology remain unchanged."},
        ],
        "unknowns": [
            {"quantity_id": QUANTITY_ID, "decision_relevance": "TOP_TWO_SENSITIVE", "resolution": "CANDIDATE_AB"},
            {"quantity_id": "per-resource-utilization", "decision_relevance": "NOT_REQUIRED_TO_RANK_TOP_TWO", "resolution": "remain UNKNOWN unless candidate result creates a new ranking ambiguity"},
        ],
        "evidence": [hardware_id, discovery_id, baseline_id, p0_id],
    }
    dump(models / "microarchitecture_model.json", microarchitecture)

    stage_map = {
        "async_copy_engine": ["s01", "s2", "s3"],
        "constant_memory_path": ["s01", "s2", "s3", "post"],
        "conversion_pipe": ["s01", "s2", "s3", "post"],
        "cta_allocation": ["s01", "s2", "s3", "post"],
        "device_memory_boundary": ["s01", "s2", "s3", "post"],
        "instruction_front_end": ["s01", "s2", "s3", "post"],
        "integer_address_pipe": ["s01", "s2", "s3", "post"],
        "kernel_dispatch": ["s01", "s2", "s3", "post"],
        "l1_shared_boundary": ["s01", "s2", "s3"],
        "l2_boundary": ["s01", "s2", "s3", "post"],
        "load_store_request": ["s01", "s2", "s3", "post"],
        "predicate_compute": ["s01", "s2", "s3", "post"],
        "predicate_storage": ["s01", "s2", "s3", "post"],
        "register_storage": ["s01", "s2", "s3", "post"],
        "scoreboard_wait": ["s01", "s2", "s3"],
        "shared_bank_service": ["s01", "s2", "s3"],
        "shared_memory": ["s01", "s2", "s3"],
        "simt_compute": ["s01", "s2", "s3", "post"],
        "special_function": ["s01", "s2", "s3", "post"],
        "synchronization": ["s01", "s2", "s3"],
        "system_register_path": ["s01", "s2", "s3", "post"],
        "tensor_compute": ["s01", "s2", "s3"],
        "tensor_issue": ["s01", "s2", "s3"],
        "warp_collective": ["s01", "s2", "s3", "post"],
        "warp_issue": ["s01", "s2", "s3", "post"],
    }
    global_state = {
        "schema_version": "global-schedule-state-v2",
        "status": "PLANNED",
        "owner": {
            "role": "GLOBAL_SCHEDULER",
            "owner_id": SCHEDULER_ID,
            "exclusive_authority": ["RANK_EXPERIMENTS", "CLOSE_RESOURCE_MODEL", "ACCEPT_GLOBAL_CANDIDATE", "AUTHORIZE_LIMIT_REPORT"],
        },
        "supervisor": {
            "role": "GLOBAL_SUPERVISOR",
            "owner_id": SUPERVISOR_ID,
            "exclusive_authority": ["VETO_EXPERIMENT", "APPROVE_EXPERIMENT_DISPATCH", "ENFORCE_BUDGET", "HALT_AND_REPLAN"],
            "must_be_distinct_from": ["GLOBAL_SCHEDULER", "MICROARCHITECTURE_ANALYST", "EXPERIMENT_AGENT"],
        },
        "material_resources": resources,
        "stage_assignments": [{"resource_id": resource, "stage_ids": stage_map[resource]} for resource in resources],
        "owned_artifacts": {
            "resource_balance": "models/resource_balance.json",
            "tradeoff_frontier": "models/tradeoff_frontier.json",
            "experiment_queue": "models/experiment_queue.json",
            "schedule_model": "models/schedule_model.json",
        },
        "decision_policy": {
            "objective": objective,
            "ranking": "candidate_specific_decision_value_us * decision_flip_probability * expected_uncertainty_reduction / experiment_cost_weight",
            "local_speedup_is_not_global_acceptance": True,
            "candidate_driven_experiments_only": True,
            "unknown_does_not_imply_measure": True,
            "supervisor_approval_required": True,
        },
        "human_report_gate": {"status": "BLOCKED", "requires": ["resolved C1/C0 decision", "validated resource balance", "validated production model"]},
        "revision_history": [{"revision": 1, "at": now, "reason": "Corrected elementwise-minimum C1 into a realizable 16x16 tile-granular schedule and retained positive-regression uncertainty."}],
    }
    dump(models / "global_schedule_state.json", global_state)

    ranking_score = maximum_decision_value * 0.5
    request = {
        "request_id": REQUEST_ID,
        "status": "PROPOSED",
        "issued_by_role": "GLOBAL_SCHEDULER",
        "workload_cases": CASES,
        "model_field": "tradeoff_frontier.global C1-C0 weighted objective delta",
        "candidate_decision": "Rank C1 block-causal S3 tile schedule against C0 current production.",
        "causal_question": "Does removing only tensor-core-feasible strict upper/tail tile work reduce exact four-kernel device execution after all control/resource coupling?",
        "decision_contract": identity(decision_path),
        "measurability_contract": identity(measurability_path),
        "experiment_class": "SCREENING",
        "tested_candidate_ids": ["C1", "C0"],
        "implementation_owner": {"role": "EXPERIMENT_AGENT", "actor_id": EXPERIMENTER_ID},
        "resource_ids": sorted(sensitive_resources),
        "affected_stage_ids": ["s3"],
        "priority": 0,
        "sensitivity": {
            "candidate_specific_decision_value_us": maximum_decision_value,
            "decision_flip_probability": 0.5,
            "expected_uncertainty_reduction": 1.0,
            "experiment_cost": "MEDIUM",
            "experiment_cost_weight": 1.0,
            "ranking_score": ranking_score,
        },
        "controls": measurability["causal_mapping"]["controls"],
        "measurement_contract": {
            "primary": measurability["observable"]["measurement_window"],
            "screening_cases": ["s404", "s768"],
            "qualification_cases": CASES,
            "precision": measurability["expected_precision"],
            "direct_transfer_gate": True,
        },
        "expected_sass": [
            "C1 S3 has fewer registered QK and score-times-V HMMA sites/dynamic tile invocations than C0",
            "S01/S2/post cubin identities unchanged",
            "zero stack/spill and resource caps preserved",
        ],
        "catalog_resolution": {
            "catalog_queried": False,
            "query": {
                "method": "CANDIDATE_AB",
                "quantity_id": QUANTITY_ID,
                "resources": sorted(sensitive_resources),
                "workload_cases": CASES,
            },
            "decision": None,
            "package_id": None,
            "reason": "Catalog query is the next deterministic lifecycle action; no atomic microbenchmark is eligible for this coupled decision.",
        },
        "result_binding": {"status": "PENDING", "evidence": []},
        "promotion_disposition": {"status": "NOT_APPLICABLE", "reason": "This is an application-specific production candidate A/B, not a generic atomic probe."},
    }
    experiment_queue = {
        "schema_version": "experiment-request-queue-v2",
        "status": "EXECUTABLE",
        "ranking_policy": {
            "primary": "candidate_specific_decision_value_us",
            "secondary": ["decision_flip_probability", "expected_uncertainty_reduction", "experiment_cost"],
            "issued_by_role": "GLOBAL_SCHEDULER",
            "formula": "candidate_specific_decision_value_us * decision_flip_probability * expected_uncertainty_reduction / experiment_cost_weight",
        },
        "requests": [request],
        "catalog_snapshot": {"status": "QUERY_PENDING", "decision": "No atomic probe can identify the registered joint candidate effect."},
        "promotion_review": [],
    }
    dump(models / "experiment_queue.json", experiment_queue)

    microbenchmark_plan = json.loads((models / "microbenchmark_plan.json").read_text())
    microbenchmark_plan.update({
        "status": "EXECUTABLE",
        "target_questions": [
            {"quantity_id": QUANTITY_ID, "question": "Does C1 beat C0 under the registered production-matched metric?", "method": "CANDIDATE_AB"},
            {"quantity_id": "graph_to_direct_ranking_transfer", "question": "Does the graph-batched timing ranking agree with uncaptured-direct production execution?", "method": "paired transfer gate"},
        ],
        "coupling_tests": [],
        "cross_layer_prediction_gates": [
            {"gate": "No atomic component sum predicts C1; only exact candidate A/B may update the frontier.", "status": "ENFORCED"},
            {"gate": "Graph/direct deltas must agree in sign and delta_graph-delta_direct 95% CI must lie in [-0.10,+0.10] us.", "status": "PENDING"},
        ],
    })
    for level in ("P1", "P2", "P3", "P4"):
        microbenchmark_plan["levels"][level] = {
            "required": False,
            "status": "NOT_APPLICABLE",
            "reason": "No atomic microbenchmark is decision-identifying; the registered work is a production candidate A/B.",
            "experiments": [],
            "evidence": [],
        }
    dump(models / "microbenchmark_plan.json", microbenchmark_plan)

    plan = {
        "schema_version": "optimization-plan-v1",
        "status": "EXECUTABLE",
        "objective": objective,
        "global_scheduler_owner": SCHEDULER_ID,
        "global_supervisor_owner": SUPERVISOR_ID,
        "candidate_limit": 3,
        "screening_budget": decision["experiment_budget"]["screening"],
        "qualification_budget": decision["experiment_budget"]["qualification"],
        "max_revisions_per_decision": 1,
        "baseline_identities": [baseline_id, operator_id, workload_id, hardware_id, p0_id],
        "workload_priorities": [
            {"case_id": "s404", "rank": 0, "reason": "main audit anchor and 20-token tail"},
            {"case_id": "s1024", "rank": 1, "reason": "long path and two-CTA/SM constraint"},
            {"case_id": "s256", "rank": 2, "reason": "SM underfill boundary"},
            {"case_id": "s640", "rank": 3, "reason": "short-dispatch edge"},
            {"case_id": "s768", "rank": 4, "reason": "long-dispatch edge"},
            {"case_id": "s384", "rank": 5, "reason": "equal-weight production coverage"},
            {"case_id": "s512", "rank": 6, "reason": "equal-weight production coverage"},
        ],
        "model_dependencies": ["mandatory-work ledger", "operator DAG", "SM120 resource graph", "frozen production baseline"],
        "experiment_queue": [REQUEST_ID],
        "correctness_gates": [
            "All seven shapes pass bitwise stage-boundary and final-output comparisons; S404 tail is explicit.",
            "Direct repeat and graph-versus-direct remain bitwise.",
            "NaN/Inf masks and extreme finite inputs match the registered reference domain.",
        ],
        "evidence_gates": [
            "Runtime import paths, source hashes, ABI/cache keys and distinct C0/C1 cubins are recorded.",
            "Final SASS proves tile-work removal, unchanged S01/S2/post, zero spill and resource caps.",
            "P0 remains PASS; CUPTI diagnostic is separated from acceptance timing.",
            "Graph/direct deltas agree in sign and delta_graph-delta_direct 95% CI lies in [-0.10,+0.10] us before production acceptance.",
        ],
        "acceptance_rule": "Accept C1 only after qualification 95% CI upper<-0.10us and every hard gate; otherwise retain C0. Screening cannot accept.",
        "model_error_tolerances_percent": {"p1_p2_to_p3": 10.0, "schedule_to_p4": 10.0, "achieved_to_feasible_bound": 15.0},
        "stop_criteria": decision["stop_rules"],
        "open_uncertainties": [{"quantity_id": QUANTITY_ID, "decision_contract": identity(decision_path)}],
        "revision_history": [{"revision": 1, "at": now, "reason": "Candidate-first correction: tile-feasible scheduled work and positive-regression uncertainty."}],
    }
    dump(models / "optimization_plan.json", plan)

    receipt = {
        "schema_version": "planning-materialization-receipt-v1",
        "status": "PASS",
        "created_at": now,
        "run": str(run),
        "roles": {
            "global_scheduler": SCHEDULER_ID,
            "microarchitecture_analyst": ANALYST_ID,
            "global_supervisor": SUPERVISOR_ID,
            "future_experiment_agent": EXPERIMENTER_ID,
        },
        "corrections": [
            "C1 scheduled FLOP is 16x16 tile-feasible; diagonal and intra-tail padding remain.",
            "C1 uncertainty permits positive regression.",
            "Graph batching is registered as a timing envelope and needs direct-ranking transfer before production acceptance.",
            "No atomic microbenchmark is authorized for the coupled Top-2 uncertainty.",
        ],
        "artifact_identities": {
            name: identity(models / name)
            for name in (
                "objective.json",
                "optimization_plan.json",
                "global_schedule_state.json",
                "resource_balance.json",
                "tradeoff_frontier.json",
                "experiment_queue.json",
                "microarchitecture_model.json",
                "microbenchmark_plan.json",
                "decision_contract.json",
                "measurability_contract.json",
            )
        },
    }
    dump(run / "traces" / "planning_materialization_v2.json", receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
