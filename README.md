# Kernel Optimization Agent

For a human review of the framework boundary, execution flow, directory
ownership and contract map, start with [REVIEW.md](REVIEW.md). This README is
the operator quick start; `AGENTS.md` contains mandatory agent policy.
The design rationale and validation report for opportunity-driven search is
available in
[skill/kernel-optimizer/references/opportunity_driven_search_design.md](skill/kernel-optimizer/references/opportunity_driven_search_design.md).
The transfer-aware method-learning layer and its two-device validation are
documented in
[skill/kernel-optimizer/references/method_learning_design.md](skill/kernel-optimizer/references/method_learning_design.md).

Community optimization evidence can be captured as immutable, hash-bound PR
snapshots and reviewed optimization events. See
[knowledge/community/README.md](knowledge/community/README.md) and use
`scripts/kernel_opt.py community capture-pr|validate-corpus|validate-event`.
Cross-framework ownership, evidence fields and champion/challenger promotion
rules are defined in
[`knowledge/community/meta_governance.v2.json`](knowledge/community/meta_governance.v2.json)
and the current four-lane role topology in
[`knowledge/community/lane_topology.v3.json`](knowledge/community/lane_topology.v3.json).
Cycle 1 keeps its original hash-bound
[`meta_governance.v1.json`](knowledge/community/meta_governance.v1.json) identity;
new control-plane policy is added in later versions rather than rewriting it.
Use `community sync-repository` with explicit time windows for bounded,
incremental performance-PR discovery.
Use `scripts/kernel_opt.py community-eval` for cutoff-safe, fixed-budget control
versus community-augmented trials. New trials bind a machine-audited architecture
frontier: the executor must pre-register minimum search dimensions, map every
candidate to them, and cannot close an untested unknown bound with prose alone.
For audited trials, the JSONL execution transcript—not agent-reported timing—is
the authority that proves the final ranking was frozen before the first
production-source edit.

Record the complete delivery cycle separately from performance metrics:

```bash
python3 scripts/kernel_opt.py community-timing init \
  --cycle-id <cycle-id> --task-id <task-id> \
  --minimum-material-speedup 1.02 --output work-cycle.json
python3 scripts/kernel_opt.py community-timing start-phase \
  --ledger work-cycle.json --span-id research-1 \
  --phase COMMUNITY_RESEARCH --actor AGENT
python3 scripts/kernel_opt.py community-timing end-phase \
  --ledger work-cycle.json --span-id research-1 \
  --evidence discovery-receipt.json
python3 scripts/kernel_opt.py community-timing summarize \
  --ledger work-cycle.json --output work-cycle-summary.json
```

The ledger uses non-overlapping primary wall-clock spans for community research,
bottleneck diagnosis, implementation, compile/measurement, correctness,
performance, whole-model validation, upstream packaging and external wait.
Hash-bound milestones report time to the first candidate, correct result,
material improvement, qualified result, upstream-ready package, draft PR,
ready-for-review PR and merge. Legacy trials may retain milestone bounds but
must leave unavailable phase attribution under `UNATTRIBUTED_LEGACY_WORK`.
This prevents a fast kernel result from hiding days spent packaging or waiting
for external review.

This repository turns GPU-kernel optimization into a reproducible loop driven
by workload contracts, hardware evidence and falsifiable microbenchmarks.

It deliberately contains no application-specific algorithm, workload or
performance result.  Hardware facts are separated from empirical measurements;
measurements are keyed by device and software environment.

The workflow has two lanes. Fast discovery first compiles conditional model
terms into a ranked opportunity map, then writes and repairs a diverse set of
run-local production candidates linked to those opportunities. It uses cheap
anchor/edge screening and successive halving. Only survivors enter the evidence-closed
qualification and limit-certification lane. A technical build failure never
counts as a causal performance rejection.

## Start a run

An agent launched with this directory as its working tree is governed by
`AGENTS.md` and must request operator computation, workload and target hardware
before tuning.  The same gate is enforced by the command line:

```bash
python3 scripts/kernel_opt.py new-run --help
python3 scripts/kernel_opt.py new-run --print-intake
```

Once three manifests are available:

```bash
python3 scripts/kernel_opt.py new-run \
  --operator operator.json \
  --workload workload.json \
  --hardware hardware.json
```

`scripts/kernel_opt.py` is the stable public command surface. Individual
scripts remain implementation modules:

