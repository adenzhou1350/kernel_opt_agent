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

A separate finite-choice development check removed the prescribed order. The
same unchanged agent/parser could select any of six reviewed commands: inspect
source or checks, run both native tests or either focused test, and submit.
The real backend chose source inspection, the combined test and submission in
three calls. Both native outcomes reached the final request and were correctly
distinguished; all three containers were removed and the session released.
Reported usage was 2,084 input plus 474 output tokens (2,558 total); cached input
was unknown, unknown and zero. The agent-loop interval was 7.89 seconds,
excluding preparation, review and release; monetary price remains unknown.
This qualifies finite reviewed-action selection without an enforced order,
not provider-native tool calls, arbitrary commands, a general action policy or
better evidence selection. The observed order happens to match the earlier
fixed sequence. It is still the same known synthetic fixture, not a new
prospective case, an equal-budget comparison, a cost advantage or an efficacy
result. The no-model public example and live Scout were not changed.

### Native function-calling path: qualified component, 2026-10-20

A later known-fixture check used the unchanged installed `DefaultAgent`,
`LitellmModel`, native tool-call parser and tool-observation formatter at the
same upstream commit, rather than the Scout text adapter. A raw-Git source
bundle installed mini-SWE-agent 2.4.6 in a fresh private Python 3.12.3 environment.
Its hash-locked base closure had 82 compatible packages, including LiteLLM
1.106.0 and OpenAI 2.54.0. A deny-network import check passed, but the first
actual query failed before transport: providing ordinary function tools caused
LiteLLM to import an MCP module absent from the base closure. Import success
and `pip check` were insufficient execution qualification.

One fresh environment added the declared `litellm[mcp]==1.106.0` extra, producing
96 compatible packages including MCP 2.3.0. All prior package versions stayed
fixed; all 59 installed upstream Python files matched the pinned raw blobs.
This is an explicitly expanded dependency closure, not a claim that the base
installation worked or that all optional extras/upstream tests passed. The two
SDK materializations took 75.92 and 91.78 seconds respectively; their captures
and original sources remain separate.

Two further developmental failures were retained, not relabeled as passes:

- The controller set global `model_fallbacks=[]`, mistakenly treating an empty
  list as disabled. The SDK's `is not None` branch recursively entered its
  fallback path. No provider connection was observed. Changing this controller
  setting to `None` avoided that branch; this was not a mini-SWE-agent repair.
- The next query returned a real native `bash` call, but its command damaged
  nested shell quotes. The literal whitelist rejected it before execution. This
  response reported 695 tokens. No controller silently repaired its command.

The final check used quote-free literal helper commands with the same six
available operations: read subject/checks, run both tests or either focused
test, and submit. No order was prescribed. It chose subject, checks, passing
control, failing boundary, then submission: five returned native tool-call
responses and five sandbox invocations, with exits `[0, 0, 0, 1, 0]`. Independent
inspection matched each parsed command to its unmodified function arguments and
each of the four tool observations to its originating tool-call ID and actual
broker output. The visible final answer correctly distinguished the assertion
failure from infrastructure failure. All containers were removed and the
session released. There was no GPU, local WSL, host-shell fallback or live Scout
mutation. The environment adapter remains explicit, not upstream Docker.

The successful run reported 4,519 prompt plus 1,349 completion tokens (5,868
total), including 3,264 reported cached prompt tokens. Including the rejected
native response gives **6,563 reported development tokens**, not a price or a
matched computation measure. The successful process interval was 28.46 seconds,
including its imports and sandbox preparation but excluding prior source/SDK/
driver work, failed attempts, owner effort and final release. Upstream retry
attempts were configured to one and SDK retries to zero; the retained responses
are not a wire-level audit proving every possible internal HTTP attempt.
Monetary prices and complete development cost remain unknown.

