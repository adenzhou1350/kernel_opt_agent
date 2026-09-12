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
  --minimum-material-speedup 1.02 \
  --initial-phase COMMUNITY_RESEARCH \
  --candidate-evidence candidate-value-decision.json \
  --output work-cycle.json
python3 scripts/kernel_opt.py community-timing switch-phase \
  --ledger work-cycle.json --span-id environment-1 \
  --phase ENVIRONMENT_SETUP --actor CPU \
  --evidence discovery-receipt.json
python3 scripts/kernel_opt.py community-timing run-phase \
  --ledger work-cycle.json --span-id env-1 \
  --phase ENVIRONMENT_SETUP --actor CPU --timeout-seconds 600 \
  --receipt environment-command-receipt.json -- \
  python3 -m pip check
python3 scripts/kernel_opt.py community-timing import-phase-receipt \
  --ledger work-cycle.json --span-id remote-env-1 \
  --phase ENVIRONMENT_SETUP --actor CPU --resource-id worker-sm120 \
  --receipt worker-terminal.json --started-at-field started_at \
  --ended-at-field finished_at --duration-field elapsed_seconds \
  --status INTERRUPTED
python3 scripts/kernel_opt.py community-timing summarize \
  --ledger work-cycle.json --output work-cycle-summary.json
python3 scripts/kernel_opt.py community-timing audit-root \
  --root /path/to/framework-evidence \
  --max-active-phase-seconds 21600
```

The ledger uses non-overlapping primary wall-clock spans for community research,
bottleneck diagnosis, implementation, compile/measurement, correctness,
performance, whole-model validation, upstream packaging, environment setup,
governance validation and external wait. Use `ENVIRONMENT_SETUP` only for
dependency/toolchain/runtime repair, and `GOVERNANCE_VALIDATION` only for
contracts, authorization, evidence closure and policy checks. The `run-phase`
form is preferred for bounded commands: it opens the span, runs the
exact argv without a shell, writes an immutable command receipt and closes the
span as `COMPLETE` or `INTERRUPTED` on success, non-zero exit, launch failure or
timeout. Its receipt proves command wall time and exit status only; it never
turns a passing command into correctness or performance evidence.
When a governed worker already produced an immutable terminal receipt, use
`import-phase-receipt` to bind its exact start/end timestamps instead of
reconstructing wall time. The prospective ledger must already predate the
receipt; optional duration-field reconciliation rejects inconsistent receipts.
Importing timing does not validate the worker result or change its outcome.
The summary reports their seconds and their share of attributed active work. If
neither phase was recorded, that ratio is `null` with
`NOT_SEPARATELY_RECORDED` rather than a misleading zero. Do not retroactively
reclassify legacy spans.
Hash-bound milestones report time to the first candidate, correct result,
material improvement, qualified result, upstream-ready package, draft PR,
ready-for-review PR and merge. Legacy trials may retain milestone bounds but
must leave unavailable phase attribution under `UNATTRIBUTED_LEGACY_WORK`.
This prevents a fast kernel result from hiding days spent packaging or waiting
for external review.

Controllers can run `audit-root` across lane evidence directories without
messaging the execution lanes. It reports prospective ledgers that have no
exact phase attribution, no primary phase, or an overlong active phase. It
separately reports environment/governance measurement debt; a normally closed
bounded cycle is not mistaken for an abandoned active cycle. The audit is
read-only and intentionally does not create another evidence schema or infer
historical timing. Invalid ledgers are grouped into machine-readable issue
classes with a conservative recommended action. A file that claims the public
schema name while using an ad-hoc shape is reported as a schema collision;
identity drift and canonical-schema drift remain distinct. Every class sets
`safe_automatic_repair=false`: migrate by creating a new ledger version or a
legacy-milestone record, never by rewriting historical evidence.

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

## Route upstream CI without mistaking policy gates for regressions

An upstream check matrix may render red because a Draft is intentionally
blocked or a maintainer-only `run-ci` label is absent. Do not restart
qualification from the aggregate color. Capture the exact public head SHA,
check conclusions, detail URLs and the small evidence lines that explain each
failure, then run:

```bash
python3 scripts/kernel_opt.py upstream-ci-route \
  --snapshot /path/to/upstream-ci-snapshot.json \
  --output /path/to/upstream-ci-route-decision.json
