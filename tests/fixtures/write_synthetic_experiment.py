#!/usr/bin/env python3
"""Create deterministic synthetic artifacts for the evidence-closed forward test."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def identity(path: Path) -> dict:
    return {"path": str(path), "sha256": digest(path)}


def write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n" if not isinstance(data, str) else data)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--request-id", required=True)
    parser.add_argument("--mode", choices=("build", "static", "correctness", "warmup", "measure", "analyze"), required=True)
    args = parser.parse_args()
    run = args.run.resolve()
    root = run / "experiments" / args.request_id
    raw = root / "raw"
    source = raw / "source.cu"
    binary = raw / "binary.cubin"
    sass = raw / "binary.sass"
    static_audit = root / "static/instruction_audit.json"
    correctness = raw / "correctness.json"
    environment = raw / "environment.json"
    samples_path = raw / "samples.json"
    p0_input = raw / "p0_input.json"
    p0_receipt = root / "p0_receipt.json"
    experiment = root / "experiment.json"
    result_path = root / "result.json"
    if args.mode == "build":
        write(source, "extern \"C\" __global__ void synthetic(float* out) { out[0] = 1.0f; }\n")
        binary.parent.mkdir(parents=True, exist_ok=True)
        binary.write_bytes(b"synthetic-test-cubin")
    elif args.mode == "static":
        write(sass, "Function : synthetic\n/*0000*/ MOV;\n/*0010*/ STG.E;\n/*0020*/ EXIT;\n")
        write(static_audit, {
            "schema_version": "synthetic-static-audit-v1", "status": "MATCH",
            "binary_identity": identity(binary), "sass_identity": identity(sass),
            "observed_sass": ["MOV", "STG", "EXIT"], "resource_usage": {"registers": 1},
        })
    elif args.mode == "correctness":
        write(correctness, {"status": "PASS", "checks": [{"name": "live-output", "max_abs": 0.0}]})
        write(environment, {"target": json.loads((run / "hardware.json").read_text()).get("target", {}), "status": "STABLE"})
    elif args.mode == "warmup":
        write(raw / "warmup.json", {"iterations": 10, "status": "PASS"})
    elif args.mode == "measure":
        samples = [1.00, 1.02, 0.99, 1.01, 1.00, 0.98, 1.03, 1.00, 0.99]
        write(samples_path, {"samples": samples})
        write(p0_input, {
            "schema_version": "p0-calibration-input-v1",
            "environment_identity": identity(environment),
            "live_sink": {"status": "PASS", "evidence_identity": identity(correctness)},
            "thresholds": {
                "timer_overhead_max_us": 0.2,
                "positive_minus_zero_min_us": 0.5,
                "graph_direct_relative_max": 0.05,
                "clock_cv_max": 0.01,
                "competing_load_max_percent": 1.0,
                "replication_relative_spread_max": 0.05
            },
            "samples": {
                "timer_overhead_us": [0.1] * 9,
                "zero_work_us": [0.2] * 9,
                "positive_work_us": [1.2] * 9,
                "graph_us": [1.0] * 9,
                "direct_us": [1.0] * 9,
                "clock_mhz": [1000.0] * 9,
                "competing_load_percent": [0.0] * 9,
                "independent_process_median_us": [0.99, 1.0, 1.01]
            },
            "cold_warm": {"separated": True, "cold_us": [1.2, 1.2, 1.2], "warm_us": [1.0] * 9}
        })
    elif args.mode == "analyze":
        samples = json.loads(samples_path.read_text())["samples"]
        write(result_path, {
            "schema_version": "benchmark-result-v2", "request_id": args.request_id,
            "experiment_identity": identity(experiment),
            "hardware_identity": identity(run / "hardware.json"),
            "workload_identity": identity(run / "workload.json"),
            "benchmark": "synthetic.execution-closed.v1", "question": "What is the launch envelope?",
            "environment": json.loads(environment.read_text()), "source_identity": identity(source),
            "measurement": {"metric": "gpu_active", "semantics": "kernel active", "unit": "us", "timer": "synthetic native GPU timer"},
            "raw_samples": samples, "raw_samples_identity": identity(samples_path),
            "summary": {"median_us": 1.0, "utilization_percent": 50.0, "revision": 1.0, "resolved_request_ids": []},
            "correctness": {"status": "PASS", "checks": [{"name": "live-output", "max_abs": 0.0}], "evidence_identity": identity(correctness)},
            "static_evidence": {
                "binary_identity": identity(binary), "sass_identity": identity(sass),
                "static_audit_identity": identity(static_audit), "resource_usage": {"registers": 1}
            },
            "runtime_evidence": {"warmup_identity": identity(raw / "warmup.json")},
            "measurement_system": {"p0_receipt": identity(p0_receipt)},
            "validity": {"status": "VALID", "dce_guard": "live sink", "known_pollution": [], "claims_allowed": ["synthetic matched launch"], "claims_forbidden": ["portable peak"]}
        })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
