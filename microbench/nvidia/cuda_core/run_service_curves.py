#!/usr/bin/env python3
"""Run the CUDA particle benchmark over a repeat grid and archive raw data."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import statistics
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", type=int, default=0)
    parser.add_argument("--modes", default="launch,barrier,load,store")
    parser.add_argument("--repeats", default="0,1,2,4,8,16")
    parser.add_argument("--blocks", type=int, default=0)
    parser.add_argument("--threads", type=int, default=256)
    parser.add_argument("--bytes-per-repeat", type=int, default=16 << 20)
    parser.add_argument("--dynamic-smem", type=int, default=0)
    parser.add_argument("--rounds", type=int, default=25)
    parser.add_argument("--graph-nodes", type=int, default=128)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    source = Path(__file__).with_name("particle_bench.cu")
    modes = args.modes.split(",")
    repeats = [int(value) for value in args.repeats.split(",")]
    raw = []
    csv_rows = []
    for mode in modes:
        for repeat in repeats:
            command = [
                str(args.binary), "--mode", mode, "--device", str(args.device),
                "--blocks", str(args.blocks), "--threads", str(args.threads),
                "--repeats", str(repeat), "--bytes-per-repeat", str(args.bytes_per_repeat),
                "--dynamic-smem", str(args.dynamic_smem), "--rounds", str(args.rounds),
                "--graph-nodes", str(args.graph_nodes),
            ]
            result = json.loads(subprocess.run(command, check=True, text=True, stdout=subprocess.PIPE).stdout)
            result["command"] = command
            result["source_sha256"] = sha256(source)
            result["binary_sha256"] = sha256(args.binary)
            raw.append(result)
            for sample in result["samples_gpu_us"]:
                csv_rows.append({"mode": mode, "repeat": repeat, "gpu_us": sample})
            print(json.dumps({"mode": mode, "repeat": repeat, "median_gpu_us": statistics.median(result["samples_gpu_us"]), "checksum": result["checksum"]}, sort_keys=True), flush=True)
    manifest = {
        "schema_version": "cuda-particle-suite-v1",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source": str(source),
        "source_sha256": sha256(source),
        "binary": str(args.binary),
        "binary_sha256": sha256(args.binary),
        "modes": modes,
        "repeats": repeats,
        "timing": "native CUDA graph with N kernel nodes, event duration divided by N",
        "validity_gate": "Each mode/repeat must be monotonic where work increases; checksum must be live and source/binary identities fixed.",
    }
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    (args.output / "raw_results.json").write_text(json.dumps(raw, indent=2, sort_keys=True) + "\n")
    with (args.output / "samples.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("mode", "repeat", "gpu_us"))
        writer.writeheader()
        writer.writerows(csv_rows)


if __name__ == "__main__":
    main()
