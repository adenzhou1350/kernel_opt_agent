# Source-inception v2: two-slot diagnostic results

Protocol: [frozen two-slot pilot v2](scout_source_inception_pilot_v2.md), committed
as `9e016ec7f8d92c90baa0ce3159bb58088a617ea5` before selected source acquisition
and model calls. Both original slots are now terminal. Original pilot v1 remains
frame-incomplete; neither study receives replacement successful examples.

## Humanize, 2026-10-18

Pin `785e5dcc0d0308ad0dff3f6cc0faa7085ad0375b`, `src/humanize/number.py` and
`tests/test_number.py`. Same coordinator, common MiniMax-M3 final reviewer,
explicit GLM-5.3 low effort, no tools, answer repair or model retries. Gateway
realization, provider-default M3 sampling and prices were not independently
controlled. All ten calls returned observed numeric usage; no unknown dispatch
remains. Their sum is 17,465 provider-reported tokens, not a dollar price or
equivalent computation across providers.

| Arm | Acquired IDs | Model calls | Reported tokens | Final review |
| --- | --- | ---: | ---: | --- |
| Source only | none | 1 | 1,257 | valid abstention |
| Rule | 2: companion start | 1 | 2,266 | valid abstention |
| Fixed native | 3: unavailable | 1 | 1,332 | valid abstention |
| GLM selected | 1: source continuation | 2 | 3,166 | valid abstention |
| M3 selected | 1: source continuation | 2 | 3,361 | valid abstention |
| GLM sequential | 1 then 2 | 3 | 6,083 | valid abstention |

The raw Git package imports generated `humanize._version`, absent from that tree.
The first native test therefore remained unavailable under the frozen no-build
observation preparation. No stub or different installed Humanize filled it.
Shared pytest preparation separately retained a site/dist-packages assumption
failure and a single-file-size failure. A corrected in-memory archive loader
passed three synthetic canary cases without weakening the CPU sandbox limits;
that is capability preparation, not a study case or Humanize coverage.

## Post-prediction audit and deviation

All predictions were saved before audit. **The owner viewed labeled null
verdicts before auditing**, contrary to the intended arm-blinded audit. Keep
these diagnostic results, but do not claim a successfully blinded study.

An unchanged pinned Git worktree was built through its own Hatch VCS wheel hook.
The shallow repository generated version `0.1.dev1`; every tracked production
Python file in the wheel was verified byte-identical to its Git blob. This later
build did not retroactively repair observation 3 or trigger new model calls.

Four contract tests ran against that authentic wheel. An ordinary/non-finite
control with eight inputs passed. Large positive/negative integers raised
`OverflowError`, and a large finite integer string rendered as `+Inf` instead of
receiving its suffix. Windows Python 3.14.3 and network-disabled nonroot Linux
Python 3.12.10 reproduced those three boundaries of **one** defect. Linux used
512 MiB/64 tasks; its container was removed and session released. Windows's first
launcher mistakenly passed helper arguments to unittest, so no target assertion
ran; that failure is retained separately from one corrected same-test/wheel run.
Pytest and unittest categorize the body exceptions differently; do not count
them as three independent findings or successful full-suite qualification.

The contract and offending float conversion are both in observation 1, which
three learned arms acquired. The audit therefore exposes an observed shared
miss, not evidence that all abstentions were correct. It establishes neither an
exhaustive miss inventory nor population recall. Ordinary tests alone would not
have covered this boundary.

