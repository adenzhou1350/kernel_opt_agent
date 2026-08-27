#!/usr/bin/env python3
"""Causal-validity review for shared-service attempt 02."""

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
    raw_path = root / "raw/samples.json"
    audit_path = root / "static/instruction_audit.json"
    raw = json.loads(raw_path.read_text())
    audit = json.loads(audit_path.read_text())
    paired = defaultdict(dict)
    for record in raw["records"]:
        p = record["parameters"]
        key = (p["stage_geometry"], p["variant"], p["stride"])
        paired[key][record["replicate_order"]] = statistics.median(record["gpu_us"])
    drift = {
        "/".join(map(str, key)): abs(values["forward"] - values["reverse"]) / ((values["forward"] + values["reverse"]) / 2)
        for key, values in paired.items() if set(values) == {"forward", "reverse"}
    }
    constants = [record for record in raw["records"] if record["parameters"]["variant"].startswith("constant_")]
    constant_sinks = {record["parameters"]["variant"]: record["sink"] for record in constants}
    checks = [
        {"check": "live_sink", "status": "PASS" if all(r["parameters"]["variant"] == "zero" or abs(float(r["sink"])) > 0 for r in raw["records"]) else "FAIL"},
        {"check": "AB_BA_order", "status": "PASS" if all(set(v) == {"forward", "reverse"} for v in paired.values()) else "FAIL"},
        {"check": "paired_drift_below_10_percent", "status": "PASS" if drift and max(drift.values()) <= 0.10 else "FAIL", "maximum_relative_drift": max(drift.values()), "worst_key": max(drift, key=drift.get)},
        {"check": "constant_address_observable", "status": "PASS" if len(set(map(float, constant_sinks.values()))) == len(constant_sinks) else "FAIL", "observed": constant_sinks},
        {"check": "function_scoped_static_audit", "status": "FAIL" if "final acceptance will require" in audit.get("note", "") else "PASS", "observed_note": audit.get("note")},
        {"check": "deterministic_output", "status": "FAIL", "reason": "shared/constant kernels use cross-warp atomic accumulation, so sink variation cannot prove address variation"},
    ]
    failed = [item for item in checks if item["status"] == "FAIL"]
    output = {
        "schema_version": "experiment-validity-review-v1", "request_id": "req-shared-request-service", "attempt": 2,
        "technical_execution": "PASS", "causal_validity": "REJECT" if failed else "PASS", "checks": checks,
        "raw_identity": identity(raw_path), "static_audit_identity": identity(audit_path),
        "execution_receipt_identity": identity(root / "execution_receipt.json"),
        "consequence": "No timing from this attempt may update resource service curves or production resource balance.",
    }
    output_path = root / "validity_review_attempt02.json"
    output_path.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": output["causal_validity"], "failed_checks": len(failed), "output": str(output_path)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
