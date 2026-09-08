#!/usr/bin/env python3
"""Capture top-5 decode logprobs for a vLLM-style correctness oracle."""

import argparse
import hashlib
import json
import time
from pathlib import Path

import torch
from transformers import AutoTokenizer
from vllm import LLM, SamplingParams

from benchmark_vllm_offline import NATURAL_REQUESTS


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, required=True)
    parser.add_argument("--new-tokens", type=int, default=64)
    args = parser.parse_args()
    if args.batch_size < 1:
        raise ValueError("batch-size must be positive")

    tokenizer = AutoTokenizer.from_pretrained(args.model, local_files_only=True)
    prompt_ids = []
    for index in range(args.batch_size):
        _, text = NATURAL_REQUESTS[index % len(NATURAL_REQUESTS)]
        rendered = tokenizer.apply_chat_template(
            [{"role": "user", "content": text}],
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=False,
        )
        prompt_ids.append(tokenizer.encode(rendered, add_special_tokens=False))

    llm = LLM(
        model=str(args.model),
        tokenizer=str(args.model),
        dtype="bfloat16",
        quantization="gptq_marlin",
        max_model_len=4096,
        max_num_seqs=args.batch_size,
        gpu_memory_utilization=0.70,
        language_model_only=True,
        enable_prefix_caching=False,
        disable_log_stats=False,
        seed=20260902,
    )
    params = SamplingParams(
        temperature=0.0,
        max_tokens=args.new_tokens,
        ignore_eos=True,
        detokenize=False,
        seed=20260902,
        logprobs=5,
    )
    inputs = [{"prompt_token_ids": ids} for ids in prompt_ids]

    warmup = llm.generate(inputs, params, use_tqdm=False)
    if any(len(item.outputs[0].token_ids) != args.new_tokens for item in warmup):
        raise RuntimeError("warmup did not generate the frozen token count")

    torch.cuda.synchronize()
    torch.cuda.cudart().cudaProfilerStart()
    started = time.perf_counter()
    outputs = llm.generate(inputs, params, use_tqdm=False)
    elapsed = time.perf_counter() - started
    torch.cuda.synchronize()
    torch.cuda.cudart().cudaProfilerStop()

    generated = [list(item.outputs[0].token_ids) for item in outputs]
    logprobs = []
    for item in outputs:
        completion_logprobs = item.outputs[0].logprobs
        if completion_logprobs is None:
            raise RuntimeError("top-5 logprobs were requested but not returned")
        packed_positions = []
        for position in completion_logprobs:
            packed_positions.append(
                {
                    str(token_id): {
                        "logprob": value.logprob,
                        "rank": value.rank,
                    }
                    for token_id, value in position.items()
                }
            )
        logprobs.append(packed_positions)
    status = (
        "PASS"
        if len(generated) == args.batch_size
        and all(len(ids) == args.new_tokens for ids in generated)
        else "FAIL"
    )
    payload = {
        "schema_version": "vllm-workload-profile-v1",
        "status": status,
        "batch_size": args.batch_size,
        "new_tokens": args.new_tokens,
        "elapsed_ms": elapsed * 1000.0,
        "aggregate_output_tokens_per_second": (
            args.batch_size * args.new_tokens / elapsed
        ),
        "prompt_token_ids_sha256": [
            hashlib.sha256(
                json.dumps(ids, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            for ids in prompt_ids
        ],
        "generated_token_ids": generated,
        "top5_logprobs": logprobs,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    if status != "PASS":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
