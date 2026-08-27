#!/usr/bin/env python3
"""Capture an immutable Nsight Compute counter-permission receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def identity(path: Path) -> dict:
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    run = args.run.resolve()
    ncu = Path("/usr/local/cuda-13.3/bin/ncu")
    command = [str(ncu), "--devices", "6", "--query-metrics"]
    completed = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    combined = completed.stdout + completed.stderr
    denied = "ERR_NVGPUCTRPERM" in combined
    output = {
        "schema_version": "ncu-counter-permission-receipt-v1",
        "status": "BLOCKED_PERMISSION" if denied else ("PASS" if completed.returncode == 0 else "FAIL"),
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "command": command,
        "exit_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "tool_identity": identity(ncu),
        "hardware_identity": identity(run / "hardware.json"),
        "required_action": "grant host-level NVIDIA performance-counter permission (for example the documented NVreg_RestrictProfilingToAdminUsers policy or equivalent container capability)" if denied else None,
        "claim_impact": "shared-bank/request counter P2 cannot close; P1 event service curves remain mechanism-only and cannot establish production utilization" if denied else None,
    }
    path = run / "experiments/req-shared-request-service/ncu_permission_receipt.json"
    path.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": output["status"], "output": str(path)}, sort_keys=True))
    return 0 if denied or completed.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
