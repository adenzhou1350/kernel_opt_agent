"""Bounded GPU comparison; run only inside an existing exclusive allocation."""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import random
import statistics
import time


def summarize(pairs, name):
    deltas = [pair["times_us"][name] - pair["times_us"]["cublas"] for pair in pairs]
    rng = random.Random(701)
    boot = sorted(statistics.median(rng.choices(deltas, k=len(deltas))) for _ in range(5000))
    candidate = statistics.median(pair["times_us"][name] for pair in pairs)
    baseline = statistics.median(pair["times_us"]["cublas"] for pair in pairs)
    return {"median_us": candidate, "baseline_median_us": baseline,
            "baseline_over_candidate": baseline / candidate,
            "median_paired_delta_us": statistics.median(deltas),
            "paired_median_delta_95pct_us": [boot[125], boot[4874]]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pairs", type=int, default=7)
    args = parser.parse_args()
    if not 3 <= args.pairs <= 15:
        parser.error("pairs must be between 3 and 15")
    expected_uuid = os.environ["EXPECTED_GPU_UUID"]
    assert os.environ["CUDA_VISIBLE_DEVICES"] == expected_uuid
    import torch
    from tirx_kernels.gemm import fp16_bf16_gemm as gemm
    from tirx_kernels.runner import compile_kernel, cuda_target
    from tvm.tirx.bench import bench
    assert torch.cuda.device_count() == 1
    props = torch.cuda.get_device_properties(0)
    observed = str(props.uuid)
    observed = observed if observed.startswith("GPU-") else "GPU-" + observed
    assert observed == expected_uuid
    assert torch.cuda.get_device_capability() == (10, 3), "this pilot targets B300 only"
    result = {"status": "RUNNING", "gpu_uuid": observed, "gpu_name": props.name,
              "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "kernel_library_sha256": hashlib.sha256(Path(gemm.__file__).read_bytes()).hexdigest(),
              "versions": {name: importlib.metadata.version(name) for name in ("tirx-harness", "tirx-kernels", "torch")},
              "contract": {"operation": "C = A @ B.T", "rtol": 0.001, "atol": 0.01,
                           "seeds": [13, 29, 71], "timer": "event", "warmup_ms": 10,
                           "repeat_ms": 30, "cooldown_s": 0.1, "pairs": args.pairs,
                           "cache_state": "warm repeated operands; no cold-cache or end-to-end claim"},
              "cases": [], "scope": "kernel comparison, not agent-system A/B"}

    def save():
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")

    save()
    order_rng = random.Random(20260930)
    for dtype, size in [("fp16", 1024), ("fp16", 2048), ("fp16", 4096), ("bf16", 1024)]:
        started = time.monotonic()
        row = {"dtype": dtype, "M": size, "N": size, "K": size, "status": "RUNNING",
               "correctness": [], "pairs": []}
        result["cases"].append(row)
        save()
        target = cuda_target()
        with target:
            executable = compile_kernel(gemm.get_kernel(dtype, size, size, size))
        executables = {"tirx_default": executable}
        if dtype == "fp16" and size == 1024:
            original = dict(gemm.GEMM_CONFIGS[1024])
            variant = dict(original, cta_n=128, pipe_depth=4)
            try:
                gemm.GEMM_CONFIGS[1024] = variant
                with target:
                    executables["tirx_variant"] = compile_kernel(gemm.get_kernel(dtype, size, size, size))
            finally:
                gemm.GEMM_CONFIGS[1024] = original
            row["variant"] = variant
            row["variant_scope"] = "one exploratory tile/pipeline candidate, not a tuned optimum"
        for seed in result["contract"]["seeds"]:
            torch.manual_seed(seed)
            A, B, _ = gemm.prepare_data(dtype, size, size, size)
            reference = torch.matmul(A, B.T)
            buffers = {name: torch.empty_like(reference) for name in executables}
            for name, candidate in executables.items():
                candidate(A, B, buffers[name])
                torch.cuda.synchronize()
                torch.testing.assert_close(buffers[name], reference, rtol=0.001, atol=0.01)
                row["correctness"].append({"implementation": name, "seed": seed, "status": "PASS",
                                           "max_abs_error": float((buffers[name].float() - reference.float()).abs().max())})
        # All arms use the last seed's identical input storage and output layout.
        baseline_output = torch.empty_like(reference)
        funcs = {name: (lambda candidate=candidate, output=buffers[name]: candidate(A, B, output))
                 for name, candidate in executables.items()}
        funcs["cublas"] = lambda: torch.matmul(A, B.T, out=baseline_output)
        for pair in range(args.pairs):
            order = list(funcs)
            order_rng.shuffle(order)
            measured = bench({name: funcs[name] for name in order}, timer="event", warmup=10,
                             repeat=30, cooldown_s=0.1, rounds=1)
            assert not measured["errors"]
            row["pairs"].append({"pair": pair, "order": order, "times_us": measured["impls"],
                                  "protocol": measured["benchmark_protocol"]})
        for name in executables:
            torch.testing.assert_close(buffers[name], baseline_output, rtol=0.001, atol=0.01)
        row["summaries"] = {name: summarize(row["pairs"], name) for name in executables}
        row["status"] = "PASS"
        row["elapsed_s"] = time.monotonic() - started
        save()
        print(json.dumps({"dtype": dtype, "size": size, "summaries": row["summaries"]}), flush=True)
    result["status"] = "PASS"
    save()


if __name__ == "__main__":
    main()
