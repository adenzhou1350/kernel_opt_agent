#!/usr/bin/env python3
"""Deterministic measurement-system calibration calculations."""

from __future__ import annotations

import math
import statistics


def finite_samples(data: dict, name: str, minimum: int = 3) -> list[float]:
    values = data.get("samples", {}).get(name, [])
    if not isinstance(values, list) or len(values) < minimum:
        raise ValueError(f"P0 input samples.{name} requires at least {minimum} values")
    result = [float(value) for value in values]
    if not all(math.isfinite(value) for value in result):
        raise ValueError(f"P0 input samples.{name} contains a non-finite value")
    return result


def relative_delta(left: float, right: float) -> float:
    denominator = max(abs(left), abs(right), 1e-12)
    return abs(left - right) / denominator


def evaluate_p0(data: dict) -> dict:
    thresholds = data.get("thresholds", {})
    timer = finite_samples(data, "timer_overhead_us", 9)
    zero = finite_samples(data, "zero_work_us", 9)
    positive = finite_samples(data, "positive_work_us", 9)
    graph = finite_samples(data, "graph_us", 9)
    direct = finite_samples(data, "direct_us", 9)
    clocks = finite_samples(data, "clock_mhz", 9)
    load = finite_samples(data, "competing_load_percent", 9)
    replicas = finite_samples(data, "independent_process_median_us", 3)
    cold = data.get("cold_warm", {})
    if cold.get("separated") is not True or len(cold.get("cold_us", [])) < 3 or len(cold.get("warm_us", [])) < 9:
        raise ValueError("P0 input must preserve at least three cold and nine warm samples separately")
    clock_mean = statistics.fmean(clocks)
    clock_cv = statistics.pstdev(clocks) / clock_mean if clock_mean else math.inf
    graph_delta = relative_delta(statistics.median(graph), statistics.median(direct))
    replica_center = statistics.median(replicas)
    replica_spread = (max(replicas) - min(replicas)) / max(abs(replica_center), 1e-12)
    controls = {
        "timer_bracket": {
            "observed": statistics.median(timer), "threshold": float(thresholds["timer_overhead_max_us"]),
            "status": "PASS" if statistics.median(timer) <= float(thresholds["timer_overhead_max_us"]) else "FAIL",
        },
        "zero_work": {
            "observed": statistics.median(positive) - statistics.median(zero),
            "threshold": float(thresholds["positive_minus_zero_min_us"]),
            "status": "PASS" if statistics.median(positive) - statistics.median(zero) >= float(thresholds["positive_minus_zero_min_us"]) else "FAIL",
        },
        "live_sink": {
            "observed": data.get("live_sink", {}).get("status"), "threshold": "PASS",
            "status": "PASS" if data.get("live_sink", {}).get("status") == "PASS" else "FAIL",
        },
        "graph_direct_equivalence": {
            "observed": graph_delta, "threshold": float(thresholds["graph_direct_relative_max"]),
            "status": "PASS" if graph_delta <= float(thresholds["graph_direct_relative_max"]) else "FAIL",
        },
        "clock_stability": {
            "observed": clock_cv, "threshold": float(thresholds["clock_cv_max"]),
            "status": "PASS" if clock_cv <= float(thresholds["clock_cv_max"]) else "FAIL",
        },
        "cold_warm_separation": {"observed": True, "threshold": True, "status": "PASS"},
        "competing_load": {
            "observed": max(load), "threshold": float(thresholds["competing_load_max_percent"]),
            "status": "PASS" if max(load) <= float(thresholds["competing_load_max_percent"]) else "FAIL",
        },
        "independent_process_replication": {
            "observed": replica_spread, "threshold": float(thresholds["replication_relative_spread_max"]),
            "status": "PASS" if replica_spread <= float(thresholds["replication_relative_spread_max"]) else "FAIL",
        },
    }
    return controls
