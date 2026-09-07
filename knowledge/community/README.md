# Community optimization evidence

Community pull requests are discovery evidence, not target-hardware performance
proof. The reusable representation has two layers:

1. An immutable `community-pr-snapshot-v1` bundle containing the pull request,
   complete diff, changed-file metadata, commits, issue comments, reviews,
   review comments and timeline. Every artifact is SHA-256 bound.
2. A reviewed `community-optimization-event-v1` that explains the baseline,
   transformation, removed and added work, applicability, bottleneck shift,
   limitations and source-reported measurements. Every claim points back to a
   snapshot artifact hash and locator.

Generated corpora do not belong in this source directory. Capture them into a
run-owned or external corpus directory:

```bash
python scripts/kernel_opt.py community capture-pr \
  --repository vllm-project/vllm --number 48870 \
  --corpus /path/to/community-corpus

python scripts/kernel_opt.py community sync-repository \
  --repository vllm-project/vllm \
  --since 2026-08-01T00:00:00Z --until 2026-09-01T00:00:00Z \
  --max-captures 20 --corpus /path/to/community-corpus \
  --receipt /path/to/sync-receipts/vllm-2026-08.json

python scripts/kernel_opt.py community validate-corpus \
  --corpus /path/to/community-corpus

python scripts/kernel_opt.py community build-graph \
  --corpus /path/to/community-corpus \
  --repository vllm-project/vllm \
  --repository sgl-project/sglang \
  --repository kvcache-ai/Mooncake \
  --output /path/to/community-graph.json

python scripts/kernel_opt.py community attach-graph \
  --run runs/<run-id> --graph /path/to/community-graph.json \
  --corpus /path/to/community-corpus
```

`sync-repository` searches an explicit, closed update window, classifies
performance changes, regressions, reverts, kernel/runtime work and data-movement
changes, then captures at most the declared PR budget. The receipt records every
matched candidate, budget skip, query URL and whether GitHub truncated search
coverage. Feed its `next_since` into the next scheduled window; never silently
advance a cursor after a failed run.

The CLI reads `GITHUB_TOKEN` first and then `GH_TOKEN`; token values are never
written to receipts or logs. An unauthenticated or exhausted request reports
the GitHub rate-limit resource, remaining count, UTC reset time and optional
retry delay. Do not advance `next_since` or create an empty success receipt on
HTTP failure; retry the same closed window only after the reported reset.

Refresh every PR already referenced by an event under a separate fixed budget:

```bash
python3 scripts/kernel_opt.py community refresh-tracked \
  --corpus /path/to/community-corpus \
  --receipt /path/to/tracked-refresh.json \
  --max-captures 20
```

The receipt lists every tracked PR, budget skip, before/after semantic snapshot,
lifecycle and event requiring re-review. `--dry-run` materializes the bounded
plan without issuing PR capture requests.

Turn newly captured or changed evidence into a bounded review backlog:

```bash
python3 scripts/kernel_opt.py community build-review-queue \
  --corpus /path/to/community-corpus \
  --output /path/to/review-queue.json \
  --max-items 10
```

Coverage is compared with a semantic identity recomputed for both legacy and
current snapshots. Physical manifest migrations therefore do not create review
work. A PR is `UNREVIEWED` when it has no event and `REVIEW_REQUIRED` when newer
semantic evidence is not represented by a current event. Reverts, regressions
and closed-unmerged changes receive explicit priority bonuses because negative
knowledge is a first-class learning input. `validate-review-queue` rejects a
stale or edited queue.

Snapshots preserve the SHA-256 of every exact GitHub response, but deduplicate
all JSON artifacts by evidence-owned semantics rather than volatile fields in
embedded repository objects. Repository stars, fork counts, size and open-issue
counts therefore cannot manufacture a new optimization revision when they recur
inside the PR, review, comment or timeline payload; title, body, state, source
timestamps, labels, base/head commits and actual evidence records still can.

Never treat merge status, a PR author's benchmark, review approval or a method
match as proof that a technique improves the current target. Reverts, closed
changes, regression reports and contradictory reviews remain first-class
evidence and must not be filtered out of the source lake.

The graph also resolves each immutable event against the newest PR snapshot
visible at its temporal cutoff. A newer snapshot does not rewrite old evidence.
Instead, the node enters `lifecycle_review_queue` and is screened out of direct
candidate transfer until a reviewer emits an event bound to the new snapshot.
This prevents an open proposal that was later closed, changed or contradicted
from surviving indefinitely as a positive optimization prior, while historical
graphs still see only transitions available before their frozen cutoff.

