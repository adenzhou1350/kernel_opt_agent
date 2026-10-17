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
| Inspect an existing private dependency tree without installing or copying it | `scout_dependency_tree.py EXISTING_TREE` | [Content versus isolation](#dependency-reuse-content-is-not-isolation) |
| Run an owner-reviewed command and retain native reports | `scout_native_run.py --help`; choose a supported actual report format | [POSIX/Windows capture and cleanup](references/scout_native_cpu_validation_notes.md#check-the-deployed-native-runner-not-another-checkout), [Vitest JSON](references/scout_native_cpu_validation_notes.md#vitest-json-is-a-separate-native-format) |
| Compare the same regressions and controls before/after | `scout_native_results.compare_regression` | [Report validity and collection skips](references/scout_native_cpu_validation_notes.md#collection-skips-are-not-executed-tests) |
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