The hard agent limit was five queries, while task text and an outer launch note
retained an older six-query declaration. The run finished within five, but this
developmental mismatch is preserved and must not be presented as a sealed,
budget-matched experiment. Provider-default reasoning also differs from the
earlier text adapter; neither token nor latency differences establish superiority.

This removes the specific uncertainty about native function-call parsing and
feedback consumption. It does **not** qualify arbitrary generated shell actions,
prove a general sequential baseline is matched, add a prospective discovery,
change the v2 null result, or establish recall, PR conversion, cost savings or
paper novelty. Before a fresh cohort, action capacity, consistent budgets,
target dependencies, complete cost and arm-blinded miss auditing still need
qualification. Keep this SDK optional; no LiteLLM dependency was added to the
standard-library Scout runtime.

### Non-menu native-provider repair: known-fixture check, 2026-10-20

The next component check removed the command menu. The same installed, pinned
mini-SWE-agent loop and native `LitellmModel` delegated actions to the shared
`CPUSandboxEnvironment` with explicit dynamic mode. A controller-side observer
retained native responses and reported usage without rewriting commands or
changing the upstream parser/observation formatter. Its serialized config omitted
connection settings. This is an adapted optional controller, not an unmodified
upstream environment or a new default Scout provider.

The model received the **same known synthetic exclusive-slice defect**, its
public behavioral contract and the two seed checks. It could inspect files,
compose stdlib-only commands, create `test_subject.py`, edit `subject.py` and
submit. Seed checks could not be edited. This reused, unblinded task is not a
held-out sample, new finding, leak-free discovery test or extra prospective slot.

One budget object supplied launch/task declarations, the query observer, agent
step/wall limits and sandbox limits: six query attempts, six sandbox commands,
180 decision seconds, at most 30 seconds per request, five seconds per command,
2,048 output tokens per request and 32,768 bytes of prepared messages. A 15,000
reported-token threshold stopped further actions/requests **after** a response;
it is not a pre-reserved hard total-token quota. Unknown usage stopped rather
than counting zero. Upstream retry attempts were one, SDK retries zero and
fallbacks disabled. These settings still do not prove wire-level HTTP attempt
counts or billed monetary cost. No environment repair or install was needed.

The single run returned four native responses and executed four unmodified
commands: inspect, generate/run tests before repair, edit/run tests, and submit.
The generated five tests covered clamping control, interior/exclusive boundary,
empty and single-element slices. The production edit removed the inclusive-end
increment. Seed bytes stayed unchanged. Each of the three tool observations
matched its originating native tool-call ID and actual broker output, and the
final command stopped the loop. All four containers were removed; the owned
session was released. No host-shell fallback, networked test, GPU, local WSL,
production Scout mutation or public PR resulted from this toy check.

All four shell exits were zero, **including the command that observed four
assertion failures**: the model appended `; echo`, masking the failing unittest
exit. The repair command and final submission similarly used shell composition.
The controller did not silently rewrite them or equate shell success with test
success. After full owner review of the small generated source/test files, the
existing `SandboxCPU` ran identical test bytes against original and repaired
sources in two new checkpoint/restore CPU sessions. Both ran five tests: original
exit one/four assertion failures, repaired exit zero/no failures; neither had
errors or skips. Input hashes, isolation, persistence, cleanup and release
matched. This is the independent evidence for this particular repair, not the
model's summary or its shell return code. Added protocol controls preserve the
exit/summary contradiction and missing-structured-summary rejection behavior;
those controls are not additional live-model or HTTP simulation samples.

Returned usage was 8,131 input plus 1,847 output tokens (9,978 total), including
3,648 cached input tokens. Reasoning counters were a subset of output and were
not added again. The decision interval was 23.55 seconds, excluding earlier
SDK/source/controller development, owner review, the independent comparison and
final release. The comparison used two additional CPU commands. Monetary price
and complete development cost remain unknown; an SDK cost placeholder of zero
does not mean free inference. Differences from earlier finite-action checks are
not an effectiveness, latency or cost comparison.

