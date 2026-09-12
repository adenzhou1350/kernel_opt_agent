# Kernel Optimization Agent

For a human review of the framework boundary, execution flow, directory
ownership and contract map, start with [REVIEW.md](REVIEW.md). This README is
the operator quick start; `AGENTS.md` contains mandatory agent policy.

Record the complete delivery cycle separately from performance metrics:

```bash
python3 scripts/kernel_opt.py community-timing init \
  --cycle-id <cycle-id> --task-id <task-id> \
  --minimum-material-speedup 1.02 \
  --candidate-evidence candidate-value-decision.json \
  --output work-cycle.json
python3 scripts/kernel_opt.py community-timing switch-phase \
  --ledger work-cycle.json --span-id environment-1 \
  --phase ENVIRONMENT_SETUP --actor CPU \
  --evidence discovery-receipt.json
python3 scripts/kernel_opt.py community-timing end-phase \
  --ledger work-cycle.json --span-id environment-1 \
  --evidence discovery-receipt.json
python3 scripts/kernel_opt.py community-timing run-phase \
  --ledger work-cycle.json --span-id governance-1 \
  --phase GOVERNANCE_VALIDATION --actor CPU --timeout-seconds 600 \
  --receipt governance-command-receipt.json -- \
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

Start a `PROSPECTIVE_EXACT` ledger when a framework candidate is selected,
before editing production source. `init` atomically opens an active
`BOTTLENECK_DIAGNOSIS` span by default, so timing cannot silently start after
the work. Override it with `--initial-phase` when the first activity is already
known. `--candidate-evidence` validates the immutable selection decision before
the same atomic write creates `FIRST_CANDIDATE_PROPOSED`; missing evidence or a
legacy observation mode leaves no partial ledger. Use `switch-phase` to close
the current span and open its successor at one timestamp, avoiding gaps between
separate end/start commands. The separate `mark` operation remains available
for later milestones.

Record GitHub transitions atomically with their stable URL, observed event time
and immutable event receipt:

```bash
python3 scripts/kernel_opt.py community-timing record-pr-stage \
  --ledger work-cycle.json --stage DRAFT \
  --url https://github.com/owner/repository/pull/123 \
  --evidence github-pr-draft-event.json
python3 scripts/kernel_opt.py community-timing record-pr-stage \
  --ledger work-cycle.json --stage READY \
  --url https://github.com/owner/repository/pull/123 \
  --evidence github-pr-ready-event.json
```

`READY` requires an observed Draft milestone and `MERGED` requires an observed
Ready milestone. When the cycle is actively in `EXTERNAL_WAIT`, the same
transaction closes that wait at the observed PR event time; unrelated
environment, validation, and implementation phases remain active. Do not
backfill missing timestamps from memory or filesystem
mtimes; such a cycle remains `LEGACY_MILESTONE_BOUNDS` and is excluded from
exact candidate-to-Draft and Draft-to-Ready timing.

The ledger uses non-overlapping primary wall-clock spans for community research,
bottleneck diagnosis, implementation, compile/measurement, correctness,
performance, whole-model validation, upstream packaging, environment setup,
governance validation and external wait. Use `ENVIRONMENT_SETUP` only for
dependency/toolchain/runtime repair, and `GOVERNANCE_VALIDATION` only for
contracts, authorization, evidence closure and policy checks. The summary
reports their seconds and their share of attributed active work. If neither
phase was recorded, that ratio is `null` with
`NOT_SEPARATELY_RECORDED` rather than a misleading zero. Do not retroactively
reclassify legacy spans.

Select canonical ledgers across the autonomous lanes without scanning or
guessing from chat transcripts:

```bash
python3 scripts/kernel_opt.py community-lanes validate \
  --topology knowledge/community/lane_topology.v3.json
python3 scripts/kernel_opt.py community-portfolio \
  --manifest /path/to/portfolio-manifest.json \
  --output /path/to/portfolio-report.json
```

Portfolio report v6 exposes the delivery funnel, freshness-attested action
ownership and phase-time totals for only the explicitly selected, hash-bound
`PROSPECTIVE_EXACT` ledgers. Active spans share one observation time.
Environment/governance overhead is kept separate from external wait, and the
report states that parallel candidate spans may overlap: it is not a wall-clock
or labor-time measure. Root-wide historical instrumentation debt remains a
separate audit and is never backfilled or hidden by the selected portfolio.

An immutable ledger's `ACTIVE` span is historical state, not proof that work is
still current. Only a valid, unexpired `community-action-attestation-v1` with
an explicit owner enters `active_delivery_queue` or
`needs_user_action_count`. Missing, expired, resolved and superseded states stay
visible in `delivery_action_inventory` without creating current work. Pass each
current attestation with `--action-attestation /path/to/action.json`.

For a bounded command, prefer `run-phase`: it runs the exact argv without a
shell, writes an immutable wall-time/exit-status receipt, and closes the span
on success, non-zero exit, launch failure, or timeout. A passing command receipt
is not correctness or performance evidence.
When a governed worker already produced an immutable terminal receipt, use
`import-phase-receipt` to bind its exact start/end timestamps instead of
reconstructing wall time. The prospective ledger must already predate the
receipt; optional duration-field reconciliation rejects inconsistent receipts.
Importing timing does not validate the worker result or change its outcome.
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
historical timing.

This repository turns GPU-kernel optimization into a reproducible loop driven
by workload contracts, hardware evidence and falsifiable microbenchmarks.

It deliberately contains no application-specific algorithm, workload or
performance result.  Hardware facts are separated from empirical measurements;
measurements are keyed by device and software environment.

The workflow has two lanes. Fast discovery writes and repairs a diverse set of
run-local production candidates, then uses cheap anchor/edge screening and
successive halving. Only survivors enter the existing evidence-closed
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

After a correct discovery baseline is present, manage the production-candidate
portfolio with:

```bash
python3 scripts/kernel_opt.py candidate init --run runs/<run-id> --if-missing
python3 scripts/kernel_opt.py candidate add --run runs/<run-id> --spec candidate-spec.json
python3 scripts/kernel_opt.py candidate run --run runs/<run-id> --candidate-id <id>
python3 scripts/kernel_opt.py candidate promote --run runs/<run-id> --candidate-id <id>
```

Discovery requires 6--12 candidates across at least four architecture families
by default. The default discovery budget is two hours overall, twenty minutes
per candidate and eight technical repairs per candidate; expiry stops further
measurement for plan review. Candidates are ranked by weighted screening gain
and at most two are promoted by default. Its timing is a routing signal, not
production acceptance evidence.

When a rebase, DCO amendment or other commit-metadata update changes the commit
ID after validation, compare the committed trees before repeating expensive
source qualification:

```bash
python3 scripts/kernel_opt.py source-supersession \
  --repo /path/to/repository \
  --validated-ref <validated-commit> \
  --replacement-ref <new-commit> \
  --output source-supersession.json
