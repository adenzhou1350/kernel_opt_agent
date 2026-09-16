---
name: kernel-optimizer
description: Optimize GPU kernels and framework execution paths for a concrete workload, validate correctness and performance, and prepare focused upstream changes. Use deeper resource modeling when a performance-limit claim requires it.
metadata:
  short-description: Practical kernel optimization with reusable evidence
---

# Kernel optimizer

Read the repository's `AGENTS.md`. Default to a focused implementation and
validation loop. Ordinary optimization does not require a formal phase machine,
multiple agent roles or a performance-limit certificate.

Resolve computation semantics, representative workload, target hardware and
numerical tolerance from the task and available evidence. Keep unknowns explicit.
Search a few relevant lessons with `scripts/kernel_opt.py knowledge search`;
check the conditions and underlying sources before applying them.

Establish a runnable correct baseline and confirm the affected production path.
Estimate whether removing the suspected cost could matter to the whole workload.
Then make the smallest useful change and run the cheapest test that can reject
it. Expand profiling, modeling or the candidate search only when the result
would change the next decision.

Match baseline and candidate source, inputs, execution mode, runtime and device.
Use the target's numerical contract; bitwise equality is not universally required.
Distinguish kernel time, GPU activity and end-to-end latency. Qualify performance
with representative repeated comparisons, including relevant regression cases.
Treat environment failures as environment problems rather than evidence against
the optimization. Keep repairs bounded by their likely value.

Use `worklog init|record|status` for lightweight experiment notes, or reuse the
task's existing record. Write reproduction commands and evidence once; let tools
compute identities. A passing bookkeeping check is not a correctness result.

Prepare a small PR according to the target repository's requirements. State the
tested scope and pending checks. When a direction fails, record the counterexample
and a concrete reopening condition. Extract a reusable lesson only if it improves
a future decision; follow `knowledge/README.md` and deduplicate existing entries.

On shared hardware, use compatible idle devices under the existing authority,
isolate environments and caches, coordinate active allocation, and clean up only
your own processes. No legacy queue or lease is required. Keep ordinary progress
in the task record; avoid cross-task acknowledgements and repeated status messages.

For explicit hardware bounds, final-instruction attribution or certification,
read [limit_research.md](references/limit_research.md). Load further references
only when that mode or a concrete technical question needs them.
