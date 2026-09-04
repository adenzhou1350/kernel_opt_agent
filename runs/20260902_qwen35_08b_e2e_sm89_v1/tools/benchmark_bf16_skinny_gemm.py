#!/usr/bin/env python3
"""Compare vLLM's CuTeDSL skinny GEMM with torch/cuBLAS on Qwen3.5 shapes."""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

import torch
import torch.nn.functional as F
import triton
import triton.language as tl

from vllm.model_executor.kernels.linear.cute_dsl.skinny_gemm import (
    shape_dynamic_skinny_gemm,
)


SHAPES = (
    # name, M, N, K, multiplicity per decoded token
    ("gdn_qkvz", 1, 8192, 1024, 18),
    ("gdn_ba", 1, 32, 1024, 18),
    ("gdn_out", 1, 1024, 2048, 18),
    ("attention_qkv", 1, 3072, 1024, 6),
    ("attention_out", 1, 1024, 2048, 6),
    ("mlp_gate_up", 1, 7168, 1024, 24),
    ("mlp_down", 1, 1024, 3584, 24),
    ("lm_head", 1, 248320, 1024, 1),
)


@triton.jit
def _gemv_kernel(
    x_ptr,
    weight_ptr,
    output_ptr,
    n: tl.constexpr,
    k: tl.constexpr,
    BLOCK_N: tl.constexpr,
    BLOCK_K: tl.constexpr,
):
    pid = tl.program_id(0)
    offsets_n = pid * BLOCK_N + tl.arange(0, BLOCK_N)
    offsets_k = tl.arange(0, BLOCK_K)
    x = tl.load(x_ptr + offsets_k, mask=offsets_k < k, other=0.0)
    weight = tl.load(
        weight_ptr + offsets_n[:, None] * k + offsets_k[None, :],
        mask=(offsets_n[:, None] < n) & (offsets_k[None, :] < k),
        other=0.0,
    )
    accum = tl.sum(weight.to(tl.float32) * x[None, :].to(tl.float32), axis=1)
    tl.store(output_ptr + offsets_n, accum, mask=offsets_n < n)


def triton_gemv(
    x: torch.Tensor,
    weight: torch.Tensor,
    *,
    block_n: int,
    num_warps: int,
) -> torch.Tensor:
    m, k = x.shape
    n = weight.shape[0]
    if m != 1:
        raise ValueError("screening kernel only supports M=1")
    output = torch.empty((1, n), dtype=x.dtype, device=x.device)
    block_k = triton.next_power_of_2(k)
    _gemv_kernel[(triton.cdiv(n, block_n),)](
        x,
        weight,
        output,
        n=n,
        k=k,
        BLOCK_N=block_n,
        BLOCK_K=block_k,
        num_warps=num_warps,
        num_stages=1,
    )
    return output


def elapsed_us(fn, iterations: int, repeats: int) -> list[float]:
    for _ in range(20):
        fn()
    torch.cuda.synchronize()
    samples = []
    for _ in range(repeats):
        start = torch.cuda.Event(enable_timing=True)
        end = torch.cuda.Event(enable_timing=True)
        start.record()
        for _ in range(iterations):
            fn()
        end.record()
        end.synchronize()
        samples.append(start.elapsed_time(end) * 1000.0 / iterations)
    return samples


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--repeats", type=int, default=7)
    args = parser.parse_args()

    torch.manual_seed(20260905)
    rows = []
    for name, m, n, k, multiplicity in SHAPES:
        x = torch.randn(m, k, device="cuda", dtype=torch.bfloat16) * 0.1
        weight = torch.randn(n, k, device="cuda", dtype=torch.bfloat16) * 0.1
        reference = F.linear(x, weight)
        torch_times = elapsed_us(
            lambda: F.linear(x, weight), args.iterations, args.repeats
        )
        torch_median = statistics.median(torch_times)
        candidates = []
        for block_n in (1, 2, 4, 8):
            for num_warps in (4, 8):
                try:
                    candidate = triton_gemv(
                        x, weight, block_n=block_n, num_warps=num_warps
                    )
                    torch.cuda.synchronize()
                    max_abs = float(
                        (candidate.float() - reference.float()).abs().max()
                    )
                    mean_abs = float(
                        (candidate.float() - reference.float()).abs().mean()
                    )
                    close = bool(
                        torch.allclose(
                            candidate.float(),
                            reference.float(),
                            rtol=0.05,
                            atol=0.05,
                        )
                    )
                    times = elapsed_us(
                        lambda block_n=block_n, num_warps=num_warps: triton_gemv(
                            x,
                            weight,
                            block_n=block_n,
                            num_warps=num_warps,
                        ),
                        args.iterations,
                        args.repeats,
                    )
                    triton_median = statistics.median(times)
                    candidates.append(
                        {
                            "block_n": block_n,
                            "num_warps": num_warps,
                            "correct": close,
                            "max_abs": max_abs,
                            "mean_abs": mean_abs,
                            "median_us": triton_median,
                            "speedup": torch_median / triton_median,
                            "samples_us": times,
                        }
                    )
                except Exception as exc:
                    candidates.append(
                        {
                            "block_n": block_n,
                            "num_warps": num_warps,
                            "correct": False,
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    )
        valid = [
            candidate
            for candidate in candidates
            if candidate.get("correct") and "median_us" in candidate
        ]
        best = min(valid, key=lambda candidate: candidate["median_us"]) if valid else None
        rows.append(
            {
                "name": name,
                "shape": [m, n, k],
                "multiplicity": multiplicity,
                "weight_bytes": n * k * 2,
                "torch_median_us": torch_median,
                "torch_samples_us": torch_times,
                "best_triton": best,
                "candidates": candidates,
            }
        )
        del x, weight, reference
        torch.cuda.empty_cache()

    comparable = [row for row in rows if row["best_triton"] is not None]
    torch_total = sum(
        row["torch_median_us"] * row["multiplicity"] for row in comparable
    )
    skinny_total = sum(
        row["best_triton"]["median_us"] * row["multiplicity"]
        for row in comparable
    )
    result = {
        "schema_version": "qwen35-bf16-triton-gemv-screen-v2",
        "device": torch.cuda.get_device_name(),
        "torch_version": torch.__version__,
        "iterations": args.iterations,
        "repeats": args.repeats,
        "cutedsl_probe": {
            "python_package_available": shape_dynamic_skinny_gemm.is_available(),
            "sm89_compatible": False,
            "reason": "vLLM CuTeDSL skinny GEMM requires SM90 or newer",
        },
        "weighted_shape_sum_us": {
            "torch": torch_total,
            "skinny": skinny_total,
            "speedup": torch_total / skinny_total if skinny_total else None,
            "warning": "sum of isolated medians is a screening estimate, not end-to-end latency",
        },
        "results": rows,
    }
    rendered = json.dumps(result, indent=2) + "\n"
    print(rendered, end="")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")


if __name__ == "__main__":
    main()
