"""Distinguish eliminated Python allocation from retained captured CUDA work.

This is a Torch mechanism experiment, not an attention/backend qualification.
The caller must select an authorized, sufficiently free device before execution.
"""

import argparse
import json
import random
import statistics
import time


def balanced_orders(pairs, seed=17):
    orders = [("fresh", "cached"), ("cached", "fresh")] * ((pairs + 1) // 2)
    random.Random(seed).shuffle(orders)
    return orders[:pairs]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--pairs", type=int, default=12)
    parser.add_argument("--replays", type=int, default=64)
    args = parser.parse_args()
    if not 2 <= args.pairs <= 32 or args.pairs % 2 or not 1 <= args.replays <= 256:
        parser.error("use an even 2..32 pairs and 1..256 replays")

    import torch

    started = time.perf_counter()
    device = torch.device(args.device)
    if device.type != "cuda" or not torch.cuda.is_available():
        raise RuntimeError("an authorized CUDA device is required")
    torch.cuda.set_device(device)
    torch.cuda.reset_peak_memory_stats(device)
    x = torch.ones((1,), dtype=torch.float32, device=device)
    constants = tuple(torch.ones_like(x) for _ in range(3))
    calls = {"fresh": 0, "cached": 0}

    def body(name):
        calls[name] += 1
        scales = (
            tuple(torch.ones_like(x) for _ in range(3))
            if name == "fresh"
            else constants
        )
        return x + scales[0] + scales[1] + scales[2]

    stream = torch.cuda.Stream(device=device)
    stream.wait_stream(torch.cuda.current_stream(device))
    with torch.cuda.stream(stream):
        for _ in range(3):
            for name in calls:
                body(name)
    torch.cuda.current_stream(device).wait_stream(stream)
    graphs = {}
    outputs = {}
    for name in calls:
        graphs[name] = torch.cuda.CUDAGraph()
        with torch.cuda.graph(graphs[name], stream=stream):
            outputs[name] = body(name)
    captured_calls = calls.copy()
    samples = {name: [] for name in calls}
    for order in balanced_orders(args.pairs):
        for name in order:
            start = torch.cuda.Event(enable_timing=True)
            end = torch.cuda.Event(enable_timing=True)
            start.record()
            for _ in range(args.replays):
                graphs[name].replay()
            end.record()
            end.synchronize()
            samples[name].append(start.elapsed_time(end) / args.replays)
    if calls != captured_calls:
        raise AssertionError("replay unexpectedly reentered the Python body")
    for output in outputs.values():
        torch.testing.assert_close(output, torch.full_like(x, 4), rtol=0, atol=0)
    for scale in constants:
        torch.testing.assert_close(scale, x, rtol=0, atol=0)

    profiles = {}
    for name in calls:
        try:
            with torch.profiler.profile(
                activities=[
                    torch.profiler.ProfilerActivity.CPU,
                    torch.profiler.ProfilerActivity.CUDA,
                ]
            ) as profile:
                graphs[name].replay()
                torch.cuda.synchronize(device)
            kernels = [
                event.name
                for event in profile.events()
                if event.device_type == torch.autograd.DeviceType.CUDA
            ]
            profiles[name] = {"cuda_events": kernels, "count": len(kernels)}
        except RuntimeError as error:
            profiles[name] = {"error": str(error), "count": None}
    print(
        json.dumps(
            {
                "scope": "TORCH_CONSTANT_GRAPH_MECHANISM_ONLY",
                "torch": torch.__version__,
                "device": torch.cuda.get_device_name(device),
                "correctness": "EXACT_SCALAR_OUTPUT_AND_CACHED_INPUT_PASS",
                "python_body_calls_after_capture": captured_calls,
                "python_body_calls_after_replay": calls,
                "cuda_event_ms_per_replay": samples,
                "median_ms": {
                    name: statistics.median(values) for name, values in samples.items()
                },
                "profiles": profiles,
                "peak_allocated_bytes": torch.cuda.max_memory_allocated(device),
                "wall_seconds": time.perf_counter() - started,
                "attention_correctness": "NOT_RUN",
                "whole_workload_gain": None,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