This qualifies a real provider's autonomous command/test/edit mechanics on one
known fixture under a consistent declared budget. It closes that specific
component gap, but does not establish effective evidence selection, recall,
PR conversion, full target-package validation or paper novelty. The completed
source-inception v2 null result remains unchanged. A fresh prospective comparison
still needs matched action/dependency capacity, complete accounting, baselines
and arm-blinded miss auditing; this successful toy run does not substitute for
those requirements.

### Full-package execution capacity: existing Pluggy pin, 2026-10-20

After the small repair component check, the same offline CPU sandbox ran
Pluggy's **complete default pytest testpaths**, rather than another synthetic
function or only its hookcaller companion. This reused the already owner-exposed
`09fabb162` source and authentic `1.7.1.dev3+g09fabb162` wheel metadata; it is not
a newly enrolled case or a replay of the completed pilot's model predictions.

The existing raw-Git bundler transferred all 80 tracked files (98 archive entries
including directories) and verified their extraction. Fourteen uploaded files,
about 1.95 MB total, contained that
bundle, its verifier, the existing hash-bound offline pytest capsule and target
wheel. The previously qualified loader reconstructed only its bounded regular
package files in memory/tmp storage. No file/resource limits were relaxed, no
dependency was installed and no stubbed version, donor Pluggy subject or source
function extraction replaced the target. Before pytest, module origin pointed
to the pinned raw source; target wheel metadata preceded donor dependencies.

The target `tox.ini`, original conftest and entire default `testing` selection
were retained. With Python 3.12.10/pytest 9.1.1, disabled plugin autoload and cache
provider, the single native command passed **220 tests, zero failures/errors/
skips**. The existing structured JUnit parser independently reconciled all 220
case records and totals, with no accounting issues. All tracked source bytes
remained unchanged; isolation, input hashes, container removal and session
release matched. The preparation/run interval was 8.75 seconds, excluding
earlier wheel/capsule preparation, source review, the first local helper failure
and final release. That helper had pre-created an extraction target which the
existing atomic extractor correctly rejected, before any remote dispatch; its
failure is preserved separately.

This qualifies the full default test selection in this **specific offline
stack**, not official `uv run` dependency groups, benchmark/coverage plugins,
pre-commit, latest main, all Python versions or a package-level autonomous
discovery. No model call or GPU was used. Existing tests passing do not exhaust
the defect inventory, repair the original v2 availability/blinding deviations
or change its null result. Reusing a full target environment closes a concrete
capacity gap; it does not by itself establish equal action capacity, total-cost
advantage, effective evidence selection or paper readiness.

### Second native provider: M3 mechanics, 2026-10-20

Two separately retained format checks preceded one M3 agent run: one through
the installed MiniMax SDK and one through the pinned, unchanged mini-SWE
`LitellmModel` and its real tool parser. Each returned one valid native bash
tool call; neither executed a command. The SDK check observed one HTTP dispatch.
The Mini check used one upstream attempt, zero configured SDK retries and no
fallback; a TCP connection count does not prove HTTP attempt cardinality.
Both retained complete numeric usage, 467 reported tokens per response. For the
SDK response, Messages input/cache-read/cache-create/output counters were
235/202/0/30: input plus output alone (265) is not the total. LiteLLM's prompt
counter was already cache-inclusive; adding its cache subset again would also
be wrong. These checks are not study slots or agent successes.

The subsequent M3 run reused the earlier GLM check's **exact original fixture,
seed bytes, shared CPU environment and budget object**: six queries and commands,
180 decision seconds, 30 seconds/request, five seconds/command, 2,048 output
tokens/request, 32,768 prepared-message bytes and a 15,000 reported-token
post-response stop. The private observer changed only provider loading,
credential-free configuration fingerprinting and the native provider selector.
The pinned mini-SWE agent, tool parser and feedback formatter stayed unchanged;
the provider-specific API translation was LiteLLM's existing implementation.
Authentication traveled to the controller on SSH stdin, not into the sandbox.
No environment install, broker limit change, GPU or local WSL was used.

