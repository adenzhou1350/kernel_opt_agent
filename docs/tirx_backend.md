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