```

The classifier recognizes only a narrow set of explicit policy-gate and
infrastructure markers. An opaque red check remains `UNKNOWN_FAILURE`; a
candidate-test marker takes precedence even when the same check also mentions
a Draft gate. The output can route the control-plane Dashboard, but it never
authorizes a CI rerun, public comment, Draft-to-Ready transition or merge.

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

For an upstream change, keep the repository's internal candidate status
separate from GitHub's Draft flag and from CI/reviewer handoffs. A red Draft
gate or maintainer-authorization check is not a test failure. Record the
current state and obtain a deterministic next owner/action with:

```bash
python3 scripts/kernel_opt.py upstream-review-state pr-review-state.json
```

The classifier recommends opening a Draft once the minimal commit,
focused correctness, lint/format, reproduction and claim boundary pass. It
recommends Ready only after every applicable official-correctness,
production-reachability, materiality, target-workload and known-regression
gate passes.

When the worker cannot clone source, create a deterministic transport directly
from committed Git blobs. The builder never reads tracked files from the
working tree, so dirty files, checkout line-ending conversion and export rules
cannot change the payload:

```bash
python3 scripts/kernel_opt.py qualification-source-bundle --build \
  --repo /path/to/framework --commit <full-commit> \
  --repository-url https://github.com/org/framework.git \
  --archive framework-source.tar.gz --manifest framework-source.manifest.json
python3 scripts/kernel_opt.py qualification-source-bundle --verify \
  --archive framework-source.tar.gz --manifest framework-source.manifest.json \
  --extract-root /immutable/new/source-root
```

The manifest binds the repository identity, commit, tree, archive digest and
every file, executable mode and safe relative symlink. Verification rejects
tampering, duplicate or special entries, traversal, escaping symlinks and an
existing extraction target. This is source transport only: it does not approve
materialization, install dependencies, build native code, launch a workload or
authorize GPU use.

The control plane can aggregate several immutable review-state records without
guessing from chat text or unrelated receipts:

```bash
python3 scripts/kernel_opt.py upstream-delivery-inbox delivery-inbox.json
```

Each manifest entry supplies a stable candidate/lane identity and the path and
SHA-256 of one `upstream-review-state-v1` record.  The command revalidates every
nested record, rejects hash drift, duplicate candidate identities and duplicate
PR bindings, then sorts the resulting actions. Each item retains the internal
candidate status and lists the passed, pending and failed Draft-minimum and
Ready gates, so equal action labels are ordered by evidence progress instead of
candidate name. In particular, a candidate whose Draft minimum is complete
but whose PR is absent becomes an explicit
`OPEN_DRAFT` inbox item instead of silently remaining in an experiment folder.
Repository-maintenance candidates use a separate manifest so they cannot
inflate framework delivery metrics.

Use `upstream-delivery-inbox-v2` once a queue contains open Ready PRs. Each
Ready entry must additionally hash-bind an `upstream-review-handoff-v1`
record observed at the same instant as the inbox. The resulting v2 queue
promotes missing reviewers, one due targeted follow-up, one due review-channel
escalation, or author feedback above an otherwise generic reviewer wait. It
retains the underlying review-state action and never authorizes an automatic
message. Version 1 remains accepted unchanged for historical replay.

Use `upstream-delivery-inbox-v3` when `OPEN_DRAFT` is actionable. It requires a
hash-bound UTF-8 PR body, freshness evidence containing the exact candidate
commit, and the intended repository/branch/compare URL. This validates the
public Draft materials but does not authorize publishing them. Versions 1 and
2 remain accepted unchanged for historical replay. An otherwise Draft-ready
candidate without these materials is routed to `COMPLETE_DRAFT_MATERIALS`; it
does not fail unrelated inbox entries or expose a public action prematurely.

Use `upstream-delivery-inbox-v4` for a live publication queue. Its
`upstream-delivery-freshness-v1` evidence is short-lived (at most six hours)
and binds the exact candidate, repository, branch, fork ref, observed upstream
main, touched-path drift result, merge result, exact-head PR count and explicit
Draft eligibility. Expired, mismatched or non-standard freshness does not fail
the whole portfolio; that candidate becomes `REFRESH_DRAFT_FRESHNESS`, owned by
its execution lane, and is removed from external publication actions until a
fresh closure is supplied. Hash or byte drift in the referenced body or
freshness file remains a hard validation failure.

Generate that closure with `python scripts/kernel_opt.py
upstream-draft-freshness`. The command resolves the exact candidate, upstream
and fork refs, compares every candidate-touched path between the merge-base and
current upstream, and runs Git's merge-tree conflict check before writing one
immutable freshness record. The exact-head PR count remains an explicitly
observed public input (`--exact-head-pull-request-count`); the command does not
query GitHub or authorize publication. This removes repeated ad-hoc drift and
merge scripts while keeping public state and human submission outside the
local Git claim.

Use `upstream-delivery-inbox-v5` before an AI-assisted Draft is exposed as a
publication action. In addition to v4 freshness, it accepts a hash-bound
`upstream-delivery-author-accountability-v1` record for the exact candidate
commit. Until the named human submitter attests that every changed line was
reviewed, relevant tests were rerun, the change can be defended, AI assistance
is disclosed, and the repository's commit-attribution rule is satisfied or not
applicable, the candidate is routed to `COMPLETE_AUTHOR_ACCOUNTABILITY`. This
also remains true after an AI-assisted Draft has already been opened: a Draft
must not make the missing human review disappear behind
`KEEP_DRAFT_CONTINUE_QUALIFICATION`. The attestation is a responsibility
boundary, not a substitute for correctness or performance evidence.

Before the human review, automation may assemble the exact commit, evidence,
pending gates, proposed body and fail-closed attestation command into one
create-once review packet:

```bash
python3 scripts/kernel_opt.py upstream-author-review-packet delivery-inbox.json \
  --candidate-id NAME --output author-review-packet.md