Event cards also declare machine-readable hard requirements for compute
capability, explicit parallel width and workload context. Routing fails closed
when those requirements are missing or contradicted, and records the rejected
event plus blockers instead of letting topical similarity create an invalid
candidate. `COMPLEMENTS` means implementation-composable; mutually exclusive
representations must use `CONFLICTS` even when they address the same bottleneck.

## Temporal A/B evaluation

Use `community-eval` to test whether the knowledge layer actually improves the
agent instead of merely producing plausible recommendations. A suite freezes a
cutoff, graph, task packet, hidden oracle, full source revision, model/prompt identity,
arm order and candidate/compile/measurement/per-command/wall-clock budgets.

Tasks may be either a future reference-PR holdout or `PROSPECTIVE_SEALED` work
whose winning solution is genuinely unknown when the packet is frozen. A
prospective oracle binds the seal time, baseline revision and task-packet hash
with `UNKNOWN_AT_SEAL`; it must never invent a PR or silently fill in a solution
after either arm begins.
Validation rejects training
snapshots captured after the cutoff and target PRs already present in the
training graph.

A suite may also bind a cutoff-safe `training_methods` snapshot generated by
`method export-snapshot`. It is materialized only into the augmented arm as
`knowledge/methods.json`; the control arm receives neither graph nor method
cards. Suite validation checks every embedded card against the method schema,
requires its source availability to be no later than the suite cutoff, and
requires the snapshot cutoff to equal the suite cutoff.

When a method snapshot is exposed, the augmented result must include a
`method_realization` receipt. It binds the inspected and selected method IDs,
operator-specific partition/local/combine/finalize mapping, realized candidate
IDs and evidence. The assessor accepts only an actual candidate realization,
a hash-bound structural infeasibility result, or an explicit no-relevant-method
outcome. Merely reading a card and then returning to an unrelated fallback does
not count as learned-method execution.

The suite also freezes a `minimum_material_speedup` greater than 1.0. The
assessor uses this threshold for time-to-first-improvement so a nominal 1.001x
result inside timing noise cannot count as successful discovery.

Every newly materialized trial also receives the same task-bound
`input/frontier_contract.json`. Before editing production source, the executor
must freeze a schema-validated opportunity ranking that covers launch and
materialization removal, a different work decomposition, and dominant-shape or
optional-path specialization. Assessment requires a hash-bound closure for
every ranked architecture and every evaluated candidate. An untested unknown
bound cannot be called dominated, and qualitative prose cannot replace a
numeric domination bound. This prevents an executor from declaring success by
quietly omitting an initially ranked or required branch. Older sealed trials
remain readable because the contract is enforced only when its identity is in
the trial manifest.

In an audited execution, completed `file_change` events provide the ordering
proof: the last change to `evidence/opportunity-ranking.json` must precede the
first change under `source/`. The result's self-reported `proposed_at_seconds`
is retained as descriptive telemetry, but it is not trusted to establish that
ordering. This also rejects a ranking that was initially written on time and
then revised after candidate implementation began.

New benchmark suites should set `protocol.task_packet_contract` to `STRICT_V3`.
V3 machine-checks the complete mandatory intake instead of hiding required
details in prose: computation and tensor roles, shapes/strides/dtypes,
state/mask/boundary semantics, ABI and legal rewrites; weighted execution modes,
upstream/downstream layouts, graph/concurrency/cache semantics; and exact
device/toolchain, power/clock policy, profiler/disassembler availability and
permission for architecture-specific code. It also requires an explicit
`USER_CONFIRMED` record covering operator, workload and hardware. Both V2 and
the optional legacy mode remain readable only for already frozen evaluation
artifacts. Strict packets require workload weights to sum to one, must identify
the same task as the hidden oracle and must match suite hardware.

