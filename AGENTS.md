# Kernel optimization repository instructions

These instructions apply to every agent working inside this repository.

## Mandatory intake gate

Every optimization task still requires three frozen inputs:

1. Operator computation: equations or pseudocode, inputs/outputs/state,
   shapes/strides/dtypes, numerical contract, aliasing and legal rewrites.
2. Target workload: shape set, occurrence weights, execution modes, upstream
   and downstream layouts, concurrency, graph mode and latency objective.
3. Target hardware: exact device or permission to auto-discover it, software
   stack, power/clock policy, allowed programming models and architecture-
   specific features.

Resolve these inputs from the active Goal, current run, repository state and
live resource inventory before asking the user.  Do not ask again for a field
that is already hash-bound by the active run or by a still-valid user decision.
Historical measurements are evidence, not permission to reuse an input.  A
standing user authorization to auto-discover a named resource class permits
the control plane to freeze a newly attested idle device from that class
without another generic confirmation; it does not permit preemption, service
interruption or a different workload.  Ask only when a missing choice would
change semantics, target workload, costly execution scope or an external
mutation.  Read-only inspection, candidate discovery, normal source edits and
focused CPU tests may continue while an expensive execution input is missing.

Once the three inputs are complete and the requested optimization scope is
authorized, create the run and begin baseline/model construction immediately.
Do not pause merely to ask the user what to do next.  Ask again only when a
mathematical choice, correctness relaxation, expensive experiment or external
mutation requires new authority.

## Autonomous lanes and pull-based control

An execution lane owns one persistent optimization Goal and keeps progressing
inside that scope.  A blocked GPU, environment, reviewer or credential gate
does not stop cheap source analysis, focused correctness work, candidate
ranking or Draft preparation.  Do not create timers or periodic chat prompts
to keep a lane alive; continue from the Goal until a real terminal condition.

The portfolio controller is the only cross-lane coordinator, shared-policy
writer and resource allocator.  It pulls task state and immutable artifacts;
lanes must not routinely message the controller or one another.  Emit a
control-plane event only when at least one of these materially changes:

- the selected candidate or its accept/reject decision;
- Draft/Ready/merged state or a maintainer/CI response needing action;
- the terminal result of an approved expensive build, GPU or service window;
- a new correctness, security or provenance defect that invalidates evidence;
- a user-owned decision that cannot be resolved from standing authority.

Do not relay acknowledgements, unchanged status, successive hash lists or
ordinary bounded-cycle narration.  Persist those details in the run and keep
working.  A material event should state the changed decision, the smallest
authoritative evidence identity and the next action; the controller decides
whether another lane needs the information.

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
After confirming that the production path is reachable and before expanding
environment, accelerator or whole-workload qualification, run
`scripts/kernel_opt.py candidate-value`.  An unknown whole-workload ceiling
must stay explicit and be quantified next; never replace it with zero or a
favorable guess.  Stop candidates below the materiality floor, open an honest
Draft once its minimum evidence is complete, and reserve expensive
qualification for candidates whose possible value justifies their permanent
review and maintenance surface.
End each bounded cycle with one of: a code/test/PR-state change, a measured
decision, or an explicit rejection.  Do not create another schema, receipt or
validator merely to restate an already-enforced boundary; add one only after a
reproduced gap could authorize an incorrect external or irreversible action.

For every selected framework candidate, start a `PROSPECTIVE_EXACT` community
timing ledger and record `FIRST_CANDIDATE_PROPOSED` before the first production
source edit. Bind the selection decision as milestone evidence. When GitHub
opens the Draft, marks it Ready or merges it, use `community-timing
record-pr-stage` with the observed event time, PR URL and an immutable event
receipt. Never reconstruct these timestamps later from memory or filesystem
mtimes. If the ledger did not exist before implementation, classify that cycle
as `LEGACY_MILESTONE_BOUNDS`; do not backfill it into delivery-speed metrics.
Agent-repository maintenance PRs are never entered in a framework lane ledger.
For bounded environment or governance commands, use `community-timing run-phase`
instead of separate start/end writes so success, non-zero exit, timeout, and
launch failure all close the phase with an immutable command receipt. The
receipt measures command wall time and exit status; it is not correctness or
performance evidence.
If a governed worker executes the command and returns an immutable receipt, use
`community-timing import-phase-receipt` against a ledger that existed before the
worker run. Bind the receipt's explicit start/end fields and reconcile its
duration field when available; never infer these times from file mtimes or
retrofit them into a legacy cycle.

Every selected framework candidate must also maintain one current
`upstream-review-state-v1` record.  Update it when the minimal Draft evidence,
GitHub Draft state, Ready gates, CI classification or reviewer state changes.
The control plane must hash-bind those records in an
`upstream-delivery-inbox-v1` manifest and run `upstream-delivery-inbox`; do not
reconstruct delivery readiness from chat summaries or arbitrary experiment
receipts.  An `OPEN_DRAFT`, `MARK_READY_AND_REQUEST_REVIEW` or
`RESPOND_TO_REVIEW` inbox item is a delivery action, not another research
prompt.  Agent-repository maintenance stays in a separate inbox and never
counts as a framework optimization success.
For live queues containing an open Ready PR, use
`upstream-delivery-inbox-v2` and hash-bind its prospective reviewer-handoff
clock. This prevents a normal reviewer wait from hiding a due bounded
follow-up. The inbox only routes the action; it never authorizes a message.
For pending candidates, consume the inbox's Draft-minimum and Ready-gate
progress rather than treating equal action labels as equal priority. Within
one action class, prefer the candidate with more completed immutable gates;
do not keep several same-lane candidates active merely because all say
`COMPLETE_DRAFT_MINIMUM`.

