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

## Package and language routes

- Python: [Humanize and missing translations](references/scout_native_cpu_validation_notes.md#humanize-core-baseline-with-translation-gaps-retained),
  [iterator concurrency capacity](references/scout_native_cpu_validation_notes.md#standard-library-iterator-tests-and-concurrency-capacity),
  [HTTPX](references/scout_native_cpu_validation_notes.md#httpx-example),
  [HTTPcore fixtures](references/scout_native_cpu_validation_notes.md#httpcore-plugins-and-behavior-matched-test-context).
- JavaScript/TypeScript: [Windows-native constraints](references/scout_native_cpu_validation_notes.md#windows-native-typescript-checks-without-bypassing-runtime-requirements),
  [bounded lifecycle tests](references/scout_native_cpu_validation_notes.md#typescript-lifecycle-checks-without-a-monorepo-rebuild).
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

## Keep the outcome useful

Use identical test bytes and matched inputs for both arms, passing ordinary
controls as well as the regression. Record source/runtime identities, command,
all exits/skips/warnings, cleanup and cost once in the existing task record.
Collection/setup errors are not assertion failures or passes. A behavior difference
still needs the [actual consumer contract](references/scout_native_cpu_validation_notes.md#native-behavior-is-not-the-entire-acceptance-contract).
Separate an evidence-backed stop, environment limitation, author-owned fix and
reviewable new contribution. No test count or source-reader success establishes
PR yield, recall or evidence-selection research benefit.
