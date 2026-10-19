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
