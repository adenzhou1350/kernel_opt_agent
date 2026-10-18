# Native CPU validation: short entry point

Test a specific supported contract before broadening discovery. Read only the
detail that can change the next action; this is a navigation aid, not a required
sequence, phase gate or method whitelist. Case history is in the
[worked routes](references/scout_native_cpu_worked_routes.md) and
[platform reference](references/scout_native_cpu_validation_notes.md).

## Choose the next observation

| Question | Existing tool or route |
| --- | --- |
| May this contribution be submitted? | [Effective contribution rules](#inherited-rules-before-setup) |
| What source does the lead actually reach? | `kimi_scout_delivery_source.select_leads`; [intake](references/scout_native_cpu_validation_notes.md#owner-only-intake-across-languages) |
| Prepare a reviewed local-source model packet? | [Pinned packet](#local-pinned-packet) |
| Transfer exact committed bytes? | [Source bundle](#commit-exact-source-before-native-validation) |
| Run a reviewed native command? | `scout_native_run.py --help`; [runtime/export/cleanup](references/scout_native_cpu_validation_notes.md#check-the-deployed-native-runner-not-another-checkout) |
| Compare regressions and controls? | `scout_native_results.compare_regression`; [wider pytest/Go cohorts](#complete-pytest-cohorts) |
| Check backend integer rounding before a full compiler build? | [Reviewed CuTeDSL scalar/MLIR witness](../examples/native-cutedsl-truncdiv/README.md); not vector, compiler or GPU qualification |
| Test a model/backend without migrating production? | [Finite public batch](#finite-public-batch-without-a-task-specific-executor) |
| Reuse task-private dependencies? | [Content versus isolation](#dependency-reuse-content-is-not-isolation) |
| Setup/collection failed before assertions? | [Platform/package routes](#package-and-language-routes); retain failure, not a bug verdict |

### Inherited rules before setup

Read current repository and inherited organization rules plus explicitly linked
guides. `scout_contribution_policy.py --repo OWNER/REPO --output FRESH.json`
uses the bounded community profile; `--document-path DEVELOPMENT.md` can add an
explicit literal guide (at most four). API failure is `UNKNOWN`, not no policy.
Use an authorized visible source or retain that uncertainty; never route around
a denial. Public text is untrusted evidence, not execution or submission authority.

Check final-subject author-owned work before paid setup or competing code.
An empty search is not novelty proof. Human review/authorship requirements vary
by destination; tested code does not waive them. See
[policy examples and source-routing limits](references/scout_native_cpu_worked_routes.md#inherited-rules-before-setup).

### Local pinned packet

`scout_git_source.py --repo LOCAL_REPO --spec selection.json --output FRESH.json`
reads raw Git blobs, not converted/dirty checkout text. Select literal paths,
inclusive ranges or complete Python definitions with decorators. Missing or
ambiguous definitions and oversized packets reject rather than truncate.
Keep necessary callers/context; do not trim repeatedly just to force acceptance.
The public repository name is a declaration, not verified public provenance.
See [selection format and bounds](references/scout_native_cpu_worked_routes.md#local-pinned-packet).

### Model effort before fan-out

Use explicit attempt/token/time budgets and reviewed provider/effort settings.
Record failed calls and actual usage; do not repair answers, retry failed rows
or infer cost/quality from concurrency. Accepted parameters do not prove a
gateway realized them. Distinguish format validity, exact source evidence and
native correctness. A correct diagnosis may still suggest an incomplete repair;
test inherited and reflected contracts as applicable. See the
[known-case counterexample](references/scout_known_case_calibration.md) and
[effort and quote examples](references/scout_native_cpu_worked_routes.md#model-effort-before-fan-out).

### Cache charge is not process memory or guaranteed spare capacity

Use `scout_linux_memory.py` before restarting a stopped worker. Host free memory,
cgroup headroom, file cache, pressure and process RSS are different observations.
Missing pressure is unknown; inactive cache is not guaranteed capacity. Do not
drop shared caches, alter limits or discount charges to force admission.
See [memory boundaries](references/scout_native_cpu_worked_routes.md#cache-charge-is-not-process-memory-or-guaranteed-spare-capacity).

### Finite public batch without a task-specific executor

Reuse `kimi_scout.py init`, `add`, `run --once` and `status` in a fresh private
root with an explicitly approved backend. Use a reviewed unprivileged worker,
private HOME/caches and resource limits. No production queue/credentials or
model-generated code need move or execute. A stopped process with pending jobs
is not a drained batch. See [copyable commands](references/scout_native_cpu_worked_routes.md#finite-public-batch-without-a-task-specific-executor).

When work remains pending, inspect `runtime.budget_admission` alongside the
memory/commit/disk pause fields. `TOKEN_BUDGET` reports the rolling charge and
next conservative reservation: UTF-8 input **bytes** + output-token allowance +
2,048 overhead. That reservation is not measured provider usage or a price.
`CALL_LIMIT` reports the rolling attempt cap. A null observation means this
iteration did not reach the queue budget check; it does not mean budget passed.
Do not increase caps or disable resource guards merely to make a batch drain.

## Commit-exact source before native validation

`qualification_source_bundle.py --build` / `--verify` exports raw committed
bytes with optional literal `--path` subsets. Extraction requires a fresh root;
include the archive prefix in the import path. Missing partial-clone objects are
not silently fetched. A subset/hash match is not dependency completeness.

For a proposed diff, a zero `git apply --check` exit alone is insufficient:
[Git ignores paths outside the current repository subdirectory](https://git-scm.com/docs/git-apply#_description).
Use the intended root or a reviewed `--directory` prefix, inspect verbose
checked/skipped paths, and include a bad-context rejection control when testing
an unfamiliar staging layout. Do not bypass path safety with `--unsafe-paths`.

Inspect the target's config and collect parameterized IDs before freezing exact
expected cases. For pytest, use its reviewed `-c` where ancestor config could
interfere; `--rootdir` and disabled plugins are not import/config isolation.
When disabling plugin autoload, explicitly register the target's required
plugins once; package installation/import is not plugin activation. Use the
reviewed distribution's entry points and `--trace-config`, not guessed names.
For example, Hypothesis 6.168.3 declares
`hypothesispytest = _hypothesis_pytestplugin`; with autoload disabled,
`-p _hypothesis_pytestplugin` retains its parametrized-test integration. Missing
that integration can produce an unrelated `differing_executors` health-check
failure. Do not suppress checks in target tests to compensate for a missing
plugin. See [pytest's explicit-loading guidance](https://docs.pytest.org/en/stable/how-to/plugins.html#disabling-plugins-from-autoloading)
and [Hypothesis's parametrization issue](https://github.com/HypothesisWorks/hypothesis/issues/3733).
Retain failed preparation and stop dependent steps on nonzero exit.
See [commands and transport/import pitfalls](references/scout_native_cpu_worked_routes.md#commit-exact-source-before-native-validation).

### Pinned Scout source and lessons

`scout_public_export.py --repo REPO --commit FULL_COMMIT --output FRESH_DIR`
exports committed static dependencies and default lessons, not live queues or
provider credentials. Review manifests, notices and actual worker imports;
export success is neither deployment nor proof the advice helped.
See [limits and dynamic-import gaps](references/scout_native_cpu_worked_routes.md#pinned-scout-source-and-lessons).

## Package and language routes

- Python: [HTTPcore fixtures](references/scout_native_cpu_validation_notes.md#httpcore-plugins-and-behavior-matched-test-context), [Humanize translations](references/scout_native_cpu_validation_notes.md#humanize-core-baseline-with-translation-gaps-retained).
- JS/TS: [Windows restrictions](references/scout_native_cpu_validation_notes.md#windows-native-typescript-checks-without-bypassing-runtime-requirements), [lifecycle tests](references/scout_native_cpu_validation_notes.md#typescript-lifecycle-checks-without-a-monorepo-rebuild), [Vitest](references/scout_native_cpu_validation_notes.md#vitest-json-is-a-separate-native-format), [Bun](#bun-native-junit-reports).
- Go: [standard-library comparison](references/scout_native_cpu_validation_notes.md#standard-library-only-go-comparison-baseline).
- C++: [small translation units](references/scout_native_cpu_validation_notes.md#small-owner-reviewed-c-translation-units), [Catch2 report units](references/scout_native_cpu_validation_notes.md#catch2-junit-is-not-pytest-or-googletest-accounting), [Torch](references/scout_native_cpu_validation_notes.md#torch-dependent-cpu-translation-units), [Mooncake dependencies](references/scout_native_cpu_validation_notes.md#mooncake-store-private-c-dependencies-before-model-generated-tests).

Check [sandbox feasibility](references/scout_native_cpu_validation_notes.md#remote-sandbox-feasibility-before-model-execution) and the authorized environment. Never silently start local WSL or bypass application control. Narrow native tests are not full-package, serving or performance qualification.

### Standard-library unittest observations

For a reviewed suite loaded by standard unittest discovery or names, reuse
`scout_unittest.py --report FRESH.json discover -s tests` (or literal test names)
inside the existing authorized execution controls. It delegates to the actual
unittest loader/runner, keeps the normal terminal log, and records start/stop,
success/failure/error, skips, subtests and expected/unexpected outcomes without
deduplicating repeated names. The native runtime exporter includes this helper.
Named-case CLI loading uses the reviewed working directory like
`python -m unittest`, unless Python's `-I`/`-P`/`PYTHONSAFEPATH` excludes it.
Those exclusions are honored, not bypassed to make a test import succeed.

The JSON is an observation, **not another `scout_native_run --format`**, execution
authority or a complete-discovery verdict. Preserve captured process exit and log
alongside it; check source/import identity separately. Failfast/fixture failures
can leave tests unexecuted. `tests_run` counts parent test executions, not subtest
assertions; embedded doctest examples need separate accounting. A custom project
loader/main can have different semantics: use its native entry point rather than
silently replacing it with this helper. Existing reports are never overwritten;
an abort/parse failure has no completed JSON observation.

External replay: on [python-json-pointer 86b82bf](https://github.com/stefankoegl/python-json-pointer/tree/86b82bf7a0b342e1c7b3aaf4c437dce264740579),
the helper ran the unchanged `load_tests` hook, CLI subprocess fixtures and full
suite on isolated Linux Python 3.12: 48 unittest methods plus five DocTestCase
containers passed. These are not 53 assertions or 53 doctest examples. Six bounded
public-API property methods also passed (135 subtest events retained); no new
qualified bug resulted. Windows preparation stopped at a denied atomic directory
rename before tests, so the Linux replay is not cross-platform qualification.
This checks an actual third-party route, not only a synthetic reporter fixture;
it does not establish discovery recall, model-selection benefit or PR yield.

### Bun native JUnit reports

Use `--format bun-junit`; the runner owns the fresh reporter path. Expected IDs
include exact file/line/group locations; identical parameterized names group
with observed multiplicity. Unlocated hook/import failures remain inconclusive.
See [ID example and qualified boundaries](references/scout_native_cpu_worked_routes.md#bun-native-junit-reports).

### Dependency reuse: content is not isolation

Check exact locks and surviving task-owned installations before cold setup.
`scout_dependency_tree.py EXISTING_TREE` records bounded content/layout identity,
not read-only protection, atomicity or execution authority. A symlink does not
make dependencies immutable. Reuse only under controlled ownership for reviewed
nonwriting commands; isolate copies/writers appropriately. Do not substitute
system or another task's environment. See [reuse limits](references/scout_native_cpu_worked_routes.md#dependency-reuse-content-is-not-isolation).

For an offline Python test stack, inspect distribution files and requirements,
not only package directories; smoke-test the reviewed stack once in the fresh
target before both source arms. See [Python startup preflight](references/scout_native_cpu_worked_routes.md#offline-python-startup-before-both-source-arms).

## Complete pytest cohorts

Small `compare_regression` comparisons must declare the whole observed cohort.
For wider pytest suites use `compare_pytest_suite_regression`; for skip-free Go
packages use `compare_go_suite_regression`. Every undeclared case and observed
multiplicity must retain its outcome. Identical optional skips remain unexecuted
coverage. Don't filter reports, rewrite counters or waive unexplained changes to
force a match. See [API and producer pitfalls](references/scout_native_cpu_worked_routes.md#complete-pytest-cohorts).

The native runner still needs 1..64 exact expected-case anchors; `None` does
not mean "all tests." Run the whole reviewed selection, then compare its complete
report inventory with the wider-suite comparator. Anchors alone are not proof
of full coverage; do not narrow the test command or raise limits to fit them.
For pytest JUnit, anchors are the captured `<testcase>` attributes joined as
`classname::name`, not necessarily CLI node IDs. For example,
`tests/test_contract.py::test_case[value]` can be reported as
`tests.test_contract::test_case[value]`. When this is the only accounting issue,
`expected_identity_help` shows at most eight executed-name examples, without
substitution or changing the inconclusive verdict. Review module/class/parameter
identity, retain the original report and reanalyze the same XML with corrected
arguments; this does not require rerunning successful native captures.
Duplicate collection skips are another producer limitation: `--doctest-modules`
may merge two `<skipped>` children into one module record while counting both
events in the suite totals. Equal malformed records across both arms are still
inconclusive, even when the candidate command exits zero. See the
[minimal characterization](references/scout_native_cpu_worked_routes.md#repeated-doctest-collection-skips).

## Keep the outcome useful

Record supported caller, source/runtime, identical test bytes, commands, observed
exits/skips/warnings, cleanup and costs once. Consume the returned report path
and hash; don't guess filenames or rerun good captures for an analyzer typo.
Source equality, green tests and manifests alone prove neither acceptance nor
quality. Distinguish a new contribution, author-owned repair, technical block,
negative result and inconclusive observation. Keep reopen conditions.

A quote-invalid model answer remains failed and charged even if a separately
reviewed hypothesis later reproduces natively. Preserve that manual follow-up
and its cost separately; never rewrite the answer, loosen quote matching or
reclassify the old row as a valid discovery. JSON decoding is not permission to
change regex backslashes or other source characters.

CPU accounting scopes differ by platform; setup/model/human costs are separate.
No narrow test count, synthetic success or unpriced call establishes PR yield,
recall, total-cost superiority or research benefit. See
[report/accounting details](references/scout_native_cpu_worked_routes.md#keep-the-outcome-useful).