```

The packet is machine-prepared convenience only. It cannot attest review or
authorize publishing, and it is emitted only for a fresh v5 inbox item already
routed to `COMPLETE_AUTHOR_ACCOUNTABILITY`.

After doing that work personally, the submitter can create the immutable record
without hand-writing JSON:

```bash
python3 scripts/kernel_opt.py upstream-author-accountability \
  --candidate-id NAME --repository OWNER/REPO --branch BRANCH \
  --commit 40_HEX_COMMIT --submitter-identity NAME_OR_EMAIL \
  --commit-attribution PASS --output author-accountability.json \
  --attest-changed-lines-reviewed --attest-relevant-tests-rerun \
  --attest-can-defend-change --attest-ai-assistance-disclosed
```

Every attestation flag is mandatory and the output is create-once. Automation
must not invoke this command from prior agent receipts or infer human review;
it may run only after the named submitter explicitly confirms all four facts.

Reviewer state records code-owner requests separately from
`early_review_handles`. This preserves the difference between reviewers that
GitHub queues until Ready and a small set of relevant maintainers explicitly
asked to review the Draft's API or overlap direction while qualification
continues.

After a PR becomes Ready, record only the time at which the system first
observed that state and route reviewer waits with:

```bash
python3 scripts/kernel_opt.py upstream-review-handoff pr-review-handoff.json
```

The handoff clock is prospective and lower-bound-only: it never invents a
review-request time before observation. The default policy used by the control
dashboard waits 24 hours before one targeted reviewer follow-up and 72 hours
before one project review-channel escalation. Decisions never authorize an
automatic message.

Drafts use a separate prospective progress clock so a failed value gate or a
stale external environment does not remain open indefinitely:

```bash
python3 scripts/kernel_opt.py upstream-draft-progress draft-progress.json
```

The router sends a passed Draft to Ready, a failed or disproven Draft to
revision/closure, and a Draft without material progress for the configured
window to bounded replanning or an external reproducible gate. It never closes
or marks a pull request Ready automatically.

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

Add a newly selected prospective cycle without hand-editing path/hash fields:

```bash
python3 scripts/kernel_opt.py community-portfolio-register \
  --manifest /path/to/current-portfolio-manifest.json \
  --register SGLANG_OPTIMIZATION=/path/to/new-community-work-cycle.json \
  --output /path/to/superseding-portfolio-manifest.json
