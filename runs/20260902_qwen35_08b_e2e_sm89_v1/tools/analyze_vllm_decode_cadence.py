#!/usr/bin/env python3
"""Bound batch-1 decode work outside observed CUDA kernel execution."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import statistics
from pathlib import Path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(fraction * len(ordered)))]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqlite", type=Path, required=True)
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--generated-steps", type=int, required=True)
    parser.add_argument("--request-count", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    trace = json.loads(args.trace.read_text(encoding="utf-8"))
    weighted_tpot_ms = sum(
        float(case["weight"]) * float(case["median_tpot_ms"])
        for case in trace["cases"]
    )

    connection = sqlite3.connect(args.sqlite)
    try:
        total_kernel_ns, kernel_count = connection.execute(
            "SELECT COALESCE(SUM(end-start), 0), COUNT(*) "
            "FROM CUPTI_ACTIVITY_KIND_KERNEL"
        ).fetchone()
        graph_launches = connection.execute(
            "SELECT r.start, r.end FROM CUPTI_ACTIVITY_KIND_RUNTIME r "
            "JOIN StringIds s ON s.id=r.nameId "
            "WHERE s.value='cudaGraphLaunch_v10000' ORDER BY r.start"
        ).fetchall()
    finally:
        connection.close()

    launch_durations_ms = [(end - start) / 1e6 for start, end in graph_launches]
    launch_cadences_ms = [
        (graph_launches[index][0] - graph_launches[index - 1][0]) / 1e6
        for index in range(1, len(graph_launches))
    ]
    # Inter-request boundaries are much larger than ordinary decode cadence.
    within_request_cadences_ms = [value for value in launch_cadences_ms if value < 10.0]

    kernel_ms_per_generated_step = total_kernel_ns / 1e6 / args.generated_steps
    outside_kernel_lower_bound_ms = max(0.0, weighted_tpot_ms - kernel_ms_per_generated_step)
    expected_graph_launches = args.generated_steps - args.request_count
    status = "PASS" if len(graph_launches) == expected_graph_launches else "FAIL"

    result = {
        "schema_version": "vllm-decode-cadence-bound-v1",
        "status": status,
        "scope": "Profiled batch-1 greedy run; CUDA kernel sum includes prefill and is therefore a conservative upper bound on decode kernel-active time.",
        "source": {
            "sqlite": {"path": str(args.sqlite), "sha256": digest(args.sqlite)},
            "trace": {"path": str(args.trace), "sha256": digest(args.trace)},
        },
        "generated_steps": args.generated_steps,
        "request_count": args.request_count,
        "weighted_tpot_ms": weighted_tpot_ms,
        "cuda": {
            "kernel_instances": kernel_count,
            "total_kernel_ms": total_kernel_ns / 1e6,
            "kernel_ms_per_generated_step_upper_bound": kernel_ms_per_generated_step,
            "kernel_fraction_of_tpot_upper_bound": kernel_ms_per_generated_step / weighted_tpot_ms,
            "outside_kernel_ms_per_token_lower_bound": outside_kernel_lower_bound_ms,
            "outside_kernel_fraction_of_tpot_lower_bound": outside_kernel_lower_bound_ms / weighted_tpot_ms,
            "graph_launch_count": len(graph_launches),
            "expected_graph_launch_count": expected_graph_launches,
            "graph_launch_api_duration_ms": {
                "median": statistics.median(launch_durations_ms),
                "mean": statistics.mean(launch_durations_ms),
                "p90": percentile(launch_durations_ms, 0.90),
                "max": max(launch_durations_ms),
            },
            "within_request_graph_launch_start_cadence_ms": {
                "count": len(within_request_cadences_ms),
                "median": statistics.median(within_request_cadences_ms),
                "mean": statistics.mean(within_request_cadences_ms),
                "p90": percentile(within_request_cadences_ms, 0.90),
                "max": max(within_request_cadences_ms),
            },
        },
        "bounds": {
            "ideal_delete_all_observed_gpu_kernels_speedup": weighted_tpot_ms / outside_kernel_lower_bound_ms,
            "ideal_delete_all_outside_kernel_time_speedup": weighted_tpot_ms / kernel_ms_per_generated_step,
            "qualification": "These are decomposition bounds, not achievable performance predictions; CPU work, CUDA submission and GPU work may overlap.",
        },
        "decision": "The post-lm-head frontier is no longer justified as a kernel-only search. Compare runtime orchestration or multi-token device-resident decoding before further local scan tuning.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if status == "PASS" else 2)


if __name__ == "__main__":
    main()
