#!/usr/bin/env python3
"""Capture the seven-case exact current four-stage baseline with separated clocks."""

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

import torch
import torch.nn.functional as F
from torch.profiler import ProfilerActivity, profile, record_function

from fla.modules import FusedRMSNormGated
from fla.ops.gated_delta_rule import chunk_gated_delta_rule
from flashinfer.gdn_kernels.delta_rule_dsl.qwen35_fla_pipeline_sm120 import (
    prepare_qwen35_fla_cute_pipeline_sm120,
)


H, D = 16, 128
SHAPES = (256, 384, 404, 512, 640, 768, 1024)
SOURCE_DIR = Path("/workspace/dance/qwen35/flashinfer/flashinfer/gdn_kernels/delta_rule_dsl")
EXPECTED = {
    "qwen35_fla_pipeline_sm120.py": "1ba9ed3d607171e2e900c91cf9c4d3ea91d3c3542f80cad4354b91eda507888d",
    "qwen35_fla_s01_sm120.py": "a17bbba422c8ee4af41c0da86b1e68f1b9db75892c4004789bc23fc2446b8df8",
    "qwen35_fla_s2_sm120.py": "00dedb81955371f5b34eb39d5f2bd0ae8d95d7f63bf13fc4635e032f8f5d9f24",
    "qwen35_fla_s3_raw_sm120.py": "fb0eb2a9bf4a72c6804eaf09c7fc3c9a74ff6eaf961c15ef4b3bd0dcb43e157b",
    "qwen35_fla_s3_short_raw_sm120.py": "2b61b0da46b13802fcc75620fe7f87fe50d4de6660259327ee08696b0b83929f",
    "qwen35_fla_s3_long_raw_sm120.py": "2b647e3971a36929a2239c1ade1b4afec33894e0cb6ec638d6b0b046871e149f",
    "qwen35_fla_post_sm120.py": "54ab667c78cdbdd082c95a6159bcfee3fce8194c32439fc4b53a7c0afd7cb818",
}
CORRECTNESS_THRESHOLDS = {
    "max_abs": 0.25,
    "mean_abs": 0.003,
    "cosine_min": 0.9999,
}


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def identity(path: Path) -> dict:
    return {"path": str(path.resolve()), "sha256": sha(path)}


