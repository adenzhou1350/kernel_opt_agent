#!/usr/bin/env python3
"""Capture immutable real-device inputs for deterministic P0 calibration."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def identity(path: Path) -> dict:
    return {"path": str(path.resolve()), "sha256": sha(path)}


def write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def smi_sample(index: int) -> dict:
    fields = "uuid,name,clocks.current.sm,utilization.gpu,temperature.gpu,power.draw"
    output = subprocess.run(
        ["nvidia-smi", "-i", str(index), f"--query-gpu={fields}", "--format=csv,noheader,nounits"],
        check=True, text=True, stdout=subprocess.PIPE,
    ).stdout.strip().split(", ")
    if len(output) != 6:
        raise RuntimeError(f"unexpected nvidia-smi output: {output}")
    return {
        "uuid": output[0], "name": output[1], "clock_mhz": float(output[2]),
        "utilization_percent": float(output[3]), "temperature_c": float(output[4]), "power_w": float(output[5]),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--sass", type=Path, required=True)
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--physical-device", type=int, required=True)
    parser.add_argument("--visible-device", type=int, default=0)
    parser.add_argument("--expected-uuid", required=True)
    args = parser.parse_args()
    raw = args.raw_dir.resolve()
    raw.mkdir(parents=True, exist_ok=True)

    before = []
    for _ in range(9):
        before.append(smi_sample(args.physical_device))
        time.sleep(0.03)
    if any(item["uuid"] != args.expected_uuid for item in before):
        raise RuntimeError("nvidia-smi UUID does not match the frozen hardware UUID")
    if max(item["utilization_percent"] for item in before) > 2.0:
        raise RuntimeError(f"competing-load gate failed before P0: {before}")

    environment = dict(os.environ)
    environment["CUDA_VISIBLE_DEVICES"] = str(args.physical_device)
    results = []
    clock_samples = []
    commands = []
    def command_for_probe() -> list[str]:
        return [
            str(args.binary.resolve()), "--device", str(args.visible_device), "--rounds", "31",
            "--warm-samples", "15", "--graph-nodes", "64", "--blocks", "170",
            "--threads", "256", "--arithmetic-repeats", "1024", "--preheat-ms", "1800",
        ]

    # A non-evidentiary pilot pays one-time driver/module startup before the
    # three independent warm-process replications. Its output remains archived.
    pilot_command = command_for_probe()
    pilot = subprocess.run(pilot_command, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment)
    pilot_result = json.loads(pilot.stdout)
    time.sleep(1.0)
    after_pilot = [smi_sample(args.physical_device) for _ in range(9)]
    if max(item["utilization_percent"] for item in after_pilot) > 2.0:
        raise RuntimeError(f"competing-load gate failed after pilot: {after_pilot}")

    for replica in range(3):
        command = command_for_probe()
        commands.append(command)
        process = subprocess.Popen(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment)
        time.sleep(0.90)
        for _ in range(9):
            sample = smi_sample(args.physical_device)
            if sample["uuid"] != args.expected_uuid:
                process.kill()
                raise RuntimeError("active clock UUID does not match frozen hardware")
            clock_samples.append(sample)
            time.sleep(0.08)
        stdout, stderr = process.communicate(timeout=60)
        if process.returncode != 0:
            raise RuntimeError(f"P0 replica {replica} failed: {stderr}")
        result = json.loads(stdout)
        result["replica"] = replica
        results.append(result)

    sass_text = args.sass.read_text(errors="replace")
    expected_groups = {
        "live_store_or_atomic": any(token in sass_text for token in ("ATOM", "RED", "STG")),
        "positive_integer_arithmetic": any(token in sass_text for token in ("IMAD", "IADD3", "UIADD3")),
        "control_exit": "EXIT" in sass_text,
    }
    sink_pass = all(int(result.get("sink_checksum", 0)) != 0 for result in results)
    identity_pass = all(
        result.get("device_name") == "NVIDIA GeForce RTX 5090"
        and result.get("compute_capability") == "12.0"
        and int(result.get("sm_count", -1)) == 170
        for result in results
    )
    correctness = {
        "schema_version": "p0-live-sink-evidence-v1",
        "status": "PASS" if sink_pass and identity_pass and all(expected_groups.values()) else "FAIL",
        "sink_checksums": [result.get("sink_checksum") for result in results],
        "device_identity_match": identity_pass,
        "expected_sass_groups": expected_groups,
        "source_identity": identity(args.source), "binary_identity": identity(args.binary), "sass_identity": identity(args.sass),
    }
    correctness_path = raw / "live_sink_correctness.json"
    write(correctness_path, correctness)
    if correctness["status"] != "PASS":
        raise RuntimeError(f"live-sink/static gate failed: {correctness}")

    primary = results[0]
    medians = [statistics.median(result["direct_us"]) for result in results]
    environment_record = {
        "schema_version": "p0-environment-v1", "captured_at": datetime.now(timezone.utc).isoformat(),
        "expected_uuid": args.expected_uuid, "physical_device_index": args.physical_device,
        "visible_device_index": args.visible_device, "pre_measurement_nvidia_smi": before,
        "active_clock_nvidia_smi": clock_samples, "commands": commands,
        "pilot_command": pilot_command, "pilot_result": pilot_result, "post_pilot_competing_load": after_pilot,
        "source_identity": identity(args.source), "binary_identity": identity(args.binary), "sass_identity": identity(args.sass),
    }
    environment_path = raw / "environment.json"
    write(environment_path, environment_record)
    raw_results_path = raw / "native_results.json"
    write(raw_results_path, {"schema_version": "p0-native-results-v1", "replicas": results})

    input_record = {
        "schema_version": "p0-calibration-input-v1",
        "environment_identity": identity(environment_path),
        "live_sink": {"status": "PASS", "evidence_identity": identity(correctness_path)},
        "thresholds": {
            "timer_overhead_max_us": 0.5,
            "positive_minus_zero_min_us": 0.5,
            "graph_direct_relative_max": 0.15,
            "clock_cv_max": 0.05,
            "competing_load_max_percent": 2.0,
            "replication_relative_spread_max": 0.10,
        },
        "samples": {
            "timer_overhead_us": primary["timer_overhead_us"],
            "zero_work_us": primary["zero_work_us"],
            "positive_work_us": primary["positive_work_us"],
            "graph_us": primary["graph_us"],
            "direct_us": primary["direct_us"],
            "clock_mhz": [item["clock_mhz"] for item in clock_samples],
            "competing_load_percent": [item["utilization_percent"] for item in before],
            "independent_process_median_us": medians,
        },
        "cold_warm": {
            "separated": True,
            "cold_us": [result["cold_region_us"][0] for result in results],
            "warm_us": primary["warm_us"],
            "semantics": "first timed post-allocation launch from each of three independent processes versus warm launches after a declared preheat",
        },
        "raw_result_identity": identity(raw_results_path),
        "pre_registered_thresholds": True,
    }
    input_path = raw / "p0_input.json"
    write(input_path, input_record)
    print(json.dumps({"status": "CAPTURED", "input": str(input_path), "replica_medians_us": medians, "active_clock_mhz": input_record["samples"]["clock_mhz"], "pre_utilization_percent": input_record["samples"]["competing_load_percent"]}, indent=2))


if __name__ == "__main__":
    main()
