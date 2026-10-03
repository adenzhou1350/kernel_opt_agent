# Storage-repository native verification

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

## LanceDB: not yet a verified entrance

At [LanceDB 0be3ae96](https://github.com/lancedb/lancedb/tree/0be3ae960eb39b43faad5685cd381c5126a305c5),
`rust-toolchain.toml` pins Rust 1.97.0; the workspace's 1.91.0 minimum is not that
pin. Python uses PyO3 and TypeScript uses napi-rs bindings. Follow its native
bootstrap instructions and matching lockfile; a released wheel with unrelated
Rust siblings is not exact-source verification of a binding change.

No native LanceDB environment or regression has been validated by this probe.
Start with a bounded test of the actual affected API in a private temporary
dataset, rebuilding bindings when required. Keep LanceDB wrapper defects separate
from Lance-engine defects and native backends separate from cloud API behavior.
Do not launch a broad Rust build or populate a large discovery queue merely to
fill concurrency; first establish a reusable relevant test entrance and budget
its cold setup cost.
