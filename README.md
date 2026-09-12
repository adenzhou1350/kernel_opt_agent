# Kernel Optimization Agent

For a human review of the framework boundary, execution flow, directory
ownership and contract map, start with [REVIEW.md](REVIEW.md). This README is
the operator quick start; `AGENTS.md` contains mandatory agent policy.

This repository turns GPU-kernel optimization into a reproducible loop driven
by workload contracts, hardware evidence and falsifiable microbenchmarks.

It deliberately contains no application-specific algorithm, workload or
performance result.  Hardware facts are separated from empirical measurements;
measurements are keyed by device and software environment.

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
python3 scripts/kernel_opt.py upstream-prior-work prior-work.json
```

Run this bounded prior-work gate before implementation, not at publication
time. It distinguishes an exact open predecessor, an already merged change, a
technical rejection, an unknown closure, an inactivity-bot closure, a feature
overlap and adjacent work. Exact open or merged work blocks a competing Draft.
Use relationship `PREREQUISITE` when a standalone candidate requires another
upstream PR. An open prerequisite keeps cheap implementation work available
but blocks publishing a stacked branch. After merge, rebase onto current
upstream and repeat source-bound focused qualification before opening the
standalone Draft; a closed-unmerged prerequisite routes to replanning.
An inactive exact predecessor may be revived only after its PR number is
attributed and coordination is planned or posted; the decision never claims
the semantic relationship was inferred by code. Those relationship labels are
human-reviewed inputs bound to the observed GitHub query snapshot. This lets a
lane reuse or contribute to old work without counting the same core idea as a
new discovery.

After the prior-work decision, record GitHub state and obtain the next
owner/action with:

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

After the targeted follow-up is actually posted, switch the record to
`upstream-review-handoff-v2` and bind its timestamp, requested reviewer,
pull-request comment URL and immutable receipt SHA-256 in `follow_up`.  The
router then returns `TARGETED_FOLLOW_UP_SENT_WAIT_FOR_RESPONSE` instead of
recommending the same message again.  A later topic-channel escalation remains
possible at the separately frozen escalation age; the receipt never authorizes
either external action.

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
facts and neighboring-device values are forbidden.

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

## Evidence classes

- `FACT`: queried or statically verified.
- `MEASURED`: backed by immutable raw samples.
- `INFERRED`: derived from stated facts and measurements.
- `HYPOTHESIS`: awaiting a discriminating experiment.
- `REJECTED`: falsified or measured with an invalid method.

See `skill/kernel-optimizer/references/` for the optimization protocol.

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
