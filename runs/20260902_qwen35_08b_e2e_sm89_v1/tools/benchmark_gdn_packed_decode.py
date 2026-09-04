#!/usr/bin/env python3
"""Sweep the Qwen3.5 packed GDN decode launch geometry.

This intentionally reuses vLLM's installed Triton kernel instead of copying its
math.  Every candidate is checked against the stock wrapper from an identical
state before timing.  The target shape defaults to Qwen3.5-0.8B on one GPU.
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

import torch

from vllm.third_party.flash_linear_attention.ops.fused_recurrent import (
    fused_recurrent_gated_delta_rule_packed_decode,
    fused_recurrent_gated_delta_rule_packed_decode_kernel,
)
from vllm.triton_utils import triton


def launch_candidate(
    *,
    mixed_qkv: torch.Tensor,
    a: torch.Tensor,
    b: torch.Tensor,
    A_log: torch.Tensor,
    dt_bias: torch.Tensor,
    initial_state: torch.Tensor,
    out: torch.Tensor,
    state_indices: torch.Tensor,
    bv: int,
    num_warps: int,
    num_stages: int,
) -> None:
    batch = mixed_qkv.shape[0]
    hv, value_dim, key_dim = initial_state.shape[-3:]
    qk_dim = mixed_qkv.shape[1] - hv * value_dim
    heads = qk_dim // (2 * key_dim)
    bk = triton.next_power_of_2(key_dim)
    nv = triton.cdiv(value_dim, bv)
    split_grid = batch * hv > 65535
    grid = (nv, hv, batch) if split_grid else (nv, batch * hv)
    fused_recurrent_gated_delta_rule_packed_decode_kernel[grid](
        mixed_qkv=mixed_qkv,
        a=a,
        b=b,
        A_log=A_log,
        dt_bias=dt_bias,
        o=out,
        h0=initial_state,
        ht=initial_state,
        ssm_state_indices=state_indices,
        scale=key_dim**-0.5,
        stride_mixed_qkv_tok=mixed_qkv.stride(0),
        stride_a_tok=a.stride(0),
        stride_b_tok=b.stride(0),
        stride_init_state_token=initial_state.stride(0),
        stride_final_state_token=initial_state.stride(0),
        stride_indices_seq=state_indices.stride(0),
        H=heads,
        HV=hv,
        K=key_dim,
        V=value_dim,
        BK=bk,
        BV=bv,
        SOFTPLUS_THRESHOLD=20.0,
        USE_QK_L2NORM_IN_KERNEL=True,
        SPLIT_BATCH_HEAD_GRID=split_grid,
        num_warps=num_warps,
        num_stages=num_stages,
    )


def elapsed_us(fn, iterations: int, repeats: int) -> list[float]:
    for _ in range(25):
        fn()
    torch.cuda.synchronize()
    values = []
    for _ in range(repeats):
        start = torch.cuda.Event(enable_timing=True)
        end = torch.cuda.Event(enable_timing=True)
        start.record()
        for _ in range(iterations):
            fn()
        end.record()
        end.synchronize()
        values.append(start.elapsed_time(end) * 1000.0 / iterations)
    return values


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--batch", type=int, default=1)
    parser.add_argument("--heads", type=int, default=16)
    parser.add_argument("--key-head-dim", type=int, default=128)
    parser.add_argument("--value-head-dim", type=int, default=128)
    parser.add_argument("--iterations", type=int, default=500)
    parser.add_argument("--repeats", type=int, default=7)
    args = parser.parse_args()

    torch.manual_seed(17)
    device = torch.device("cuda")
    batch = args.batch
    heads = args.heads
    key_dim = args.key_head_dim
    value_dim = args.value_head_dim
    qkv_dim = 2 * heads * key_dim + heads * value_dim

    mixed_qkv = torch.randn(batch, qkv_dim, device=device, dtype=torch.bfloat16)
    a = torch.randn(batch, heads, device=device, dtype=torch.bfloat16)
    b = torch.randn(batch, heads, device=device, dtype=torch.bfloat16)
    A_log = torch.randn(heads, device=device, dtype=torch.float32)
    dt_bias = torch.randn(heads, device=device, dtype=torch.float32)
    base_state = torch.randn(
        2, heads, value_dim, key_dim, device=device, dtype=torch.float32
    )
    state_indices = torch.ones(batch, device=device, dtype=torch.int32)

    ref_state = base_state.clone()
    ref_out = torch.empty(
        batch, 1, heads, value_dim, device=device, dtype=torch.bfloat16
    )
    fused_recurrent_gated_delta_rule_packed_decode(
        mixed_qkv=mixed_qkv,
        a=a,
        b=b,
        A_log=A_log,
        dt_bias=dt_bias,
        scale=key_dim**-0.5,
        initial_state=ref_state,
        out=ref_out,
        ssm_state_indices=state_indices,
        use_qk_l2norm_in_kernel=True,
    )
    torch.cuda.synchronize()

    timing_state = base_state.clone()
    timing_out = torch.empty_like(ref_out)
    stock_times = elapsed_us(
        lambda: launch_candidate(
            mixed_qkv=mixed_qkv,
            a=a,
            b=b,
            A_log=A_log,
            dt_bias=dt_bias,
            initial_state=timing_state,
            out=timing_out,
            state_indices=state_indices,
            bv=32,
            num_warps=1,
            num_stages=3,
        ),
        args.iterations,
        args.repeats,
    )
    stock_median = statistics.median(stock_times)
    rows = [
        {
            "name": "stock_bv32_w1_s3",
            "bv": 32,
            "num_warps": 1,
            "num_stages": 3,
            "median_us": stock_median,
            "samples_us": stock_times,
            "speedup_vs_stock": 1.0,
            "correct": True,
        }
    ]

    for bv in (16, 32, 64, 128):
        for warps in (1, 2, 4, 8):
            for stages in (2, 3, 4):
                name = f"bv{bv}_w{warps}_s{stages}"
                if (bv, warps, stages) == (32, 1, 3):
                    continue
                candidate_state = base_state.clone()
                candidate_out = torch.empty_like(ref_out)
                try:
                    launch_candidate(
                        mixed_qkv=mixed_qkv,
                        a=a,
                        b=b,
                        A_log=A_log,
                        dt_bias=dt_bias,
                        initial_state=candidate_state,
                        out=candidate_out,
                        state_indices=state_indices,
                        bv=bv,
                        num_warps=warps,
                        num_stages=stages,
                    )
                    torch.cuda.synchronize()
                    out_equal = torch.equal(candidate_out, ref_out)
                    state_equal = torch.equal(candidate_state, ref_state)
                    max_out_abs = float(
                        (candidate_out.float() - ref_out.float()).abs().max().item()
                    )
                    max_state_abs = float(
                        (candidate_state - ref_state).abs().max().item()
                    )
                    if not (out_equal and state_equal):
                        rows.append(
                            {
                                "name": name,
                                "bv": bv,
                                "num_warps": warps,
                                "num_stages": stages,
                                "correct": False,
                                "out_equal": out_equal,
                                "state_equal": state_equal,
                                "max_out_abs": max_out_abs,
                                "max_state_abs": max_state_abs,
                            }
                        )
                        continue

                    candidate_times = elapsed_us(
                        lambda bv=bv, warps=warps, stages=stages: launch_candidate(
                            mixed_qkv=mixed_qkv,
                            a=a,
                            b=b,
                            A_log=A_log,
                            dt_bias=dt_bias,
                            initial_state=timing_state,
                            out=timing_out,
                            state_indices=state_indices,
                            bv=bv,
                            num_warps=warps,
                            num_stages=stages,
                        ),
                        args.iterations,
                        args.repeats,
                    )
                    median_us = statistics.median(candidate_times)
                    rows.append(
                        {
                            "name": name,
                            "bv": bv,
                            "num_warps": warps,
                            "num_stages": stages,
                            "median_us": median_us,
                            "samples_us": candidate_times,
                            "speedup_vs_stock": stock_median / median_us,
                            "correct": True,
                            "out_equal": out_equal,
                            "state_equal": state_equal,
                            "max_out_abs": max_out_abs,
                            "max_state_abs": max_state_abs,
                        }
                    )
                except Exception as exc:  # Triton resource failures are candidates too.
                    rows.append(
                        {
                            "name": name,
                            "bv": bv,
                            "num_warps": warps,
                            "num_stages": stages,
                            "correct": False,
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    )

    valid = [row for row in rows if row.get("correct") and "median_us" in row]
    valid.sort(key=lambda row: row["median_us"])
    result = {
        "device": torch.cuda.get_device_name(),
        "torch_version": torch.__version__,
        "shape": {
            "batch": batch,
            "heads": heads,
            "key_head_dim": key_dim,
            "value_head_dim": value_dim,
            "state_dtype": str(base_state.dtype),
            "input_dtype": str(mixed_qkv.dtype),
        },
        "iterations": args.iterations,
        "repeats": args.repeats,
        "stock_median_us": stock_median,
        "best": valid[0],
        "results": rows,
    }
    rendered = json.dumps(result, indent=2)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
