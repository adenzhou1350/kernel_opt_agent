# Native CPU validation: worked routes and boundaries

This is on-demand detail for the [short entry point](../scout_native_cpu_validation.md).
Read the relevant section, not this entire document for every candidate. The
[historical reference](scout_native_cpu_validation_notes.md) retains additional
platform restrictions, failed attempts and package examples. Neither document
is a mandatory sequence or a new acceptance gate.

## Choose the next observation

| Need | Existing entrance | Read when relevant |
| --- | --- | --- |
| Resolve effective contribution rules, including organization defaults | `scout_contribution_policy.py --repo OWNER/REPO --output FRESH_FILE.json`; read its complete documents and linked rules | [Inherited rules before setup](#inherited-rules-before-setup) |
| Start a separate tool-free model batch | Reuse `kimi_scout.py add` / `run --once` and an explicit controller-owned backend configuration | [Model effort before fan-out](#model-effort-before-fan-out) |
| Resolve a lead's actual implementation | `kimi_scout_delivery_source.select_leads` with `owner_review=True` or an explicit supported `owner_language` | [Intake and missing source](scout_native_cpu_validation_notes.md#owner-only-intake-across-languages) |
| Prepare a reviewed source packet from existing local Git objects | `scout_git_source.py --repo LOCAL_REPO --spec selection.json --output FRESH_PACKET.json` | [Local pinned packet](#local-pinned-packet) |
| Transfer committed code without checkout newline changes | `qualification_source_bundle.py --build` / `--verify` | [Commit-exact transport](scout_native_cpu_validation_notes.md#commit-exact-source-before-native-validation), [literal path subsets](scout_native_cpu_validation_notes.md#scoped-raw-git-source-transport) |
| Reuse the tested capture tools on another host | `scout_native_run.py --export-runtime FRESH_DIRECTORY` | [Runtime/API limits](scout_native_cpu_validation_notes.md#check-the-deployed-native-runner-not-another-checkout) |
| Prepare a separate public-source Scout batch without migrating a live queue | `scout_public_export.py --repo REPO --commit FULL_COMMIT --output FRESH_DIRECTORY` | [Pinned Scout source and lessons](#pinned-scout-source-and-lessons) |
| Inspect an existing private dependency tree without installing or copying it | `scout_dependency_tree.py EXISTING_TREE` | [Content versus isolation](#dependency-reuse-content-is-not-isolation) |
| Run an owner-reviewed command and retain native reports | `scout_native_run.py --help`; choose a supported actual report format | [POSIX/Windows capture and cleanup](scout_native_cpu_validation_notes.md#check-the-deployed-native-runner-not-another-checkout), [Vitest JSON](scout_native_cpu_validation_notes.md#vitest-json-is-a-separate-native-format) |
| Compare the same regressions and controls before/after | `scout_native_results.compare_regression` | [Report validity and collection skips](scout_native_cpu_validation_notes.md#collection-skips-are-not-executed-tests) |
| Compare a wider pytest suite with unchanged optional skips | `scout_native_results.compare_pytest_suite_regression` | [Complete pytest cohorts](#complete-pytest-cohorts) |
| Compare a wider skip-free Go package suite, including parent/subtest repeats | `scout_native_results.compare_go_suite_regression` | Declare changed leaves and failing ancestors; every other case name/outcome/multiplicity must match and pass. No skip waivers or expanded required-name budget. |
| Diagnose failure before package assertions ran | Inspect the original process/report and actual imported paths | [Temporary paths](scout_native_cpu_validation_notes.md#keep-test-process-temporary-paths-short-and-private), [SQLite temporary capacity](scout_native_cpu_validation_notes.md#sqlite-read-only-queries-still-need-temporary-capacity), [backend identity](scout_native_cpu_validation_notes.md#verify-realized-backends-not-parameter-labels) |

Selection, export and a self-consistent manifest are not execution permission or
proof of a defect. Generated code remains untrusted until reviewed. Check current
contribution rules, supported callers, existing work and the actual test entrypoint
before installing dependencies. Preserve unavailable actions and original failures.

### Inherited rules before setup

A clone with no CONTRIBUTING or PR template can still inherit both from the
owner's `.github` repository. Use the existing bounded policy reader before
paid discovery or environment setup. `UNKNOWN` after an API failure is not
an empty policy: under existing authority, read the repository's visible
Contributing tab and linked organization files, or retain the uncertainty.
Do not add another classifier, mandatory schema or automatic publication gate.

The community profile is not a complete guide index. If a maintainer or an
already reviewed document points to a specific repository guide, request that
literal path with the same reader, for example:

```sh
python scripts/scout_contribution_policy.py --repo jfhbrook/pyee --document-path DEVELOPMENT.md --output fresh-policy.json
```

At most four explicit paths are read, pinned to the verified default-branch
commit and subject to the existing file/type/hash/32-KiB checks. Successful
profile duplicates are not fetched again. Default calls add no requests; there
is no filename guessing or link crawler. Invalid paths stop before network;
missing or failed reads stay `UNKNOWN`, and profile denial is not routed around.
The text is evidence to review, not an instruction to execute publishing tasks
or an automatic permission decision. Pyee's
[3116911 guide](https://github.com/jfhbrook/pyee/blob/3116911e09cadcc1e0c85631fbab8aebefc1b772/DEVELOPMENT.md)
requires bot-emoji prefixes on AI-assisted commits/changelog entries and reviewer
disclosure. This permits disclosed assistance; it is neither a blanket ban nor
a rule to transfer to other projects. Native API transport may remain unavailable
even though the reader's offline tests pass.

For example, [aio-libs' organization guide](https://github.com/aio-libs/.github/blob/df5def2d78949a4ff7150de6fbd5aa27eb45b090/CONTRIBUTING.md)
permits AI-assisted code but requires human review and human-authored community
communication, explicitly including PR descriptions and changelogs. Permission
to use AI is not permission for an agent to author those texts. Keep code/test
evidence private pending actual review; ask for the human's own explanation and
limit language assistance to translation/grammar. Do not turn a generic approval
into a claim of authorship. This is that organization's policy, not a universal
AI ban. Recheck current effective rules before publication. A successful native
run changes technical evidence, not contributor eligibility or PR conversion.

A short repository-local guide is not necessarily a waiver of an owner's
explicit all-project guidance. For example, [isaacs' guide](https://github.com/isaacs/.github/blob/cfc3974c544c435869c2fd3483b303c919409d40/CONTRIBUTING.md)
requires the human contributor to demonstrate deep understanding of AI-assisted
changes, as well as coverage preservation. Read its companion AGENTS guidance
before preparing public text/commits. A tested patch and generic permission to
publish do not establish that understanding. This is a scoped policy check,
not an inferred AI ban or a reason to crawl unrelated personal pages.

Follow linked policy pages too: [Pallets' AI policy](https://palletsprojects.com/contributing/llm-ai)
explicitly tells new contributors not to use AI for contributions and includes
community text/translation. A repository's brief setup guide is not a waiver.
Do not spend discovery/setup budget on an ineligible publication route or
disguise generated work as the human's own.

For a pytest export nested under another repository, also read the
[root/configuration note](scout_native_cpu_validation_notes.md#keep-test-process-temporary-paths-short-and-private)
before freezing expected JUnit IDs. `cwd` and disabled plugin autoload do not stop
ancestor configuration discovery. Use the target's reviewed configuration with
`-c` when appropriate; `--rootdir` alone is not configuration or import isolation.
Do not rerun an otherwise valid capture just to fix an expected-name typo.

When collecting an exported pytest file, choose a reviewed `--rootdir` that
contains that file. A test collected outside it can produce an empty JUnit
`classname`; the strict reader rejects that identity and points to test paths
and reporter configuration. Do not invent a module name, rewrite the XML or
waive the refusal. Preserve the native observation with this accounting limit.
If an owner-reviewed wrapper calls `pytest.main()`, forward the runner's appended
report arguments (for example, `sys.argv[1:]`); ignoring them can execute tests
without writing the report. Check this before another native invocation.

For an owner-prepared Python excerpt, reuse
`scout_requested_definition.requested_function_window(lines, "definition(Class.method)")`
against the full pinned file instead of slicing from `FunctionDef.lineno`.
The existing selector retains binding decorators, including parenthesized ones.
Dropping `@property` can turn a false boolean attribute into a truthy bound method
in the supplied evidence. Preserve original ranges and mark missing context;
selection is syntax-only, not runtime dispatch proof. Keep any malformed packet
and its cost, and recheck the actual package before crediting a model's repair.

Two explicit `definition(Class.first)` / `definition(Class.second)` requests can
replace the two ordinary follow-up reads when both uniquely resolve in one
already-observed, current-pin Python cache whose Git blob matches the snapshot.
The bounded cache check does not fetch missing bodies; mixed owners, references,
duplicates, ambiguous declarations and ineligible paths keep the old fallback.
Each read retains its own definition hint and completeness metadata, rather than
letting a multi-target request fall back to unrelated same-basename files.
This is evidence routing within the existing budget, not native correctness or
measured model/PR benefit. Cold test selection remains a separate unresolved case.

Keep the controller and target Python versions distinct. The dependency notes
use conservative pre-3.14 annotation timing for the pinned Python 3.12 native
profiles; they must not become host-version-dependent just because Windows runs
3.14. [Python 3.14 defers ordinary annotations](https://docs.python.org/3.14/whatsnew/3.14.html#pep-649-pep-749-deferred-evaluation-of-annotations),
while `from __future__ import annotations` still stores strings. Native timing
controls must test their actual runtime: definition may succeed while reading
`__annotations__` or resolving hints triggers the missing import. String/deferred
annotations are not an import sandbox. Do not waive a native failure or claim
profile compatibility merely because an AST hint or another interpreter passed.

For a terminal lead, inspect the dashboard's **related-work sample** beside its
analysis: it shows the current/prior title when recoverable and the recorded
search queries, without extra requests. A final hypothesis can change after the
last lookup; inherited results may concern the old subject. Title text differences
are not semantic drift, and matching titles or empty samples prove neither
coverage nor novelty. Check the final subject's existing author-owned work before
implementation or dependency setup; this display is advisory, not a phase gate.
An empty general web-search result is not that repository check: search indexes
can omit an already-open exact repair. When direct API access is unavailable,
use the repository's visible all-state issue/PR search under existing authority,
or keep duplicate coverage unknown. Finding an author's repair redirects work
to scoped independent verification, not a competing PR or a credited discovery.

For a source follow-up that exactly cites an already displayed issue, the
related-work slot now uses the existing bounded issue timeline rather than
searching only PR bodies for its number. A fix can predate the report and be
confirmed only in comments, as in [Megatron #8179](https://github.com/NVIDIA/Megatron-LM/issues/8179#issuecomment-6163575360).
The lookup retains at most three sources from the first 50 events, with no
recursive link fetch or added numeric search. It does not adopt issue focus,
infer acceptance, or establish coverage when empty/unavailable. Explicit
body-only requests retain their existing separate scope; partial comments
and old deployed code can still miss the confirmation. No historical model
answer is corrected or credit for avoided cost inferred from this routing test.

An issue-focused chain can likewise move to a different displayed report.
When `next_check` explicitly chooses that report and its own citation matches
the supplied text, the same single related-work slot queries it without changing
the original focus, chain key or depth cap. Multiple citations without an explicit
verified target still abstain; invented, cross-repository or unquoted targets
cannot redirect the lookup. The SGLang [#44789](https://github.com/sgl-project/sglang/issues/44789)
follow-on already has [PR #44814](https://github.com/sgl-project/sglang/pull/44814),
while the observed chain kept searching its original #38871 subject. Replaying
the saved parent changes only the selected lookup, not its paid model result;
this is neither a measured token saving nor a prospective discovery result.

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

### Local pinned packet

Use the local reader when the reviewed commit is already available, rather than
writing per-task `git show`/AST excerpt adapters. A selection JSON contains
`name`, public `repo` (`owner/project`), full 40-character `commit`, `question`
and `files`. Each file has a literal `path`; optional inclusive line `ranges`
use `{"start": 1, "end": 20}`, and Python `definitions` use explicit names such
as `["Client._close"]`. Both can be combined to retain headers and callers.
Omitting both selects the complete file. Missing/ambiguous definitions reject
the packet, rather than falling back to another body. The existing selector
retains decorators; it does not resolve inheritance or prove reachability.

The reader uses one `git cat-file --batch` for up to eight regular files. Whole
files and Python AST definition selections retain the 100,000-byte read bound.
An explicit line-only selection can read a raw blob up to 1,000,000 bytes, so
large C/C++ implementation files need not disappear from a small reviewed
packet. Mixed packets keep the smaller per-path limits for other files; the
batch reader checks each header before reading its payload. No automatic
window, fallback, fetch or C parser is added. The blob is still read and decoded
in full within that bound to verify identity and line ranges; this is not
streaming a selected fragment or a measured memory optimization. The existing
24,000-byte prompt limit, eight-file maximum and complete-card budget do not
increase. Explicitly selecting too much text still rejects without truncation.
That refusal reports the complete serialized input size and each selected
source's UTF-8 text size. The latter excludes system/metadata and JSON escaping,
so it is a diagnostic, not an additive token-cost estimate. Inspect those sizes
before revising a selection; do not keep trimming away necessary caller context
or repeatedly retry an unchanged oversized scope.
The reader ignores checkout newline conversion and dirty files, retains raw
blob/SHA256 identities and
visible line ranges, and produces commit-pinned `raw.githubusercontent.com`
URLs accepted by delivery source routing. Files are emitted in the selection's
order. Over-budget packets reject without truncating evidence; `--lessons` is
an optional advisory lookup, dropped first by the existing 24,000-byte input
budget. No fetch, queue, model, target import or test is run. The output must be
fresh. Review it before using the ordinary queue entrance.

The stored packet retains both hashes, but those two new provenance fields do
not affect content dedup: a different full-file hash with the same visible
excerpt/question alone is not another paid observation. Visible source changes
still matter. This neither proves omitted bodies are equivalent nor updates
historical job IDs/packets; obtain missing current context when it can change a
decision, rather than treating excerpt dedup as a whole-file no-bug verdict.

Research enqueue also checks the evidence actually retained after budget fitting,
alongside the original retrieval identity. Two retrieved tails that are both
omitted cannot create two review tasks merely through different names/pretrim
hashes. These aliases commit atomically before queue admission; visible changes,
stages and observed issue/PR lifecycle changes remain distinct. This prevents a
synthetic duplicate enqueue, not a measured historical token saving or recall
guarantee. Previously queued packets are not removed or rewritten.

The supplied public repository name is a caller declaration, **not verified
public provenance**: local Git availability does not prove the commit is
published there, the clone is current, the source is safe to share, or a repair
is novel. This entrance neither transfers credentials nor checks contribution
policy. Retain failed original model outputs; generating clearer owner context
does not repair their verdicts or establish better discovery/PR yield.

### Model effort before fan-out

A fresh small public-source batch need not inherit or migrate a live Scout queue,
credentials or provider configuration. Export pinned source/lessons, explicitly
enqueue reviewed packets and use the existing `--once`, attempt/token/time limits
and memory/disk admission. Distinguish a terminal batch with pending unadmitted
jobs from a drained queue; increasing concurrency does not fix a conservative
token reservation that cannot fit the next packet.

For a model migration or empty length-limited responses, search the existing
model-specific lessons before repeating a default configuration. For example,
`knowledge search "GLM reasoning effort"` routes
[`reasoning-effort-is-model-specific`](../../knowledge/lessons/reasoning-effort-is-model-specific.json).
The documented GLM-5.3 default is max effort when the parameter is omitted;
explicit `low` is a calibration candidate, not a universal quality-preserving
default. Preserve failed calls and usage. A revised bounded invocation can
consume previously unattempted packets without resetting failed rows or
silently retrying them. Record changed effort/output/reservation ceilings before
the invocation and leave frozen study arms unchanged. Different packets and
settings cannot establish a causal efficiency or discovery-quality comparison.
Accepted request syntax does not prove a gateway realized the selected effort.

One known-case application check on the
[vLLM stream helper](https://github.com/vllm-project/vllm/blob/aa3564ceefbd605f1d28238fa0fbbb964201c6b8/vllm/multimodal/video_decoders/pynvvideocodec.py#L260-L284)
illustrates why these gates stay separate. With effort omitted, 4,096- and
8,192-completion-token allowances both ended at `length` without a complete
answer. A separately declared one-call `low` configuration, with the same packet
and the original 4,096 allowance, returned a schema/source-quotation-accepted
diagnosis using 1,918 reported total tokens in 5.104 client seconds. All three
attempts remain charged: 16,784 reported tokens, excluding preparation, owner and
native costs. This single realization is neither a causal/general quality result
nor evidence of the gateway's internal reasoning policy; the reasoning counter
was absent. It does not change frozen study arms or justify a production switch.

The completed answer still suggested an incomplete repair: restore the caller's
device **before** setting the saved stream. That stream was saved after switching
to the target device, so selecting it can switch away from the caller again.
An owner-reviewed literal implementation of that order, in the complete imported
vLLM module on Torch 2.14/two CUDA devices, passed the same-device control but
failed both normal and exceptional cross-device exits (1 pass / 2 failures).
This used the existing unchanged tests, not another run of the already passing
repair. Keep `REVIEW`/valid diagnosis separate from repair correctness; do not
promote a native-failing suggestion, rewrite its model answer or count a known
development case as prospective discovery or paper evidence.

Keep JSON syntax and source accuracy separate too. A six-call synthetic quoting
calibration on GLM-5.3 produced valid JSON for both ordinary and `json_object`
requests, but both miscopied the same trailing backslash as a double quote.
The existing source-membership validator rejected both; four exact quotations
passed. No answer repair, retry or new default was warranted. The 2,003 reported
tokens are diagnostic cost, not evidence of format-mode efficacy or PR yield.
HTTP acceptance also does not prove the server realized constrained decoding.
Preserve punctuation through validation; normalizing whitespace is not permission
to normalize quote characters or manufacture source evidence.

### Cache charge is not process memory or guaranteed spare capacity

For a stopped/paused Linux worker, run the read-only `scout_linux_memory.py`
diagnostic before changing budgets or restarting. Admission still uses the
minimum of host `MemAvailable` and visible finite cgroup `max-current` values.
That is deliberately conservative: file cache is charged, and kernel reclaim
can allow an allocation larger than the raw difference. It is not a strict
per-process allocation ceiling or proof that a Python process leaked.

The same diagnostic now exposes host/cgroup PSI and `memory.oom.group` when
available. Missing/malformed pressure stays `null`, not zero; these optional
observations do not grant memory credit or change admission. Inactive file
charge alone is not guaranteed reclaimable capacity. With group OOM enabled,
an allocation failure can affect the whole cgroup, not just the test child.
Do not turn one successful small allocation into high-concurrency permission,
drop shared caches, alter limits or discount all inactive cache to make a queue
run. See the [kernel memory-controller semantics](https://docs.kernel.org/admin-guide/cgroup-v2.html#memory)
and [PSI interface](https://docs.kernel.org/accounting/psi.html).

When another already authorized worker has genuine raw headroom, a fresh bounded
public-only batch can continue discovery without moving the stopped worker's
queue or credentials. Retain its actual PID/terminal result, call/token budget
and private source/runtime identities. That is independent work, not recovery
of the original queue or evidence of a discovery-policy improvement.

The SSH SDK backend also reuses this reader before each request: it resolves
the process's actual cgroup and visible ancestors instead of checking only
`/sys/fs/cgroup/memory.max`. Unknown or v1 memory observations do not admit a
request. Its existing 1 GiB RAM/disk floor is unchanged. This does not increase
capacity or fix a memory-stopped HTTP controller; it closes a separate admission
gap. Keep the shared helper alongside the backend when provisioning its scripts.

### Finite public batch without a task-specific executor

After reviewing/exporting the committed code and public packets, use the existing
CLI on an already authorized, provisioned CPU worker. A fresh private run and an
explicitly approved provider file are separate from the public source export:

```sh
python scripts/kimi_scout.py --root /task/private/fresh-batch init
python scripts/kimi_scout.py --root /task/private/fresh-batch add /task/public/packet-1.json
python scripts/kimi_scout.py --root /task/private/fresh-batch add /task/public/packet-2.json
python scripts/kimi_scout.py --root /task/private/fresh-batch run \
  --kimi-python /path/to/existing/python \
  --openai-backend-config /task/private/approved-provider.json \
  --once --hours 0.083333 --concurrency 2 --max-jobs 2 \
  --token-budget 80000 --output-tokens 8192 --timeout 120 \
  --min-free-memory-mb 8192 --worker-memory-mb 128 --min-free-disk-mb 8192
python scripts/kimi_scout.py --root /task/private/fresh-batch status --limit 8
```

These are example limits and paths, not provisioning, disclosure or execution
authority. Run as the reviewed unprivileged user with task-private temporary and
cache directories. Review the actual provider/effort and source scope first.
Inspect every job's terminal state and actual usage: a process exiting with
`PENDING` jobs is not a drained batch. Do not clear failed rows, reuse a stopped
production run or add a supervisor just to repeat these commands. Target builds,
tests, native reproduction, duplicate review and publication remain separate
owner work. No code generated by the model is executed by this batch.

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
[full restrictions](scout_native_cpu_validation_notes.md#commit-exact-source-before-native-validation)
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

For a partial Python export, inspect all top-level package/data directories and
the target's package configuration before treating an import failure as a missing
external dependency. Dateparser's own `dateparser_data/settings.py` is required
by its ordinary import but is outside `dateparser/`; omitting it broke a private
baseline despite matching every selected blob. Export the authentic sibling,
not a stub. For unavailable small dependencies, fixed universal wheels can be
acquired on an authorized connected host, checked against registry release
hashes, then privately installed with `--no-index`; platform-specific wheels and
dependency markers still need target-compatible selection. Retain failed setup
and inherited-package limits, rather than claiming a frozen complete environment.
Use collection output for parameterized test IDs: a decorated base method may
not itself be a runnable node. Freeze the expanded cohort before running it.

### Tracked links versus workspace persistence

Source transport, extraction and sandbox persistence are different contracts.
For example, Tenacity's tracked
[`README.rst`](https://github.com/jd/tenacity/blob/32ac68f0941319c0d2f4fb927f96e4ee29bb46c6/README.rst)
is a relative link to `doc/source/index.rst`. Safe POSIX extraction preserves it,
but a broker that persists only regular files can reject the workspace **after**
tests finish. Inspect the same invocation's exit, `workspace_persisted`, cleanup
and retained evidence; do not turn this into a target failure or rerun blindly.

For read-only validation in that profile, keep the verified archive/manifest in
the persistent workspace, extract a fresh original tree in ephemeral `/tmp` for
each command, and persist only inputs and reports. Verify tracked file bytes and
link targets after tests. This preserves source semantics without weakening the
broker or flattening a link. Confirm both expanded and persisted storage budgets.
An editable multi-command agent needs an explicit change-transfer design; an
ephemeral checkout does **not** retain its source edits into the next command.

In the bounded Tenacity observation, the first full pytest selection exited zero
but persistence failed. A separate fresh ephemeral-source run kept the original
selection and link, exited zero, persisted its report and removed its container.
CLI reported 185 tests plus 15 passed subtests; JUnit declared 200 but emitted 185
case nodes. The existing strict reader correctly retained `INCONCLUSIVE`, as in
the [known subtest reporting lesson](../../knowledge/lessons/pytest-subtest-report-granularity.json).
No counters or selection were rewritten. This is Python 3.12 runtime capacity
with pinned pytest/Tornado/Trio; Tornado's optional native speedups were absent.
It is not an installed-package build, docs/lint/type-check CI, novel bug, fresh
discovery cohort or evidence that a model's agent investigation works.

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

- Python: [Humanize and missing translations](scout_native_cpu_validation_notes.md#humanize-core-baseline-with-translation-gaps-retained),
  [iterator concurrency capacity](scout_native_cpu_validation_notes.md#standard-library-iterator-tests-and-concurrency-capacity),
  [HTTPX](scout_native_cpu_validation_notes.md#httpx-example),
  [HTTPcore fixtures](scout_native_cpu_validation_notes.md#httpcore-plugins-and-behavior-matched-test-context).
- JavaScript/TypeScript: [Windows-native constraints](scout_native_cpu_validation_notes.md#windows-native-typescript-checks-without-bypassing-runtime-requirements),
  [bounded lifecycle tests](scout_native_cpu_validation_notes.md#typescript-lifecycle-checks-without-a-monorepo-rebuild),
  [Bun JUnit](#bun-native-junit-reports).
- Go: [standard-library-only comparison](scout_native_cpu_validation_notes.md#standard-library-only-go-comparison-baseline),
  [small retry library](scout_native_cpu_validation_notes.md#a-small-dependency-free-retry-library).
  The comparison route also covers GoAWK API checks without claiming its missing
  GNU AWK differential oracle is available.
- Rust: [client crate with an upstream Python wire fixture](#rust-client-crate-with-a-python-wire-fixture).
- C++: [small native translation units](scout_native_cpu_validation_notes.md#small-owner-reviewed-c-translation-units),
  [Torch-dependent units](scout_native_cpu_validation_notes.md#torch-dependent-cpu-translation-units),
  [Mooncake private dependencies](scout_native_cpu_validation_notes.md#mooncake-store-private-c-dependencies-before-model-generated-tests).

A narrow native unit or exported method is not a full-package import, serving
run or performance qualification. Label mechanical adaptations and nonexact
dependencies. Before remote execution, inspect
[sandbox feasibility](scout_native_cpu_validation_notes.md#remote-sandbox-feasibility-before-model-execution)
and the authorized environment; do not silently start local WSL or bypass an
execution-policy denial. Process capture is not a security sandbox.

### Rust client crate with a Python wire fixture

A read-only PATH lookup is not a complete installation inventory. Before a cold
Rust setup, inspect surviving **task-owned** SDK records and verify the actual
compiler/Cargo versions and artifacts. A previous Rust 1.97.1 installation and
Cargo cache could be reused, but did not satisfy vLLM's `rust-toolchain.toml`
selection of 1.95. Materializing that selection in the same private rustup home
left the old SDK available; no global toolchain or shell profile was changed.

At [vLLM `b8e9001`](https://github.com/vllm-project/vllm/tree/b8e9001bf9568c801985889deff34d3b9fe6d0b0/rust),
the raw-Git bundle supplied the complete Rust workspace plus root toolchain and
contribution instructions: 532 regular tracked files, about 1.30 MB compressed.
The unchanged crate was tested with Rust/Cargo 1.95.0 and uv 0.12.12:

```sh
cargo test --manifest-path /private/source/rust/Cargo.toml \
  -p vllm-engine-core-client --lib --locked --offline -- --test-threads=2
```

Use available nextest when the target instructions require it; it was absent
in this environment. Review the package's actual Python fixture too. This
crate executes its original, executable `python_compat.py` through its `uv run`
shebang and PEP 723 dependencies. The fixture produces real MessagePack/NumPy
frames for Rust assertions, but mirrors Python structures; it does **not**
import the Python vLLM engine. Pre-materialize its dependencies through uv,
disable Python downloads, then keep Cargo and uv offline during the test.
Cargo.lock pins the Rust dependency selection. The Python script's declared
version ranges are not a complete byte-pinned Python dependency closure.

Initial preparation failures remain separate: a controller used an unsupported
capture-result key after a successful toolchain install; Cargo then encountered
a registry connection failure. A subsequent optional offline `uv lock` failed
despite the script environment being runnable. A working installed environment
does not imply enough cached registry metadata for a new universal resolution.
That extra lock gate was not an upstream test requirement and was not used to
rewrite the script. Dependency recovery reused the original source and runnable
fixture; there were no model calls or generated target tests.

The first complete native invocation ran **136 tests: 101 passed, 35 failed**.
Thirty-four failing cases reported `SUN_LEN`; the remaining timeout-message
assertion encountered transport setup failure rather than its intended wait.
The redirected task temporary directory made pathname Unix socket addresses too
long. Moving only socket temp storage to a short, unique, owner-private root
preserved artifacts and build caches on the task volume.

The next capture passed **136/136, zero skipped**, with unchanged tracked source,
test identities, command and compiled test-binary digest. Its new private HOME
was also different, so an additional HOME-matched control restored the original
HOME: **only TMPDIR differed**, and the same 136 cases passed again. No test was
dropped or edited. The existing `scout_native_run` captured original failures,
complete libtest accounting and natural process-group exit. A private uv lock
file remained in the short temporary directory; it was retained, not treated as
a live process or grounds for deleting another task's files.

This qualifies that pinned **client lib-test baseline**, including the registered
Python-fixture comparison, not all Rust workspace targets, an HTTP server,
Python engine, model/GPU behavior, performance or hosted CI. It is not a new
upstream defect, discovery-policy result or a fresh prospective study case.
Keep the same-source failure/control rather than filing a bug for an artificial
deep-temp-root setup. The reusable
[socket-path lesson](../../knowledge/lessons/unix-socket-temporary-path-budget.json)
states applicability and exceptions.

At [later client source `3eb3145`](https://github.com/vllm-project/vllm/tree/3eb3145bd0f56e15667a3783044aa5720061f277/rust/src/engine-core-client),
the same crate selection passed **140/140, zero skipped**, including the four
new JSON/structural-tag nesting and malformed-tag cases. All old136 case IDs
were present. This is a new pinned-source result, not retrospective extension
of the old baseline. The533 tracked files were independently rehashed after
execution; no source/test edits were made. Rust/Cargo1.95 and the unchanged
Cargo.lock/Python fixture reused private dependency content. A separate source
root and copied/reflinked build cache kept the historical executable unchanged;
the changed crate was recompiled in its new target directory. Do not hard-link
mutable build output over retained historical artifacts.

Two preparation failures remain failures: an initial selected-blob fetch lacked
the promisor/no-negotiation flags; a first native wrapper supplied533 paths to
`scout_native_run`'s explicit64-anchor cap and stopped before tests. The corrected
wrapper kept all533-file pre/post verification while supplying bounded capture
anchors. Neither failure was a target defect, native pass or model discovery.

The complete source and original
`structured_outputs_rejects_missing_constraint` test also close an excerpt-only
empty-constraint allegation at this pin: `TryFrom` returns an error before
`validate()` when no constraint is present. A missing excerpt is not missing
validation. Future changes or bypassing callers require a fresh witness; this
client result does not establish Python EngineCore or HTTP validation parity.

### CPU transport logic before RDMA qualification

The upstream [NIXL transport unit file](https://github.com/vllm-project/vllm/blob/4bd75e952a9f423742223c97c8cc9fc6db362950/tests/v1/kv_offload/tiering/p2p/test_data_transport.py)
can exercise Python submission, polling, cancellation, registration and cleanup
logic without an RDMA device. It explicitly supplies a mocked NIXL agent; that
boundary is part of the test, not a transport emulator or native NIXL proof.

A native Linux/Python 3.12, Torch 2.14/NumPy environment ran the complete file:
56 items passed, no skips/errors or missing predefined IDs, 10.02 seconds
including capture startup. The existing `scout_native_run.run` handled JUnit,
source checks and cleanup with CUDA hidden and uninitialized. A fresh private
package copy received all 50 current `vllm/v1/kv_offload` Python files, the current
NIXL utility and the unchanged test (52 files, 633,283 bytes); raw Git-blob and
SHA256 identities were verified first. Source checks also bound the three copied
package parent initializers before/after (55 files total). Remaining package
code and installed dependencies were reused, not silently called current-main.
No source stubs, extraction of target methods, install or native build were used.

This was a file-scoped invocation with explicit empty pytest config and plugin
autoload disabled, not the full project's conftest/CI environment. It establishes
that specific CPU test capacity only. A proposed lifecycle repair still needs a
discriminating original/fixed test with ordinary controls and real callers.
Mocked handle states cannot prove when an actual DMA stops writing or whether
buffers are safe to reuse; NIXL/RDMA failure, GPU correctness and throughput need
their own compatible environment and observations. Do not demand scarce hardware
for an exclusively Python control, or advertise a simulated pass as hardware
qualification. This setup check is not a new defect, PR or agent-policy result.

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

Before starting a cold install, inspect the exact required runtime, package
manager, lockfile and any surviving **task-owned** installation. A cache directory
alone proves neither complete artifacts nor usable resolution metadata. A
bounded same-lock offline attempt can answer that question; preserve its failure
and do not repeatedly retry an unchanged store. For
[pnpm](https://pnpm.io/cli/install#--offline), offline installation fails when
required packages are unavailable, and a workspace install normally includes
all workspace projects. A small owner test can therefore incur broad setup cost.
Do not silently filter the workspace, relax versions/integrity/release-age rules,
or substitute another project's installation to make setup pass. Resume reviewed
task-private partial acquisition when appropriate, keeping cancelled and failed
attempts separate. `--ignore-scripts` also leaves lifecycle work unexecuted;
verify the actual imports/native requirements of the selected test rather than
equating a successful install with a fully qualified package.

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

#### Offline Python startup before both source arms

Use the intended interpreter's standard-library
[distribution metadata](https://docs.python.org/3.12/library/importlib.metadata.html#distribution-files)
before hand-selecting directories from a reviewed task-owned installation:

```python
from importlib.metadata import distribution

dist = distribution("pytest")
print(dist.version, dist.requires)
if dist.files is None:
    raise RuntimeError("Installation file inventory unavailable")
print([str(path) for path in dist.files if len(path.parts) == 1])
```

Distribution and import-package names are not one-to-one. In the inspected
pytest 9.1.1 installation, the inventory includes the top-level `py.py` shim and
requirements include Pygments; copying only `pytest/` and `_pytest/` is incomplete.
Review all selected files and target Python/OS requirement markers, metadata and
licenses. This inventory is not dependency resolution, a content verification or
proof that extensions match the target ABI. Missing metadata means unknown.

Pure-Python artifacts do not make the source host's resolved dependency set
portable. [pytest-asyncio 1.2.0](https://github.com/pytest-dev/pytest-asyncio/blob/v1.2.0/pyproject.toml)
requires `typing-extensions>=4.12` only for Python below 3.13: an installation
resolved on 3.14 can omit it and fail plugin loading on 3.12 before any target
test. Re-evaluate `Requires-Dist` for the actual deployment environment, retain
the additional distribution's exact provenance/content, and preflight the
registered plugins there. Do not alter project imports or suppress tests to
compensate. This is a dependency-completeness condition, not an ABI guarantee or
a measured discovery benefit.

Before paying for both source arms, check actual import paths and run a tiny
fixture/parameterized startup test in a fresh authorized target. Retain bootstrap
failures separately from target assertion failures. An existing reviewed
pure-Python stack was reused offline on Linux Python 3.12: 472 files, 1,703,777
compressed bytes and 6,287,037 expanded bytes; all three startup cases passed.
This is framework feasibility, not project qualification or measured savings.
No new packager or mandatory workflow is needed. Where transport has per-file
limits, use reviewed chunks with archive/member hashes and bounded expansion into
private ephemeral storage; do not raise quotas to force a transfer through.

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

### Repeated doctest collection skips

A separate producer observation occurs when a module skips at import time:

```python
# sample.py
import pytest
pytest.skip("optional component unavailable", allow_module_level=True)
```

```python
# test_control.py
def test_control():
    assert 2 + 2 == 4
```

In a fresh reviewed directory with an explicit empty `pytest.ini`, compare
`python -m pytest -c pytest.ini sample.py test_control.py --junitxml=ordinary.xml`
against the same command plus `--doctest-modules` and a fresh `doctest.xml` path.
Use the actual authorized native runner and private output paths; this example
does not grant execution authority or require installing another pytest.

On Windows pytest 9.0.3, the ordinary invocation produced two case nodes and
declared two tests. The doctest invocation exited zero but emitted two case nodes
and declared three tests: one classless module record had two collection-skip
children. A Linux pytest 9.1.1 full-suite capture also contained this shape.
These are producer observations, not an exhaustive version matrix or an accepted
upstream bug diagnosis. The parser retains `INCONCLUSIVE`; neither equal reports
nor corrected-looking counters justify collapsing events into executed cases.
Preserve the original XML and command exits. Do not remove doctests, optional
modules or long parameter IDs solely to force structured acceptance.

## Threaded suites: task count is not resident memory

At more-itertools `4aeb4338ae1407d8da9723e86da99efeb446f719`, the complete original
stdlib unittest selection includes native `load_tests` doctests and a
[100-thread test](https://github.com/more-itertools/more-itertools/blob/4aeb4338ae1407d8da9723e86da99efeb446f719/tests/test_more.py#L7080-L7114).
The original full tree and assertions were not changed. One CPU sandbox run
retained all 929 parent test cases: three thread-start errors and one subsequent
callback doctest failure. Exit1, original source hashes, successful report
persistence, container removal and release were retained. A separate healthy
one-thread control passed and read the actual `pids.max=64`; it did not qualify
the larger concurrency requirement. A preceding owner quoting SyntaxError is
an owner-command failure, not another failed target control.

Do not infer seccomp denial or a target leak solely from "can't start new
thread". The kernel PID controller counts [threads as kernel tasks](https://docs.kernel.org/admin-guide/cgroup-v2.html#pid).
The scope of the complete failed invocation stays failed, even if other
sequential components ran. Do not decrease a target test's thread count, add a
skip or rename the full suite as passed to fit a resource profile.

A separately bounded native-host route (Python3.12.3, two CPUs, 3GiB
`RLIMIT_AS`, 90-second wall ceiling, private source/home/temp/cache, no GPU,
network or installs) still had three thread errors and MemoryError tracebacks.
This address-space limit is not a 3GiB RSS quota. A final fresh invocation kept
the same complete source/selection/limits and set **task-local**
`MALLOC_ARENA_MAX=2` before launching the interpreter. All 929 parent cases
passed, no errors/skips, with reaped-child peak RSS147940KiB. All original source
hashes were rechecked. The passing target interval was8.16s; that excludes earlier
failed setup, source transport, review and the direct-agent work below.

glibc [documents its arena setting](https://sourceware.org/glibc/manual/latest/html_node/Memory-Allocation-Tunables.html).
This is a scoped capacity repair, not proof that every thread failure is an
arena problem, that memory usage was reduced by a measured amount, or that
changing allocator settings improves production performance. The native route
is **not** equally isolated to the512MiB/64-task sandbox. Neither route qualifies
the project's other Python versions, coverage, lint, docs, packaging or CI.
Both failed invocations remain failures. No shared broker/resource limits were
changed; no indefinite same-case repair loop was started.

The existing `ObservedRunner` preserved real unittest/subtest events; the full
JSON was5.17MB. A compressed111KB report fit the broker's1MiB single-file budget
and was retrieved and decompressed by the owner. Do not clip events, rewrite
counts or give an agent every raw event merely to move a report. Parent counts
are not counts of every embedded doctest example or independent discoveries.

## Keep the outcome useful

Use identical test bytes and matched inputs for both arms, passing ordinary
controls as well as the regression. Record source/runtime identities, command,
all exits/skips/warnings, cleanup and cost once in the existing task record.
Collection/setup errors are not assertion failures or passes. A behavior difference
still needs the [actual consumer contract](scout_native_cpu_validation_notes.md#native-behavior-is-not-the-entire-acceptance-contract).
Separate an evidence-backed stop, environment limitation, author-owned fix and
reviewable new contribution. No test count or source-reader success establishes
PR yield, recall or evidence-selection research benefit.

For Scout answer validation, distinguish an oversized quote, an empty normalized
quote, a URL not supplied in the packet and a genuine excerpt mismatch. The
validator keeps the same 1..300-character limit and source-membership rules;
fixed diagnostic messages do not echo rejected text or URLs. A long literal
quotation can still be invalid without being invented. Do not trim it, promote
the old answer, retry the call automatically or rewrite historical verdicts.
An owner can separately inspect a useful context request and acquire reviewed
source/native evidence; that is a new observation, not a repaired model answer.

For a completed file-reporter capture, consume the returned
`record["test_report"]["path"]` and verify its recorded SHA256 rather than guessing
`pytest.xml` or another filename. For pytest JUnit the current runner writes
`junit.xml`; a task-local analyzer looking for the wrong name can fail after both
real test runs completed. Preserve that analysis failure and use the existing
bound reports in a separate analysis step, without rerunning tests, rewriting
XML or replacing the original capture verdict. This is file-report routing,
not a generic path field for every log-only format.

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

## Large default suites: native success is not report-budget admission

An additional capability check used
[`pypa/packaging` at fc61337](https://github.com/pypa/packaging/tree/fc613377731e5211ab6e08e6fd6163f09ae67ce8).
Its contribution/test instructions were read first. The deterministic raw-Git
bundle and thirteen wheel artifacts were verified; mirror-delivered wheels
matched PyPI publisher hashes. Standard offline uv/flit installation into a
fresh private Python3.12 venv produced `packaging 26.4.dev0`; all23 installed
production files matched the original source bytes. No stub/version overlay or
modification of the pre-existing environment was used.

The original default `python -B -m pytest -q` selection, with JUnit output added,
reported63,232 passes and one Python-version skip (`copy.replace` needs3.13).
Its431 opt-in property tests were deselected by the project's own configuration.
The pytest invocation took18.78 wall seconds on the bounded native route;
setup, acquisition and owner review are separate costs. Original tracked bytes
stayed unchanged and no owned process-group cleanup was required. This is one
Linux/Python3.12 run, not the nox/platform/property/coverage matrix or a PR result.
The trusted native route had two-CPU affinity,6GiB address space and a180s test
timeout; it was not the512MiB/60s default sandbox or OS/network isolation.

The untouched JUnit is8,373,718 bytes. A separate owner audit checked its raw
digest, suite totals,63,233 unique complete IDs and the one recorded skip.
At initial capture, the unchanged automatic reader rejected those same bytes
with `log exceeds 2 MiB`. The original rejection and native capture remain
historical; do not rewrite either as an automatic pass, truncate/rewrite XML,
or rerun the target merely to repeat a known reader rejection.

A subsequent [explicit large-report option](../scout_native_cpu_validation.md#bounded-large-pytest-reports)
reanalyzed the **same** 8,373,718-byte report with a declared 10 MiB allowance.
Its SHA256 remained
`81e9f99e0db0894edfb9999f253b83598840f3611ad3acf6afd86ea11c90c8e6`;
the parser's complete 63,233-ID outcome inventory matched an independent
ElementTree inventory, with 63,232 passes and one skip. Default rejection was
rechecked unchanged. No packaging tests or model requests were repeated.
The affected six reporter/runner test modules had 194 passes/50 platform skips
on Windows and 210 passes/31 platform skips on the bounded native Linux route.
Two private Linux launch failures (tool layout/cleanup API and missing imported
modules/fixture) were preserved separately before the successful complete
affected-module run; they are not target defects or successful verification.
This fixes input-budget admission, not the sandbox's 1 MiB file-write/persistence
limit, target execution authority, or automatic access to a full environment.
This environment preparation is not prospective study enrollment, a defect,
or evidence that a routing/model policy improves discovery or contribution cost.
