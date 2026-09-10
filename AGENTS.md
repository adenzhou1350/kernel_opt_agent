# Kernel optimization repository instructions

These instructions apply to every agent working inside this repository.

## Mandatory intake gate

At the start of every new optimization task, show the user a concise reminder
that three inputs are required and ask for any missing fields:

1. Operator computation: equations or pseudocode, inputs/outputs/state,
   shapes/strides/dtypes, numerical contract, aliasing and legal rewrites.
2. Target workload: shape set, occurrence weights, execution modes, upstream
   and downstream layouts, concurrency, graph mode and latency objective.
3. Target hardware: exact device or permission to auto-discover it, software
   stack, power/clock policy, allowed programming models and architecture-
   specific features.

Do this even when historical defaults exist.  Historical input may be reused
only after the user names a run or explicitly confirms reuse.  Read-only
inspection may continue while fields are missing, but do not compile, tune,
benchmark or change production code before the intake gate is complete.

Once the three inputs are complete and the requested optimization scope is
authorized, create the run and begin baseline/model construction immediately.
Do not pause merely to ask the user what to do next.  Ask again only when a
mathematical choice, correctness relaxation, expensive experiment or external
mutation requires new authority.

## Delivery-first operating model

The objective is a correct, reviewable upstream improvement, not the largest
possible evidence tree.  Apply evidence in proportion to the action being
taken:

- Exploration may use cheap static checks, focused CPU tests and bounded
  micro-attribution.  It must preserve unknowns, but it does not need the full
  qualification or dispatch protocol.
- A draft pull request may be prepared once a clean, minimal commit has focused
  correctness evidence, a reproduction command and an explicit claim
  boundary.  Whole-model, cross-hardware and production-workload evidence may
  remain pending and must be shown as pending.  Draft review and upstream CI are
  useful evidence sources, not rewards reserved for already-complete work.
- A non-draft or performance-qualified pull request still requires the full
  applicable correctness, production-workload, regression and provenance
  gates.  Never relax a publication claim merely to ship sooner.

Keep at most one qualification candidate and one cheap discovery candidate per
execution lane.  When a candidate is selected, prioritize a clean commit,
focused tests and a draft-ready package before expanding the search frontier.
End each bounded cycle with one of: a code/test/PR-state change, a measured
decision, or an explicit rejection.  Do not create another schema, receipt or
validator merely to restate an already-enforced boundary; add one only after a
reproduced gap could authorize an incorrect external or irreversible action.

Normal local source edits, CPU-only builds and focused tests are implementation
work and do not require repeated user authorization.  Expensive compilation,
GPU execution, service interruption, credential use and external publication
retain their explicit authority boundaries.  For model materialization, prefer
an accessible ModelScope snapshot when it can be content-hash matched to the
required model identity; a hosting platform name is never a substitute for
file identities.

## Optimization invariants

- Freeze a machine-readable operator contract, workload and hardware snapshot
  before establishing the baseline.
- Before recording any target-hardware capability, resource mapping or numeric
  specification, archive an exact vendor-official source or official target-
  device query with URL/command, version, locator and SHA-256. Search official
  sources first. If the exact architecture/device is not documented clearly,
  ask the developer for the official document location and stop hardware-model
  construction. Never infer from a neighboring architecture or product.
- Build an explicit optimization plan and target-microarchitecture resource
  graph before changing launch parameters or implementation structure.
- Generate at most 2--4 architecture-level candidates before requesting a
  microbenchmark. Compute candidate-specific objective intervals and identify
  exactly one unknown whose interval can flip the top-two ordering. `UNKNOWN`
  in a resource ledger does not itself authorize measurement.
- Separate `GLOBAL_SCHEDULER`, `MICROARCHITECTURE_ANALYST`, `EXPERIMENT_AGENT`
  and `GLOBAL_SUPERVISOR` actor identities. The supervisor alone approves
  dispatch and owns veto, budget, stop and replan authority.
- Use an atomic microbenchmark only when a measurability contract shows that
  its observable identifies the decision quantity with sufficient precision.
  Otherwise use candidate A/B, existing evidence or no measurement.
- Separate screening from qualification. Freeze configuration, sample,
  process-launch, wall-clock and revision budgets before materialization.
- Preserve the mathematical result and public ABI unless the user authorizes a
  change.  Record every authorized relaxation explicitly.
- Separate mathematical DAG edges from schedule-induced serialization.
- Maintain a mandatory-work ledger before proposing a lower bound.
- Time native GPU kernels with a method that excludes CPU enqueue gaps.  Treat
  end-to-end CPU time and GPU active time as separate metrics.
- A benchmark is comparable only when source identity, ABI, workload, launch
  geometry, clocks, competing load and measurement semantics are recorded.
- Every candidate ends in ACCEPT, REJECT or INCONCLUSIVE with raw evidence.
- Every accepted candidate with inspectable device code requires a final-binary
  PTX/SASS/resource audit.  Source syntax or PTX alone does not prove which
  machine instructions ran.
- Map mandatory work and instruction dependency chains to warp schedulers,
  issue paths, register/shared-memory resources, compute pipelines, memory
  paths, synchronization and architecture-specific engines that are relevant
  to the target.  Unknown properties stay explicit.
- Never call a theoretical peak, a calibrated service rate and an achieved
  production time the same kind of limit.
