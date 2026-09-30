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
Long native race/synchronization messages can hide their source spans after
truncation. The brief separately retains bounded operation sites (at most two
per finding) and directional ordering/effect fields for the three retained
findings. These come from the report, not a new source inspection; unknown
report shapes remain partial. Use the raw report and exact source to interpret
them, rather than treating an omitted location as evidence of no finding.

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

## Scout feedback, without requiring a new compiler

The [TIRx Harness article](https://zhuanlan.zhihu.com/p/2088605062314643836)
motivates actionable compiler diagnostics, reusable implementations rather than
generic advice, and separating generation from device measurements. Scout keeps
native project tests first; an existing TIRx case can opt into compiler feedback.
Do not translate unrelated Python/TypeScript/CUDA leads solely to use TIRx.

The delivery worker's existing one-repair call now receives per-arm exit/count/
cleanup observations and bounded failure excerpts, not entire duplicated logs.
The owner handoff includes the same brief plus its existing raw evidence link.
Omission counts and hashes preserve the distinction between a partial diagnostic
and complete evidence. Missing context, import errors and simulator gaps are not
candidate defects; no new queue gate or automatic GPU execution is introduced.

For an already reviewed TIRx case, create a tool-free model context:

```sh
python scripts/scout_validation_feedback.py \
  --tirx-result runs/example/cpu.json --case-file examples/my_cases.py
```

This reads saved observations and source without importing either. It rejects a
source hash mismatch, preserves failure/resource excerpts and explicitly forbids
changing independent references or treating feedback as execution authority.
Review any model edit before running the existing check/device route. Retain the
source, reference and reproducible commands, not just the model's explanation.

September 30 pilot: one tool-free Kimi call consumed a saved native int64 failure
and proposed removing the planted `+1`; 1,220 reported tokens, 6.87 s model wall.
Reference/control ASTs were unchanged. B300 SSH timed out, so the edited case was
**not rerun**. This is a handoff demonstration, not a new bug, repair correctness
certificate, productivity comparison or performance improvement. A four-job
delivery trial hit four static environment/context blocks before any model/test
execution; richer feedback does not solve missing package/test environments.

Before repairing an environment, an explicit owner source audit can also disprove
an alleged bug. Delivery's `--reject-owner-job`, `--reject-reason` and
`--reject-evidence-url` accept a terminal environment/context/GPU-review lead and
retain its prior state and reason. The evidence URL must pin a commit in the same
repository; running, pending and published candidates cannot be overridden.
This is an owner judgment, never an automatic inference from a failed import.
One SGLang QSA lead was resolved this way: valid speculative capture already
makes metadata row count equal captured token capacity. Do not create artificial
metadata to manufacture the mismatch before tracing its producer.

An exploratory OpenClaw case tested native Node 24.16 stream consumption, not a
copied implementation. Original pipes violated pause-only and resume-then-pause;
the owner's repair passed six consumer/backpressure modes and nine transport/
size controls through the real Linux host/worker IPC, including an exact
`870c5b6` source replay. The older `c83486b` registered handoff suite, extended
with two fixed regressions, gave 10 pass / 2 fail on control and 12 pass on repair
(2.42 s in-file). These runs used explicit source overlays and cached external
dependencies; they are not whole-application or performance qualifications.

An October 1 follow-up closed the current registered-test environment gap on a
task-private Linux worker. Exact `870c5b6` source with the same added regression
bytes, Node 24.16.0, pinned pnpm 12.5.1 and the frozen-lockfile Vitest 5.0.1 install
ran the owning `unit-fast` lane through `scripts/run-vitest.mjs`. The original
pipe implementation gave 10 passed / 2 failed; the repair gave 12 passed, including
both pause variants, async consumption and the early-byte/EOF controls. This
is a native regression discriminator, not a claim about performance, the entire
application or model-generated repair quality. Dependency preparation belongs
outside the source-selection loop; independent publication review remains
separate. Preserve failed bootstrap attempts as tooling failures, not product
failures. The private raw logs are under
`runs/kimi-scout-20260920/openclaw-native-szd-20261001/`.

Two tool-free Kimi calls used 5,877 / 8,769 reported tokens and 10.82 / 29.52 s.
The second received concrete failed-control diagnostics but not the owner's
winning implementation. Both proposed repairs still failed resume-then-pause;
richer feedback did **not** establish better repair success or PR conversion.
Its bounded registered replay produced no result and remains inconclusive.
This single exploratory case is not a budget-matched productivity comparison.

An October 1 next-evidence check fed two fresh Scout hypotheses their missing
caller/consumer source, without providing a repair or claiming tool execution.
Kimi changed both to `no_lead`: FlashInfer's outer wrapper already binds positional
arguments and defaults; the shown SGLang raw-verify constructor leaves the alleged
aliased field `None`, and its consumer constructs derived tensors. The calls used
4,236 and 3,140 reported tokens. A separate pinned, unmodified FlashInfer decorator
AST check passed six scalar binding/rejection cases; it is not a CUDA test.
Original hypotheses remain in the queue history, linked to these follow-ups.
These owner-selected development cases support evidence-first triage, not a
prospective success-rate, total-cost or PR-conversion claim. The next comparison
must select held-out leads before observing their outcomes and charge retrieval,
environment preparation and failed attempts to both arms.

The first prospective feasibility draw selected six production Python paths from
two previously unconfigured repositories (TorchTitan and llm-compressor), using
tree metadata before source or model outcomes were read. One initial call returned
`no_lead`; five failed with an unclassified controller-side `OSError` in under a
second. Only 2,443 actual tokens were observed; the other five usages are unknown,
not zero and not their admission reservations. No paired routing arms ran, so
the pilot is inconclusive and establishes no cost or quality improvement. Those
cases were not redrawn or retried to improve the result. Six parallel no-model
launch probes later succeeded; contemporaneous memory/connection checks did not
identify the historical failure's cause. New receipts retain numeric `errno`/
`winerror` and operation phase without exception messages or private paths.

Reusable controls from the case:

- Keep native runner failure names (unittest, TAP, Vitest and Rust), and test
  observable consumer progress, buffered bytes and EOF, not only state flags.
  See [the applicable stream lesson](../knowledge/lessons/native-events-versus-consumer-progress.json).
- Check executed inventory: an explicit zero-test success is inconclusive;
  absent counts remain unknown. Resolve the owning test lane before retrying.
- Bind source-overlay contents in transform caches and isolate arm caches.
  A stale cache or a loader's incorrect internal-import resolution is a tooling
  fault, not a reason to weaken product assertions. Preserve failed evidence.

Scout's automatic CPU repair now keeps already executed test bytes unchanged.
A repair may revise source or request context, but changing those tests requires
owner review instead of another automatic execution. A malformed proposal that
never executed may still correct its tests on the one existing repair attempt.
This keeps before/after evidence interpretable without imposing TIRx or another
compiler on native project work.

Another October 1 owner-selected SGLang lead alleged that packed KDA decode could
read a missing `lower_bound` attribute. Its actual layer constructor assigns the
attribute unconditionally; fabricating an incomplete layer would not prove the
claim. Scout's source locator now anchors an unambiguous Python `Class.method`
within its owning class and prefers the last direct definition when duplicated.
It parses source without executing it and keeps the existing window/cache budget.
This retrieval correction is not a measured productivity or PR-conversion gain.
The follow-up actually returned `no_lead` after reading this constructor (4,123
reported tokens); it remains an owner-selected counterexample, not a held-out
comparison or proof that arbitrary source follow-ups improve triage.

Replaying the saved registered OpenClaw failure also exposed a real feedback
transport defect: ANSI-colored assertion labels produced **zero** excerpts in
the previous compactor. The revised compactor strips presentation codes for
selection, prioritizes terminal causes and bounded assertion diffs/sites, and
keeps the raw-output digest unchanged. The same log now retains the two failing
test names, `expected false to be true`, expected/received values and the native
assertion location within the existing 12-line budget. Focused regressions cover
colored logs and repetitive failure labels. This repairs observation delivery;
it does not establish that a model repairs the program better. No new model or
GPU execution is implied by replaying a saved log.

An actual follow-up used the repaired compactor, the original pipe source and
unchanged registered tests in one tool-free Kimi call (4,004 reported tokens,
6.50 s). Its one-line proposal guarded the historical resume with `isPaused()`.
On the same task-private Node 24.16.0 / Vitest 5.0.1 owning runner, both control
and proposal gave 10 passed / 2 failed; each full command took about 30 s,
including transformation. Tests were unchanged and the task's prior source was
restored afterward. This owner-selected development replay is not a held-out or
budget-matched comparison, and the proposal is not a contribution. Correctly
delivering a failure did not resolve the unexamined native listener-transition
mechanism. Retain this negative result, use relevant dependency/caller context
when it can change the repair, and do not add blind attempts merely to obtain a
passing verdict. Raw evidence stays in the existing local run, not the public
knowledge library; no GPU, service or shared dependency changes were made.

Scout also retrieves at most one intact related card from the small curated
lesson library for discovery and repair contexts, alongside its existing core
lessons where present. Queries use the current question/path/hypothesis, not the
entire source or historical job archive. The scope, counterconditions, status
and public evidence stay with the card; lexical matches do not establish
applicability. Oversized cards are omitted instead of truncating their caveats,
and optional advice is dropped before it can displace primary source under the
existing input cap. Card updates alone do not enqueue unchanged source again.
The lookup has no growing cache, network fetch or automatic knowledge promotion.
This repairs a real integration gap (previously only three fixed cards were
included); it is not yet a measured PR-conversion or total-cost improvement.

A live, owner-selected existing FlashInfer lead exercised the retrieved
consumer-contract card in one tool-free call (6,536 reported tokens, 5.92 s).
The model requested omitted context instead of claiming qualification. Reading
the same pinned function's omitted branch then falsified its missing-variable
suspicion; the original alleged cache layout was also outside the documented
layout. This is a wiring smoke and source-level falsification, not a paired
quality/cost comparison. A relevant lesson cannot replace the missing code,
and neither allegation warrants GPU testing without a supported caller.
