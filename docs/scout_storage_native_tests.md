# Storage-repository native verification

## Bounded Go/Rust owner-review selection

For another supported language, pass `owner_language="typescript"` (including
`.tsx`) or `owner_language="javascript"` (including `.jsx`, `.mjs`, `.cjs`).
Explicit `python`, `go`, and `rust` selections are also available. This mode is
owner-review-only, cannot be combined with `native_cpu=True`, and does not
change the automatic Python selector. It validates the immutable primary URL
before applying `scan_limit`, not a companion test's language. Match the actual
upstream toolchain and caller before running reviewed native tests.

Stage these leads only with `stage(delivery_root, leads, owner_review=True)`.
Automatic admission rejects the owner-only route and rolls back its batch;
workers cannot claim `OWNER_REVIEW_REQUIRED` rows. This is source admission,
not a native executor or evidence that a lead is correct.

Explicit owner selection also returns optional `owner_context`: up to three
known PR links and two same-file deferrals from the existing bounded history
readers. Inspect the actual patch and reopening condition before repeating a
repair. These are untrusted coverage hints, not current GitHub status, a
same-file blacklist, or instructions. They neither change selection order nor
rewrite the source packet, queue, or notes. Context is read only for returned
owner rows; the automatic selector's payload is unchanged.

The ordinary delivery worker still selects Python primary sources. For explicit
native CPU review, use the same read-only selector without staging a Python
proposal or pretending another-language source has been reproduced:

```python
from pathlib import Path
from kimi_scout_delivery_source import select_leads

leads = select_leads(
    Path("/path/to/private/scout-run"),
    limit=6, scan_limit=200, native_cpu=True,
)
for lead in leads:
    print(lead["id"], lead["repo"], lead["commit"], lead["verification_route"])
```

Only immutable same-repository Go/Rust **primary** source URLs are selected; a
later Python companion does not change the primary language. The language
filter runs before the SQL scan limit. Existing parent and staged-job exclusion,
exact-key deduplication and repository round-robin still apply. `scan_limit`
caps matching rows considered, not total SQL work or elapsed time.

`OWNER_NATIVE_CPU_REVIEW_ONLY` means review source, caller contract, duplicates,
baseline and target toolchain before a scoped native test. It is not an
architecture assertion, sandbox, compile request, queue state, reproduction or
publication approval. The Python loader still rejects these leads. Empty
selection is legitimate; do not relabel old jobs or invent results to keep a
queue busy. The existing native log/run tools require a reviewed command and a
separately authorized compatible worker.


The wide-research template includes JuiceFS storage/cache/metadata, SDK and sync
sources, plus LanceDB core, Python/TypeScript APIs and both native Rust bridges.
These prefixes select evidence, not executable tests or permission to run a model.
Keep the local runtime configuration in sync when changing the shipped template.

Adding a repository or recognizing `.go` / `.rs` source does not supply a native
verifier. Go/Rust leads must not be recast as Python leads because their packets
contain a companion Python test. Keep them available for matching native review.
The Python delivery selector filters native-primary packets before its bounded
scan, and its source loader rejects a companion-test substitution before fetching
or running anything. This prevents misrouting; it is not a Go/Rust executor.
Admission and source loading share the exact immutable-URL validator. Invalid
native URLs cannot hide a later valid Python source, and invalid Python URLs
cannot consume the bounded admission scan. Check both rejection and these
acceptance cases when changing routing; a stricter-looking SQL URL glob is not
equivalent to validating the commit and path.
This note records a bounded environment entrance and a scoped native regression
example, not automatic Scout execution, full-suite qualification or performance.

### Keep the rules comparator language-aware

The optional `scripts/kimi_scout_shadow.py` admission helper recognizes pinned
Go/Rust and C-family source as well as Python, CUDA and TypeScript. A `.go` or
`.rs` URL must not be reported as missing source simply because a legacy
extension list omits it. Same-repository and exact-commit checks still apply;
test-looking paths are only catalog hints, not proof of a registered test.

The `predecision-native-test-baseline-v2` version records the extension coverage
change for new admissions. Existing records use INSERT OR IGNORE and are not
backfilled or relabeled. If a study re-extracts development source clusters with
this helper, declare the helper/version anew; do not silently rescore a frozen
cohort. Recognition is not execution, correctness or an acquisition-benefit win.
The helper uses no model/network and cannot advance a candidate or dispatch work.

```text
python -B -m unittest tests.test_kimi_scout_shadow
```

### Deliver exact source without whole-archive RAM copies

Reuse `qualification-source-bundle` when a native reproduction needs committed
bytes on another host. It reads Git objects, not a dirty or CRLF-converted checkout;
it does not apply `export-ignore` or `export-subst` transformations. A normal
`git archive` is not evidence of raw-blob equality. This tool rejects Git submodules
rather than silently omitting their source.

```sh
python scripts/kernel_opt.py qualification-source-bundle --build \
  --repo /path/to/repo --commit EXACT_COMMIT --repository-url PUBLIC_REPOSITORY \
  --archive /private/source.tar.gz --manifest /private/source.manifest.json
python scripts/kernel_opt.py qualification-source-bundle --verify \
  --archive /private/source.tar.gz --manifest /private/source.manifest.json \
  --extract-root /private/fresh-source
```

The CLI streams blob contents and uses temporary disk files beside the archive,
so that directory must be writable with room for compressed and uncompressed
scratch data, plus any extracted source. Manifest/path metadata still scales with
file count. Verification hashes one captured snapshot and rejects changed inputs
before extraction or publishing a receipt. Existing archive/manifest/extraction
targets are not overwritten. The legacy Python `verify_bundle()` byte-returning
API still materializes the tar; use the CLI or `verify_bundle_into()` with a
seekable disk-backed scratch stream for low-memory verification.

An offline Windows Python 3.12 comparison of the exact JuiceFS `185d0df` source
(1,113 files, 51,223,760 raw bytes) preserved the old archive and manifest bytes.
Python allocation peaks changed from approximately 131/197 MiB to 3.8/6.0 MiB
for build/verify-and-extract. This is not RSS or Git-child memory, a sustained
throughput result, automatic Scout recovery, or a PR-conversion gain. The disk
tradeoff matters; keep source identity separate from native correctness and CI.

### Count saved native results before calling them verified

