#!/usr/bin/env python3
"""Validate official-source provenance for one target hardware manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evidence_utils import read_object, validate_hardware_evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--hardware", type=Path, help="frozen hardware.json whose exact target must match")
    args = parser.parse_args()
    errors = validate_hardware_evidence(args.manifest, args.hardware)
    data = read_object(args.manifest)
    result = {
        "status": "PASS" if not errors and data.get("status") == "READY" else "FAIL",
        "manifest": str(args.manifest.resolve()),
        "target": data.get("target_identity"),
        "errors": errors,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
