#!/usr/bin/env python3
"""Run the disassembler and create a hash-bound final-binary SASS receipt."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from evidence_utils import sha256


def compatible_architecture_codes(compute_capability: str) -> set[str]:
    """Return exact generic and architecture-specific cubin targets for a CC."""
    generic = "sm_" + compute_capability.replace(".", "")
    return {generic.lower(), (generic + "a").lower()}


def atomic_text(path: Path, value: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value)
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--output-sass", type=Path, required=True)
    parser.add_argument("--output-receipt", type=Path, required=True)
    parser.add_argument("--tool", default="cuobjdump")
    parser.add_argument("--vendor", required=True)
    parser.add_argument("--device-name", required=True)
    parser.add_argument("--compute-capability", required=True)
    parser.add_argument("--symbol", action="append", default=[])
    args = parser.parse_args()
    binary = args.binary.resolve()
    if not binary.is_file():
        raise FileNotFoundError(binary)
    tool = shutil.which(args.tool) or (str(Path(args.tool).resolve()) if Path(args.tool).is_file() else None)
    if not tool:
        raise FileNotFoundError(args.tool)
    version_command = [tool, "--version"]
    version = subprocess.run(version_command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT).stdout.strip()
    command = [tool, "--dump-sass", str(binary)]
    architecture_command = [tool, "--list-elf", str(binary)]
    architecture = subprocess.run(architecture_command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    architecture_codes = sorted(set(re.findall(r"\bsm_[0-9]+[a-z]?\b", architecture.stdout + "\n" + architecture.stderr, re.IGNORECASE)))
    compatible_architectures = compatible_architecture_codes(args.compute_capability)
    discovered_architectures = {item.lower() for item in architecture_codes}
    matched_architectures = sorted(compatible_architectures & discovered_architectures)
    if architecture.returncode or not matched_architectures:
        raise RuntimeError(
            "binary architecture probe does not contain an exact compatible "
            f"target from {sorted(compatible_architectures)}: "
            f"{architecture.stdout}{architecture.stderr}"
        )
    completed = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if completed.returncode or not completed.stdout.strip():
        raise RuntimeError(f"disassembly failed: {completed.stderr}")
    args.output_sass.parent.mkdir(parents=True, exist_ok=True)
    atomic_text(args.output_sass, completed.stdout)
    receipt = {
        "schema_version": "final-binary-disassembly-receipt-v1",
        "status": "PASS",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "command": command,
        "exit_code": completed.returncode,
        "stderr": completed.stderr,
        "tool": {"path": tool, "sha256": sha256(Path(tool)), "version_command": version_command, "version": version},
        "architecture_probe": {
            "command": architecture_command, "exit_code": architecture.returncode,
            "stdout": architecture.stdout, "stderr": architecture.stderr,
            "discovered_architecture_codes": architecture_codes,
        },
        "target": {
            "vendor": args.vendor,
            "device_name": args.device_name,
            "compute_capability": args.compute_capability,
            "architecture_code": matched_architectures[0],
            "compatible_architecture_codes": sorted(compatible_architectures),
        },
        "symbols": sorted(set(args.symbol)),
        "binary_identity": {"path": str(binary), "sha256": sha256(binary)},
        "sass_identity": {"path": str(args.output_sass.resolve()), "sha256": sha256(args.output_sass)},
    }
    args.output_receipt.parent.mkdir(parents=True, exist_ok=True)
    atomic_text(args.output_receipt, json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": "PASS", "sass": str(args.output_sass), "receipt": str(args.output_receipt)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