```bash
python3 scripts/kernel_opt.py --help
python3 scripts/kernel_opt.py new-run --operator operator.json --workload workload.json --hardware hardware.json
python3 scripts/kernel_opt.py next --run runs/<run-id>
```

After a correct discovery baseline is present, quantify several global
opportunities before managing the production-candidate portfolio:

```bash
python3 scripts/kernel_opt.py opportunity init --run runs/<run-id> --if-missing
python3 scripts/kernel_opt.py opportunity add --run runs/<run-id> --spec opportunity-spec.json
python3 scripts/kernel_opt.py opportunity rank --run runs/<run-id>
python3 scripts/kernel_opt.py opportunity close --run runs/<run-id> --opportunity-id <id> --disposition AT_MEASURED_ROOF --reason <reason> --evidence <result.json> --evidence-claim <claim> --reopen-condition <condition>
python3 scripts/kernel_opt.py opportunity reopen --run runs/<run-id> --opportunity-id <id> --reason <changed-condition>
python3 scripts/kernel_opt.py method recommend --run runs/<run-id>
python3 scripts/kernel_opt.py method export-snapshot --cutoff-at 2026-08-31T23:59:59Z --output /path/to/methods.json
python3 scripts/kernel_opt.py candidate init --run runs/<run-id> --if-missing
python3 scripts/kernel_opt.py candidate plan-execution --run runs/<run-id> --candidate-id <id> --phase-timing models/phase-timing.json --output models/candidate-execution/<id>.json --arm-count 2 --requests-per-arm 3
python3 scripts/kernel_opt.py candidate add --run runs/<run-id> --spec candidate-spec.json
python3 scripts/kernel_opt.py candidate run --run runs/<run-id> --candidate-id <id>
python3 scripts/kernel_opt.py candidate promote --run runs/<run-id> --candidate-id <id>
python3 scripts/kernel_opt.py persistent-run --root runs/<run-id> --spec runs/<run-id>/persistent-session.json --output runs/<run-id>/persistent-session-receipt.json
```

The default opportunity map requires 2--6 quantified opportunities across at
least two rewrite families. Each opportunity states the current global
contribution, a conditional optimistic gain ceiling, a likely gain interval,
confidence, implementation cost and hash-bound model evidence. New maps also
require a representative end-to-end `production_impact_gate` against the map's
frozen 1.01x materiality floor. It binds the
component self-time to total latency, checks the declared removable-work and
Amdahl speedup ceilings, and rejects the opportunity before implementation when
even its optimistic ceiling is below the frozen materiality floor. A fast
microbenchmark alone therefore cannot consume candidate-development budget.
Absolute-global-optimum labels are
rejected: a decomposition-specific minimum is not a semantic lower bound.
Candidates must bind to a ranked opportunity and stay below its gain ceiling.
Start with the highest-density one or two opportunities; broaden the portfolio
only after those focused implementations fail or remain ambiguous.
New maps must also name one or more `primary_transformation_axes`. These axes
are frozen from the local source and bottleneck analysis before method or
community retrieval. They are a subset of the broader rewrite-family inventory:
secondary families and generic words in historical evidence may score a match,
but cannot make it eligible. Routing always preserves the local opportunity
rank first, then uses method cards and community events only as bounded priors.
Measured dead ends can be marked `CLOSED` only with hash-bound run-local evidence,
a global stop reason and explicit reopen conditions. Closed opportunities score
zero and are excluded from method matching, candidate registration and next-action
routing; they return to the search budget only through an explicit audited reopen.

If that portfolio is still narrow, `method recommend` matches reusable method
cards against the frozen operator, workload, hardware and opportunity map. The
receipt is hash-bound to all four inputs and the card library. Literature and
vendor guidance remain discovery priors only: they cannot increase a gain
estimate, prove a hardware capability, accept a candidate or support a limit
claim. Unverified hard capabilities fail closed. A community task that declares
`FULL_HARNESS_DRY_RUN` must bind a two-arm, output-schema-validated canary with
all output contract checks true and every required rank sidecar mutually
consistent. Health checks and successful HTTP requests alone never satisfy
this dispatch prerequisite.
Every method source has a machine-readable availability timestamp. Temporal
evaluations use `method export-snapshot` so cards published or accessed after
the frozen cutoff never enter the augmented arm. Cards may additionally encode
an algorithmic decomposition (dependency, partition, local state, combine,
finalization, work/span/communication and invariants) so literature retrieval
can produce structural candidates rather than only launch-parameter hints.

