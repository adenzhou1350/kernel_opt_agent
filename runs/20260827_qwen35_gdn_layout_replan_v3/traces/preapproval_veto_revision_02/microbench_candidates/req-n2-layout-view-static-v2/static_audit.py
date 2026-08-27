#!/usr/bin/env python3
"""Revalidate identities, witness cardinality and archived proof SASS."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from common import dump, experiment_dir, identity, load, sha256, verify_production_sources


def cubin_entries(manifest: dict) -> list[tuple[str, dict]]:
    entries = []
    for name, artifacts in manifest.get("artifacts", {}).items():
        cubin = artifacts.get("cubin")
        if cubin:
            entries.append((name, cubin))
    return entries


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    run = args.run.resolve()
    experiment = experiment_dir(run)
    manifest_path = experiment / "build/manifest.json"
    manifest = load(manifest_path)
    if manifest.get("status") != "PASS" or manifest.get("cuda_kernel_launches") != 0:
        raise RuntimeError("clean-build manifest is invalid or reports dynamic execution")
    if manifest.get("production_sources") != verify_production_sources():
        raise RuntimeError("production source identity changed after clean build")
    mapping_path = Path(manifest["mapping_report_identity"]["path"])
    if sha256(mapping_path) != manifest["mapping_report_identity"]["sha256"]:
        raise RuntimeError("mapping report identity changed")
    mapping = load(mapping_path)
    witness_path = Path(mapping["witness_identity"]["path"])
    if sha256(witness_path) != mapping["witness_identity"]["sha256"]:
        raise RuntimeError("mapping witness identity changed")
    witness_rows = sum(1 for _ in witness_path.open())
    outcome = manifest["predicate_outcome"]
    if outcome == "PASS" and witness_rows != 8192:
        raise RuntimeError(f"PASS mapping witness must contain 8192 rows, observed={witness_rows}")
    if outcome == "REJECT" and not manifest.get("predicate_id"):
        raise RuntimeError("REJECT requires a precise predicate_id")

    sass_identities = {}
    for name, cubin_identity in cubin_entries(manifest):
        cubin = Path(cubin_identity["path"])
        if sha256(cubin) != cubin_identity["sha256"]:
            raise RuntimeError(f"cubin identity changed: {name}")
        completed = subprocess.run(
            ["/usr/local/cuda/bin/cuobjdump", "--dump-sass", str(cubin)],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        if completed.returncode:
            raise RuntimeError(f"cuobjdump infrastructure failure: {completed.stdout}{completed.stderr}")
        sass = experiment / f"static/{name}.sass"
        sass.write_text(completed.stdout)
        sass_identities[name] = identity(sass)
    expected_count = 2 if outcome == "PASS" else 1
    if len(sass_identities) != expected_count:
        raise RuntimeError(f"unexpected proof binary count: {len(sass_identities)}")

    audit_path = experiment / "static/instruction_audit.json"
    dump(audit_path, {
        "schema_version": "n2-static-layout-audit-v2",
        "status": "PASS", "audit_status": "PASS",
        "predicate_outcome": outcome, "binary_pass": manifest["binary_pass"],
        "predicate_id": manifest.get("predicate_id"),
        "build_manifest_identity": identity(manifest_path),
        "mapping_report_identity": identity(mapping_path),
        "witness_identity": identity(witness_path), "witness_rows": witness_rows,
        "binary_identities": {name: artifacts["cubin"] for name, artifacts in manifest["artifacts"].items()},
        "sass_identities": sass_identities,
        "production_source_identities": manifest["production_sources"],
        "compiled_callable_invocations": 0, "cuda_kernel_launches": 0, "gpu_performance_samples": 0,
        "claims_allowed": ["N2 static same-backing layout-view predicate"],
        "claims_forbidden": ["latency", "speedup", "numerical correctness", "K-loop order", "production SASS", "production acceptance"],
    })
    print(f"PASS: static audit closed; predicate_outcome={outcome}; witness_rows={witness_rows}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