M3 returned six responses and six autonomous commands, consuming its complete
query/action count. It inspected files, generated tests, repaired the subject,
corrected its own test expectations, checked both source variants, and submitted.
Its **first generated tests contained two incorrect expected values** consistent
with the broken implementation. After observing failures on the repaired source,
it corrected those tests within the original budget; those earlier tests and
failures remain in the trace. The final submission marker had empty summary
text. Several pipelines masked failing unittest exits, and running the seed file
as a script did not discover its tests. Neither zero shell exits nor the final
marker was accepted as a correctness verdict.

After full owner review, the existing independent CPU comparator ran identical
final test bytes on the original and repaired source, using checkpoint/restore
and fresh sessions. Each ran six tests: original exit one/five assertion failures;
repaired exit zero/no failures, errors or skips. Source/test hashes, unchanged
seed bytes, actual native arguments, tool-result IDs, container removal and
session releases matched. These two extra commands, and the review, are separate
from the agent's budget and cost. All owned sessions were released.

The agent reported 14,363 tokens (12,699 input plus 1,664 output), with cached
inputs a subset, not another charge. The two preceding format checks cost 934
additional reported tokens. Its 18.67-second decision interval excludes prior
SDK/controller preparation, format checks, owner review, independent comparison
and release. Prices and complete development cost remain unknown. This is not
a controlled latency, sampling-effort or provider-quality comparison with GLM;
same ceilings do not make realized costs equal.

Both available providers have now exercised native model/action mechanics under
the same declared resource profile, rather than M3 being a text-only comparator.
This closes that preflight gap, not full target-package parity or the research
question. Do not repeat this known synthetic repair as a discovery evaluation.
Next empirical work needs fresh source-inception enrollment, matched runnable
target dependencies, existing-method controls, complete costs and arm-blinded
native adjudication/miss auditing. The earlier two-slot null result is unchanged;
no new discovery, PR, recall improvement or paper-ready result is claimed here.

### Native-eligible production exploration, 2026-10-20

A subsequent production check admitted two adjacent vLLM Rust client files,
`protocol/request.rs` and `protocol/structured_outputs.rs`, at
`b8e9001bf9568c801985889deff34d3b9fe6d0b0`. The same unchanged client crate had
already passed its 136 native library tests. That made investigation feasible;
it did not establish Python-engine integration or a defect in either file.

Seven source-window reviews and one follow-up consumed 42,564 provider-reported
tokens. Six root reviews abstained; one requested more context and its follow-up
also abstained. No failing supported contract, qualified discovery or PR resulted.
The follow-up correctly found that an empty structured-output constraint is
explicitly rejected. The existing native log already includes
`protocol::structured_outputs::tests::structured_outputs_rejects_missing_constraint`
as passed; it was not rerun to manufacture another validation result. A separate
owner source check rejected an earlier control-metadata-loss allegation after
reading the actual Python producers and the Rust wire classification. Neither
check establishes absence of other defects or exhaustive miss coverage.

This was ordinary production exploration, not a registered cohort, randomized
comparison, independent assessor or new v2 slot. Native setup and owner review
costs are separate and incompletely measured; reported tokens are not a price.
Preserve these null outcomes. Native execution capacity alone does not make
fragmented source review useful or cost-effective. A future comparison needs a
real full-file/direct-agent baseline and matched executable actions, rather than
crediting file exposure, concurrency or successful environment setup as findings.

### Real-project direct-tool development stops, 2026-10-20

Tenacity `32ac68f0941319c0d2f4fb927f96e4ee29bb46c6` provided a real small
Python project, not another synthetic repair. The owner had already exposed this
pin on October 18 and identified an author-owned fix in PR722; that defect was
explicitly excluded. These are development observations, **not fresh cohort
enrollment, new v2 slots or independent study results**.

