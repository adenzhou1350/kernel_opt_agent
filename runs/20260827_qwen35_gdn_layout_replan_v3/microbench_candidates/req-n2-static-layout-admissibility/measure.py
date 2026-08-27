#!/usr/bin/env python3
"""Emit repeated binary static-predicate observations, never timing samples."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from common import dump, experiment_dir, identity


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    run = args.run.resolve()
    experiment = experiment_dir(run)
    audit_path = experiment / "static/instruction_audit.json"
    correctness_path = experiment / "correctness/correctness.json"
    audit = json.loads(audit_path.read_text())
    correctness = json.loads(correctness_path.read_text())
    passed = audit.get("status") == "PASS" and correctness.get("status") == "PASS"
    samples = [1.0 if passed else 0.0] * 9
    output = experiment / "raw/samples.json"
    dump(output, {
        "schema_version": "static-predicate-samples-v1",
        "samples": samples,
        "metric": "exact_layout_predicate",
        "unit": "binary_pass",
        "timer": "none",
        "gpu_performance_samples": 0,
        "cuda_kernel_launches": 0,
        "static_audit_identity": identity(audit_path),
        "correctness_identity": identity(correctness_path),
    })
    if not passed:
        raise RuntimeError("layout predicate failed")
    print("PASS: nine repeated static predicate records emitted; GPU timing samples=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
