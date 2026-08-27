#!/usr/bin/env python3
"""Compute a P0 receipt from raw control measurements; PASS is never self-declared."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from evidence_utils import read_object, sha256, validate_identity
from p0_utils import evaluate_p0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    data = read_object(args.input)
    if data.get("schema_version") != "p0-calibration-input-v1":
        raise ValueError("invalid P0 calibration input schema")
    errors: list[str] = []
    validate_identity(args.input.parent, data.get("environment_identity", {}), "P0 environment", errors)
    validate_identity(args.input.parent, data.get("live_sink", {}).get("evidence_identity", {}), "P0 live sink", errors)
    if errors:
        raise ValueError("; ".join(errors))
    controls = evaluate_p0(data)
    status = "PASS" if all(record["status"] == "PASS" for record in controls.values()) else "FAIL"
    receipt = {
        "schema_version": "p0-calibration-receipt-v2",
        "status": status,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "input_identity": {"path": str(args.input.resolve()), "sha256": sha256(args.input)},
        "controls": controls,
        "raw_evidence": [{"path": str(args.input.resolve()), "sha256": sha256(args.input)}],
        "environment_identity": data["environment_identity"],
        "live_sink_identity": data["live_sink"]["evidence_identity"],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": status, "output": str(args.output)}, sort_keys=True))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