def write(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def summary(values: list[float]) -> dict:
    ordered = sorted(values)
    return {
        "count": len(values), "unit": "us", "median_us": statistics.median(values),
        "mean_us": statistics.fmean(values), "min_us": ordered[0], "max_us": ordered[-1],
        "p05_us": ordered[max(0, int(0.05 * (len(ordered) - 1)))],
        "p95_us": ordered[min(len(ordered) - 1, int(0.95 * (len(ordered) - 1)))],
    }


def smi(index: int) -> dict:
    fields = "uuid,name,clocks.current.sm,utilization.gpu,temperature.gpu,power.draw"
    output = subprocess.run(
        ["nvidia-smi", "-i", str(index), f"--query-gpu={fields}", "--format=csv,noheader,nounits"],
        check=True, text=True, stdout=subprocess.PIPE,
    ).stdout.strip().split(", ")
    return {
        "uuid": output[0], "name": output[1], "clock_mhz": float(output[2]),
        "utilization_percent": float(output[3]), "temperature_c": float(output[4]), "power_w": float(output[5]),
    }


def reference_output(mixed, zba, a_log, dt_bias, norm_weight):
    sequence = mixed.shape[2]
    token_major = mixed.transpose(1, 2)
    q = token_major[..., : H * D].reshape(1, sequence, H, D)
    k = token_major[..., H * D : 2 * H * D].reshape(1, sequence, H, D)
    v = token_major[..., 2 * H * D :].reshape(1, sequence, H, D)
    z = zba[:, : H * D].reshape(1, sequence, H, D)
    beta_logits = zba[:, H * D : H * (D + 1)].reshape(1, sequence, H)
    decay_logits = zba[:, H * (D + 1) :].reshape(1, sequence, H)
    beta = beta_logits.float().sigmoid()
    g = -a_log.exp()[None, None, :] * F.softplus(decay_logits.float() + dt_bias[None, None, :])
    raw, _ = chunk_gated_delta_rule(
        q, k, v, g=g, beta=beta, initial_state=None,
        output_final_state=False, use_qk_l2norm_in_kernel=True,
    )
    norm = FusedRMSNormGated(D, elementwise_affine=True, eps=1.0e-6, device=mixed.device, dtype=torch.bfloat16)
    norm.weight.copy_(norm_weight)
    return norm(raw.reshape(-1, D), z.reshape(-1, D)).reshape(sequence, H, D)


def compare(actual: torch.Tensor, reference: torch.Tensor) -> dict:
    actual_f, reference_f = actual.float(), reference.float()
    difference = (actual_f - reference_f).abs()
    result = {
        "finite_actual": bool(torch.isfinite(actual_f).all().item()),
        "finite_reference": bool(torch.isfinite(reference_f).all().item()),
        "max_abs": float(difference.max().item()),
        "mean_abs": float(difference.mean().item()),
        "cosine": float(F.cosine_similarity(actual_f.flatten(), reference_f.flatten(), dim=0).item()),
        "thresholds": CORRECTNESS_THRESHOLDS,
    }
    result["status"] = "PASS" if (
        result["finite_actual"] and result["finite_reference"]
        and result["max_abs"] <= CORRECTNESS_THRESHOLDS["max_abs"]
        and result["mean_abs"] <= CORRECTNESS_THRESHOLDS["mean_abs"]
        and result["cosine"] >= CORRECTNESS_THRESHOLDS["cosine_min"]
    ) else "FAIL"
    return result


def profile_stages(run, stream, sequence: int, output_dir: Path, repeats: int = 12) -> dict:
    label = f"QWEN35_CURRENT_PIPELINE_S{sequence}"
    with profile(activities=[ProfilerActivity.CPU, ProfilerActivity.CUDA]) as profiler:
        for _ in range(repeats):
            with record_function(label):
                run()
        stream.synchronize()
    trace = output_dir / f"s{sequence}_stage_trace.json"
    profiler.export_chrome_trace(str(trace))
    events = json.loads(trace.read_text())["traceEvents"]
    needles = {
        "s01": "qwen35_fla_s01_sm120", "s2": "qwen35_fla_s2_sm120",
        "s3_short": "qwen35_fla_s3_short_raw_sm120", "s3_long": "qwen35_fla_s3_long_raw_sm120",
        "post": "qwen35_fla_post_sm120",
    }
    kernels = sorted([
        event for event in events
        if event.get("name", "").startswith("kernel_cutlass_kernel_")
        and "qwen35_fla_" in event.get("name", "")
    ], key=lambda event: float(event.get("ts", 0.0)))
    stage_values = {
        stage: [float(event["dur"]) for event in kernels if needle in event.get("name", "")]
        for stage, needle in needles.items()
    }
    active_s3 = "s3_short" if sequence <= 640 else "s3_long"
    expected_order = ("s01", "s2", active_s3, "post")
    if len(kernels) != repeats * 4:
        raise RuntimeError(f"S={sequence}: profiler saw {len(kernels)} production kernels, expected {repeats * 4}")
    pipeline_sums = []
    for offset in range(0, len(kernels), 4):
        group = kernels[offset : offset + 4]
        observed = []
        for event in group:
            matched = [stage for stage in expected_order if needles[stage] in event.get("name", "")]
            if len(matched) != 1:
                raise RuntimeError(f"S={sequence}: unexpected profiled kernel {event.get('name')}")
            observed.append(matched[0])
        if tuple(observed) != expected_order:
            raise RuntimeError(f"S={sequence}: launch order changed: {observed}")
        pipeline_sums.append(sum(float(event["dur"]) for event in group))
    return {
        "status": "DIAGNOSTIC_NOT_ACCEPTANCE_TIMING", "metric": "CUPTI kernel activity duration",
        "trace_identity": identity(trace), "kernel_count": len(kernels), "expected_order": list(expected_order),
        "stages": {stage: summary(values) if values else None for stage, values in stage_values.items()},
        "four_kernel_sum": summary(pipeline_sums),
    }


@torch.inference_mode()
def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--device", type=int, default=6)
    parser.add_argument("--expected-uuid", required=True)
    parser.add_argument("--graph-batch", type=int, default=64)
    parser.add_argument("--gpu-rounds", type=int, default=31)
    parser.add_argument("--dispatch-rounds", type=int, default=31)
    parser.add_argument("--dispatch-batch", type=int, default=64)
    parser.add_argument("--e2e-rounds", type=int, default=31)
    args = parser.parse_args()
    run_root = args.run.resolve()
    baseline_dir = run_root / "baseline"
    raw_dir = baseline_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    torch.cuda.set_device(args.device)
    device = torch.device(f"cuda:{args.device}")
    if torch.cuda.get_device_capability(device) != (12, 0):
        raise RuntimeError("baseline requires the frozen SM120 target")

    observed_sources = {name: sha(SOURCE_DIR / name) for name in EXPECTED}
    if observed_sources != EXPECTED:
        raise RuntimeError(f"production sources changed: {observed_sources}")
    if sha(run_root / "static/current_s404_composite.cubin") != "ac0a9b859bd3506a75a06c80806f58238e1827432e87612b43bf89190f2cc04e":
        raise RuntimeError("frozen current S404 composite binary changed")

    pre_environment = [smi(args.device) for _ in range(9)]
    if any(item["uuid"] != args.expected_uuid for item in pre_environment):
        raise RuntimeError("baseline GPU UUID mismatch")
    if max(item["utilization_percent"] for item in pre_environment) > 2.0:
        raise RuntimeError(f"baseline competing-load gate failed: {pre_environment}")

    cases = []
    correctness_cases = []
    operator_identity = identity(run_root / "operator.json")
    script_identity = identity(Path(__file__))
    p0_identity = identity(run_root / "experiments/req-p0-measurement-system/p0_receipt.json")
    for sequence in SHAPES:
        print(json.dumps({"event": "CASE_START", "sequence": sequence}), flush=True)
        generator = torch.Generator(device=device).manual_seed(20260826 + sequence)
        token_major = torch.randn((1, sequence, 3 * H * D), device=device, dtype=torch.bfloat16, generator=generator)
        mixed = token_major.transpose(1, 2)
        zba = torch.randn((sequence, H * (D + 2)), device=device, dtype=torch.bfloat16, generator=generator)
        a_log = -3.0 + 0.1 * torch.randn(H, device=device, dtype=torch.float32, generator=generator)
        dt_bias = -0.5 + 0.1 * torch.randn(H, device=device, dtype=torch.float32, generator=generator)
        norm_weight = torch.randn(D, device=device, dtype=torch.bfloat16, generator=generator)
        cu = torch.tensor([0, sequence], device=device, dtype=torch.int64)
        output = torch.empty((sequence, H, D), device=device, dtype=torch.bfloat16)
        stream = torch.cuda.Stream(device=device)
        torch.cuda.synchronize(device)
        with torch.cuda.stream(stream):
            plan = prepare_qwen35_fla_cute_pipeline_sm120(mixed, zba, a_log, dt_bias, norm_weight, cu, output=output)

        def launch():
            return plan.run_fused_gated_rms(output, mixed, zba, a_log, dt_bias, norm_weight)

        for _ in range(40):
            launch()
        stream.synchronize()
        first = output.clone()
        launch(); stream.synchronize(); second = output.clone()
        deterministic_bitwise = bool(torch.equal(first, second))

        reference = reference_output(mixed, zba, a_log, dt_bias, norm_weight)
        torch.cuda.synchronize(device)
        reference_check = compare(second, reference)

        graph = torch.cuda.CUDAGraph()
        with torch.cuda.graph(graph, stream=stream):
            launch()
        with torch.cuda.stream(stream):
            for _ in range(10):
                graph.replay()
        stream.synchronize()
        graph_output_bitwise = bool(torch.equal(output, second))
        case_correctness = {
            "case_id": f"s{sequence}", "deterministic_direct_bitwise": deterministic_bitwise,
            "graph_output_bitwise_vs_direct": graph_output_bitwise, "reference": reference_check,
        }
        case_correctness["status"] = "PASS" if deterministic_bitwise and graph_output_bitwise and reference_check["status"] == "PASS" else "FAIL"
        correctness_cases.append(case_correctness)
        if case_correctness["status"] != "PASS":
            write(baseline_dir / "correctness.json", {"status": "FAIL", "cases": correctness_cases})
            raise RuntimeError(f"S={sequence} correctness failed: {case_correctness}")

        gpu_samples = []
        start, stop = torch.cuda.Event(enable_timing=True), torch.cuda.Event(enable_timing=True)
        for _ in range(args.gpu_rounds):
            # CUDAGraph.replay enqueues on the current stream.  Keep replay and
            # both boundary events in one explicit stream context; a boundary
            # event on plan.stream with replay on the default stream would
            # produce a physically impossible value below the four kernel sum.
            with torch.cuda.stream(stream):
                start.record()
                for _ in range(args.graph_batch):
                    graph.replay()
                stop.record()
            stop.synchronize()
            gpu_samples.append(start.elapsed_time(stop) * 1000.0 / args.graph_batch)

        dispatch_samples = []
        for _ in range(args.dispatch_rounds):
            stream.synchronize()
            for _ in range(args.dispatch_batch):
                before_ns = time.perf_counter_ns()
                launch()
                after_ns = time.perf_counter_ns()
                dispatch_samples.append((after_ns - before_ns) / 1000.0)
            stream.synchronize()

        e2e_samples = []
        for _ in range(args.e2e_rounds):
            before_ns = time.perf_counter_ns()
            launch()
            stream.synchronize()
            after_ns = time.perf_counter_ns()
            e2e_samples.append((after_ns - before_ns) / 1000.0)

        stage_profile = profile_stages(launch, stream, sequence, raw_dir)
        case_environment = smi(args.device)
        raw_record = {
            "schema_version": "qwen35-production-baseline-raw-v1", "case_id": f"s{sequence}",
            "captured_at": datetime.now(timezone.utc).isoformat(), "seed": 20260826 + sequence,
            "workload": {"B": 1, "H": H, "D": D, "S": sequence, "C": 64, "P": ((sequence + 63) // 64) * 64, "J": (sequence + 63) // 64, "dtype": "BF16", "initial_state": None, "output_final_state": False},
            "source_sha256": observed_sources, "abi_tag": plan.stage_abi_tag,
            "correctness": case_correctness, "p0_receipt": p0_identity,
            "samples": {"cpu_dispatch_us": dispatch_samples, "gpu_active_graph_batched_us": gpu_samples, "end_to_end_direct_sync_us": e2e_samples},
            "summaries": {"cpu_dispatch": summary(dispatch_samples), "gpu_active": summary(gpu_samples), "end_to_end": summary(e2e_samples)},
            "stage_profile": stage_profile, "post_case_environment": case_environment,
        }
        graph_median = raw_record["summaries"]["gpu_active"]["median_us"]
        kernel_sum_median = stage_profile["four_kernel_sum"]["median_us"]
        raw_record["stream_containment_gate"] = {
            "status": "PASS" if 0.85 * kernel_sum_median <= graph_median <= 2.0 * kernel_sum_median else "FAIL",
            "graph_event_pipeline_us": graph_median,
            "separate_cupti_four_kernel_sum_us": kernel_sum_median,
            "allowed_ratio": [0.85, 2.0],
        }
        raw_path = raw_dir / f"s{sequence}.json"
        write(raw_path, raw_record)
        if raw_record["stream_containment_gate"]["status"] != "PASS":
            raise RuntimeError(f"S={sequence}: graph/event stream containment failed: {raw_record['stream_containment_gate']}")
        cases.append({
            "case_id": f"s{sequence}", "correctness": "PASS", "source_identity": operator_identity,
            "raw_samples": identity(raw_path), "cpu_dispatch": raw_record["summaries"]["cpu_dispatch"],
            "gpu_active": raw_record["summaries"]["gpu_active"], "end_to_end": raw_record["summaries"]["end_to_end"],
            "stage_profile": stage_profile,
        })
        print(json.dumps({"event": "CASE_PASS", "sequence": sequence, "cpu_dispatch_us": cases[-1]["cpu_dispatch"]["median_us"], "gpu_active_us": cases[-1]["gpu_active"]["median_us"], "end_to_end_us": cases[-1]["end_to_end"]["median_us"], "four_kernel_cupti_sum_us": stage_profile["four_kernel_sum"]["median_us"]}), flush=True)
        del graph, plan, reference, output, first, second, mixed, token_major, zba, a_log, dt_bias, norm_weight, cu
        torch.cuda.empty_cache()

    correctness_path = baseline_dir / "correctness.json"
    write(correctness_path, {
        "schema_version": "qwen35-production-baseline-correctness-v1", "status": "PASS",
        "thresholds": CORRECTNESS_THRESHOLDS,
        "threshold_basis": "pre-existing real-checkpoint production-vs-FLA evidence showed max_abs=0.125, mean_abs<=0.001151 and cosine>=0.999985; this baseline pre-registers conservative 2x/2.6x margins before current outputs were measured",
        "cases": correctness_cases,
    })
    environment_path = baseline_dir / "environment.json"
    write(environment_path, {
        "schema_version": "qwen35-production-baseline-environment-v1", "captured_at": datetime.now(timezone.utc).isoformat(),
        "target_uuid": args.expected_uuid, "device_index": args.device, "pre_measurement": pre_environment,
        "p0_receipt": p0_identity, "source_sha256": observed_sources,
    })
    baseline = {
        "schema_version": "production-baseline-v1", "status": "VALID",
        "correctness": {"status": "PASS", "evidence": [identity(correctness_path)]},
        "source_identities": [operator_identity, script_identity, identity(run_root / "static/current_s404_composite.cubin")],
        "measurement_methods": {
            "cpu_dispatch": "host perf_counter_ns around one production TVM-FFI call; 31x64 direct calls, GPU drained at batch boundaries",
            "gpu_active": "P0-qualified native CUDA events around 64 replays of a captured exact four-kernel production pipeline, divided by 64; compilation/allocation/host dispatch excluded",
            "end_to_end": "host perf_counter_ns around one direct production TVM-FFI call plus synchronization; 31 warm samples",
            "stage_diagnostic": "separate torch-profiler/CUPTI collection; never mixed into acceptance timing distribution",
        },
        "environment_controls": {
            "competing_load": "pre-run GPU utilization <=2% and exact UUID match; per-case environment archived",
            "clock_power_policy": "P0 active-clock stability PASS; no application clock lock requested; observed clocks archived",
            "thermal_policy": "temperature and power archived before/after; no cooling sleep inserted between warm cases",
            "warmup_and_cold_start": "40 production warmups plus 10 graph warmups; compilation/allocation and FLA reference excluded; cold evidence preserved separately by P0",
            "p0_receipt": p0_identity,
        },
        "cases": cases,
        "environment_identity": identity(environment_path),
    }
    write(run_root / "models/baseline.json", baseline)
    print(json.dumps({"event": "BASELINE_READY", "cases": len(cases), "baseline": str(run_root / "models/baseline.json")}), flush=True)


if __name__ == "__main__":
    main()
