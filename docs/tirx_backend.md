# Optional TIRx backend

Keep the existing task discovery, workload selection, evidence reuse and delivery
loop. For a TIRx candidate, use compiler feedback as another tool in that loop:

1. Select the computation, concrete inputs, independent reference and tolerance.
2. Screen synchronization, races and numerical output on CPU.
3. Repair findings; treat unsupported analysis and environment errors as unknown,
   not evidence that the candidate is incorrect. A clean CPU check covers only
   the supported model and these inputs.
4. On an allocated compatible GPU, check real outputs and then measure matched,
   interleaved/randomized baseline/candidate workloads. Include negative and
   regression cases, and retain other backends when they are better.
5. Link the result and logs in the existing worklog. Extract an applicable lesson
   or complete implementation when it changes a future decision.

The public interface needs only the standard library for help and metadata:

```sh
python scripts/kernel_opt.py tirx probe
```

Run `check` with a Linux interpreter whose private environment contains the
TIRx Harness and its compiler/Rust dependencies. Nothing is automatically
installed, dispatched to a remote host, or assigned a GPU.

```sh
python scripts/kernel_opt.py tirx check \
  --case-file examples/tirx/affine_cases.py --case valid \
  --output runs/tirx-example/cpu.json --timeout 300
python scripts/kernel_opt.py worklog record --run runs/my-optimization \
  --kind correctness --summary "TIRx concrete CPU checks passed; GPU validation pending" \
  --evidence runs/tirx-example/cpu.json --command "<actual check command>"
```

The example is a complete 32-element FP32 affine kernel with exact NumPy
reference. Its `numerical_bug`, `race_bug` and `sync_bug` cases are deliberate
CPU-only negative controls. They should fail; never submit them to a GPU.
These are adapter regression examples, not production optimization results.

A trusted Python case file exports `make_case(name)`, returning `kernel`,
`inputs`, `expected` (output-name to independent NumPy reference), and explicit
`rtol`/`atol`. The adapter accepts a TIRx PrimFunc or TIRx-lite wrapper `.func`.
Each checker and simulator gets fresh copies of array buffers. Scalar bindings
are retained. Output shape is checked and nonfinite outputs are rejected.
Numerical checks do not establish dtype/storage-layout equivalence. Use the
target project's full contract for that. Empty references cannot pass.
Integer and boolean comparisons are exact, even with nonzero tolerances; mixed
signed/unsigned values are compared without conversion to floating point.

## Generated-code feedback

Use the installed compiler environment to inspect a candidate without allocating
a GPU. The explicit compatible architecture avoids auto-detecting a different
device on a shared host:

```sh
python scripts/kernel_opt.py tirx inspect \
  --case-file examples/tirx/feedback_cases.py --case persistent:4194313 \
  --arch sm_103a --output runs/my-optimization/inspect.json --timeout 180
```

The bounded child compiles under the official CUDA initialization guard, with
GPU visibility disabled, then calls `tirx_harness.dump_kernel.dump_module`.
It records CUDA/PTX/cubin/SASS paths and hashes, raw ptxas logs, reported
resources, source identity, errors and package versions. Requested-stage errors
return exit 2, preserving partial artifacts. The dump API regenerates a cubin;
it does not establish identity with the binary loaded by a separate GPU run.
Match compilation settings before using its resources for a causal claim.
Missing static SMEM in a ptxas report is not proof of zero dynamic shared memory.

For wrong values use `check`; for generated instructions or spills use `inspect`;
for hardware counters and pipeline overlap use an available NCU/IKET profiler
or independent targeted measurements. Follow
[TIRx workflow routing](../skill/kernel-optimizer/references/tirx_workflow.md).
Do not turn unavailable profiler evidence into an inferred measured fact.

`feedback_cases.py` supplies complete threadwise, tiled and persistent kernels,
including a 1024-CTA persistent variant. `feedback_study.py` compiles before
allocation, takes the existing UUID lock, verifies live idle/device mapping,
checks three seeds per shape and uses randomized official event-timer pairs.
It requires authorized idle Linux GPU hardware and an outer timeout. These
mechanism examples and candidate views demonstrate tools; they are not a full
model-generated optimization A/B.