Normal local source edits, CPU-only builds and focused tests are implementation
work and do not require repeated user authorization.  Expensive compilation,
GPU execution, service interruption, credential use and external publication
retain their explicit authority boundaries.  For model materialization, prefer
an accessible ModelScope snapshot when it can be content-hash matched to the
required model identity; a hosting platform name is never a substitute for
file identities.

After an environment or toolchain failure, run `qualification-environment`
before downloading or rebuilding another closure. Reuse only the layers it
marks compatible: dependency/toolchain state, source binding and a source-bound
native extension are separate identities. A reuse decision is advisory and
never authorizes a build, test, GPU run or result claim.

An environment repair is a bounded implementation activity, not a reason to
mint an unlimited sequence of plans.  Route every terminal attempt through
`qualification-route` before creating a successor.  Create a new version only
when an executable byte, bound identity or reviewed scope changes; a wording,
timestamp or filename correction alone must not become another attempt.  Keep
one current plan and mark all predecessors terminal.  When the frozen repair
budget is exhausted, stop that environment route and continue a different
cheap candidate or Draft/review task until the controller explicitly opens a
new scope and budget.  Prefer the shared approval, worker attestation and
single-use dispatcher receipts over run-specific controller scripts or new
schemas that restate the same boundary.

Execute an approved CPU-only preparation only through
`qualification-environment-dispatch`. The approval must bind the exact
dispatcher, contain one sealed argv and be atomically consumed once. A failed,
timed-out or ambiguous claim is terminal and must not be retried in place.
The dispatcher receipt is process evidence only; accept the environment only
from the separately validated materializer terminal receipt.

Before a cache-bound model download, JIT compile or native build, bind every
framework/compiler cache root explicitly and run `environment-cache-preflight`.
Require the intended environment-variable mapping, a writable directory and a
workload-sized free-space floor. A blocked preflight is an environment result,
not a candidate failure; move to a reviewed cache root or stop the bounded
repair instead of retrying against an implicit home-directory default.

On a CPU-only preprovisioned worker, `CUDA_VISIBLE_DEVICES=-1` can make
`torch.cuda.get_arch_list()` return an empty list even when the installed Torch
binary contains the required architecture. Reuse the worker attestation logic:
fall back to `torch._C._cuda_getArchFlags()` and hash-bind the Torch binary and
build configuration. Do not relax or skip the architecture check, and do not
make CUDA visible merely to query compiled targets.

Treat the GPU process list in a worker attestation as a time-stamped
observation, not a permanent empty-worker promise. Immediately around each
CPU-only preparation step, capture the same `nvidia-smi` process fields and
use `validate_cpu_only_process_transition`: pre-existing protected workloads
may remain, but the normalized GPU UUID/PID/process-name set must be unchanged
afterward. Do not compare live process rows to the historical attestation or
fail on memory-accounting drift alone, and never stop a protected process to
make the old snapshot match.

Before dependency installation or the first framework import on a managed
worker, call `cpu_only_cache_environment` with the exact closure root and bind
the returned environment. Framework imports can write caches even with CUDA
hidden; XDG, Hugging Face, Torch, TorchInductor, Triton, CUDA, SGLang,
FlashInfer and temporary paths must stay inside the writable closure. Do not
fall back to `/root`, `$HOME` or another image-owned filesystem, and do not
repair a full image filesystem by deleting unrelated caches.

Execute an approved CPU-only preparation only through
`qualification-environment-dispatch`. The approval must bind the exact
dispatcher, contain one sealed argv and be atomically consumed once. A failed,
timed-out or ambiguous claim is terminal and must not be retried in place.
The dispatcher receipt is process evidence only; accept the environment only
from the separately validated materializer terminal receipt.

Before a cache-bound model download, JIT compile or native build, bind every
framework/compiler cache root explicitly and run `environment-cache-preflight`.
Require the intended environment-variable mapping, a writable directory and a
workload-sized free-space floor. A blocked preflight is an environment result,
not a candidate failure; move to a reviewed cache root or stop the bounded
repair instead of retrying against an implicit home-directory default.

When a shared qualification resource broker is available, submit the sealed
validation job and continue bounded discovery or review work instead of waiting
on a GPU. Do not SSH to a pooled worker or reserve cards independently. A broker
lease is only a resource reservation; the lane's normal authorization and
atomic dispatcher must still validate before launch. Treat a stale lease as
possibly running until the worker reconciles it, and route its immutable
terminal result only to the originating task recorded in the job.

Before submitting or acquiring a GPU job that depends on a profiler, compiler,
disassembler or runtime utility, collect a fresh worker attestation and run
`qualification-worker-toolchain` against the exact execution plan. Bind every
required executable by name and the plan bytes as the consumer. A stale
attestation or missing tool is a pre-lease environment blocker; do not reserve
GPUs merely to discover it in the worker process. A passing result is tool
availability evidence only and does not authorize the lease or execution.

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