Discovery then requires 2--6 candidates across at least two architecture families
by default. The default discovery budget is two hours overall, twenty minutes
per candidate and eight technical repairs per candidate; expiry stops further
measurement for plan review. Candidates are ranked by weighted screening gain
and at most two are promoted by default. Screening records prediction-versus-
observation residuals. Its timing is a routing signal, not
production acceptance evidence.

For models whose load, compilation or CUDA Graph capture dominates the actual
candidate measurement, `persistent-run` sends a bounded request list through
exactly one worker process. The worker must identify one engine initialization,
declare whether safe in-process treatment switching is supported, echo each
treatment identity, and return an output SHA-256. Single-treatment sessions
amortize setup without weakening isolation. Shared-treatment sessions fail
closed unless the worker explicitly supports identity-preserving switching.
Startup, per-request and shutdown timeouts remain separate, and receipts/logs
are immutable: reruns use a new output path.

Deterministic workloads must pass `output-parity` before `paired-compare` can
read timing samples. The parity input freezes both arm names, every case, the
repeat count and one output SHA-256 per arm/repeat/case. Missing, duplicate or
unexpected observations, baseline self-drift and baseline/candidate mismatch
all produce a reproducible `FAIL`; `paired-compare` requires the hash-bound
`PASS` result and rejects a stale or edited result before opening the timing
CSV. A caller-supplied `--correctness pass` assertion is not accepted.

Every newly registered candidate must first bind a machine-generated
`candidate-execution-plan-v1`. `candidate plan-execution` reads hash-bound phase
timing, compares fixed setup/compile/warmup cost with steady-state work, and
selects `COLD_PER_ARM`, `PERSISTENT_PER_ARM`, or
`PERSISTENT_SHARED_ENGINE`. Shared-engine routing is available only when a
successful persistent-session receipt exercised at least two treatment
identities and its logs still match their hashes. Smoke result v6 must echo the
selected process model and bind the plan in its reachability evidence. Use
`--attach` to migrate an active candidate created before this requirement;
repeat `--persistent-session-spec` once per planned session when persistence
was selected.

Strict qualification is intentionally blocked until `hardware_evidence.json` archives exact
vendor-official documents for the programming model, ISA, target-architecture
tuning guide and device specification. If the agent cannot find one of those
official documents, the developer must provide its location; inferred hardware
facts and neighboring-device values are forbidden. Discovery-only production
implementation and cheap screening may proceed after a correct baseline; those
results cannot support a production acceptance or limit claim.

After the exact launched binary is archived inside the run, disassemble it with
a hash-bound tool/architecture receipt, classify every static instruction site,
and build the conservative resource set. Unknown or multiply classified SASS
mnemonics are a hard stop:

```bash
python3 scripts/kernel_opt.py sass-archive \
  --binary runs/<run-id>/static/launched.cubin \
  --output-sass runs/<run-id>/static/final.sass \
  --output-receipt runs/<run-id>/static/disassembly_receipt.json \
  --vendor NVIDIA --device-name '<exact device>' --compute-capability 12.0
python3 scripts/kernel_opt.py sass-count \
  --input runs/<run-id>/static/final.sass \
  --binary runs/<run-id>/static/launched.cubin \
  --disassembly-receipt runs/<run-id>/static/disassembly_receipt.json \
  --output runs/<run-id>/static/sass-summary.json
python3 scripts/kernel_opt.py resources-discover \
  --sass-summary runs/<run-id>/static/sass-summary.json \
  --hardware-evidence runs/<run-id>/hardware_evidence.json \
  --output runs/<run-id>/models/resource_discovery.json
python3 scripts/kernel_opt.py next --run runs/<run-id>
```

Use `scripts/kernel_opt.py hardware-discover` to create a hardware snapshot,
then use the selected microbenchmarks and analysis commands to build evidence. `runs/` is
for generated artifacts; reusable knowledge belongs in `hardware/`,
`knowledge/`, `microbench/`, `schemas/` or the skill references.

Each run designates one `GLOBAL_SCHEDULER` and an independent
`GLOBAL_SUPERVISOR`. The scheduler maintains the global resource balance,
2--4-candidate tradeoff frontier and candidate-driven experiment queue. The
supervisor alone approves a hash-bound, budgeted dispatch. Stage workers cannot
accept a local candidate or approve their own probe. Phase gates reject a
run whose material resources are omitted, whose unknown utilization is not
bound to an experiment request, or whose accepted candidate lacks a global
tradeoff decision.

