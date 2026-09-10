#!/usr/bin/env python3
"""Analyze interleaved baseline/candidate GPU samples by pair."""

from __future__ import annotations

import argparse
import csv
import json
import random
import statistics
from pathlib import Path

from deterministic_output_parity import digest, validate_parity_result


def quantile(values, fraction):
    ordered = sorted(values)
    return ordered[round((len(ordered) - 1) * fraction)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input", type=Path, required=True, help="CSV: pair,candidate,duration_us"
    )
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bootstrap", type=int, default=20000)
    parser.add_argument(
        "--parity-result",
        type=Path,
        required=True,
        help="reproducible deterministic-output-parity-result-v1",
    )
    args = parser.parse_args()
    parity = validate_parity_result(args.parity_result)
    if parity["baseline_arm"] != args.baseline:
        raise ValueError("parity result baseline_arm mismatch")
    if parity["candidate_arm"] != args.candidate:
        raise ValueError("parity result candidate_arm mismatch")
    if not parity["performance_evaluation_allowed"]:
        raise ValueError(
            "deterministic output parity failed; performance comparison is forbidden"
        )
    pairs = {}
    with args.input.open(newline="") as handle:
        for row in csv.DictReader(handle):
            pairs.setdefault(row["pair"], {})[row["candidate"]] = float(
                row["duration_us"]
            )
    complete = [
        values
        for values in pairs.values()
        if args.baseline in values and args.candidate in values
    ]
    if len(complete) < 3:
        raise ValueError("at least three complete pairs are required")
    deltas = [values[args.candidate] - values[args.baseline] for values in complete]
    improvements = [-value for value in deltas]
    rng = random.Random(20260826)
    boot = [
        statistics.median(rng.choices(deltas, k=len(deltas)))
        for _ in range(args.bootstrap)
    ]
    lo, hi = quantile(boot, 0.025), quantile(boot, 0.975)
    if hi < 0:
        decision = "ACCEPT"
        reason = "candidate is faster and paired 95% CI excludes zero"
    elif lo > 0:
        decision = "REJECT"
        reason = "candidate is slower and paired 95% CI excludes zero"
    else:
        decision = "INCONCLUSIVE"
        reason = "paired 95% CI crosses zero"
    result = {
        "schema_version": "paired-comparison-v1",
        "baseline": args.baseline,
        "candidate": args.candidate,
        "complete_pairs": len(complete),
        "delta_semantics": "candidate_us - baseline_us; negative is faster",
        "median_delta_us": statistics.median(deltas),
        "median_improvement_us": statistics.median(improvements),
        "candidate_win_rate": sum(value < 0 for value in deltas) / len(deltas),
        "bootstrap_median_delta_p025_us": lo,
        "bootstrap_median_delta_p975_us": hi,
        "correctness": "PASS",
        "deterministic_output_parity": {
            "path": str(args.parity_result),
            "sha256": digest(args.parity_result),
        },
        "decision": decision,
        "reason": reason,
        "raw_paired_deltas_us": deltas,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "decision",
                    "reason",
                    "median_delta_us",
                    "candidate_win_rate",
                )
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