`scripts/scout_native_results.py` reads a bounded saved log (2 MiB maximum) and
an observed process exit code. It never fetches, imports or executes project code.
For Go, use [test2json events](https://pkg.go.dev/cmd/test2json) from `go test -json`
and an exact package. For Rust, use complete, verbose
[libtest](https://doc.rust-lang.org/rustc/tests/index.html) batches, not a tail
excerpt or arbitrary custom harness output. Supply exact expected test names:

```sh
python scripts/scout_native_results.py --format go-json --log go-tests.jsonl \
  --exit-code 0 --package github.com/juicedata/juicefs/pkg/sync --expect-test TestSync
python scripts/scout_native_results.py --format rust-libtest --log rust-tests.log \
  --exit-code 0 --expect-test remote::table::tests::test_query_plain
python scripts/scout_native_results.py --format pytest-junit --log report.xml \
  --exit-code 0 --expect-test 'tests.test_contract::test_case'
```

The tool reports passed/failed/skipped observations, missing expected targets and
incomplete/contradictory terminals. Zero executed tests, all ignored tests, a
different target, Go's replayed cached output, or a timeout cannot produce PASS.
Go counts include parent tests, subtests and repeats; they are not assertion or
independent-case counts. Rust measured/compact/custom batches are unsupported.
`expected_test_results` also counts pass/fail/skip observations for each exact
requested name, with zero counts for missing targets. To distinguish regression
cases from a parent or repeated executions, request the reviewed full subtest
names and compare their observations in matched baseline/fixed logs. A count
is still not an assertion count or a semantic independence proof. Details from
an INCONCLUSIVE result do not qualify execution; a reported failing Go test in
a passing package is a contradictory terminal, not a successful reproduction.
CLI exits are 0 for observed tests passing, 1 for observed test failures and 2
for inconclusive input. This does not change a delivery state or PR readiness.

For Python tests, retain the complete UTF-8 XML from `pytest --junitxml=report.xml`
and the actual pytest exit code separately. The saved-report reader accepts flat
`testsuite`/`testsuites` reports and identifies cases by exact
`classname::name`, including parameterized suffixes. It checks case outcomes
against suite totals and rejects duplicate identities, unexpected structure,
DTD/entities, and contradictory process exits. Setup/collection/teardown errors
are INCONCLUSIVE, not proof that the candidate reproduces an assertion failure.
An expected skipped or xfailed case does not qualify as executed. Some richer
JUnit dialects or duplicate teardown-error cases are deliberately unsupported.
For a matched regression, request the reviewed case set in both reports, verify
the same selected cases ran, and inspect which assertions failed before and passed
after. XML accounting does not bind the report to source, runtime or a native
library; preserve those identities and full integration evidence separately.
The saved-result reader never executes tests. The optional worker entrance below
can capture fresh pytest reports separately.

### Optional worker-side execution entrance

`scripts/scout_native_run.py` captures one **already reviewed** CPU test command
on an authorized POSIX worker. It is not an SSH dispatcher, environment builder,
model launcher, queue consumer or mandatory validation route. It refuses to run
on Windows; do not start local WSL to work around that refusal. Use the existing
authorized remote environment and its native tools instead.

For example, substitute the reviewed Git-blob hashes and actual private paths:

```sh
python /path/to/kernel_opt_agent/scripts/scout_native_run.py \
  --cwd /path/to/juicefs --output /path/to/private/fresh-result \
  --format go-json --package github.com/juicedata/juicefs/pkg/utils \
  --expect-test TestBuffer --timeout 120 \
  --source 'pkg/utils/buffer.go=REVIEWED_SHA256' \
  --source 'pkg/utils/buffer_test.go=REVIEWED_SHA256' \
  --source 'go.mod=REVIEWED_SHA256' --source 'go.sum=REVIEWED_SHA256' \
  --env GOENV=off --env GOTOOLCHAIN=local --env GOPROXY=off \
  --env GOCACHE=/path/to/private/build-cache \
  --env GOMODCACHE=/path/to/private/modules \
  -- /path/to/pinned/go/bin/go test -json -count=1 -timeout=60s \
     ./pkg/utils -run '^TestBuffer$'
```

For Rust, use `--format rust-libtest`, an exact expected libtest name, and the
repository's native Cargo command/profile or an independently source-bound test
binary. Pin and verify the full source, build inputs and environment separately;
selected file hashes alone cannot establish that a cached binary came from them.
In particular, two archived Rust source arms with the same package identity can
reuse one test binary when they share a Cargo target and preserve old mtimes.
A fresh process or fresh result directory does not isolate that build cache.
Prefer an arm-specific Cargo target; reuse dependency caches separately. If a
reviewed experiment deliberately shares its own target to save dependency builds,
clean only the affected package/profile before changing arms and verify that the
compiler rebuilt that package from the selected root. Retain an observable
before/after regression; a cached PASS or FAIL is not source attribution. Never
clean another task's target. Cargo documents [target-directory configuration](https://doc.rust-lang.org/cargo/reference/build-cache.html)
and [package/profile-scoped cleaning](https://doc.rust-lang.org/cargo/commands/cargo-clean.html).
Run the before/after commands into separate fresh output directories and retain
failing controls. The output directory's parent must already exist.

For an already prepared Python/native-binding test environment, use
`--format pytest-junit`. The runner appends
`--junitxml=FRESH_OUTPUT/junit.xml` to the reviewed pytest command and rejects
an existing JUnit output argument before launch. It retains stdout separately,
reads only the fresh regular report with a 2 MiB cap, and records both hashes.
Missing, malformed, oversized, skipped-target or setup-error reports cannot pass;
a report written before a command timeout does not bypass that timeout.

```sh
python /path/to/kernel_opt_agent/scripts/scout_native_run.py \
  --cwd /path/to/project --output /path/to/private/fresh-pytest-result \
  --format pytest-junit --expect-test 'tests.test_contract::test_case' \
  --source 'tests/test_contract.py=REVIEWED_SHA256' \
  -- /path/to/venv/bin/python -B -m pytest -q tests/test_contract.py
```

Use the actual qualified names from the selected repository's pytest report.
This does not install dependencies, build extensions or select the right native
source automatically. Bind imported module/extension identity and reproduce the
same failing and passing cases separately; a report alone proves none of those.

The entrance checks 1–64 selected regular source files (8 MiB maximum each)
before and after execution, records the resolved executable/content hash, hides
CUDA, and delegates complete log counting to the existing native-results parser.
Its command deadline includes compilation, child exit and output-pipe closure;
both command and overall invocation wall time are recorded. It caps captured
output at 2 MiB on disk, not an unbounded in-memory `capture_output`. Timeout,
overflow, changed inputs/tool or invalid UTF-8 cannot produce a partial-log PASS.
Timeout/overflow cleanup signals only its child's process group, including a
child that retains stdout after the original parent exits. This is not containment
of processes that deliberately escape that group, nor a filesystem/network/GPU
security sandbox; only reviewed commands belong here. Tests may still change
other files or use networks. No source patching, download or global install is
performed by this tool itself.

Only explicit environment overrides are value-hashed in the result; inherited
environment, dependencies and compiler caches are **not** attested. Keep raw
commands, paths and output private. No test counts or exit codes automatically
qualify a candidate, prove a useful oracle, or advance Scout/PR state.

Git-sensitive fixtures need repository isolation as well as fresh files. A temp
directory inside a checkout can inherit its enclosing repository through Git's
upward discovery, invalidating a test intended to exercise a non-Git directory.
Check the runtime's actual temporary root, inherited Git directory/work-tree
variables and discovery from the fixture before attributing a failure. Keep the
same environment for baseline and candidate. Prefer a verified non-repository
temp root for those cases; do not change tests intentionally probing nesting or
globally suppress Git discovery. Preserve confounded attempts separately.
See the scoped `git-sensitive-temporary-fixture-isolation` lesson and
[Git's discovery rules](https://git-scm.com/docs/git#Documentation/git.txt-GITDISCOVERYACROSSFILESYSTEM).

Development validation used a previously built, independently checked LanceDB
binary: six registered alteration tests pass, while an exit-zero selector matching
no native test stays INCONCLUSIVE. The same CLI executes one registered JuiceFS
`TestBuffer` with exact selected source hashes and an existing offline Go cache.
Linux process controls cover source/tool changes, oversized output, invalid UTF-8,
timeouts and a pipe-holding descendant; Windows controls prove no child is started.
These are runner/reuse checks, not a new repository correctness result, autonomous
Scout execution, model-cost improvement or PR-conversion measurement.

The pytest entrance was also replayed with separately verified native PyO3
bindings and all four [LanceDB #4455](https://github.com/lancedb/lancedb/pull/4455)
regressions: the unchanged arm reports two failures/two controls passing, and
the fixed arm reports four passes. Imported source/extension paths and binary
hashes were checked independently of the report parser. This is reuse of an
existing qualification, not another PR, a packaging test or policy-effect evidence.

For a native SDK pagination control, see
[`examples/scout-native-juicefs`](../examples/scout-native-juicefs/README.md).
It independently reproduces the existing JuiceFS #7578 fix with the real GCS
iterator. Small HTTP pages were an invalid first prototype because the SDK
aggregates them inside one `List` call; use full requested pages to reach the
outer retry boundary. The failed prototype remains private negative evidence.

The implementation was checked against saved native JuiceFS output (52 passing
terminal test events) and LanceDB output (266 passes, 1232 filtered). Two fresh
native commands deliberately matching no test both returned process exit zero;
both were rejected as INCONCLUSIVE. Unit controls also cover truncation, skipped
targets, contradictory counts/status, duplicated events and process failure.
Those controls prove accounting behavior, not better PR conversion or recall.

Logs can be forged and Rust output can interleave under `--nocapture`: ambiguous
or incomplete batches must stay inconclusive. Independently capture and bind
both arms' full output, source/runtime/command identities and exit status before
using this summary. It is not a sandbox, authenticity proof, oracle-quality
check, whole-workload measurement or permission to run unreviewed model code.

### Native declarations before incidental mentions

Recognizing `.go` and `.rs` is insufficient if bounded source-window selection
only recognizes Python/JS declarations. The selector now also recognizes Go
functions/receiver methods and common Rust function modifiers. Native functions
take priority over same-named local `let`/`var` bindings. Explicit start lines
still take precedence, and the source/revision, line and byte bounds are unchanged.

In a five-target development audit of pinned JuiceFS/LanceDB source, old windows
missed JuiceFS `Sync`, `startProducer` and LanceDB's remote `query` implementation;
the last window centered on a local `let query`, not the function. Updated windows
contain all five requested function declarations. The other two old windows
already contained their targets. This is inspected development evidence, not a
held-out retrieval-accuracy, model-quality, cost-saving or PR-conversion result.
Lexical matching is not a compiler/parser or call-graph proof: ambiguous receiver/
impl ownership, multiline declarations, macros and a truncated function still
require caller context or explicit source lines.

### Same-file native names are not unique implementations

For an automatically selected Go/Rust declaration, `definition_selection`
lists at most five same-name lexical declaration lines from already-read bytes,
with an omitted count. It does not change the selected window, resolve receiver/
impl ownership, fetch another file, or prove reachability. Use an explicit start
to inspect the intended implementation; unique names and explicit starts retain
their existing result shape. Multiline declarations/macros remain unsupported.

A development replay at pinned LanceDB `0be3ae96` found `NativeTable.query`
selected a trait declaration at line 605, not its implementation at 3582.
`create_index` and `wait_for_index` have the same three-declaration pattern.
The advisory adds 307–316 serialized bytes in these examples. Request
`declaration line 3582` to follow one of the controller-supplied alternatives;
arbitrary, conflicting, cross-pin and ambiguous-source requests are rejected.
The existing producer follows that request without increasing its read budget.
All three windows and the query-body followup used one cached source read. This is a
retrospective acquisition control, not measured model recall, cost or PR benefit.

### A basename is not a namespace or symbol owner

Initial issue triage still reads one ranked source file. When several ranked
observed-tree members share its basename and the report has not uniquely named
that full path, `path_selection` now exposes at most five candidates and an
omission count. These are unfetched naming hints, not symbol definitions or new
evidence. Request the actual path/import/definition before reasoning from a
same-named unrelated implementation; do not automatically download every match.

In the inspected [vLLM #58178](https://github.com/vllm-project/vllm/issues/58178)
development case, lexical ranking selected `fused_moe/oracle/mxfp4.py`, while the
named quantization method was in `quantization/mxfp4.py`. A retrospective replay
using the saved acquired paths now exposes both choices with 438 additional
serialized UTF-8 bytes and zero additional GETs. The first read is unchanged;
this is not demonstrated model-selection accuracy, cost saving, held-out
retrieval utility or PR-conversion improvement.

### An open report can already have an open fix

A title-only duplicate query can return the original issue and therefore miss a
fix with a different title. For an observed issue number, a bounded same-repository
PR-body search adds useful evidence: inspect explicit `#number` or full issue-URL
references, not incidental numeric matches. Keep the sample bound, observation
scope and unknowns; compare the actual reported mechanism before proposing work.
An explicit reference does not prove that a PR fixes the issue, passed tests or
merged, and an empty or partial search does not prove that no fix exists.

In four selected known-positive LanceDB development cases, the title queries
returned no PR, while the existing issue-reference lookup found related work:
[FTS-language panic #4369](https://github.com/lancedb/lancedb/pull/4369),
[nonfinite vectors #4410](https://github.com/lancedb/lancedb/pull/4410),
[projection order #4292](https://github.com/lancedb/lancedb/pull/4292) and
[all-null vectors #4034](https://github.com/lancedb/lancedb/pull/4034).
The unresolved [drop-table policy #4398](https://github.com/lancedb/lancedb/issues/4398)
returned no explicit PR in the bounded sample and remains a maintainer-design
question, not permission to change server semantics or perform a racy client
preflight. These selected examples are not held-out precision/recall,
model-quality, cost-efficiency or PR-conversion measurements.

The existing optional `owner-source-notes.json` also accepts a same-repository
GitHub PR URL as its `evidence_url`, alongside commit-pinned blob/commit URLs.
Its `source_url` must still pin a raw source file. This lets a reviewed
duplicate-coverage explanation survive without inventing a delivery record.
Links are advisory data, not current ownership, CI, merge or quality verdicts:
inspect the actual PR and current source before deciding what is covered.
The 64 KiB input, 24 recent distinct rows per repository and two same-file
prompt hints remain bounded. Foreign/private URLs and private artifact paths
are excluded. Advice neither replays identical source nor suppresses changed
source. This reader change does not relax the source-pinned owner-parking
command or restore a blocked model runtime; no conversion benefit is measured.

## JuiceFS: reusable Linux Go entrance

At [JuiceFS adcca1cc](https://github.com/juicedata/juicefs/tree/adcca1cc61bb4d668a945d64b2e176b44ac8e5b5),
`go.mod` requires Go 1.25.10. The tested toolchain was the official Linux/amd64
archive, 59,844,667 bytes, SHA256
`42d4f7a32316aa66591eca7e89867256057a4264451aca10570a715b3637ba70`.
Check [official download metadata](https://go.dev/dl/?mode=json&include=all)
before reusing or updating a toolchain; do not infer compatibility from its name.

Use a fresh task-private directory on a filesystem with enough actual free
space. Check the output directory itself, not only `/`: a home directory or
cache may be a separate nearly-full mount. Bind tool, source, module cache,
build cache and temporary files to that directory. A `/tmp` environment is
ephemeral; its continued existence and identity require checking before reuse.
Do not install globally, change persistent `go env` settings or use shared model
storage for compiler caches.

In the pinned clean Linux checkout, with `TASK_ROOT` pointing to the private
environment and the official archive extracted as `TASK_ROOT/go`:

```sh
CUDA_VISIBLE_DEVICES='' GOENV=off GOTOOLCHAIN=local \
GOMAXPROCS=2 GOMEMLIMIT=1024MiB GOFLAGS='-p=2 -mod=readonly' \
GOCACHE="$TASK_ROOT/build-cache" GOPATH="$TASK_ROOT/gopath" \
GOMODCACHE="$TASK_ROOT/modules" TMPDIR="$TASK_ROOT/tmp" \
GOPROXY=https://goproxy.cn GOSUMDB=sum.golang.org \
GONOSUMDB='' GONOPROXY='' GOPRIVATE='' \
"$TASK_ROOT/go/bin/go" test -json -count=1 -timeout=120s ./pkg/utils \
  -run '^(TestBuffer|TestSetBytes|TestNativeBuffer|TestAlloc)$'
```

Provision the directories first. `GOMEMLIMIT` is a soft runtime target, not a
hard process-memory sandbox. Apply a separate controller wall deadline covering
dependency download and compilation; Go's test timeout alone covers neither.
Track and terminate only owned child processes if that deadline is reached.

This exact invocation passed all four registered tests, with unchanged tracked
source. The successful invocation took about 10 seconds including its remaining
dependency/compile work. An earlier default-proxy invocation was stopped after
about 245 seconds without test results, after an independent connectivity check
found `proxy.golang.org` unavailable on that host. Preserve that failed attempt
and setup cost; do not report ten seconds as total environment acquisition cost
or a proxy speedup estimate. Keep checksum-database verification enabled when
changing transport; do not set `GOSUMDB=off` or silently fall back to direct fetch.

For a real candidate, inspect its current caller, test side effects and relevant
[contribution rules](https://github.com/juicedata/juicefs/blob/adcca1cc61bb4d668a945d64b2e176b44ac8e5b5/AGENTS.md).
Use native before/after tests at the candidate's exact source revision. These
four utility tests do not qualify metadata-engine parity, filesystem mounts,
object-store behavior, distributed correctness or a new revision. Use temporary
data/mocks; never mount, repair, delete or write shared user data.

### Native SDK request regression

[JuiceFS #7604](https://github.com/juicedata/juicefs/pull/7604) supplies small
real-SDK recording-transport tests for KS3, IBM COS and QingStor copy operations.
The original KS3/IBM control has three ordinary-key passes and fifteen special-key
failures on unchanged production source. QingStor independently has six plain-key/
Unicode passes and eight ASCII special-key failures. Exact fix commit
`f260bd5f7d51c58713ebcf6d31ccd83200740071` passes all thirty-two checks in a clean
Linux checkout. This is request-wire evidence without cloud credentials, not a
live-provider round-trip result.

Use the same private environment with `go test -count=1 ./pkg/object -run
'^(TestOtherSDKCopySourceEncoding|TestQingStorCopySourceEncoding)$'`.
Check each SDK's serialization and signing:
the pinned KS3 V2 signer lowercases header map keys, so a recording transport
must compare header names case-insensitively rather than interpret a failed
`Header.Get` as a missing request header. Preserve the negative capture attempt.

QingStor SDK v4.4.1 escapes headers only when they contain a non-ASCII character,
so a Unicode-only test can pass while literal ASCII `%41`, `%2F`, `?` or spaces
are still sent unescaped. Include ordinary, ASCII-reserved, Unicode, and mixed
Unicode/reserved controls when checking an encoding boundary. Its
[Copy Object API](https://docsv4.qingcloud.com/user_guide/development_docs/api/api_list/storage/object_storage/object/basic_opt/copy/)
requires an encoded source. The recording response must match the SDK's actual
operation status codes: both QingStor operations expect 201; a mock 200 response
caused unrelated multipart failures and was corrected before drawing conclusions.

Do not disable unrelated object backends merely to make compilation smaller:
existing package tests reference some of their types unconditionally. That tag
combination failed to compile, while the default package compiled and ran the
targeted test. Its cold invocation cost about eighty-one seconds, versus about
five seconds with the populated cache; neither is a throughput speedup claim.
Review supported build combinations separately (`go build -tags nos3 ./pkg/object`
passed for this fix), and distinguish a package build from a full test suite.

### Recursive scanner backpressure

[JuiceFS #7605](https://github.com/juicedata/juicefs/pull/7605) demonstrates why
acquiring a semaphore inside every newly created goroutine bounds active work,
not the number of waiting goroutines. With 2048 in-memory child directories and
two listing threads, unchanged source added 2068 goroutines; the fix added about
24–26 and still copied all files. This is a controlled waiting-goroutine test,
not million-directory RSS or remote-store throughput qualification.

For recursive producers, blocking on the same producer limit while holding a
parent slot can deadlock. The tested change tries asynchronous admission before
spawning, processes a child inline under backpressure, and releases the parent's
delimiter-listing slot before waiting for children. Check nested trees, filters,
files-from input, checkpoint restoration and destination content, not only a
flat work counter. Exact-head `pkg/sync` tests and isolated bound/nested race
checks passed. A combined race run found existing shared-error and progress
lifecycle races; keep those findings and baseline controls rather than calling
the whole package race-clean. Its cold race invocation, including compilation
and tests, cost about 129 seconds; do not label that as isolated compiler time.
Budget cold setup separately from the roughly 4–10 second warm isolated checks.

### Separate a new concurrency regression from existing lifecycle races

[JuiceFS #7606](https://github.com/juicedata/juicefs/pull/7606) fixes a separate
`--files-from` worker error race: assigning each listing result to the outer
`err` from opening the input file allows concurrent workers to overwrite it
before checking or logging it. A worker-local result removes that sharing.
The regression uses 128 independent prefixes, eight workers, flat listing and
one `Sync` per process; it checks actual destination bytes. Unchanged main
reports two race warnings, while the fixed exact commit passes the isolated
race test and normal `pkg/sync` suite.

Use unchanged production plus the same regression as the negative control.
If a combined suite exposes a different global progress lifecycle race across
repeated `Sync` calls, preserve that result and isolate the relevant scenario
in fresh processes. Isolation narrows attribution; it does not prove the full
suite race-clean or justify removing concurrent work from the target test.

### Follow the lifecycle failure without broadening the earlier fix

The progress race preserved above became a separate, independently reproduced
fix in [JuiceFS #7608](https://github.com/juicedata/juicefs/pull/7608). Every `Sync`
started an endless pending-progress updater; eight completed sequential calls
left eight goroutines behind (8 to 16 in the isolated control). Old updaters
also read the next call's replacement global bar. Concurrent calls are not
needed to reproduce this history-dependent failure.

The change captures the invocation's bar, cancels and joins its updater on
return, and joins before final progress accounting. At exact fix commit
`3f34b252081de3be3669e8539ec63a409bb66c47`, the normal `pkg/sync` suite and the
following repeated native race tests pass:

```sh
go test -race -count=3 -timeout=60s ./pkg/sync -run '^TestSyncStopsPendingProgress$' -v
go test -race -count=3 -timeout=60s ./pkg/sync -run '^TestSync$' -v
```

The new goroutine regression fails with unchanged production. The second
command is an existing upstream test; it independently reports the progress
race on unchanged main. This is stronger attribution than merely suppressing
a combined race test or running each invocation in a new process. Capturing a
bar alone would address stale-global reads but would still leak the updater;
cancellation without joining would not prove quiescence before reuse.

Keep this lifecycle fix separate from producer backpressure and worker-local
errors. It does not make simultaneous `Sync` calls supported, repair all other
background loops/error-path cleanup, or prove the full package race-clean.

## LanceDB: reusable native query-test entrance

At [LanceDB 0be3ae96](https://github.com/lancedb/lancedb/tree/0be3ae960eb39b43faad5685cd381c5126a305c5),
`rust-toolchain.toml` pins Rust 1.97.0; the workspace's 1.91.0 minimum is not that
pin. Python uses PyO3 and TypeScript uses napi-rs bindings. Follow its native
bootstrap instructions and matching lockfile; a released wheel with unrelated
Rust siblings is not exact-source verification of a binding change.

The pinned Rust 1.97.0 compiler, Cargo, standard library and rustfmt were installed
under a task-private Linux directory from official standalone archives, each
checked against the exact release manifest's SHA256. No global rustup/toolchain
configuration was changed. Protoc 24.4 follows the pinned repository's Linux
wheel workflow; its downloaded digest was recorded, but was not checked against
a separate publisher checksum. Check the current repository's requirements
before reusing these versions.

With a full LF Git export of the pinned source, this bounded compile check passed:

```sh
cargo check --profile ci --locked -p lancedb --no-default-features --features remote --tests
```

Use task-private `CARGO_HOME`, `RUSTUP_HOME`, `CARGO_TARGET_DIR`, `TMPDIR`, HOME and
PATH, exact protoc, two build jobs and an external wall timeout. An initial
libgit2 fetch of the locked Lance Git dependency timed out after about 48 seconds,
before compilation. A separate attempt with Cargo's supported
`CARGO_NET_GIT_FETCH_WITH_CLI=true` succeeded without changing source, lockfile or
features, taking about 347 seconds including dependency setup and compilation.
Keep credentials disabled for these public dependency fetches; do not infer a
missing revision from a network failure. The compiled/check cache occupied about
974 MB at that point. This is one environment observation, not a transport speedup.

The same pinned source subsequently executed a native Rust query test, followed
by all fifteen matching query tests with the populated cache:

```sh
cargo test --profile ci --locked -p lancedb --no-default-features --features remote \
  --lib remote::table::tests::test_query_plain -- --exact --nocapture
cargo test --offline --profile ci --locked -p lancedb --no-default-features --features remote \
  --lib remote::table::tests::test_query_ -- --nocapture
```

The first invocation passed one test and took about 465 seconds including native
code generation/linking; the test body took 0.05 seconds. The cached invocation
passed fifteen tests and took about 0.84 seconds overall, with 0.07 seconds in the
tests. The compiler cache then occupied about 4.6 GB. These are sequential setup
observations, not a benchmark or a model-efficiency claim. Preserve the preceding
tool/download/check costs when accounting for a new environment.

The same cached binary also passed all 266 tests selected by
`--lib remote::table::tests:: -- --nocapture`, using the same locked/offline profile
and features above. That invocation took about 4.3 seconds, including 3.53 seconds
in tests. It broadens the mocked remote-table regression baseline, not live-server
or binding qualification; it is still not the full Rust workspace suite.

These tests exercise the actual remote query implementation against mocked HTTP
responses, including vector/FTS request serialization and result decoding. They
do **not** qualify a live cloud service, a rebuilt Python/PyO3 or TypeScript
binding, the full Rust suite or a new candidate. Check that the result names the
expected tests and has a nonzero executed count: an exit-zero invocation with all
tests filtered out is not verification. `--offline` prevents Cargo dependency
fetches; it is not an OS network sandbox for arbitrary test code.

Start a candidate with a bounded test of its actual affected API in a private
temporary dataset, rebuilding bindings when required. Keep LanceDB wrapper
defects separate from Lance-engine defects and native backends separate from
cloud API behavior. Budget cold code generation/linking separately: successful
`cargo check` artifacts do not mean a native test binary is already built.

## Lifecycle cleanup must preserve streaming exits

For a listing/worker leak, exercise error paths **and** a caller's successful
early exit. A finite in-memory fixture can conceal a change that waits for all
listing input after reaching a copy limit. Use a paused native listing stream:
make enough objects available to reach the limit, hold EOF behind a test-owned
gate, and require the operation to return before releasing that gate. Always
release and join the fixture even when the assertion fails.

In the investigation of [JuiceFS #7609](https://github.com/juicedata/juicefs/issues/7609),
an unconditional-drain trial passed the normal sync package, but failed that
paired limit control; unchanged production passed it. The revised trial drains
error paths while preserving the successful short circuit. Error regressions
also cover initial source/destination failures, a recursive producer wider than
the prefix buffer, and a streamed failure with pending copies. Count specific
worker stacks or observe owned completion signals rather than claiming every
background goroutine is gone.

Keep composed race checks separate from standalone-head checks: tests with an
additional pending-progress fix do not prove that fix was part of the published
worker-error head. These controls support that scoped change, not a general
cancellation protocol, stalled-I/O recovery, performance improvement or a
prospective model-efficiency result.

## Wait for this submission, not a same-named old artifact

A replacement's resource name is not its operation identity. When an API returns
a job ID, test that its bounded wait follows that ID rather than an existing
same-named index, file or deployment. A useful adversarial mock keeps the old
artifact fully ready while the new job first reports `IN_PROGRESS`, then reaches
`DONE`, `FAILED` or `CANCELLED`. Assert the polled endpoint and job ID as well as
the returned value/error; a success-only mock can hide the wrong wait path.

For [LanceDB #4402](https://github.com/lancedb/lancedb/issues/4402), native Rust
HTTP-mock regressions on `0be3ae96` demonstrate early success without polling the
returned index job. Cover a still-running job's deadline, failure details,
cancellation, no explicit wait, the existing maximum timeout, and the legacy
server response without a job ID. Keep explicit job waiting and older
name-based compatibility paths separate. An initial mock incorrectly expected
`replace=true` on the wire; production omits that default. That fixture failure
is not a product regression and is retained separately from the corrected
before/after run. These tests do not establish live-cloud or language-binding
qualification, synchronous server validation, or a performance improvement.

## Zero-valued replacements are not omitted fields

When storage uses an ORM, test nonempty-to-empty overwrites, a shorter nonempty
replacement, returned metadata, and an unrelated key. A successful update count
alone does not establish that zero-length data and size replaced the old values.
Inspect both UPDATE-column selection and WHERE-condition construction: an API
that forces zero-valued columns may also force zero predicates in a condition
bean, turning a proposed fix into a no-match update.

In [JuiceFS #7612](https://github.com/juicedata/juicefs/pull/7612), native SQLite
controls reproduce retained old bytes/size for empty and nil replacements.
An initial `MustCols` trial also affected condition construction and failed;
`Cols("size", "data")` explicitly updates the replacement without changing the
key predicate or automatic modification time. The final focused tests and
three repeated race runs pass, including the unrelated-key control. This is
SQLite-backed source evidence, not live MySQL/PostgreSQL, full-suite or
performance qualification. Check the actual pinned ORM rather than inferring
semantics from another version or an API name.

## Peer-backend comparisons still need an explicit contract

For an implementation of a shared API, apply the same small boundary matrix to
an established peer backend and the candidate backend. This can distinguish a
backend divergence from a fixture misunderstanding, but the peer is not a
universal oracle: inspect the caller and API meaning before treating parity as
required. Keep explicit expected results rather than copying arbitrary peer
output as the truth.

[JuiceFS #7614](https://github.com/juicedata/juicefs/pull/7614) checks an inclusive
prefix separately from an exclusive marker. Memory passes the common matrix;
unchanged SQLite omits the exact-prefix key and can stop on a nonmatching key
after an earlier marker. Cover missing/earlier/equal/later markers, an empty
match set, and concatenated one-key pages. Fixing the first page with `>=`
everywhere would instead duplicate explicit marker keys. Native SQLite and
memory regression/race checks do not qualify live MySQL/PostgreSQL or prove a
model-efficiency gain.

## Native row-ID reads: membership is not occurrence-preserving take

The proposed direct-read route in [LanceDB #4429](https://github.com/lancedb/lancedb/issues/4429)
needs a compatibility check before performance work. At
[LanceDB 0be3ae96](https://github.com/lancedb/lancedb/tree/0be3ae960eb39b43faad5685cd381c5126a305c5),
a native stable-ID fixture requests `[5, 1, 5]`: public `Table::take_row_ids`
returns membership `[1, 5]`, while underlying `Dataset::take_rows` retains
occurrences `[5, 1, 5]`. Ordering is not promised by the public API; losing or
adding occurrences is a separate question. Empty requests, unsorted IDs, misses,
deletes and checked-out historical versions are independent controls.

The small [native probe](../examples/scout-native-lancedb/take-row-id-contract.patch)
adds one Rust test with six explicit cases and a non-executing plan explanation
to that exact upstream checkout. It changes no production implementation.
Apply only to a separate clean checkout at the pinned commit, then use its
declared toolchain/dependencies:

```sh
git apply /path/to/kernel_opt_agent/examples/scout-native-lancedb/take-row-id-contract.patch
cargo fmt --all
cargo test --profile ci --locked -p lancedb --no-default-features --features remote \
  --lib test_probe_ -- --nocapture
```

Keep the actual query's projection, snapshot and logical read routing in any
eligible fast path. In this pin, [native query planning](https://github.com/lancedb/lancedb/blob/0be3ae960eb39b43faad5685cd381c5126a305c5/rust/lancedb/src/table/query.rs#L170-L191)
can include un-compacted MemWAL data; a base-dataset shortcut needs an explicit
compatible route or fallback. That is source evidence, not an executed MemWAL
test. The probe uses different projections for the two readers and the `ci`
profile is unoptimized: neither its runtime nor the older downstream benchmark
qualifies a current-main performance gain. Compaction, metadata projections,
legacy-ID deletion/snapshot cases, remote execution and additional builder
features remain untested.

### Check the physical work before attributing scan savings

The same probe now includes one physical-work test: two table sizes (512 and
65,536 rows), each with legacy and stable row IDs. A membership request
`[5, 1, 5, 17]` projects only `id`, returns three distinct rows, and records
`rows_scanned=3` in all four cases. A same-projection full-scan control records
512 and 65,536 respectively. This qualifies the row-reader counter at this pin,
not bytes fetched, page decompression, cold-storage cost or a latency speedup.

The lock pins [Lance e5a3553b](https://github.com/lancedb/lancedb/blob/0be3ae960eb39b43faad5685cd381c5126a305c5/Cargo.lock#L5145-L5147).
Its [scanner](https://github.com/lance-format/lance/blob/e5a3553b1699a7062ff7afe4ee268d596bbf2e0d/rust/lance/src/dataset/scanner.rs#L3318-L3338)
recognizes the row-ID predicate and invokes a take source; the
[mask/read path](https://github.com/lance-format/lance/blob/e5a3553b1699a7062ff7afe4ee268d596bbf2e0d/rust/lance/src/dataset/scanner.rs#L3839-L3908)
preserves membership rather than duplicate occurrences. Thus a current-version
fast-path proposal cannot attribute its gain to removing a full-row scan that
is not occurring. Planning/materialization overhead may still matter; isolate
that mechanism with matched API, projection, snapshot and an optimized profile.
Neither the older downstream result nor an unoptimized test runtime supplies
that measurement.

## Rejected responses and returned streams have different owners

Follow both exits of an HTTP-backed storage method. When an error returns a nil
body, the method must release the acquired response; the caller cannot do so.
When success returns a body, ownership transfers to the caller. An unconditional
deferred Close would break that successful streaming contract.

The [JuiceFS native regression](https://github.com/adenzhou1350/juicefs/blob/c136a937ebf46e08b375022782cee3a3f4122adf/pkg/object/download_body_test.go)
holds a real HTTP response open after flushing headers and four body bytes.
Across Qiniu and Dragonfly, unchanged code leaves six rejected-status requests
running (404/416/500); the scoped two-line fix releases them. Positive 200/206
controls read the bytes and observe cancellation only after caller Close. Always
release the fixture on assertion failure. Repeated native/race checks qualify
this ownership boundary, not cloud credentials, connection reuse or throughput.

## Positive HTTP controls must satisfy the SDK protocol

A status-200 JSON fixture is not necessarily a successful SDK request. In
[Qiniu v7.26.8's interceptor](https://github.com/qiniu/go-sdk/blob/5f8f7f02881515c3d88ee76a6b29097ac3c2c473/internal/clientv2/interceptor_anti_hijacking.go#L19-L29),
responses with neither a request-ID nor a log header are rejected as potentially
hijacked. Its retry classifier treats that error as retryable. A local success
fixture needs a valid operation response and an appropriate `X-Reqid` or
`X-Log` header; do not disable production validation to make the test pass.
Check the real verb too: this revision uses GET for Stat and POST for Copy/Delete.

Run a successful request control before attributing a cancellation timeout to
production. Use nonblocking fixture notifications, bounded clients, and release
held requests on every failure path; retries can invoke the handler more than
once. Keep invalid-fixture failures separate from reproduced contract defects.

Then inspect the exact dependency interface. This pin's
[Stat/Copy/Delete wrappers](https://github.com/qiniu/go-sdk/blob/5f8f7f02881515c3d88ee76a6b29097ac3c2c473/storage/bucket.go#L533-L601)
take no context and call the underlying API with `context.Background()`.
JuiceFS forwarding context to List does not fix those operations. Do not invent
WithContext methods or return early while leaving an unowned request running.
Choose a reviewed dependency extension or a separately tested context-aware API
integration, preserving endpoints, credentials, metadata and error semantics.

The [separately tested existing typed-API integration](https://github.com/adenzhou1350/juicefs/blob/79205416364f19a9e31bbac5c0ec7757670d7f42/pkg/object/qiniu_context_cancellation_test.go)
uses the same pinned SDK rather than adding a dependency version. Twelve exact
Head/Copy/Delete cancellation/deadline cases fail on unchanged production and
pass after context forwarding; nine 200/612/403 controls pass on both versions.
Five focused race repeats pass. The fixture also checks the actual `Qiniu`
authorization scheme; an earlier `QBox` expectation was a fixture failure,
not a changed authentication contract. A broad package race run exposes an
independently reproduced existing delimiter-list race, while ordinary package
tests pass with the disclosed baseline TestDisk2 exclusion. Do not call this
a full race-suite, live-cloud or performance qualification.

## Worker-local locks do not protect shared traversal state

Trace which synchronization object orders each read and write. Several workers
holding their own mutexes do not protect a stop/error variable written by the
parent traversal. In the
[JuiceFS delimiter walker](https://github.com/juicedata/juicefs/blob/adcca1cc61bb4d668a945d64b2e176b44ac8e5b5/pkg/object/object_storage.go#L245-L327),
that mistaken sharing triggers the native race detector. The proposed fix keeps
the traversal error local and uses a walk-owned atomic stop signal instead.

The [matched regression](https://github.com/adenzhou1350/juicefs/blob/185d0df3c62d9a618442fe1c31e4fa010f31a4d7/pkg/object/object_storage_test.go#L1129-L1221)
uses the actual memory backend with concurrent nested directories, complete and
bounded output, deep starts and initial/child/grandchild failures. Unchanged
production reproduces the race; the exact fixed head passes five focused race
repeats and the object-package race selection with the already disclosed
TestDisk2 exclusion and environment skips. A stop flag is not proof of joined
workers or cancellation of an in-flight backend request.

An extra matched sync selection reports five passing leaf tests but fails at
package level with progress-bar races on both unchanged and fixed source.
Preserve that failure: do not claim a passing package from leaf counts, fold it
into this patch's causality, or silently change the recorded command. Isolate a
new mechanism in a separate matched check. Neither this proposed fix nor its
knowledge lesson qualifies full upstream CI or a performance/model-cost gain.
The reusable synchronization lesson is separate from the existing
helper-contract/owner-lifetime card; frozen study records are not rescored.

The independent progress race already has [PR #7608](https://github.com/juicedata/juicefs/pull/7608);
do not rediscover it as another candidate. A fresh composition of delimiter head
`185d0df` and progress head `3f34b25`, both based on `adcca1c`, passes
six selected sync tests under `-race -count=3` (18 executions), including the
pending-progress lifecycle regression. The composition used raw Git-blob bytes,
offline native Go 1.25.10 and explicit source hashes. This resolves the observed
focused blocker, not full sync CI or either PR's standalone race-suite coverage.

## Backend cancellation is not pipeline cancellation

Follow the request and the outer producer separately. In
[JuiceFS adcca1cc](https://github.com/juicedata/juicefs/blob/adcca1cc61bb4d668a945d64b2e176b44ac8e5b5/pkg/object/sharding.go#L145-L155),
the S3 SDK stops a canceled next-page HTTP request, but the ListAll loop keeps
retrying the resulting error every 100ms. A local HTTP fixture using the actual
SDK distinguishes request cancellation, deadline expiry and cancellation during
retry backoff; a 503-then-success control protects ordinary transient retries.

The [paired regression and proposed scoped fix](https://github.com/adenzhou1350/juicefs/tree/eff22d2d246f97934b99d8dd8e847693a14dca3e)
retain the nil failure sentinel while the consumer drains output. Teardown
bypasses the failed backend only to join the unchanged producer after a failing
assertion; it is not the tested fix. This does not qualify blocked-output,
delimiter/sharded or context-ignoring backend cancellation. Those need distinct
consumer/producer controls. Related closed, unmerged
[PR #7136](https://github.com/juicedata/juicefs/pull/7136) already proposed broader
retry changes: acknowledge that prior work, and do not label this mechanism a
new discovery or the local tests as cloud/performance qualification.

## Failed uploads need abort, not successful finalization

A resource's Close is not always failure cleanup. For a GCS upload Writer,
Close finalizes the object. When the input Reader fails, cancel an upload-owned
child context instead of unconditionally calling Close or canceling the caller.
Successful uploads must still finish through Close.

The [real-SDK regression and proposed fix](https://github.com/adenzhou1350/juicefs/tree/8e7be7b2e810b833df95eb0cc8c57269ed383c0b)
cover errors before/after one full chunk, then empty, small and multi-chunk
success. Both errors leave SDK cancellation monitors running on unchanged
production; the child-context fix releases them without committing failed
uploads or changing the caller context. The monitor assertion observes a
revision-specific internal stack frame, not a public SDK guarantee. The fixture
uses HTTP200 plus X-Http-Status-Code-Override=308 for unfinished chunks because
the pinned client requests that protocol; literal HTTP308 was an invalid first
fixture, not a target failure. Cancel and join fixture work even on assertion
failure so one case cannot mask the next.

Focused tests and three race repeats pass. The object-package run explicitly
excludes baseline-failing root-permission TestDisk2 and has skipped tests; this
is not complete upstream CI, live-GCS validation or measured throughput. The
existing owner-lifetime lesson incorporates the abort/commit distinction; no
new card or mandatory workflow is needed, and automatic Scout conversion or
model-cost benefit remains unmeasured.

The submitted [GCS PR #7617](https://github.com/juicedata/juicefs/pull/7617)
and [Qiniu List PR #7618](https://github.com/juicedata/juicefs/pull/7618)
are public reproductions, not merge or CI guarantees. The latter distinguishes
caller-context forwarding from outer retry lifetime; neither fixes every
operation of its backend.

## Reject unsupported wire types through the real native API

An Arrow type being valid in memory does not mean a remote wire serializer can
represent it. Call the actual public operation with supported and unsupported
types before changing the protocol or rebuilding every language binding.
[LanceDB PR #4430](https://github.com/lancedb/lancedb/pull/4430) exercises
`alter_columns` with Utf8View, BinaryView and a nested view: all three panic on
unchanged production, while the scoped fix returns `InvalidInput` before any
HTTP request. Existing supported-type payload tests stay passing.

The Rust remote-table selection has 269 passing tests, with locked offline
dependencies, Clippy and formatting checks. These native API/HTTP-mock results
do not qualify live Cloud or rebuilt Python/Node bindings, add view-type server
support, or prove performance. A serializer limitation, server error mapping,
and binding exception translation are separate contracts. Inspect prior work
for each before opening another fix.

## Preserve callback ownership when batching

The next useful evidence can be a public registration path, not another GPU run.
[Transformers' pinned router](https://github.com/huggingface/transformers/blob/469230357aab0f2b303b0d638c1f8d06edb14184/src/transformers/generation/continuous_batching/continuous_api.py#L87-L131)
stores a loop per handler but batch delivery schedules every callback on the last
loop. The [native CPU example](../examples/scout-native-transformers/README.md)
initializes a real tiny model/manager and registers on two actual debug-mode loops.
Reversed-order paired tests fail unchanged and pass when callbacks are grouped by
owner loop; single-output, one-loop streaming, cleanup and queue fallback remain
controls. This establishes a routing component failure, not generated-token
correctness, production prevalence or performance. The target's autonomous-agent
publication restriction remains a separate stop, even after a reproduced fix.

The scoped `batch-by-executor-affinity` lesson is optional searchable advice.
Source review should still establish whether the next router permits several
loops; a single-loop enforcement or explicit proxy can make the analogy invalid.
These retrospective cases do not rescore the frozen prospective study or establish
better PR conversion, model cost or a publishable research result.

## A failed helper assumption is not yet a failed consumer

The [native TorchTitan example](../examples/scout-native-torchtitan/README.md)
checks real cleanup and tensor-wrapper consumers without replacing project
modules. In the observed runtime, detached FSDP wrappers report no alias even
though their inner tensors share storage; ModelWrapper's copy fallback still
preserves cache storage and current/loaded values. Test that consequence before
turning a helper predicate into a corruption claim. Real one-rank CPU DTensor
controls are useful but do not qualify distributed staging or full checkpoints.
An unrelated official-suite import failure remains NOT_RUN, not an excuse to
call a narrower component check full CI. The existing helper-contract lesson
already covers this decision; no duplicate knowledge card or mandatory gate is
needed. This post-outcome NO_LEAD audit does not prove zero misses or model value.

## Record source review without a redundant model call

For a bounded set of already inspected `select_leads` results, the existing Python
API supports `stage(delivery_root, leads, owner_review=True)`. New rows go directly
to `OWNER_REVIEW_REQUIRED`; automatic `claim()` cannot execute them. This is an
unverified handoff with empty results and zero reported model tokens, not a test
pass, human signoff or rejection. Existing rows, observations and dispositions
are never overwritten by repeated intake. Record the source-review decision in
the existing owner workflow; the selector then excludes the admitted source IDs.
The normal default still schedules unseen leads for model work. Exact-key/source
deduplication does not prove semantic uniqueness or measured conversion savings.

Two concrete omitted-context controls illustrate when this helps:

- [SGLang's root initialization](https://github.com/sgl-project/sglang/blob/50be533d09bde329bface6f1ac0631af93b528bf/python/sglang/srt/mem_cache/radix_cache.py#L333)
  sets root lock_ref to one, and reference updates stop before the root. A proposed
  root-eviction failure that assumes zero misses this owner invariant.
- [TensorRT-LLM's constructor](https://github.com/NVIDIA/TensorRT-LLM/blob/80f1809362f1a1e5d5eafc5ac0e744b98e13f271/tensorrt_llm/_torch/pyexecutor/scheduler/scheduler_v2.py#L216)
  sets max_context_length from max_num_tokens; the scheduling loop creates a new
  BudgetTracker each iteration. Repeating a helper with a fixed depleted budget
  does not reproduce permanent total-budget starvation. This does not resolve
  the separate unit-rounded-block extent problem: an upstream test that asserts
  one SKIP is not proof of eventual progress. Keep that native-caller question
  inconclusive instead of treating all deferral as either a bug or a no-bug result.

These are revision-bound source controls, not full runtime qualification. The
existing helper-contract lesson applies; no duplicate card or required phase is
needed. Use `tests/test_scout_owner_intake.py` for native offline queue/claim,
duplicate-preservation and selector integration checks.