The shortest legal experiment path is:

```bash
python3 scripts/kernel_opt.py experiment-rank --run runs/<run-id>
python3 scripts/kernel_opt.py experiment-materialize --run runs/<run-id> --request-id <id>
# Complete the sealed experiment.json, then independent review:
python3 scripts/kernel_opt.py experiment-approve --run runs/<run-id> --request-id <id> \
  --supervisor-id <registered-id> --rationale '<decision-boundary review>'
python3 scripts/kernel_opt.py experiment-dispatch --run runs/<run-id> --request-id <id>
```

Dispatch fails when the top-two ordering cannot flip, the quantity is not
identifiable at the required precision, any role identity overlaps, a tier
budget is exceeded, or any approved artifact changed.

Run phases are non-skippable.  Inspect and advance the next gate with:

```bash
python3 scripts/kernel_opt.py advance --run runs/<run-id> --to BASELINE --check-only
python3 scripts/kernel_opt.py advance --run runs/<run-id> --to BASELINE
```

The enforced order is planning, production-exact baseline, modeling,
P0--P3 experiments, production/P4 validation, certification and completion.

## Clean asset lifecycle

Each directory has one owner:

- `runs/` contains mutable application work, raw evidence, binaries and new
  microbenchmark candidates.
- `microbench/` contains promoted application-independent source packages only.
- `hardware/measurements/` contains immutable results keyed by complete device
  and software identity.
- `skill/`, `scripts/`, `schemas/` and `templates/` contain only reusable
  instructions, automation and contracts.

Create candidates with `scripts/kernel_opt.py microbench-new`. At each accepted
hypothesis and before closing a run, execute `scripts/kernel_opt.py
microbench-harvest --run <run> --promote`; only candidates whose
correctness, controls, clean build, two independent cold starts, genericity and
static-instruction evidence are hash-bound and pass are added to the catalog.
Mechanism, device-calibrated and production-predictive claims have progressively
stronger gates. Device qualification additionally requires an
`EVIDENCE_CLOSED_V2` record in `hardware/measurements/index.json`; a string
`PASS` or an unregistered result is rejected. Promotion is append-only and never overwrites an
existing package. `scripts/kernel_opt.py audit` rejects undeclared files,
caches, generated outputs, production dependencies and task-specific content
in reusable directories.

Cold validation commands are argv-form JSON executed by `scripts/kernel_opt.py
microbench-reproduce`. The executor rejects source-tree
outputs and stale pre-existing artifacts, then binds logs and fresh outputs to
its own identity. Promotion accepts PASS check results only when those exact
artifacts occur in a trusted reproduction receipt.

## Evidence classes

- `FACT`: queried or statically verified.
- `MEASURED`: backed by immutable raw samples.
- `INFERRED`: derived from stated facts and measurements.
- `HYPOTHESIS`: awaiting a discriminating experiment.
- `REJECTED`: falsified or measured with an invalid method.

See `skill/kernel-optimizer/references/` for the optimization protocol.

## Community cohort dispatch authorization

A supplemental harness gate is deliberately not a global execution decision.
Formal community-evaluation arms use
`scripts/community_execution_authorization.py` to bind a frozen authorization
request and recompute three independent conditions: pre-GPU readiness (P),
execution-contract readiness (E), and a single-use `GLOBAL_SUPERVISOR`
qualification approval (A). Dispatch is legal only when `P && E && A`.

Every launched arm/repeat has an immutable
`community-dispatch-receipt-v1`. New observation and final-report provenance
envelopes must bind those receipts, so a numerically valid result cannot be
accepted without proof that its resource, GPU UUIDs, randomized schedule and
sealed argv were authorized. Existing frozen readiness, observation and report
formats remain unchanged; they are inputs or legacy evidence, not substitutes
for this combined gate.

Semantic supervisor approval v2 is intentionally a pre-dispatch layer. Validate
it with `scripts/community_semantic_approval.py`; a successful result is
`READY_FOR_ATOMIC_CONSUMPTION`, always reports
`gpu_dispatch_authorized=false`, and must still be consumed exactly once by a
versioned atomic dispatcher. The validator binds the trusted supervisor
registry, distinct scheduler/analyst/experimenter roles, exact bounded budget,
per-task decision/measurability/frontier/objective chain, frozen request scope,
expiry policy, and its own declared Git blobs. The v1 combined gate continues
to reject non-null approvals and there is no compatibility auto-upgrade.

