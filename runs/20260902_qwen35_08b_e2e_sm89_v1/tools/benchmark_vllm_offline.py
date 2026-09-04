#!/usr/bin/env python3
"""Bounded, fresh-state vLLM discovery baseline for frozen Qwen3.5 cases."""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import re
import shutil
import statistics
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

SYNTHETIC_CASES = (
    ("prompt-128-generate-128", 128, 0.2),
    ("prompt-512-generate-128", 512, 0.3),
    ("prompt-2048-generate-128", 2048, 0.5),
)

NATURAL_REQUESTS = (
    (
        "zh-explanation",
        "请用通俗但准确的语言解释：为什么大语言模型逐 token 解码通常受显存带宽限制？给出一个简单的数量级估算。",
    ),
    (
        "python-code",
        "Write a complete Python function that merges overlapping half-open intervals. Include type hints, a concise explanation, and three edge-case tests.",
    ),
    (
        "reasoning",
        "A shop discounts an item by 20%, then raises the discounted price by 25%. Explain step by step whether the final price equals the original price.",
    ),
    (
        "editing",
        "Rewrite the following paragraph to be concise and professional without losing any facts: Our team ran several experiments over the last two weeks, but because each trial used a different environment and no frozen baseline, the reported improvements cannot yet be compared reliably.",
    ),
    (
        "systems-design",
        "Design a bounded GPU-kernel optimization loop for an autonomous agent. Focus on candidate diversity, fail-fast checks, correctness gates, measurement noise, and stopping rules.",
    ),
    (
        "translation",
        "Translate into natural Chinese and briefly explain the technical meaning: Speculative decoding reduces latency only when accepted draft tokens amortize the verification cost.",
    ),
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


def nvcc_release() -> str | None:
    executable = shutil.which("nvcc")
    if executable is None:
        return None
    result = subprocess.run(
        [executable, "--version"], capture_output=True, text=True, check=False
    )
    match = re.search(r"release\s+(\d+\.\d+)", result.stdout + result.stderr)
    return match.group(1) if match else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--new-tokens", type=int, default=128)
    parser.add_argument(
        "--prompt-suite", choices=("synthetic", "natural"), default="synthetic"
    )
    parser.add_argument("--gpu-memory-utilization", type=float, default=0.70)
    parser.add_argument("--kv-cache-memory-bytes", type=int, default=None)
    parser.add_argument("--enforce-eager", action="store_true")
    parser.add_argument("--max-num-seqs", type=int, default=None)
    parser.add_argument("--max-num-batched-tokens", type=int, default=None)
    parser.add_argument(
        "--speculative-tokens",
        type=int,
        default=0,
        help="Enable the model's native MTP proposer with this many draft tokens.",
    )
    parser.add_argument(
        "--ngram-speculative-tokens",
        type=int,
        default=0,
        help="Enable the zero-weight n-gram proposer with this many draft tokens.",
    )
    parser.add_argument("--ngram-prompt-lookup-min", type=int, default=2)
    parser.add_argument("--ngram-prompt-lookup-max", type=int, default=5)
    parser.add_argument(
        "--chunked-prefill",
        choices=("default", "on", "off"),
        default="default",
    )
    parser.add_argument(
        "--kv-cache-dtype",
        choices=("auto", "fp8"),
        default="auto",
    )
    parser.add_argument(
        "--custom-ops",
        choices=("default", "all", "none"),
        default="default",
    )
    parser.add_argument(
        "--quantization",
        choices=("none", "fp8", "int8_per_channel_weight_only"),
        default="none",
    )
    args = parser.parse_args()
    if args.warmups < 1 or args.trials < 1:
        raise ValueError("warmups and trials must both be positive")
    if args.max_num_seqs is not None and args.max_num_seqs < 1:
        raise ValueError("max-num-seqs must be positive")
    if args.max_num_batched_tokens is not None and args.max_num_batched_tokens < 1:
        raise ValueError("max-num-batched-tokens must be positive")
    if args.speculative_tokens < 0:
        raise ValueError("speculative-tokens must be non-negative")
    if args.ngram_speculative_tokens < 0:
        raise ValueError("ngram-speculative-tokens must be non-negative")
    if args.speculative_tokens and args.ngram_speculative_tokens:
        raise ValueError("MTP and n-gram speculation are mutually exclusive")
    if args.ngram_prompt_lookup_min < 1:
        raise ValueError("ngram-prompt-lookup-min must be positive")
    if args.ngram_prompt_lookup_max < args.ngram_prompt_lookup_min:
        raise ValueError("ngram-prompt-lookup-max must be >= lookup-min")
    if args.kv_cache_memory_bytes is not None:
        if args.kv_cache_memory_bytes < 1:
            raise ValueError("kv-cache-memory-bytes must be positive")
        if args.max_num_seqs is None:
            raise ValueError(
                "fixed KV cache requires explicit --max-num-seqs so the high "
                "engine default cannot cause an avoidable late Mamba-cache failure"
            )
    import torch

    selected_nvcc = nvcc_release()
    if args.kv_cache_dtype == "fp8":
        runtime_cuda = str(torch.version.cuda or "")
        if selected_nvcc is None or selected_nvcc != runtime_cuda:
            raise RuntimeError(
                "FP8 KV cache requires FlashInfer JIT in this environment, but "
                f"nvcc={selected_nvcc!r} and torch CUDA runtime={runtime_cuda!r}; "
                "align compiler and runtime headers before launching the engine"
            )

    import transformers
    import triton
    import vllm
    from transformers import AutoTokenizer
    from vllm import LLM, SamplingParams

    model_path = args.model.resolve()
    tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True)
    if args.prompt_suite == "synthetic":
        cases = list(SYNTHETIC_CASES)
        prompts = {
            case_id: exact_prompt(tokenizer, length)
            for case_id, length, _ in cases
        }
    else:
        prompts = {}
        for case_id, request in NATURAL_REQUESTS:
            rendered = tokenizer.apply_chat_template(
                [{"role": "user", "content": request}],
                tokenize=False,
                add_generation_prompt=True,
                enable_thinking=False,
            )
            prompts[case_id] = tokenizer.encode(rendered, add_special_tokens=False)
            if not prompts[case_id] or not all(
                isinstance(token_id, int) for token_id in prompts[case_id]
            ):
                raise TypeError(f"chat template produced invalid token IDs for {case_id}")
        weight = 1.0 / len(NATURAL_REQUESTS)
        cases = [
            (case_id, len(prompts[case_id]), weight)
            for case_id, _ in NATURAL_REQUESTS
        ]
    params = SamplingParams(
        temperature=0.0,
        max_tokens=args.new_tokens,
        ignore_eos=True,
        detokenize=False,
        seed=20260902,
    )

    init_started = time.perf_counter()
    engine_overrides = {}
    if args.max_num_seqs is not None:
        engine_overrides["max_num_seqs"] = args.max_num_seqs
    if args.max_num_batched_tokens is not None:
        engine_overrides["max_num_batched_tokens"] = args.max_num_batched_tokens
    if args.chunked_prefill != "default":
        engine_overrides["enable_chunked_prefill"] = args.chunked_prefill == "on"
    if args.custom_ops != "default":
        engine_overrides["compilation_config"] = {"custom_ops": [args.custom_ops]}
    if args.speculative_tokens:
        engine_overrides["speculative_config"] = {
            "method": "mtp",
            "num_speculative_tokens": args.speculative_tokens,
        }
    elif args.ngram_speculative_tokens:
        engine_overrides["speculative_config"] = {
            "method": "ngram",
            "num_speculative_tokens": args.ngram_speculative_tokens,
            "prompt_lookup_min": args.ngram_prompt_lookup_min,
            "prompt_lookup_max": args.ngram_prompt_lookup_max,
        }

    llm = LLM(
        model=str(model_path),
        dtype="bfloat16",
        quantization=None if args.quantization == "none" else args.quantization,
        max_model_len=4096,
        gpu_memory_utilization=args.gpu_memory_utilization,
        kv_cache_memory_bytes=args.kv_cache_memory_bytes,
        enforce_eager=args.enforce_eager,
        language_model_only=True,
        enable_prefix_caching=False,
        disable_log_stats=False,
        kv_cache_dtype=args.kv_cache_dtype,
        seed=20260902,
        **engine_overrides,
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
    case_ids = [item[0] for item in cases]
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
    for case_id, prompt_tokens, weight in cases:
        measured = [sample for sample in samples if sample["case_id"] == case_id and sample["phase"] == "measure"]
        reference_ids = measured[0]["generated_token_ids"]
        exact_repeat = all(sample["generated_token_ids"] == reference_ids for sample in measured)
        summaries.append({
            "case_id": case_id,
            "weight": weight,
            "prompt_tokens": prompt_tokens,
            "prompt_token_ids_sha256": hashlib.sha256(
                json.dumps(prompts[case_id], separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
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
            "nvcc_release": selected_nvcc,
            "triton": triton.__version__,
            "transformers": transformers.__version__,
            "vllm_use_v2_model_runner": os.environ.get("VLLM_USE_V2_MODEL_RUNNER"),
            "vllm_use_flashinfer_sampler": os.environ.get("VLLM_USE_FLASHINFER_SAMPLER"),
            "vllm_gdn_decode_kernel": os.environ.get("VLLM_GDN_DECODE_KERNEL", "cuda(default)"),
            "vllm_enable_fla_packed_recurrent_decode": os.environ.get(
                "VLLM_ENABLE_FLA_PACKED_RECURRENT_DECODE", "1(default)"
            ),
        },
        "controls": {
            "language_model_only": True,
            "dtype": "bfloat16",
            "quantization": args.quantization,
            "prompt_suite": args.prompt_suite,
            "max_model_len": 4096,
            "enable_prefix_caching": False,
            "enforce_eager": args.enforce_eager,
            "gpu_memory_utilization": args.gpu_memory_utilization,
            "kv_cache_memory_bytes": args.kv_cache_memory_bytes,
            "max_num_seqs": args.max_num_seqs,
            "max_num_batched_tokens": args.max_num_batched_tokens,
            "speculative_tokens": args.speculative_tokens,
            "ngram_speculative_tokens": args.ngram_speculative_tokens,
            "ngram_prompt_lookup_min": args.ngram_prompt_lookup_min,
            "ngram_prompt_lookup_max": args.ngram_prompt_lookup_max,
            "chunked_prefill": args.chunked_prefill,
            "kv_cache_dtype": args.kv_cache_dtype,
            "custom_ops": args.custom_ops,
            "warmups": args.warmups,
            "trials": args.trials,
            "case_order": "rotated per iteration",
            "sampling": (
                f"greedy temperature=0, ignore_eos=True, exact {args.new_tokens} tokens"
            ),
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
