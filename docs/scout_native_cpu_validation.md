# Native CPU validation: short entry point

Use existing native tools to test a specific contract before broadening Scout
discovery. The [complete reference](references/scout_native_cpu_validation_notes.md)
retains platform restrictions, historical failures and package examples. Read
the relevant section, not the entire reference for every candidate. It is
optional context, not a mandatory sequence or a new acceptance gate.

## Choose the next observation

| Need | Existing entrance | Read when relevant |
| --- | --- | --- |
| Resolve a lead's actual implementation | `kimi_scout_delivery_source.select_leads` with `owner_review=True` or an explicit supported `owner_language` | [Intake and missing source](references/scout_native_cpu_validation_notes.md#owner-only-intake-across-languages) |
| Transfer committed code without checkout newline changes | `qualification_source_bundle.py --build` / `--verify` | [Commit-exact transport](references/scout_native_cpu_validation_notes.md#commit-exact-source-before-native-validation), [literal path subsets](references/scout_native_cpu_validation_notes.md#scoped-raw-git-source-transport) |
| Reuse the tested capture tools on another host | `scout_native_run.py --export-runtime FRESH_DIRECTORY` | [Runtime/API limits](references/scout_native_cpu_validation_notes.md#check-the-deployed-native-runner-not-another-checkout) |
| Prepare a separate public-source Scout batch without migrating a live queue | `scout_public_export.py --repo REPO --commit FULL_COMMIT --output FRESH_DIRECTORY` | [Pinned Scout source and lessons](#pinned-scout-source-and-lessons) |
| Inspect an existing private dependency tree without installing or copying it | `scout_dependency_tree.py EXISTING_TREE` | [Content versus isolation](#dependency-reuse-content-is-not-isolation) |
| Run an owner-reviewed command and retain native reports | `scout_native_run.py --help`; choose a supported actual report format | [POSIX/Windows capture and cleanup](references/scout_native_cpu_validation_notes.md#check-the-deployed-native-runner-not-another-checkout), [Vitest JSON](references/scout_native_cpu_validation_notes.md#vitest-json-is-a-separate-native-format) |
| Compare the same regressions and controls before/after | `scout_native_results.compare_regression` | [Report validity and collection skips](references/scout_native_cpu_validation_notes.md#collection-skips-are-not-executed-tests) |
| Compare a wider pytest suite with unchanged optional skips | `scout_native_results.compare_pytest_suite_regression` | [Complete pytest cohorts](#complete-pytest-cohorts) |
| Diagnose failure before package assertions ran | Inspect the original process/report and actual imported paths | [Temporary paths](references/scout_native_cpu_validation_notes.md#keep-test-process-temporary-paths-short-and-private), [SQLite temporary capacity](references/scout_native_cpu_validation_notes.md#sqlite-read-only-queries-still-need-temporary-capacity), [backend identity](references/scout_native_cpu_validation_notes.md#verify-realized-backends-not-parameter-labels) |

Selection, export and a self-consistent manifest are not execution permission or
proof of a defect. Generated code remains untrusted until reviewed. Check current
contribution rules, supported callers, existing work and the actual test entrypoint
before installing dependencies. Preserve unavailable actions and original failures.

For a terminal lead, inspect the dashboard's **related-work sample** beside its
analysis: it shows the current/prior title when recoverable and the recorded
search queries, without extra requests. A final hypothesis can change after the
last lookup; inherited results may concern the old subject. Title text differences
are not semantic drift, and matching titles or empty samples prove neither
coverage nor novelty. Check the final subject's existing author-owned work before
implementation or dependency setup; this display is advisory, not a phase gate.

For an already selected Rust file, one explicit unqualified `definition(name)`
can locate a unique `fn name(` or `fn name<` literal within the existing source
window budget. `requested_rust_fn_literal` is a lexical location, including
comments/strings; it does not parse Rust, resolve impl/cfg/macros, or certify a
complete body. Repeated literals abstain. Exact line/literal requests retain
precedence. This avoids returning an earlier prose reference when the requested
function is elsewhere; inspect the actual code before inferring behavior.

Reference/import hints can reuse a current-pin window already supplied later in
the packet even when an older window of that same exact path appears first.
This preference inspects only the existing eight-source bound, does not relabel
old bytes or ranges, and does not fetch missing pins. Without a supplied
same-path current pin, revision-drift abstention remains in force. A successful
lookup is source evidence, not proof of a defect or of lower discovery cost.

## Commit-exact source before native validation

For a committed baseline/candidate, prefer raw Git objects over copying a dirty or
CRLF-converted checkout. The existing CLI is:

```text
python scripts/qualification_source_bundle.py --build --repo REVIEWED_REPO --commit FULL_COMMIT --repository-url PUBLIC_REPO_URL --archive task/candidate.tar.gz --manifest task/candidate.manifest.json
python scripts/qualification_source_bundle.py --verify --archive task/candidate.tar.gz --manifest task/candidate.manifest.json --extract-root task/candidate-export
```

The extraction target must not already exist. Include the archive prefix in the
eventual import root and check what was actually imported. Optional repeatable
`--path` selects literal tracked files/directories; `--prefix` only names the
archive root. A partial manifest does not establish dependency completeness.
The builder does not silently lazy-fetch missing objects. See the
[full restrictions](references/scout_native_cpu_validation_notes.md#commit-exact-source-before-native-validation)
before using this route with partial clones, LFS, submodules or symlinks.

If a test preceded the commit, compare its recorded source hashes with the raw
committed blobs before crediting the published head. Windows checkout bytes can
differ only by CRLF normalization; prove that difference rather than silently
relabeling the old run. When exact-head execution matters, export the committed
bytes and retain the earlier run separately. Stop a dependent commit/push step
when a prerequisite check fails; orchestration must inspect each process exit.
A generated driver also has transport bytes: hash the actual emitted file, not
only an in-memory string when text-mode writing can translate its newlines.
The runtime exporter writes its snapshots as bytes to avoid that mismatch.
For JIT/native tests, include changed headers in source identity and use a fresh
task-private build cache unless dependency-aware invalidation is demonstrated.
A fresh Python process alone does not establish a fresh compiled extension.

### Pinned Scout source and lessons

`scout_public_export.py` reads the two Scout entrypoints' static flat-module
imports and all committed default lesson cards from one explicit local Git
commit. It reuses the source bundler's local-only raw-object reader, in batches,
without importing the target code. Dirty/untracked files, live databases and
provider configuration are not selected. Per-file hashes and byte counts are
written to `manifest.json`; output must be fresh. Limits are 512 files, 512 KiB
per blob and 4 MiB total. A failed write can leave a partial fresh directory;
directory existence alone is not export success.

Review the selected bytes/manifest before transferring them under existing
authority. This is not a secret scanner or a redistribution/license package;
include required notices before redistribution. Static imports do not resolve
dynamic imports, package data or external dependencies. Single-dot sibling
imports follow the same pinned flat modules, without executing package code.
Parent-relative, unresolved-relative and local-package imports stop this
exporter rather than being silently omitted.
Check the worker's actual interpreter, imports and lesson inventory separately.
Exporting advice proves neither that a model consumed it nor that it helped.
Provider configuration and any original queue/credential migration remain
separate, explicitly scoped actions. This tool never transfers or starts work.

For a reviewed Python command on native Windows, explicitly pass
`--env PYTHONUTF8=1 --env PYTHONIOENCODING=utf-8` when its captured console may
contain localized warnings. The report reader requires UTF-8: valid JUnit and a
zero exit do not make an undecodable console a qualified capture. Preserve the
original inconclusive run; do not silently decode arbitrary logs with replacement
characters or hide its warnings. These flags are Python-specific, not a general
encoding fix for every executable.

## Package and language routes

- Python: [Humanize and missing translations](references/scout_native_cpu_validation_notes.md#humanize-core-baseline-with-translation-gaps-retained),
  [iterator concurrency capacity](references/scout_native_cpu_validation_notes.md#standard-library-iterator-tests-and-concurrency-capacity),
  [HTTPX](references/scout_native_cpu_validation_notes.md#httpx-example),
  [HTTPcore fixtures](references/scout_native_cpu_validation_notes.md#httpcore-plugins-and-behavior-matched-test-context).
- JavaScript/TypeScript: [Windows-native constraints](references/scout_native_cpu_validation_notes.md#windows-native-typescript-checks-without-bypassing-runtime-requirements),
  [bounded lifecycle tests](references/scout_native_cpu_validation_notes.md#typescript-lifecycle-checks-without-a-monorepo-rebuild),
  [Bun JUnit](#bun-native-junit-reports).
- Go: [standard-library-only comparison](references/scout_native_cpu_validation_notes.md#standard-library-only-go-comparison-baseline),
  [small retry library](references/scout_native_cpu_validation_notes.md#a-small-dependency-free-retry-library).
- C++: [small native translation units](references/scout_native_cpu_validation_notes.md#small-owner-reviewed-c-translation-units),
  [Torch-dependent units](references/scout_native_cpu_validation_notes.md#torch-dependent-cpu-translation-units),
  [Mooncake private dependencies](references/scout_native_cpu_validation_notes.md#mooncake-store-private-c-dependencies-before-model-generated-tests).

A narrow native unit or exported method is not a full-package import, serving
run or performance qualification. Label mechanical adaptations and nonexact
dependencies. Before remote execution, inspect
[sandbox feasibility](references/scout_native_cpu_validation_notes.md#remote-sandbox-feasibility-before-model-execution)
and the authorized environment; do not silently start local WSL or bypass an
execution-policy denial. Process capture is not a security sandbox.

### Bun native JUnit reports

Use `--format bun-junit` with a reviewed `bun test` command. The runner supplies
its own `--reporter=junit` and fresh `bun.xml` path, preserving the separate
console log. Do not supply reporter flags yourself. Export a fresh runtime with
`--export-runtime`; copying only the entry script omits required sibling modules,
including `scout_bun_junit.py`.

Expected names are exact JSON location/group IDs, not just display names. For
example, if `probe.test.ts` declares `describe('group', ...)` on line 1 and
`test('regression', ...)` on line 2:

```python
from scripts.scout_bun_junit import case_id

regression = case_id('probe.test.ts', 2, [('group', 1)], 'regression')
# '["probe.test.ts",2,[["group",1]],"regression"]'
```

Freeze these locations against the reviewed test bytes. Identical parameterized
names at the same location form a group with observed multiplicity; Bun's report
does not identify parameter values. The reader counts nested cases once, and
`compare_regression` requires the same grouped inventory and multiplicities in
both arms. Declare the complete selected cohort, including passing controls;
a group mixing passing and failing instances is not an all-failed regression.

Missing import reports, unlocated hook failures, timeouts, unsupported report
shapes and inconsistent counters are `INCONCLUSIVE`, not bug reproductions.
Skip/TODO cases are retained but not counted as executed. A located failure still
needs inspection of the actual caller contract; parsing it is not a correctness
oracle or permission to run generated code.

The entrance was replayed with native Linux Bun 1.4.3 on the already exposed
[MiniMax CLI quiet/JSON repair](https://github.com/MiniMax-AI/cli/pull/292): identical
test bytes yielded 7 passes/1 regression failure before and 8 passes after, with
matching grouped inventories. Separate native probes covered nested groups,
assertion failure, skips/TODO, hook/import failures and timeout. Windows tests
exercise process capture with injected XML, not Windows Bun. This qualification
is neither a new Scout discovery nor evidence of prospective selection benefit,
full-package portability or a security sandbox.

### Dependency reuse: content is not isolation

Account for preparation and postchecks as well as test time. A reviewed Linux
Bun replay exposed a practical bottleneck: native test/typecheck/lint commands
took about 34 seconds, but the outer 280-second job expired during final checks
after duplicating dependencies. Preserve that failure; successful test exits do
not turn the entire timed-out job into a successful bounded execution.

For owner-reviewed commands known not to write dependencies, an existing
**task-private** installation can sometimes be reused instead of copied. Keep
fresh source roots, HOME, temporary files and reports. Preserve the original
locked-install provenance, runtime identities and actual import paths; equal
`package.json`/lockfile bytes alone do not prove an installation matches them.
Do not silently substitute a system or another project's dependency tree.

The optional, standard-library-only reader is included in fresh runtime exports:

```text
python scripts/scout_dependency_tree.py EXISTING_PRIVATE_TREE
python scripts/scout_dependency_tree.py EXISTING_PRIVATE_TREE --expect-sha256 SHA_FROM_BEFORE
```

It hashes regular-file contents, relative paths, empty directories and in-tree
symlink targets, without following those links as duplicate subtrees. External,
dangling or root links, junctions, special files, unreadable subtrees and exceeded
budgets abstain rather than returning a partial digest. Defaults are 20,000
entries, 1 GiB read bytes, 8 MiB retained entry metadata and a cooperative
60-second deadline; retain an outer
timeout for stalled filesystem I/O. Modes, owners, timestamps, hardlink aliasing
and atomicity are **not** established. The digest is a new content/layout format,
not interchangeable with older task-local file-only inventory hashes.

A separate known-case feasibility replay linked an existing private Bun
installation into fresh sources and completed the same focused old/new checks
in 28.4 seconds, including matching before/after file/link inventories. It did
not repeat the full suite, measure cold-cache alternatives or compare policies
under equal realized resources. Do not infer a speedup ratio or Scout yield.

**A directory symlink does not make its target read-only.** Matching observations do not prevent
concurrent writes, write-and-restore changes or access outside the tree. Keep
this reuse opt-in for reviewed nonwriting commands with controlled ownership;
use an isolated copy or an actual read-only sandbox/mount for dependency writers,
untrusted generated code or conflicting users. Do not change the runner's source
symlink rejection or treat the reader as execution authority. No automatic
dependency linking, queue policy or sandbox protection is added by this tool.

## Complete pytest cohorts

For a small all-executed selection, keep using `compare_regression`: its declared
regressions and controls must describe the entire observed report. Do not pass a
wide report with only a few declared cases, filter away unwanted results, or
reinterpret its rejection as a successful comparison.

When a reviewed broader **pytest** selection contains optional skips, use:

```python
from scripts.scout_native_results import compare_pytest_suite_regression

comparison = compare_pytest_suite_regression(
    baseline_xml, candidate_xml, baseline_exit=1, candidate_exit=0,
    regressions=["tests.test_contract::test_regression"],
    controls=["tests.test_contract::test_success"],
)
```

Freeze the same suite command, regression identities and passing controls before
running either arm. `MATCHED_SUITE_REGRESSION_OBSERVED` requires identical complete
case inventories: only declared regressions change, from failure to pass. Every
other outcome stays unchanged; skipped attributes must also match. With an
explicit nonempty skip `message`, the body is retained but not compared: native pytest
reports include the arm's volatile source location there. Without a message,
the text must match too. This does not establish equivalence of arbitrary skip
body prose. Missing
or extra cases, pass/skip transitions, changed skip reasons, additional failures,
setup/collection errors, invalid counters and abnormal exits cannot match. This
separate API does not weaken the existing strict comparison or default summary.

Identical collection skips remain **unexecuted coverage**, not successful tests;
equal XML inventories cannot reveal tests hidden behind a skipped module. A
changed skip reason can make a legitimate repair incomparable; retain the
reports and explain or rerun a predeclared matched environment, not strip the
difference. The reader verifies saved-report accounting only, not authenticity,
source/runtime identity, assertion quality, caller support or PR readiness.
It makes no selection-policy or PR-yield claim. Other report formats retain their
existing entrances; this is not a generic JUnit dialect adapter.

Cardinality errors include the affected counter and its declared/observed
values, without echoing malformed counter text. A captured pytest run can report
passed subtests in its CLI total while its JUnit suite count exceeds the emitted
case nodes. Keep that report inconclusive: inspect the original report and the
actual test framework before attributing the discrepancy to a candidate. Do not
rewrite counters, infer missing case identities, filter the report to force a
match or silently relabel CLI success as structured acceptance. A separately
declared focused test selection is different evidence, not a replay or repair
of the original full-suite record; retain both scopes and their costs.
The existing upstream discussion
[pytest #13876](https://github.com/pytest-dev/pytest/issues/13876) describes
subtests sharing their parent's JUnit reporter. Check today's producer rather
than treating that history as an exemption for arbitrary count mismatches.

## Keep the outcome useful

Use identical test bytes and matched inputs for both arms, passing ordinary
controls as well as the regression. Record source/runtime identities, command,
all exits/skips/warnings, cleanup and cost once in the existing task record.
Collection/setup errors are not assertion failures or passes. A behavior difference
still needs the [actual consumer contract](references/scout_native_cpu_validation_notes.md#native-behavior-is-not-the-entire-acceptance-contract).
Separate an evidence-backed stop, environment limitation, author-owned fix and
reviewable new contribution. No test count or source-reader success establishes
PR yield, recall or evidence-selection research benefit.

New runner reports include `cpu_accounting` even for failing commands. Windows
queries [cumulative user/kernel time](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_basic_accounting_information)
for the private Job Object, including its trusted launcher. An `active_processes`
value above zero means that reading is not final job consumption. POSIX records the
runner process's [reaped-child CPU delta](https://docs.python.org/3/library/os.html#os.times):
concurrent children can contribute, and unpropagated descendant usage is absent.
Prefer sequential CLI invocations and retain the method label; these scopes are
not interchangeable complete process-tree costs. Missing readings remain null,
not zero. Compilation inside the command contributes; model calls, preparation
outside it and human effort are separate. These observations do not establish a
priced, budget-matched comparison. Historical reports stay unchanged.