The [native route](scout_native_cpu_worked_routes.md#tracked-links-versus-workspace-persistence)
preserved the complete original linked source and default pytest selection.
It retained a successful CLI run with failed workspace persistence, then a fresh
ephemeral-source run with successful report persistence. The latter's JUnit
case mismatch remains inconclusive; no case totals or tests were rewritten.
A regular-file read view and original archive were supplied to the direct agent;
native checks would reconstruct the original tree, not import that read view.
This is a read-only investigation design, not persistent editable-checkout parity.

The unchanged pinned Mini agent, native tool parser and CPU Environment were used
with actual GLM calls, no automatic retry/fallback, and explicit task/SDK/network
boundaries. Each attempt had ten queries/actions, 360 decision seconds,
45 seconds/request, 15 seconds/command, 3,072 output tokens/request, 98,304
prepared-message bytes and a 60,000 reported-token **post-response** stop.

| Attempt | Changed development condition | Responses / commands | Reported tokens | Terminal observation |
| --- | --- | --- | --- | --- |
| v1 | Initial real-project task | 1 / 0 | 3,969 | Length-truncated reasoning, no tool call; native format failure |
| v2 | Explicitly inspect source before recalling possible bugs | 4 / 3 | 20,695 | Read actual files; next answer again truncated; native format failure |
| v3 | Also forward the already configured `reasoning_effort=low` into native SDK options | 9 / 8 | 67,348 | Post-response token stop before dispatching the ninth proposed command |

The native adapter had omitted the effort field, although the separate Scout
tool-free HTTP adapter already forwarded it. An actual pinned SDK HTTP check
against an owned loopback stand-in distinguished old omission, explicit `low`
and absent-stays-absent controls, with three parsed mock responses and zero model
or target calls. Postman CLI could not start because of a missing packaged
module; no Postman simulation pass is claimed. This proves request serialization,
not the real gateway's internal effort policy or a causal quality/cost effect.

Across all three attempts: **14 provider responses, 92,012 reported tokens,
11 source-reading commands, zero model-issued native assertions and zero
qualified findings/PRs**. All sessions were released. The last response is
charged even though the post-response threshold prevented its action; 60,000
was not a hard pre-request billing limit. Cached inputs are subsets, not extra
tokens; prices, setup/owner time and complete development cost remain unknown.
The v3 observer exited nonzero and produced no accepted final submission.
Do not relabel budget/format stops as `NO_LEAD` or absence of defects, or hide
earlier failures behind the adapter correction. No further same-pin retry was
started. The direct-agent research baseline still lacks a completed real-project
native investigation and matched fresh-source/miss auditing; this is not evidence
that the evidence selector outperforms it or that the project is paper-ready.

One separate owner-issued action then exercised the supplied helper on the
unchanged `TestStatistics` class: all four original tests passed, native imports
resolved to the reconstructed original source, input bytes stayed unchanged,
and report persistence/container removal/session release succeeded. Strict
case accounting accepted that four-case report. This verifies an available
native action, not a model-issued test, repair of the earlier full-suite XML,
new defect or completed autonomous investigation. Its execution/review cost is
additional to the model attempts above.

### Real-project native actions, incomplete investigation, 2026-10-20

A new development task used the complete more-itertools
`4aeb4338ae1407d8da9723e86da99efeb446f719` source with its original docstrings,
tests and contribution policy. It was owner-exposed for the
[native capacity check](scout_native_cpu_worked_routes.md#threaded-suites-task-count-is-not-resident-memory),
not prospectively enrolled. The repository requires production-code examples
for automated bug reports; a contrived witness would not authorize publication.
It was not added to production Scout merely to fill workers.

The unchanged pinned Mini `DefaultAgent`, native `LitellmModel`/tool parser and
CPU sandbox Environment received the entire declared task. The source was
readable; native commands reconstructed and verified the original tree. The task
covered public `peekable`, `seekable` and `SequenceView` semantics, with no
seeded defect, hidden fix, repair or publication authority. Both the full-suite
capacity failures and the supported sequential test route were disclosed.

One attempt had six queries/actions,360 decision seconds,80s/request,
30s/command,8192 output tokens/request,98304 prepared-message bytes and a90000
reported-token post-response stop. Configured low effort was forwarded; there
were no automatic retries/fallbacks. These changed bounds and a new project
are **not** a controlled comparison to the Tenacity attempts above.

The model issued six commands: three source reads, a native deque/Sequence
membership observation with a source grep, an incorrectly located test-helper
call, then a corrected original-test call. The latter ran42 relevant tests,
all passed/no skips. The owner independently retrieved and decompressed the
real observed-runner report; no model paraphrase or shell exit alone was used
as a test verdict. The incorrect command's `tail` pipeline returned0 despite
Python failing to find the helper. All six shell exits being0 is therefore
**not six successful verifications**.

At the six-query limit the native agent returned `LimitsExceeded` with an empty
submission. The outer capture exited0 without group cleanup, but there was no
accepted final investigation, generated defect witness or finding/PR. Do not
relabel this as `NO_LEAD`, absence of bugs or successful task completion. The
original inputs were independently rehashed during export; all remained
unchanged, every action container was removed, and the session was released.
No extra query or owner completion was attached after the declared limit.

Six provider responses consumed28600 inclusive reported tokens; cache reads
remain subsets. The recorded decision interval was20.47s, excluding earlier
native setup/failures, source preparation/transfer, owner adjudication and
release. Prices and complete owner/development costs remain unknown. This
qualifies **model-issued real native actions**, but the direct-agent comparator
still lacks a completed investigation, fresh matched enrollment and miss audit.
Future comparisons must budget the final submission/review explicitly for all
arms, not credit partial source reads or passed controls as discoveries. No new
same-pin retry, extra v2 slot, selector advantage or paper-ready result is claimed.

### Reserved final step, empty submission, 2026-10-21

One additional development task supplied TOMLKit
`eddd27e43a62fe58707c311bfad2f52e72493f53` (0.15.2) and its exact
`toml-test` gitlink `08ed8697864548b3cdb4b8decbf496bef47e1c82`.
The owner had already examined this project; known lookup-rebuild performance
and array-comment defects were explicitly excluded. This is not fresh enrollment,
a replacement v2 slot, or a budget-matched comparison with the attempts above.

The unchanged pinned Mini agent/native tool parser received readable original
source, docs and tests, plus a helper reconstructing the verified original tree
and corpus for native checks. Standard offline pytest dependencies were supplied;
this was not Poetry-lock or official-CI qualification. The task covered documented
Array/Table/document mutation and serialization, without a seeded defect, repair
or publishing authority. An unresolved or no-finding conclusion was allowed.

Bounds were eight queries/actions, 360 decision seconds, 80s/request,
30s/command, 8,192 output tokens/request, 98,304 prepared-message bytes and a
60,000 inclusive reported-token post-response stop. Low effort was forwarded;
there were no retries/fallbacks. The eighth step was explicitly reserved for a
nonempty final submission, with per-query budget reminders. This changes the
task/configuration, not the pinned agent's native tool or submission parser.

The model read the helper, issued five inline exploratory commands, ran the
complete original suite, then printed only the submission marker. Inline outputs
were not controlled defect witnesses: unsupported slice assignment and an
incorrect `str.replace` call raised exceptions, not demonstrated project bugs.
No standalone probe or conclusion file was generated. The helper's native
JUnit/log/import observations independently establish **1,203 passes, no skips,
failures or errors**, with the same complete case inventory as the preparation
run. Selected source hashes and the outer full protected-input audit stayed
unchanged; all eight action containers were removed and the session released.
The command's `tail` pipeline exit alone was not used as the test verdict.

The framework returned `Submitted` with `submission=""`. Its native completion
protocol permits that representation; it is not itself an upstream agent bug.
For this read-only investigation task, however, the requested conclusion and
controlled finding were absent. Record **incomplete task output**, not completed
investigation, valid `NO_LEAD`, absence of defects or a qualified PR. A reserved
step/reminder did not suffice; no rescue call or owner-written answer was added.

Eight responses consumed 29,803 inclusive reported tokens, including cache-read
subsets. The recorded decision interval was 32.92s; earlier preparation/failures,
source transfer, owner review and release are not included. Prices and total
development/owner cost remain unknown. This establishes another real native-action
capability observation and an output-contract failure, not selector superiority
or paper readiness. Future matched comparisons need an independently evaluated
task/output contract shared by the arms, counting incomplete outputs as failures
without requiring every baseline to become successful through repeated retries.

### Nonempty conclusion, unreconciled oracle failure, 2026-10-21

One further **development** task audited the fresh `pypa/packaging` commit
[`ffced26`](https://github.com/pypa/packaging/commit/ffced26d0a30557a0e181dbaca561a0432ddec53),
which adds `Specifier/SpecifierSet.__replace__`. This is not a blinded cohort,
replacement for either v2 slot, or matched comparison with the earlier projects.
The owner inspected the changed source/docs/tests first. The task explicitly
excluded documented unchanged-object aliasing as a supposed bug, and permitted
a no-finding or incomplete conclusion. It granted no repair/publication authority.

The current commit first passed an authentic unchanged native Linux/Python3.12
default suite: **63,239 passes, three Python3.13-only skips**, 431 property tests
default-deselected. Its complete8,375,194-byte JUnit was parsed with an explicit
10MiB budget and independently inventoried; selected source/import identities
were unchanged. This was capacity preparation, not model execution, the full
nox/property/platform matrix or a new defect. The previous commit's baseline was
not silently relabeled as current evidence.

The model received the original source/docs/tests and used the existing pinned
Mini agent/LiteLLM/native tool parser plus offline CPU sandbox. The same declared
eight-query/action,360s decision,80s request,30s command,8,192 output-token,
98,304 message-byte and60,000 inclusive post-response token bounds applied.
There were no retries/fallbacks or rescue query. An opt-in task finish wrapper
now rejects **empty** submissions without granting extra budget or changing the
native parser. A separate seven-command, zero-model scripted canary checked that
behavior. Its first launcher failed before sandbox/model execution because of
an omitted import path; the failure was retained before a fresh corrected run.

The real audit used eight responses and eight commands: **44,952 reported tokens**
(40,521 input,4,431 output;30,592 cached input is a subset, not an extra charge).
The recorded decision interval was47.11s; setup, native baseline, transfer,
release and owner review are additional. Prices and total monetary/owner cost
remain unknown. All eight containers were removed, protected inputs unchanged
and the session released. No empty-submission rejection occurred in this real
attempt, so its nonempty conclusion is not evidence of a causal wrapper benefit.

The generated six-test probe had **five passes and one failure**. Its failing
assertion expected `Specifier(">=1.0").__replace__(operator="~=")` to raise,
although the resulting `~=1.0` is a valid compatible-release specifier. The model
instead retried the *different* invalid `version="1.0.*"` case, then described
the original failure as transient/misattributed in its final `NO_FINDING` text.
That related-case success did not reconcile the saved failing assertion.

Independent owner execution in a **new** isolated container retained the exact
generated probe bytes and reproduced the same5-pass/1-fail result. Two separate
controls passed: valid compatible-release construction/replacement accepts1.5
and rejects2.0; wildcard compatible-release forms correctly raise. The complete
original production package and probe/control input hashes stayed unchanged;
containers and session were released. No production fix, rewrite of the model
probe, or new model call was used to rescue the attempt.

Record **no qualified finding, generated-oracle error, final explanation not
reconciled with native evidence**; do not credit a target bug, completed clean
audit or proof that the package has no bugs. This supports independent review
and exact failure-identity checking, not a new scientific method, selector
superiority, cross-project efficacy, PR conversion or paper readiness.
