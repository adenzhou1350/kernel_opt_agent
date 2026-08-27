#!/usr/bin/env python3
"""Validate register-allocation and warp-collective P1 service curves."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from collections import defaultdict
from pathlib import Path


ORDERS = {"forward_a", "forward_b", "reverse_a", "reverse_b"}
GEOMETRIES = ("s01", "s2", "s3", "post")
ALLOCATION_REPEATS = (32, 64, 128)
COLLECTIVE_REPEATS = (64, 128, 256)
ALLOCATION_VARIANTS = ("alloc0", "alloc32", "alloc64", "alloc96", "alloc112", "alloc116", "alloc124")
S3_ALLOCATION_VARIANTS = ("alloc0", "alloc32", "alloc64", "alloc96", "alloc112")


def identity(path: Path) -> dict:
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def linear_fit(xs: tuple[int, ...], ys: list[float]) -> dict:
    x_mean, y_mean = statistics.mean(xs), statistics.mean(ys)
    denominator = sum((x - x_mean) ** 2 for x in xs)
    slope = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys)) / denominator
    intercept = y_mean - slope * x_mean
    residual = sum((y - (intercept + slope * x)) ** 2 for x, y in zip(xs, ys))
    total = sum((y - y_mean) ** 2 for y in ys)
    return {
        "slope_us_per_repeat": slope,
        "slope_ns_per_repeat": slope * 1000.0,
        "intercept_us": intercept,
        "r_squared_descriptive": 1.0 - residual / total if total else 1.0,
        "fit_status": "DESCRIPTIVE_THREE_POINT_FIT; NOT_EXTRAPOLATABLE",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    run = args.run.resolve()
    root = run / "experiments/req-register-collective"
    raw_path = root / "raw/samples.json"
    audit_path = root / "static/instruction_audit.json"
    receipt_path = root / "execution_receipt.json"
    experiment_path = root / "experiment.json"
    raw = json.loads(raw_path.read_text())
    audit = json.loads(audit_path.read_text())
    receipt = json.loads(receipt_path.read_text())

    grouped = defaultdict(list)
    for record in raw["records"]:
        parameters = record["parameters"]
        key = (parameters["stage_geometry"], parameters["variant"], int(parameters["repeats"]))
        gpu_median = statistics.median(record["gpu_us"])
        host_median = statistics.median(record["host_dispatch_us"])
        ordered_gpu = sorted(record["gpu_us"])
        grouped[key].append({
            "order": record["replicate_order"],
            "gpu_median_us": gpu_median,
            "host_dispatch_median_us": host_median,
            "p05_us": ordered_gpu[1],
            "p95_us": ordered_gpu[-2],
            "sink": float(record["sink"]),
            "occupancy_blocks_per_sm": int(record["occupancy_blocks_per_sm"]),
            "actual_registers_per_thread": int(parameters["actual_registers_per_thread"]),
            "dynamic_smem_bytes": int(record["dynamic_smem_bytes"]),
            "measurement_launch_path": record.get("measurement_launch_path"),
            "external_compute_processes": record["external_compute_processes_during"],
            "idle_gate": record["pre_record_idle_receipt"]["status"],
        })

    expected_allocation = {
        (geometry, variant, repeats)
        for geometry in GEOMETRIES
        for variant in (S3_ALLOCATION_VARIANTS if geometry == "s3" else ALLOCATION_VARIANTS)
        for repeats in ALLOCATION_REPEATS
    }
    expected_collective = {
        (geometry, variant, repeats)
        for geometry in GEOMETRIES
        for variant in ("shfl_dep", "shfl_ilp4")
        for repeats in COLLECTIVE_REPEATS
    }
    expected_zero = {(geometry, "zero", 1) for geometry in GEOMETRIES}
    expected_nonzero = expected_allocation | expected_collective
    expected = expected_nonzero | expected_zero

    process_spread = {}
    deterministic = True
    occupancy_stable = True
    graph_measurement_closed = True
    external = []
    idle_failures = []
    submission_risk = []
    within_process_spreads = []
    for key, values in grouped.items():
        medians = [item["gpu_median_us"] for item in values]
        process_spread[key] = (max(medians) - min(medians)) / statistics.mean(medians)
        deterministic = deterministic and len({item["sink"] for item in values}) == 1
        occupancy_stable = occupancy_stable and len({item["occupancy_blocks_per_sm"] for item in values}) == 1
        graph_measurement_closed = graph_measurement_closed and all(
            item["measurement_launch_path"] == "cuda_graph_batch_external_events" for item in values
        )
        external.extend(item for value in values for item in value["external_compute_processes"])
        idle_failures.extend((key, value["order"]) for value in values if value["idle_gate"] != "PASS")
        for value in values:
            if key[1] != "zero" and value["host_dispatch_median_us"] >= 0.8 * value["gpu_median_us"]:
                submission_risk.append({
                    "group": list(key), "order": value["order"],
                    "host_over_gpu": value["host_dispatch_median_us"] / value["gpu_median_us"],
                })
            within_process_spreads.append((value["p95_us"] - value["p05_us"]) / value["gpu_median_us"])

    allocation_curves = []
    for key_prefix in sorted({(key[0], key[1]) for key in expected_allocation}):
        process_medians = {
            str(repeats): [item["gpu_median_us"] for item in grouped[(*key_prefix, repeats)]]
            for repeats in ALLOCATION_REPEATS
        }
        aggregate = [statistics.median(process_medians[str(repeats)]) for repeats in ALLOCATION_REPEATS]
        representative = grouped[(*key_prefix, ALLOCATION_REPEATS[0])][0]
        allocation_curves.append({
            "stage_geometry": key_prefix[0], "variant": key_prefix[1],
            "actual_registers_per_thread": representative["actual_registers_per_thread"],
            "occupancy_blocks_per_sm": representative["occupancy_blocks_per_sm"],
            "dynamic_smem_bytes": representative["dynamic_smem_bytes"],
            "repeat_values": list(ALLOCATION_REPEATS),
            "aggregate_median_us": aggregate,
            "independent_process_medians_us": process_medians,
            "maximum_relative_process_spread": max(process_spread[(*key_prefix, repeat)] for repeat in ALLOCATION_REPEATS),
            **linear_fit(ALLOCATION_REPEATS, aggregate),
        })

    collective_curves = []
    collective_index = {}
    for key_prefix in sorted({(key[0], key[1]) for key in expected_collective}):
        process_medians = {
            str(repeats): [item["gpu_median_us"] for item in grouped[(*key_prefix, repeats)]]
            for repeats in COLLECTIVE_REPEATS
        }
        aggregate = [statistics.median(process_medians[str(repeats)]) for repeats in COLLECTIVE_REPEATS]
        fit = linear_fit(COLLECTIVE_REPEATS, aggregate)
        record = {
            "stage_geometry": key_prefix[0], "variant": key_prefix[1],
            "repeat_values": list(COLLECTIVE_REPEATS),
            "aggregate_median_us": aggregate,
            "independent_process_medians_us": process_medians,
            "maximum_relative_process_spread": max(process_spread[(*key_prefix, repeat)] for repeat in COLLECTIVE_REPEATS),
            **fit,
        }
        collective_curves.append(record)
        collective_index[key_prefix] = record

    collective_incremental = {}
    for geometry in GEOMETRIES:
        dependent = collective_index[(geometry, "shfl_dep")]["slope_us_per_repeat"]
        ilp4 = collective_index[(geometry, "shfl_ilp4")]["slope_us_per_repeat"]
        collective_incremental[geometry] = {
            "dependent_chain_iteration_ns": dependent * 1000.0,
            "ilp4_iteration_ns": ilp4 * 1000.0,
            "incremental_ns_per_each_of_three_extra_shfl": (ilp4 - dependent) * 1000.0 / 3.0,
            "scope": "probe iteration service only; runtime branch and loop overhead prevent a pure-instruction latency claim",
        }

    robust_positive_zero = {}
    for geometry in GEOMETRIES:
        zero_max = max(item["gpu_median_us"] for item in grouped[(geometry, "zero", 1)])
        high_work_keys = [key for key in expected_nonzero if key[0] == geometry and key[2] == (128 if key[1].startswith("alloc") else 256)]
        positive_min = min(min(item["gpu_median_us"] for item in grouped[key]) for key in high_work_keys)
        robust_positive_zero[geometry] = positive_min - zero_max

    maximum_nonzero_spread = max(process_spread[key] for key in expected_nonzero)
    checks = [
        {"check": "technical_execution_receipt", "status": "PASS" if receipt.get("status") == "PASS" else "FAIL"},
        {"check": "exact_parameter_coverage", "status": "PASS" if set(grouped) == expected else "FAIL", "observed_groups": len(grouped), "expected_groups": len(expected)},
        {"check": "four_independent_ABBA_replicas", "status": "PASS" if all(len(values) == 4 and {item["order"] for item in values} == ORDERS for values in grouped.values()) else "FAIL"},
        {"check": "P0_bound_active_clock_cv", "status": "PASS" if raw["clock_control"]["active_clock_cv"] <= 0.05 else "FAIL", "value": raw["clock_control"]["active_clock_cv"], "threshold": 0.05},
        {"check": "no_external_compute_process", "status": "PASS" if not external else "FAIL", "observed": sorted(set(external))},
        {"check": "per_record_idle_gate", "status": "PASS" if not idle_failures else "FAIL", "failures": idle_failures},
        {"check": "function_scoped_SASS_and_exact_ptxas_resources", "status": "PASS" if audit.get("status") == "PASS" and audit.get("function_scoped_requirements", {}).get("ptxas_resource_contract", {}).get("status") == "PASS" else "FAIL"},
        {"check": "deterministic_live_sink", "status": "PASS" if deterministic else "FAIL"},
        {"check": "runtime_occupancy_stable_across_replicas", "status": "PASS" if occupancy_stable else "FAIL"},
        {"check": "P0_qualified_graph_batch_measurement_path", "status": "PASS" if graph_measurement_closed else "FAIL"},
        {"check": "nonzero_independent_process_spread", "status": "PASS" if maximum_nonzero_spread <= 0.10 else "FAIL", "maximum": maximum_nonzero_spread, "threshold": 0.10},
        {"check": "robust_high_work_positive_zero", "status": "PASS" if min(robust_positive_zero.values()) >= 0.5 else "FAIL", "high_work_min_minus_zero_max_us": robust_positive_zero, "threshold_us": 0.5},
    ]
    failed = [item for item in checks if item["status"] == "FAIL"]
    validity = "PASS" if not failed else "REJECT"
    result = {
        "schema_version": "register-collective-p1-v1",
        "status": validity,
        "qualification": "MECHANISM_VALIDATED" if validity == "PASS" else "REJECTED_FOR_CAUSAL_VALIDITY",
        "request_id": "req-register-collective",
        "experiment_identity": identity(experiment_path),
        "execution_receipt_identity": identity(receipt_path),
        "raw_identity": identity(raw_path),
        "static_audit_identity": identity(audit_path),
        "p0_receipt_identity": raw["p0_receipt"],
        "checks": checks,
        "allocation_service_curves": allocation_curves,
        "collective_service_curves": collective_curves,
        "collective_incremental_service": collective_incremental,
        "diagnostics_not_acceptance_gates": {
            "direct_batched_submission_risk_records": len(submission_risk),
            "direct_batched_submission_risk_total_nonzero_records": sum(len(grouped[key]) for key in expected_nonzero),
            "submission_risk_examples": sorted(submission_risk, key=lambda item: item["host_over_gpu"], reverse=True)[:16],
            "maximum_within_process_p95_minus_p05_over_median": max(within_process_spreads),
            "interpretation": "CUDA events around many direct CPU launches include stream idle gaps when host submission does not stay ahead of short kernels; use a P0-qualified CUDA Graph batch or another proven gap-free enqueue path.",
        },
        "summary": {
            "active_clock_cv": raw["clock_control"]["active_clock_cv"],
            "maximum_nonzero_process_spread": maximum_nonzero_spread,
            "robust_high_work_positive_zero_us": robust_positive_zero,
        },
        "claims_allowed": [] if validity != "PASS" else [
            "run-local slope sensitivity to register allocation under the exact probe and launch geometry",
            "run-local incremental collective service under the exact probe",
        ],
        "claims_forbidden": [
            "production critical-path attribution or utilization",
            "pure SHFL instruction latency because the probe includes loop and runtime branch overhead",
            "mechanism conclusions from curves that fail the independent-process spread gate",
            "P2 counter or scheduler-stall claims while NVGPUCTRPERM remains unavailable",
        ],
        "fit_disclosure": "Three-point fits are descriptive only; no fit is accepted when a causal validity gate fails.",
    }
    output = root / "p1_service_curve.json"
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": validity, "output": str(output), "failed_checks": [item["check"] for item in failed], "summary": result["summary"], "submission_risk_records": len(submission_risk)}, sort_keys=True))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