`materialize-suite` uses the suite's frozen random seed to create every task,
repeat and arm in a hash-bound execution schedule. A control trial withholds the
community graph; an augmented trial contains only the frozen graph. During
materialization, augmented trials also receive a task-specific
`knowledge/prior_shortlist.json`. It fail-closes on compute capability, vendor,
required capability and context gates, uses phrase-boundary problem matching,
excludes generic evaluation/search cards from candidate-generation slots, and
contains at most two events, two transformation/orchestration methods and one
separately budgeted evaluation guard. Community-derived transfer primitives are
accepted only when every provenance event is present in the frozen graph and no
source event postdates the primitive. Its
task, environment, graph and method inputs are hash-bound. This avoids charging
the Agent for repeatedly parsing the full knowledge corpus and prevents fields
such as `windows_prefix` from spuriously matching a `prefix` algorithm. Neither arm
receives the hidden oracle. Each trial also carries a hash-bound JSON result
contract so an isolated executor does not have to guess the reporting format.
The shortlist additionally emits a deterministic routing recommendation. A
hard-gated event or transformation with at least five relevance points must be
consulted before the augmented arm's first source edit; weaker matches remain
deferred until a named local gap. A selected decomposition is first projected to
the smallest state and transitions actually consumed by the target contract.
This prevents both treatment non-realization and over-porting a source PR's
unrelated machinery into a simpler target.
The materialized executor prompt also freezes the filesystem boundary, runtime
adapter and evidence-writing rules shared by both arms.
Execute `schedule.json` in order with networking
disabled. Before execution, materialize the exact historical commit from a local
repository into each trial. The source receipt binds the commit, Git tree and every
extracted file hash, and validation rejects later source edits. On Windows, Git
symlinks are materialized as inert target-text blobs rather than live links so they
cannot escape the trial root; the original Git tree identity remains bound. Write each raw
`community-trial-result-v1`, then assess and compare:

A task may also declare hash-bound `support` files. They are copied identically
to `harness/` in both arms and are immutable executor inputs. Use them for a
baseline adapter, correctness oracle interface and timing driver that contain no
held-out solution. This keeps application-shaped tooling in the suite rather
than polluting the reusable hardware `microbench/` catalog.

Support drivers use a three-way outcome contract: `PASS` and causal candidate
`FAIL` both produce a valid structured artifact and exit zero; only
`TECHNICAL_FAILURE` exits nonzero. This separation prevents an expected
correctness rejection from exhausting the bounded harness-repair budget.

```bash
python scripts/kernel_opt.py community-eval validate-suite \
  --suite /path/to/suite/suite.json --corpus /path/to/corpus

python scripts/kernel_opt.py community-eval materialize-suite \
  --suite /path/to/suite/suite.json --corpus /path/to/corpus \
  --output /path/to/materialized-schedule

python scripts/kernel_opt.py community-eval validate-schedule \
  --schedule /path/to/materialized-schedule/schedule.json

python scripts/kernel_opt.py community-eval audit-task-packets \
  --suite /path/to/suite/suite.json \
  --output /path/to/task-packet-audit.json

python scripts/kernel_opt.py community-eval prepare-source \
  --trial /path/to/materialized-schedule/trials/001-control \
  --repository /path/to/local/source-repository

python scripts/kernel_opt.py community-eval validate-source \
  --trial /path/to/materialized-schedule/trials/001-control

python scripts/community_trial_runner.py \
  --trial /path/to/materialized-schedule/trials/001-control \
  --model gpt-5.6-sol --reasoning-effort high

python scripts/kernel_opt.py community-eval audit-execution \
  --trial /path/to/materialized-schedule/trials/001-control \
  --sandbox-mode AUDITED_UNRESTRICTED

python scripts/kernel_opt.py community-eval assess-trial --trial /path/to/control \
  --require-execution-audit

python scripts/kernel_opt.py community-eval compare \
  --control /path/to/control --community /path/to/community \
  --output /path/to/paired-report.json

python scripts/kernel_opt.py community-eval aggregate-repeats \
  --pairs /path/to/paired-r1.json /path/to/paired-r2.json \
  --output /path/to/repeat-summary.json

python scripts/kernel_opt.py community-eval summarize-schedule \
  --schedule /path/to/materialized-schedule/schedule.json \
  --output /path/to/suite-run-summary.json
```

The assessor derives time-to-first-correct, time-to-first-improvement, best
speedup, architecture-family coverage, held-out correctness, whole-model
speedup and upstream readiness from candidate-level evidence. It rejects stale
hashes, incomplete upstream claims and any trial that exceeds its frozen
budget. A paired report is scoped to one task and repeat; repeated-task
statistics must not be inferred from a single pair.
For a frontier-bound trial, `best_speedup` and time-to-first-improvement include
only the selected candidate. A correctness-passing candidate that violates a
protected per-shape performance guard can remain useful diagnostic evidence,
but a null frontier selection prevents it from being reported as an accepted
optimization. Frontier selection is compared only with other held-out-accepted
candidates: a faster raw screen point is not eligible merely because basic
correctness passed.
`aggregate-repeats` validates every pair and assessment hash, requires unique
repeat indices from one suite/task, and reports arm medians, paired medians,
win/tie counts and an exact two-sided sign-test value for time-to-first-correct.
Its claim boundary remains one repeated held-out task, not cross-task
generalization.
`audit-task-packets` is a suite-authoring check that compares task language with
the hidden oracle and must never be copied into a trial. `summarize-schedule`
keeps invalid and unfinished arms visible instead of silently dropping them
from an A/B report.

