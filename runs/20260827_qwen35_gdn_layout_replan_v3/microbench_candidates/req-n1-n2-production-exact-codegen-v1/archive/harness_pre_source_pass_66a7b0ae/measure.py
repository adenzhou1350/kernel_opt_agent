#!/usr/bin/env python3
"""Materialize four binary static outcomes; perform no timing or GPU work."""

from __future__ import annotations

import argparse
from pathlib import Path

from common import (
    CANDIDATES,
    EXPERIMENT_ROOT,
    PATHS,
    dump,
    gate,
    require_run,
    verify_bound_sources,
    verify_experiment_source_seal,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    run = require_run(args.run)
    experiment = verify_experiment_source_seal(run)
    sources = verify_bound_sources()
    build_gate = gate(EXPERIMENT_ROOT / "build/manifest.json")
    static_gate = gate(EXPERIMENT_ROOT / "static/instruction_audit.json")
    correctness_gate = gate(EXPERIMENT_ROOT / "correctness.json")
    warmup_gate = gate(EXPERIMENT_ROOT / "warmup_receipt.json")
    build = build_gate["payload"]
    static = static_gate["payload"]
    correctness = correctness_gate["payload"]

    build_entries = {
        (item.get("model_candidate_id"), item.get("production_path")): item
        for item in build["configurations"]
        if item.get("model_candidate_id")
    }
    static_entries = {
        (item["candidate_id"], item["production_path"]): item
        for item in static["candidate_results"]
    }
    records = []
    samples = []
    for model_id in CANDIDATES:
        semantic = correctness["candidate_results"][model_id]["status"]
        for path_name in PATHS:
            build_entry = build_entries[(model_id, path_name)]
            static_entry = static_entries[(model_id, path_name)]
            passed = (
                build_entry.get("status") == "PASS_CODEGEN"
                and static_entry.get("status") == "PASS"
                and semantic == "PASS"
            )
            sample = 1 if passed else 0
            samples.append(sample)
            records.append({
                "candidate_id": model_id,
                "production_path": path_name,
                "sequence": PATHS[path_name]["sequence"],
                "binary_pass": sample,
                "status": "PASS" if passed else "FAIL",
                "build_status": build_entry.get("status"),
                "static_status": static_entry.get("status"),
                "semantic_status": semantic,
                "failure_reasons": static_entry.get("reasons", [])
                or [
                    value for value in (
                        build_entry.get("status") if build_entry.get("status") != "PASS_CODEGEN" else None,
                        semantic if semantic != "PASS" else None,
                    ) if value
                ],
            })

    dump(EXPERIMENT_ROOT / "raw/static_outcomes.json", {
        "schema_version": "qwen35-n1-n2-codegen-raw-v1",
        "status": "PASS",
        "experiment_identity": experiment,
        "bound_sources": sources,
        "upstream_gates": {
            "build": build_gate["identity"],
            "static": static_gate["identity"],
            "correctness": correctness_gate["identity"],
            "warmup": warmup_gate["identity"],
        },
        "timer": "none_compile_sass_resource",
        "unit": "binary_pass_by_candidate",
        "samples": samples,
        "records": records,
        "compiled_callable_invocations": 0,
        "cuda_kernel_launches": 0,
        "gpu_timers": 0,
        "performance_samples": 0,
    })
    print("PASS: four static binary outcomes emitted; CUDA launches=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
