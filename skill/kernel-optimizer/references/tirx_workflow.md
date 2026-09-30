# TIRx feedback in ordinary optimization

Keep the existing workload contract, task discovery, knowledge and delivery.
Use TIRx tools for the question at hand; a full tool battery is not mandatory.
Runnable examples and the trusted-case interface are in
`docs/tirx_backend.md` and `examples/tirx/` at the repository root.

| Question | Useful evidence/action |
| --- | --- |
| Incorrect values, tail handling, synchronization or cross-thread memory | `kernel_opt.py tirx check`; for GPU-only behavior use actual output tests and Compute Sanitizer on an allocated device |
| Did code generation introduce spills, scalarize a load, or emit the expected instruction? | `kernel_opt.py tirx inspect --arch <explicit compatible SM>`; inspect generated CUDA, PTX, SASS and raw ptxas log |
| Occupancy, traffic, cache behavior or execution stalls | Stable benchmark first, then available NCU counters; replay timing is diagnostic, not the performance score |
| Pipeline overlap, dependency critical path, load imbalance | Available IKET timeline or independent targeted experiment; label missing profiler evidence honestly |
| Which syntax or implementation pattern is valid? | Installed TIRx API and complete canonical kernels at the matching revision; use upstream wiki/manual for the relevant instruction |

Do not invent counters or timelines if a profiler is unavailable. In the current
private B300 environment event timing works; Proton/CUPTI failed and NCU/IKET
have not been qualified. Use explicit compiler architecture and CPU compilation
before shared GPU allocation when useful. Same-worker/cache reuse is optional:
our small warm tests do not establish a stable universal speedup. New NumSim
candidate materialization can dominate a short task.

Tie each next edit to a falsifiable finding: excessive CTA count, observed
spills, redundant memory traffic, uncovered synchronization, or a measured
shape-specific regression. Change one interpretable mechanism, rerun the same
correctness contract and matched benchmark, and keep source/command/results in
the existing worklog. Generated-code inspection does not prove GPU behavior;
passing CPU simulation does not replace device checks.

Preserve different optimization mechanisms as active alternatives rather than
keeping only the fastest parameter variant. Record a tested candidate with an
explicit ACCEPT decision, its family, measured latency and evidence:

```sh
python scripts/kernel_opt.py worklog record --run runs/<task> \
  --kind decision --status ACCEPT --summary "Exact device outputs passed; measured tile route" \
  --candidate <complete-candidate.py> --family tiled --latency-us <measured> \
  --evidence <correctness-and-timing.json> \
  --workload "<math/dtype/shapes/tolerance/benchmark settings>" \
  --hardware "<device/runtime/clock/cache/concurrency>"
python scripts/kernel_opt.py worklog frontier --run runs/<task>
```

The view retains the fastest declared passing representative per family and
separates comparison contexts. Changed/unavailable source or result files are
excluded. This is a view of explicit judgments and file identities, not a proof
that arbitrary evidence establishes correctness. A later REJECT/INCONCLUSIVE
decision for the same candidate and context withdraws it. Keep imported helper
identities in the evidence as needed. Prefer complete implementations with
held-out shapes/seeds over snippets or a timing-only lesson.

Upstream contributions should follow real findings. Reproduce with the installed
version and current upstream source, preserve a small positive/negative control,
fix narrowly, and validate on the target hardware before proposing a PR. Do not
present environment-only repairs or speculative tuning as an upstream defect.