```

Registration is explicit rather than a recursive evidence scan. It validates the
complete prior manifest, the new ledger and its evidence closure, rejects legacy
or pre-accounting cycles and duplicate cycle/task identities, and creates the
superseding manifest once. This keeps candidate accounting current without
guessing lane ownership from filenames or free-form task prose.

When an already-selected prospective ledger advances in place (for example, a
Draft PR event closes an earlier active wait), refresh only that exact lane/path
identity instead of hand-editing its hash:

```bash
python3 scripts/kernel_opt.py community-portfolio-register \
  --manifest /path/to/current-portfolio-manifest.json \
  --refresh VLLM_OPTIMIZATION=/path/to/advanced-community-work-cycle.json \
  --output /path/to/superseding-portfolio-manifest.json
```

Refresh never scans for ledgers and cannot change the selected path or lane. It
permits the named old hash to be stale, then validates the advanced ledger and
the complete superseding selection. Registration and refresh are deliberately
separate operations so a stale identity cannot weaken new-cycle admission.

The report rejects duplicate ledger or cycle/task identities and keeps
prospective measurements separate from legacy milestone bounds. Version 4 adds
an evidence-backed delivery funnel from candidate proposal through correctness,
material improvement, qualification, upstream readiness, PR review and merge,
plus candidate-to-Draft and Draft-to-Ready timing and conversion metrics. Exact
delivery timing is computed only from `PROSPECTIVE_EXACT` ledgers; legacy cycles
are never backfilled into those metrics. `leading_constraint` gives dashboards a
transcript-free answer to where each lane is currently losing useful upstream
output. A pull-based dashboard can therefore separate user confirmations,
credentials, environment work, governance, GPU work, and normal agent work
without asking autonomous lanes for status messages. An active ledger describes
an unfinished candidate cycle, which can remain open while its lane continues
research on another candidate. This is descriptive accounting; it does not
establish strategy causality or count this repository's maintenance PRs as
framework optimization results.

Version 5 adds `prospective_phase_time` for the explicitly selected,
hash-bound `PROSPECTIVE_EXACT` ledgers. It includes active spans at one shared
`generated_at`, separates environment/governance overhead from external waits,
and reports the overhead share only against attributed active phase time. The
aggregation sums ledger spans, so parallel candidates may overlap; it is not a
wall-clock or labor-time measure. Historical root-wide instrumentation debt
remains a separate audit and is never hidden by this selected-portfolio view.

Version 6 stops treating an immutable ledger's `ACTIVE` span as proof that work
is still current. `active_delivery_queue` and `needs_user_action_count` now
contain only spans backed by a valid, unexpired
`community-action-attestation-v1` with an explicit owner. Missing, expired,
resolved and superseded attestations remain visible in
`delivery_action_inventory` but cannot create current work or silently assign a
credential to the user. Bind one or more attestations explicitly when they are
available:

```bash
python3 scripts/kernel_opt.py community-action-attest \
  --ledger /path/to/work-cycle.json --span-id active-span \
  --state ACTIVE --action-owner AGENT --valid-for-seconds 1800 \
  --evidence /path/to/current-result.json --output current-action.json
```

The command derives the cycle, resource and ledger identity from the validated
active span, requires current evidence, and creates the attestation once. Use
`RESOLVED` or `SUPERSEDED` with owner `NONE` and no validity window to retire a
stale declared action without rewriting its historical ledger.

```bash
python3 scripts/kernel_opt.py community-portfolio \
  --manifest /path/to/four-lane-portfolio-manifest.json \
  --action-attestation /path/to/current-action.json \
  --output /path/to/four-lane-portfolio-report.json
```

Start timing when a framework candidate is selected, before editing production
source, and bind the selection receipt immediately:

```bash
python3 scripts/kernel_opt.py community-timing init \
  --cycle-id framework-candidate-v1 --task-id lane-task-id \
  --observation-mode PROSPECTIVE_EXACT \
  --initial-phase UPSTREAM_PACKAGING \
  --candidate-value-decision candidate-value-decision.json \
  --output community-work-cycle.json