Live all-state repository search then identified existing
[PR #414](https://github.com/python-humanize/humanize/pull/414), covering the same
integer/string/Decimal failure and integer-first repair. This is not a novel
discovery or a new PR opportunity. No competing implementation or redundant
verification comment was published; the PR already has detailed peer checks.

## First-slot cost and decision

Retain actual envelopes, journal, immutable input identities, original failures,
wheel and native reports privately. Source preparation/transfer recorded about
1.67 seconds, and the later authentic build/source verification about 16.84
seconds. Those timers exclude earlier intake/policy/source work, framework
preparation failures and unmeasured owner effort. They are components, not total
cost; no priced efficiency ratio or amortized speedup is established. Source
observations were physically prepared once and logically delivered to each arm;
logical read microseconds do not make acquisition free.

For this slot, learned selection cost more reported tokens and produced no
additional finding. Do not promote it into Scout's default routing or paper
claims. At this point the remaining frozen slot retained 10 attempts / 57,535
reported tokens. The lesson update derived **after** this case was excluded from
the remaining original model inputs. No case was rerun for a favorable result.

## Pluggy, 2026-10-18

Pin `09fabb162b8f84af0292b827c94e0149b82d448a`, `src/pluggy/_hooks.py` and
`testing/test_hookcaller.py`. The implementation slot is now a compatibility
reexport module shorter than 80 lines. Observation 1 truthfully reports EOF;
it does not follow imports into a different implementation file. The owner read
all package Python sources as required by the target's contribution instructions;
that preparation exposure did not enter model prompts.

Native preparation built the unchanged real Git worktree through its own
setuptools-scm backend after fetching ancestor tags. The resulting version is
`1.7.1.dev3+g09fabb162`, and all 13 tracked production Python files were verified
byte-identical to Git blobs in the wheel. The offline pytest stack's donor Pluggy
1.6.0 was **not** used as the subject: the target wheel was placed before it,
and imported module path and distribution version were checked before pytest
started. The target `tox.ini`, full companion and original `conftest.py` were
retained. No package install/build/network occurred inside an observation.

| Arm | Acquired IDs | Model calls | Reported tokens | Final review |
| --- | --- | ---: | ---: | --- |
| Source only | none | 1 | 790 | valid abstention |
| Rule | 2: companion start | 1 | 1,376 | valid abstention |
| Fixed native | 3: first test | 1 | 944 | valid abstention |
| GLM selected | 2: companion start | 2 | 2,050 | valid abstention |
| M3 selected | 3: first test | 2 | 1,797 | valid abstention |
| GLM sequential | 1: EOF, then 3 | 3 | 2,401 | valid abstention |

The preselected `test_adding_nonwrappers` ran once and passed. Three arms received
that same cached physical observation; these are logical reads, not independent
native repetitions. Preparation/build/transfer recorded 12.24 seconds, excluding
earlier source/policy review and fetching ancestor history. Those excluded costs
remain unpriced and unmeasured, not zero.

After predictions were saved, accepted hypotheses were deduplicated and stripped
of arm/provider labels. The owner read only that null-hypothesis set before a
bounded audit of the whole companion file plus compatibility alias identities.
That audit passed 24 pytest cases on nonroot, network-disabled Linux/Python
3.12.10 with 512 MiB/64 tasks. Its fresh container was removed and session
released. This did not replay observation 3 or qualify the full repository,
all hookspec/plugin consumers, all versions or all platforms. No further defect
was confirmed in this bounded scope; the exhaustive miss inventory remains
unknown. The owner is still not an independent human assessor.

## Aggregate stop decision

Both original slots consumed **20 actual model attempts / 26,823 reported
tokens**, with complete observed usage, 12 schema-valid abstentions, zero model
proposals and zero new qualified discoveries/PRs. The study's attempt stop is
reached. Do not reuse its remaining token allowance to invent more slots.

| Arm | Total calls | Total reported tokens | Additional confirmed discoveries |
| --- | ---: | ---: | ---: |
| Source only | 2 | 2,047 | 0 |
| Rule | 2 | 3,642 | 0 |
| Fixed native | 2 | 2,276 | 0 |
| GLM selected | 4 | 5,216 | 0 |
| M3 selected | 4 | 5,158 | 0 |
| GLM sequential | 6 | 8,484 | 0 |

The Humanize audit exposes one known contract defect missed by all arms; it is
already author-owned upstream work, not a new contribution. Pluggy provides a
runnable native observation but no useful difference in final findings. The
limited windows, first-test choice, convenience sampling, uncontrolled provider
sampling/effort realization, shared reviewer, incomplete total-cost accounting
and Humanize blinding deviation prevent an effectiveness, recall, cost-optimality
or paper-novelty claim. This is not an equivalent ReAct/SWE-Search comparison or
a cheap-versus-strong model evaluation. Six arms are not twelve independent
repository samples.

Production Scout already has opt-in `followup_import_context` and explicit
`definition(Class.method)` acquisition through cached import hints. Those tools
were outside this study's fixed three-action menu. The thin-shim result therefore
does not demonstrate that the production reader lacks reexport support, and no
new resolver is justified merely by this restricted experiment.

**Do not promote learned evidence selection into default Scout routing on these
results.** Keep simple existing behavior while improving a specific demonstrated
source/native bottleneck. Any future function-aware or contract-boundary study
needs a fresh prospective cohort and comparable evidence/action capacity; it
must retain this completed null/negative result instead of silently replacing it.

## Subsequent prior-art and metric check, 2026-10-19

This is preparation for a different comparison, not another v2 case or a
reinterpretation of its results.

- [Agent Retrieval Bench](https://arxiv.org/html/2607.24882v1) already evaluates
  workflow-dependent next-context retrieval, abstention and budgeted exposure.
  Its file-level scores explicitly do not establish useful-span localization or
  test-passing repair. Reuse its public lexical/BM25/RepoMap controls rather than
  treating next-file selection as new.
- [SWE-Explore](https://arxiv.org/abs/2606.07297) already evaluates ranked code
  regions under line budgets and connects exploration with downstream repair.
  Moving from files to spans alone is therefore not a sufficient novelty claim.
- [CAM-DF](https://arxiv.org/html/2607.27083v1) studies cost-aware stopping over
  ranked tool prefixes before execution. Its stated setting does not adapt the
  prefix after receiving tool outputs; that distinction is not evidence that an
  output-adaptive alternative would outperform it.
- [SWE-Next](https://arxiv.org/html/2603.20691v1) combines executable base/fixed
  comparisons with reusable repository/time environment profiles. Environment
  reuse and strict improvement checks are also established prior work, not new
  contributions merely because Scout implements them.

Local feasibility check: official ARB code at
[`07014c9`](https://github.com/eyuansu62/agent-retrieval-bench/tree/07014c986f3deadb1548c62b32c0ffbe6a81465d)
passed its three BCY-curve and one context-cost test methods on native Windows.
No full dataset or published leaderboard was rerun. A deliberately known-source
boundary probe used the real pinned vLLM `reload/layerwise.py`: a header plus one
content token earns file-exposure credit while leaving the requested restore
definition at line 417 unseen. The 16-content-token sensitivity does not give
credit. This reproduces documented metric semantics, not an ARB defect, a
benchmark sample, a new metric or a downstream performance result.

The remaining research question is conditional: can output-adaptive acquisition
reach a **baseline-discriminating, controls-preserving native witness**, or a
supported rejection, at lower total cost without increasing audited misses?
Our recent owner-reviewed counterexamples motivate that question but cannot
answer it prospectively. Do not replace file exposure with another unvalidated
proxy and declare success.

A fresh comparison must retain the existing null result; predeclare admissions
before outcomes; give rule, direct-model and layered-model arms comparable
actions and budgets; separate setup from per-case execution; and audit missed
defects independently of arm labels. An actual sequential tool-use baseline is
needed, not a renamed two-ID selector. Available provider names are not a
verified cheap/strong ordering. Existing-method implementation, pricing,
sampling realization, native-action availability and blinded assessment still
need qualification. Do not open a replacement cohort until those choices are
executable; the present check makes no efficacy or paper-ready claim.

## External baseline replication and repair, 2026-10-19

The published `v2_trace2code` release was acquired at dataset revision
`5901e1ee3aff048290db72edf9c63bc498b79ea3`, with its published checksum checked
against the 39,295,446-byte archive (SHA256
`19b252e8cfff42107fedc74005dbb6972f2970af33651ce0c1571546819e41c4`).
Extraction checked paths, regular-file types and expansion bounds first. The
release contains 101 samples from seven repositories and 98 corpus snapshots;
56 samples are Gin and 26 Click. It is not a vLLM/GPU discovery population.

Unmodified toolkit `07014c9` was run on the complete subset with `all_files`,
no keep-list filtering and default parameters on native Windows/Python 3.14.
All three controls evaluated 101 rows without skips:

| Control | Recall@20 | MRR |
| --- | ---: | ---: |
| Lexical | 0.696370 | 0.207453 |
| BM25 | 0.493399 | 0.163848 |
| RepoMap, process hash seed 0 | 0.836634 | 0.270631 |
| RepoMap, process hash seed 1 | 0.836634 | 0.274988 |

Lexical agrees with the published subset table to four decimal places. RepoMap
does not reproduce one stable ranking: 94 of its 101 detail rows differ between
the two seeds. A separate capped-symbol witness also produces different graphs.
The cause is set-dependent tie selection before the reference cap, plus
normalized-name overwrites and unordered traversal. A final score/path sort
does not undo those upstream differences.

The proposed repair is [ARB PR #3](https://github.com/eyuansu62/agent-retrieval-bench/pull/3),
head `dda9cc25b665581270423d7e5f3b337db6c1cf55`. Its matched-count-priority
control and hash-seed regression pass; the original fails the regression on
Windows and Linux. The related Windows groups pass 23 tests. An independent
offline Linux CPU sandbox passes 22 with one missing-Git skip. Both sandbox
containers were removed and sessions released. Full Windows discovery retains
14 pre-existing failures and 11 skips; original-source comparison reproduces
those failures plus the three failing regression seed subcases. This is not a
claim of a clean full Linux suite or maintainer CI.

The first narrow fix stabilized rankings and aggregate metrics, but left one
snapshot's edge counts/scores seed-dependent. That intermediate result is kept,
not promoted. With the complete proposed fix, the two 101-row detail files are
byte-identical (SHA256
`36836759d454f13909b6495d4d16f506b777097f9fbd263ada526c71847e1c9a`),
with Recall@20 0.846535 and MRR 0.272324. Those changed values are not an accuracy
improvement claim or an exact reconstruction of the author's historical run.
All original and intermediate outputs remain local. No paid model calls, GPU
use, embedding downloads or changes to the completed v2 study were involved.

ARB also ships an output-interleaved `list_dir`/`grep`/`read_file`/`submit`
protocol. Its existence further rules out treating sequential context selection
alone as our contribution. Qualify that existing control and native-witness
availability before a new prospective comparison; do not turn this baseline
maintenance PR into evidence that Scout improves discovery yield or cost.

### Scripted read-budget invariant and existing agent controls

Qualifying the existing sequential control exposed a separate defect in pinned
`07014c9`: its scripted policy charges a token-limited read but scores the first
20,000 characters of the original text. A native counterexample keeps grep hits,
actual read observations and charged budgets identical while changing only an
unobserved suffix; the old final selection changes. Both the per-file limit and
remaining-total limit fail this invariant. A visible-suffix positive control
continues to change selection when the larger budget actually exposes it.

[ARB PR #4](https://github.com/eyuansu62/agent-retrieval-bench/pull/4), head
`c44bb2b18d769df0deca950e589fb29f0982a1d7`, reuses the existing `token_prefix`
boundary for scoring and preserves the character ceiling and ranking weights.
All 14 tests in the contributed file pass on Windows/Python 3.14 and offline
Linux/Python 3.12; the original module fails the two hidden-suffix subcases.
The Linux comparison also includes two private diagnostic controls (16 methods
total), not 16 upstream test methods. Containers were removed and sessions
released. These focused checks do not qualify the full suite or maintainer CI.

At 16 calls, eight grep calls, 8,000 total read tokens and 1,200 tokens per file,
paired original/fixed scripted runs evaluate all 101 released trace2code cases
without skips. Every non-latency detail field, trace, final selection and
aggregate metric is unchanged. Both have final-file F1 0.099670 and final-any-gold
rate 0.198020. Preserve this null result: the synthetic witness establishes a
real budget-boundary defect, not measured accuracy or discovery improvement on
this population. Grep/path candidate information and file-exposure metrics have
other semantics; this fix is not a certificate that all information access or
useful-span/native-witness credit is matched across arms.

Related implementations already cover much of the proposed layering:

- [Oko's ARB report](https://github.com/eyuansu62/agent-retrieval-bench/issues/1)
  combines keyword candidate retrieval with a Jev reranker. Its reported scores
  are author measurements, not independently replicated here.
- [Oko's public experiment protocol](https://github.com/bartlomein/oko/blob/main/scripts/benchmark-public/README.md)
  already separates setup/query cost and uses paired agent/edit validation.
  Classifier-assisted retrieval and matched agent evaluation are not novelty
  merely because Scout adopts them.
- [The CodeNib adapter discussion](https://github.com/eyuansu62/agent-retrieval-bench/issues/2)
  distinguishes released-corpus access from full-source indexing and proposes
  matched agent budgets. Its adapter smoke is not a full quality result.

No Oko/Jev/model service was called or rescored in this check. The next research
decision remains to qualify a native-capable sequential comparison and total
cost before enrolling a fresh prospective cohort; these known controls must not
be relabeled as held-out discoveries or evidence of paper-ready novelty.

### Cold-cache companion-selection feasibility: negative development result

A later real Scout packet at vLLM `2cea893821861c1007b3c7f1da44f9774bb0c18c`
paired `kv_offload/tiering/p2p/data/nixl.py` with an unrelated EC-connector NIXL
test. The basename selector missed the differently named P2P data-transport
test. A cache-only direct-import prototype passed 199 affected Windows checks,
but replaying the original packet's observed cache did **not** improve selection:
all seven component test bodies were absent; the prototype made eight bounded
cache lookups and returned the same unrelated test. No cache was warmed, source
fetched or model called for this replay. Warm synthetic cases are not evidence
that the cold production packet improves. The prototype was not deployed.

The corresponding close hypothesis also needed caller evidence, not a stronger
ranking score: the manager already wait-cancels and polls for up to three seconds
before a deliberate forced timeout teardown. That rebuts an absent-drain premise
without establishing timeout DMA safety. The private native environment lacked
NIXL and accessible IB device nodes, so the 56 passing mocked upstream transport
tests cannot settle native quiescence or justify a repair. Keep the lead
inconclusive pending the exact transport/version and a supported surviving-buffer
path; neither an indefinite wait nor a mock that assumes cancellation is proof.

This is a known development case, not a new prospective cohort or a measured
recall/PR-conversion result. Before further selector work, check whether its
required evidence is actually available at decision time; any cold-source
acquisition must retain and account for the existing companion-read budget.

### Native-capable sequential control: bounded component preparation, 2026-10-20

ARB's released closed-tool protocol intentionally excludes native tests. Adding
a test command would change that action space, not reproduce its unmodified
baseline. The next preparation therefore examined the actual
[mini-SWE-agent loop and environment protocol](https://github.com/SWE-agent/mini-swe-agent/tree/04d809ceab9df28f9adaed044884180159172930/src/minisweagent)
at `04d809c`. Its environment interface permits an explicit execution adapter;
its published local and Docker environments do not become sandboxed simply
because the controller limits model steps.

An initial task-private Linux local-driver canary failed when its finite test
model exhausted its scripted outputs. No target assertions or per-action trace
were retained, so do not invent a direct traceback diagnosis from that run.
Separate fixed shell controls then established an infrastructure mechanism:
setting `RLIMIT_NPROC=64` on the parent before its child launch produced EAGAIN
under a shared real UID; the same primitive without that new per-UID limit
succeeded. Setting it only inside an already-created child did not reproduce the
parent-spawn failure and was not an adequate control. This explains a possible
failure path, not an observed verdict for each lost action. The original attempt
remains terminal; its budget was not silently relaxed and rerun.

The [public component canary](../../examples/native-agent-loop/README.md) instead
keeps the unchanged upstream `DefaultAgent` and deterministic test model on the
trusted controller, with an explicitly custom `Environment` forwarding only
reviewed fixed commands to the existing CPU sandbox. This avoids installing
controller dependencies in its minimal image or replacing per-task cgroup
isolation with a shared-UID limit. It is not an unmodified LocalEnvironment or
DockerEnvironment comparison: each command starts a fresh container and only
regular workspace files persist.

The public canary completed five sandbox invocations / four scripted queries.
It observed one known synthetic control pass and one intentional boundary
failure, checked that the failure reached the next query, submitted through the
real loop, checked a one-query stop, and classified an owned timeout as
infrastructure rather than a target result. Broker records confirm offline,
nonroot, read-only-root execution with 512 MiB and 64-task cgroups, all five
container removals and session release. Raw module hashes and trajectories were
retained; selected source files remained unchanged. A private sandbox canary and
a public run before renaming the intentionally failing fixture outside ordinary
test discovery are separate development work, not additional study slots. The
final renamed example was rechecked in a fresh session, without replaying an
uncertain attempt or rewriting the earlier captures.
The first public-file syntax check also caught an extra parenthesis before any
execution; it was repaired before this run, not counted as a target failure.

There were **zero real model/provider calls**. The upstream `api_calls` field
counts deterministic test-model queries here. This known fixture establishes
neither discovery quality nor a tested provider's action parsing. Controller
dependencies were observed, not qualified as a complete official installation.
The local execution interval excludes earlier setup, diagnosis and owner effort;
pricing and total-cost comparison remain incomplete. Stdout/stderr concatenation
also does not establish mixed-stream chronology equivalence.

Keep the completed v2 null result unchanged. Before a fresh cohort, qualify the
actual provider/tool realization, comparable action and budget capacity, target
dependency availability, full cost accounting and arm-blinded miss auditing.
This component capability removes one concrete feasibility uncertainty; it is
not a research effectiveness result or justification to promote learned routing.

### Real-provider feedback compatibility: known-fixture check, 2026-10-20

A separate, one-shot private check subsequently replaced the scripted model
with the existing Scout tool-free HTTP backend. The unchanged upstream
`DefaultAgent`, text-action parser and observation formatter consumed three
actual responses. The controller accepted only the three reviewed source-read,
unittest and submission commands in that fixed order. The third real request
contained the native return code 1 and both test outcomes; its response correctly
named the passing control and failing exclusive-end witness before submitting.
All three containers were removed, the session was released, and the 16 reviewed
upstream module hashes remained unchanged. The no-model public example itself
was not modified or relabeled as this run.

The gateway reported 1,592 input and 292 output tokens (1,884 inclusive total)
across three accepted responses. Cached input was reported as 0, unknown and 320
respectively; do not treat the unknown as zero or infer a monetary cost from
these counts. The measured agent-loop interval was 8.32 seconds, excluding prior
source/dependency/adapter preparation, review and final session release. Provider
pricing and total owner cost remain unknown; the upstream accumulator's zero is
an unpriced placeholder, not free inference. There were no retries. Private
requests, responses, trajectories and broker records are retained outside Git;
provider connection configuration is not published.

This qualifies our explicit **text compatibility adapter**, not the upstream
recommended provider-native function-calling path, arbitrary generated command
execution, or a full official upstream installation. The provider was given the
known task and exact command order: this tests neither action selection nor bug
discovery. It does not add a prospective sample, change the completed v2 null
result, support an efficacy/cost-saving claim, or remove the remaining matched
action-capacity, cost-accounting and blinded-audit requirements for a new cohort.
