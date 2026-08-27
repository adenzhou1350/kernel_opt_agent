#!/usr/bin/env python3
"""Reproducibly audit the causal validity of shared-service attempt 01."""

from __future__ import annotations

import argparse
import hashlib
import json
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
    raw = json.loads(raw_path.read_text())
    records = raw["records"]
    global_sinks = [float(item["sink"]) for item in records if item["parameters"]["variant"] == "global_request"]
    shared_sinks_by_geometry = {}
    for item in records:
        if item["parameters"]["variant"] == "shared":
            shared_sinks_by_geometry.setdefault(item["parameters"]["stage_geometry"], set()).add(float(item["sink"]))
    constant_sinks = {
        item["parameters"]["variant"]: float(item["sink"])
        for item in records if item["parameters"]["variant"].startswith("constant_")
    }
    order_labels = sorted({item.get("replicate_order") for item in records if item.get("replicate_order") is not None})
    checks = [
        {
            "check": "global_request_live_sink",
            "status": "FAIL" if global_sinks and all(value == 0.0 for value in global_sinks) else "PASS",
            "observed": global_sinks,
            "requirement": "every non-zero-work parameter row must expose a host-checked live sink",
        },
        {
            "check": "shared_address_pattern_observable",
            "status": "FAIL" if any(len(values) == 1 for values in shared_sinks_by_geometry.values()) else "PASS",
            "observed_unique_sink_count_by_geometry": {key: len(values) for key, values in shared_sinks_by_geometry.items()},
            "requirement": "stride variants must consume distinguishable input values",
        },
        {
            "check": "constant_address_pattern_observable",
            "status": "FAIL" if len(set(constant_sinks.values())) < len(constant_sinks) else "PASS",
            "observed": constant_sinks,
            "requirement": "broadcast/divergent variants must consume distinguishable constant addresses",
        },
        {
            "check": "AB_BA_order_control",
            "status": "FAIL" if order_labels != ["forward", "reverse"] else "PASS",
            "observed": order_labels,
            "requirement": "paired forward/reverse execution order is required to expose drift",
        },
    ]
    output = {
        "schema_version": "experiment-validity-review-v1",
        "request_id": "req-shared-request-service",
        "attempt": 1,
        "technical_execution": "PASS",
        "causal_validity": "REJECT",
        "checks": checks,
        "raw_identity": identity(raw_path),
        "execution_receipt_identity": identity(root / "execution_receipt.json"),
        "consequence": "No timing from this attempt may update resource service curves or production resource balance.",
    }
    output_path = root / "validity_review_attempt01.json"
    output_path.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": "REJECT", "output": str(output_path), "failed_checks": sum(c["status"] == "FAIL" for c in checks)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