`scripts/community_atomic_claim.py` is the non-launching transactional primitive
used by that future dispatcher. It takes transition timestamps from its own UTC
clock after acquiring the SQLite write transaction, binds each session to one
canonical SQLite store path plus an externally issued no-rollback epoch,
revalidates the frozen schedule and receipt lineage on every transition, and
consumes entries in order without automatic retry after an ambiguous launch.
The epoch issuer must durably prevent reuse after database deletion or rollback;
SQLite alone cannot prove that external monotonicity. These guarantees do not
validate a live process, GPU assignment, or successful observation; only the
dispatcher may establish those identities and turn a consumed entry into
authorized execution provenance.

The claim store also refuses to turn a bare process exit into experimental
success. `SUCCESS` and `CORRECTNESS_FAIL` transitions require a
`community-entry-terminal-receipt-v2` created from a canonical
`community-work-cycle-observation-v1`; the observation, ledger and assessment
are revalidated and hash-bound under one evidence root while the SQLite write
lock is held. A later state transition rechecks those bytes. Timeouts, process
failures and ambiguous crash windows remain explicit v1 terminal outcomes and
never advance the schedule. This is evidence finalization, not a process or GPU
launcher.

Before an atomic claim store can be consumed, validate a versioned deployment
with `scripts/community_claim_store_deployment.py`. The deployment binds one
canonical database path, host boot identity, dispatcher executable and an
externally issued no-rollback epoch. Epoch replacement must form an explicit
predecessor chain, and both the declared Git commit and current worktree bytes
for the schemas, validator and claim implementation must match. Passing this
gate means only `ready_for_atomic_claim=true`; it never grants GPU dispatch.

`scripts/community_execution_authorization_v2.py` is the store-bound bridge
into that primitive. It independently re-runs the canonical pre-GPU and
execution-contract validators, the semantic approval validator and the live
store-deployment validator; resolves each exact argv from the frozen task and
schedule; and derives `ready_for_atomic_claim` from `P && E && A && store`.
Its output still has `gpu_dispatch_authorized=false`: only a later atomic
dispatcher can consume the token, attest a child process and write terminal
evidence. Version 1 remains legacy and is not reinterpreted in place.

`scripts/community_runtime_authorization.py` adds the final fail-closed bridge
before launch. A version-4 combined authorization revalidates version 2 and
binds each task **and arm** to a distinct materialized treatment manifest,
source-file closure, implementation identity, runtime lock, working directory,
command executable, resolved `/proc` executable and complete child environment.
Both repeats reuse the same arm profile, while CONTROL and
COMMUNITY_AUGMENTED must not resolve to the same implementation. A
`KERNEL_OPT_TREATMENT_ID` marker is part of the exact child environment, so an
arm label without a realized treatment is rejected before atomic claim.
Relative sealed commands such as `python3` are executed through the bound
interpreter while preserving the original argv identity.

`scripts/community_atomic_dispatcher.py` is the runtime-bound single-entry
launcher. It revalidates version-4 combined authorization on the live
claim-store host, derives the
wall/GPU ceiling from the exact `--timeout-seconds` already present in every
sealed argv, checks the formal UUID set against live inventory, atomically
claims the next frozen entry, rechecks the executable immediately before spawn,
launches once with the exact environment, and records `/proc` argv, executable,
environment, boot and process-start identity. Output and log paths must be new,
distinct and below the artifact root. Runtime drift before claim does not
consume the token; drift in the launch window is terminal and never retried.
Every dispatch result carries the arm, treatment and implementation identities
that were present in the attested child environment.
Any ordinary process exit—including zero—stays
`PROCESS_EXITED_AWAITING_VALIDATED_OBSERVATION`; only the terminal-v2 evidence
finalizer may advance the schedule as success.

## Four-lane delivery accounting

The four autonomous execution lanes write canonical work-cycle ledgers while
the control plane selects their identities explicitly in one portfolio manifest:

```bash
python3 scripts/kernel_opt.py community-portfolio \
  --manifest /path/to/four-lane-portfolio-manifest.json \
  --output /path/to/four-lane-portfolio-report.json
```

