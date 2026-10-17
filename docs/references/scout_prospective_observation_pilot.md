# Prospective observation pilot, protocol v1

Frozen 2026-10-17 before reading the held admissions' outcomes. This is a
four-slot feasibility pilot, not a sufficiently powered efficacy study. It
does not change the production Scout routing policy or require extra paperwork
for ordinary contributions.

## Question and enrollment

Does choosing the next observation improve **independently reproduced findings
under a declared resource ceiling**, compared with a cheap fixed-native policy?
Do not substitute literal output transcription or existing merged repairs for
new discovery.

Use the existing metadata-only enrollment frame: the first four source-audit
jobs created after `1792182113.3726711`, ordered by `(created, id)`, from:

- `cenkalti/backoff`, `fsspec/filesystem_spec`, `go-viper/mapstructure`
- `pytest-dev/pluggy`, `python-humanize/humanize`, `samber/lo`
- `spf13/afero`, `spf13/cobra`, `spf13/pflag`

The frame was frozen before this protocol and has not been replaced. Its last
metadata-only observation at protocol preparation contained **zero cases**.
Controller downtime is not a negative discovery result. Continue the same frame
when collection is safely available; do not manufacture admissions, reset its
cutoff, fill slots from owner-reviewed history, or pick jobs by successful output.
Missing queue-time bindings, unavailable execution and no findings retain their
slots. Group related revisions and repeated mechanisms; four slots do not imply
four independent discoveries. Record prior owner exposure and possible public
training contamination, without retrospectively deleting inconvenient cases.

## Shared task and evidence

All arms get the exact queue-time source-audit packet, without later Scout
answers, PR outcomes, owner advice added after admission or other arms' outputs.
The task is to propose **at most one** concrete public-contract violation and a
falsifiable reproduction, or abstain. There is no required bug in every packet.
Repair generation and publication are subsequent common owner work, not the
selector's task.

Before any compared call for a case, freeze and hash one observation menu using
only packet/source metadata, not observed behavior. Keep its construction cost.
Do not ask a model to invent or execute a shell command. IDs only index reviewed
observations; unavailable entries remain in the menu with an explicit reason.

| ID | Observation | Deterministic construction / boundary |
| --- | --- | --- |
| 0 | Stop acquiring | No new evidence; not a negative finding |
| 1 | Source continuation | Existing bidirectional continuation rule, one same-commit window, at most 80 lines / 4,500 characters; EOF/failure is retained |
| 2 | Companion test | First same-commit test source in original packet order, one 80-line / 4,500-character window; absent test means unavailable, no oracle-guided search |
| 3 | Native test observation | Frozen repository-native tests associated with that source, if a bounded compatible environment already exists; no model-generated repair, no adaptation silently substituted for the package |

Native action preparation must inspect the repository's contribution/test
contract, pin raw source and imported paths, and record the literal test
selection before running it. If that cannot be done within the preparation
budget, mark ID 3 unavailable. A passing test is not a refuted bug; it may lack
coverage. A failing environment is not a reproduced bug. Do not convert test
stdout into a verdict automatically.

The per-case menu, exact prompts, provider configuration fingerprints and
executor identities must be persisted **before execution**. These case bindings
cannot change the arm list, caps, action semantics or scoring below. If a case
needs a different task/interface, retain an incompatible-case outcome and start
a separately versioned study; do not repair this one in place.

## Arms and common reviewer

Run in this fixed base order, cyclically rotated by case index (0 through 3).
Do not run the favored arm first every time. One realization per arm; this pilot
does not estimate model sampling variance.

1. `source_only`: no acquisition.
2. `rule`: choose ID 2 if available, otherwise ID 1; no model selector.
3. `fixed_native`: ID 3, including its unavailable/failure outcome, with no fallback.
4. `glm_selected`: one `glm-5.3` action selection.
5. `m3_selected`: one `MiniMax-M3` action selection.
6. `glm_sequential`: at most two GLM action selections; after the first observation
   it can choose one *different* action or stop.

GLM/M3 are two available provider configurations, **not a verified cheap/strong
ordering**. Relative prices, compute and capability remain unknown. A future
paper needs independently justified cheap/strong controls and an applicable
published-method comparison, not labels assigned from these pilot outcomes.

Selectors return exactly `{"action_id": integer}`. Use the strict
`scout_shadow_comparison.parse_action_id` interface. No prose, aliases, string
numbers, automatic format repair, retries or alternate provider fallback.
Invalid or repeated choices terminate acquisition, preserving their costs.
This new interface never changes scores from older frozen experiments.

Each arm then gets one fresh common **MiniMax-M3** review of the original packet
and only that arm's returned observations. Do not pass selector prose/reasoning,
earlier reviewer answers, another arm's evidence or oracle labels. The review
returns exactly `{"hypothesis": null}` to abstain, or an object with the sole
key `hypothesis` containing exactly `public_entrypoint`, `contract`, `failure`,
`evidence`, `reproduction`. The four text fields must be nonempty strings of at
most 2,000 characters each. `evidence` is a list of one to four exact objects
`{"observation_id": integer, "quote": string}`; ID 0 means the original packet,
IDs 1–3 mean acquired actions. Quotes must be nonempty literal substrings of
delivered evidence (at most 1,000 characters each). Refuse duplicate/extra JSON
keys or unavailable evidence IDs. Schema validity is assessed separately from
correctness; matching a quote does not prove the allegation. Do not buy extra
reviews to rescue a wrong answer.

