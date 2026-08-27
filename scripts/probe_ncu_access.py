#!/usr/bin/env python3
"""Probe Nsight Compute counter access and archive the exact result."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ncu", default="ncu")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if not args.command:
        raise ValueError("a target command is required after --output")
    profiler_command = [args.ncu, "--set", "basic", "--launch-count", "1", *args.command]
    completed = subprocess.run(profiler_command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    combined = completed.stdout + "\n" + completed.stderr
    if "ERR_NVGPUCTRPERM" in combined:
        status = "DENIED"
    elif completed.returncode == 0 and "==ERROR==" not in combined:
        status = "AVAILABLE"
    else:
        status = "INCONCLUSIVE"
    result = {
        "schema_version": "ncu-counter-access-probe-v1",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "returncode": completed.returncode,
        "command": profiler_command,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "interpretation": "Tool installation and performance-counter permission are separate capabilities.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(args.output), "status": status}, sort_keys=True))


if __name__ == "__main__":
    main()
