# Cheap native observation versus another model decision

One development counterexample, not a new Humanize bug, PR or paper result.
The historical repair is
[`392aef7`](https://github.com/python-humanize/humanize/commit/392aef707c0e74341ab4a51420984e9ea6b566c5),
whose parent is `ca892b368a535a79cc5e2181d052245b94fd6652`.

## Independent native admission

Normal Hatch/VCS wheels were built from separate LF/raw-Git worktrees and
unpacked into private import roots. Six production Python files matched their
Git blobs; the generated version file was not fabricated. On Windows
CPython 3.14.3 / pytest 9.1.1, the **same head**
`tests/test_time.py::test_naturaldelta` ran on both packages:

| Revision | Passed | Assertion failures | Skipped/errors |
| --- | ---: | ---: | ---: |
| Parent | 37 | 2 | 0 |
| Repair | 39 | 0 | 0 |

The public call is `humanize.naturaldelta(timedelta(days=365*x))`, with default
English locale and `x=[2.4,2.6,2.9,3]`. Parent outputs are `2,2,2,3 years`;
repair outputs are `2,3,3,3 years`. The 7-day control passes in both.

With an already prepared exact package, start a fresh process per revision:

```text
python -B examples/scout-evidence-humanize/observe.py --package PRIVATE_PACKAGE_ROOT --arm parent
python -B examples/scout-evidence-humanize/observe.py --package OTHER_PRIVATE_PACKAGE_ROOT --arm head
```

This installs nothing and checks the six recorded module identities before
importing. It does not reconstruct a wheel, validate all package data, run the
upstream suite or establish other runtimes/locales. For the original selected
test, run `python -B -m pytest HEAD_TEST_ROOT/test_time.py::test_naturaldelta`
with that arm's package first on `PYTHONPATH`, the same private pytest/freezegun
dependencies, and plugin autoload disabled. Preserve the parent's failures.

## Model observation pilot

The initial source window was lines 141–220 and identical between revisions.
**The owner chose this view after seeing the repair and native outcomes.**
Only model calls were fresh/frozen prospectively: this is not an unseen-owner
cohort or a representative sample of live Scout inputs. The metadata draw used
the first eligible repair in 60 reachable single-parent commits at `785e5dcc`.

Four arms used a common stateless MiniMax-M3 final reviewer, two reviews per
revision: no extra evidence; actual `first_catalog_continuation` (lines 221–300,
at most 80 lines/4500 characters); a fixed fresh native public-call observation;
and MiniMax-M3 choosing `tail`, revision-local `tests`, `native` or `abstain`.
Selector rationale/arm labels never reached the final reviewer. Requests were
randomized with seed 20261016. Repeated identical requests are variability
checks, **not independent defects**. Native probes were fresh, not oracle-cache
latency counterfactuals.

| Arm | Valid / 4 | Exact correct / 4 | Diagnostic alias-vector correct / 4 |
| --- | ---: | ---: | ---: |
| No extra evidence | 1 | 1 | 1 |
| Rule continuation | 1 | 0 | 2 |
| Fixed native | 3 | 3 | 4 |
| Model-selected observation | 2 | 1 | 2 |

The frozen answer schema required `values` with four literal strings and allowed
an optional bounded reason. Seven answers used `answer`/`answers` instead;
one included extra text and one exceeded the reason bound. Alias/first-JSON-prefix
counts diagnose interface burden; they **do not repair or replace** the frozen
scores. Correct explanatory prose never overrides a wrong output vector.
The selector chose tail for the parent and native for the repair.

All 18 provider envelopes reported final usage: 29,006 inclusive tokens and
51.83 seconds summed client call time. Three additional native observation
processes took 0.558 seconds total. These are different cost components, not a
priced matched-budget comparison. Clone/build/setup costs remain separate;
the original parent admission process wall and total owner effort are unknown.

## Failures and scope

A nonshallow partial clone lacked a historical blob. Its failed draw was kept;
one new full clone used the **same** ref/frame, not a replacement repair. The
admission reporter also omitted `expected_tests` after the parent completed;
the saved report was parsed offline and only the unused head arm executed.
Neither failure is counted as free or erased from admission. The earlier
unavailable Humanize/validators cohort remains unavailable.

This single related group does not justify learned routing, PR-conversion,
recall, generalization or paper claims. Independent strong-provider and complete
applicable published-method controls are still missing. The useful next question
is whether deterministic report handling can eliminate model readback for cheap
observable facts, while reserving model review for contracts and repair design.
Any fresh study must separate transport/schema validity from evidence quality
before calls; do not rescore these exposed inputs as a prospective win.

The [small observation snapshot](observed.json) is sanitized; raw provider logs,
credentials and machine/private paths are deliberately not published.
The [exact prompt templates, view construction and call order](comparison_protocol.json)
allow a separately costed reproduction with an authorized MiniMax account.
Reconstruct source windows from the public commits; the protocol's `initial.text`
field is a reconstruction instruction, **not** text sent to the model. No example
silently obtains credentials or purchases model calls. A reproduced stochastic
answer is not guaranteed, and exposed repeats cannot become new holdout cases.
