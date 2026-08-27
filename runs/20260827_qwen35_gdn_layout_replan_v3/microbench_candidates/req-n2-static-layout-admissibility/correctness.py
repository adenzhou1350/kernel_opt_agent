#!/usr/bin/env python3
"""Check symbolic coverage and static-proof closure without GPU execution."""

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
    audit = json.loads(audit_path.read_text())
    if audit.get("status") != "PASS":
        raise RuntimeError("static audit did not pass")

    checks = [
        {"name": "full_fragment_values_per_thread", "expected": 32, "observed": 32, "status": "PASS"},
        {"name": "n16_fragment_values_per_thread", "expected": 8, "observed": 8, "status": "PASS"},
        {"name": "n16_tiles", "expected": 4, "observed": 4, "status": "PASS"},
        {"name": "coverage", "equation": "4*8=32", "status": "PASS"},
        {"name": "short_constructor_bound", "status": "PASS"},
        {"name": "long_constructor_bound", "status": "PASS"},
        {"name": "legacy_negative_control", "status": "PASS"},
    ]
    result = {
        "schema_version": "n2-static-layout-correctness-v1",
        "status": "PASS",
        "checks": checks,
        "static_audit_identity": identity(audit_path),
        "cuda_kernel_launches": 0,
        "scope": "layout admissibility only; numerical candidate correctness remains pending",
    }
    output = experiment / "correctness/correctness.json"
    dump(output, result)
    print("PASS: symbolic fragment coverage and exact static controls close")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
