# Scout GPU correctness screen

Scout may propose a baseline, candidate, and test, but generated Python is **not**
automatically executable on a shared machine. A reviewer checks imports, side
effects, tensor sizes, and the test oracle, then pins the three SHA-256 hashes
in a JSON manifest. The reviewed queue consumes only a separate approval that
pins that manifest, the job, the worker, and the full GPU UUID.

`scripts/kimi_scout_gpu_queue.py` watches
`<run-root>/delivery/gpu-approved/<24-hex-job-id>.json`. Use
`--once` for a dry operational check, or run it with a bounded polling interval
for continuous work. Each approval creates a terminal file under
`delivery/gpu-results` **before** any remote command. An interrupted or
uncertain dispatch is never retried automatically. `delivery/GPU_STOP` stops
the polling loop after the current attempt.

If an attempt fails for an infrastructure reason, a reviewer may issue a new,
versioned approval only after inspecting the terminal result and confirming
that every arm cleaned up. The new approval binds the previous terminal hash;
the queue never silently retries an old approval. The latest compact screen
result is published to `delivery/gpu-latest.json` for the dashboard.

The dispatcher rehashes all inputs on both machines, selects one full CUDA
UUID, checks three live headroom samples, caps each child to 30 seconds and
4 GiB of Torch allocation, runs it as an unprivileged user, and checks cleanup.
An occupied card can be used for this small correctness screen if at least
6 GiB is free and utilization remains at most 80%; no process is stopped.
The result is only `SCREEN_PASS_NOT_UPSTREAM_QUALIFIED` when the baseline has
a discriminating failure and the candidate passes the *same* tests. It is not
an upstream suite, performance measurement, or PR-readiness verdict.

The current worker uses SSH to a Linux Torch/Triton environment and is not a
sandbox for arbitrary model-generated code. In particular, it does not provide
network or filesystem namespace isolation. Keep human/controller review in the
loop until a separate disposable sandbox is available. NVIDIA hardware can
run this CUDA screen; ROCm candidates require an AMD worker and a separate
backend-specific verifier.
