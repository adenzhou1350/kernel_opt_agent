#!/usr/bin/env python3
"""Execute one cold microbenchmark validation command and bind fresh outputs."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from evidence_utils import path_is_within, sha256


def identity(path: Path) -> dict:
    return {"path": str(path.resolve()), "sha256": sha256(path)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--process-id", required=True)
    parser.add_argument("--argv-json", required=True, help="JSON array; shell parsing is forbidden")
    parser.add_argument("--artifact", type=Path, action="append", required=True)
    parser.add_argument("--output-receipt", type=Path, required=True)
    args = parser.parse_args()
    run = args.run.resolve()
    candidate = args.candidate.resolve()
    benchmark = candidate / "benchmark.json"
    if not path_is_within(candidate, run / "microbench_candidates") or not benchmark.is_file():
        raise ValueError("candidate must be a run-local microbench candidate")
    argv = json.loads(args.argv_json)
    if not isinstance(argv, list) or not argv or not all(isinstance(item, str) and item for item in argv):
        raise ValueError("--argv-json must be a non-empty string array")
    artifacts = [path.resolve() if path.is_absolute() else (run / path).resolve() for path in args.artifact]
    if len(set(artifacts)) != len(artifacts):
        raise ValueError("expected artifacts must be unique")
    for artifact in artifacts:
        if not path_is_within(artifact, run) or path_is_within(artifact, candidate):
            raise ValueError("reproduction outputs must stay in the run but outside the source-only candidate")
    before = {path: sha256(path) if path.is_file() else None for path in artifacts}
    receipt_path = args.output_receipt.resolve()
    if not path_is_within(receipt_path, run) or path_is_within(receipt_path, candidate):
        raise ValueError("receipt must stay in the run but outside the candidate package")
    log_root = receipt_path.parent / (receipt_path.stem + ".logs")
    log_root.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc).isoformat()
    completed = subprocess.run(argv, cwd=run, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout = log_root / "stdout.txt"
    stderr = log_root / "stderr.txt"
    stdout.write_text(completed.stdout)
    stderr.write_text(completed.stderr)
    failure = None
    if completed.returncode:
        failure = f"command exited {completed.returncode}"
    stale = [str(path) for path in artifacts if not path.is_file() or (before[path] is not None and before[path] == sha256(path))]
    if stale:
        failure = f"expected outputs are missing or stale: {stale}"
    receipt = {
        "schema_version": "microbenchmark-reproduction-receipt-v1",
        "status": "FAIL" if failure else "PASS",
        "failure": failure,
        "independent_process_id": args.process_id,
        "started_at": started,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "executor_identity": {
            "path": "scripts/execute_microbench_reproduction.py",
            "sha256": sha256(Path(__file__)),
        },
        "candidate_identity": identity(benchmark),
        "commands": [{
            "argv": argv,
            "exit_code": completed.returncode,
            "stdout": identity(stdout),
            "stderr": identity(stderr),
        }],
        "artifacts": [identity(path) for path in artifacts if path.is_file()],
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = receipt_path.with_suffix(receipt_path.suffix + ".tmp")
    temporary.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    temporary.replace(receipt_path)
    print(json.dumps({"status": receipt["status"], "receipt": str(receipt_path), "failure": failure}, sort_keys=True))
    return 0 if not failure else 1


if __name__ == "__main__":
    raise SystemExit(main())
