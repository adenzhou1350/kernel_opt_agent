#!/usr/bin/env python3
"""Opt-in empirical references using an existing Torch installation.

Caller must first verify live UUID/load/processes and coordinate exclusive use.
Run in a task-private process with an outer timeout of 120 seconds, for example:
CUDA_VISIBLE_DEVICES=GPU-<full-uuid> timeout 120 /existing/python this_file.py \
    --device GPU-<full-uuid> --output /fresh/task-private/result.json
No installation, compilation, profiler, clock changes or automatic allocation.
Copy rates count logical read+write bytes, not measured L2/DRAM transactions.
"""

import argparse
import json
import math
import os
from pathlib import Path
import re
import statistics
import time

UUID_PATTERN = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
COPY_BYTES = (8 * 1024**2, 256 * 1024**2)
MM_SIZES = (2048, 4096)
WARMUPS, REPEATS = 3, 7
MEMORY_BUDGET = 1024**3


def normalize_uuid(value, require_prefix=False):
    value = str(value)
    prefix = "GPU-" if require_prefix else "(?:GPU-)?"
    if not re.fullmatch(prefix + UUID_PATTERN, value, re.IGNORECASE):
        raise ValueError(
            "A full GPU UUID is required; ordinals, MIG and prefixes are unsupported"
        )
    return "GPU-" + (value[4:] if value[:4].lower() == "gpu-" else value).lower()


def validate_config(device, output, environment):
    selected = normalize_uuid(device, require_prefix=True)
    if environment.get("CUDA_VISIBLE_DEVICES") != device:
        raise ValueError(
            "CUDA_VISIBLE_DEVICES must exactly equal the single --device UUID"
        )
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise ValueError("Output must be fresh; existing files are never overwritten")
    if not output.parent.is_dir():
        raise ValueError("Output parent must already exist")
    return selected, output


def summarize(samples_ms, work, unit, formula):
    if not samples_ms or any(not math.isfinite(x) or x <= 0 for x in samples_ms):
        raise ValueError("CUDA event samples must be finite and positive")
    median_ms = statistics.median(samples_ms)
    return {
        "samples_ms": samples_ms,
        "median_ms": median_ms,
        "work_per_call": work,
        "rate_per_second": work / (median_ms / 1000),
        "unit": unit,
        "rate_formula": formula,
        "status": "empirical_reference",
    }


def timed(torch, operation):
    for _ in range(WARMUPS):
        operation()
    torch.cuda.synchronize()
    start, end = (
        torch.cuda.Event(enable_timing=True),
        torch.cuda.Event(enable_timing=True),
    )
    samples = []
    for _ in range(REPEATS):
        start.record()
        operation()
        end.record()
        end.synchronize()
        samples.append(float(start.elapsed_time(end)))
    return samples


def run_probe(torch, device_uuid=None):
    began = time.monotonic()
    visible = os.environ.get("CUDA_VISIBLE_DEVICES", "")
    selected = normalize_uuid(device_uuid or visible, require_prefix=True)
    if normalize_uuid(visible, require_prefix=True) != selected:
        raise ValueError("Visible device does not match requested UUID")
    if torch.cuda.device_count() != 1:
        raise RuntimeError("Exactly one CUDA device must be visible")
    props = torch.cuda.get_device_properties(0)
    if normalize_uuid(getattr(props, "uuid", "")) != selected:
        raise RuntimeError("Torch device UUID does not match; refusing allocations")
    matmul = torch.backends.cuda.matmul
    old_reduction = matmul.allow_bf16_reduced_precision_reduction
    matmul.allow_bf16_reduced_precision_reduction = False
    try:
        if matmul.allow_bf16_reduced_precision_reduction is not False:
            raise RuntimeError("Cannot enforce full-precision BF16 reductions")
        free_bytes, _ = torch.cuda.mem_get_info(0)
        if free_bytes < 768 * 1024**2:
            raise RuntimeError("At least 768 MiB free memory is required")
        torch.cuda.reset_peak_memory_stats(0)
        results = []
        with torch.inference_mode():
            for size in COPY_BYTES:
                source = torch.full(
                    (size // 4,), 1.0, dtype=torch.float32, device="cuda:0"
                )
                target = torch.empty_like(source)
                samples = timed(torch, lambda s=source, t=target: t.copy_(s))
                if not torch.equal(source, target):
                    raise RuntimeError("FP32 copy sanity failed")
                result = summarize(
                    samples, 2 * size, "bytes/s", "2 * buffer_bytes / median_seconds"
                )
                result.update(
                    operation="Tensor.copy_",
                    dtype="float32",
                    buffer_bytes=size,
                    working_set_bytes=2 * size,
                    sanity="exact constant 1.0 copy",
                )
                results.append(result)
                del source, target
            for n in MM_SIZES:
                a = torch.full((n, n), 0.5, dtype=torch.bfloat16, device="cuda:0")
                b = torch.full((n, n), 0.25, dtype=torch.bfloat16, device="cuda:0")
                c = torch.empty_like(a)
                samples = timed(torch, lambda x=a, y=b, z=c: torch.mm(x, y, out=z))
                expected = torch.full_like(c, n / 8)
                if not torch.equal(c, expected):
                    raise RuntimeError("BF16 mm sanity failed")
                result = summarize(
                    samples, 2 * n**3, "FLOP/s", "2 * n**3 / median_seconds"
                )
                result.update(
                    operation="torch.mm",
                    dtype="bfloat16",
                    shape=[n, n, n],
                    sanity=f"exact constant result {n / 8}",
                )
                results.append(result)
                del a, b, c, expected
        peak = torch.cuda.max_memory_allocated(0)
        if peak >= MEMORY_BUDGET:
            raise RuntimeError("Probe exceeded its <1 GiB allocated-memory budget")
        fields = (
            "name",
            "major",
            "minor",
            "total_memory",
            "multi_processor_count",
            "warp_size",
        )
        return {
            "status": "empirical_reference",
            "device_uuid": selected,
            "device_properties": {key: getattr(props, key, None) for key in fields},
            "torch_version": str(torch.__version__),
            "cuda_version": torch.version.cuda,
            "backend": {
                "allow_bf16_reduced_precision_reduction": False,
                "accumulation": "FP32 accumulation policy; backend kernel not inspected",
            },
            "execution": "eager; same buffers reused; CUDA event pair synchronized each repeat",
            "warmups": WARMUPS,
            "repeats": REPEATS,
            "results": results,
            "peak_allocated_bytes": peak,
            "elapsed_wall_seconds": time.monotonic() - began,
            "limitations": "Not an upper bound; copy traffic is logical, cache/DRAM residency unverified; "
            "constant sanity is not general numerical validation; clock/load observations are caller-owned",
        }
    finally:
        matmul.allow_bf16_reduced_precision_reduction = old_reduction


def main(argv=None):
    began = time.monotonic()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    selected, output = validate_config(args.device, args.output, os.environ)
    with output.open("x", encoding="utf-8") as stream:
        import torch

        result = run_probe(torch, selected)
        result["elapsed_wall_seconds"] = time.monotonic() - began
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write("\n")


if __name__ == "__main__":
    main()
