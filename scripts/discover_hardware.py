#!/usr/bin/env python3
"""Create a provenance-rich NVIDIA hardware snapshot without invented fields."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


QUERY_FIELDS = [
    "index", "name", "uuid", "compute_cap", "driver_version", "memory.total",
    "memory.used", "utilization.gpu", "clocks.current.sm", "clocks.max.sm",
    "clocks.current.memory", "clocks.max.memory", "power.draw", "power.limit",
]
TOOLS = ("nvidia-smi", "nvcc", "ptxas", "nvdisasm", "cuobjdump", "ncu", "nsys")


def command_output(command: list[str]) -> str:
    return subprocess.run(command, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.strip()


def find_tool(name: str) -> str | None:
    direct = shutil.which(name)
    if direct:
        return direct
    candidates = []
    cuda_home = os.environ.get("CUDA_HOME")
    if cuda_home:
        candidates.append(Path(cuda_home) / "bin" / name)
    candidates.append(Path("/usr/local/cuda/bin") / name)
    candidates.extend(
        path / "bin" / name
        for path in sorted(Path("/usr/local").glob("cuda-*"), reverse=True)
    )
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def number(value: str, unit: str, multiplier: float = 1.0):
    cleaned = value.replace(unit, "").strip()
    if cleaned in ("N/A", "[Not Supported]", ""):
        return None
    try:
        return float(cleaned) * multiplier
    except ValueError:
        return None


def torch_software() -> dict:
    try:
        import torch
        return {"torch": torch.__version__, "torch_cuda_runtime": torch.version.cuda}
    except Exception:
        return {}


def official_cuda_properties(device: int, nvcc: str | None) -> tuple[dict, dict]:
    if not nvcc:
        return {}, {"status": "UNAVAILABLE", "reason": "nvcc not found; capacity fields remain unknown"}
    source = Path(__file__).with_name("cuda_device_query.cu")
    with tempfile.TemporaryDirectory(prefix="kernel-opt-device-query-") as temporary:
        binary = Path(temporary) / "cuda_device_query"
        compile_command = [nvcc, "-O2", str(source), "-o", str(binary)]
        try:
            subprocess.run(compile_command, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            run_command = [str(binary), str(device)]
            data = json.loads(command_output(run_command))
            provenance = {
                "status": "PASS",
                "authority": "VENDOR_OFFICIAL_TOOL",
                "api": "cudaGetDeviceProperties",
                "source": str(source),
                "compile_command": compile_command,
                "run_command": run_command,
            }
            return data, provenance
        except Exception as error:
            return {}, {"status": "FAILED", "reason": repr(error), "source": str(source)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", type=int, default=0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    smi = find_tool("nvidia-smi")
    if not smi:
        raise RuntimeError("nvidia-smi is required by the NVIDIA adapter")
    query = [smi, f"--query-gpu={','.join(QUERY_FIELDS)}", "--format=csv,noheader,nounits"]
    rows = command_output(query).splitlines()
    if args.device >= len(rows):
        raise ValueError(f"device index {args.device} not found; detected {len(rows)} devices")
    values = [value.strip() for value in rows[args.device].split(",")]
    if len(values) != len(QUERY_FIELDS):
        raise RuntimeError(f"unexpected nvidia-smi row: {rows[args.device]}")
    raw = dict(zip(QUERY_FIELDS, values))
    tool_paths = {name: find_tool(name) for name in TOOLS}
    cuda_data, cuda_query = official_cuda_properties(args.device, tool_paths["nvcc"])
    target = {
        "vendor": "NVIDIA",
        "device_index": args.device,
        "device_name": raw["name"],
        "uuid": raw["uuid"],
        "compute_capability": raw["compute_cap"],
        **cuda_data,
    }
    if target.get("memory_bytes") is None:
        target["memory_bytes"] = int(number(raw["memory.total"], "", 1024 * 1024) or 0) or None
    tools = {name: {"available": path is not None, "path": path} for name, path in tool_paths.items()}
    nvcc_version = None
    if tool_paths["nvcc"]:
        try:
            nvcc_version = command_output([tool_paths["nvcc"], "--version"]).splitlines()[-1]
        except Exception as error:
            nvcc_version = f"query failed: {error!r}"
    snapshot = {
        "schema_version": "hardware-snapshot-v1",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "host": {"hostname": platform.node(), "platform": platform.platform(), "python": platform.python_version()},
        "target": target,
        "software": {"driver": raw["driver_version"], "nvcc": nvcc_version, **torch_software()},
        "power_clock": {
            "power_draw_w": number(raw["power.draw"], ""),
            "power_limit_w": number(raw["power.limit"], ""),
            "sm_clock_current_mhz": number(raw["clocks.current.sm"], ""),
            "sm_clock_max_mhz": number(raw["clocks.max.sm"], ""),
            "memory_clock_current_mhz": number(raw["clocks.current.memory"], ""),
            "memory_clock_max_mhz": number(raw["clocks.max.memory"], ""),
            "policy": "observed-only; no clock or power mutation performed",
        },
        "tools": tools,
        "competing_load": {
            "gpu_utilization_percent": number(raw["utilization.gpu"], ""),
            "memory_used_mib": number(raw["memory.used"], ""),
        },
        "provenance": {
            "queries": [" ".join(query), "cudaGetDeviceProperties via scripts/cuda_device_query.cu"],
            "field_authority": {
                "nvidia_smi": "VENDOR_OFFICIAL_TOOL",
                "cuda_device_properties": cuda_query,
                "torch": "software version only; no hardware capacity field is accepted from torch"
            }
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(args.output), "target": target}, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