```

`--candidate-value-decision` re-hashes its request and recomputes the complete
decision before one atomic write creates the ledger and
`FIRST_CANDIDATE_PROPOSED` milestone. A modified decision, stale request hash,
ambiguous generic evidence or ledger timestamp before the decision fails before
the ledger is written. This is the strict candidate-to-Draft timing origin;
`--candidate-evidence` remains available for explicitly non-strict historical
or late-entry accounting and must not be presented as the same KPI. The strict
entry also opens `BOTTLENECK_DIAGNOSIS` by default; use
`--initial-phase` when selection occurs later in a truthful phase. Missing
evidence, an existing output, or a legacy observation mode leaves no partial
ledger. Use `switch-phase` to close the current phase and open its successor at
one timestamp. The separate `mark` operation remains available for later
milestones.

PR transitions are recorded atomically with their stable URL and immutable
GitHub event receipt. `READY` requires an observed Draft milestone, and
`MERGED` requires an observed Ready milestone. When the cycle is actively in
`EXTERNAL_WAIT`, the same transaction closes that wait at the observed PR event
time; unrelated environment, validation, and implementation phases remain
active:

```bash
python3 scripts/kernel_opt.py community-timing record-pr-stage \
  --ledger community-work-cycle.json --stage DRAFT \
  --url https://github.com/owner/repository/pull/123 \
  --evidence github-pr-draft-event.json
python3 scripts/kernel_opt.py community-timing record-pr-stage \
  --ledger community-work-cycle.json --stage READY \
  --url https://github.com/owner/repository/pull/123 \
  --evidence github-pr-ready-event.json
```

Do not retroactively manufacture these events. A cycle that began without the
prospective ledger remains `LEGACY_MILESTONE_BOUNDS` and is excluded from exact
candidate-to-Draft and Draft-to-Ready timing.

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

Before issuing another version of an environment materialization plan, audit the
run's existing plan and terminal receipts:

```bash
python3 scripts/kernel_opt.py qualification-churn \
  --run runs/<run-id> \
  --output runs/<run-id>/experiments/qualification-churn-v1.json
```

The audit links terminal receipts to exact plan hashes and distinguishes four
useful states: stop an exhausted repair scope, collapse unexecuted plan
revisions, advance after an environment closure succeeds, or acknowledge that
the workload was actually reached. It is a routing signal only and never acts
as execution, correctness, performance, or authorization evidence.

The route distinguishes an exact-source candidate assertion failure from image,
toolchain, dependency, ISA, import-identity and platform failures. Environment
failures retain the candidate and consume a frozen technical-repair budget;
exhausting that budget stops dependency chasing without turning the event into a
correctness rejection. An official workflow that intrinsically builds native
code cannot run under a no-build contract: the result explicitly asks for that
build to be authorized or for a pinned prebuilt closure. Tests that ran against
an unverified imported source are invalid evidence, not a pass or candidate
failure.

Before rebuilding an environment after that routing decision, compare the
requested workflow with an already materialized closure:

```bash
python3 scripts/kernel_opt.py qualification-environment \
  --closure cached-environment.json \
  --request candidate-environment-request.json \
  --output environment-reuse.json
```

The comparison separates reusable dependency/toolchain state from a source-
bound native extension and the actual imported module. It permits a cheap
source rebind or bounded extension rebuild without treating an image, ISA,
workflow, test-contract, dependency-lock or GPU-visibility mismatch as a cache
hit. The result is advisory reuse routing only: it never authorizes a build,
test, GPU run, correctness claim or performance claim. Templates are available
with `--print-closure-template` and `--print-request-template`.

Before a model download, JIT compile or native build, fail fast on implicit or
unusable framework caches:

```bash
python3 scripts/kernel_opt.py environment-cache-preflight --print-template \
  > cache-preflight-request.json
python3 scripts/kernel_opt.py environment-cache-preflight \
  --request cache-preflight-request.json \
  --output cache-preflight-result.json
```

The request binds every intended cache path, its environment variable, a
workload-sized free-space floor and whether a temporary write probe is allowed.
The result distinguishes path drift, missing or non-directory roots,
writeability and insufficient space before an expensive command starts. It is
only an environment preflight and never authorizes download, build, execution,
correctness or performance claims.

When a new closure really must be built, the controller can issue a separate,
short-lived CPU-only materialization approval after reviewing the exact plan,
environment request and still-blocked broker job:

```bash
python3 scripts/kernel_opt.py qualification-environment-authorize --issue \
  --artifact-root /path/to/run \
  --plan /path/to/run/experiments/materialization-plan.json \
  --request /path/to/run/experiments/environment-request.json \
  --job /path/to/run/experiments/resource-job.json \
  --supervisor-id controller --approval-id closure-prep-v1 \
  --ttl-seconds 7200 --max-wall-seconds 3600 \
  --output /path/to/run/experiments/materialization-approval.json
