#!/usr/bin/env python3
"""Copy immutable baseline/P0 evidence into a continuation run and rebind paths."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def replace_paths(value, old: str, new: str):
    if isinstance(value, dict):
        return {key: replace_paths(item, old, new) for key, item in value.items()}
    if isinstance(value, list):
        return [replace_paths(item, old, new) for item in value]
    if isinstance(value, str):
        return value.replace(old, new)
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old-run", type=Path, required=True)
    parser.add_argument("--new-run", type=Path, required=True)
    args = parser.parse_args()
    old = args.old_run.resolve()
    new = args.new_run.resolve()
    if not old.is_dir() or not new.is_dir():
        raise ValueError("old/new run directories must exist")

    old_prefix = str(old)
    new_prefix = str(new)
    shutil.copytree(old / "baseline", new / "baseline", dirs_exist_ok=True)
    shutil.copy2(old / "traces/capture_production_baseline.py", new / "traces/capture_production_baseline.py")
    shutil.copy2(old / "static/current_s404_composite.cubin", new / "static/current_s404_composite.cubin")

    old_p0 = old / "experiments/req-p0-measurement-system"
    new_p0 = new / "experiments/p0-reused"
    shutil.copytree(old_p0 / "raw", new_p0 / "raw", dirs_exist_ok=True)
    input_path = new_p0 / "raw/p0_input.json"
    rebound = replace_paths(json.loads(input_path.read_text()), str(old_p0), str(new_p0))
    write(input_path, replace_paths(rebound, old_prefix, new_prefix))

    calibrate = Path(__file__).resolve().parents[3] / "scripts/calibrate_p0.py"
    completed = subprocess.run([
        sys.executable, str(calibrate),
        "--input", str(new_p0 / "raw/p0_input.json"),
        "--output", str(new_p0 / "p0_receipt.json"),
    ], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if completed.returncode:
        raise RuntimeError(completed.stdout + completed.stderr)

    baseline = replace_paths(json.loads((old / "models/baseline.json").read_text()), old_prefix, new_prefix)
    baseline["environment_controls"]["p0_receipt"] = {
        "path": str(new_p0 / "p0_receipt.json"),
        "sha256": digest(new_p0 / "p0_receipt.json"),
    }
    write(new / "models/baseline.json", baseline)

    plan_path = new / "models/microbenchmark_plan.json"
    plan = json.loads(plan_path.read_text())
    plan["levels"]["P0"].update({
        "status": "PASS",
        "reason": "Rebound immutable P0 evidence from the explicitly reused run; hardware/workload hashes are identical.",
        "experiments": ["p0-reused"],
        "evidence": [{"path": str(new_p0 / "p0_receipt.json"), "sha256": digest(new_p0 / "p0_receipt.json")}],
    })
    write(plan_path, plan)

    receipt = {
        "schema_version": "continuation-evidence-rebind-v1",
        "status": "PASS",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "old_run": str(old),
        "new_run": str(new),
        "identical_contract_hashes": {
            name: digest(old / name)
            for name in ("operator.json", "workload.json", "hardware.json")
            if digest(old / name) == digest(new / name)
        },
        "old_baseline_identity": {"path": str(old / "models/baseline.json"), "sha256": digest(old / "models/baseline.json")},
        "new_baseline_identity": {"path": str(new / "models/baseline.json"), "sha256": digest(new / "models/baseline.json")},
        "old_p0_identity": {"path": str(old_p0 / "p0_receipt.json"), "sha256": digest(old_p0 / "p0_receipt.json")},
        "new_p0_identity": {"path": str(new_p0 / "p0_receipt.json"), "sha256": digest(new_p0 / "p0_receipt.json")},
    }
    if len(receipt["identical_contract_hashes"]) != 3:
        raise ValueError("operator/workload/hardware identities differ; evidence reuse is forbidden")
    write(new / "traces/continuation_evidence_rebind.json", receipt)
    print(json.dumps({"status": "PASS", "receipt": str(new / "traces/continuation_evidence_rebind.json")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
