#!/usr/bin/env python3
"""Audit proof/production identities and archive the emitted proof SASS."""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

from common import candidate_dir, dump, experiment_dir, identity, production_sources, sha256


def require_pattern(text: str, pattern: str, label: str) -> None:
    if not re.search(pattern, text, flags=re.MULTILINE | re.DOTALL):
        raise RuntimeError(f"missing exact constructor/control: {label}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    run = args.run.resolve()
    source_root = candidate_dir(run)
    experiment = experiment_dir(run)
    build = experiment / "build"
    manifest_path = build / "manifest.json"
    manifest = __import__("json").loads(manifest_path.read_text())
    if manifest.get("status") != "PASS" or manifest.get("cuda_kernel_launches") != 0:
        raise RuntimeError("clean-build manifest does not prove zero launch")

    for name, path in production_sources().items():
        if manifest["production_sources"][name]["sha256"] != sha256(path):
            raise RuntimeError(f"production source changed after proof compile: {name}")
        text = path.read_text()
        require_pattern(text, r"make_layout\(\(8,\s*1,\s*1\)\).*?permutation_mnk=\(D,\s*BT,\s*D\)", f"{name} exact O1")
        require_pattern(text, r"make_fragment_C\(o1_thr\.partition_shape_C\(\(D,\s*BT\)\)\)", f"{name} exact O1 fragment")

    proof_text = (source_root / "layout_proof.py").read_text()
    require_pattern(proof_text, r"logical_divide\(output\.layout,\s*\(None,\s*None,\s*2\)\)", "actual MMA_N split")
    require_pattern(proof_text, r"make_tensor\(output\.iterator,\s*divided_layout\)", "same iterator")
    require_pattern(proof_text, r"assert\s+tile\.layout\s*==\s*prototype\.layout", "positive layout equality")
    require_pattern(proof_text, r"assert\s+output\.layout\s*!=\s*legacy_appended", "negative legacy control")

    cubin = Path(manifest["artifacts"]["cubin"]["path"])
    sass_path = experiment / "static/proof.sass"
    sass_path.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        ["/usr/local/cuda/bin/cuobjdump", "--dump-sass", str(cubin)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode:
        raise RuntimeError(completed.stdout + completed.stderr)
    sass_path.write_text(completed.stdout)

    audit = {
        "schema_version": "n2-static-layout-audit-v1",
        "status": "PASS",
        "verdict": "EXACT_LAYOUT_PREDICATE_COMPILED",
        "build_manifest_identity": identity(manifest_path),
        "binary_identity": identity(cubin),
        "sass_identity": identity(sass_path),
        "production_source_identities": manifest["production_sources"],
        "positive_controls": [
            "same eight-warp M ownership",
            "real output.iterator reused",
            "four N16 views equal exact scoreV prototype layout",
            "32 accumulator values partitioned into four disjoint 8-value views",
        ],
        "negative_controls": ["legacy single-warp append layout is unequal"],
        "cuda_kernel_launches": 0,
        "claims_allowed": ["N2 layout admissibility only"],
        "claims_forbidden": ["latency speedup", "candidate correctness", "production acceptance"],
    }
    dump(experiment / "static/instruction_audit.json", audit)
    print("PASS: exact production constructors and positive/negative layout controls are bound")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
