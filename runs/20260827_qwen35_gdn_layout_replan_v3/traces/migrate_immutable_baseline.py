#!/usr/bin/env python3
"""Rebind immutable production evidence into a fresh optimization run.

This is deliberately narrower than a run copy: it carries only the frozen
operator baseline, P0 calibration inputs, exact launched baseline binary and
derived final-binary resource evidence.  Candidate, decision, approval,
budget, queue and failure state are never inherited.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


CONTRACT_FILES = (
    "operator.json",
    "workload.json",
    "hardware.json",
    "hardware_evidence.json",
)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def identity(path: Path) -> dict:
    return {"path": str(path.resolve()), "sha256": sha256(path)}


def dump(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def replace_paths(value, old: str, new: str):
    if isinstance(value, dict):
        return {key: replace_paths(item, old, new) for key, item in value.items()}
    if isinstance(value, list):
        return [replace_paths(item, old, new) for item in value]
    if isinstance(value, str):
        return value.replace(old, new)
    return value


def checked(command: list[str]) -> None:
    completed = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if completed.returncode:
        raise RuntimeError(
            f"command failed ({completed.returncode}): {command!r}\n"
            + completed.stdout
            + completed.stderr
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old-run", type=Path, required=True)
    parser.add_argument("--new-run", type=Path, required=True)
    args = parser.parse_args()
    old = args.old_run.resolve()
    new = args.new_run.resolve()
    if not old.is_dir() or not new.is_dir():
        raise ValueError("old/new run directories must exist")

    contract_hashes: dict[str, str] = {}
    for name in CONTRACT_FILES:
        old_path = old / name
        new_path = new / name
        if sha256(old_path) != sha256(new_path):
            raise ValueError(f"contract differs; evidence reuse forbidden: {name}")
        contract_hashes[name] = sha256(new_path)

    old_prefix = str(old)
    new_prefix = str(new)
    framework = new.parents[1]
    python = Path(sys.executable).resolve()

    # Immutable raw production measurements retain their byte identity.
    shutil.copytree(old / "baseline", new / "baseline", dirs_exist_ok=True)
    old_baseline = old / "models/baseline.json"
    baseline = replace_paths(json.loads(old_baseline.read_text()), old_prefix, new_prefix)

    # Recalibrate the copied P0 input after rebinding only run-local paths.
    old_p0 = old / "experiments/p0-reused"
    new_p0 = new / "experiments/p0-reused"
    shutil.copytree(old_p0 / "raw", new_p0 / "raw", dirs_exist_ok=True)
    p0_input = new_p0 / "raw/p0_input.json"
    dump(p0_input, replace_paths(json.loads(p0_input.read_text()), old_prefix, new_prefix))
    checked([
        str(python), str(framework / "scripts/calibrate_p0.py"),
        "--input", str(p0_input),
        "--output", str(new_p0 / "p0_receipt.json"),
    ])
    baseline["environment_controls"]["p0_receipt"] = identity(new_p0 / "p0_receipt.json")
    dump(new / "models/baseline.json", baseline)

    # Copy only the exact launched production binary; regenerate every derived
    # receipt under the new run so all embedded paths and hashes are local.
    source_binary = old / "static/baseline_s404_composite.cubin"
    target_binary = new / "static/baseline_s404_composite.cubin"
    target_binary.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_binary, target_binary)
    if sha256(source_binary) != sha256(target_binary):
        raise ValueError("copied production binary identity changed")

    checked([
        str(python), str(framework / "scripts/archive_final_binary_sass.py"),
        "--tool", "/usr/local/cuda/bin/cuobjdump",
        "--binary", str(target_binary),
        "--output-sass", str(new / "static/final.sass"),
        "--output-receipt", str(new / "static/disassembly_receipt.json"),
        "--vendor", "NVIDIA",
        "--device-name", "NVIDIA GeForce RTX 5090",
        "--compute-capability", "12.0",
    ])
    checked([
        str(python), str(framework / "scripts/count_sass.py"),
        "--input", str(new / "static/final.sass"),
        "--binary", str(target_binary),
        "--disassembly-receipt", str(new / "static/disassembly_receipt.json"),
        "--output", str(new / "static/sass-summary.json"),
    ])
    checked([
        str(python), str(framework / "scripts/discover_resources.py"),
        "--sass-summary", str(new / "static/sass-summary.json"),
        "--hardware-evidence", str(new / "hardware_evidence.json"),
        "--output", str(new / "models/resource_discovery.json"),
    ])

    plan_path = new / "models/microbenchmark_plan.json"
    plan = json.loads(plan_path.read_text())
    plan["levels"]["P0"].update({
        "status": "PASS",
        "reason": (
            "Immutable P0 raw evidence was rebound and recalibrated only because "
            "operator/workload/hardware/hardware-evidence hashes are identical."
        ),
        "experiments": ["p0-reused"],
        "evidence": [identity(new_p0 / "p0_receipt.json")],
    })
    dump(plan_path, plan)

    receipt = {
        "schema_version": "continuation-evidence-rebind-v2",
        "status": "PASS",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "old_run": str(old),
        "new_run": str(new),
        "identical_contract_hashes": contract_hashes,
        "scope_carried": [
            "immutable production baseline raw samples",
            "recalibrated P0 receipt from immutable raw evidence",
            "exact launched production baseline binary",
            "fresh path-local disassembly, SASS count and resource discovery",
        ],
        "scope_forbidden_and_not_carried": [
            "architecture candidate implementations",
            "candidate performance samples",
            "decision or measurability contracts",
            "experiment approvals, budgets, queues or revision allowance",
            "old run failure or phase state",
        ],
        "old_baseline_identity": identity(old_baseline),
        "new_baseline_identity": identity(new / "models/baseline.json"),
        "old_p0_identity": identity(old_p0 / "p0_receipt.json"),
        "new_p0_identity": identity(new_p0 / "p0_receipt.json"),
        "binary_identity": identity(target_binary),
        "derived_evidence": [
            identity(new / "static/disassembly_receipt.json"),
            identity(new / "static/sass-summary.json"),
            identity(new / "models/resource_discovery.json"),
        ],
    }
    dump(new / "traces/continuation_evidence_rebind.json", receipt)
    print(json.dumps({"status": "PASS", "receipt": identity(new / "traces/continuation_evidence_rebind.json")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
