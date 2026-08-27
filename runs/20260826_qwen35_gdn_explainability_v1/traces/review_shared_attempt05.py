#!/usr/bin/env python3
"""Reproducible causal-validity review for shared-service attempt 05."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from collections import defaultdict
from pathlib import Path


def identity(path: Path) -> dict:
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    run = args.run.resolve()
    root = run / "experiments/req-shared-request-service"
    raw_path, audit_path = root / "raw/samples.json", root / "static/instruction_audit.json"
    raw, audit = json.loads(raw_path.read_text()), json.loads(audit_path.read_text())
    grouped = defaultdict(list)
    for record in raw["records"]:
        p = record["parameters"]
        grouped[(p["stage_geometry"], p["variant"], p["stride"])].append({
            "order": record["replicate_order"], "median_us": statistics.median(record["gpu_us"]),
            "sink": float(record["sink"]),
        })
    spread = {
        "/".join(map(str, key)): (max(x["median_us"] for x in values) - min(x["median_us"] for x in values)) / statistics.mean(x["median_us"] for x in values)
        for key, values in grouped.items()
    }
    nonzero_spread = {key: value for key, value in spread.items() if "/zero/" not in key}
    positive_zero = {}
    for geometry in ("s01", "s2", "s3", "post"):
        positive = min(x["median_us"] for x in grouped[(geometry, "shared", 1)])
        zero = max(x["median_us"] for x in grouped[(geometry, "zero", 1)])
        positive_zero[geometry] = positive - zero
    checks = [
        {"check": "clock_cv", "status": "PASS" if raw["clock_control"]["active_clock_cv"] <= 0.05 else "FAIL", "value": raw["clock_control"]["active_clock_cv"]},
        {"check": "four_process_ABBA", "status": "PASS" if all(len(v) == 4 and {x["order"] for x in v} == {"forward_a", "forward_b", "reverse_a", "reverse_b"} for v in grouped.values()) else "FAIL"},
        {"check": "nonzero_process_spread_below_10_percent", "status": "PASS" if max(nonzero_spread.values()) <= 0.10 else "FAIL", "maximum": max(nonzero_spread.values()), "worst_key": max(nonzero_spread, key=nonzero_spread.get)},
        {"check": "robust_positive_minus_zero_at_least_0.5us", "status": "PASS" if min(positive_zero.values()) >= 0.5 else "FAIL", "min_positive_minus_max_zero_us": positive_zero},
        {"check": "deterministic_sink", "status": "PASS" if all(len({x["sink"] for x in v}) == 1 for v in grouped.values()) else "FAIL"},
        {"check": "function_scoped_SASS", "status": "PASS" if audit.get("status") == "PASS" and audit.get("function_scoped_requirements") else "FAIL"},
    ]
    failed = [item for item in checks if item["status"] == "FAIL"]
    output = {
        "schema_version": "experiment-validity-review-v1", "request_id": "req-shared-request-service", "attempt": 5,
        "technical_execution": "PASS", "causal_validity": "REJECT" if failed else "PASS", "checks": checks,
        "raw_identity": identity(raw_path), "static_audit_identity": identity(audit_path),
        "execution_receipt_identity": identity(root / "execution_receipt.json"),
        "consequence": "Attempt 05 is preserved as stability evidence but cannot define the service curve.",
    }
    output_path = root / "validity_review_attempt05.json"
    output_path.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": output["causal_validity"], "failed_checks": len(failed), "output": str(output_path)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
