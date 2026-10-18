# Native CPU validation reference

## Keep test-process temporary paths short and private

Python multiprocessing's forkserver can create an AF_UNIX listener beneath the
test process's temporary directory. A long source-identity/run path can exceed
the socket path limit before the package operation under test runs. Preserve
that setup failure; use a fresh short task-owned temporary directory for a new
matched run rather than removing the forkserver test or changing shared TMPDIR.
Check source/test identities and repeat the same declared selection on both
arms. A path repair is not a library fix or evidence of all-platform support.
See the actual listener construction in
[CPython's forkserver](https://github.com/python/cpython/blob/v3.12.13/Lib/multiprocessing/forkserver.py).

Similarly, disabling pytest plugin autoload does not make installed fixture
providers available. Explicitly load the reviewed private plugin (for example,
`-p pytest_mock` when upstream uses `mocker`) and record that environment change.
Retain missing-fixture errors instead of scoring the unexecuted test as a pass.

When an exported package sits beneath a larger repository, pytest may inherit
the ancestor's root and emit a longer JUnit `classname` than expected. Declare
`--rootdir=<reviewed-export>` and qualified expected test names before execution.
Separately check `configfile`: `--rootdir` does not select or disable a configuration
file. When appropriate, explicitly pass `-c <target's-reviewed-config>`; preserve
its upstream settings rather than inventing an empty configuration to hide failures.
For example, a raw Tomlkit export with no pytest options in its `pyproject.toml`
can otherwise select a containing workspace's `pytest.ini`. An explicit target
configuration and root produced 108 passing items/probe tests on native Windows
in one development check; this is not its full corpus, dependency recipe or CI.
Pytest documents these distinct controls in its
[rootdir/configfile algorithm](https://docs.pytest.org/en/stable/reference/customize.html#finding-the-rootdir).
Neither control establishes the actual imported package path; verify that separately.
If only the report prefix differs, preserve the original inconclusive capture
and reconcile the same hashed XML against the exact predefined test; do not
rerun assertions merely to repair accounting or accept a different test.

## SQLite read-only queries still need temporary capacity

When a read-only Scout query reports `database or disk is full`, inspect the
temporary filesystem separately from the database filesystem. `GROUP BY`,
`ORDER BY` and materialized subqueries can require temporary storage. On the
usual Unix VFS, `/var/tmp` precedes `/tmp` when no temporary-directory override
is set; free space beside the database therefore does not rule out this failure.
Check the actual query plan, VFS/build and process environment rather than
assuming corruption or an exhausted database size limit. See SQLite's
[temporary-file mechanisms and locations](https://www.sqlite.org/tempfiles.html).

For a bounded counterfactual, run the same read-only query in a fresh child with
`SQLITE_TMPDIR` pointing to a short, permission-restricted task directory on a
filesystem with verified capacity. Set it before the child initializes SQLite;
do not change the process-global temporary-directory pragma in a threaded
controller. SQLite explicitly discourages that
[global interface](https://www.sqlite.org/c3ref/temp_directory.html).
Windows uses a different OS-specific selection mechanism; do not assume the
Unix environment variable applies there. Keep the original failure, and report
the child-only environment change. A successful retry is scoped recovery
evidence, not a database-health or throughput certificate. Do not clear shared
temporary directories, disable journaling, or force all temporary work into RAM.

## Collection skips are not executed tests

Pytest can report a whole skipped module as a JUnit `testcase` with an empty
`classname`, a module name, and `skipped message="collection skipped"`.
The native result reader retains that exact form as an `@collection::...` skip
event; it cannot satisfy a required regression/control or count as executed.
One module skip says nothing about how many tests inside it were not collected.
Ordinary passing/failing cases still require qualified identities; duplicate,
missing or contradictory outcomes remain inconclusive. Preserve the original
XML and old parser result when deriving a new analysis with a corrected reader;
do not edit skipped records or rerun a costly suite only to change its format.

## Standard-library iterator tests and concurrency capacity

At [More Itertools 4aeb433](https://github.com/more-itertools/more-itertools/tree/4aeb4338ae1407d8da9723e86da99efeb446f719),
the unchanged package and its unittest/doctest suite require no installed test
dependencies. Native Windows CPython 3.12.13 completed all 929 cases with source
hashes unchanged using `python -B -m unittest -q` from the commit-exact checkout.
This establishes that baseline only, not the full supported Python/OS matrix,
packaging, static checks or a discovered defect.

The default offline CPU sandbox instead completed 929 cases with one failure and
three errors involving thread creation. Its 64-PID limit cannot accommodate the
[100-thread concurrent-tee test](https://github.com/more-itertools/more-itertools/blob/4aeb4338ae1407d8da9723e86da99efeb446f719/tests/test_more.py#L7098).
A fresh one-thread canary passed; later failures in the full suite may be cascades,
not four independent library bugs. Retain the failed run, do not drop cases or
relax sandbox limits to advertise a green full-suite capability. Use an authorized
native environment with appropriate capacity for independently reviewed tests.

Also read the repository's [Development rules](https://github.com/more-itertools/more-itertools/blob/4aeb4338ae1407d8da9723e86da99efeb446f719/README.rst#development):
assistant-found reports require affected production code, and an issue precedes
a PR. A synthetic red/green test is not a substitute for that contribution route.

Add a repository when a supported baseline can actually run, not just because
source is available. A baseline may reveal a known upstream failure; retain it
and compare the same affected tests before/after a candidate. Do not suppress
warnings or weaken assertions to manufacture a green environment.

## Humanize core baseline, with translation gaps retained

The Python utility is [python-humanize/humanize](https://github.com/python-humanize/humanize),
not the Humanize agent workflow. At
[`785e5dcc`](https://github.com/python-humanize/humanize/tree/785e5dcc0d0308ad0dff3f6cc0faa7085ad0375b),
an unchanged, normally built pure-Python wheel ran the upstream tests on native
Windows CPython 3.14.3 / pytest 9.1.1: 744 passed, 112 skipped, zero failures.
The command used `-p pytest_benchmark.plugin --benchmark-disable`; it establishes
no benchmark speed. Two skips require GNU gettext tools; 110 require generated
translation catalogs. Do not call this complete CI or localization qualification.
The project CI generates catalogs and runs Tox/coverage on multiple runtimes.

Production Python files in the wheel were checked against raw Git blobs; its
version file was generated by the normal Hatch VCS build, not fabricated.
An initial Windows checkout had CRLF bytes and was not used for qualification.
A separate LF checkout preserved the original observation. Dependency preparation
also initially failed while moving a pip temporary target from C: to D:; one
fresh, hash-pinned retry with task-private TEMP/TMP on D: completed. This is one
observed recovery, not proof that all such errors have a common cause. Keep the
failed setup and the later native test cost separate. Core number/time/list/size
leads can now receive independent Windows tests; localization leads still need
the missing tools/catalogs and every new candidate needs its own paired test.

This operational admission does not replace the earlier unavailable historical
Humanize research draw or enter its denominator as a success.

## Check the contribution destination before opening a new scope

Native testability does not imply a viable upstream contribution channel. Reuse
`python scripts/scout_contribution_policy.py --repo OWNER/REPO` (or equivalent
current public metadata and policy evidence) before paying for a new discovery
scope. Read its timestamped `repository_settings`, including `archived` and
`disabled`, rather than treating an unchanged Git head as evidence of activity.
Missing metadata is unknown, not permission. The command observes public facts;
it does not establish personal eligibility, CLA completion or publication authority.

An archived dependency can still justify an explicitly bounded reproduction or
research comparison. Do not leave it in continuous PR discovery without a viable
maintainer/fork channel. If archive status is found late, retain the original
sample, calls and setup costs; remove only future discovery scope, not historical
evidence, and do not replace that case to improve a reported success rate.

Duplicate checks also need the linked history, not only current open-PR search.
[go-retryablehttp #179](https://github.com/hashicorp/go-retryablehttp/issues/179)
has a same-scope [fix #299](https://github.com/hashicorp/go-retryablehttp/pull/299)
that a maintainer closed unmerged; partial issue/index views omitted that link.
The closure had no visible explanation at owner review. Do not infer an accepted
design or an invitation to submit the same patch. Clarify the contribution route
or establish a distinct uncovered defect before paying for a replacement. A
closed prior PR is not a universal ban; its intent may remain unknown. The
original author's test claims are not independent native validation.

## Owner-only intake across languages

Owner intake exposes `source_selection` separately from its visibility `commit`:
`RESOLVED_CITATION` identifies one supplied immutable implementation citation;
`LEGACY_FIRST_SOURCE` retains older records without evidence; `UNRESOLVED`
means an owner must choose the target before testing. A packet comparing two
revisions of the same file is ambiguous too, not just a multi-file claim. The
fallback commit keeps the line visible and classifies its language; it is not
permission to execute that version or silently rewrite the model's citations.
The source loader still refuses unresolved evidence before fetching anything.
Preserve this marker and the bounded owner advice in summaries/frontends rather
than showing the commit alone. Resolution identifies provenance, not correctness.

Long issue text keeps its head and tail and, when it fits, one literal middle
Markdown section headed as a workaround, patch, proposed fix or suggested fix.
This uses the same character budget and no extra read; simple fenced-code
headings are ignored. A retained fragment may still be incomplete. Inspect it
before asserting that an author supplied no patch or opening competing work.
These headings are untrusted text, not proof of ownership, correctness, tests
or a reason to suppress a distinct contribution automatically.

### Native behavior is not the entire acceptance contract

A real loopback HTTP test can show that **that server** replaces bytes on PUT;
it does not establish the behavior of every remote server. In
[Fsspec #2294](https://github.com/fsspec/filesystem_spec/pull/2294#issuecomment-6193718335),
maintainer review accepted rejecting unsupported `pipe_file` modes but required
the explanation to be defensive: PUT semantics remain server-dependent. The
[merged implementation](https://github.com/fsspec/filesystem_spec/blob/16fad6169ad2c61e9e7afc6791ab9f560ed21ee0/fsspec/implementations/http.py)
keeps that boundary. Preserve the native before/after evidence, but independently
justify the intended contract; do not turn one test server's behavior into a
universal protocol claim. A merged contribution is an observed delivery outcome,
not by itself a controlled comparison of Scout strategies or knowledge utility.

### A no-op setter does not make a probe state-free

Check the state of the parser/iterator/owner around an observation, not only its
value callback. In [Cobra #2529 at e94da41](https://github.com/spf13/cobra/blob/e94da41f7c050e2c35fd505cbabfa1294206dcbf/completions.go),
`ParseAll` with a no-op setter fixes duplicated flag values but its synthetic
`--` still changes the live `ArgsLenAtDash()` metadata. An
[independent native check](https://github.com/spf13/cobra/pull/2529#issuecomment-6208428527)
reproduced that leftover state in both completion commands. Isolate a probe's
mutable metadata as well as its callbacks and argument backing storage; check
the actual consumer-visible state. This is a scoped counterexample, not proof
that arbitrary shallow copies are safe. Recheck current linked PRs before
implementing: an empty cached/partial timeline is not proof of no existing fix.
Contribute uncovered evidence to that PR instead of opening a duplicate.

### Missing source is not a native-test failure

Before repairing an environment, inspect the actual excerpt delivered to the
reviewer. A long requested definition may have been clipped by the packet budget.
The producer recognizes both `after line 360` and `360行之后`. A requested interval
can also bridge a short gap between two same-pin windows of one observed file:
one head and one tail anchor must agree on file identity and total length, and
the gap must fit the existing 120-line window. It prefers the trailing fragment
to avoid re-reading the declaration prefix. Duplicate same-direction anchors,
competing files, changed revisions and arbitrary unseen intervals still abstain.
This uses the existing read/call budgets; it neither executes source nor proves
a complete function, correct diagnosis or improved PR yield. Packet trimming
remains a separate check: route selection alone does not prove final visibility.

For an existing Scout inbox, `kimi_scout_delivery_source.select_leads(root,
source_ids=[known_job_id], scan_limit=16, owner_review=True)` also returns
non-Python immutable source leads. Use `owner_language="go"` (also `python`,
`rust`, `typescript`, `javascript`, `cpp`) for a language-specific owner inbox,
or `native_cpu=True` for Go/Rust. These modes are mutually exclusive with
`owner_review=True`. C++ includes host headers, not CUDA/HIP translation units;
selection is not evidence that a file can compile on CPU. `exclude_repos` can
omit repositories before the bounded scan. Immutable URL, target-language and
already-staged checks run before `scan_limit`, so a companion Python file or
invalid raw URL cannot consume the scan budget for a matching-language target.

The automatic route remains Python-only, but now uses the unique immutable
same-repository code URL cited in `analysis.evidence`, not the first Python
companion. The URL must have been supplied in the packet. Repeated citations
of that URL are one target; issue-only, absent, malformed, unsupplied or
multi-module code evidence needs independent source selection. Those leads stay
visible using the first code source for inbox language classification only;
`load_source` refuses to fetch this fallback. The worker records `INCONCLUSIVE`
with `source_selection=UNRESOLVED`, without fetching, model calls or execution.
This is not an environment failure or a refuted bug. Legacy records with no
evidence field use the first immutable code source; a native primary is not
recast as its Python companion. Citation binding proves provenance only, not
the hypothesis, caller reachability or runnable package context.

Opt-in results may also carry `owner_deferrals`: at most two same-file historical
decisions, public evidence links and reopening conditions from the existing
bounded memory reader. Advice is fetched only for the final selected leads,
not the scanned history. Read it before repeating source acquisition or tests,
but check its applicability: a same-file match is not a duplicate verdict.
Advice does not suppress candidates, rewrite their analysis or alter automatic
selection. Missing or invalid optional notes do not block independent review.

Every opt-in result carries `verification_route=OWNER_REVIEW_ONLY` and must be
admitted with `kimi_scout_delivery.stage(root / "delivery", leads,
owner_review=True)`. Automatic admission rejects that route; an owner row cannot
be claimed by model/test workers. Selection and admission perform no source
execution, model call or environment setup.

This is a read/review handoff, not a newly supported language verifier. Inspect
current contribution rules, caller reachability and existing PR ownership before
building. Keep an unsupported environment or source-refuted premise distinct from
native test failure. Use existing owner disposition/publication records after the
actual outcome; do not rewrite the original Scout answer into a verified result.

Pending-lead selection alone cannot measure misses: it omits terminal negative
decisions. For a negative audit, predeclare the sample and native budget, retain
unexecutable cases, and freeze the native conclusion before reading the final
model answer. Keep earlier proposer claims untrusted. One such owner audit found
[Fsspec #2306](https://github.com/fsspec/filesystem_spec/pull/2306): a related merged
seek restriction was incorrectly taken as explicit approval of a `None` return.
The real synchronous BufferedReader failure is distinct from the unproved async
zip/tar impact. This is one negative-stratum counterexample, not population recall,
an estimate of missed PRs, or a budget-matched selector benefit.

## Scoped raw-Git source transport

`qualification_source_bundle.py --build --path python/sglang --path pyproject.toml`
selects literal repository-relative files or directories. Repeat `--path` as
needed; it is not a glob or a Git pathspec. `--prefix` only names the archive root.
Without `--path`, the existing full-tree behavior and manifest remain unchanged.

A scoped manifest explicitly records `source.included_paths`; it does not prove
that the selection contains every import, build input or transitive dependency.
Include the real package and relevant tests/configuration, then check actual
imports. Verification/extraction needs the updated reader: older strict readers
will reject the new optional field. Do not remove the field to make them accept a
partial bundle as a full-tree export.

Missing blobs inside the selection still fail, without lazy fetch or credential
prompts. Unrelated unmaterialized blobs outside the selection are not read. This
helps partial clones without inventing a source export adapter for each lead;
it is not an isolation or execution authorization mechanism.

## Check the deployed native runner, not another checkout

To stage a standalone native-test task, export the matching tool siblings once:

```text
python scripts/scout_native_run.py --export-runtime task/native-tools
```

This copies the runner, result reader, Windows backend and commit-exact source bundler into a
fresh directory and prints their byte hashes. Transfer that complete directory,
not just `scout_native_run.py` (which imports `scout_native_results.py`). Existing
destinations are refused; the parent task directory must exist. Export performs
no execution, install or network call;
it does not supply pytest/compilers or qualify a target package. Keep the reviewed
command, exact sources and expected test identities for the normal run entrance.

Check the Python API contract before upload or environment repair as well as
checking CLI help. The collector requires **1..64 exact expected test names**;
an empty list is not an opt-out. Its supported formats are actual test-report
formats, not a generic `unittest`/setup-log mode. The existing stdlib
`scout_native_results.summarize` can reject an invalid format/name list locally
before staging. An empty report with valid inputs remains inconclusive, not a
successful preflight test. Use names from the real test inventory and keep
setup/import subprocess exits and costs separate from registered test results.

For file reporters such as pytest JUnit, run the capture driver and reviewed
child under the same unprivileged task identity. The driver creates the fresh
output directory; a root-owned private directory can prevent a `nobody` child
from writing its XML even after assertions ran. Prefer correct ownership over
world-writable output or running the tests as root. Preserve the original
inconclusive capture, fix only the task's identity/paths, and use fresh reports
with unchanged assertions. Partial terminal failure/pass dots do not replace
the missing JUnit report or override the strict capture verdict.

Also check traversal through the task's extraction parent: the source bundler
creates its fresh target with mode `0700`. A root-owned parent can hide an
otherwise readable `go.mod` from a nonroot child, which may report "no modules
specified" rather than a package failure. Set appropriate ownership or traversal
on that task-owned parent only; keep source content and shared paths unchanged.

The CPU capture entrance permits at most 0.5 seconds of natural process-group
shutdown after the leader exits, within the original command deadline. This
handles short-lived runtime helpers without a helper-name whitelist. The whole
owned group must actually disappear; a persistent group still makes the capture
inconclusive and is terminated. Results record the observed wait and whether
post-exit cleanup was required. This is not a sandbox or proof about children
that escape the owned group. Historical inconclusive reports stay unchanged;
an XML pass count alone must not override their capture verdict.

Before planning a native run, inspect `python scripts/scout_native_run.py --help`
in the **actual execution checkout** and record the tool files used. A supported
format in a committed development worktree does not mean the live Scout directory
has that implementation. Compare overlapping local changes before applying an
update; do not replace a dirty working tree wholesale or restart model workers
just to deploy a result reader.

The owner capture runner accepts `node-tap` for Node's built-in test reporter:

```text
python scripts/scout_native_run.py --cwd PRIVATE_REVIEWED_CHECKOUT --output FRESH_OUTPUT --format node-tap --expect-test "suite::regression" --expect-test "suite::control" --source contract.mjs=REVIEWED_SHA256 -- /absolute/reviewed/node --test --test-reporter=tap contract.mjs
```

Run that capture command on an authorized POSIX worker, after reviewing the
command/source and setting up its private dependencies. On native Windows, add
`--native-windows` and supply an absolute Windows executable path. Windows
execution remains refused without that explicit opt-in; neither route starts WSL.
Arbitrary generated JavaScript remains untrusted.

The Windows CPU backend uses a private, unnamed
[Job Object](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects).
A trusted `-I -S` Python launcher joins it before starting the reviewed command;
ordinary CreateProcess descendants inherit the job, not its handle. Output is
bounded on disk, and timeouts include compilation and pipe closure. The runner
allows at most 0.5 seconds for natural background shutdown within the original
deadline. Remaining members are terminated only through the owned job, and their
wait handles plus zero active job membership must confirm cleanup. Unrelated
processes are never selected by name or inventory PID. Windows environment names
are checked case-insensitively so a lowercase CUDA override cannot reopen GPUs.

This is process-lifecycle accounting, **not a security sandbox**: service/WMI
launches, malicious code, network access, CPU/memory quotas and full dependency
identity are not isolated or proven. No Windows GPU hook is supported here.
The backend serializes its own handle-inheritance window; callers must not
concurrently launch unrelated inherit-all-handles children in the same Python
process. Prefer the standalone CLI when sharing a host with other controllers.
Job assignment, execution-policy denial, missing launcher status or uncertain
cleanup produce an inconclusive capture; there is no alternate-runtime fallback
or policy bypass. Keep a denied run as evidence rather than automatically trying
another interpreter or host. Native dependencies and target-repository policies
remain the task owner's responsibility.

Windows CPython 3.14 controls cover live descendants with open and redirected
output, natural shutdown, timeout/log-limit cleanup, controller termination,
unrelated-process preservation and rejection before failed job assignment.
The unchanged POSIX controls are separately replayed on Linux. A historical
Humanize repair also reproduces through the opt-in CLI with the same 39 upstream
tests on both normal wheel packages: parent 37 pass/2 fail, repair 39 pass.
These establish execution-tool behavior and one known red/green replay, not new
discoveries, supported-platform CI, performance or acquisition-policy efficacy.

Use emitted, TAP-escaped test names, joined with `::` for nested cases. Suites
are containers, not extra passing tests. Missing targets, TODO/skipped cases,
truncated reports, cancellation, timeouts and hook/runner failures do not prove
an assertion regression. `compare_regression` checks the declared matched
red/green cases and passing controls; it does not decide their relevance.
This reader covers the observed Node 24 built-in TAP format, not arbitrary TAP,
Vitest/Jest output, TypeScript compilation or an entire repository's CI.

For a no-install deployment check, set `SCOUT_TEST_NODE` to an already reviewed
compatible executable and run `test_scout_native_node` together with the existing
result/capture tests. Check the actual test names and platform skips: a Windows
pass cannot establish POSIX process-group cleanup. These are tool integration
controls, not newly discovered community bugs or PR-conversion measurements.

### Vitest JSON is a separate native format

The same capture runner supports `--format vitest-json`, checked against Vitest
4.1.4's [JSON reporter](https://github.com/vitest-dev/vitest/blob/v4.1.4/packages/vitest/src/node/reporters/json.ts).
Use exact emitted `fullName` strings (ancestor titles and test title joined with
spaces), not the Node TAP `::` convention. For an already reviewed private
checkout/environment:

```text
python scripts/scout_native_run.py --cwd PRIVATE_REVIEWED_CHECKOUT --output FRESH_OUTPUT --format vitest-json --expect-test "contract regression" --expect-test "contract control" --source contract.test.ts=REVIEWED_SHA256 -- /absolute/reviewed/node /absolute/reviewed/vitest.mjs run contract.test.ts --maxWorkers 1
```

The runner owns `--reporter=json` and a fresh `vitest.json` path; do not provide
reporter/output-file arguments. It retains stdout separately, hashes the report,
and applies the existing timeout, source-identity and child-group cleanup checks.
It does not audit imported dependencies or override a repository's test config.
Native Windows can use the same explicit `--native-windows` CPU opt-in. A saved
report alone still establishes only log accounting, not a captured execution.

Filtered tests and explicit skips share `skipped` in this reporter; they cannot
be distinguished from JSON alone. Every skipped/todo case stays in the reported
skip count, while `executed` includes only passed/failed cases. Named skipped,
missing or pending targets, hook/collection errors, contradictory counts, abnormal
exit and truncated reports are inconclusive. Suite totals include nested suites,
not just files. Require globally unique `fullName` values: ambiguous names across
files/projects are conservatively unsupported, not silently combined.

Matched regression accounting allows unselected unexecuted cases only when both
arms retain the same complete name inventory and unexecuted count; any extra
executed case still rejects a declared complete selection. Source/import/test
semantics must be reviewed independently. A saved report with 364 listed cases,
3 passed, 2 failed and 359 skipped establishes **5 executed cases**, not a passing
364-test suite. JSON consistency is neither reporter authenticity nor PR quality,
and this support does not claim compatibility with all Jest/Vitest versions.

Python source admission distinguishes a function's definition from its body.
Literal imports in defaults and decorators are required when the definition is
reached; nested definitions inherit the surrounding lazy/optional context.
Function annotation imports are deferred with `from __future__ import annotations`
under the Python 3.10 source model. Lambda bodies remain lazy, unlike their
defaults. This static check does not resolve aliases, execute source or prove a
test environment supports the affected caller; native import checks still matter.

## Commit-exact source before native validation

When testing a committed change, reuse the existing source bundle tool instead
of copying a Windows working tree into the test environment:

```text
python scripts/qualification_source_bundle.py --build --repo REVIEWED_REPO --commit FULL_COMMIT --repository-url PUBLIC_REPO_URL --archive task/candidate.tar.gz --manifest task/candidate.manifest.json
python scripts/qualification_source_bundle.py --verify --archive task/candidate.tar.gz --manifest task/candidate.manifest.json --extract-root task/candidate-export
```

`--extract-root` (and the Python API's `target`) must **not already exist**:
use a fresh child of the workspace, never the workspace itself. Extraction keeps
the archive prefix beneath that child; with `--prefix source` and a `src` layout,
the import path is `task/candidate-export/source/src`, not the staging parent.
Preflight the same CLI/API locally on the reviewed bundle before paying for
remote setup or model comparisons. Successful extraction proves only source
identity; it must not be scored as package import or test success.

Use fresh output paths for each arm. On an authorized Linux test host, transfer
the archive, manifest and reviewed verifier, then run the second command there;
the package root is `task/candidate-export/source`. Review the source before
execution, select that root before importing the project, and check the actual
import path. The manifest binds the commit/tree and every archived entry, not
the Python environment, runtime reachability or test result. A trusted expected
manifest/hash is still required; a self-consistent replacement is not proof of
upstream identity. No model-generated code is automatically executed by this recipe.

The builder reads raw Git blobs. `core.autocrlf`, dirty copies, ignored files and
output filenames cannot change committed contents. Unlike `git archive`, it
does not apply `export-ignore` or `export-subst`. It rejects submodule gitlinks
rather than pretending to include their source; Git LFS blobs remain pointers,
not downloaded assets. The current format accepts SHA-1 Git identities only.
Existing `git archive` recipes below remain usable when their intended exported
members have been checked against Git; disabling autocrlf alone is not that check.

Object reads set `GIT_NO_LAZY_FETCH=1` and disable credential prompts. With Git
support for that environment variable, missing objects in a partial/promisor
clone fail the build instead of silently downloading. Materialize missing objects
in a separate, explicitly budgeted fetch before retrying; this builder is not a
network sandbox or a Git LFS/submodule downloader. The regression fixture checks
that an unprotected read attempts a local promisor fetch and the protected build
does not. It is tested on the installed Git version, not every historical Git.
The CLI accepts commits, not uncommitted index trees; do not label a staged replay
as its unchanged HEAD commit. Low-level tree readers are available to reviewed
callers, but those callers must record the derived tree and any selected/omitted
paths separately rather than claiming a complete commit bundle.

Build now reads one blob at a time and stages an uncompressed tar on the archive's
output volume before streamed gzip compression. The verification CLI snapshots
only compressed input on that same volume, then verifies a seekable gzip view
without writing an inflated temporary tar. It reads through gzip EOF to validate
CRC/truncation even when tar parsing stops earlier. File hashes and extraction
use the private snapshot; replacing the original pathname cannot change it.
Leave space for the original archive, compressed snapshot and requested extracted
files; the build step still also needs its uncompressed temporary tar.
Backward seeks replay decompression, trading CPU work for fewer temporary disk
writes, not a demonstrated speedup. A writable archive directory is required;
there is no fallback to the system temporary drive or constant-memory claim.
Build memory still scales with the largest blob; verification retains
manifest/member metadata. The compatibility
`verify_bundle` helper still returns an in-memory tar; use the CLI or the
`verified_bundle` context manager for streamed verification. Windows extraction
of symlinks needs host permission; do not silently replace links or start local
WSL to bypass it.

Transport preserves POSIX filenames, but Windows extraction rejects names that
would be reinterpreted (backslashes, drive/stream colons, device names, invalid
characters or trailing dots/spaces); it does not rename them. On every platform,
extraction checks native destinations against its private staging directory,
rejects archive members beneath a symlink, and rechecks link resolution before
publishing the completed tree. A lexically internal link can still escape after
following another link, so POSIX string normalization alone is insufficient.
Unresolvable link loops are refused at extraction; archive verification remains
a separate byte/metadata check, not a sandbox or execution authorization.

Regression tests cover LF Git text with CRLF/dirty checkout bytes, in-memory
versus streamed tar/gzip identity, large/PAX entries, bounded verification reads,
snapshot replacement, gzip corruption, unsafe members and temporary-file/child
cleanup. These are transport checks, not project tests or evidence of a higher
PR conversion rate.

An owner-run offline Linux CPU sandbox comparison kept its original 1 MiB
per-file limit: old verification failed three cases with `File too large` while
two hash/CRC controls passed; the compressed-snapshot verifier passed all five.
This included verification (not full extraction) of a genuine 543,900-byte
Fsspec bundle and extraction of a synthetic four-member package whose individual
files fit the limit. The Fsspec bundle still has a 5.3 MB member and 9.3 MB total
source payload, so its complete extraction/package tests remain outside that
sandbox's file/persistence limits. No resource limit was raised; this is a tool
compatibility result, not Fsspec correctness or a community PR.

Historical community trials also reuse the raw-blob reader for their ZIP source
materialization, so checkout newlines and export attributes cannot silently alter
the bound revision. Their existing `BLOB_TEXT_NO_LIVE_LINKS` policy is unchanged:
symlink target blobs become regular text files, and executable modes are not
restored by that trial extractor. Submodule gitlinks are refused, not omitted.
This fixes newly materialized trials; it does not retroactively establish that
old source receipts contain commit-exact bytes, or qualify a project's runtime.

## Mooncake Store: private C++ dependencies before model-generated tests

The pinned [Store test targets](https://github.com/kvcache-ai/Mooncake/blob/3312b5182bdcd1f46c13d1e07a190dfc33da5524/mooncake-store/tests/CMakeLists.txt)
link the real Store and Transfer Engine. A copied initialization conditional does
not test those implementations. At this revision, `client_integration_test` can
build on an authorized Linux CPU worker without CUDA, Rust or a running external
master. Use the exact source and pybind11 gitlink, and the pinned YLT/GTest inputs;
record whether dependency archives were independently verified or merely reused.

For a task-private Debian/Ubuntu dependency prefix, inspect the upstream
[dependency list](https://github.com/kvcache-ai/Mooncake/blob/3312b5182bdcd1f46c13d1e07a190dfc33da5524/dependencies.sh)
before compiling. Verify target-compatible package bytes against their trusted
package metadata before extracting with `dpkg-deb -x`; this is not a system
installation. Three observed setup traps are worth checking early:

- `msgpack.hpp` is required by Store even when CMake configuration succeeds.
  On Ubuntu 22.04 it comes from `libmsgpack-dev`; package splitting differs on
  newer distributions. Do not substitute a fake serialization header.
- Private OpenSSL headers also need the prefix's multiarch include directory,
  such as `usr/include/x86_64-linux-gnu`, for `openssl/opensslconf.h`.
- An extracted glog CMake target can retain an absolute system `libunwind.so`
  path. Relocate only that verified private metadata reference to the extracted
  library, preserving its original bytes and the exact substitution. Do not
  create a system symlink or change Mooncake to evade the missing dependency.

One reviewed configuration used the following options (replace placeholders
with fresh private paths; these commands do not provision dependencies):

```sh
cmake -S "$task_source" -B "$task_build" -G Ninja \
  -DWITH_STORE=ON -DWITH_STORE_RUST=OFF -DWITH_TE=ON \
  -DBUILD_UNIT_TESTS=ON -DBUILD_EXAMPLES=OFF -DBUILD_BENCHMARK=OFF \
  -DUSE_CUDA=OFF -DUSE_TENT=OFF -DUSE_ETCD=OFF -DUSE_REDIS=OFF -DUSE_HTTP=OFF \
  -DCMAKE_BUILD_TYPE=Debug -DENABLE_DEBUG_SYMBOLS=OFF \
  -DCMAKE_CXX_FLAGS_DEBUG='-O0 -g0' -DCMAKE_C_FLAGS_DEBUG='-O0 -g0' \
  -DCMAKE_PREFIX_PATH="$task_prefix/usr" \
  -DCMAKE_BUILD_RPATH="$task_prefix/usr/lib/x86_64-linux-gnu" \
  -DJSONCPP_INCLUDE_DIR="$task_prefix/usr/include/jsoncpp" \
  -DJSONCPP_LIBRARY="$task_prefix/usr/lib/x86_64-linux-gnu/libjsoncpp.so" \
  -DFETCHCONTENT_SOURCE_DIR_YALANTINGLIBS="$task_ylt" \
  -DFETCHCONTENT_SOURCE_DIR_GOOGLETEST="$task_gtest" \
  -DFETCHCONTENT_FULLY_DISCONNECTED=ON
CPLUS_INCLUDE_PATH="$task_prefix/usr/include/x86_64-linux-gnu" \
C_INCLUDE_PATH="$task_prefix/usr/include/x86_64-linux-gnu" \
cmake --build "$task_build" --target client_integration_test --parallel 2
```

The observed GCC 11.4/CMake 3.22.1 build completed after retained failed setup
attempts. That establishes this target's buildability, not a clean-build timing,
general toolchain support or full CI. Inspect resolved native libraries before
testing; private headers alone do not prove the loader uses matching libraries.

Review listener behavior before running integration tests on a shared host.
The pinned embedded master binds loopback, but Transfer Engine handshake/data
listeners can bind wildcard addresses. A private directory is not network
isolation. Use an available isolated network environment; if a reviewed common
test adaptation redirects binds to loopback instead, disclose it for both arms
and do not call the result an unadapted suite or a performance measurement.
Use a real reachable master and passing TCP control when testing transport-init
failure: failure to connect to a missing master can make both arms return null
without ever reaching the suspected installation path. Bound build/test process
groups, preserve terminal failures, and terminate only owned children on timeout.

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

### Installer API tests are not a configured CLI upgrade

When a repair changes installation or dependency resolution, importing the
installed module through an internal installer test does not prove the shipped
CLI or replacement of an existing configured installation. If that boundary
matters, pin the public stable release's version, tarball and integrity, let its
actual CLI create a small installation in private state, and use the candidate's
documented CLI to replace and load it. Keep the source-built candidate distinct
from the released package. Read the structured runtime verdict and resulting
install record; command exit alone is not runtime-loading proof. An inspector
can exit zero while reporting `status: error`; even an `imported: true` flag or
an empty missing-dependency list need not mean module initialization succeeded.
Do not fabricate old database rows to stand in for a stable-version installation.

Review the wrapper's build/publication contract before reserving test ports.
OpenClaw's [runtime publication owner](https://github.com/openclaw/openclaw/blob/b46ec6167975f57fa33cc298e78c8338ae59746e/src/cli/update-cli/update-command-service-publication.ts)
requires the affected Gateway's port to be free before changing runtime artifacts.
A task-owned bound, non-listening socket can prevent connections to an operator
Gateway during an offline CLI test, but is **not a free port** for this build
check. Build through the official entry point with a genuinely free private port
first, then reserve it for the installation commands if appropriate. Preserve
the refusal; do not disable the guard, fake build stamps, or stop an operator
service. This is a fixture-ordering precondition, not proof of a product defect,
successful upgrade, full package qualification or better Scout conversion.

### Tap CLI setup is separate from a direct test-module run

With Tap 21.7.4, directly running a TypeScript test with Node can reach real
assertions without exercising the CLI's plugin setup, discovery or coverage.
Keep that narrower evidence; a Windows symlink-permission failure is not a
reason to enable Developer Mode, elevate, patch `fs`, or start local WSL.
An authorized native Linux worker can provide the missing CLI observation.

For an offline worker, prepare dependencies using the target OS/CPU and retain
the resolved versions/integrities. An npm-distributed Node runtime has registry
provenance; verifying its SRI does **not** verify the official vendor archive or
release signature. Do not describe those distributions interchangeably.
Clock 3.3.10 accepts core 4.5.8 in this Tap environment; newer Clock releases
can require a different core. Inspect peer requirements rather than force an
incompatible install.

In `@tapjs/run` 4.5.8, plugin version selection calls `pacote.packument(name)`
without forwarding the offline configuration. An installed plugin and an
`npm_config_offline` setting alone did not prevent a registry request. With an
already reviewed fixed plugin set, the supplied
`@tapjs/test/generate-tap-test-class` executable can build that same set without
version discovery. Load `@tapjs/core` before reading `defaultPlugins` from
`@tapjs/test`, retain the configured nondefault plugins, and then run the actual
Tap CLI. The generator writes into its private dependency/plugin tree; do not
reuse it as a read-only command or modify a shared installation. This is an
explicit setup alternative, not a claim that `npm test` or coverage ran.

A Linux LRU replay reached all 29 discovered test files with this route:
the changed source passed; unchanged production with the same added tests
failed only the two snapshot-reuse assertions. The suite's randomized cache
stress test produced different assertion totals, so those totals are not a
matched case inventory. An unchanged five-case native Node witness supplied
the separate strict old/new comparison. A subsequent actual `npm test` capture
also ran the project's pretest/build and generated coverage. The supplied
`tap report json-summary text-summary` read those saved V8 files without a test
rerun and reported 100% in all four standard coverage metrics for the four
mapped source files. Keep the raw-file identities: reporter silence can mean
the default hides complete coverage, not that coverage was absent. These are
local observations, not upstream CI or discovery-policy effectiveness.

Also distinguish virtual address reservation from resident memory. A 4 GiB
`RLIMIT_AS` prevented the CLI's WASM report dependency from initializing,
although the host had ample available memory. A separately captured run with
16 GiB virtual address space, a 1 GiB Node old-heap limit and two test workers
reached the tests. These are scoped settings, not universal safe capacities
or a process-tree physical-memory cap. Retain the failed run and check actual
worker headroom before choosing limits.

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

Build the [example Dockerfile](../../examples/scout-native-httpx/Dockerfile) with a
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

Generated-test screens record unittest failures, errors, skips, expected failures
and unexpected successes, not just `testsRun` (which also counts skipped tests).
Missing, contradictory or duplicate outcome markers and skipped/expected outcomes
remain inconclusive. Legacy count-only records are preserved, not silently
upgraded. An assertion-fail/pass pair can reach owner review; a baseline exception
can also represent a real defect, but its handoff explicitly requires locating the
traceback in the subject rather than test setup. Child output is still untrusted:
these counters neither prove relevance nor authenticate model-generated tests.

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

Resolve runtime, test plugins and optional backend extras **together** in a
fresh task environment. Independently pinned components can collect and pass
ordinary tests while violating another component's declared requirements.
Record the installed dependency metadata and resolved versions; do not treat
import success or a pytest backend label as a compatibility check. For a
cancellation-sensitive repair, exercise actual task cancellation and cleanup,
not only normal response completion. Keep an incompatible test-driver failure
separate from an assertion against supported production behavior.

If Windows AppControl or another platform policy refuses a native extension,
retain the refusal and stop that affected route. Do not switch its binary path,
library implementation or execution host to evade the denial. Unrelated checks
that do not need the denied component may continue, with the omitted backend
explicitly unqualified. A later compatible or authorized environment is a new
scope of evidence, not a reason to rewrite the historical result as passing.

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

## Audit service-free test entrypoints before preparing dependencies

A runner's `--no-services` flag may only skip starting its sidecars. It does
not prove that application initialization, pytest hooks or autouse fixtures avoid
connecting to services. Inspect those paths before an expensive dependency setup,
including for a targeted test that only exercises a pure helper.

For example, at FutureAGI commit `ea12cc3f4456fc568d9694a215c661b15be1cea2`,
[`futureagi/bin/test`](https://github.com/future-agi/future-agi/blob/ea12cc3f4456fc568d9694a215c661b15be1cea2/futureagi/bin/test)
skips Compose and migrations with `--no-services`, but
[`futureagi/conftest.py`](https://github.com/future-agi/future-agi/blob/ea12cc3f4456fc568d9694a215c661b15be1cea2/futureagi/conftest.py)
still contains a ClickHouse schema-apply hook and session fixtures that attempt
DDL. Its explicit schema-apply skip does not disable those other fixtures.
Do not point that run at a shared service, invent import stubs or silently omit
the conftest to claim backend qualification. An owner-reviewed targeted run in a
working isolated network namespace is a distinct possible component-test route;
it is neither proof of a filesystem sandbox for generated code nor a replacement
for the project's required full-stack checks.

Record failures at the stage actually reached: a locked dependency download
timeout before application import means `environment blocked / tests not run`,
not a failed candidate or a passing backend. Retain the exact source and useful
cache; retry only when transport/cache/environment evidence changes. This also
keeps a new Scout pass from repeatedly rediscovering the same body-only result.

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

## Standard-library-only Go comparison baseline

`google/go-cmp` is a bounded CPU-only discovery target. At
[`b133f1f1932e48f466f597a3346ce6f5a49a0dc1`](https://github.com/google/go-cmp/tree/b133f1f1932e48f466f597a3346ce6f5a49a0dc1),
its `go.mod` has no external requirements, so a complete raw-Git export can be
tested with module network access disabled and a verified compatible Go compiler:

```sh
env GOENV=off GOTOOLCHAIN=local GOPROXY=off GOSUMDB=off \
  GOMAXPROCS=2 GOMEMLIMIT=1GiB GOFLAGS='-p=2 -mod=readonly' \
  HOME="$task_home" TMPDIR="$task_tmp" GOPATH="$task_gopath" \
  GOMODCACHE="$task_modules" GOCACHE="$task_build_cache" \
  "$reviewed_go" test -race -json -count=1 -timeout=240s ./...
```

Run from that verified export on an authorized Linux worker, with task-private
directories and an external process-group wall limit. `GOPROXY=off` is module
resolution policy, not network isolation. Recheck the compiler's live path,
version and hash on the actual worker: a historical cache path on another host
is not a transferable installed environment. Avoid modifying shared Go installs
or reusing someone else's writable build cache.

An owner check of this unchanged revision on Linux amd64 Go 1.26.9 completed
ordinary tests and race tests with 710 passing test/subtest events per run and
zero failed/skipped test events. Five helper packages reported no test files;
those are not extra passing tests. Source hashes remained unchanged. This is a
compatibility baseline, not the project's Go 1.21/macOS CI matrix, a discovered
bug or evidence of higher PR yield. Repeat relevant native checks for new source
revisions and proposed changes. The wide Scout template uses mutable `master`
to discover updates rather than treating the tested commit as forever-current.

Check [package contracts](https://github.com/google/go-cmp/blob/b133f1f1932e48f466f597a3346ce6f5a49a0dc1/cmp/compare.go)
before proposing a repair: comparison callbacks must satisfy their documented
semantics, and deliberate panics or diff formatting choices are not necessarily
defects. Source reading does not authorize arbitrary model-generated test code.
The [contribution guide](https://github.com/google/go-cmp/blob/b133f1f1932e48f466f597a3346ce6f5a49a0dc1/CONTRIBUTING.md)
also requires the submitter's Google CLA; do not claim one on their behalf.

Keep race-runtime setup failures distinct from detected data races. A small
address-space limit can prevent ThreadSanitizer shadow mappings even when RSS is
modest; [LLVM documents this virtual-address limitation](https://clang.llvm.org/docs/ThreadSanitizer.html#limitations).
Preserve the failed run and its diagnostics. If changing the execution limits is
authorized, retain bounded CPU/time/process and memory protection appropriate to
that worker; sampled RSS and cooperative runtime heap limits are not hard cgroup
quotas. Do not change assertions or turn off race instrumentation to get PASS.

The native result reader accepts at most 64 expected identities. A full-suite log
is useful for package accounting, but is not a complete small selection merely
because the expected cases occur in it. `compare_regression` rejects extra cases.
Run a fresh focused baseline/candidate selection when that is the required check;
do not filter away test events or synthesize package terminals. Go parent/subtest
events are identities, not distinct bugs. This checks captured outcomes, not the
truth of the assertions or prospective discovery quality.

For a separately cross-built Windows test executable, the existing native
Windows runner can consume the official converter's JSON stream:

```text
python scripts/scout_native_run.py --native-windows --cwd TASK_DIR --output FRESH_OUTPUT --format go-json --package PACKAGE --source fs.test.exe=SHA256 --expect-test TestRegression --expect-test TestControl --timeout 30 -- ABSOLUTE_TEST2JSON_EXE -t -p PACKAGE ABSOLUTE_TEST_EXE -test.v=test2json -test.count=1 -test.timeout=20s
```

Replace the template's paths/hashes and supply every selected test identity,
including parents/subtests. Set task-private TEMP/TMP through `--env` when used.
Bind both executable hashes and record compiler/converter versions. This
[official single-binary interface](https://pkg.go.dev/cmd/test2json) needs a
toolchain supporting the framing flag; plain `-test.v` is lower fidelity.
Prefer `go test -json` when a native compiler is available. A JSON converter
does not make compilation a runtime witness, replace fixtures, verify source,
or qualify Windows race/other Go versions. Reviewed commands still need local
physical and commit headroom; do not reroute an application-control denial.

For a dependency-bearing Go package, first make a small bounded request for an
actually needed module's version metadata on the intended worker. Local Git
access or an installed compiler does not prove that its module proxy or checksum
service is reachable. Preserve a timed-out preparation and stop its owned
process group; it is not a failing test. A separately reviewed public mirror
can change transport without changing the frozen `go.mod`/`go.sum` or replacing
real imports with stubs. Keep acquisition task-private, use `-mod=readonly`, and
compare both files with the raw source after preparation and testing. Checksum
verification against a trusted existing `go.sum` and fresh checksum-database
authentication are different guarantees: [Go documents their relationship](https://go.dev/ref/mod#authenticating).
Do not silently disable authentication or accept newly generated sums. Once the
required modules are present, turn module acquisition off for the comparison;
this still is not network-namespace isolation or full-application qualification.

### A small dependency-free retry library

`cenkalti/backoff` is another native Go discovery source. At current-v7
[`b1a30d9`](https://github.com/cenkalti/backoff/tree/b1a30d947ca896d37518610255281904b439c619),
`go.mod` requires Go 1.23 and no external modules. An unchanged raw-Git export
passed ordinary and race suites on Linux amd64 Go 1.25.10: 41 passing
test/subtest events per run, no failures/skips, with all source hashes unchanged.
This is baseline testability, not Go 1.23/Windows CI or a performance result.
The examples use real loopback HTTP, so the Python-only offline sandbox without
Go is not an equivalent execution environment. Reuse a compatible authorized
native toolchain in a private directory; disable module acquisition and keep
the test child environment free of credentials. Disabled module resolution is
not network-namespace isolation.

The [contribution rules](https://github.com/cenkalti/backoff/blob/b1a30d947ca896d37518610255281904b439c619/README.md#contributing)
require discussing an issue before a PR. The independently reproduced
[Notify cancellation report #194](https://github.com/cenkalti/backoff/issues/194)
is an open report, not an accepted repair or Scout discovery result. Its real
zero-delay timer can be ready alongside cancellation; the old select branch
starts a second operation and can report success after synchronous cancellation
in Notify. Separate controls retain the initial-attempt guarantee, ordinary
zero-delay retry and cancellation of a long wait. This concerns dispatch of a
future attempt, not interruption of a running operation. Do not conflate it
with older context-wrapper or in-flight cancellation discussions or count the
128 repetition bound as independent bugs. Follow maintainer direction before
publishing a repair, and keep the original baseline failure.

## TypeScript lifecycle checks without a monorepo rebuild

For a reviewed, self-contained module, a compatible Node runtime and the real
lock-integrity dependencies can answer a narrow native question. Preserve raw
source bytes; if a task-local package imports mapping replaces a workspace alias,
record that adaptation rather than claiming the shipped package was imported.
Use real filesystem/process dependencies for the behavior at issue, and explain
any logging wrapper. Check executable access as the actual unprivileged child,
including parent-directory traversal. Reuse a verified task-private binary copy
when appropriate; do not relax permissions on another task's tool directory.
This is not a full TypeScript typecheck, Vitest suite or rendered TUI test.

Acquire the existing contract tests as well as the cache and its caller. Kimi
Code's pinned [negative-probe test](https://github.com/MoonshotAI/kimi-code/blob/83a39b49ed62627c7a604b39e26d8e9d17ade296/apps/kimi-code/test/utils/git/git-status.test.ts)
explicitly expects no second probe, including after forced refresh. A real
`git init` then stale-cache observation establishes a user-visible limitation,
not by itself a contract-validated repair. Changing that policy needs an explicit
behavior rationale or maintainer clarification, with throttling/coalescing and
disposal controls. Existing tests can themselves be wrong; neither this example
nor a green baseline is a blanket no-bug verdict for negative caches.

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

### Torch-dependent CPU translation units

A serving wheel's platform tag can block installation without making every
native unit untestable. On a compatible CPU Torch runtime, a reviewed small
translation unit can be built with `torch.utils.cpp_extension.load` in a private
directory, with CPU affinity, one compiler job and a process-group deadline.
This does not qualify the serving package, its supported hardware matrix or a
model. Check the real translation unit's linked dependencies, not just includes:
vLLM's [CPU MoE TU](https://github.com/vllm-project/vllm/blob/a2fb4827324bf023075799ef3d70d347834b8137/csrc/cpu/cpu_fused_moe.cpp)
also needs the unchanged [scratchpad implementation](https://github.com/vllm-project/vllm/blob/a2fb4827324bf023075799ef3d70d347834b8137/csrc/cpu/utils.cpp).
Keep ISA/build-definition adaptations explicit; an AVX2 vector check is not AMX
qualification, and disabling unused NUMA setup is not a topology test.

Use an unprivileged task directory whose ancestors are traversable. A private
child under a root-only parent remains inaccessible after changing the child's
owner. Disable unrelated uv configuration discovery. A task-owned uv cache
normally contains relative links to its own archive objects; validate their
resolved confinement rather than rejecting every symlink or following foreign
targets. Completed owned artifacts can be reused offline. `--no-deps` is not a
dependency check: inherited packages must satisfy the actual selected Torch
METADATA requirements, and their observed versions/provenance must be retained.

Runtime visibility and installer reuse are separate checks. For a uv-created
`--system-site-packages` environment, [uv documents](https://docs.astral.sh/uv/reference/cli/#uv-venv--system-site-packages)
that its list/install commands ignore inherited system packages even though
Python can import them. A successful Torch/numpy import therefore does not imply
that a subsequent uv resolution will reuse those distributions or work offline.
Inspect the actual interpreter paths and package metadata before allocating a
large repair budget. If the target requires uv, prepare its explicit private
closure; otherwise an inheritance-aware installer is an option to evaluate,
not an assumed fix. Never install into the shared base to make either route pass.

A narrow registration shim must preserve the real op schema, mutation aliases,
default arguments and wrapper behavior. Calling extracted method/test ASTs with
a seed or fixture adapter is not a full-module import or official pytest run.
Compare independent numerical oracles and retain failed controls. If an old
control fails, run the identical input on baseline: bitwise-equal outputs can
separate a shared baseline discrepancy from a new regression, but cannot turn
either strict failure into PASS. Do not loosen tolerances or discard the case.

A Python loop over rank-local contributions is not a distributed check. When the
failure involves expert placement, run the reviewed real operator in fresh rank
processes, compare each local contribution (including exact zero for nonlocal
routes), then use a real collective and compare the global result independently.
Match safe baseline inputs: do not send global IDs outside the old kernel's local
array bounds merely to obtain a red result. Keep broader corrected-input coverage
separate. A four-process Gloo operator check still does not qualify the framework's
process-group setup, prepare/finalize lifecycle, serving package or model.

Audit oracle precision against the actual implementation. In the pinned vLLM CPU
MoE TU, the activation intermediate is the input dtype, but the second GEMM and
weighted accumulator are float32. An extra per-expert BF16 cast changes that
reference computation even if the test happens to pass. Preserve and supersede
results obtained with the wrong oracle rather than silently editing their inputs.

Before a full build, check the pinned source's compiler/CMake requirements, not
only whether the narrow TU compiled. Private compiler packages need a functional
header/link/runtime canary in addition to download hashes. Bound dependency
resolution and acquisition too; an exact official artifact can remove resolver
work, but do not keep retrying unchanged failed setup or call a toolchain canary a
full-package build.
