#!/usr/bin/env python3
"""Serialize one deterministic short and one deterministic long observation."""

from __future__ import annotations

import argparse
from pathlib import Path

from common import dump, experiment_dir, identity, load


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    experiment = experiment_dir(args.run.resolve())
    manifest = load(experiment / "build/manifest.json")
    control_path = experiment / "controls/no_gpu_warmup.json"
    control = load(control_path)
    if control.get("status") != "PASS" or manifest.get("status") != "PASS":
        raise RuntimeError("static observation prerequisites did not pass")
    value = float(manifest["binary_pass"])
    observations = [
        {"production_path": "short", "value": value, "unit": "binary_pass", "independent_timing_sample": False},
        {"production_path": "long", "value": value, "unit": "binary_pass", "independent_timing_sample": False},
    ]
    output = experiment / "raw/samples.json"
    dump(output, {
        "schema_version": "deterministic-static-observations-v1",
        "metric": "n2_layout_view_feasible", "timer": "none_compiler_typecheck",
        "unit": "binary_pass", "samples": [item["value"] for item in observations],
        "observations": observations, "aggregate": "logical_and(short,long)",
        "duplicated_samples": False, "statistical_interpretation": "FORBIDDEN",
        "cuda_kernel_launches": 0, "gpu_performance_samples": 0,
        "control_identity": identity(control_path),
    })
    print(f"PASS: wrote two path-specific deterministic observations value={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
