#!/usr/bin/env python3
"""Bounded vLLM offline smoke with exact token IDs and immutable receipts."""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import torch
import transformers
import triton
import vllm
from transformers import AutoTokenizer
from vllm import LLM, SamplingParams


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(8 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def prompt_ids(tokenizer, length: int) -> list[int]:
    seed_text = "Kernel optimization must preserve semantics while reducing global latency. "
    seed = tokenizer.encode(seed_text, add_special_tokens=False)
    if not seed:
        raise RuntimeError("tokenizer produced an empty seed")
    return (seed * ((length + len(seed) - 1) // len(seed)))[:length]


def serializable_metrics(metrics):
    if metrics is None:
        return None
    if dataclasses.is_dataclass(metrics):
        return dataclasses.asdict(metrics)
    if hasattr(metrics, "__dict__"):
        return {key: value for key, value in vars(metrics).items() if isinstance(value, (str, int, float, bool, type(None)))}
    return str(metrics)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--prompt-tokens", type=int, default=16)
    parser.add_argument("--new-tokens", type=int, default=2)
    parser.add_argument("--gpu-memory-utilization", type=float, default=0.70)
    parser.add_argument("--enforce-eager", action="store_true")
    parser.add_argument(
        "--quantization",
        choices=("none", "fp8", "int8_per_channel_weight_only"),
        default="none",
    )
    args = parser.parse_args()
    model_path = args.model.resolve()
    tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True)
    tokens = prompt_ids(tokenizer, args.prompt_tokens)

    free_before, total_memory = torch.cuda.mem_get_info()
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
    free_after_init, _ = torch.cuda.mem_get_info()
    params = SamplingParams(
        temperature=0.0,
        max_tokens=args.new_tokens,
        ignore_eos=True,
        detokenize=False,
        seed=20260902,
    )

    def generate():
        started = time.perf_counter()
        outputs = llm.generate({"prompt_token_ids": tokens}, params, use_tqdm=False)
        elapsed = time.perf_counter() - started
        if len(outputs) != 1 or len(outputs[0].outputs) != 1:
            raise RuntimeError("expected exactly one request and one completion")
        return outputs[0], elapsed

    first, first_seconds = generate()
    second, warm_seconds = generate()
    first_ids = list(first.outputs[0].token_ids)
    second_ids = list(second.outputs[0].token_ids)
    deterministic = first_ids == second_ids and len(second_ids) == args.new_tokens
    payload = {
        "schema_version": "qwen35-vllm-offline-smoke-v1",
        "status": "PASS" if deterministic else "FAIL",
        "claim_scope": (
            "CORRECTNESS_AND_ENVIRONMENT_SMOKE_NOT_PRODUCTION_BASELINE"
            if args.quantization == "none"
            else "EXPLORATORY_QUANTIZED_SMOKE_REQUIRES_NEW_NUMERICS_CONTRACT"
        ),
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "model": {
            "path": str(model_path),
            "config_sha256": sha256(model_path / "config.json"),
            "weight_sha256": sha256(model_path / "model.safetensors-00001-of-00001.safetensors"),
            "language_model_only": True,
            "dtype": "bfloat16",
            "quantization": args.quantization,
            "max_model_len": 4096,
        },
        "environment": {
            "gpu": torch.cuda.get_device_name(0),
            "compute_capability": ".".join(map(str, torch.cuda.get_device_capability(0))),
            "vllm": vllm.__version__,
            "torch": torch.__version__,
            "cuda": torch.version.cuda,
            "triton": triton.__version__,
            "transformers": transformers.__version__,
        },
        "engine": {
            "enforce_eager": args.enforce_eager,
            "gpu_memory_utilization": args.gpu_memory_utilization,
            "enable_prefix_caching": False,
            "request_metrics_enabled": True,
            "vllm_use_v2_model_runner": os.environ.get("VLLM_USE_V2_MODEL_RUNNER"),
            "vllm_use_flashinfer_sampler": os.environ.get("VLLM_USE_FLASHINFER_SAMPLER"),
            "initialization_seconds": init_seconds,
            "free_gpu_bytes_before": free_before,
            "free_gpu_bytes_after_init": free_after_init,
            "total_gpu_bytes": total_memory,
        },
        "input": {"prompt_tokens": len(tokens), "prompt_token_ids": tokens, "new_tokens": args.new_tokens},
        "output": {
            "generated_token_ids": second_ids,
            "deterministic_repeat": deterministic,
            "first_request_seconds": first_seconds,
            "warm_request_seconds": warm_seconds,
            "request_metrics": serializable_metrics(second.metrics),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
