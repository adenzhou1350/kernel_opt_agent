# Source-inception v2: first-slot diagnostic result

Protocol: [frozen two-slot pilot v2](scout_source_inception_pilot_v2.md), committed
as `9e016ec7f8d92c90baa0ce3159bb58088a617ea5` before selected source acquisition
and model calls. The second, Pluggy slot remains unexecuted. Original pilot v1
remains frame-incomplete; neither study receives replacement successful examples.

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

## Cost and decision

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
claims. Keep the remaining frozen slot and budget (10 attempts / 57,535 reported
tokens remain); a separate future comparison could examine function-aware source
windows and contract-boundary tests, but cannot replace this outcome. The lesson
update derived **after** the experiment must not leak into its remaining original
arms or be used to rerun this case for a favorable result.
