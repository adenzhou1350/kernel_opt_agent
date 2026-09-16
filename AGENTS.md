# Kernel optimization workspace

Help a fresh capable model understand hardware and reach correct, efficient
operator implementations with less repeated work, GPU time and context cost.
Keep evidence reusable and key decisions explainable. Use the model's judgment
for analysis and implementation; use scripts for repeatable execution and
measurement. These instructions supersede older mandatory workflow text in
research references and historical community records for ordinary delivery work.

The activities below are adaptable guidance, not a required sequence or a method
whitelist. Choose, reorder or omit tools and research steps according to expected
information value, reuse potential and the task's budget. Existing experience is
a falsifiable prior; revise or reject it when conditions or evidence disagree.
Keep numerical correctness, honest claims, user authority and shared-resource
safety intact. Near-optimality is a conditional claim to justify, not an admission
gate. Do not require a reasoning transcript; record the decisive hypothesis,
reproduction, result and reason for changing direction once.

## Ordinary optimization work (default)

- Resolve the computation, representative workload, target hardware and numerical
  requirements from the task and existing evidence. Ask only for a missing choice
  that materially changes the work. Record unknowns; cheap investigation can proceed.
- Reuse relevant evidence when it can save work. The lightweight entry point is
  `python scripts/kernel_opt.py knowledge search "<problem>"`; equivalent existing
  evidence is fine. Check applicability before transfer, not just the architecture
  name. Search results are suggestions, not rankings of scientific merit.
- For unfamiliar hardware, `hardware/PROFILING.md` offers a first-layer handoff;
  an equivalent existing profile is fine. Carry queried facts and unknowns forward.
  Investigate gaps that can change a current or reusable future decision.
  Inventory is not calibration or proof of an operator optimum.
- Establish a runnable baseline and confirm the affected path is reached. Estimate
  the possible whole-workload benefit before expensive implementation or tuning.
  Choose the cheapest useful experiment; no fixed candidate count or universal
  percentage threshold is required.
- Choose candidate breadth and implementation scope by expected value; keep each
  comparison interpretable. Run relevant correctness/regression checks and compare
  matched baseline/candidate workloads. Use interleaved or randomized
  repeats when order, clocks, caches or competing load could confound the result.
  Preserve numerical semantics unless the task explicitly permits a relaxation.
- Keep source, workload, hardware, reproduction commands, results and evidence
  in the task's existing record or a lightweight `worklog init|record|status`
  notebook. Record once, not in duplicate formats or for every routine tool call.
  Bookkeeping is not a phase gate; existing notes need no migration.
- End a candidate with a reviewable change or an evidence-backed stop/inconclusive
  decision. Record the reason and what would justify reopening it. Repeated
  environment repair should trigger a change of approach, not more planning files.
- Follow the target repository's contribution rules. Draft and Ready decisions
  depend on the actual change, applicable tests and the claims in the PR. A kernel
  timing is not whole-model performance. Do not claim human review or signoff that
  the human has not provided. Treat maintainer CI/review waits as delivery states.

The default loop does not require `new-run`, `advance`, a supervisor document,
resource-model closure, a SASS audit or a limit certificate. Reuse specialist tools
when they answer a concrete question. Do not generate a new schema, validator or
receipt family merely to describe ordinary progress.

## Shared machines and independent work

Use existing user authorization. Before using a shared GPU, check its live UUID,
processes and load; choose compatible idle devices, isolate source/environment/
caches, and verify the selected device mapping. Coordinate active use through one
allocator or the site's existing scheduler to prevent simultaneous assignment.
Historical broker queues and leases are not prerequisites for new work. Never
preempt, reset or stop another task or alter its environment. Track your child
processes and release only your own resources after completion.

Each task owns its work. Parallel helpers are useful for independent bounded
implementation or review; do not require a standing scheduler/analyst/supervisor
cast. Persist routine progress locally. The portfolio owner pulls results; send
messages only for a real shared-resource conflict, invalidated active execution,
or a decision that cannot be resolved under existing authority. Waiting alone is
not a reason to keep creating artifacts or running periodic analysis.

## Knowledge that survives a run

Use `knowledge/README.md` for the contribution format. Keep a lesson only when it
changes a future decision: a non-obvious precondition, reusable implementation,
matched counterexample, or a reproducible environment fix. Include applicability,
exceptions and public evidence. Search for duplicates before adding; improve the
existing entry when the lesson is the same. Label hypotheses honestly. Reading or
validating a card does not establish a measured performance claim.

Commit reusable code, focused tests and reviewed knowledge. Keep raw runs, model
weights, profiles, worker addresses, credentials and private logs local. Publish
small sanitized reproductions or stable public evidence links when useful.
Repository-maintenance PRs are separate from community optimization results.

## Optional performance-limit research

Use `hardware/PROFILING.md` for lightweight conditional resource-gap analysis.
Use `skill/kernel-optimizer/references/limit_research.md` when the deliverable
needs that formal protocol or you deliberately choose it for the task. Its
existing strict requirements do not block ordinary analysis or a useful PR.

## Repository changes

Preserve unrelated working-tree edits and historical experiment evidence. Keep
the default interface small and standard-library-only. Test changed behavior and
the affected existing tools; do not expand testing merely to increase test counts.