`glm_sequential` is a deliberately limited act-observe adaptation, **not** a
reproduction of ReAct or SWE-Search. It omits repair search, editable repository
states, tree/value selection, full tool interaction and solution discrimination.
Do not publish it as an equivalent baseline for those methods.

## Resources and accounting

All arms have the same **300-second decision-path wall ceiling**, including
selector, acquisition and common review; cancelled/failed attempts remain
charged. Individual model requests have a 90-second ceiling, selector output
cap 1,024 tokens and common review cap 2,048. Stop before a new operation if no
time remains. Before the final review, reserve 90 seconds for it; bound each
selector/acquisition by the remaining nonreserved time and decline a new action
when none remains. No extra attempt after a timeout. Native observation is CPU-only,
at most 60 seconds and 512 MiB of additional task RSS; incompatible packages
remain unavailable rather than silently receiving a GPU or larger allowance.

At most two distinct acquired observations per arm; one-shot and rule arms use
at most one. Each delivered source/native observation is capped at 4,500
characters, each prompt at 16,000 UTF-8 bytes, and the full arm at 48,000 prompt
bytes. Record output-limit failures, not truncation disguised as complete
evidence. Reserve one final review; selectors cannot spend its output allowance.

Prepare observations with at most 600 seconds of owner/CPU work per case before
calls. Native tests use task-private roots, no network/install/build, existing
environments and exact selected tests. Preparation failure is an observation,
not permission for unbounded environment repair. Real preparation, source-fetch,
native-process and owner times are separately metered and retained.

Source menus may share immutable bytes and prepared native reports. Charge the
actual one-time preparation once at study level; show its amortization and the
standalone per-arm cost, rather than calling cached evidence free or duplicating
the same execution as multiple independent observations. Randomized ordering
does not create an uncached counterfactual. Keep both physical and logical reads.

Normalize every captured provider envelope before validating answers, including
reasoning-inclusive completion and disjoint Messages cache counters. Complete
final usage, partial usage and missing usage remain distinct. Unknown usage
stops further calls for that case; retain partial results and do not replace it.
Stop the entire pilot after 150,000 observed provider tokens (a post-call stop,
not a hard server-side total-token ceiling); preserve any discrete overshoot.
There are at most **40** planned model attempts across four complete cases: one
review per each of six arms, plus 1+1+2 selector attempts per case.

Equal ceilings are not equal realized or priced costs. Report wall/resource
budgeted outcomes and actual tokens separately. Dollar prices and missing owner
effort stay unknown, not zero. No dollar-cost or fully budget-matched superiority
claim is allowed until pricing/effort and independent budget-matched controls
are available. Include interface preflight costs separately from compared cases.

## Independent check, misses and stopping

Save all arm predictions before adjudication. Remove provider/arm labels and
deduplicate equivalent hypotheses before native checking. Use identical
adjudication for every distinct hypothesis: inspect the documented public
contract and exact package behavior, require a baseline failing reproduction
plus ordinary passing controls, and distinguish mock/internal/exported-source
checks from actual public package execution. Charge this owner work and failures.
Adjudication gets at most 1,200 seconds per case; unresolvable findings remain
`UNRESOLVED`, not silently false or true.

Additionally do one arm-blinded independent source/native audit per case under
the same 1,200-second ceiling, to look for findings missed by all arms. It is a
bounded owner audit, not exhaustive ground truth or an independent human panel.
Report its findings and cost. Recall against this audited reference set is
**audited recall**, not population recall; unresolved cases need sensitivity
bounds, not denominator deletion.

Primary pilot records: independently reproduced distinct findings per enrolled
slot and per actual resource use, audited misses, false/unresolved proposals,
format failures, unavailable actions, setup/decision/adjudication cost, and
delivery outcomes. Report every slot and raw counts. With four potentially
related slots, do not use a bootstrap interval to imply broad generalization.

Publish a community PR only after the normal repository-specific validation,
novelty and contribution-policy checks. Maintainer quota/CI/review waits are
delivery states. Neither an accepted PR nor a rejected draft by itself attributes
success/failure to evidence selection. Do not rush publication for this study.

Expand to a fresh, separately enrolled cohort only if the pilot can acquire
meaningfully different useful observations, retain costs and adjudicate them.
If fixed-native ties or wins while cheaper, stop promoting learned routing;
retain the counterexample and keep the simpler production behavior. Paper work
remains pending novelty, independent replications, representative repositories,
proper method/cheap/strong controls and full budget/recall evidence.

## Interface preflight (not a study result)

Two synthetic literal-ID calls on 2026-10-17 returned valid ID 2 without retries:
MiniMax-M3 reported 258 total tokens / 1.415 client seconds; GLM-5.3 reported
270 tokens / 1.345 seconds. No held case was read. M3 used the installed CLI's
nonstreaming full JSON mode (`--quiet=false`), because its quiet mode strips
usage. Complete envelopes are retained privately. These observations justify
trying the interface, not an efficacy/cost ordering or native correctness claim.
