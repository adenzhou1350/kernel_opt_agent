# Observable next-evidence acquisition

## Live controller transport (separate from the trial helper)

`kimi_scout_context.PublicContext` normally reads immutable raw source. On a
connection reset or timeout only, it makes one GitHub Git-blob API request for
the blob already bound by the public repository snapshot. It validates bounded
base64 content, declared size and the Git blob SHA-1 before UTF-8 decoding and
caching. API authentication stays opt-in and is never sent to the raw host.
HTTP errors, TLS verification failures, unknown transport failures and oversized
responses do not trigger this fallback; it does not change certificate checks,
repository visibility checks, queue decisions or model privileges.

The source cache records `transport=git_blob_api` when used, while evidence keeps
its original immutable source URL. Count both attempted reads when accounting
for acquisition costs; a fallback is not free evidence. This operational path
does not modify the single-GET trial helper described below or establish any
improvement in candidate quality or PR conversion.

`scripts/scout_evidence_acquisition.py` is an optional standard-library helper
for fresh shadow experiments. It does not replace the live Scout fetcher, decide
candidate quality, launch code, or write files. A caller supplies already
sanitized public targets and enforces its cohort repository/revision constraints.

## Caller evidence before runtime preparation (exposed development case)

An existing DeepSeek V4.1 WO-A lead repeated the `dispatch(tokens=0)` division
concern through three paid source-audit/follow-up stages. All three retained
unknown production reachability and requested external references; their packets
still lacked the actual output-projection caller. The complete pinned
[`dsv41_o_proj` wrapper](https://github.com/vllm-project/vllm/blob/5fd62688ffe995c0c11c8708fe51dbff53235b74/vllm/models/deepseek_v41/nvidia/ops/o_proj.py)
requires `1 <= o.shape[0]` before fusion. The kernel's
[`get_warmup_keys`](https://github.com/vllm-project/vllm/blob/5fd62688ffe995c0c11c8708fe51dbff53235b74/vllm/models/deepseek_v41/nvidia/ops/fused_wo_a.py)
also enumerates from one. Both raw blobs are unchanged from the original
81f7c695 lead revision. This supports deferring that reachability premise without
building CUDA or changing the deliberately excluded internal input; it does not
prove the complete kernel correct or rule out a different caller.
The three retained receipts report 20,656 total tokens; acquisition/preparation
and owner review are outside that token sum, and cache usage/prices are unknown.
That is historical expenditure, not a measured saving from the routing change.

At the time of this observation, the live controller's external code-search
branch was eligible only for
`needs_context`, whereas these three analyses were labelled `lead` despite
requesting missing references. Same-file lexical references do not establish an
external consumer. This identifies a bounded acquisition failure to test, not
evidence to automatically relabel every lead, search all callers, relax source
budgets or promote a new policy from one known case. The owner used the existing
raw-Git packet helper for complete definitions and recorded a deferred decision
with explicit reopening conditions; original model results were not rewritten.
No new model/native call, prospective enrollment, measured saving or PR claim
was made by this source check. Future comparisons must charge all three prior
calls and the caller acquisition, not count the helper exception as a finding.

## Research boundary (2026-10-11)

Evidence selection is a hypothesis, not established novelty. Primary work
already covers several broader claims:

- [FixedBench](https://arxiv.org/html/2605.07769v1), sections 2–3, tests
  resolved, partially fixed and novel issues. Explicit abstention instructions
  can suppress unnecessary edits but increase missed repairs on partial fixes.
- [Active-SWE](https://arxiv.org/html/2608.04682v2), sections 3–4, evaluates
  proactive discovery without issue reports, across languages, using recorded
  repairs and test-supported potential discoveries.
- [Abstain and Validate](https://arxiv.org/html/2510.03217v2), sections 3–4,
  already combines bug selection, executable checks and model patch validation.
  Its appendix C.4 also discusses repair/review cost and unrepaired-bug value.
- [Performance-PR validation study](https://arxiv.org/html/2610.03969v1),
  sections 3 and 6, examines reported optimization evidence and trade-offs;
  [Merged, Not Measured](https://arxiv.org/html/2609.37985v1), sections 3 and 7,
  independently re-executes performance claims. Merges and benchmark mentions
  are not sufficient performance outcomes.

### Further related-work check (2026-10-16)

[Humanize](https://arxiv.org/html/2610.08900v2), sections 6 and 8, describes
independent builder/reviewer judgment and reports observational deployment
evidence. It explicitly discusses environment-dependent verification failures,
review tails and unmeasured round costs. Independent review or a feedback
knowledge base is therefore not, by itself, a new contribution here. This is a
focused reading of the method/limitations, not reproduction of its applications.

[HMA](https://arxiv.org/html/2610.13494v1), sections 3.4 and 4.1 and appendix C.3,
alternates native agents with context resets, a per-session experiment cap,
persistent candidates and reserved final-review time. Its main evaluation is
MLE-bench, not OSS bug triage; it cannot establish our PR yield. Some reported
gains use the mean of the constituent single-agent results: distinguish that
reference from the stronger constituent, and matched wall time from equal tokens
or dollars. Do not call independent stateless prompts an HMA reproduction.

For a future OSS adaptation, record every changed task, tool, stopping and review
interface. Separate an existing-method pipeline comparison from an acquisition
ablation: hold session/reset and final-review policy fixed when estimating the
effect of choosing evidence. Conversely, compare reset/alternation with the same
evidence options when estimating that workflow's effect. Include the stronger
single-agent baseline, startup/handoff/final-review costs and failed native
admissions. These are proposed controls, not an executed comparison or proof
that our narrower research question is novel. The closed unavailable/negative
cohorts remain unchanged; do not recycle exposed cases into a fresh test split.

### Test volume is not evidence value (2026-10-18)

[Rethinking the Value of Agent-Generated Tests](https://arxiv.org/html/2602.07900v2),
sections 2, 5 and 6, studies six models' SWE-bench Verified trajectories and
prompt interventions on four models using mini-SWE-agent. Changing how often
agents write tests did not significantly change final outcomes in that setting;
interaction costs did change. This does not establish that native verification
is useless, or isolate which observation to acquire next. Section 6.2 already
proposes feedback-adapted testing policies and matched-budget comparisons.
Therefore neither adaptive testing nor measuring its cost is a new idea here.

This changes our experimental priority: distinguish a useful observation from
the decision to select it. A fixed, contract-relevant native check is the direct
comparator for a learned selector; an arbitrary first test is not an adequate
stand-in. Keep generated-test assumptions separate from independently supported
API contracts. Compare unchanged source, the candidate, and relevant passing
controls with the same witness before crediting a repair. Successful test
execution alone does not establish an oracle, consumer reachability or PR value.
These are design inferences, not measured selector gains or a new trial.

For a complete-system comparison, [Agentless](https://arxiv.org/abs/2407.01489v2)
provides localization, repair and validation without model-directed future
actions; [SWE-Search](https://arxiv.org/abs/2410.20285v6) instead uses MCTS and
iterative feedback. Our source-only prompts or three-action menu reproduce
neither system. Pin and run the applicable original implementation, or label
the adaptation and its differences; do not attach a published method name to
a smaller passing baseline. Full-system comparisons and single-action ablations
answer different questions and need separate accounting.

[Agent Retrieval Bench](https://arxiv.org/abs/2607.24882) already evaluates
workflow-conditioned file retrieval, selective abstention, logged acquisition
and retrieval-seed interventions. Its closed-tool runner explicitly forbids
test execution and repairs. It is a useful localization comparator, not an
oracle for independently reproduced defects or repair success. Finding a more
relevant file, or adding a next-read policy, is not a new contribution by itself.
[LogDx](https://github.com/eyuansu62/LogDx) also compares reduced-log evidence in
single-shot and agent-loop diagnosis, including context-provider and diagnoser
costs. Its results are author-reported, not our replication. A new utility study
must distinguish its outcome, available executable observations and total-cost
accounting from both systems; do not rename a small source menu as either method.

The completed [two-slot diagnostic](scout_source_inception_pilot_v2_results.md)
does not justify expanding selector complexity or repeating exposed cases.
Improve native admission and executable contract coverage in ordinary delivery
first. Reopen an efficacy trial only with fresh groups, comparable action
capacity, independent outcome checks and measured total-cost components. The
existing Scrouting discussion below separately cautions against attributing a
verified handoff's benefit to routing.

Consequently, a model hierarchy, proactive PR search, abstention, or collecting
failed optimizations is not by itself our contribution. A remaining **unproven**
question is whether choosing an executable next observation improves verified
decisions at the same total cost without increasing missed real defects. This
is a research question, not a claim that the literature leaves it unanswered.

Before another utility trial, use runnable contracts rather than arbitrary
file prefixes. Development controls should include a real unresolved defect,
an already-correct case, and an incomplete fix that still needs work. Verify
each expected behavior independently; a green generated test is not its oracle.
Keep known controls separate from fresh evaluation cases, and keep a repository's
related revisions together when splitting data. Retain unavailable environments
and unresolved judgments in the denominator, not as correct abstentions.

One exposed development control now uses the real AnyIO portal regression in
[PR #1410](https://github.com/agronholm/anyio/pull/1410), not a copied implementation.
The AI-assisted tests were already exposed through that PR, not independently
blinded labels. With the same committed `test_cancel_during_completion`
tests from `48547204e8680c296e2ae6b813964c85414085bb`, Windows CPython 3.12 runs
sync/async callables on asyncio, winloop, eager asyncio and Trio:

| Source state | Pass | Fail |
| --- | ---: | ---: |
| Baseline `c326ee1f601f8c142db984299ce00efce36e0ce9` | 0 | 16 |
| Authored partial: fix result completion only, retain the exception race | 8 | 8 |
| Full repair `48547204e8680c296e2ae6b813964c85414085bb` | 16 | 0 |

The partial state is a deliberate development mutation, not a historical upstream
revision. Its eight remaining failures are exactly the exception cases; a
success-only oracle would falsely accept it. The real package, with only the
declared completion edits and shared committed tests, runs in separate processes;
no new model calls or new PR result
are implied. This calibrates test discrimination only. Keep these exposed related
states out of a fresh evaluation split and require independently verified native
contracts for new cases; neither this control nor green callback plumbing proves
that selecting evidence improves decisions, recall or cost.

A later natural-pair feasibility check used packaging's upstream
[filename repair](https://github.com/pypa/packaging/commit/ae9d39c13b5f5485b6295eb100b08ef9c3dde852),
selected by a frozen first-eligible-fix rule before cloning. The same upstream
five filename parameters/assertion ran against complete real parent/head packages
in fresh offline CPU containers: parent 1 failure/4 passing controls; head 5 pass.
The adapter invoked the unchanged test function directly, not full pytest
collection. These are two related states of **one** repair, not new discoveries.

Twelve MiniMax-M3 calls compared no-added-source reflection, BM25 reflection and
model-selected source under the same call/prompt/output ceilings. Reported total
usage was 50,295 input/cache/output tokens; dollars and owner cost remain unknown.
Five of six final records failed the frozen format/quote interface. The sole
interface-valid baseline answer incorrectly inferred that Python `^...$` plus
`re.match` guarantees complete-string matching; the native trailing-newline case
disproves that assertion. Getting relevant source was insufficient in this case.

The task itself also mixed a positive requirement question with labels for an
alleged violation. Therefore **do not rank policy accuracy from this group**, strip
fences/rescore its answers, or call it selector benefit. Before new inputs, align
an explicit failure proposition with the verdict direction and preflight the
response interface on exposed controls. Include a separately costed native
semantic probe as a candidate observation, not only more source windows. This is
a next-experiment hypothesis, not evidence that a native-action policy wins.
Public-history memorization is unknown; strong/cheap-model rank comparisons,
complete existing-agent methods and equal priced total budgets were not run.

An **exposed development** follow-up used an explicit alleged-acceptance claim,
strict unfenced JSON and IDs pointing to supplied evidence instead of copied
multiline quotes. Four MiniMax-M3 calls (5,133 reported tokens) all met that new
interface. Fixed source-only review missed the parent's acceptance; fixed
source-plus-native review classified both related states correctly. This is not
a selection policy, a new repair group, or a budget-matched utility comparison.
Do not attribute the interface change to any one prompt edit or rescore old runs.

Correct verdicts still carried false explanations: the source-plus-native parent
answer said `Path` typically strips trailing newlines, and the correct source-only
head verdict incorrectly attributed rejection to `$` alone. Audit semantic claims
separately from final labels. The stdlib control below directly exposes `Path.name`,
`match` and `fullmatch`; it does **not** replace the real-package parent/head check.
No generated code or external package is imported. Windows CPython 3.12.13 and
Linux CPython 3.12.10 agreed on all four observations; the two control tests passed
on both. Preserve runtime identities when transferring this control. These known
inputs remain development data; prospective action selection and cost/recall
benefits are still unproven.

```text
python -B examples/python_filename_semantics.py
python -B -m unittest tests.test_python_filename_semantics_control
```

Compare no additional evidence, a strong zero-model acquisition rule, a cheap
model, a strong model and an applicable existing agent method. Charge selector,
failed acquisition, downstream review, native setup/execution and owner effort;
unknown prices stay unknown. Report confirmed defects retained/missed alongside
false changes and cost, not only precision among the survivors. Zero discovered
defects cannot establish recall. Stop or simplify the selector if extra spending
does not improve verified decisions; ordinary PR work need not wait for a paper.

A subsequent frozen-rule-selected historical Toolz repair,
[`interpose([])`](https://github.com/pytoolz/toolz/commit/d2eba0374a452c2b18fe188b04527e22bda3548c),
provided another independently executable parent/head group. Complete exact-source
packages ran the same two upstream test functions through a stdlib adapter:
parent one empty-call error/one passing nonempty control; head two pass. This
does not claim full pytest collection. Both initial source windows contained the
complete implementation; the visible repair was not hidden to manufacture value.

Eleven MiniMax-M3 calls used 16,117 reported input/cache/output tokens under frozen
caps. Source-only reflection missed the parent; its head answer was invalid JSON
and received no replacement final call. The selector chose no added observation
for either state, missed the parent and classified the head correctly. Fixed
native observation classified the head correctly. On the parent it corrected the
semantic explanation to an exception during the call, but still emitted the
opposite verdict. That contradiction remains a wrong label, not a success repaired
from its prose. Two added native observations took 4.579 seconds including their
session lifecycle; measured model-client time was 23.748 seconds, not total setup,
owner or priced cost. All CPU sessions were released.

This group demonstrates no selector benefit and does not justify adding one to
production. Before buying another comparison, preflight verdict/observation
consistency on exposed controls; do not repair or rerun these answers as fresh
results. Public-history memorization, recall, cross-group utility and equal-priced
budget superiority remain unknown. Neither this historical repair nor a format
failure is a new PR outcome.

A four-call **exposed development** preflight replaced allegation polarity with
direct call-outcome labels, with one stateless call for each source-only and
source-plus-cached-native parent/head condition. It used 5,668 reported
input/cache/output tokens and 7.547 seconds of model-client time; no new native
execution or retries. Three answers were format-valid and outcome-correct.
The source-only parent answer exceeded its 400-character reason cap and still
paired the wrong empty-iterator label with a correct call-time exception
explanation. Do not repair that label from its prose. The native-supplied head
answer cited source, so supplying an observation does not prove reliance on it.
This one exposed group supports neither automatic verdict routing nor selector
utility; the direct-label interface did not eliminate the contradiction. Keep
format, factual outcome and explanation checks separate, and retain invalid
outputs and all incurred costs in future comparisons.

A later metadata-only draw fixed the latest 60 first-parent nonmerge commits of
`more-itertools/more-itertools`, selecting the first small fix/bug-titled change
with production Python and test paths. Its initial depth-100 clone exposed only
13 apparent records, including a shallow-boundary merge presented as parentless.
That preliminary empty draw was retained as incomplete, not a no-repair finding.
Bounded history acquisition completed the same sampling frame; a subsequent
300-record mixed-merge traversal cap also stopped before the frame was complete.
Both setup failures and acquisition costs remain part of this pilot. Do not
hide them or count the completed draw as a second independent admission.

The first eligible change was
[`4bd0bd876`](https://github.com/more-itertools/more-itertools/commit/4bd0bd876273a8ff2171352c937b91a8c053d00b),
titled a `distinct_permutations` fix. Its production-file changes were docstrings,
not an executable repair. The same unchanged head `DistinctPermutationsTests`
class on complete exact-source parent/head packages passed six tests per arm,
with no errors or skips, using Python 3.12.10's real unittest runner in isolated
offline CPU sessions. Both sessions were released. This is selected-class
evidence, not full-repository correctness or proof of universal equivalence.
The predeclared oracle did not discriminate, so the selected group was retained
and **zero model calls** were purchased; no replacement case was drawn. A fix
title and test churn do not establish a faulty/fixed behavior pair. This is an
admission negative, not a selector win, measured counterfactual savings, recall
or PR result. Strong-provider/existing-agent and total-cost comparisons remain
unfinished; keep this group outside future unseen evaluation inputs.

An additional **exposed development** control now comes from our own
[Pyodide request repair](https://github.com/fsspec/filesystem_spec/pull/2293).
The first submitted head `f77a724` passed 65 native tests and nine real-browser
direct-request checks, but a subsequent actual `HTTPFileSystem.put_file` check
still uploaded a generator's repr instead of file bytes. Both POST/PUT methods,
filesystem/BytesIO sources and binary/empty inputs failed the round-trip
expectation. Adding more direct JSON assertions would not expose this remaining
consumer-contract gap.

The follow-up `c851dfe` consumes finite iterator chunks as Blob parts. In the
same Pyodide 314.0.7/CPython 3.14.2 module-worker runtime it satisfies 19 loopback
expectations: the original nine, two iterator checks and eight actual upload/read
round trips, including progress count and caller stream ownership. The complete
native test file reports 67 passes; the same new tests on the partial head yield
two failures and 65 passes. Native mocks test conversion-call protocol, whereas
the browser checks use real Blob and synchronous XHR. The implementation buffers
finite chunks and does not qualify streaming, large-upload memory or cloud services.

This is one related, owner-exposed partial/extended-repair group, not fresh
prospective selection labels, nineteen independent discoveries or a comparison
against a model/rules policy. No new model calls were used; owner/setup cost was
not fully measured. Keep both revisions together and outside fresh evaluation
splits. The case motivates including a real upper-consumer observation as an
available action, not a claim that a selector will choose it or improve recall,
total cost or PR conversion.

`fetch_source(url)` accepts only HTTPS `raw.githubusercontent.com` URLs with an
exact 40-character commit and a safe path. Percent-encoded targets are excluded
in this initial interface. It makes one GET, without authentication, redirect,
retry, model call, or fallback. A response is source text only on HTTP 200,
complete bounded UTF-8 body. HTTP failure bodies remain digest/accounting data,
not source evidence. A short body inconsistent with Content-Length fails.

For success and failure it records HTTP status when observed, application body
bytes returned to the reader, digest of that observed body/prefix, completeness,
error class, and client elapsed time. A read-budget sentinel permits at most one
byte over the declared cap. These are not total network/TLS bytes; a connection
failure may have unobserved traffic. The 20-second default is a socket-operation
timeout, **not a hard total-wall deadline**. Experiments needing a hard deadline
must separately enforce and account for one, including incomplete observations.

`AcquisitionSession.acquire(url)` shares an identical response across arms,
including failures, for at most 64 requests. It reports logical requested GETs
and actual GETs separately. A cache hit incurs no additional observed GET cost;
the original latency is not a measured counterfactual uncached latency.
`costs()` includes failed/invalid targets and explicitly leaves model/owner
cost, pricing, wire bytes, and counterfactual latency unmeasured.

`AcquisitionSession.acquire_window(url, start_line=...)` composes that reader
with the existing bounded line selector. Its result separates `acquisition`
metadata (`FETCHED` on transport success) from `window` (`ACQUIRED` only when
the selected text is available). The full fetched body is not returned to the
consumer. Invalid selectors fail before a GET; HTTP failures and beyond-EOF
windows remain distinct, with original physical/cache costs preserved.

A task-local trial adapter confused those two success labels and consequently
gave reviewers no added text despite a successful GET. That comparison is an
implementation failure, not evidence against source selection or a model.
The composed-interface tests check that fetched text actually reaches the
window consumer; they do not establish that a model uses it correctly or that
PR yield improves. Keep affected trial answers immutable and use fresh inputs
for a new quality experiment, not repaired answers as prospective results.

Use this in a newly declared protocol. Historical pilot records remain immutable:
re-fetching their missing target does not recover the historical failure cost or
turn development examples into a prospective cohort. Source acquisition alone
does not establish native correctness, independent adjudication, PR conversion,
miss rate, dollar savings, or superiority to a strong-model/rules comparator.

`scout_acquisition_choice` is a small optional trial adapter. It restricts choices
to safe immutable URLs in the case's repository, preserves original catalog order
and implements the first-file continuation baseline. An issue-only/empty catalog
is `UNAVAILABLE`, an explicit null/null selector answer is `ABSTAIN`, and a malformed
answer is `INVALID_SELECTION`; none spends a GET. A selected EOF or HTTP failure is
`FAILED`, with the session's original transport/window verdicts and costs retained.
No target or case is substituted. A successful window is `ACQUIRED`, not a claim
that the reviewer used it. Programming/budget errors still raise. The adapter does
not invoke a model, change live routing, or establish budget-matched utility.

For new trials, `first_clipped_or_continuation` is a separate zero-model baseline:
restore the first eligible clipped file from its original `start_line` (or 1 when
absent); if none is clipped, retain first-file continuation. Catalog-only clipped
entries qualify, and duplicate URLs retain their first metadata entry. The same
one-GET/window cap applies; restoration may still miss omitted text beyond that
cap. Original `end_line` describes the pre-clipping snippet, not the last line the
reviewer actually saw, so continuing after it can skip the missing implementation
or hit EOF. An offline synthetic test composes the real view, rule and reader to
check this distinction; it is not a useful-bug or model-quality result.

This policy was motivated by an exposed two-case development pilot. Do not change
the old continuation rule or rescore those cases as prospective wins. A future
selector comparison should declare the stronger cheap comparator before seeing
new cases, retain unavailable/failed observations, and measure total selection,
review and native-verification costs. A selected implementation window and one
subsequent useful PR do not establish a general routing advantage.

One task-local pilot asserted that every admitted case contained pinned code,
but its first future admission had only issue/PR URLs. It terminated before model
or GET calls. That pilot stays invalid and its exposed inputs are not rescored.
Declare action availability and abstention handling before enrolling new cases;
retain unavailable cases in the denominator and report them separately from
actionable-policy outcomes. Offline adapter checks include real composed
reader/window success, HTTP failure and EOF, not only mocked success labels:

```text
python -B -m unittest tests.test_scout_acquisition_choice
```

Offline transport/accounting checks:

For a future utility study, include a no-additional-acquisition arm as well as
rules and model-selected evidence. Give each downstream reviewer the same
original input, frozen model/version, stopping rule and total resource cap;
charge target selection, failed reads, review and native verification to the
acquisition arms. Identical GET/window caps alone do not match total budgets.
Judge the incremental verified decision or reproduction, not window validity.
The present small acquisition trials do not satisfy this study design.

### MiniMax CLI cost observations

For a newly declared study using an already authorized MiniMax CLI, capture
non-streaming `mmx text chat --output json --non-interactive --no-color` output.
Set the actual model and region explicitly. **Do not add `--quiet` for this
accounting path:** in observed mmx 1.0.18 it emits only model answer text, dropping
the API message envelope and usage. JSON-looking model text is not API metadata.
An explicit region also avoids the CLI's separate key-region discovery request;
it must match the user's configured provider, not bypass an authorization error.
Do not print credentials or enable verbose auth diagnostics.

`scout_shadow_comparison.parse_mmx_message` reads that captured envelope without
invoking a model. It keeps answer text separate from thinking blocks, preserves
observed input/output/cache counters, and only returns a usable answer on a
normal `end_turn` completion. Missing/invalid cache counts remain unknown rather
than zero. A max-token termination may still carry known usage but cannot supply
a valid decision. The reader cannot authenticate a transcript, infer attempt
identity, restore stripped historical counters, price tokens or equalize total
budgets; keep those responsibilities and failed/uncertain requests in the caller.

An SDK caller may also supply `diagnostic_text` containing only
`error_class`, integer `sdk_exit_code` and `usage_unknown: true`.
The reader retains recognized SDK categories without echoing free-form messages
or hints. This is captured diagnostic metadata, not proof of an HTTP status or
recovered usage. Auth/quota failures remain failures, not permission to switch
credentials or providers. Old class-only errors stay unclassified; do not rewrite
past trials using a later quota check or successful request.

Offline controls and optional real-installed-CLI replay:

```text
python -B -m unittest tests.test_scout_mmx_accounting tests.test_scout_shadow_comparison
```

Set `SCOUT_TEST_NODE` and `SCOUT_TEST_MMX_ENTRY` to reviewed installed executables
to include the replay. It uses a loopback fake API, temporary empty CLI config,
dummy auth and explicit region, not a real model. Its injected token counters
test preservation only: they are not measured provider cost or decision quality.
The replay does not start local WSL or download/install a runtime. Old quiet-mode
observations remain immutable with unknown usage; they are not rescored.

This is our experimental-design inference, informed by
[Scrouting (sections 6–9)](https://arxiv.org/html/2608.04804v1): its no-router,
cheap-fixer-plus-verified-handoff ablation ties the routed system on its measured
benchmark. It also explicitly lacks an unverified-handoff pass-through ablation,
so the verification guard's effect on final solves was not isolated. Neither
result proves a Scout-specific evidence selector helps. Treat verified handoff
and routing as separate interventions, with separate ablations.

```text
python -B -m unittest tests.test_scout_evidence_acquisition
```

The tests inject controlled responses to cover partial timeout/EOF, HTTP error
bodies, invalid UTF-8/targets/budgets, byte caps and cache accounting. They test
the reader's behavior, not remote availability or scientific utility.

## Language-neutral window selection

After a successful fetch, `scripts.scout_source_window.source_window(text,
anchor="export function example(")` selects up to 80 lines/10,000 characters
starting at a unique single-line literal. Alternatively pass an exact one-based
`start_line`. It is standard-library-only and does not execute source. The
original UTF-8 bytes are hashed; displayed newlines are normalized. Ambiguous,
missing, beyond-EOF or over-budget targets fail explicitly, with no fallback.
A comment or string match is only a text location, not a function definition,
reachable caller or quality verdict. The caller still binds repository/commit
and judges whether the returned evidence answers the question.

This avoids pretending that a Python-only symbol resolver supports TypeScript
or C++. It does not infer unknown anchors, find a call graph or fix guessed
paths. Declare this selector in a fresh comparison before seeing its cases;
post-trial repaired windows are development checks, not prospective wins.

For separated caller/callee evidence in one immutable file, the optional
`AcquisitionSession.acquire_windows(url, ranges)` accepts up to eight disjoint
`{"start_line": 1, "line_count": 40}` ranges under **one shared** 80-line,
4,500-character default cap. It performs one logical acquisition, reuses the
existing source cache, and returns each excerpt with exact bounds and the same
raw-source digest. Range order is preserved. Overlap and excessive requested
lines fail before a GET; EOF, character-budget or transport failures expose no
partial excerpt set. Unlike the single-window API, requested ranges are exact,
not silently shortened. Character cost includes one newline between excerpts;
serialized metadata, model prompt bytes and tokens require separate accounting.

This is a reading primitive, not an automatic call-graph selector. Existing live
routing and historical trials still use their original policies. A future trial
must declare the range-selection policy, total evidence and actual prompt/model
costs before enrollment; a synthetic caller/callee test is not evidence of better
bug discovery or PR conversion.

```text
python -B -m unittest tests.test_scout_source_window
```

For acquisition-only shadow comparisons,
`scout_pending_cohort.compact_acquisition_view(packet)` offers a shared input
under 6,500 serialized characters. It retains a catalog of up to 24 source
URLs/ranges, discloses omissions, and allocates text to three snippets, pinned
code first in original order. It does not rank candidate merit, consult later
answers or change the live Scout prompt. Catalog-only entries have empty text;
clipped ranges describe the original snippets. An oversized catalog fails
explicitly rather than silently excluding a case. Apply it consistently to
every arm under a new declaration. Better source coverage is not demonstrated
utility, PR conversion or accuracy.

## Requested Python wrapper interfaces

Live continuation requests can also cross the visible tail from inside an
observed truncated window: for example, `lines 350-400` after seeing 241-360.
The interval must overlap that same pinned file's window and extend beyond its
end; wholly unseen, ambiguous, beyond-EOF and mixed-direction requests still
abstain. This uses the existing one/two-read budget and bounded overlap, not a
new URL, arbitrary line target or larger prompt allowance.

An exposed TorchAO replay had visible windows 481-600 and 581-669 in
[`cutedsl_quantize_2d_1x32_32x1_fused.py`](https://github.com/pytorch/ao/blob/f7c8353e8adeefc008a32169e6f92f8271d15e2d/torchao/prototype/moe_training/kernels/mxfp8/cutedsl_quantize_2d_1x32_32x1_fused.py#L650-L700).
The explicit request for 666-700 previously matched no continuation; it now
selects 650-700, exposing output validation and the actual `run` arguments.
A reconstructed untrimmed definition fallback already contained 586-700, so
this is a shorter tail-focused choice, not proof that the source reader could
not fetch the tail. Original pre-trimming producer arguments and prospective
model savings were not replayed/measured. No historical job or answer was
rewritten and no extra provider call was bought for this diagnostic.

When a follow-up explicitly requests one `definition(...)`, a source-reader
result marked `requested_definition_complete=true` with target metadata satisfies
that optional lexical read. The producer need not fill its second ordinary slot
with an unrelated file. Incomplete/ambiguous targets, prose-only hints, reference
scans, code-search hints, continuations and import hops keep their existing reads;
explicit companion tests and contracts remain intact. This is bounded acquisition,
not a correctness verdict or a measured model/PR-conversion improvement.
`tests.test_scout_exact_definition_reads` covers the producer with its real AST
selector and mocked source transport; it does not execute a candidate repository.

For one explicit `definition(Class.method)`, a bounded cache-only lookup can
move its unique declaring Python file ahead of same-basename lexical matches.
It examines at most eight already-supplied sources at the same commit and only
reorders an otherwise eligible path. Missing/malformed/ambiguous caches abstain;
explicit full paths and structured reference/import/continuation reads retain
their precedence. This is declaration location, not receiver resolution, and
does not add acquisition/model calls or establish a downstream savings claim.

The live producer's optional per-repository `followup_import_context=true`
uses `scout_import_context.import_requests` to replace guessed follow-up reads,
not add a new read tier. It accepts relative-import hints in top-level Python
free functions, including deferred/conditional imports. Competing targets,
nested functions/classes, missing cache and revision drift abstain. These are
module locations, not proof of Python binding or runtime support. An already
supplied complete export module is not requested again. A fully supplied cached
Python package with a literal `__all__` and the simple
`__getattr__ -> relative module import -> getattr(module, name)` pattern can
provide one observed-tree implementation hint. Missing cache, unsupported hook
syntax or ambiguous module/package files abstain. The helper does not fetch,
execute, recursively chase hooks, or expand the existing follow-up read budget.

For fresh shadow comparisons, `scout_catalog_target.mentioned_catalog_target`
provides a zero-model, language-neutral file baseline. It uses only the explicit
next-check text and at most 24 catalog entries: a unique full path outranks a
bare filename, repeated snippets are deduplicated, and competing paths/revisions
abstain. Only safe pinned URLs in the packet's repository qualify. Missing files
are not guessed, and the returned line 1 does not imply that the desired evidence
is there. Source text can be acquired and windowed with the existing helpers;
any definition lookup, fallback, or abstention must be declared identically
before a new comparison. This helper is not enabled in live routing. Offline
tests establish targeting/boundedness, not useful evidence or model superiority.

```text
python -B -m unittest tests.test_scout_catalog_target
```

Development example: at FlashInfer `426d028e`, the
[wrapper](https://github.com/flashinfer-ai/flashinfer/blob/426d028e18a270b60a1ac72306b29754bf087c67/flashinfer/fused_moe/cudnn_frost_selected.py#L56-L77)
imports `workspace_size` inside a function. Its
[export module](https://github.com/flashinfer-ai/flashinfer/blob/426d028e18a270b60a1ac72306b29754bf087c67/flashinfer/experimental/cudnn_frost_selected_kernels_moe_grouped_gemm/__init__.py#L15-L21)
defers to `bf16.runtime`; the
[actual signature](https://github.com/flashinfer-ai/flashinfer/blob/426d028e18a270b60a1ac72306b29754bf087c67/flashinfer/experimental/cudnn_frost_selected_kernels_moe_grouped_gemm/bf16/runtime.py#L235-L252)
accepts optional `out`. Five arguments in one wrapper do not establish that
another wrapper's six-argument call is invalid. The observed previous follow-ups
missed this interface. Offline producer tests now cover the two-hop acquisition
and unchanged two-read-per-follow-up ceiling, not native kernel correctness,
model accuracy, prospective cost savings or PR conversion. The limited cached
lazy-export hint now covers this source pattern; it is still not evaluation of
the export hook or proof of the installed package's binding.

## Cached Python literal-assignment hints

An explicit unqualified `references(UPPERCASE_NAME)` can now include an unseen
module-level assignment of a literal, using the already cached, pinned Python
source. Both simple and annotated assignments are supported. Repeated or other
syntactic bindings, wildcard imports, local/class-only assignments, computed
values and qualified receiver requests do not introduce this assignment hint.
Ordinary use-site and import-statement hints remain available under their
existing rules. Source is parsed, never executed or evaluated. A literal in the
returned text does not prove its runtime value, binding or reachability.

This uses the existing maximum of two 80-line source windows; it does not add a
model call, network acquisition or follow-up depth. Already supplied lines are
not requested again.

Development counterexample: h2 `bc239af1` has
[`CONTINUATION_BACKLOG = 64` at line28](https://github.com/python-hyper/h2/blob/bc239af1d1b85bc70482804f30a0e0e587d90a08/src/h2/frame_buffer.py#L28).
A supplied guard window covered its use but not this assignment. The previous
use-only lookup returned no unseen match, so a follow-up read another method
instead of the explicitly requested bound. The offline regression now supplies
the assignment in one window and retains ambiguity, receiver and budget checks.
This is a development-case repair, not a held-out accuracy, cost-saving or PR
conversion result.

```text
python -B -m unittest tests.test_scout_symbol_references
```

## Optional missing-implementation discovery

Explicit `definition(...)` and `references(...)` next-evidence requests take
precedence over an incidental kernel-launch hint from an earlier excerpt.
Otherwise a wrapper importing a kernel from another module can repeatedly win
the fallback and suppress the requested import/reference lookup. The import
helper can use one explicitly named, already-supplied module after an issue
source; ambiguous basenames, foreign revisions and unobserved paths abstain.
This retains the existing read budgets and does not resolve runtime bindings.
The exposed KDA chain supplied the development counterexample; fixing its
acquisition route is not GPU defect verification or a prospective PR-yield result.

A repository may opt into `followup_code_search=true`. When a needs-context
follow-up explicitly asks for `references(identifier)` or an unqualified
`definition(identifier)` (one or two bounded ASCII identifiers or hyphenated
reason codes), and no cached reference, import,
registration, continuation or kernel-definition read already supplies the next
step, the controller makes at most one GitHub code-search query. Five current
default-branch index hits are only path hints: intersect them with the already
observed immutable source tree, prefer implementations to test paths, then read
at most two 80-line windows at that fixed commit. A second requested literal can
use another window in the same cached file. Search results' URLs and contents
are never trusted as source; a window lacking its requested literal is discarded.
Unavailable search is observable and falls back to the existing bounded selection.
The index may be stale or incomplete, and a literal can be a comment/declaration,
not a definition or reachable caller. No call graph, defect verdict, native
execution or novelty is inferred. This does not increase the two-source-read
ceiling, but the discovery API request is an additional cost. Query results are
cached for the existing 15-minute snapshot TTL, keyed by repository, target
commit and literal, with tree membership rechecked on reuse.

An unvalidated `lead` is also eligible when it explicitly requests only one/two
`references(...)` targets. The label is not evidence completeness; free prose,
malformed targets or a lead's definition-only request do not enable this route.
The existing opt-in, earlier cached evidence routes and one-query/two-read caps
remain. If two explicit references name a unique cached module-level class and
its direct `INSTANCE = Class(...)` binding, the single query prefers that
requested instance literal. Ambiguous/rebound/missing/drifted input abstains and
keeps the first literal. This is a lexical search hint, not receiver resolution
or permission to invent a third target.

A real read-only GitHub check for the exposed WO-A case queried that instance
once and returned the output-projection caller; its fixed-81f7c695 window
contained the positive-token guard and full raw bytes matched local Git. Local
HTTP stand-ins separately exercised the real client against 200 and 403 with no
credentials, including query/read limits and no retry of forbidden search.
These prove the tested routing/wire path, not improved model decisions, recall,
total research cost, PR conversion or fresh prospective efficacy. The
[REST search contract](https://docs.github.com/en/rest/search/search#search-code)
still does not pin the index to our chosen commit; returned paths must pass the
existing immutable-source checks before becoming evidence.

The definition fallback covers a missing callee reached through an object rather
than a direct named import. Qualified receiver expressions, URLs and search-query
syntax are not accepted as literals; discovering a matching method does not
resolve that receiver's runtime type. This is a source-acquisition capability,
not evidence of improved selector quality or PR conversion.

An explicit unqualified `definition(identifier)` in a pinned Python file can
match both a base default and a subclass override. The literal window still
obeys the same 80-line cap and is not silently redirected to a guessed owner.
When the already acquired file contains multiple declarations, the source
includes a syntax-only `definition_inventory`: lexical qualified names and
declaration/end lines for at most eight candidates, the total match count and
an omission flag. It makes no additional source request. A later explicit
qualified-definition request can use the existing body selector; duplicate
owners or unsupported syntax remain unresolved. Locations outside the visible
window are not body evidence, runtime receiver resolution or dispatch proof.

An owner-known SGLang replay exposed this distinction: discovery acquired
`prefill_budget.py`, but the first window showed only the base default, not the
shared-SWA override. The inventory exposed both locations; an owner-selected
qualified follow-up then acquired the override body within the existing chain.
This is retrospective wiring validation, not a model prediction or a prospective
quality/cost result. Unread physical reclaim effects remain separate from the
source-refuted budget-offset-debit claim.

For an explicit `references(identifier)` in a C-family source, the window prefers
the first invocation-shaped occurrence (`identifier` followed by `(`) over an
earlier `using` import. It reuses the already-read body, masks ordinary comments,
quoted strings and continued preprocessor directives, and retains literal
fallback for unsupported raw strings or no match. Declarations and inactive
branches can still match: this is a lexical window hint, not call resolution.
Ordinary literal requests and non-native source windows are unchanged.

C-family `.cc`, `.c` and `.cxx` files are included in observed-path selection;
a tree member with one of these extensions must not be silently excluded.

Offline checks:

```text
python -B -m unittest tests.test_scout_code_search
python -B -m unittest tests.test_scout_definition_inventory tests.test_scout_requested_definition
python -B -m unittest tests.test_scout_native_reference_anchor
```

Development evidence motivating the opt-in: an unexecuted report
[TileLang #3381](https://github.com/tile-ai/tilelang/issues/3381) requested
`LowerToSTGPredicated` / `LowerToLDGPredicated`, but its supplied catalog had
carver policy and engine entry Python, not
[the actual pass](https://github.com/tile-ai/tilelang/blob/994b44eca1a83a00d19d926e5264a6c608700656/src/cuda/transform/lower_ldg_stg.cc).
Independent inspection and a native CPU-only TileLang 0.1.15 IR transform showed
an outer-store/inner-load predicate discrepancy. This was extra owner work, not
a selector win, GPU execution or a current-source native rebuild. Current code
search located the missing observed path. That development check establishes
feasibility, not prospective conversion/cost superiority.

## Displayed-row review citations (experimental)

`scout_review_citations.citation_view` preserves each bounded excerpt as a rows
array with a local evidence ID. `resolve_review` accepts one-based excerpt row
ranges and extracts their exact displayed text, including existing line prefixes,
instead of requiring a model to reproduce escaped quotes. These are display
positions, **not** original file line numbers. At most two spans, eight rows and
1,400 characters per span are allowed. A valid span does not verify the reason,
producer/consumer contract, execution or candidate quality; independent semantic
adjudication remains required. This interface is not enabled in live Scout.
Duplicate JSON keys at any output-object level are rejected, including identical
repeats: contradictory decisions or citation coordinates must not be silently
resolved by keeping the last value. This is input disambiguation, not a repair
of prior model answers or evidence of better discovery quality.

```text
python -B -m unittest tests.test_scout_review_citations
```

Two fresh, nonrandom follow-up inputs in an interface feasibility pilot still
had no eligible implementation file in their catalogs. All acquisition selectors
abstained, with zero GETs. Six reviewer completions correctly described missing
implementation evidence, but only two respected the citation interface; four
chose unavailable or over-budget ranges. No incremental verified solve was
demonstrated. Do not repair those answers into successes or claim cross-cohort
accuracy from this negative result. Explicit rendered row labels are a candidate
for a future fresh trial, not a retroactive improvement to this one.


`numbered_citation_view` offers an optional model-facing rendering with explicit
`{"row": 1, "text": "315: ..."}` labels. Preserve the plain `citation_view` as
resolver input: rendering does not change normalized text, IDs or digests. It
performs no fetch or live routing change.

A subsequent predeclared recent-follow-up trial requested four cases but enrolled
only one; the three empty slots were not replaced after inspection. All three
arms used the numbered interface. No-additional and the explicit-file rule
returned valid INSUFFICIENT reviews; the rule abstained. The model selected one
80-line pinned window containing the missing encoder, but its review cited 13
rows against the frozen eight-row cap and was rejected, without retry or repair.
Reported total tokens were 2,636 / 2,582 / 7,388 respectively (four calls total);
only the model arm made a source GET (21,857 body bytes). These are observed
reported token costs, not dollar or cached-latency savings.

After predictions were sealed, six separate pinned owner source reads found
small-M caller reachability but no demonstrated runtime defect; the owner label
remained INSUFFICIENT pending applicable TMA-store semantics/native verification.
This is unresolved, not a negative bug label. There were zero incremental
owner-supported decisive solves. The one-case underfilled, nonrandom trial does
not establish citation-accuracy improvement, acquisition superiority or PR yield.
Explicit labels alone did not eliminate invalid ranges. Owner review is not an
independent human judgment; vendor-document browsing is separate from model GET
cost. Raw private experiment records remain local.

## Visible-frontier rule for fresh comparisons

`first_visible_frontier_or_continuation` is an optional zero-model baseline.
For a clipped, numbered source prefix, it continues at the last displayed row
(or the next row when the last row ends with a newline). It requires contiguous
original line labels within the declared snippet range; ambiguous, unnumbered
or catalog-only text falls back to the existing restore-from-start rule.
Original policy functions, eligible URLs and caller window budgets are unchanged.
This is not enabled in live routing and must not rescore a frozen trial.

A development counterexample showed that restoring lines 11–90 can miss a guard
at line 121, while continuing from displayed line 50 reaches it with the same
80-line cap. The synthetic regression verifies that mechanism, not held-out
decision accuracy, source relevance, native bug discovery or PR yield. The rule
cannot recover a missing implementation file from a closed catalog; expanding
the catalog is a different action with its own costs and evaluation.

```text
python -B -m unittest tests.test_scout_visible_frontier tests.test_scout_acquisition_choice
```

## Compose a fresh case before spending model calls

`scout_source_trial.run_case` composes the existing acquisition session with
selector/reviewer callbacks for **newly declared** shadow protocols. It does not
replace the live Scout runner or repair a frozen historical trial. A prior
chronological pilot stopped before any model call because its first admission
contained only issue/PR text and the runner asserted a pinned source existed.
Keep that pilot invalid; do not substitute a more convenient case.

The driver accepts a bounded compact acquisition view, not a raw queue row:

Eligibility uses the same `acquisition_catalog` and `validate_selection` as the
standalone choice helper: only immutable files in the view's declared repository
qualify. Foreign repository entries remain quoted original context, but cannot
be preflighted, selected, or used as the continuation rule's target. An entirely
foreign catalog stays unavailable without paid callbacks or GETs. This is a
repository boundary, not a guarantee that the remaining evidence is relevant.

- No pinned file in the displayed catalog produces three
  `UNAVAILABLE_ACTION_SPACE` records, with no callbacks or GETs. Retain these
  admissions in the population denominator, separately from comparisons with
  available actions. This is not evidence that no useful file exists elsewhere.
- Available cases make one selector call, then one reviewer call per declared
  arm: no additional source, the declared zero-model rule window, and the selected
  catalog window. Each acquisition is at most 80 lines/4,500 characters. Callers
  may predeclare a rotated arm order.
- Abstention, invalid selection, callback exceptions, EOF, transport failure and
  session exceptions remain distinct records, without replacement or retry.
  A session exception flags potentially incomplete cost accounting; it is not a
  free acquisition. KeyboardInterrupt/SystemExit are not swallowed.
- Reviewer callbacks receive separate copies of the original view and the
  additional window/failure, without the arm name or selector rationale. This
  avoids explicit arm labels, not inference from differing evidence. Original
  text is untrusted; field allowlisting is not an injection or leakage defense.

New protocols can set `rule_policy` to one of the existing deterministic rules:

- `first_catalog_continuation` (unchanged default): continue the first eligible
  catalog file at `end_line + 1`, or line 1 without a range.
- `first_clipped_or_continuation`: restore the first eligible clipped file from
  its original start, otherwise use the continuation rule.
- `first_visible_frontier_or_continuation`: continue a clipped contiguous
  numbered prefix, with the restore rule's conservative fallback described above.

The result records `rule_policy` and labels its rule arm `rules_<rule_policy>`.
An explicit `arm_order` must use that exact label; unknown policies and mismatched
labels fail before any acquisition or callback. For example, declare
`run_case(..., rule_policy="first_visible_frontier_or_continuation")` before
enrollment rather than choosing the best rule after seeing a case. No extra GET,
fallback read or larger window is granted to the rule. These alternatives make
stronger cheap comparators available, not a claim that one dominates or that the
model improves on them. Keep original defaults, frozen protocols and historical
answers unchanged. These rules still cannot select an absent catalog file.

Callbacks must enforce their predeclared provider/prompt/output/time budgets,
use isolated model conversations, and persist call identities, raw answers,
reported usage and uncertain/failed attempts. The opaque `RETURNED` record says
only that a callback returned: it is not a parsed verdict or native bug label.
Selector overhead belongs to the selected arm. Equal ceilings do not imply
equal observed spend. Session costs are cumulative; shared-cache actual GETs
must not be charged twice or treated as measured uncached arm latencies. Record
root discovery, setup, independent native adjudication and owner costs separately.

New runs also record monotonic `client_elapsed_seconds` for each completed or
failed callback and `client_wall_seconds` around the complete `run_case` call,
including input validation, acquisition, preflight and callback failures. A
not-called selector has no callback interval, not a fabricated measured call.
The enclosing case interval already contains callbacks and observed GET time:
**do not add these nested intervals together**. A sequential multi-arm shadow
case is not deployment latency for an individual policy. These are client wall
observations, not provider compute, dollars, active GPU time or total research
cost. They do not cover preparation outside this call, a caller interrupt/crash
or escaping input/programming error, or prove that a callback respected its budget.
Preserve those unknown costs and
the wrapper's durable attempt/usage records; do not re-run frozen cohorts to
fill missing historical timings or infer a quality/cost improvement.

Before new admissions, freeze this implementation, callback adapters, eligibility,
unavailable-action policy, metrics and budgets. After predictions are sealed,
independently adjudicate falsifiable claims against the pinned source/native
environment; leave unresolved cases unresolved. The composed tests below cover
control flow only, not provider quality, incremental discovery or PR conversion.

```text
python -B -m unittest tests.test_scout_source_trial tests.test_scout_evidence_acquisition
```

### Optional source-availability preflight for new protocols

A later owner-known Go before/after calibration completed its ten model calls,
but neither immutable raw-source GET succeeded on the remote worker. All eight
reviews abstained; this is an unavailable-evidence result, not a comparison of
selector quality. Retain those answers and paid calls. Do not rewrite that
experiment using a subsequently repaired network or a different source cache.

New protocols may declare `run_case(..., preflight_sources=True)` to acquire each
distinct pinned catalog URL before paid callbacks. If every acquisition fails,
the case and all three arms remain `UNAVAILABLE_SOURCE_ACQUISITION`; no selector
or reviewer is invoked. Admission and cost denominators must retain the case.
The preflight has the same session's source/body/time limits and charges its
actual GETs, observed bytes and uncertain exceptions. Predeclare its additional
logical requests and the catalog-size acquisition budget (at most 24 URLs).

If any source is fetched, the original catalog remains unchanged. A selector
may still choose a failed entry, abstain or request a window beyond EOF; there
is no substitution or retry. `FETCHED` does not prove a particular window is
usable, a hypothesis is true, or the initial snippet is insufficient. Existing
protocols default to the previous callback behavior. This opt-in gate is for
comparisons that require available additional source, not a blanket policy to
discard evidence-poor production leads or suppress useful baseline-only work.

### Diagnose transport failure without retaining exception text

New acquisition records keep the original `error_kind` and additionally report
`error_category`, `error_errno`, `error_winerror` and `tls_verify_code`. Categories
are fixed labels for DNS, timeout, TLS/certificate, permission, reset/refused and
other OS errors; numeric codes are bounded integers. No exception messages,
certificate messages, filenames, proxy values or headers are copied. These four
fields stay null on success, HTTP-status errors and non-transport failures.

An unclassified reason is still a failed acquisition, not permission to retry,
switch transport, add credentials or disable TLS verification. Codes describe
the observed attempt only: a current connection reset does not establish why a
historical request failed or who reset the connection. Shared-cache requests
retain the original diagnosis and have no additional physical GET cost. This
diagnostic addition does not repair, relabel or rerun frozen experiments.

### Bounded owner feedback for growing repositories

Source feedback is optional advisory context, not a rejection rule. Put reviewed
notes in `owner-source-notes/<owner>%2F<repo>.json` under the local Scout run;
the literal filename is case-normalized. The reader opens only that repository's
file and the optional legacy `owner-source-notes.json`, each capped at 64 KiB.
An oversized or malformed legacy file must not hide valid repository feedback.
It keeps the latest 24 distinct valid notes, with repository copies preferred;
the existing same-file context still exposes at most two. It does not scan all
repository files, rewrite history, query GitHub, launch models or mutate jobs.

Each list entry keeps the existing six fields: `repo`, `prior_hypothesis`,
`source_url`, `reason`, `reopen_when`, `evidence_url`. Bind source URLs to an exact
raw Git commit and use same-repository public evidence. Do not include private
artifact paths or logs. State which old head failed and which new head was
rechecked, and what remains untested. A PR link does not prove live merge/CI
state. Notes do not replace inspecting current source and cannot suppress a
distinct defect. Updating feedback alone creates no new paid task; changed
primary evidence can still enter the queue normally.

Write reviewed feedback through `scout_owner_note.py --root RUN --note NOTE.json`
and inspect its `context_status`/`projection`, rather than appending unchecked
JSON and assuming it reached the reader. Safe same-repository issue comments,
PR comments/reviews/inline discussions, and discussion comments can be cited by
their exact GitHub permalink. Queries, arbitrary fragments and cross-endpoint
comment forms remain rejected; these links never become canonical published-PR
identities. Keep a stable `prior_hypothesis` and full source path when revising
one decision: the writer replaces only that key, including across revisions.
Preserve the old evidence in its existing task record before updating current
advice. A stored note alone does not establish projection or model consumption.

This closes a published-reader integration gap found when the legacy file grew
past its byte cap. It does not measure saved calls, recall or PR conversion, and
is not a prospective selector experiment. Tests cover the actual producer's
changed-source/no-replay behavior as well as bounded read-only note loading.

For new feedback in a growing repository, use
`scout_owner_note.py --root RUN --note NOTE.json --indexed`. This writes a
standard-library SQLite index, `owner-source-notes.sqlite`, without migrating,
expanding, pruning or rewriting either legacy JSON file. The original command
remains compatible and explicitly reports the indexed alternative when full.
The indexed key is repository + full source path + stable hypothesis; updates
replace only that decision across source revisions. Preserve its superseded
evidence in the existing task record. Exact repeats do not refresh recency.

The reader queries up to eight requested source paths, using a path index, and
returns at most 24 indexed rows with a total serialized budget of 64 KiB and a
16 KiB per-note cap. It still exposes at most two advisory items and drops optional
memory before clipping primary source. More than eight paths abstains from the
optional index rather than widening the query. Legacy files retain their separate
64 KiB caps. A valid indexed revision shadows only the same legacy hypothesis/file;
invalid, locked, corrupt or unknown-schema index data cannot erase legacy advice.
Both the actual reader and writer validate projection. Indexed
`--expected-sha256` binds that note's canonical UTF-8 bytes, not the whole database
or legacy file; an absent indexed note hashes as empty bytes. A stored note is
not proof of model consumption, saved tokens or a new finding. Updating feedback
does not replay old source or mutate discovery/delivery jobs.

Retain explicit `owner_rejection` evidence from terminal `NO_BUG` delivery rows
as a reminder to reassess the old explanation, not proof that current source has
no bug. Bare model rejection text and a disposition stored under the wrong state
do not qualify. Public source/evidence and privacy checks still apply; the reader
does not invent a human-authored reopening decision.

Followup production and owner intake project only the already-parsed hypothesis
title into the memory reader. Passing a complete analysis longer than its
2,500-character input cap used to silently disable identifier ranking, letting
unrelated newer notes displace relevant advice. Full source analysis is retained
unchanged; explanation text cannot select advice. The title, scan and two-note
bounds remain unchanged, as do admission and no-replay behavior. Offline
regressions cover both callers, not just the memory helper; this repair is not
a measured PR-conversion or token-saving result.

### Shadow capacity is not a model verdict

An operational pilot can produce zero model calls when every immediately
observed slot is busy. Preserve that admission failure, not an accuracy score.
For a **new** frozen protocol, `scout_shadow_admission.wait_for_capacity` offers
a bounded read-only wait using fresh runtime heartbeats, pause/cooldown flags
and observed spare capacity. Freeze the cohort independently; keep wait time
and exhaustion in costs. Recheck immediately before calling: this helper is not
an atomic reservation, dispatcher, request retry or reason to restart Scout.
Preloaded public source snapshots also require declared setup costs; local reads
are not network GETs. Neither change retroactively repairs old trial results.

Go import hints skip an exact declaration already found in the supplied file.
For example, `definition(Result.Bool)` must not spend a module-metadata read
merely because the file also has unaliased stdlib imports. Mixed requests still
resolve genuinely imported targets under the original two-read cap. This is a
lexical acquisition shortcut, not proof of a complete body or type binding.
An exposed GJSON source replay removed one redundant go.mod request; it does not
establish prospective model accuracy, token savings or PR-conversion benefit.

Related-work search can also use one title-mentioned, visibly defined C++ method
as its existing query hint. It accepts contiguous numbered out-of-line definitions
with a body opener in a pinned same-repository source; comments, strings,
preprocessor directives, declarations without bodies and ambiguous matches retain
the original title. Unsupported raw strings and clipped signatures abstain.
This is lexical evidence, not a C++ parser, owner binding, absence/duplicate
verdict, or extra search request. Python owner-spelling behavior is unchanged.
The existing lookup still returns at most five issue/PR excerpts in at most two
queries; a relevant RFC may explain why an apparently small repair needs a wider
safety change. Read it before publishing, rather than automatically rejecting
every overlapping contribution. Offline composed checks do not establish live
search recall or prospective call/PR savings.

Repositories may opt into `followup_issue_body_context=true`. A source-chain
follow-up can then explicitly name one already displayed canonical issue in
`next_check`, by its same-repository URL or `#number`. The controller constructs
one body GET after the usual public-visibility check. It replaces other
related-work/PR-revision/discussion lookups for that follow-up, not its normal
source reads. The body uses the existing 5,000-character head-tail budget;
comments, timeline and recursively linked reports are not fetched. The original
primary source and chain/root ownership remain unchanged; the requested report
replaces its inherited search snippet and is not marked peripheral search text.
Foreign, unseen, malformed and comment-only references cannot create fetch URLs.
Invalid/failed responses remain errors, not successful-empty reports; defaults
and citation-only related-PR searches are unchanged.

An exposed Mooncake case had already retrieved [RFC #3231](https://github.com/kvcache-ai/Mooncake/issues/3231),
but packet-budget trimming retained only its title and opening paragraph, not
the scope-safety constraints. This was a **body-availability gap**, not proof
that a better symbol query discovered the report. Reading the RFC changed the
owner's decision: a recursive-delete-only patch is not a qualified fix for the
broader unscoped cleanup problem. The new capability honors an explicit request;
it does not guarantee the model will request, read or apply the relevant body,
or prove safe deletion, better recall, reduced spend or PR conversion.

```text
python -B -m unittest tests.test_scout_duplicate_query tests.test_scout_duplicate_owner_spelling tests.test_scout_native_reference_anchor
python -B -m unittest tests.test_scout_cited_issue_context
```

### Optional feature-named companion test

Repositories may opt into `followup_feature_test_context=true`. When a follow-up
explicitly names a Python method whose definition is visible in either of the
first two same-file source windows, the companion selector can prefer one
observed test filename containing an adjacent pair of nongeneric method-name
components plus a source-module component. Only a unique match replaces the
ordinary companion test read; ambiguous/unmatched cases keep the old selector.
It adds no GET or model call and keeps the existing 80-line test budget. A name
match is a retrieval hint, not proof of test coverage or source reachability.

In an exposed SGLang case, the old module-name match selected a throughput test
while the same tree already contained `test_xpu_encoder_decoder_varlen.py`, with
a real-XPU mixed-empty SDPA correctness check for the named helper. Retrospective
replay selects that file with the opt-in. This does not prove that all-empty or
multiple-query cases are covered, that the XPU tests pass, or that future model
accuracy/PR yield improves. New prospective evaluation inputs must remain unseen.

### Operational refill diagnostics

For a parallel research producer, `research.json.refill_health` reports each
repository's current fetch age, last completed outcome/duration and remaining
retry delay. `ERROR_BACKOFF` retains the sanitized controller error code even
after the one-iteration `last_error` clears. `NO_NEW_EVIDENCE` means that refill
enqueued nothing, not that the repository has no defects or is fully explored.
`ELIGIBLE` describes scheduling eligibility, not a stalled or dead process.
The dashboard exposes these details without new network/model requests or
changes to queue ordering, deduplication, retry policy or candidate decisions.
These are process-local diagnostics; restarting clears the timing history.

### Optional PR review feedback

Set `followup_pr_review_context: true` for a deliberately selected repository to
let an explicit `next_check` request for a displayed PR's reviews/comments use
`scout_pr_review.pr_review_sources`. The default is off. Model text selects only
an already supplied same-repository PR number; it cannot supply a new URL to fetch.
This route replaces PR patch/search/discussion expansion for that follow-up,
not its ordinary source reads. A failed feedback read records an error code,
not an empty-success claim, and does not trigger extra related-work lookups.

The reader refreshes PR metadata, reads the first page of at most 100
chronological review submissions and at most 10 updated-desc inline comments,
then supplies up to two body-bearing submissions and one inline comment.
That costs three bounded GETs plus any required public-visibility check; each
response is capped at 300,000 UTF-8 bytes and each displayed body at 1,200
characters. The first page can omit later reviews; an empty sample does not
prove no feedback. It does not retrieve ordinary issue-conversation comments
or resolved-thread state. See GitHub's distinct
[review](https://docs.github.com/en/rest/pulls/reviews#list-reviews-for-a-pull-request)
and [review-comment](https://docs.github.com/en/rest/pulls/comments#list-review-comments-on-a-pull-request)
interfaces.

Pending submissions never enter evidence. An inline comment must link to a
submitted review observed in that page. Keep that review's commit separate from
the comment's current/original commit fields and the initially observed PR head;
diff-position updates do not make an old review current. All bodies remain
untrusted statements, not test results, a fix verdict, human signoff or authority
to execute their suggested commands. Offline tests cover producer routing and
these bounds, not live API compatibility or measured discovery benefit.

### Current owner advice at delivery generation

An old immutable lead can predate a published PR or an owner counterexample.
Refresh the existing bounded publication/deferral readers when constructing its
delivery request, using the actual selected source URL rather than copying all
source-window matches. This supplies coverage and reopening hints, not a reason
to suppress a distinct candidate or change its source analysis.

Optional advice uses at most 4,096 additional serialized context bytes and only
the remaining existing context allowance. Fit the actual outer backend request
too: source quotes and backslashes are escaped again when the prompt is encoded
as JSON. Drop optional advice before clipping any source, hypothesis or existing
lesson. Missing, corrupt or unrelated notes leave the original request intact.
No new network/model call, queue mutation or publication is implied.

The offline worker fixture stages an old lead, records a new public PR hint,
then intercepts generation without calling a model or executing a subject. It
checks that the latest hint/caution reaches the request, while the staged lead,
source and note files remain unchanged. This establishes advice availability,
not better model decisions, fewer duplicate PRs, recall or measured token savings.

The same four fixtures were also replayed against the actual deployed worker's
dependencies: the original request missed the publication field, while the
narrowly patched module passed. Read-only probes against existing owner history
then exposed pyparsing PR #698 and the scoped fsspec public-API counterexample.
The update preserved deployed lesson handling and all unrelated methods; only
the idle delivery module's on-disk bytes changed. Existing controller/viewer
processes were not restarted. Future delivery processes can import the update;
this is not evidence that a production model consumed it. An initial installed
fixture launch failed before test bodies because inherited bootstrap paths were
parsed as unittest names; its log was retained and only the launcher was fixed.

```text
python -B -m unittest tests.test_scout_delivery_owner_memory tests.test_kimi_scout_delivery tests.test_scout_direct_owner_intake tests.test_scout_publication_context
```

### Optional BM25 window comparator

An exposed knowledge-reader development audit compared the existing word-overlap
policy with this scorer over 33 existing/literal queries, using both unweighted
fields and the old field weights as token repetition. The weighted variant moved
the relevant consumer-contract card first for two exposed walrus/swizzle queries,
but also moved a CLI-input-transport card ahead of the parser/plugin contract for
a configuration query. These owner-read examples are not independent relevance
labels, prospective recall, runtime savings or PR outcomes. Index preloading and
file-reading costs differed, so the recorded intervals are not speedup evidence.
No default ranking was changed.

The actual producer already passes immutable source URLs, which can prioritize
a same-repository/full-path lesson before generic word overlap. The development
library's synthetic queue fixture retained that advice, but the same fixture on
the deployed modules/library failed: the deployed consumer-contract card lacked
four newer source anchors. It also contained one older unique host-memory anchor
absent locally. Its recorded `utils/host_memory.py` path was invalid at the pinned
commit; inspection of the raw Git tree/source places it under
`mem_cache/host_memory.py`. The host/cgroup minimum applies only without the
explicit environment override. Preserve that bounded fact and the old snapshot
when merging, not the invalid active pointer or an unconditional cap claim.

The merged card retains these distinct examples within the existing 8,192-byte
reader cap; no whole-library mirror, larger prompt or ranking change is needed.
Recheck the same isolated producer fixture against the deployed library after a
scoped compare-and-swap update. After that update, both the same ambiguous-query
fixture and the existing source-affinity control passed on the actual deployed
modules and 135-card library. The other 134 card files and runtime code remained
byte-identical; no production jobs, model calls or controller restarts were used.
These synthetic queue fixtures establish scoped deployed packet availability,
not actual production-model use or knowledge benefit. Keep the failed deployed
check as a negative control.

`scout_shadow_comparison.run_arm` accepts `action="bm25"` for newly declared
experiments. It ranks preloaded, hash-verified source windows using only the
prior hypothesis and next-check text. This is an established lexical-retrieval
comparator, not a new retrieval algorithm or a live Scout routing policy.
The scoring family follows [Robertson and Zaragoza](https://doi.org/10.1561/1500000019);
the fixed `k1=1.2`, `b=0.75` and positive IDF variant follow
[Lucene 9.12.0's documented defaults and IDF](https://github.com/apache/lucene/blob/releases/lucene/9.12.0/lucene/core/src/java/org/apache/lucene/search/similarities/BM25Similarity.java).
This implementation is not bit-identical to Lucene: it uses binary query terms,
Unicode words plus camel/snake identifier components, and unquantized lengths.

The index includes paths and full window text, including comments and strings.
Windows contain at most 80 lines/4,500 characters, fitted before scoring, at
stride 40 or the fitted length when shorter. A single oversized line is skipped
without hiding later lines. Positive-score ties use path/start/count order;
no lexical match abstains. Invalid identities or exceeded budgets fail closed
without falling back to another policy. Limits are 64 files, 1 MB per file,
8 MB total, 8,192 windows, and 256 unique query terms within 8,000 query bytes.

Record full-corpus logical index bytes and index wall time separately from the
selected excerpt, physical snapshot acquisition and downstream calls. Preloaded
source is not free; this comparator reads more source than a continuation rule.
The same two model-call opportunities and reviewer caps remain in force, but
equal caps do not imply equal total costs. It can repeat already visible text
and cannot retrieve an implementation absent from its catalog. Ranking, valid
citations and synthetic tests do not establish relevance, native correctness,
incremental discoveries, recall, PR conversion or superiority to an existing
agent. Declare the comparator before opening fresh inputs and establish an
independent executable oracle before purchasing compared calls; unresolved
cases remain in the cohort, with no replacement or repaired historical answers.

```text
python -B -m unittest tests.test_scout_bm25_source tests.test_scout_shadow_comparison tests.test_scout_source_window
```

## Additional native admission (2026-10-15)

A separately frozen metadata-only draw from the latest 60 first-parent nonmerge
commits of `mahmoud/boltons` selected the first eligible small fix:
[`4e5faa3d7e4008d89e0d8bf1ea87b6d9a061a16d`](https://github.com/mahmoud/boltons/commit/4e5faa3d7e4008d89e0d8bf1ea87b6d9a061a16d),
parent `961dcff3f42e73b245aef65e377fe82763b257bb`. No source semantics or native
outcome were inspected before selection. The full non-shallow history supplied
the declared frame; no replacement was drawn.

Complete raw-blob packages plus the identical unchanged head
[`tests/test_ioutils.py`](https://github.com/mahmoud/boltons/blob/4e5faa3d7e4008d89e0d8bf1ea87b6d9a061a16d/tests/test_ioutils.py)
ran through the official unittest loader/runner in separate restored offline
CPU sandboxes on Python 3.12.10. Of 88 test methods, parent 82 passed/six failed;
head 88 passed, with zero skips. The failures cover byte/character write counts,
BufferedWriter, byte-count rollover, backwards Unicode seeks and rejected
negative destinations. Failing subtest events are not counted as additional
independent bugs. All package files and test-overlay identities were checked.

The first parent invocation hit the sandbox's stdout limit and was killed;
that attempt is retained, not interpreted from its partial JSON. A versioned
wrapper changed only report delivery to a bounded summary plus a separately
retrieved/hash-verified full report before session release. Source and tests
were unchanged. The repaired two-arm client lifecycle took about 5.94 s;
clone, initial setup/terminated attempt, owner work and prices remain separate
or unknown, not zero.

This supplies one discriminating historical repair group with zero model calls
or new PRs. It is not itself an evidence-selection comparison, native full pytest
or full-repository qualification, a memorization-free held-out sample, recall,
matched total-cost superiority or paper evidence. The strong-provider,
applicable existing-method and prospective multi-group requirements remain
unmet; do not present admission as their completion.

## Optional common final review and interrupted pilot (2026-10-15)

For newly frozen comparisons, `scout_shadow_comparison.run_arm(...,
single_review=True)` removes the fixed arm's first-pass reflection. Fixed/rule/
BM25 arms use one final reviewer call; a selected-source arm uses its selector
and one final reviewer call. Selector answers and reasons are not supplied to
the final reviewer. Freeze the same final provider, instructions and caps across
arms, retaining their different evidence. Charge actual calls; do not add dummy
calls to make counts equal. The legacy default is unchanged. This helper still
calls the reviewer after an invalid selector and marks the protocol invalid;
caller-owned stopping policies must not be inferred from it.

`summarize_reported_tokens` keeps the sum of known nonnegative integer counters
as `known_token_lower_bound`; if any record lacks valid usage, total usage is
null. Its record count includes injected no-call controls and is not an
authenticated provider request count. This does not recover usage, normalize
prices or account for owner effort.

A bounded development pilot on the exposed Boltons group above planned eight
arms using the same fresh final M3 reviewer. It attempted two model calls: the
parent fixed-native review completed correctly (1,504 reported tokens); the
head fixed-native review returned CLIError without a message envelope or usage.
The frozen stop rule ended the pilot without retry: one complete arm, one
incomplete arm, six unstarted arms. Total tokens remain unknown, with a known
lower bound of 1,504. No selector, source-only or rule comparison ran, so there
is no selector-benefit result. Sandbox sessions were released. The old transport
did not retain the SDK error category, so authentication, quota and network
causes remain undiagnosed. Future error-category logging can help diagnosis;
synthetic SDK error tests cannot establish current provider health.

```text
python -B -m unittest tests.test_scout_single_review tests.test_scout_shadow_comparison tests.test_scout_mmx_accounting tests.test_scout_model_usage
```

## Direct-outcome negative comparison (2026-10-15)

A new metadata-only draw selected the first eligible small repair from the
latest 60 first-parent nonmerge commits of `tkem/cachetools`:
[`bcf9e8176ebe16da58751fce971c98ffe045ede1`](https://github.com/tkem/cachetools/commit/bcf9e8176ebe16da58751fce971c98ffe045ede1),
parent `eadb91cc9d54a57d6738386bc5c575ff3c7d22ec`. Selection used commit titles,
paths and line counts before reading semantics, with no replacement draw.
This is public historical source, not guaranteed absent from model training.

Complete raw-blob packages and identical unchanged head `tests/test_rr.py` and
`tests/__init__.py` were tested in separate restored offline Python 3.12.10 CPU
sandboxes. The official unittest loader ran `tests.test_rr.RRCacheTest`: parent
28 passed/one error; head 29 passed; zero skips. The sole parent error is
`test_rr_popitem_empty_custom_choice`, where `min` raises `ValueError` instead
of the expected `KeyError`. These are 29 test methods, not independent bugs.
An owner eligibility correction preceded model calls: a temporary classifier
guessed the old Python exception message, whereas the worker used a different
wording. Its false decision remains in the raw record. The substantive declared
oracle was satisfied, but this was not a perfectly implemented automatic gate.

The frozen question asked for actual exception types on fresh empty `RRCache`
instances using `min`, `max` and `next(iter(seq))` as choice functions. Source
windows included the complete relevant class without hiding the repair. Three
arms used the same MiniMax-M3 final-review instruction/output cap: source-only
provisional answer plus reflection; fixed fresh native observations plus review;
and model-selected native/test context/abstention plus review. Selector answers
were withheld from final review. Invalid first responses stopped their arm;
outputs were not repaired, relabeled or retried.

| Arm, two related revisions | Strict correct final answers | Calls | Reported tokens |
| --- | --- | --- | --- |
| Source-only reflection | 1/2; other first response had the wrong JSON shape | 3 | 2,984 |
| Fixed native acquisition + review | 2/2 | 2 | 2,388 |
| Selector + review | 0/2; both first responses violated the interface | 2 | 2,173 |

All seven calls had observed input/cache/output counters: 7,545 total normalized
tokens and about 16.10 s model-client wall. The two fresh fixed-arm probes took
about 4.16 s client lifecycle; shared oracle calls, clone/setup and owner work
are separate costs. Dollar cost and owner effort remain unknown. Equal ceilings
are not equal realized or priced budgets; failed arms' lower spend is not a
useful-efficiency win. Every created sandbox session was released after terminal
container cleanup. No GPU, new PR or production Scout change was involved.

No selector benefit is demonstrated. The selector was asked for both an outcome
vector and an acquisition action, adding a task/interface burden absent from
fixed acquisition. Its observed end-to-end failures are real, but cannot isolate
action-selection quality. A fresh comparison should use action-only selection,
common final review and predeclared invalid-action handling; do not rerun this
exposed group or silently relax its parser. One related repair group, missing
cheap/strong-provider and full existing-method comparisons, and incomplete
priced/owner costs cannot establish generalization, causal utility or paper
readiness. Fixed native acquisition remains the necessary simple comparator,
not a new algorithm inferred from this result.

## Action-only selection: retained negative comparison (2026-10-15)

A new metadata-first draw selected Tenacity's
[`b6201eceed` repair](https://github.com/jd/tenacity/commit/b6201eceedfc719e996dcbc3f6c17f21011fb236)
and its single parent. It was the first eligible fix among the latest 60
first-parent nonmerge commits, requiring changed production and test files and
at most 180 production added/deleted lines, without reading patch semantics
until the draw was frozen. The draw was not replaced. This is already-fixed
public history, not a new contribution or memorization-free holdout.

Complete raw-Git-blob packages ran offline under Python 3.12.10. Two unchanged
head unittest methods were exported into the same-name test class to avoid
unrelated pytest-module imports: parent had the sole falsy-callable assertion
failure and a passing None/0 control; head passed both. This is a disclosed test
adapter, not a full upstream import/suite/CI claim. Separate actual sync/async
public calls established callback lists `[0.0]` on parent and `[1.0]` on head;
None/0 controls remained `[0.0]`. Sleep callbacks recorded values without real
one-second waits. Exact production packages were not patched or exported.

The frozen question asked for these direct sync/async outcomes. Unlike the
earlier Cachetools trial, the selector only chose `native`, `tests` or `abstain`;
it did not also answer the question. All arms used the same final-review format.
The reviewer never saw the selector response. Invalid actions stopped that arm
without repair, reinterpretation or retry. Source-only and fixed-native arms
needed one review call each; selectors could use a selection plus review call.
Equal ceilings do not imply equal realized or priced spend.

| Arm, two related revisions | Strict correct final answers | Calls | Reported tokens |
| --- | --- | --- | --- |
| Source-only common review | 0/2 | 2 | 3,268 |
| Zero-model fixed fresh native acquisition + review | 2/2 | 2 | 3,560 |
| Action-only selector + acquired evidence + review | 0/2 | 3 | 5,278 |

The parent selector correctly requested native execution, but final review
contradicted the supplied observation. Its model request was byte-identical to
the fixed-parent review request that answered correctly, demonstrating
downstream variability rather than an attributable selection effect. The head
selector returned an abstain-keyed prose object instead of the required action
enum; it was invalid despite a complete provider response (117 output tokens,
below its 128 cap). A plausible answer inside prose was not rescored as success.

All seven model calls retained input/cache/output counters, totaling 12,106
normalized tokens. Native/client/shared-oracle/setup costs were recorded
separately; dollars and owner effort remain unknown. Seven sandbox executions
were terminal with containers removed and their seven exact sessions released.
There was no GPU, new PR or production Scout strategy change.

This group shows no selector benefit and does not justify adaptive deployment.
Action-only output alone did not solve interface reliability or evidence-use
errors. A future fresh multi-group study needs repeated/common-review variance
controls and simple fixed-acquisition comparators, plus the still-missing
cheap/strong-provider and full existing-method comparisons. Do not rerun this
exposed group or loosen its parser to obtain a positive result; one related
repair, unrandomized provider order and incomplete total costs cannot establish
generalization, causal utility or paper readiness.

## Metadata-enrolled native admission (2026-10-16)

`scripts/scout_repair_draw.py` makes a historical Python repair draw repeatable
without a new task-specific sampler. Freeze the repository/revision, literal
production/test directories and bounds before reading patch semantics:

```text
python -B scripts/scout_repair_draw.py --repo <local-repo> --ref <pinned-commit> --production-prefix src/ --test-prefix tests/ --count 60 --max-production-files 4 --max-production-lines 180
```

It selects the newest eligible fix/bug/correct title in a first-parent nonmerge
frame with changed Python production and test paths. Security-titled changes are
excluded; that title filter is not a security audit. Git metadata, not checkout
bytes or source semantics, drives selection. The result records the resolved
revision, scopes, bounds, scanned metadata and selected parent/head trees.
Shallow history is rejected, missing objects fail, and no eligible entry returns
`selected=null`. Do not replace an unavailable or nondiscriminating draw. Git
commands have individual 30-second timeouts, not a total experiment deadline.
This opt-in tool neither clones nor executes tests/models, changes the live
Scout strategy, or chooses current publishable bugs.

The default `--history-scope first-parent` deliberately excludes commits on
merged side branches as well as merge commits. On a merge-based repository,
60 such entries can span years and omit the ordinary repair history; an empty
draw is not evidence that the repository has no repairs. For a separately
declared cohort, `--history-scope reachable` includes single-parent commits
reachable through merged branches. It still excludes merge commits and compares
each selected fix with its own sole parent, **not** a merge's net diff. This is
a different population, not an automatic fallback for an empty default draw.
Freeze the scope before enrollment, retain earlier empty/failed draws, and group
related branch/release revisions rather than treating them as independent bugs.
It does not resolve native eligibility, counterfactual cost or publication value.

One frozen attrs draw selected the existing
[ClassVar repair](https://github.com/python-attrs/attrs/commit/97f8d175656bc03c373a1c9038048a4d312c307c).
On Windows CPython 3.14.3 / pytest 9.0.3, complete raw-Git source packages and the
unchanged head `tests/test_annotations.py` module produced three failures/four
passing controls on parent `6851ab593cd25f3c14393e9355d57d22bec2a074`, and seven
passes on the repair. Selection was
`-k 'missing_classvar_import or test_is_class_var'`. The original two-value
`slots` fixture was supplied separately, without the Hypothesis-dependent root
conftest; this is not the full suite or official CI. Python 3.12 would skip the
affected upper-level regression, so interpreter compatibility changes what
native evidence can discriminate.

An initial collection inherited this workspace's pytest config and prefixed node
IDs with its directories. No test body ran. An explicit private empty config and
rootdir corrected that before the parent/head executions; the setup failure is
retained. Accepted-run elapsed time excludes that earlier setup and must not be
reported as complete acquisition cost. There were zero model/GPU calls and zero
new PRs; total owner effort and priced cost remain unknown. This is one related,
already-fixed public-history group, not an unseen-model holdout or a result for
evidence-selection efficacy. Any future model comparison needs a separate
pre-call protocol, common-review variance controls and budget accounting.

```text
python -B -m unittest tests.test_scout_repair_draw
```

## Go enrollment and a retained output-limit stop (2026-10-16)

The optional historical sampler now accepts `--language go`. Production `.go`
files exclude `*_test.go`; directory scopes may coincide and explicit `./`
selects the repository root. Python defaults and its disjoint-directory rule
are unchanged. Language-specific production bounds are not bounds on all
files in a mixed-language commit. Real-Git tests cover suffix classification,
root/subdirectory selection, frozen-frame caps, security-title exclusion,
invalid scopes and the CLI. An initial fixture miscounted its one-line source
as two lines, and one Windows teardown reported `WinError145`; both are retained.
The corrected full 19-case run passed without suppressing cleanup errors.

One newly frozen Go draw used the latest 60 reachable nonmerge commits in
`go-chi/chi`, after reading public repository metadata/README but before repair
source. It selected the existing
[self-mount repair](https://github.com/go-chi/chi/commit/aba86186a27484f3cadc55b8d6448d2049af71bf).
Complete parent/head raw production exports ran the identical unchanged head
mounting tests on Linux amd64 Go1.25.10/race. Parent had three failed test/subtest
events and three passing controls; head passed all six. They are one historical
repair group, not three bugs. Tests call `Mount` and recover without serving a
request through the invalid self-mount. This is scoped call-time discrimination,
not full CI, a new PR or a training-unseen sample. An owner report adapter called
the comparison API incorrectly after both captures finished; existing saved
logs were re-aggregated through its actual interface with no repeated execution.

A subsequent separately frozen common-review pilot allowed one cached
observation, two repetitions per arm and at most eight M3 calls. It stopped on
the first selector: the complete provider envelope ended at `max_tokens`, with
128 output tokens and incomplete JSON. No action was accepted and no final
review occurred; this does not measure semantic selector accuracy or evidence
utility. Actual normalized usage was 1,173 tokens (888 input + 157 cache read
+ 128 output), with about 33.13s client time. The task-local collector incorrectly
reported zero because it gated accounting on answer validity. The original
report remains preserved with a hash-bound correction using the existing usage
helpers; no model call was replayed or output ceiling raised on the exposed case.

Native admission and cached observations are separate costs. Equal ceilings
are not equal realized/priced budgets. Strong-model/full existing-method
comparators, monetary/owner cost and multiple independent groups remain absent;
there is no adaptive-policy, PR-yield or paper-readiness result here.

Separately, the current Chi root package at `3a33ba578e0dd93444e0ff386cc26e665d92e31e`
passed unchanged ordinary and race runs on Linux amd64 Go1.25.10, with 80
test/subtest events per run and no module downloads. This supports a small
router-only Scout discovery scope, not a finding or selector result. Middleware,
examples, the declared Go1.24-1.27/Windows CI matrix and performance remain
unverified. The historical self-mount fix is already present and is not a new lead.

## Repeated common review: attrs pilot (2026-10-16)

The admitted attrs group above subsequently received a separately frozen M3
comparison: source-only, fixed fresh native acquisition, and action-only
selection, with two planned common final reviews per revision/arm. The question
was the actual `attrs.fields(C)` and `C()` outcome for a top-level slotted class
with an unbound `ClassVar[str]` annotation on CPython 3.14.3, not the intended
semantics. Fresh complete-package public calls gave parent
`CLASSVAR_AND_VALUE / TYPE_ERROR` and head `VALUE_ONLY / VALUE_1`; ordinary-class
controls passed. No production export, AST replacement or mock provided the
native oracle. Source views included the Python 3.14 annotation collector and
complete relevant functions, without hiding the repair.

| Arm | Actual final reviews / strict correct | Actual model calls | Reported tokens |
| --- | --- | --- | --- |
| Source-only | 4 / 0 | 4 | 9,378 |
| Fixed fresh native acquisition + review | 4 / 4 | 4 | 9,661 |
| Action-only selector | 0 / not observed | 2 | 4,968 |

Both selectors returned `action=native` but added a forbidden `reason` field.
Under the predeclared exact schema, both stopped without repair/retry; their four
planned review slots were **not calls**. These are two format failures, not four
failed reviews or evidence of wrong semantic action choices. Responses ended
normally at 118/102 output tokens, below the 128 cap; truncation is not supported.
All ten calls retained usage, totaling 24,007 normalized tokens. Fixed-arm native
client time was about 0.328 s; the two shared-oracle calls took about 0.344 s.
Clone/setup/owner effort and dollars remain separate and incompletely measured.

An offline audit reconstructed every request from frozen inputs, re-parsed raw
provider envelopes, checked source/probe hashes and compared original request
bytes. Each revision/arm had two byte-identical review requests: both source-only
groups varied between incorrect answers, while both native groups agreed on the
correct outcome. `summarize_repeated_reviews` optionally reports this distinction
from caller-validated actual calls; it neither authenticates hashes nor validates
the caller's oracle/schema. Callers must omit selectors and uncalled slots; the
helper separates invalid answers from accepted-answer variation and returns
counts, not raw text.

This supports the value of native evidence **on this one historical group**, not
adaptive selection, independence of repetitions, causal model-quality claims or
PR yield. Same ceilings are not equal realized/priced budgets; provider sampling
defaults were not controlled. Do not deploy an adaptive policy, rerun exposed
groups, relax their parsers or claim paper readiness from these pilots. The next
efficacy study still needs fresh independent groups, a simple fixed-acquisition
baseline, cheap/strong and full existing-method comparisons, and total-cost
accounting. There were zero new PRs/GPU calls/production Scout changes.

```text
python -B -m unittest tests.test_scout_single_review tests.test_scout_shadow_comparison tests.test_scout_mmx_accounting tests.test_scout_model_usage
```

## Qualified method search hints

The opt-in bounded code-search route also accepts one or two explicit
`definition(Class.method)` requests sharing a capitalized owner of at least
four characters. It searches the literal owner once, rather than silently
falling through to incidental filename matches. Lowercase receivers, nested
qualification, qualified references, competing owners, mixed qualified/free
targets and malformed or more-than-two requests retain ordinary acquisition.

This is only a non-exhaustive current-index path hint: results must still belong
to the observed tree, be read at its exact revision, and contain the owner
literal in the visible window. It does not prove a class declaration, method
ownership, complete body or reachability. One search query and at most two
80-line source views remain the ceiling; no model call or search tier is added.
The observed Kimi Code chain requested a registry's register/resolve methods
but received unrelated resolver files. Offline regression covers the previously
unsupported request shape; actual index hits, PR yield and cost gains remain
unmeasured.

```text
python -B -m unittest tests.test_scout_code_search tests.test_scout_exact_definition_reads tests.test_scout_requested_definition
```

## Qualified C++ source-location hints

An explicit `definition(Owner::method)` request in a pinned C-family file can
locate the unique full qualified literal followed by `(`, rather than scoring
unrelated prose keywords. Namespace spelling is literal; ambiguous/missing,
multiple, template/operator and unsupported requests retain the old fallback.
An explicit start or exact hint takes precedence. This uses already-read bytes
and preserves the existing line/character caps and physical-read count.

The returned `requested_native_literal` records a text location, not a parsed
definition: comments, generated source strings and inactive preprocessor paths
can match. It does not assert owner resolution, a complete function body,
compilation or reachability, and never sets `requested_definition_complete` or
triggers the optional-read omission intended for complete Python definitions.

One exposed debugging replay used the existing exact TileLang
[`79401028` source cache](https://github.com/tile-ai/tilelang/blob/7940102813c08c1a589e1b4c57d7010d9aa68982/src/ascend/codegen/codegen_pto.cc#L7600).
With the same reconstructed parent-analysis/issue-excerpt hints, the old reader
selected lines 3466–3585 without the target; the new reader selected 7600–7719
containing it. Both used zero new source fetches and zero model calls. This is
not an exact recording of the original pre-budget producer arguments, a blinded
prospective comparison, native PTO codegen qualification or measured PR yield.

```text
python -B -m unittest tests.test_scout_cpp_qualified_hint tests.test_scout_native_reference_anchor tests.test_scout_requested_definition tests.test_kimi_scout_context
```
