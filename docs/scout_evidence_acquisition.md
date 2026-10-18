# Evidence acquisition: short entry point

Use this page to choose an existing reading or validation tool. Detailed API
limits, examples, failure records and related-work boundaries remain in the
[complete reference](references/scout_evidence_acquisition_notes.md). That
reference is optional context, not a mandatory procedure or a proven policy.

The live Scout fetcher, optional shadow comparisons and native verification are
different paths. A fetched window, green interface test or published PR does
not establish that evidence selection improves discovery, recall or total cost.

## Choose the smallest useful observation

| Question | Existing entrance | What it does not prove |
| --- | --- | --- |
| Need immutable public source? | `kimi_scout_context.PublicContext` for the live controller; `scout_evidence_acquisition.fetch_source` for a separately declared trial | Complete caller coverage or correctness |
| Need a known location across languages? | `scout_source_window.source_window`; `AcquisitionSession.acquire_window` / `acquire_windows` | Symbol binding or reachability |
| Need Python import/wrapper context? | [Requested wrapper interfaces](references/scout_evidence_acquisition_notes.md#requested-python-wrapper-interfaces) | Arbitrary dynamic Python resolution |
| Missing implementation, literal or companion test? | [Missing-implementation discovery](references/scout_evidence_acquisition_notes.md#optional-missing-implementation-discovery), [literal hints](references/scout_evidence_acquisition_notes.md#cached-python-literal-assignment-hints), [feature-named tests](references/scout_evidence_acquisition_notes.md#optional-feature-named-companion-test) | That the selected code/test establishes the allegation |
| Need a cheap acquisition comparator? | `scout_acquisition_choice`, `scout_bm25_source`; [rule](references/scout_evidence_acquisition_notes.md#visible-frontier-rule-for-fresh-comparisons) and [BM25](references/scout_evidence_acquisition_notes.md#optional-bm25-window-comparator) scopes | An existing published agent method or measured utility |
| Need actual package behavior? | [Native CPU validation](scout_native_cpu_validation.md) and the commit-exact source bundler | Full-platform, serving or performance qualification |
| Need feedback on a displayed PR? | Optional `followup_pr_review_context`; [bounded review reader](references/scout_evidence_acquisition_notes.md#optional-pr-review-feedback) | Complete/latest threads, maintainer approval or current-head correctness |
| Need a reproducible historical Python/Go repair draw? | `scout_repair_draw`; [enrollment limits](references/scout_evidence_acquisition_notes.md#metadata-enrolled-native-admission-2026-10-16) | New discovery, unseen training data or selection-policy benefit |
| Need provider cost observations? | `scout_model_usage`, `scout_shadow_comparison.parse_mmx_message` | Dollar pricing, complete owner cost or budget equality |
| Need to diagnose low activity or owner feedback? | [Refill diagnostics](references/scout_evidence_acquisition_notes.md#operational-refill-diagnostics), [current owner advice](references/scout_evidence_acquisition_notes.md#current-owner-advice-at-delivery-generation) | That a lock/state file proves a process is live |

These are options, not a required tool sequence. Read the relevant reference
section when its restrictions matter; do not load every historical experiment
into ordinary delivery context.

In refill health, `QUEUE_CAPACITY_DEFERRED` means a rotation could not complete
because admission filled (or owned shutdown interrupted it). It is not evidence
that a repository was checked and had nothing new. Such a deferral does not
increment empty-frontier backoff; the queue-capacity guard still applies.
`NO_NEW_EVIDENCE` requires a complete dry rotation. Neither signal establishes
repository exhaustion, candidate quality, fairness or improved PR conversion.

Repair draws default to Python with disjoint production/test directory scopes.
Optional `--language go` classifies `*_test.go` separately from other `.go` files,
allowing co-located directory scopes; explicit `./` selects the repository root.
For example, a predeclared root-level Go frame can use
`--language go --production-prefix ./ --test-prefix ./`. Other traversal/root
spellings stay invalid. Freeze language and scopes before sampling: changed-line
bounds cover the classified language source, not an entire mixed-language commit.
Go metadata eligibility is not a native Go oracle or a memorization-free holdout;
retain missing/non-discriminating historical draws without replacement.

## Keep acquisition and execution claims distinct

- Bind source to the repository and exact revision. For committed native work,
  use the raw-Git-object bundler and check the actual imported source.
- A successful transport is not an available window, a complete contract or a
  passing test. Preserve failures and unavailable actions rather than silently
  choosing a replacement case.
- The standalone trial reader makes one bounded GET with no authentication,
  redirects, retries or fallback. Its socket timeout is not a hard wall deadline.
  The live controller has a separately scoped timeout/reset Git-blob fallback;
  do not apply its behavior or cost accounting retrospectively to a trial.
- Sessions distinguish logical requests from physical reads, including cached
  failures. Cache-hit latency is not an observed uncached counterfactual.
- Keep bounded stdout summaries separate from complete native reports. A sandbox
  transport marked completed can still report a killed or failing child. Check
  exit/termination and cleanup, retrieve/hash the full report before releasing
  files, and preserve output-limit failures. Partial JSON is not a test verdict.
- Test the supported upper-level caller and ordinary controls. A direct internal
  call, mocked successful response or synthetic invalid state may miss the
  actual contract. Distinguish test-method outcomes from failing subtest events.
- For compatibility restoration, first read the promised API and latest issue/PR
  disposition. Old-release success and new-release failure establish a behavior
  change, not that upstream owes restoration. A real consumer may depend on an
  accidental behavior; a downstream migration can be the appropriate fix.
  Preserve maintainer rejection as an outcome rather than purchasing more tests
  for the same rejected premise. A contribution block stops that scope; do not
  work around it through another identity or contact channel.

## Before spending on a comparison

Freeze enrollment, related-revision grouping, available observations, common
review interfaces, stopping rules and independent adjudication before compared
calls. Keep exposed owner examples and interface repairs out of unseen results.

For new queue admissions, `kimi_scout_shadow.enroll_future_source_audits` reads
the first requested source-audit jobs after a predeclared `created_after` cutoff
in a fixed repository frame, ordered by creation time and ID. Freeze those
arguments before admission and persist each returned prefix. It reads neither
answers nor current states, so later failure/no-lead/CI outcomes cannot select a
more convenient case. Missing or mismatched queue-time packet bindings retain
their slots; an incomplete frame is not an empty or successful trial. Raw packet
bodies belong in private run storage, not Git. Owner-context flags and related
revisions still need exposure/grouping review. This reader is enrollment only:
it does not freeze providers, action menus, independent native oracles, stopping
rules, realized costs or prices, and does not make a comparison budget-matched.

Compare no additional evidence, a strong zero-model rule, cheap and strong
models, and an applicable existing method or explicitly labeled adaptation.
A component smoke is not that method's full pipeline. Verify that the selected
native contract actually discriminates before purchasing model comparisons;
retain nondiscriminating/unavailable draws without replacement.

Charge failed selection/acquisition, setup, execution, model input/cache/output
and review effort. Same call/output caps are not equal realized or priced total
budgets. Missing usage/prices/owner effort stay unknown, not zero. Separate
format validity, observed outcome, final label and explanatory correctness;
do not relabel an incorrect answer from its otherwise correct prose.

Normalize and account for every actual provider envelope **before** checking
whether its answer is usable. A complete MiniMax `max_tokens` response can have
final reported usage but no accepted JSON action. `response.ok=false` must not
short-circuit cost collection or be renamed a transport/unknown-usage failure.
Use `summarize_reported_tokens` or `summarize_token_attempts` unconditionally;
the latter keeps complete final usage separate from interrupted partial usage.
Preserve a wrong old report and bind a correction to the original request and
envelope instead of rerunning or silently changing a frozen trial.

The tool-free HTTP backend also retains final numeric usage from a complete,
bounded JSON response when its answer is rejected (for example, forbidden tool
calls or malformed content). The queue still records failure and executes no
tools; usage accounting is not answer acceptance. Invalid/missing counters,
malformed JSON and responses exceeding the body cap do not acquire invented
usage. Transport errors and interrupted streaming observations remain separate.

Keep the selector's job to choosing an observation, then use a common final
reviewer. Requiring only the selector to also solve the case introduces an
answer/interface burden that can obscure acquisition quality. A small
[native-backed negative comparison](references/scout_evidence_acquisition_notes.md#direct-outcome-negative-comparison-2026-10-15)
illustrates this limitation; it does not establish that learned selection works.

A separate [Humanize native-observation example](../examples/scout-evidence-humanize/README.md)
retains a historical repair, native parent/head discrimination and 18 real
common-review calls. Fixed cheap native observations outperformed the learned
choice in its frozen small pilot, with schema drift a substantial confound.
It is exposed development data, not unseen/generalizable or priced efficacy.
Do not require a model to restate a deterministic native fact merely to give
the routing layer another job; keep contract/repair judgment distinct from
structured observation handling and test that alternative in a fresh study.

The [prospective observation pilot](references/scout_prospective_observation_pilot.md)
freezes the existing four-slot future-admission frame, action menu, six arms,
common reviewer, resource ceilings and native adjudication before reading case
outcomes. Its two synthetic integer-ID calls only test formatting/usage capture;
the frame currently has no cases and no efficacy result. Equal ceilings are not
matched realized dollar costs. The optional `parse_action_id` helper rejects
aliases/extra keys without changing legacy trials or live Scout routing.

The [research findings](references/scout_evidence_acquisition_notes.md#research-boundary-2026-10-11)
include unresolved novelty/utility requirements and negative comparisons.
Nothing here authorizes a learned selector in production or a paper claim.

The separately frozen [source-inception v2 results](references/scout_source_inception_pilot_v2_results.md)
are terminal: two convenience slots, 20 attempts, 26,823 reported tokens,
12 valid abstentions and no new discovery/PR. An owner audit found one existing
Humanize defect missed by every arm; valid abstention is not a correct no-bug
verdict. This does not fill the frame-incomplete v1 pilot or authorize additional
slots with v2's unused token allowance.

A [two-repair Python/Go comparison](../examples/scout-evidence-native-facts/README.md)
extends that countercheck with matched native regression/control tests and fresh
public-call observations. Fixed native evidence and M3-selected evidence both
answered all four related states; the latter always chose native and consumed
more model tokens. Direct handling avoided four review calls without changing
those observed values. Construction/setup costs are not zero or fully metered;
this is neither a new-discovery benchmark nor a general adaptive-policy result.

## Published-method comparator boundary

[SWE-Search, ICLR 2025](https://arxiv.org/html/2410.20285v4) is a relevant
reference, not a reproduced baseline here. Its Sections 3.2–3.5 combine editable
repository states, test execution, heuristic tree selection, LLM state valuation
and final solution discrimination. A one-shot evidence ranking prompt is not
that pipeline. Appendix I reports additional search cost; Appendix J compares
five search solutions with five independent base-agent runs. Neither makes our
equal request caps a matched total-cost comparison.

For this project's next experiment, distinguish two questions before enrollment:

- **Observation routing:** keep repair generation and final adjudication common;
  compare a declared, limited adaptation with rules, fixed native evidence and
  cheap/strong model selectors. Label the adaptation, omitted stages and costs.
- **Repository repair:** an actual method reproduction needs its compatible
  execution/tool environment, pinned implementation and full search stages.
  Do not place it in a table against a one-window classifier as an equivalent task.

These are experiment-design decisions, not measured advantages. First show an
improvement over the cheap fixed-native alternative. Known deterministic outputs
should not require model paraphrasing just to justify a learned layer. Retain
unavailable native actions and unknown owner/review costs; do not replace them
with easier cases or retrospectively call them budget-matched.

## Focused offline checks

```text
python -B -m unittest tests.test_scout_evidence_acquisition tests.test_scout_acquisition_choice tests.test_scout_source_window tests.test_scout_shadow_comparison tests.test_scout_mmx_accounting
```

These validate interfaces and injected failure cases, not a real provider's
availability, model quality, native bug discovery or PR conversion. Real-model
and native checks must retain their own execution and cost evidence.