```

The approval is deliberately narrower than a broker gate: all preparation
steps must declare `gpu=false`, the job must remain blocked, and the approval
forbids GPU devices, workloads, service mutation and every broker transition.
It may permit network access only for dependency materialization. Revalidate
the approval immediately before preparation; it never authorizes the later
GPU test or turns the prepared closure into correctness evidence.

Add `--dispatcher-bound` when the approval will be consumed by the shared
worker-local dispatcher. Omitting it preserves the legacy v1 approval format
for existing run-local audit and materializer flows.

Run an approved standard plan through the worker-local dispatcher instead of
calling its materializer directly:

```bash
python3 scripts/kernel_opt.py qualification-environment-dispatch \
  --artifact-root /path/to/run \
  --approval /path/to/run/experiments/materialization-approval.json \
  --approval-sha256 <controller-reviewed-sha256>
```

New approvals bind the exact dispatcher bytes and are single-use. The
dispatcher revalidates the approval, plan, still-blocked job, executor and
deadline, atomically claims the approval, forces CUDA visibility off and runs
the one sealed argv without a shell. A crash or nonzero exit consumes the
claim and requires a fresh versioned plan and approval; it is never retried
automatically. Its terminal receipt proves only the executor process outcome.
The materializer's own evidence still decides whether the closure succeeded,
and neither receipt authorizes a GPU, workload, service or broker transition.
Legacy v1 approvals remain validatable for audit but cannot be dispatched.

The versioned dispatcher receipt includes exact process `started_at`,
`completed_at` and monotonic `duration_seconds`. Import it into a prospective
work-cycle ledger so environment repair is measured instead of disappearing
into unaccounted wall time:

```bash
python3 scripts/kernel_opt.py community-timing import-phase-receipt \
  --ledger work-cycle.json --span-id worker-materialization \
  --phase ENVIRONMENT_SETUP --actor CPU --resource-id worker-sm120 \
  --receipt .kernel-opt/materialization-claims/<approval-sha>.receipt.json \
  --started-at-field started_at --ended-at-field completed_at \
  --duration-field duration_seconds --status COMPLETE
```

Use `INTERRUPTED` for failed or timed-out executor receipts. Importing the
receipt measures environment wall time only; it does not accept the resulting
closure or change correctness, performance, GPU or workload state.

Some registered workers already run inside a managed GPU container and cannot
launch the requested image again. Attest that preprovisioned runtime and its
writable closure filesystem before writing a plan for it:

```bash
CUDA_VISIBLE_DEVICES=-1 python3 scripts/kernel_opt.py \
  qualification-environment-worker --collect \
  --worker-id worker-shared-sm120 --host-id shared-8x-sm120-32g \
  --storage-root /workspace \
  --output worker-runtime-attestation.json
```

The attestation records the exact Python and Torch bytes, compiled CUDA arches,
toolchain, mount capacity, pre-mounted device nodes, nested container-runtime
availability, and current GPU process snapshot. It requires Torch to see no
CUDA device during collection, but it does not pretend that a managed worker
has no device nodes. A request may bind this identity with
`runtime_provenance.kind=ATTESTED_PREPROVISIONED_WORKER`, a null image digest,
and the exact worker id. Reuse then fails closed on either the worker id or
attestation hash. This is still preparation evidence, never a GPU lease or
workload authorization.

For several autonomous lanes sharing multiple GPU machines, queue validation
work independently from the task that discovered it:

```bash
python3 scripts/kernel_opt.py resource-broker --database broker.sqlite \
  submit --job job.json
python3 scripts/kernel_opt.py resource-broker --database broker.sqlite \
  bind-gate --job same-job-with-ready-gate.json
python3 scripts/kernel_opt.py resource-broker --database broker.sqlite \
  withdraw --job-id stale-job --reason-path decisions/supersession.json \
  --reason-sha256 <sha256>