`audit-execution` independently parses Codex JSONL rather than trusting the
Agent's final summary. It rejects incomplete turns, missing/invalid results,
network or remote-Git commands, parent/external data paths and a failed-command
lower bound above the frozen technical-repair budget. An audited unrestricted
run is therefore evidence only when its complete transcript passes this gate.
Strict assessment additionally binds the passing audit to the current trial and
result hashes, so editing a result after audit cannot silently enter a comparison.
`community_trial_runner.py` captures stdout and stderr directly and splits the
wall budget into search and finalization. Candidate search stops at the
fraction sealed in `frontier_contract.json` (55% for new trials); a primary
executor that has not returned a result by 70% is terminated and a fresh
low-reasoning finalizer gets only the remaining budget. The runner embeds a
compact inventory of existing candidate, held-out, ranking, closure, method and
hash evidence, so the finalizer may not call tools, edit production source,
repeat screening or create another candidate. It returns a semantic
`{frontier_closure, result}` draft; deterministic runner code writes the
closure, injects its actual hash into the result and appends a commit receipt.
A primary result also receives a fail-closed semantic preflight before it can
bypass that finalizer. The preflight checks evidence identities, candidate and
frontier timestamps, quantified domination, selected held-out acceptance and
arm-conditional realization receipts. During transactional commit, an
unquantified `DOMINATED` row is conservatively normalized to `EVALUATED` (or
`DEADLINE_UNTESTED` when no candidate exists); absent realization records can
only become explicit no-recorded-realization receipts, never positive claims.
A runner-inserted phase marker hashes the complete search transcript; the
auditor rejects a changed prefix, any `source/` edit after that marker, or a
draft/closure/result commit hash mismatch. This turns the finalization reserve
into an execution boundary and transactional commit rather than another prompt
suggestion.

New frontier contracts also seal a qualification checkpoint. The first
screen-correct candidate that reaches the material-speedup threshold must run
held-out validation before the executor spends another candidate slot. A pass
becomes a durable delivery baseline while later architectures remain free to
improve on it. This separates "we already have something shippable" from "the
frontier is fully closed" and prevents optional search from consuming the only
time left for validation.

The runner deliberately performs local result validation instead of weakening
the repository schema to fit a provider's smaller structured-output JSON
Schema dialect. It re-states the manifest's exact trial identity at execution
time and rejects mismatched output. The auditor additionally requires
`result.json` to equal the final transcript JSON, so an out-of-band edit cannot
be laundered by re-running the audit.

Community primitives may also carry hash-bound `experiment_refs` from sealed
single-task trials. These references refine routing and failure modes after a
negative or positive realization, but never upgrade one trial into a general
performance claim. The refined card's `source.available_at` must be later than
the experiment and can participate only in future cutoffs.

Never append later community or experiment evidence directly to an older method
card: that would backdate the new knowledge into historical evaluations. Write a
full method revision under `knowledge/method_revisions/` with the same
`method_id`, a monotonically increasing `revision`, a hash-bound `supersedes`
pointer and a strictly later `source.available_at`. Snapshot export selects the
latest revision visible at its cutoff; current recommendation selects the chain
tip. The loader rejects gaps, duplicate revisions, predecessor path/hash changes
and non-increasing availability. A temporal snapshot binds only the selected
visible revision files; future method IDs, paths and hashes are withheld and
represented only by anonymous counts. Current (non-temporal) recommendation
still binds the complete revision history.

GitHub discovery windows are based on `updated_at`, so they are ingestion and
refresh windows, not held-out eligibility windows. New sync receipts record
both `window_basis=UPDATED_AT` and each candidate's `earliest_public_at` from
the PR `created_at`. A temporal held-out task is eligible only when
`earliest_public_at` is after the evaluation cutoff; a pre-cutoff PR does not
become unseen merely because a review, force-push, close or merge updates it
later.

