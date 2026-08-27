#!/usr/bin/env python3
"""Validate one JSON artifact against the repository's enforced schema subset."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from schema_utils import validate_json_file


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instance", type=Path, required=True)
    parser.add_argument("--schema", type=Path, required=True)
    args = parser.parse_args()
    errors = validate_json_file(args.instance, args.schema)
    print(json.dumps({"status": "PASS" if not errors else "FAIL", "instance": str(args.instance), "schema": str(args.schema), "errors": errors}, indent=2, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
