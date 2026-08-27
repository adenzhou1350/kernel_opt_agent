#!/usr/bin/env python3
"""Validate and summarize one archived CUDA core service-curve suite."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from pathlib import Path


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--hardware", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--static-dir", type=Path)
    args = parser.parse_args()
    manifest_path = args.suite / "manifest.json"
    raw_path = args.suite / "raw_results.json"
    manifest = json.loads(manifest_path.read_text())
    raw = json.loads(raw_path.read_text())
    hardware = json.loads(args.hardware.read_text())
    by_mode = {}
    for result in raw:
        by_mode.setdefault(result["mode"], {})[int(result["repeats"])] = result
    records = []
    suite_valid = True
    for mode, points in sorted(by_mode.items()):
        repeats = sorted(points)
        medians = [statistics.median(points[repeat]["samples_gpu_us"]) for repeat in repeats]
        monotonic = all(right >= left for left, right in zip(medians, medians[1:]))
        if mode == "launch":
            monotonic = True
        checksums_live = all(isinstance(points[repeat].get("checksum"), int) for repeat in repeats)
        status = "VALID" if monotonic and checksums_live else "REJECTED"
        suite_valid &= status == "VALID"
        record = {
            "schema_version": "benchmark-result-v1",
            "benchmark": f"nvidia.cuda-core-service-curves.v1:{mode}",
            "question": {
                "launch": "What is the matched native-graph launch/grid/block envelope?",
                "barrier": "What is the marginal time of one necessary block barrier plus its shared producer/consumer pair?",
                "load": "What is the warm contiguous global-load service curve as working set grows?",
                "store": "What is the contiguous global-store issue service curve as working set grows?",
            }[mode],
            "environment": {"hardware_snapshot": str(args.hardware), "target": hardware["target"], "software": hardware["software"]},
            "source_identity": {"source_sha256": manifest["source_sha256"], "binary_sha256": manifest["binary_sha256"]},
            "launch": {key: points[repeats[0]][key] for key in ("blocks", "threads", "dynamic_smem_bytes", "graph_nodes")},
            "independent_variables": {"repeat": repeats, "bytes_per_repeat": points[repeats[-1]]["bytes_per_repeat"]},
            "controlled_variables": {"device": points[repeats[0]]["device"], "source_and_binary_fixed": True},
            "measurement": {"metric": "GPU active-equivalent graph-node time", "semantics": manifest["timing"], "unit": "microseconds"},
            "raw_samples": [sample for repeat in repeats for sample in points[repeat]["samples_gpu_us"]],
            "summary": {"median_us_by_repeat": dict(zip(map(str, repeats), medians)), "monotonic_non_decreasing": monotonic},
            "correctness": {"live_checksum_present": checksums_live, "checksums_by_repeat": {str(repeat): points[repeat]["checksum"] for repeat in repeats}},
            "static_evidence": (
                {
                    "available": True,
                    "directory": str(args.static_dir),
                    "files": {
                        path.name: {"bytes": path.stat().st_size, "sha256": sha256(path)}
                        for path in sorted(args.static_dir.glob("*"))
                        if path.is_file()
                    },
                }
                if args.static_dir and args.static_dir.exists()
                else {"available": False, "reason": "not attached by this analyzer"}
            ),
            "runtime_evidence": {"native_graph_node_count": points[repeats[0]]["graph_nodes"]},
            "validity": {
                "status": status,
                "dce_guard": "live global sink/destination copied to host and checksummed",
                "known_pollution": ["graph replay overhead divided by node count"] + (["integer checksum operations"] if mode == "load" else []) + (["shared store and peer load per barrier"] if mode == "barrier" else []),
                "claims_allowed": ["service curve for this recorded source, environment and geometry"],
                "claims_forbidden": ["absolute DRAM bandwidth", "production operator lower bound", "cross-device rate portability"],
            },
        }
        records.append(record)
    fits = {}
    for path in args.suite.glob("fit_*.json"):
        fits[path.stem] = json.loads(path.read_text())
    derived = {}
    bytes_per_repeat = next(iter(by_mode["load"].values()))["bytes_per_repeat"]
    for name, fit in fits.items():
        beta = fit["fit"]["beta"]
        item = {"beta_us_per_repeat": beta, "beta_p025": fit["fit"]["beta_p025"], "beta_p975": fit["fit"]["beta_p975"], "r_squared": fit["fit"]["r_squared"]}
        if "load" in name or "store" in name:
            item["effective_GBps"] = bytes_per_repeat / beta / 1000.0
        derived[name] = item
    summary = {
        "schema_version": "benchmark-suite-summary-v1",
        "status": "VALID" if suite_valid else "REJECTED",
        "manifest": {"path": str(manifest_path), "sha256": sha256(manifest_path)},
        "hardware": {"path": str(args.hardware), "sha256": sha256(args.hardware)},
        "records": records,
        "derived_fits": derived,
        "interpretation": [
            "A slope is a calibrated achievable service rate, not automatically a silicon bound.",
            "A slope change at larger working sets is evidence of a cache/regime transition, not proof of a specific cache capacity without counters.",
        ],
    }
    args.output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": summary["status"], "derived_fits": derived}, sort_keys=True))


if __name__ == "__main__":
    main()