```

An identical tree permits reuse only of source-tree-scoped evidence. Runtime,
build artifact, workload and hardware identities still have to be rebound or
revalidated. Any tree change fails closed and lists the paths that require
source requalification.

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

Use `upstream-delivery-inbox-v5` before an AI-assisted Draft is exposed as a
publication action. In addition to v4 freshness, it accepts a hash-bound
`upstream-delivery-author-accountability-v1` record for the exact candidate
commit. Until the named human submitter attests that every changed line was
reviewed, relevant tests were rerun, the change can be defended, AI assistance
is disclosed, and the repository's commit-attribution rule is satisfied or not
applicable, the candidate is routed to `COMPLETE_AUTHOR_ACCOUNTABILITY` instead
of `OPEN_DRAFT`. The attestation is a responsibility boundary, not a substitute
for correctness or performance evidence.

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

The run is intentionally blocked until `hardware_evidence.json` archives exact
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
`microbench/`, `schemas/` or the skill references.

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

## Atomic cohort claims

`scripts/community_atomic_claim.py` is a non-launching transactional primitive
for consuming a frozen cohort schedule once and in order. It records session,
entry, dispatch-identity and terminal receipts in SQLite, preserves ambiguous
crash windows without automatic retry, and validates stored receipt lineage on
every transition. Pure identities and schedule validation live separately in
`scripts/community_claim_contracts.py`.

This primitive does not authorize or start a process. A dispatcher must still
validate canonical pre-GPU, execution-contract and semantic-approval artifacts,
obtain a durable no-rollback store epoch, attest the live process and GPU lease,
make the final expiry decision immediately before child creation, and bind a
successful terminal state to validated correctness and observation evidence.
Reusing an epoch after restoring or replacing the database is outside SQLite's
trust boundary and must be prevented by the external epoch issuer.

Before an atomic claim store can be consumed, validate a versioned deployment
with `scripts/community_claim_store_deployment.py`. The deployment binds one
canonical database path, host boot identity, dispatcher executable and an
externally issued no-rollback epoch. Epoch replacement must form an explicit
predecessor chain, and both the declared Git commit and current worktree bytes
for the schemas, validator and claim implementation must match. Passing this
gate means only `ready_for_atomic_claim=true`; it never grants GPU dispatch.

## Evidence classes

- `FACT`: queried or statically verified.
- `MEASURED`: backed by immutable raw samples.
- `INFERRED`: derived from stated facts and measurements.
- `HYPOTHESIS`: awaiting a discriminating experiment.
- `REJECTED`: falsified or measured with an invalid method.

See `skill/kernel-optimizer/references/` for the optimization protocol.

## Upstream delivery package

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

## Candidate value gate

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
protocol/API changes at Draft even when their focused tests pass. Its review
cost formula is explicit and policy thresholds are supplied by the run; it is
a routing decision, not performance proof. A confirmed path with an unknown
ceiling requests `QUANTIFY_WHOLE_WORKLOAD_CEILING`; when the Draft minimum is
already complete and no permanent API or protocol variant is added, it may
instead recommend opening an honestly scoped Draft while that ceiling is
quantified. Callers never have to invent zero or a favorable estimate merely
to pass the schema.

## Qualification failure routing

Classify a stopped qualification attempt before rejecting its candidate:

```bash
python3 scripts/kernel_opt.py qualification-route --print-template \
  > qualification-attempt.json
python3 scripts/kernel_opt.py qualification-route \
  --attempt qualification-attempt.json \
  --output qualification-route.json
```

The route distinguishes an exact-source candidate assertion failure from
image, toolchain, dependency, ISA, import-identity and platform failures.
Environment failures retain the candidate and consume a frozen technical-
repair budget. Exhausting that budget stops dependency chasing without
turning the event into a correctness rejection. An official workflow that
intrinsically builds native code cannot run under a no-build contract: either
authorize that build or use a pinned prebuilt closure. Tests against an
unverified imported source are invalid evidence, not a pass or candidate
failure.

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
