# Constant initialization can survive CUDA graph capture

`check_constant_initialization.py` contrasts three fresh float32 unit tensors
inside capture with three distinct precreated tensors. Both arms perform the
same three additions and verify the exact scalar output and unchanged cached
inputs. Python-body counters prove replay does not reenter the body; optional
native CUDA profiler events expose the work that still runs.

Select an authorized, sufficiently free GPU externally. Use an existing compatible
Torch/CUDA interpreter; the script does not install dependencies, download models,
start WSL, select shared resources or change another process:

```sh
python check_constant_initialization.py --device cuda:0 --pairs 12 --replays 64
```

The even paired schedule is deterministically order-balanced and shuffled. Samples
are CUDA-event **mechanism** timings, not attention latency, service throughput,
or an end-to-end confidence interval. A missing CUDA profiler or empty trace is
not evidence of zero work. No output files are created by the script.

Observed on native Windows, Torch 2.11.0+cu128 and RTX 4060 Laptop: both graph
arms preserve exact output and Python call counts. The fresh graph exposes three
`FillFunctor` and three add kernels; the cached graph exposes only three add
kernels. One 12-pair run has median replay times 10.854 vs 10.984 microseconds,
so it does **not** demonstrate a performance gain. Peak Torch allocation is
5,632 bytes. The point is the execution distinction, not this tiny timing.

This experiment is deliberately not a SGLang/FlashMLA reproduction. Before
caching a backend's scales, establish its supported architecture, real caller,
input mutation/retention contract, stream/device lifetime, numerical correctness
and matched production-mode performance. Captured device fills are not Python
allocation overhead; eliminating either is not automatically material.
