#!/usr/bin/env python3
"""Validate and summarize the attempt-06 shared/request P1 service curves."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from collections import defaultdict
from pathlib import Path


ORDERS = {"forward_a", "forward_b", "reverse_a", "reverse_b"}
REPEATS = (64, 128, 256)
GEOMETRIES = ("s01", "s2", "s3", "post")
STRIDES = (1, 2, 4, 8, 16, 32)


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
    root = run / "experiments/req-shared-request-service"
    raw_path = root / "raw/samples.json"
    audit_path = root / "static/instruction_audit.json"
    receipt_path = root / "execution_receipt.json"
    experiment_path = root / "experiment.json"
    raw = json.loads(raw_path.read_text())
    audit = json.loads(audit_path.read_text())
    receipt = json.loads(receipt_path.read_text())
    grouped = defaultdict(list)
    for record in raw["records"]:
        p = record["parameters"]
        key = (p["stage_geometry"], p["variant"], int(p["stride"]), int(p["repeats"]))
        grouped[key].append({
            "order": record["replicate_order"],
            "median_us": statistics.median(record["gpu_us"]),
            "p05_us": sorted(record["gpu_us"])[1],
            "p95_us": sorted(record["gpu_us"])[-2],
            "sink": float(record["sink"]),
            "active_clock_samples": record["active_gpu_samples"],
            "external_compute_processes": record["external_compute_processes_during"],
            "idle_gate": record["pre_record_idle_receipt"]["status"],
        })

    expected_nonzero = {
        (geometry, "shared", stride, repeats)
        for geometry in GEOMETRIES for stride in STRIDES for repeats in REPEATS
    } | {
        ("s01", variant, 1, repeats)
        for variant in ("constant_broadcast", "constant_divergent") for repeats in REPEATS
    }
    expected_zero = {(geometry, "zero", 1, 1) for geometry in GEOMETRIES}
    coverage_pass = set(grouped) == expected_nonzero | expected_zero
    four_replica_pass = all(len(values) == 4 and {item["order"] for item in values} == ORDERS for values in grouped.values())
    max_spread = {}
    deterministic = True
    external = []
    idle_failures = []
    for key, values in grouped.items():
        medians = [item["median_us"] for item in values]
        max_spread[key] = (max(medians) - min(medians)) / statistics.mean(medians)
        deterministic &= len({item["sink"] for item in values}) == 1
        external.extend(item for value in values for item in value["external_compute_processes"])
        idle_failures.extend((key, value["order"]) for value in values if value["idle_gate"] != "PASS")

    address_pass = True
    for geometry in GEOMETRIES:
        for repeats in REPEATS:
            sinks = [grouped[(geometry, "shared", stride, repeats)][0]["sink"] for stride in STRIDES]
            address_pass &= len(set(sinks)) == len(sinks)
    constant_address_pass = all(
        grouped[("s01", "constant_broadcast", 1, repeats)][0]["sink"]
        != grouped[("s01", "constant_divergent", 1, repeats)][0]["sink"]
        for repeats in REPEATS
    )

    curves = []
    curve_by_key = {}
    for geometry in GEOMETRIES:
        for stride in STRIDES:
            process_medians = {
                str(repeats): [item["median_us"] for item in grouped[(geometry, "shared", stride, repeats)]]
                for repeats in REPEATS
            }
            aggregate = [statistics.median(process_medians[str(repeats)]) for repeats in REPEATS]
            fit = linear_fit(REPEATS, aggregate)
            record = {
                "stage_geometry": geometry, "access": "shared", "stride": stride,
                "repeat_values": list(REPEATS), "aggregate_median_us": aggregate,
                "independent_process_medians_us": process_medians,
                "maximum_relative_process_spread": max(max_spread[(geometry, "shared", stride, r)] for r in REPEATS),
                **fit,
            }
            curves.append(record)
            curve_by_key[(geometry, stride)] = record
    constant_curves = []
    for variant in ("constant_broadcast", "constant_divergent"):
        process_medians = {
            str(repeats): [item["median_us"] for item in grouped[("s01", variant, 1, repeats)]]
            for repeats in REPEATS
        }
        aggregate = [statistics.median(process_medians[str(repeats)]) for repeats in REPEATS]
        constant_curves.append({
            "variant": variant, "repeat_values": list(REPEATS), "aggregate_median_us": aggregate,
            "independent_process_medians_us": process_medians,
            "maximum_relative_process_spread": max(max_spread[("s01", variant, 1, r)] for r in REPEATS),
            **linear_fit(REPEATS, aggregate),
        })

    robust_positive_zero = {}
    for geometry in GEOMETRIES:
        positive_min = min(item["median_us"] for item in grouped[(geometry, "shared", 1, 256)])
        zero_max = max(item["median_us"] for item in grouped[(geometry, "zero", 1, 1)])
        robust_positive_zero[geometry] = positive_min - zero_max
    stride_slope_ratios = {
        geometry: {
            str(stride): curve_by_key[(geometry, stride)]["slope_us_per_repeat"] / curve_by_key[(geometry, 1)]["slope_us_per_repeat"]
            for stride in STRIDES
        }
        for geometry in GEOMETRIES
    }
    constant_ratio = constant_curves[1]["slope_us_per_repeat"] / constant_curves[0]["slope_us_per_repeat"]
    checks = [
        {"check": "technical_execution_receipt", "status": "PASS" if receipt.get("status") == "PASS" else "FAIL"},
        {"check": "exact_parameter_coverage", "status": "PASS" if coverage_pass else "FAIL", "observed_groups": len(grouped), "expected_groups": 82},
        {"check": "four_independent_ABBA_replicas", "status": "PASS" if four_replica_pass else "FAIL"},
        {"check": "P0_bound_active_clock_cv", "status": "PASS" if raw["clock_control"]["active_clock_cv"] <= 0.05 else "FAIL", "value": raw["clock_control"]["active_clock_cv"], "threshold": 0.05},
        {"check": "no_external_compute_process", "status": "PASS" if not external else "FAIL", "observed": sorted(set(external))},
        {"check": "per_record_idle_gate", "status": "PASS" if not idle_failures else "FAIL", "failures": idle_failures},
        {"check": "function_scoped_final_SASS", "status": "PASS" if audit.get("status") == "PASS" and audit.get("function_scoped_requirements") else "FAIL"},
        {"check": "deterministic_live_sink", "status": "PASS" if deterministic and address_pass and constant_address_pass else "FAIL"},
        {"check": "nonzero_independent_process_spread", "status": "PASS" if max(max_spread[k] for k in expected_nonzero) <= 0.10 else "FAIL", "maximum": max(max_spread[k] for k in expected_nonzero), "threshold": 0.10},
        {"check": "robust_positive_zero", "status": "PASS" if min(robust_positive_zero.values()) >= 0.5 else "FAIL", "min_positive_256_minus_max_zero_us": robust_positive_zero, "threshold_us": 0.5},
        {"check": "adverse_shared_stride_direction", "status": "PASS" if all(stride_slope_ratios[g]["32"] > 1.0 for g in GEOMETRIES) else "FAIL", "ratios": stride_slope_ratios},
        {"check": "adverse_constant_divergence_direction", "status": "PASS" if constant_ratio > 1.0 else "FAIL", "divergent_over_broadcast_slope": constant_ratio},
    ]
    failed = [item for item in checks if item["status"] == "FAIL"]
    validity = "PASS" if not failed else "REJECT"
    result = {
        "schema_version": "shared-request-service-p1-v1",
        "status": validity,
        "qualification": "MECHANISM_VALIDATED" if validity == "PASS" else "REJECTED",
        "request_id": "req-shared-request-service",
        "question": "Run-local shared/constant request service slopes under four production launch geometries",
        "experiment_identity": identity(experiment_path),
        "execution_receipt_identity": identity(receipt_path),
        "raw_identity": identity(raw_path),
        "static_audit_identity": identity(audit_path),
        "p0_receipt_identity": raw["p0_receipt"],
        "checks": checks,
        "shared_service_curves": curves,
        "constant_service_curves": constant_curves,
        "summary": {
            "active_clock_cv": raw["clock_control"]["active_clock_cv"],
            "maximum_nonzero_process_spread": max(max_spread[k] for k in expected_nonzero),
            "stride32_over_stride1_slope": {g: stride_slope_ratios[g]["32"] for g in GEOMETRIES},
            "constant_divergent_over_broadcast_slope": constant_ratio,
            "robust_positive_zero_us": robust_positive_zero,
        },
        "claims_allowed": [
            "measured run-local latency slope versus repeated shared access for the exact probe and launch geometries",
            "direction and magnitude of probe sensitivity to shared stride and constant divergence",
            "mechanism-level evidence for layout and bank-index candidate screening",
        ],
        "claims_forbidden": [
            "production-kernel shared-bank conflict count or shared-pipe utilization",
            "production-kernel latency prediction without P2 counter/coupling validation",
            "L2 or DRAM traffic inference from these logical request slopes",
            "service-curve extrapolation outside repeats 64 through 256",
        ],
        "fit_disclosure": "R-squared is descriptive and was not a pre-registered acceptance threshold; only measured-range slopes are reported.",
    }
    output = root / "p1_service_curve.json"
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": validity, "output": str(output), "failed_checks": len(failed), "summary": result["summary"]}, sort_keys=True))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
