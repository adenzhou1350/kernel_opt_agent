#!/usr/bin/env python3
"""Run one immutable lm-head treatment in a persistent vLLM process."""

from __future__ import annotations

import argparse
import hashlib
import importlib.abc
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import sys
import time


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def install_source_package(source: Path, binary: Path) -> None:
    """Load Python from the PR checkout while resolving compiled extensions locally."""
    class VllmOverlayFinder(importlib.abc.MetaPathFinder):
        """Append the wheel fallback to every nested source package."""

        def find_spec(self, fullname, path=None, target=None):
            if not fullname.startswith("vllm."):
                return None
            spec = importlib.machinery.PathFinder.find_spec(fullname, path, target)
            if spec is None or spec.submodule_search_locations is None:
                return spec
            fallback = binary.joinpath(*fullname.split(".")[1:])
            if fallback.is_dir():
                fallback_text = str(fallback)
                if fallback_text not in spec.submodule_search_locations:
                    spec.submodule_search_locations.append(fallback_text)
            return spec

    sys.meta_path.insert(0, VllmOverlayFinder())
    spec = importlib.util.spec_from_file_location(
        "vllm",
        source / "__init__.py",
        submodule_search_locations=[str(source), str(binary)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to construct the vLLM source package")
    module = importlib.util.module_from_spec(spec)
    sys.modules["vllm"] = module
    spec.loader.exec_module(module)


def emit(stream, value: dict) -> None:
    stream.write(json.dumps(value, sort_keys=True) + "\n")
    stream.flush()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session-manifest", type=Path, required=True)
    parser.add_argument("--treatment-manifest", type=Path, required=True)
    parser.add_argument("--source-identity", type=Path, required=True)
    args = parser.parse_args()

    session_path = args.session_manifest.resolve()
    treatment_path = args.treatment_manifest.resolve()
    source_identity_path = args.source_identity.resolve()
    session = json.loads(session_path.read_text(encoding="utf-8"))
    treatment = json.loads(treatment_path.read_text(encoding="utf-8"))
    source_identity = json.loads(source_identity_path.read_text(encoding="utf-8"))
    for item in source_identity["files"]:
        path = Path(item["path"])
        if sha256(path) != item["sha256"]:
            raise RuntimeError(f"source identity mismatch: {path}")

    os.environ.setdefault("VLLM_ENABLE_V1_MULTIPROCESSING", "0")
    os.environ.setdefault("VLLM_WSL2_ENABLE_PIN_MEMORY", "1")
    os.environ.setdefault("VLLM_USE_FLASHINFER_SAMPLER", "0")
    protocol_stdout = sys.stdout
    sys.stdout = sys.stderr
    install_source_package(
        Path(session["source_package"]), Path(session["binary_package"])
    )

    import torch
    from torch.profiler import ProfilerActivity, profile
    from transformers import AutoTokenizer
    from vllm import LLM, SamplingParams

    model = session["model"]
    tokenizer_path = session["tokenizer"]
    backend = treatment["lm_head_backend"]
    tokenizer = AutoTokenizer.from_pretrained(tokenizer_path, local_files_only=True)
    llm = LLM(
        model=model,
        tokenizer=tokenizer_path,
        dtype="bfloat16",
        max_model_len=256,
        gpu_memory_utilization=0.70,
        kv_cache_memory_bytes=536_870_912,
        max_num_seqs=1,
        language_model_only=True,
        enable_prefix_caching=False,
        seed=int(session["seed"]),
        kernel_config={
            "lm_head_backend": backend,
            "lm_head_max_packed_fraction": float(
                treatment["lm_head_max_packed_fraction"]
            ),
        },
    )
    warmup_ids = tokenizer.encode("Persistent lm-head warmup:", add_special_tokens=False)
    warmup_params = SamplingParams(
        temperature=0.0,
        max_tokens=8,
        ignore_eos=True,
        seed=int(session["seed"]),
    )
    llm.generate(
        [{"prompt_token_ids": warmup_ids}], warmup_params, use_tqdm=False
    )
    torch.cuda.synchronize()

    with profile(activities=[ProfilerActivity.CPU, ProfilerActivity.CUDA]) as prof:
        llm.generate(
            [{"prompt_token_ids": warmup_ids}], warmup_params, use_tqdm=False
        )
        torch.cuda.synchronize()
    packed_event_count = sum(
        int(event.count)
        for event in prof.key_averages()
        if "lossless_packed_bf16_lm_head" in event.key
    )
    if backend == "lossless_packed" and packed_event_count < 1:
        raise RuntimeError("the requested packed backend was not observed in execution")
    if backend == "torch" and packed_event_count != 0:
        raise RuntimeError("the baseline unexpectedly executed the packed backend")

    session_identity = sha256(session_path)
    treatment_identity = sha256(treatment_path)
    emit(
        protocol_stdout,
        {
            "event": "ready",
            "protocol": "persistent-session-v1",
            "session_identity": session_identity,
            "switching_supported": False,
            "engine_init_count": 1,
            "backend": backend,
            "packed_kernel_event_count": packed_event_count,
            "vllm_source_commit": source_identity["git_commit"],
        },
    )

    for line in sys.stdin:
        message = json.loads(line)
        if message.get("event") == "shutdown":
            return 0
        if message.get("event") != "request":
            raise ValueError("unsupported protocol event")
        if message.get("treatment_identity") != treatment_identity:
            raise ValueError("unknown treatment identity")
        payload = message["payload"]
        prompt_ids = tokenizer.encode(payload["prompt"], add_special_tokens=False)
        params = SamplingParams(
            temperature=0.0,
            max_tokens=int(payload["tokens"]),
            ignore_eos=True,
            seed=int(session["seed"]),
        )
        torch.cuda.synchronize()
        started = time.perf_counter()
        outputs = llm.generate(
            [{"prompt_token_ids": prompt_ids}], params, use_tqdm=False
        )
        torch.cuda.synchronize()
        duration = time.perf_counter() - started
        token_ids = list(outputs[0].outputs[0].token_ids)
        emit(
            protocol_stdout,
            {
                "event": "result",
                "request_id": message["request_id"],
                "treatment_identity": treatment_identity,
                "output_digest": hashlib.sha256(
                    json.dumps(token_ids, separators=(",", ":")).encode("utf-8")
                ).hexdigest(),
                "measurement": {
                    "tokens": len(token_ids),
                    "wall_seconds": duration,
                    "ms_per_token": duration * 1000.0 / len(token_ids),
                },
            },
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
