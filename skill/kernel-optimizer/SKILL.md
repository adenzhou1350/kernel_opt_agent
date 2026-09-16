---
name: kernel-optimizer
description: Optimize GPU kernels and framework execution paths for a concrete workload, validate correctness and performance, and prepare focused upstream changes. Use deeper resource modeling when a performance-limit claim requires it.
metadata:
  short-description: Practical kernel optimization with reusable evidence
---

# Kernel optimizer

Read the repository's `AGENTS.md`. Use accumulated evidence and tools to reduce
the cost of hardware understanding and correct optimization. Choose your own
algorithms, search breadth and experiment order; the activities below are guidance,
not a fixed recipe. Ordinary work needs no formal phase machine, multiple agent
roles or performance-limit certificate. Keep decisive results reproducible without
writing a transcript of every thought or tool call.

Resolve computation semantics, representative workload, target hardware and
numerical tolerance from the task and available evidence. Keep unknowns explicit.
Reuse relevant lessons with `scripts/kernel_opt.py knowledge search` or existing
evidence when useful. Check conditions and sources; revise or reject prior advice
when new evidence disagrees. For a new device, `hardware/PROFILING.md` supplies a
first-layer briefing; do not repeat a valid inventory just to follow a template.

Establish a runnable correct baseline and confirm the affected production path.
Estimate whether removing the suspected cost could matter to the whole workload.
Choose implementation scope and informative tests by expected benefit and cost.
Expand profiling, modeling or search when it can improve current decisions or
create reusable evidence; stay within the task's scope and budget.

Match baseline and candidate source, inputs, execution mode, runtime and device.
Use the target's numerical contract; bitwise equality is not universally required.
Distinguish kernel time, GPU activity and end-to-end latency. Qualify performance
with representative repeated comparisons, including relevant regression cases.
Treat environment failures as environment problems rather than evidence against
the optimization. Keep repairs bounded by their likely value.

Use `worklog init|record|status` for lightweight experiment notes, or reuse the
task's existing record. Write reproduction commands and evidence once; let tools
compute identities. A passing bookkeeping check is not a correctness result.

Deliver the requested result; when contributing code, prepare a focused PR under
the target repository's requirements. State tested scope and pending checks.
When a direction fails, record the counterexample and a concrete reopening
condition. Extract a reusable lesson only if it improves
a future decision; follow `knowledge/README.md` and deduplicate existing entries.

On shared hardware, use compatible idle devices under the existing authority,
isolate environments and caches, coordinate active allocation, and clean up only
your own processes. No legacy queue or lease is required. Keep ordinary progress
in the task record; avoid cross-task acknowledgements and repeated status messages.

Use `hardware/PROFILING.md` for conditional resource-gap analysis. Read
[limit_research.md](references/limit_research.md) when the deliverable needs that
formal protocol or you deliberately choose it for the task. Load other references
only for a concrete question; approaching an optimum is not a mandatory gate.
