#!/usr/bin/env python3
"""Write deterministic synthetic promotion check results for repository tests."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--check", action="append", required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    candidate_identity = {
        "path": str(args.candidate.resolve()),
        "sha256": hashlib.sha256(args.candidate.read_bytes()).hexdigest(),
    }
    for check_id in args.check:
        (args.output_dir / f"{check_id}.json").write_text(json.dumps({
            "schema_version": "microbenchmark-check-result-v1",
            "check_id": check_id,
            "status": "PASS",
            "candidate_identity": candidate_identity,
            "method": "deterministic synthetic auditor",
            "conclusion": f"{check_id} passed deterministic synthetic validation",
        }))
    marker = args.output_dir / "run-marker.json"
    marker.write_text(json.dumps({"status": "PASS", "checks": sorted(args.check)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
