#!/usr/bin/env python3
"""Populate every queued experiment with executable, hash-bound commands."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
from pathlib import Path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def identity(path: Path) -> dict:
    return {"path": str(path.resolve()), "sha256": sha(path)}


def write(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def memory_bytes(S: int) -> int:
    H, D, C, b, f = 16, 128, 64, 2, 4
    J, P = math.ceil(S / C), math.ceil(S / C) * C
    R, Rp, E, Ep, HS = S * H, P * H, S * H * D, P * H * D, J * H * D * D
    return (
        (4*b*E + 3*b*Ep + 2*b*R + f*Rp + 2*f*H)
        + (4*b*Ep + f*Rp + b*HS)
        + (2*b*E + 2*b*Ep + f*Rp + b*HS)
        + (3*b*E + b*D)
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--python", default="/workspace/dance/qwen35/.venv-cu13/bin/python")
    parser.add_argument("--request-id", action="append", dest="request_ids")
    args = parser.parse_args()
    run = args.run.resolve()
    driver = run / "traces/experiment_driver.py"
    source = run / "traces/resource_probe.cu"
    if not driver.is_file() or not source.is_file():
        raise RuntimeError("missing experiment driver or CUDA probe source")

    geometries = [
        {"stage_geometry": "s01", "grid": 112, "block": 384},
        {"stage_geometry": "s2", "grid": 128, "block": 160},
        {"stage_geometry": "s3", "grid": 112, "block": 512},
        {"stage_geometry": "post", "grid": 539, "block": 384},
    ]
    matrices = {}
    matrices["req-shared-request-service"] = [
        {**geometry, "variant": "shared", "stride": stride, "repeats": repeats, "batches": 32, "samples": 31, "preheat-ms": 500}
        for geometry in geometries for stride in (1, 2, 4, 8, 16, 32) for repeats in (64, 128, 256)
    ] + [
        {**geometries[0], "variant": variant, "stride": 1, "repeats": repeats, "batches": 32, "samples": 31, "preheat-ms": 500}
        for variant in ("constant_broadcast", "constant_divergent") for repeats in (64, 128, 256)
    ] + [
        {**geometry, "variant": "zero", "stride": 1, "repeats": 1, "batches": 256, "samples": 31, "preheat-ms": 500}
        for geometry in geometries
    ]
    register_geometries = [
        {**geometries[0], "smem-bytes": 58624, "production_registers_per_thread": 144},
        {**geometries[1], "smem-bytes": 76672, "production_registers_per_thread": 76},
        {**geometries[2], "smem-bytes": 73984, "production_registers_per_thread": 126},
        {**geometries[3], "smem-bytes": 0, "production_registers_per_thread": 24},
    ]
    actual_registers = {"alloc0": 22, "alloc32": 48, "alloc64": 80, "alloc96": 124, "alloc112": 128, "alloc116": 130, "alloc124": 163}
    matrices["req-register-collective"] = [
        {**geometry, "variant": variant, "actual_registers_per_thread": actual_registers[variant], "repeats": repeats, "batches": 128, "samples": 31, "preheat-ms": 500}
        for geometry in register_geometries
        for variant in (("alloc0", "alloc32", "alloc64", "alloc96", "alloc112") if geometry["stage_geometry"] == "s3" else tuple(actual_registers))
        for repeats in (32, 64, 128)
    ] + [
        {**geometry, "variant": variant, "actual_registers_per_thread": 17, "repeats": repeats, "batches": 128, "samples": 31, "preheat-ms": 500}
        for geometry in register_geometries for variant in ("shfl_dep", "shfl_ilp4") for repeats in (64, 128, 256)
    ] + [
        {**geometry, "variant": "zero", "actual_registers_per_thread": 6, "repeats": 1, "batches": 256, "samples": 31, "preheat-ms": 500}
        for geometry in register_geometries
    ]
    matrices["req-sync-async-overlap"] = [
        {**geometry, "variant": variant, "repeats": repeats, "batches": 16, "samples": 31}
        for geometry in geometries[:3] for variant in ("sync", "async") for repeats in (16, 32, 64)
    ]
    matrices["req-compute-service"] = [
        {**geometry, "variant": variant, "repeats": 128, "batches": 16, "samples": 31}
        for geometry in geometries[:3] for variant in ("fma_dep", "fma_ilp4", "sfu", "integer", "tensor")
    ]
    matrices["req-memory-hierarchy-service"] = [
        {"S": S, "variant": variant, "grid": 340, "block": 256, "bytes": memory_bytes(S), "repeats": 16, "batches": 8, "samples": 31}
        for S in (256, 384, 404, 512, 640, 768, 1024) for variant in ("read", "write")
    ]
    matrices["req-p0-measurement-system"] = [{
        "source": "existing-attempt-03-qualified-receipt", "device": 6,
        "timer": "CUDA events", "processes": 3, "status": "PASS",
    }]

    summary_fields = {
        "req-shared-request-service": ["bank_stride_latency_curve", "constant_broadcast_penalty", "request_service_curve"],
        "req-register-collective": ["register_allocation_curve", "collective_latency_curve", "spill_and_residency_gate"],
        "req-sync-async-overlap": ["A_only_us", "B_only_us", "AB_us", "overlap_fraction", "barrier_wait_sites"],
        "req-compute-service": ["dependent_latency", "independent_throughput", "tensor_issue_curve", "SFU_and_SIMT_coupling"],
        "req-memory-hierarchy-service": ["warm_L2_useful_bytes_per_us", "streaming_device_bytes_per_us", "read_write_asymmetry"],
        "req-p0-measurement-system": ["timer_bracket_us", "process_spread", "clock_cv", "graph_direct_difference"],
    }
    standard_controls = [
        "zero control: zero-work launch establishes the timer and launch bracket",
        "positive control: live production-shaped work must exceed the zero-work bracket",
        "negative control: deliberately adverse dependency, bank, cache, or synchronization pattern must move the predicted metric",
        "live sink control: output is copied or atomically accumulated so the measured work cannot be eliminated",
    ]
    for request_id, matrix in matrices.items():
        if args.request_ids and request_id not in set(args.request_ids):
            continue
        experiment_path = run / "experiments" / request_id / "experiment.json"
        experiment = json.loads(experiment_path.read_text())
        candidate = run / "microbench_candidates" / request_id
        candidate.mkdir(parents=True, exist_ok=True)
        candidate_driver = candidate / "experiment_driver.py"
        candidate_source = candidate / "resource_probe.cu"
        shutil.copy2(driver, candidate_driver)
        shutil.copy2(source, candidate_source)
        source_identities = [identity(candidate_driver), identity(candidate_source)]
        command_prefix = [args.python, str(candidate_driver), "--run", str(run), "--request-id", request_id]
        experiment["commands"] = {
            phase: [command_prefix + ["--phase", phase]]
            for phase in ("clean_build", "static_audit", "correctness", "warmup", "measure", "analyze")
        }
        experiment["parameter_matrix"] = matrix
        experiment["controls"] = list(dict.fromkeys(experiment.get("controls", []) + standard_controls))
        experiment["model_update_contract"]["summary_fields"] = summary_fields[request_id]
        experiment["source"]["identities"] = list(source_identities)
        if request_id == "req-p0-measurement-system":
            p0_source = run / "experiments/req-p0-measurement-system/raw/p0_probe.cu"
            p0_driver = run / "experiments/req-p0-measurement-system/raw/run_p0.py"
            experiment["source"]["identities"].extend([identity(p0_source), identity(p0_driver)])
            experiment["level"] = "P0"
        elif request_id in {"req-sync-async-overlap", "req-register-collective"}:
            experiment["level"] = "P1_P2"
        else:
            experiment["level"] = "P1"
        experiment["status"] = "MATERIALIZED"
        write(experiment_path, experiment)
    selected = sorted(set(args.request_ids or matrices))
    print(json.dumps({"status": "PASS", "experiments": len(selected), "request_ids": selected}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
