#!/usr/bin/env python3
"""Create a schema-valid result restricted to the static admission claim."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from common import candidate_dir, dump, experiment_dir, identity


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    run = args.run.resolve()
    experiment = experiment_dir(run)
    experiment_path = experiment / "experiment.json"
    raw_path = experiment / "raw/samples.json"
    correctness_path = experiment / "correctness/correctness.json"
    audit_path = experiment / "static/instruction_audit.json"
    manifest_path = experiment / "build/manifest.json"
    raw = json.loads(raw_path.read_text())
    correctness = json.loads(correctness_path.read_text())
    audit = json.loads(audit_path.read_text())
    manifest = json.loads(manifest_path.read_text())
    if raw["samples"] != [1.0] * 9 or correctness["status"] != "PASS" or audit["status"] != "PASS":
        raise RuntimeError("static predicate evidence is not unanimously PASS")

    p0 = run / "experiments/p0-reused/p0_receipt.json"
    result = {
        "schema_version": "benchmark-result-v2",
        "request_id": "req-n2-static-layout-admissibility",
        "experiment_identity": identity(experiment_path),
        "hardware_identity": identity(run / "hardware.json"),
        "workload_identity": identity(run / "workload.json"),
        "benchmark": "CuTe exact accumulator N16 same-iterator layout proof",
        "question": "Does exact production O1 admit the N2 scoreV N16 view without transport?",
        "environment": {"target_arch": "sm_120a", "cuda_kernel_launches": 0, "gpu_performance_samples": 0},
        "source_identity": identity(candidate_dir(run) / "layout_proof.py"),
        "measurement": {
            "metric": "exact_layout_predicate",
            "semantics": "one means compiler/type proof passed; values are not timing observations",
            "unit": "binary_pass",
            "timer": "none_compiler_typecheck",
        },
        "raw_samples": raw["samples"],
        "raw_samples_identity": identity(raw_path),
        "summary": {
            "static_admissibility": "PASS",
            "n2_disposition": "ADMIT_TO_BOUND_RANKING_ONLY",
            "cuda_kernel_launches": 0,
            "gpu_performance_samples": 0,
        },
        "correctness": {"status": "PASS", "checks": correctness["checks"], "evidence_identity": identity(correctness_path)},
        "static_evidence": {
            "binary_identity": manifest["artifacts"]["cubin"],
            "sass_identity": audit["sass_identity"],
            "static_audit_identity": identity(audit_path),
            "resource_usage": {"claim": "not a production kernel", "transport_allocations": 0, "cuda_kernel_launches": 0},
        },
        "runtime_evidence": {"compiled_callable_invocations": 0, "cuda_kernel_launches": 0},
        "measurement_system": {"p0_receipt": identity(p0)},
        "validity": {
            "status": "VALID",
            "dce_guard": "compile-time positive and negative layout assertions; emitted proof cubin/SASS archived",
            "known_pollution": [],
            "claims_allowed": ["N2 static layout admissibility"],
            "claims_forbidden": ["GPU latency", "speedup", "numerical candidate correctness", "production acceptance"],
        },
    }
    dump(experiment / "result.json", result)
    print("PASS: N2 admitted only to bound ranking; no latency or production claim")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