Exit 0 means the requested concrete checks passed; 1 means a checker or numeric
finding; 2 means execution/coverage/configuration error. Unknown checker verdicts
remain errors. Numerical simulation is skipped after checker findings/errors.
Results contain case-source SHA256, installed versions, checker details,
tolerances, errors and elapsed CPU time; sibling stdout/stderr logs capture native
tool diagnostics. This is ordinary evidence, not a new approval certificate.
The `simulation` check retains the NumSim verdict and structured diagnostics.
Only `clean` passes; a `review` or unknown verdict is ERROR, not a candidate
rejection. The separate `numerical` check may still pass, showing that values
matched while simulator coverage needs review.
Only the case file itself is hashed; record imported helper source as additional
evidence when applicable. Run one writer per output/cache directory.

## Connect feedback to discovery and delivery

After source/consumer review of a Scout lead, choose the cheapest useful check.
Existing Python/C++ tests, Triton/CUDA kernels and direct GPU validation remain
first-class routes. TIRx simulation is useful for a supported synchronization or
numerical question, not a mandatory conversion of every kernel.

```sh
python scripts/kernel_opt.py tirx summarize \
  --result runs/tirx-example/cpu.json --run runs/my-optimization
```

This offline command never imports the case or compiler and never calls a model.
It prints at most six case briefs, prioritizes non-passing cases, retains finding
and simulator-coverage excerpts, exact integer errors, reported compiler resources,
the raw result SHA and a local source identity check. Omitted details are counted;
read the raw result before interpreting a finding. Missing local source remains
unavailable, not verified. A saved PASS is a reported observation, not a new
correctness certificate. Foreign/performance result scopes are rejected.

Without `--run` it is read-only. With it, an existing worklog receives one
`correctness` or `inspection` entry per explicit invocation; it does not set
ACCEPT/REJECT, mutate the Scout queue, grant GPU access or mark a PR Ready.
Exit 0 for `summarize` means the saved result was processed, not that its checks
passed; use `declared_status` and inspect the evidence. Malformed inputs exit 2.
Do not repeat the invocation merely to poll status. The notebook references raw
evidence rather than making a second result store. Inspection records stay
distinct from numerical correctness and performance.

Give the brief to the local optimization agent as untrusted observations, not
instructions. Preserve the real source/consumer contract, then use a concrete
finding to choose an edit and rerun the same test. Device checks and representative
matched timing still decide a performance contribution. Fixes to the compiler,
checker or diagnostics can instead be useful correctness/reporting PRs, without
claiming a kernel speedup. Deduplicate reusable lessons under `knowledge/README.md`.
No public feed automatically reads private experiment files or executes a lead.

The child has GPU visibility disabled and a bounded timeout (default 300 seconds).
Timeout/interruption kills this worker's process tree and replaces stale results
with ERROR. This is trusted-code execution, not a security sandbox. CPU caches
are scoped beside the output by default or supplied with `--cache-dir`.

## Measurement and recurring validation

Choose a candidate per workload, dtype and GPU rather than replacing all existing
backends. TIRx optimized data-center Blackwell kernels need their actual
instruction support; RTX 5090 cannot be assumed compatible from its family name.
Keep performance decisions separate from the CPU status. Float-tolerant GEMM
tests must not fabricate bitwise parity for the historical `paired-compare`
command. Record the actual tolerance and raw randomized pairs, then analyze those
measurements with a method suited to that numerical contract.

Repeat testing when source, dependencies, hardware or the candidate changes.
Expand to held-out shapes and real project tasks; unchanged examples need not
consume GPU on every recurring check. A system-level evaluation must hold model,
task, GPU and budget constant, and track time to correct output, final performance,
GPU time and tokens. Adapter fixtures alone cannot establish agent productivity.

KCoral is a possible execution transport. Before deploying it for shared workers,
verify the full dependency stack, allocation coordination, profiler access and
code isolation. The initial B300 trusted-script loopback test did not establish
those properties.
