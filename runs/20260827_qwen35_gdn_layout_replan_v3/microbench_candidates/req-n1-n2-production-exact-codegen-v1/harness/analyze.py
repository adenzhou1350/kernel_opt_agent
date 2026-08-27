#!/usr/bin/env python3
"""Finalize independent N1/N2 PASS/FAIL outcomes without ranking performance."""

from __future__ import annotations

import argparse
from pathlib import Path

from common import (
    CANDIDATE_PACKAGE,
    EXPERIMENT_ROOT,
    REQUEST_ID,
    dump,
    gate,
    identity,
    require_run,
    verify_bound_sources,
    verify_experiment_source_seal,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    run = require_run(args.run)
    experiment_identity = verify_experiment_source_seal(run)
    verify_bound_sources()
    build = gate(EXPERIMENT_ROOT / "build/manifest.json")
    static = gate(EXPERIMENT_ROOT / "static/instruction_audit.json")
    correctness = gate(EXPERIMENT_ROOT / "correctness.json")
    warmup = gate(EXPERIMENT_ROOT / "warmup_receipt.json")
    raw_gate = gate(EXPERIMENT_ROOT / "raw/static_outcomes.json")
    raw = raw_gate["payload"]

    candidate_summary = {}
    for candidate_id in ("N1", "N2"):
        records = [entry for entry in raw["records"] if entry["candidate_id"] == candidate_id]
        passed = all(entry["binary_pass"] == 1 for entry in records)
        candidate_summary[candidate_id] = {
            "status": "PASS" if passed else "FAIL",
            "paths": records,
            "scope": "production-exact compile/final-SASS/resource admission only",
        }

    p0_path = run / "experiments/p0-reused/p0_receipt.json"
    experiment = (EXPERIMENT_ROOT / "experiment.json")
    commands = __import__("json").loads(experiment.read_text())["commands"]
    dump(EXPERIMENT_ROOT / "reproduction.json", {
        "schema_version": "qwen35-n1-n2-codegen-reproduction-v1",
        "status": "PASS",
        "experiment_identity": experiment_identity,
        "commands": commands,
        "zero_gpu_execution": True,
        "note": "Execution requires a distinct GLOBAL_SUPERVISOR dispatch approval.",
    })

    result = {
        "schema_version": "benchmark-result-v2",
        "request_id": REQUEST_ID,
        "experiment_identity": experiment_identity,
        "hardware_identity": identity(run / "hardware.json"),
        "workload_identity": identity(run / "workload.json"),
        "benchmark": "qwen35-n1-n2-production-exact-codegen-gate",
        "question": (
            "Do N1 causal-QK and N2 direct-view dual-causal production "
            "implementations compile to the required final SASS within hard resources?"
        ),
        "environment": {
            "target_arch": "sm_120a",
            "runtime_device_execution": "NONE",
        },
        "source_identity": identity(CANDIDATE_PACKAGE / "CANDIDATE_CONTRACT.md"),
        "launch": {
            "compiled_callable_invocations": 0,
            "cuda_kernel_launches": 0,
        },
        "independent_variables": {
            "N1": "causal QK only",
            "N2": "causal QK plus eight-warp same-backing direct-view scoreV",
        },
        "controlled_variables": {
            "paths": ["short S404", "long S1024"],
            "production_abi_grid_block_bound": True,
            "toolchain_hash_bound": True,
        },
        "measurement": {
            "metric": "candidate path codegen/SASS/resource admission",
            "semantics": "one deterministic binary predicate per candidate/path",
            "unit": "binary_pass_by_candidate",
            "timer": "none_compile_sass_resource",
        },
        "raw_samples": raw["samples"],
        "raw_samples_identity": raw_gate["identity"],
        "summary": {
            "candidate_results": candidate_summary,
            "performance_ranking": "NOT_AUTHORIZED",
        },
        "correctness": {
            "status": "PASS",
            "checks": {
                "static_classification_completed": True,
                "candidate_semantic_results": correctness["payload"]["candidate_results"],
                "numerical_correctness_deferred": True,
            },
            "evidence_identity": correctness["identity"],
        },
        "static_evidence": {
            "binary_identity": build["identity"],
            "sass_identity": static["identity"],
            "static_audit_identity": static["identity"],
            "resource_usage": {
                "hard_caps_applied": True,
                "candidate_results": static["payload"]["candidate_results"],
            },
        },
        "runtime_evidence": {
            "compiled_callable_invocations": 0,
            "cuda_kernel_launches": 0,
            "gpu_timers": 0,
            "performance_samples": 0,
            "warmup_identity": warmup["identity"],
        },
        "measurement_system": {"p0_receipt": identity(p0_path)},
        "validity": {
            "status": "VALID",
            "dce_guard": "final cubin SASS and distinct binary identities",
            "known_pollution": [],
            "claims_allowed": [
                "candidate-specific production-exact codegen admission",
                "final-binary static HMMA delta",
                "register/shared/stack/local hard-gate result",
            ],
            "claims_forbidden": [
                "numerical correctness",
                "GPU latency or speedup",
                "dynamic executed instruction count",
                "production acceptance",
                "candidate performance ranking",
            ],
        },
    }
    dump(EXPERIMENT_ROOT / "result.json", result)
    print("PASS: independent N1/N2 static results finalized; CUDA launches=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
