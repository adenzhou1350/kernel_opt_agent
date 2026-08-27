#!/usr/bin/env python3
"""Small multi-process gate before dispatching the full register Graph matrix."""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess


CASES = (
    ("s01_alloc0", "alloc0", 112, 384, 58624, 32, 128),
    ("s3_alloc64", "alloc64", 112, 512, 73984, 64, 128),
    ("s01_zero", "zero", 112, 384, 58624, 1, 256),
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", required=True)
    args = parser.parse_args()
    summaries = []
    for name, variant, grid, block, smem, repeats, batches in CASES:
        runs = []
        for _ in range(4):
            command = [
                args.binary, "--mode=register", "--action=measure", "--device=6",
                f"--variant={variant}", f"--grid={grid}", f"--block={block}",
                f"--smem-bytes={smem}", f"--repeats={repeats}", f"--batches={batches}",
                "--samples=31", "--preheat-ms=500",
            ]
            runs.append(json.loads(subprocess.check_output(command, text=True)))
        medians = [statistics.median(run["gpu_us"]) for run in runs]
        spread = (max(medians) - min(medians)) / statistics.mean(medians)
        summaries.append({
            "case": name, "process_medians_us": medians, "relative_process_spread": spread,
            "maximum_within_process_relative_range": max(
                (max(run["gpu_us"]) - min(run["gpu_us"])) / statistics.median(run["gpu_us"])
                for run in runs
            ),
            "launch_paths": sorted({run["measurement_launch_path"] for run in runs}),
            "sinks": sorted({run["sink"] for run in runs}),
            "occupancy_blocks_per_sm": sorted({run["occupancy_blocks_per_sm"] for run in runs}),
        })
    passed = all(item["relative_process_spread"] <= 0.10 for item in summaries)
    print(json.dumps({"status": "PASS" if passed else "FAIL", "threshold": 0.10, "cases": summaries}, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