The report rejects duplicate ledger or cycle/task identities and keeps
prospective measurements separate from legacy milestone bounds. Version 3 adds
an evidence-backed delivery funnel from candidate proposal through correctness,
material improvement, qualification, upstream readiness, PR review and merge,
plus candidate-to-Draft and Draft-to-Ready timing and conversion metrics. Exact
delivery timing is computed only from `PROSPECTIVE_EXACT` ledgers; legacy cycles
are never backfilled into those metrics. `leading_constraint` gives dashboards a
transcript-free answer to where each lane is currently losing useful upstream
output. This is descriptive accounting; it does not establish strategy causality
or count this repository's maintenance PRs as framework optimization results.

## Upstream delivery package

Before expanding qualification, combine the whole-workload gain ceiling with
the permanent maintenance surface and real workload coverage:

```bash
python3 scripts/kernel_opt.py candidate-value --print-template \
  > candidate-value-request.json
python3 scripts/kernel_opt.py candidate-value \
  --request candidate-value-request.json \
  --output candidate-value-decision.json
```

The value gate stops an optimistic ceiling below the materiality floor, asks
for reachability before timing an unproven path, and holds narrow low-density
protocol/API changes at Draft even when their focused tests pass.  Its review
cost formula is explicit and policy thresholds are supplied by the run; it is
a routing decision, not performance proof.  This keeps expensive target-
hardware qualification focused on candidates whose possible production value
can justify their permanent review and maintenance cost.  A confirmed path
with an unknown ceiling returns `QUANTIFY_WHOLE_WORKLOAD_CEILING`; callers do
not have to invent zero or favorable gain estimates merely to pass the schema.

When qualification stops, classify the attempt before rejecting the candidate:

```bash
python3 scripts/kernel_opt.py qualification-route --print-template \
  > qualification-attempt.json
python3 scripts/kernel_opt.py qualification-route \
  --attempt qualification-attempt.json \
  --output qualification-route.json
```

The route distinguishes an exact-source candidate assertion failure from image,
toolchain, dependency, ISA, import-identity and platform failures. Environment
failures retain the candidate and consume a frozen technical-repair budget;
exhausting that budget stops dependency chasing without turning the event into a
correctness rejection. An official workflow that intrinsically builds native
code cannot run under a no-build contract: the result explicitly asks for that
build to be authorized or for a pinned prebuilt closure. Tests that ran against
an unverified imported source are invalid evidence, not a pass or candidate
failure.

An accepted optimization is not automatically an upstream-ready change. Build
the review package from a clean candidate commit and hash-bound evidence. Set
`submission_mode` to `DRAFT_REVIEW` when the immediate objective is early
maintainer review or upstream CI; omit it (or use `QUALIFICATION`) for the full
release gate:

```bash
python3 scripts/kernel_opt.py upstream-package build \
  --spec upstream-candidate-spec.json \
  --evidence-root evidence \
  --repository /path/to/candidate-worktree \
  --output upstream-package
```

The command independently materializes `base_commit..candidate_commit` as
`changes.patch`, verifies that `HEAD` is the declared candidate and the worktree
is clean, and rejects stale evidence or known failed gates. `DRAFT_REVIEW`
requires focused correctness and source review plus reproducible evidence, but
permits empty benchmark claims and pending whole-model, upstream-CI and
cross-hardware gates. It is always labeled `DRAFT_PENDING_QUALIFICATION` and
explicitly forbids upstream-ready or portable-performance claims. Full
`QUALIFICATION` mode still recomputes every benchmark speedup, requires
whole-model evidence, and only produces `UPSTREAM_READY` when all five gates
pass. Existing output directories are never overwritten.

## Seeded hardware evidence

The first adapter and historical dataset target an RTX 5090 / SM120 environment.
They live under `hardware/measurements/nvidia/rtx5090_sm120_gpu6/` and include a
hardware snapshot, raw launch/barrier/load/store samples, service-curve fits,
the compiled binary identity, resource usage and SASS.  The counter-access
probe is archived separately and currently reports `DENIED`; no stall-counter
claim is permitted from that environment.

Those historical records are explicitly `LEGACY_UNQUALIFIED`: they may be
inspected, but they cannot parameterize a hardware model. A usable measurement
must be re-run and registered as `EVIDENCE_CLOSED_V2` with official target
evidence, P0 calibration, source, binary, final SASS and raw samples. New device
models receive separate snapshots and measurement directories rather than
inheriting values.
