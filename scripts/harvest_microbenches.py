#!/usr/bin/env python3
"""Audit or promote every reusable benchmark candidate in one optimization run."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    default_root = Path(__file__).resolve().parents[1]
    parser.add_argument("--root", type=Path, default=default_root)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--promote", action="store_true")
    args = parser.parse_args()

    root = args.root.resolve()
    run = args.run.resolve()
    script_dir = Path(__file__).resolve().parent
    candidates = run / "microbench_candidates"
    if not candidates.is_dir():
        raise ValueError(f"missing candidate directory: {candidates}")
    results = []
    failed = False
    for candidate in sorted(path for path in candidates.iterdir() if path.is_dir()):
        slug = candidate.name
        evidence = candidates / f"{slug}.promotion.json"
        receipt = candidates / f"{slug}.receipt.json"
        if receipt.exists():
            results.append({"candidate": slug, "status": "ALREADY_PUBLISHED", "receipt": str(receipt)})
            continue
        command = [
            sys.executable,
            str(script_dir / "promote_microbench.py"),
            "--root",
            str(root),
            "--candidate",
            str(candidate),
            "--evidence",
            str(evidence),
        ]
        if not args.promote:
            command.append("--check-only")
        completed = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if completed.returncode:
            failed = True
            results.append({"candidate": slug, "status": "RETAINED_RUN_LOCAL", "error": completed.stdout.strip() or completed.stderr.strip()})
        else:
            results.append(json.loads(completed.stdout))
    if args.promote and not failed:
        audit = subprocess.run(
            [sys.executable, str(script_dir / "audit_repository.py"), "--root", str(root)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if audit.returncode:
            failed = True
            results.append({"status": "REPOSITORY_AUDIT_FAILED", "error": audit.stdout.strip() or audit.stderr.strip()})
        else:
            results.append({"status": "REPOSITORY_AUDIT_PASS"})
    print(json.dumps({"run": str(run), "mode": "PROMOTE" if args.promote else "AUDIT", "results": results}, indent=2, sort_keys=True))
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"ERROR: {error}")
        raise SystemExit(1)
