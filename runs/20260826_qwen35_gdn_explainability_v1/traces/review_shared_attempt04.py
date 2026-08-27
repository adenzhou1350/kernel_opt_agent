#!/usr/bin/env python3
"""Reproducible causal-validity review for shared-service attempt 04."""

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
    grouped = defaultdict(dict)
    for record in raw["records"]:
        p = record["parameters"]
        grouped[(p["stage_geometry"], p["variant"], p["stride"])][record["replicate_order"]] = {
            "median_us": statistics.median(record["gpu_us"]), "sink": float(record["sink"]),
        }
    pair_drift = {}
    for key, values in grouped.items():
        if set(values) == {"forward", "reverse"}:
            a, b = values["forward"]["median_us"], values["reverse"]["median_us"]
            pair_drift["/".join(map(str, key))] = abs(a - b) / ((a + b) / 2)
    nonzero_drift = {key: value for key, value in pair_drift.items() if "/zero/" not in key}
    address_observable = True
    deterministic = True
    for geometry in ("s01", "s2", "s3", "post"):
        sinks = []
        for stride in (1, 2, 4, 8, 16, 32):
            values = grouped[(geometry, "shared", stride)]
            deterministic &= values["forward"]["sink"] == values["reverse"]["sink"]
            sinks.append(values["forward"]["sink"])
        address_observable &= len(set(sinks)) == len(sinks)
    constant_sinks = [grouped[("s01", variant, 1)]["forward"]["sink"] for variant in ("constant_broadcast", "constant_divergent")]
    positive_zero = {}
    for geometry in ("s01", "s2", "s3", "post"):
        positive = statistics.mean(v["median_us"] for v in grouped[(geometry, "shared", 1)].values())
        zero = statistics.mean(v["median_us"] for v in grouped[(geometry, "zero", 1)].values())
        positive_zero[geometry] = positive - zero
    checks = [
        {"check": "P0_receipt_bound", "status": "PASS" if raw.get("p0_receipt") else "FAIL"},
        {"check": "no_competing_process", "status": "PASS" if raw.get("competing_processes_before") == [] else "FAIL"},
        {"check": "active_clock_cv", "status": "PASS" if raw["clock_control"]["active_clock_cv"] <= 0.05 else "FAIL", "value": raw["clock_control"]["active_clock_cv"]},
        {"check": "function_scoped_SASS", "status": "PASS" if audit.get("status") == "PASS" and audit.get("function_scoped_requirements") else "FAIL"},
        {"check": "deterministic_sink", "status": "PASS" if deterministic else "FAIL"},
        {"check": "address_pattern_observable", "status": "PASS" if address_observable and len(set(constant_sinks)) == 2 else "FAIL"},
        {"check": "nonzero_AB_BA_drift_below_10_percent", "status": "PASS" if max(nonzero_drift.values()) <= 0.10 else "FAIL", "maximum": max(nonzero_drift.values()), "worst_key": max(nonzero_drift, key=nonzero_drift.get)},
        {"check": "positive_minus_zero_at_least_0.5us", "status": "PASS" if min(positive_zero.values()) >= 0.5 else "FAIL", "differences_us": positive_zero},
    ]
    failed = [item for item in checks if item["status"] == "FAIL"]
    output = {
        "schema_version": "experiment-validity-review-v1", "request_id": "req-shared-request-service", "attempt": 4,
        "technical_execution": "PASS", "causal_validity": "REJECT" if failed else "PASS", "checks": checks,
        "raw_identity": identity(raw_path), "static_audit_identity": identity(audit_path),
        "execution_receipt_identity": identity(root / "execution_receipt.json"),
        "consequence": "No timing from this attempt may update resource service curves or production resource balance.",
    }
    output_path = root / "validity_review_attempt04.json"
    output_path.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": output["causal_validity"], "failed_checks": len(failed), "output": str(output_path)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
