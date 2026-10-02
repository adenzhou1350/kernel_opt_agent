# Native CPU tests before broadening Scout discovery

Add a repository when a supported baseline can actually run, not just because
source is available. A baseline may reveal a known upstream failure; retain it
and compare the same affected tests before/after a candidate. Do not suppress
warnings or weaken assertions to manufacture a green environment.

## Windows-native TypeScript checks without bypassing runtime requirements

Read the reviewed checkout's `package.json` engines and test wrappers before
running it. A locally installed Node executable can be too old even when its
major version matches. Use a task-private official portable runtime; check the
archive against the corresponding [Node release checksums](https://nodejs.org/dist/v24.16.0/SHASUMS256.txt)
before safe extraction. Do not replace global Node, reconcile shared dependencies
or launch local WSL as a fallback.

For owner-reviewed OpenClaw code with already-ready dependencies, use its native
wrapper and one relevant test. Prefix PATH only in that child environment so
spawned Node processes use the same reviewed runtime. Set TEMP and TMP to a fresh
task-owned directory on the intended storage drive **before** launch; a D-drive
checkout alone does not keep generated workers and temporary state off C.

```powershell
$env:PATH = "$taskNodeDirectory;$env:PATH"  # this test shell only
$env:TEMP = $taskTempDirectory
$env:TMP = $taskTempDirectory
& "$taskNodeDirectory/node.exe" scripts/run-vitest.mjs run src/cron/store.test.ts -t "cascades authority deletion and permits a fresh recapture" --maxWorkers=1
```

One observed Windows check at OpenClaw `3e49333709714693f39d393f03f0c3ab92cedb74`
with Node 24.16.0 passed that existing real save/load deletion test (1 pass,
75 skipped; 41.31 s process wall, including 19.34 s cold worker preparation).
It emitted retained SQLite-singleton and non-group descendant-cleanup warnings;
retain those warnings and do not delete a reported namespace solely because the
parent returned success. This is one historical-checkout result, not current-main,
full-suite, candidate-discrimination or sandbox evidence.

The separately reviewed source at `bf3f9d7256f25ef80cde36dbb2c2061d085e9eea`
declares [authority-row cascade](https://github.com/openclaw/openclaw/blob/bf3f9d7256f25ef80cde36dbb2c2061d085e9eea/src/cron/store/runtime-authority-store.ts)
and [foreign-key connection setup](https://github.com/openclaw/openclaw/blob/bf3f9d7256f25ef80cde36dbb2c2061d085e9eea/src/state/openclaw-state-db-open.ts).
Inspect both before treating a missing manual child-row DELETE as a bug. A
different connection, migration or failing supported flow can overturn that
counterevidence. No autonomous delivery profile or PR promotion is enabled by
this recipe; arbitrary model-generated code still requires secretless isolation.

## HTTPX example

The [official contribution guide](https://www.python-httpx.org/contributing/)
routes installation through `scripts/install` and tests through `scripts/test`.
Its CI installs `requirements.txt`; `scripts/test` uses coverage + pytest when
`GITHUB_ACTIONS=true`. That flag deliberately omits the separate linting and
coverage-threshold steps. These commands are native tests, not complete CI.

Use a reviewed **full Git source export**, not one module over unrelated installed
siblings. Export with `git -c core.autocrlf=false archive` on Windows too; verify
important members against raw Git blobs. Keep `.git`, credentials, local config,
model weights and unrelated files out of the build context/source export.

Build the [example Dockerfile](../examples/scout-native-httpx/Dockerfile) with a
`source.tar` in its small task-private build context. The pinned Python 3.10 base
must already be cached. Installing public dependencies needs network only during
this secretless setup step; run project code only inside the container. Record
the resulting image ID and `/opt/dependencies.freeze.txt`. Upstream intentionally
leaves some dependencies unpinned: rebuilding later need not yield the same image.

For each complete baseline/candidate export, use the same immutable image:

```sh
docker run --rm --init --pull never --runtime runc \
  --network none --read-only --user 65534:65534 \
  --cap-drop ALL --security-opt no-new-privileges=true \
  --memory 768m --memory-swap 768m --cpus 1 --pids-limit 64 \
  --tmpfs /tmp:rw,nosuid,nodev,size=256m,mode=1777 \
  --mount type=bind,src=/absolute/source-export,dst=/input,readonly \
  --env HOME=/tmp --env GITHUB_ACTIONS=true --env PYTHONDONTWRITEBYTECODE=1 \
  --entrypoint sh sha256:REVIEWED_IMAGE_ID -c '
    set -eu
    cmp /input/requirements.txt /opt/httpx/requirements.txt
    cmp /input/pyproject.toml /opt/httpx/pyproject.toml
    cp -R /input /tmp/source
    cd /tmp/source
    python -c "import httpx; assert httpx.__file__.startswith(\"/tmp/source/httpx/\")"
    sh scripts/test -m "not network" -q
  '
```

Do not mount the Docker socket, home directory or devices inside the container,
publish ports, or inherit operator credentials. Track the owned container ID and
bound its execution; on timeout inspect/stop only that container. HTTPX's local
test servers then use its private network namespace, not shared host ports.
Dependency-manifest drift needs a new reviewed environment, not an ignored `cmp`
failure. Extra candidate regressions can be passed to the native test script;
keep source/import provenance and both arms' results.

## Observed boundary, not a new bug or throughput claim

At HTTPX `b5addb64f0161ff6bfe94c124ef76f6a1fba5254`, Python 3.10.19,
pytest 8.4.1, Trio 0.31.0, AnyIO 4.15.1 and httpcore 1.0.9, the unmodified native
offline suite produced **1,412 passed, 1 failed, 5 deselected**. The failure was
`test_write_timeout[trio]`: `ByteStream.__aiter__` was finalized before exhaustion.
[PR #3777](https://github.com/encode/httpx/pull/3777) and
[PR #3700](https://github.com/encode/httpx/pull/3700) already cover this problem;
do not open a competing fix. This is not an environment-wide failure or proof of
an unrelated candidate. Keep the exact baseline failure visible.

The cached native test command took about 8 seconds in that one run; cold image
setup time was not recorded. This is not cold setup cost, a speedup, or Scout PR
conversion evidence. Five network-marked cases were not run; external network,
proxy behavior, other Python versions, lint, package/docs build and the 100%
coverage threshold remain separate checks. HTTPX generally asks for a prior
Discussion before escalation to an Issue/PR; verify current policy before posting.

This optional owner recipe does not add an automated delivery profile, enable
network in model-generated tests, or promote a candidate to Ready. Native capacity
and publication quality still require independent evidence for the actual lead.

## Optional delivery use of the reviewed HTTPX image

`kimi_scout_delivery.py --httpx-native` enables a **generated-test package screen**
for HTTPX only; it is off by default. The cached profile currently binds the
exact source revision above and image
`sha256:ad47b9d7b2ed3afc265fdf95732bd35527cdf092362ba4382c722949a36a4309`.
This is a locally reviewed image ID, not an image available for registry download.
Use the setup recipe before opting in; a rebuilt image or later source revision
requires its own reviewed identity rather than silently replacing this profile.

The controller passes the fetched revision, module path and baseline byte digest.
Each container checks its original module against that digest **before** loading
any candidate or generated test, copies the complete package into private scratch,
overlays only the selected file and checks package/subject import paths. Sibling
modules and dependencies are the same in both arms. Network, credentials, devices,
installation and host ports remain unavailable; memory is bounded at 768 MiB and
the delivery timeout remains 30 seconds per arm. Reserve sufficient controller
memory as well; the memory cap is not a proof of current host headroom.

For a reviewed local pair, the same route can be invoked directly:

```text
python3 -I -B scripts/kimi_scout_verify.py \
  --baseline /private/baseline.py --candidate /private/candidate.py \
  --test /private/test.py --profile httpx-cpu \
  --module-path httpx/_urlparse.py \
  --source-commit b5addb64f0161ff6bfe94c124ef76f6a1fba5254 --timeout 30
```

This is not HTTPX's full native pytest suite. Generated assertions and output
remain untrusted evidence, requiring owner review of the contract, actual caller,
duplicates, native tests and contribution policy. Missing images or mismatched
preimages/imports remain inconclusive, never a pass. Old blocked, reviewed or
published records are not reset or replayed when enabling the flag.

In an exposed IPv6 development case, the package screen ran three identical
tests per arm: baseline had two errors plus a passing normal control, candidate
passed all three; both owned containers were removed. A deliberately wrong
baseline stopped before testing in both arms. These checks establish runnable
capacity and rejection behavior, not prospective PR conversion or cost savings.

## Windows-native checks of owner-reviewed code

Local WSL is not required to test an already reviewed Python change. Use a fresh
Windows virtual environment and full source exports for both arms. This is an
owner-run test route, **not a sandbox for arbitrary Scout-generated code**. Do
not connect unreviewed queue entries to it or treat Python's `-I` flag as isolation.

For the URL tests, the native environment needs HTTPX's runtime dependencies
plus the upstream test/conftest dependencies: pytest, Trio, trustme,
cryptography, uvicorn and sniffio. Install them only into the task-private venv,
using the repository's tooling pins where present; record the resolved versions.
Do not silently use a global installed HTTPX in place of the exported package.

Export baseline and candidate with `git -c core.autocrlf=false archive`. Verify
changed source and test members against raw Git blobs before extracting. Place
the exact candidate regression test file in both trees; disclose that test-only
overlay on the baseline, leaving its production files unchanged. From each source
root, run the same private interpreter in separate processes:

```powershell
& $taskPython -B -c "import httpx; print(httpx.__file__)"
& $taskPython -B -m pytest tests/models/test_url.py -q -p no:cacheprovider
```

Check the reported import path lies inside that arm's source root. Retain both
results, failures and exact test bytes; a baseline failure unrelated to the
candidate is not test discrimination. This file-scoped command does not start
HTTPX's local test servers, run its full suite or establish CI/coverage completion.

At the same baseline `b5addb64` and reviewed bracketed-netloc change, Windows
CPython 3.12.13 with pytest 8.4.1, Trio 0.31.0, AnyIO 4.15.1 and httpcore 1.0.9
independently reproduced **14 IPv6 failures / 108 passes** on the baseline and
**122 passes** on the candidate. The same regression file was used for both
arms, both imports resolved into their full source exports, and no WSL or GPU
was used. This confirms that URL-test result across the two observed environments;
it is not an additional PR, a full-suite pass or a throughput measurement.

### Wider Windows suite: retain the baseline failures

The URL-only environment was insufficient for the full offline suite: collection
first failed because `chardet` was missing. Add the required test dependency and
declared HTTPX extras to the same task-private environment, retaining the initial
failure and recording resolved versions rather than suppressing collection.
Run full-suite arms serially on the host: upstream test fixtures use fixed ports,
so separate Python processes are not independent server environments. An initial
concurrent baseline attempt was interrupted and is not a completed test result.

A subsequent serial check of the same two exports and regression-file overlay
collected 1,445 non-network cases per arm. Baseline: 1,426 passed, 18 failed,
1 skipped; candidate: 1,440 passed, 4 failed, 1 skipped. The 14 removed failures
were the IPv6 regressions. Both arms retained `test_download` (Click 8.5.0's
`isolated_filesystem` deprecation under warnings-as-errors), the text-mode
temporary-file assertion, and both write-timeout cases. No candidate-only failure
was observed. Five network-marked tests were deselected. This is paired evidence
for the scoped change, not full CI, coverage completion, or proof that the shared
platform/dependency failures are harmless. Both suite invocations took about
29 seconds combined; failed attempts and dependency setup are additional costs.

## HTTPcore: plugins and behavior-matched test context

At immutable HTTPcore `10a658221deb38a4c5b16db55ab554b0bf731707`, a first
collection attempt failed because the environment lacked the declared
`pytest-trio==0.8.0` plugin. Keep `--strict-markers` and warnings-as-errors;
install the declared plugin rather than suppressing the marker check. See the
[upstream requirements](https://github.com/encode/httpcore/blob/10a658221deb38a4c5b16db55ab554b0bf731707/requirements.txt)
and [pytest configuration](https://github.com/encode/httpcore/blob/10a658221deb38a4c5b16db55ab554b0bf731707/pyproject.toml).

A fresh task-private Linux environment with Python 3.12.13, pytest 8.2.2,
pytest-trio 0.8.0, Trio 0.31.0, AnyIO 4.15.1, h11 0.16.0 and h2 4.4.1 passed
54 model/sync-HTTP11/async-HTTP11 tests. A separate invocation passed 30 existing
sync/async HTTP2 tests. The imported package came from the full exact source
export; all 92 exported files matched raw Git-object bytes before and after.
No package/system mutation outside the task environment, native build or GPU
was used. The first remote setup plus 54-test run took 13.79 seconds; the later
HTTP2 invocation took 1.75 seconds. These are bounded upstream mock-test checks,
not full CI, external-network coverage or automated untrusted-code isolation.

An isolated four-window Scout admission trial froze source/test bytes, clipping,
rules and a four-call cap before answers. It used 14,719 reported model tokens:
three `NO_LEAD` answers and one `REVIEW`. Owner review rejected the reset-leak
hypothesis after reading the outer shielded cleanup paths and the existing
[RST_STREAM/reuse test](https://github.com/encode/httpcore/blob/10a658221deb38a4c5b16db55ab554b0bf731707/tests/_async/test_http2.py#L130-L173).
That test was outside the supplied first-100-line test window. The three
`NO_LEAD` answers are not independently established negatives.

The resulting next action is to retrieve caller cleanup and behavior-matched
tests before generating another reproduction. This one old-commit repository
trial produced no PR; it is not a fresh-change yield, recall, cost-saving or
budget-matched multi-router result. Strong-model/owner-review costs were not
independently metered. Keep raw inputs, packages and logs in local runs; do not
expand continuous admission merely because a native baseline passed.

An exposed development replay found that the existing follow-up selector already
retrieved the complete reset regression (lines 106–185) and the requested owning
caller (55–174). One capped Kimi follow-up then returned `NO_LEAD`, using 5,911
reported tokens in 6.56 seconds. No retrieval-code change was needed for this
case. This is a falsification check on an already reviewed example, not a held-out
utility comparison; it does not establish that every initial `NO_LEAD` is correct.

## Keep the requested implementation in the delivered context

Follow-up `next_check` hints are evaluated separately from quoted background.
One unambiguous Python function is selected from the already observed pinned file,
starting at its declaration; unrelated qualified names cannot displace it.
Missing, ambiguous and non-Python matches retain the existing selector. Explicit
line ranges and literal anchors still take precedence. No extra source call or
larger packet budget is introduced.

During packet fitting, complete requested functions are retained before unrelated
raw windows, after peripheral search snippets. If the budget eventually forces
their truncation, `requested_definition_complete` becomes false and the delivered
line range is updated. Check the actual queued packet, not just the retrieval
output. Completeness describes a syntax span, not imported behavior, decorator
semantics, caller reachability, test coverage or candidate quality.

## Verify realized backends, not parameter labels

A native check of installed AnyIO 4.15.1 with Python 3.12.13, pytest 9.1.1,
Hypothesis 6.168.3 and Trio 0.34.0 reproduced
[AnyIO #1353](https://github.com/agronholm/anyio/issues/1353).
For a Hypothesis test parametrized as asyncio then Trio, the Trio-labelled case
actually used asyncio. Reversing the order in a fresh process made the
asyncio-labelled case actually use Trio. Each order had one pass and one failure.
Non-Hypothesis controls passed both backend cases in both fresh-process orders,
separating the wrapper problem from missing Trio support.

The first reproduction used a function-scoped fixture and stopped at a Hypothesis
health check before executing; preserve that failure. The revised test uses a
session-scoped immutable backend-name fixture, without suppressing health checks.
This release-level check does not qualify current main or the existing
[fix PR #1354](https://github.com/agronholm/anyio/pull/1354), and no competing PR
was opened. Before claiming backend coverage, add a targeted realized-backend
assertion where wrapper caching can change execution; labels alone are insufficient.

## Keep issue endings visible before planning a competing fix

Long issue bodies now keep literal head/tail excerpts in the existing 5,000-character
budget, rather than only the beginning. The same rule applies to issue-page intake,
full-issue follow-ups and later packet-budget trimming. A visible omission marker
and `truncated` flag preserve the partial-evidence boundary. No extra GET or model
call is added, and the global input-byte cap is unchanged.

This exposes closing paragraphs that may contain an existing local correction,
linked work or an author's offer to submit. It does not classify ownership, grant
permission, guarantee every relevant sentence survives, or replace reading the
complete current issue/comments before publication. Already clipped historical
packets cannot recover missing text without fresh evidence. A replay on a case
used to develop this change is an exposed canary, not a holdout benefit estimate.

## Remote sandbox feasibility before model execution

Before moving automated delivery to a shared Linux worker, check that the
isolation backend really works, not only that Python or a container command is
installed. A reachable worker with ample storage is not automatically a verifier.
Do not install a privileged daemon, mount a host socket into generated tests or
fall back to running untrusted code directly as the SSH user.

If evaluating a namespace-based alternative, probe the actual namespaces the
backend requires. An observed worker allowed `unshare --user --map-root-user
--net true` but rejected the mount namespace with `cannot change root filesystem
propagation: Permission denied`. The first probe alone would falsely advertise
usable sandbox capacity. Keep such a worker ineligible for automatic execution
until a separately reviewed isolation policy and real canaries pass. Resource
limits, hidden host files/devices, network isolation, child cleanup and output
bounds remain necessary; namespace availability by itself proves none of them.

Distinguish namespace creation from the setup operation that failed. A later
CPU-only B300-worker probe passed user+network, user+PID and
`unshare --user --map-root-user --mount --propagation unchanged true`.
The default mount probe still failed at root-filesystem propagation. Thus the
observed error does **not** prove that creating a mount namespace is forbidden;
the successful `true` also does not prove mounts, a hidden host filesystem or a
usable sandbox. A separate shared SM120 worker had a zero user-namespace quota
and rejected even the user-namespace probe. These are worker-local observations,
not architecture limitations. Do not change shared quotas or mount propagation
to make a test pass.


Neither worker had Docker, Podman or bubblewrap. One owner-stopped attempt to fetch a
distribution bubblewrap package for a task-private **trusted-`true` capacity
probe** stalled before package extraction and was terminated; no sandbox command
or project code ran. It did not establish a usable bubblewrap version or policy.
Keep automated generated-code execution disabled. Already owner-reviewed native
tests remain a distinct route; they are not evidence of untrusted-code isolation.
Put an external process-wall bound around tool acquisition too: a socket timeout
does not reliably bound DNS resolution or the complete setup process.

A subsequent trusted B300 canary went beyond namespace creation: a bind mount of
`/usr` into a fresh task-owned directory, inside the new user/mount namespace with
unchanged propagation, failed (util-linux exit 32, `bind /usr failed`). The message
did not report a syscall errno. The parent mount namespace stayed unchanged, no
probe mount appeared there, and the empty task directory was removed. Do not
reinterpret the earlier successful `true` as proof of working filesystem mounts.
Cached apt package metadata also did not guarantee acquisition: its exact legacy
archive filename returned 404; no package was extracted or executed. Two other
authorized workers had no Docker, Podman or bubblewrap executable either. Tool
absence is not an architecture limitation, and these observations do not justify
weakening isolation or installing a privileged daemon on shared machines.

## Small owner-reviewed C++ translation units

Do not substitute a Python arithmetic model for a native compiler pass or
protocol implementation. First check whether the exact reviewed translation
unit and its compatible headers/libraries can run in a task-private build.
This can answer a narrow native question without rebuilding the whole project.
It is an owner-reviewed route, not an automatic executor for generated code.

For a plain POSIX helper, compile the unchanged raw Git-blob source and header
with a small caller using the actual public entry. Record hashes before compiling,
a bounded build/test command, stderr and the observed return values. Avoid
changing shared packages or launching local WSL. Use an authorized Linux worker
for Linux-only system calls. Windows text-mode writes can translate LF into CRLF;
verify staged bytes against the original source digest before any execution.

For a registered compiler pass, a probe may need mechanical factory/registry
renaming so both baseline and candidate can be loaded without collisions.
Document exactly those changes, leave the actual pass logic intact, and run
each arm in a fresh process against the same dependency closure and test bytes.
Packaged headers alone do not establish ABI compatibility: check header versions,
runtime libraries, compile definitions and symbol resolution. Keep environment
failures separate from candidate failures; a private compatible header overlay is
not a full current-main dependency qualification.

[TileLang #3390](https://github.com/tile-ai/tilelang/pull/3390) used actual C++
pass translation units against packaged TileLang 0.1.15 dependencies. The same
new CPU-native IR regressions produced 9 failures/8 passes on baseline and
17 passes on candidate; 13 existing pure-IR cases passed on both. Fifteen
CUDA-marked pytest cases stayed skipped. This establishes scoped transformed-IR
discrimination, not a full current-main compiler build, GPU execution or speedup.

A separate owner audit of TransformerEngine
[ipcsocket.cc](https://github.com/NVIDIA/TransformerEngine/blob/f38a1fce7f2396d6b39aa368a4497e7f82baa4f2/transformer_engine/common/comm_gemm_overlap/userbuffers/ipcsocket.cc)
and its
[real callers](https://github.com/NVIDIA/TransformerEngine/blob/f38a1fce7f2396d6b39aa368a4497e7f82baa4f2/transformer_engine/common/comm_gemm_overlap/userbuffers/userbuffers-host.cpp)
rejected a proposed successful-partial-stream-write defect: the socket is
SOCK_DGRAM and ipcSocketSendFd supplies one byte plus SCM_RIGHTS. An unchanged
native helper check completed 1,024 descriptor round trips across blocking/
nonblocking modes and four rank boundaries. That check is not a proof of all IPC
behavior, queue-pressure/cancellation safety or the full TransformerEngine stack.
Reopen only with a distinct supported path or protocol failure; do not create a
competing partial-write patch from missing initial context.
