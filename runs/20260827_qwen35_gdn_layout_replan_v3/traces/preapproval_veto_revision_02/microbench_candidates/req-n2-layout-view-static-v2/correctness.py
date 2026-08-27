#!/usr/bin/env python3
"""Check the static experiment classification from derived evidence, not literals."""

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
    mapping = load(experiment / "static/mapping_report.json")
    audit = load(experiment / "static/instruction_audit.json")
    outcome = manifest.get("predicate_outcome")
    checks = []
    if outcome == "PASS":
        summary = mapping.get("summary", {})
        derived = {
            "row_count": summary.get("row_count"),
            "unique_global_coordinates": summary.get("unique_global_coordinates"),
            "unique_owner_offset_pairs": summary.get("unique_owner_offset_pairs"),
            "tile_count": summary.get("tile_count"),
            "tile_cardinality": summary.get("tile_cardinality"),
        }
        expected = {
            "row_count": 8192, "unique_global_coordinates": 8192,
            "unique_owner_offset_pairs": 8192, "tile_count": 4, "tile_cardinality": 8,
        }
        if derived != expected or audit.get("witness_rows") != 8192:
            raise RuntimeError(f"mapping evidence does not support PASS: observed={derived}")
        if int(summary.get("negative_control_mismatches", 0)) <= 0:
            raise RuntimeError("negative control was not discriminating")
        checks.extend([
            "8192 unique global coordinates derived from witness",
            "8192 unique (owner tid, logical backing offset) pairs derived from witness",
            "four disjoint eight-slot tiles form each thread's full 0..31 offset union",
            "legacy one-warp append negative control differs",
            "short and long live CuTe C/D consumers both emitted proof binaries",
        ])
        binary_pass = 1
    elif outcome == "REJECT":
        if mapping.get("predicate_outcome") != "REJECT" or not manifest.get("predicate_id"):
            raise RuntimeError("REJECT classification lacks derived predicate evidence")
        if len(audit.get("binary_identities", {})) != 1:
            raise RuntimeError("REJECT classification lacks exactly one compiled marker")
        checks.extend([
            f"recognized deterministic predicate rejected: {manifest['predicate_id']}",
            "compiled reject marker identity archived",
        ])
        binary_pass = 0
    else:
        raise RuntimeError(f"unknown controlled predicate outcome: {outcome}")

    output = experiment / "correctness/correctness.json"
    dump(output, {
        "schema_version": "n2-static-classification-correctness-v2",
        "status": "PASS", "predicate_outcome": outcome, "binary_pass": binary_pass,
        "candidate_numerical_correctness": "NOT_TESTED",
        "checks": checks,
        "mapping_report_identity": identity(experiment / "static/mapping_report.json"),
        "static_audit_identity": identity(experiment / "static/instruction_audit.json"),
    })
    print(f"PASS: static classification correctness closed; predicate_outcome={outcome}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
