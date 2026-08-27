#!/usr/bin/env python3
"""Deterministically query reusable microbenchmarks and emit a hash-bound receipt."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from evidence_utils import read_object, sha256
from experiment_utils import catalog_matches


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--resource", action="append", default=[])
    parser.add_argument("--mechanism", action="append", default=[])
    parser.add_argument("--boundary", action="append", default=[])
    parser.add_argument("--qualification", default="DRAFT")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    catalog = read_object(args.catalog)
    query = {
        "resources": sorted(set(args.resource)),
        "mechanisms": sorted(set(args.mechanism)),
        "boundaries": sorted(set(args.boundary)),
        "qualification": args.qualification,
    }
    matches = catalog_matches(catalog, query)
    receipt = {
        "schema_version": "catalog-query-receipt-v1",
        "queried_at": datetime.now(timezone.utc).isoformat(),
        "catalog_identity": {"path": str(args.catalog.resolve()), "sha256": sha256(args.catalog)},
        "query": query,
        "matching_package_ids": [entry["id"] for entry in matches],
        "decision": "REUSE" if matches else "CREATE_RUN_LOCAL",
        "selected_package_id": matches[0]["id"] if matches else None,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