Before authoring held-out task packets, combine one or more v2 sync receipts
with the exact cutoff graph and method snapshot through
`community-eval build-heldout-queue`. The selector rejects pre-cutoff public
PRs and training-graph sources, deduplicates overlapping discovery windows,
then orders candidates by one-first-per repository/classification group,
discovery score and a frozen seeded hash. It reads discovery metadata only;
diffs, reviews, lifecycle outcomes and hidden reference results are outside the
selection input. `validate-heldout-queue` rehashes every receipt, graph, method
snapshot and corpus index, recomputes the queue and rejects edited priorities.
The queue selects what becomes a task candidate; it does not expose source
patches or count as a trial result.

Run `community-eval build-feasibility-screen` before turning selected queue
rows into task packets. The screen hashes the queue, a versioned metadata-only
policy and an execution profile, then accounts for every selected row as
`ELIGIBLE`, `INFEASIBLE` or `HARNESS_BLOCKED`. Unavailable hardware and missing
harnesses remain visible in the denominator. A policy declared after queue
generation is labeled `POST_SELECTION_PILOT`; only a predeclared policy may
produce `PRESELECTION`. This screen is scheduling evidence, never performance
evidence, and it may use only the repository, title and classifications already
present in the discovery queue—not the held-out diff, review or outcome.

For a formal prospective window, commit a
`community-heldout-preregistration-v1` document together with its referenced
policy, execution profile and optional portable prior-routing snapshot before
the declared cutoff. The optional `evaluation` block freezes both arms,
repeats, randomization, network policy, model identity, strict task contract,
candidate/compile/measurement/repair/revision/wall budgets, material threshold,
all seven metrics and the source outcome-ledger hash. After the commit,
`community-eval anchor-preregistration` verifies every referenced byte stream
through `git show`, checks the commit timestamp and both routing timestamps are
not later than the cutoff, and emits an external validation receipt. A JSON
`declared_at` field by itself is not acceptable proof of pre-registration.

An anchored temporal suite may set `preselection_anchor`,
`training_prior_routing` and `training_prior_outcomes`. Suite validation then
fails closed unless its cutoff and complete evaluation protocol equal the
pre-registration and the portable snapshot binds the exact source-ledger hash.
This makes the pre-registration executable rather than advisory.

After discovery and screening, run `community-eval audit-preselection-chain`.
The chain audit recomputes the anchor, queue and feasibility screen, then checks
that repository coverage, cutoff, receipt schema, selection seed/limit, policy,
execution profile and all denominator counts match the committed
preregistration. Independent artifact validation is insufficient when valid
artifacts can be accidentally combined from different prospective windows.

Use `community-eval meta-analyze` to recursively inventory paired A/B reports.
The summary separates legacy reports, assigned-but-unrealized community arms,
diagnostic realized treatments and primary realized treatments. Its advantage
gate requires at least eight primary pairs across four tasks, a majority win in
time-to-first-correct, no worse than parity in best speedup and no held-out
correctness losses. This prevents attractive legacy or diagnostic runs from
being counted as proof that the knowledge layer improves the Agent.

`community-eval build-prior-outcome-ledger` follows only primary realized pairs
through their hash-bound community assessment and result, attributes deltas to
the event and method IDs that actually changed candidates, and emits routing
feedback. Any held-out correctness loss requires a context guard; directional
up/down-ranking requires at least two observations. Diagnostic, legacy and
assignment-only reports never train this ledger, and one negative observation
does not globally delete a method.

Create a portable, Git-anchorable routing surface without copying local pair
paths into the repository:

```bash
python scripts/kernel_opt.py community-eval build-prior-outcome-ledger \
  --meta-analysis /path/to/community-ab-meta-analysis.json \
  --output /path/to/community-prior-outcome-ledger.json

python scripts/kernel_opt.py community-eval build-prior-routing-snapshot \
  --ledger /path/to/community-prior-outcome-ledger.json \
  --output knowledge/community/prior_routing/routing-v1.json

python scripts/kernel_opt.py community-eval validate-prior-routing-snapshot \
  --snapshot knowledge/community/prior_routing/routing-v1.json \
  --ledger /path/to/community-prior-outcome-ledger.json
```

The portable snapshot contains only aggregate route decisions, the failed task
IDs needed for a context guard and the source-ledger hash. It deliberately
omits absolute assessment/pair paths and raw target measurements. Future
augmented trials still receive the hash-bound source ledger; control trials
receive neither form. A `REQUIRE_CONTEXT_GUARD` event or method is excluded
unless the suite binds a task-specific context-distinction contract that names
every prior held-out failure and an explicit causal difference. The shortlist
is deterministically rebuilt during trial validation, and the assessor rejects
a result that reintroduces a guarded prior by scanning the full graph.
