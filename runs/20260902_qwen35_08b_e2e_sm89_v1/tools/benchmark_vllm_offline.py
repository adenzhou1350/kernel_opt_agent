#!/usr/bin/env python3
"""Bounded, fresh-state vLLM discovery baseline for frozen Qwen3.5 cases."""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

import torch
import transformers
import triton
import vllm
from transformers import AutoTokenizer
from vllm import LLM, SamplingParams


CASES = (
    ("prompt-128-generate-128", 128, 0.2),
    ("prompt-512-generate-128", 512, 0.3),
    ("prompt-2048-generate-128", 2048, 0.5),
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(8 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def exact_prompt(tokenizer, length: int) -> list[int]:
    seed_text = "Kernel optimization must preserve semantics while reducing global latency. "
    seed = tokenizer.encode(seed_text, add_special_tokens=False)
    if not seed:
        raise RuntimeError("tokenizer produced an empty seed")
    return (seed * ((length + len(seed) - 1) // len(seed)))[:length]


def median(values: list[float]) -> float:
    return float(statistics.median(values))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--new-tokens", type=int, default=128)
    parser.add_argument("--gpu-memory-utilization", type=float, default=0.70)
    parser.add_argument("--enforce-eager", action="store_true")
    parser.add_argument(
        "--quantization",
        choices=("none", "fp8", "int8_per_channel_weight_only"),
        default="none",
    )
    args = parser.parse_args()
    if args.warmups < 1 or args.trials < 1:
        raise ValueError("warmups and trials must both be positive")

    model_path = args.model.resolve()
    tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True)
    prompts = {case_id: exact_prompt(tokenizer, length) for case_id, length, _ in CASES}
    params = SamplingParams(
        temperature=0.0,
        max_tokens=args.new_tokens,
        ignore_eos=True,
        detokenize=False,
        seed=20260902,
    )

    init_started = time.perf_counter()
    llm = LLM(
        model=str(model_path),
        dtype="bfloat16",
        quantization=None if args.quantization == "none" else args.quantization,
        max_model_len=4096,
        gpu_memory_utilization=args.gpu_memory_utilization,
        enforce_eager=args.enforce_eager,
        language_model_only=True,
        enable_prefix_caching=False,
        disable_log_stats=False,
        seed=20260902,
    )
    init_seconds = time.perf_counter() - init_started

    def request(case_id: str, phase: str, iteration: int) -> dict:
        started = time.perf_counter()
        outputs = llm.generate({"prompt_token_ids": prompts[case_id]}, params, use_tqdm=False)
        wall_seconds = time.perf_counter() - started
        output = outputs[0]
        token_ids = list(output.outputs[0].token_ids)
        stats = output.metrics
        if stats is None:
            raise RuntimeError("vLLM request metrics are unavailable with disable_log_stats=False")
        raw_stats = dataclasses.asdict(stats)
        decode_intervals = max(len(token_ids) - 1, 1)
        decode_seconds = max(float(stats.last_token_ts - stats.first_token_ts), 0.0)
        return {
            "case_id": case_id,
            "phase": phase,
            "iteration": iteration,
            "prompt_tokens": len(prompts[case_id]),
            "generated_tokens": len(token_ids),
            "generated_token_ids": token_ids,
            "end_to_end_ms": wall_seconds * 1000.0,
            "ttft_ms": float(stats.first_token_latency) * 1000.0,
            "tpot_ms": decode_seconds * 1000.0 / decode_intervals,
            "output_tokens_per_second": decode_intervals / decode_seconds if decode_seconds > 0 else None,
            "engine_metrics": raw_stats,
        }

    samples: list[dict] = []
    # Rotate the case order so clock/thermal drift cannot systematically favor one shape.
    case_ids = [item[0] for item in CASES]
    for iteration in range(args.warmups):
        order = case_ids[iteration % len(case_ids):] + case_ids[: iteration % len(case_ids)]
        for case_id in order:
            samples.append(request(case_id, "warmup", iteration))
    for iteration in range(args.trials):
        shift = (iteration + args.warmups) % len(case_ids)
        order = case_ids[shift:] + case_ids[:shift]
        for case_id in order:
            samples.append(request(case_id, "measure", iteration))

    summaries = []
    for case_id, prompt_tokens, weight in CASES:
        measured = [sample for sample in samples if sample["case_id"] == case_id and sample["phase"] == "measure"]
        reference_ids = measured[0]["generated_token_ids"]
        exact_repeat = all(sample["generated_token_ids"] == reference_ids for sample in measured)
        summaries.append({
            "case_id": case_id,
            "weight": weight,
            "prompt_tokens": prompt_tokens,
            "generated_tokens": args.new_tokens,
            "correctness": "PASS" if exact_repeat and len(reference_ids) == args.new_tokens else "FAIL",
            "generated_token_ids": reference_ids,
            "median_end_to_end_ms": median([sample["end_to_end_ms"] for sample in measured]),
            "median_ttft_ms": median([sample["ttft_ms"] for sample in measured]),
            "median_tpot_ms": median([sample["tpot_ms"] for sample in measured]),
            "median_output_tokens_per_second": median([sample["output_tokens_per_second"] for sample in measured]),
        })

    payload = {
        "schema_version": "qwen35-vllm-discovery-baseline-v1",
        "status": "PASS" if all(case["correctness"] == "PASS" for case in summaries) else "FAIL",
        "claim_scope": (
            "DISCOVERY_BASELINE_ONLY_NOT_QUALIFICATION"
            if args.quantization == "none"
            else "EXPLORATORY_QUANTIZED_DISCOVERY_REQUIRES_NEW_NUMERICS_CONTRACT"
        ),
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "model": {
            "path": str(model_path),
            "config_sha256": sha256(model_path / "config.json"),
            "weight_sha256": sha256(model_path / "model.safetensors-00001-of-00001.safetensors"),
        },
        "environment": {
            "gpu": torch.cuda.get_device_name(0),
            "compute_capability": ".".join(map(str, torch.cuda.get_device_capability(0))),
            "vllm": vllm.__version__,
            "torch": torch.__version__,
            "cuda": torch.version.cuda,
            "triton": triton.__version__,
            "transformers": transformers.__version__,
            "vllm_use_v2_model_runner": os.environ.get("VLLM_USE_V2_MODEL_RUNNER"),
            "vllm_use_flashinfer_sampler": os.environ.get("VLLM_USE_FLASHINFER_SAMPLER"),
        },
        "controls": {
            "language_model_only": True,
            "dtype": "bfloat16",
            "quantization": args.quantization,
            "max_model_len": 4096,
            "enable_prefix_caching": False,
            "enforce_eager": args.enforce_eager,
            "gpu_memory_utilization": args.gpu_memory_utilization,
            "warmups": args.warmups,
            "trials": args.trials,
            "case_order": "rotated per iteration",
            "sampling": "greedy temperature=0, ignore_eos=True, exact 128 tokens",
            "engine_initialization_seconds": init_seconds,
        },
        "cases": summaries,
        "raw_samples": samples,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "controls": payload["controls"], "cases": summaries}, indent=2))


if __name__ == "__main__":
    main()
