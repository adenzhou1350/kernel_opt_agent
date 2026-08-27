#!/usr/bin/env python3
"""Restore two missing path-local immutable baseline identities by exact hash."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


RUN = Path("/workspace/dance/qwen35/kernel_opt_agent/runs/20260827_qwen35_gdn_layout_replan_v3")
SOURCES = {
    RUN / "traces/capture_production_baseline.py": (
        Path("/workspace/dance/qwen35/kernel_opt_agent/runs/20260827_qwen35_gdn_decision_supervised_v2/traces/capture_production_baseline.py"),
        "faf3533168710cd202ebc469c08646fec7fba9c561a59074024f39ab5f6f0114",
    ),
    RUN / "static/current_s404_composite.cubin": (
        RUN / "static/baseline_s404_composite.cubin",
        "ac0a9b859bd3506a75a06c80806f58238e1827432e87612b43bf89190f2cc04e",
    ),
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    records = []
    for destination, (source, expected) in SOURCES.items():
        if digest(source) != expected:
            raise RuntimeError(f"source hash mismatch: {source}")
        if destination.exists():
            if digest(destination) != expected:
                raise RuntimeError(f"refusing to overwrite mismatched destination: {destination}")
            action = "ALREADY_PRESENT"
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            action = "COPIED_EXACT_HASH"
        if digest(destination) != expected:
            raise RuntimeError(f"destination verification failed: {destination}")
        records.append({
            "source": str(source), "destination": str(destination),
            "sha256": expected, "action": action,
        })
    receipt = {
        "schema_version": "baseline-identity-path-restoration-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "semantic_change": False,
        "records": records,
    }
    output = RUN / "traces/baseline_identity_path_restoration.json"
    output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": "PASS", "receipt": str(output)}, sort_keys=True))


if __name__ == "__main__":
    main()