python3 scripts/kernel_opt.py resource-broker --database broker.sqlite \
  acquire --inventory inventory.json
python3 scripts/kernel_opt.py resource-broker --database broker.sqlite \
  plan --inventory inventory.json
python3 scripts/kernel_opt.py resource-broker --database broker.sqlite snapshot
```

The resource broker atomically reserves an exact GPU gang on one compatible
worker, prefers a reusable environment closure, and backfills a smaller
runnable job when a larger high-priority gang cannot currently fit. It is
deliberately non-launching: the returned lease identifies only the worker, GPU
UUIDs, environment, budget, and callback task. The task-specific authorization
and atomic dispatcher remain mandatory before starting a process. A missed
heartbeat keeps its GPUs reserved in `STALE_REQUIRES_RECONCILIATION` until a
hash-bound terminal result releases them, so a possibly running job is never
made available by timeout alone.
`bind-gate` lets the controller atomically move an existing
`BLOCKED_AUTHORIZATION` job into the queue after an external supervisor gate is
available. It accepts only the same complete job with a READY gate identity;
any workload, source, environment, resource, budget, priority, origin or
callback drift is rejected. The broker binds that identity but does not certify
its authorization semantics or launch work.
An unleased blocked or queued job whose immutable body is superseded can be
withdrawn with a hash-bound reason. Withdrawal preserves the terminal audit
record and is forbidden once any lease exists; it never counts as an
experimental result.
Jobs that require a particular topology or must avoid service GPUs can bind an
exact gang through optional `resource.required_gpu_uuids`. Its cardinality must
equal `gpu_count`; the broker waits unless every named UUID is simultaneously
free on one compatible host, and records that exact sorted set in the lease.
The read-only `plan` view classifies every queued item as immediately
reservable, waiting for GPUs, requiring environment preparation, or having no
compatible resource. It is suitable for a dashboard but is not a reservation.

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

CPU isolation may intentionally make `torch.cuda.get_arch_list()` empty. The
worker attestation therefore falls back to the non-device-initializing
`torch._C._cuda_getArchFlags()` metadata while still binding the Torch module,
build configuration and native libraries. Materializers should consume that
attested value rather than exposing a GPU to rediscover compiled targets.
The same attestation records `nvcc`, C/C++ compilers, Ninja, Git, CMake and
Make as exact resolved path/version/SHA identities (or explicit nulls). Plans
that need a source fetch or native build can therefore reject an incompatible
worker before consuming a long materialization budget.
For a preprovisioned worker, set `runtime_worker.required_toolchain` in the
materialization plan to the exact attested identities needed by that plan. The
approval gate rejects a missing or drifted required tool before issuing an
approval; plans without this optional field keep their existing behavior.

The recorded GPU process list is a historical observation. A shared service
may be running when a later CPU-only preparation starts. Capture live process
rows immediately before and after and call
`validate_cpu_only_process_transition`: it accepts stable pre-existing process
identities (and memory-use drift) but fails closed on any added, removed or
replaced GPU process. This avoids treating a protected service as a reason to
rebuild the runtime while still proving that preparation did not mutate GPU
occupancy.

Framework imports are not necessarily read-only: DeepSpeed, SGLang, Triton,
Torch and model tooling can create caches before any test or GPU call. Use
`cpu_only_cache_environment` to derive XDG, model, compiler and temporary cache
paths under the exact closure root, create those directories before the first
import, and bind the resulting environment in the execution plan. This keeps
worker image filesystems immutable and prevents unrelated `/root` capacity
from deciding whether an otherwise reusable environment can materialize.
The same contract is available to shell-oriented executors without importing
the module:

```bash
python scripts/qualification_environment_worker.py \
  --cache-environment /workspace/kernel-opt/closures/<closure-id>
```

The command emits one JSON object containing the complete environment mapping;
consumers must create and bind every emitted path before the first framework
import rather than partially reconstructing the mapping.

Framework imports may also write informational logs to stdout before a probe
prints its machine result. Use `parse_final_json_object` to require the final
non-empty line to be one JSON object. Earlier logs remain permitted, while a
missing result, trailing diagnostic or non-object JSON still fails closed.

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