- Never turn an operator-specific measurement into a hardware fact.  Hardware
  measurements must come from standalone synthetic microbenchmarks.
- Generate the material-resource candidate set from final-binary instruction
  classes plus the official-source manifest with
  `scripts/kernel_opt.py resources-discover`.
  A hand-written resource list, unresolved mapping or missing official document
  is a planning-gate failure.
- Treat a missing or unknown framework contract as a hard failure. Production
  runs use `optimization-run-state-v4` plus `evidence-closed-v2`; only explicit
  synthetic TEST fixtures may exercise legacy validation.
- Execute only a sealed argv-form experiment contract. Raw samples, result,
  static audit and reproduction log must be created or changed by that
  execution, then hash-bound before result binding.
- Apply experimental model changes through field-level transforms whose input,
  before value, after value, units and uncertainty can be recomputed from the
  bound result. Resource balance, schedule and tradeoff frontier must all be
  reconciled before reranking.
- A proof claim requires per-case immutable silicon, resource-service and DAG
  lower bounds, a feasible-schedule upper bound, achieved confidence intervals
  and a recomputed workload-weighted gap. SASS explanation without those bounds
  may explain a residual but cannot prove a theoretical limit.

## Global scheduling and supervision authority

Every run has exactly one global scheduling/resource-modeling owner and one
independent global supervisor. In a
multi-agent workflow this is a dedicated global scheduler; in a single-agent
workflow the active agent must explicitly hold the same role.  The role is an
artifact and decision boundary, not an optional staffing convention.

Only the global scheduler may construct and rank the candidate frontier, declare a resource
model closed, accept a schedule candidate or authorize a human limit report.
Stage/kernel agents may propose hypotheses, implement candidates and return raw
evidence, but they must not optimize a local stage by silently worsening a
different resource or stage.

Only the global supervisor may approve or veto dispatch. The exact experiment,
decision contract, measurability contract, objective, frontier and tier budget
are hash-bound in `supervisor_approval.json`; an edit invalidates approval. A
technical failure enters `AWAITING_SUPERVISOR_REVIEW`; a causal rejection enters
`HALT_AND_REPLAN`. Neither state may automatically return to `PLANNED`.

The global scheduler owns `models/global_schedule_state.json`,
`models/resource_balance.json`, `models/tradeoff_frontier.json` and
`models/experiment_queue.json`.  Read
`skill/kernel-optimizer/references/global_scheduler.md` before plan
construction or delegation.  Missing ownership, resource coverage, utilization
semantics, tradeoff accounting or model-driven experiment requests is a phase-
gate failure, not a documentation omission.

Use `scripts/kernel_opt.py experiment-rank` for a reproducible candidate-
specific decision-value ranking receipt. Use `experiment-materialize`,
`experiment-approve` and `experiment-dispatch`;
`DISPATCHED` is forbidden until source,
commands, parameter matrix, controls, expected final SASS and artifact paths
are hash-bound and executable. Bind results with `experiment-bind`, then use
`experiment-apply` and `experiment-reconcile` before executing another
hypothesis. All command names in this paragraph use the public
`scripts/kernel_opt.py` entrypoint.

## Required run artifacts

Use the public `scripts/kernel_opt.py` command surface for normal operation;
direct script entrypoints are implementation modules. Use `new-run` to create
a run. Keep raw samples immutable and derive
summaries from them.  A completed run contains the frozen inputs, baseline,
optimization plan, microarchitecture model, work ledger,
  mathematical/current DAGs, global scheduling state, per-resource balance,
  compute-memory tradeoff frontier, model-driven experiment queue,
  per-candidate instruction audits, model-driven experiment requests and candidate decisions,
  environment identity, reproduction command and a limit certificate.

Every run advances only through `scripts/kernel_opt.py advance` in this order:

`PLANNING -> BASELINE -> MODELING -> EXPERIMENT -> PRODUCTION_VALIDATION ->
CERTIFICATION -> COMPLETE`.

Do not hand-edit phase state or perform work belonging to a later phase.  The
run maintains production baselines, a P0--P4 microbenchmark plan, a calibrated
SASS/resource schedule, cross-layer prediction validation and production
validation.  `NOT_APPLICABLE` requires evidence and cannot bypass P0, P1, P3 or
P4 for a performance-limit claim.

## Reusable asset boundary

- Develop new probes only under a run's `microbench_candidates/` directory.
- Automatically attempt promotion when a probe becomes
  application-independent.  Use the promotion and repository-audit scripts;
  failed checks leave the probe run-local.
- Promotion uses structured, hash-bound check results and at least two
  independent cold-start receipts. Device-calibrated status additionally
  requires a registered `EVIDENCE_CLOSED_V2` hardware measurement; historical
  or self-declared `PASS` records cannot parameterize a model.
- `microbench/` contains only promoted definitions and source.  It must never
  contain raw samples, profiles, binaries, caches, production imports or
  application-specific names and paths.
- Published benchmark packages and registered measurement bundles are
  append-only.  Create a new version instead of overwriting one.
- Run `scripts/kernel_opt.py audit` after promotion and before completing a
  run.  Directory purity is a release gate.

Read `skill/kernel-optimizer/SKILL.md` for routing.  Load only the reference
needed for the current phase.
