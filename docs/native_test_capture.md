# Reuse native verification without a new controller per candidate

These optional standard-library tools capture **owner-reviewed** commands. They
do not discover defects, sandbox generated code, install dependencies, SSH,
schedule workers, call models, or decide PR readiness. Keep automated unreviewed
Scout execution disabled unless a separately reviewed isolation backend exists.

`scripts/scout_native_results.py` checks saved Go `go test -json` events, Rust
verbose libtest output, flat pytest JUnit XML, or Node's built-in TAP reporter.
Supply exact expected case names;
for Go also supply the exact package. Missing targets, skipped expected cases,
incomplete terminals, abnormal pytest exits, cached Go results, contradictory
counts, and signal termination remain inconclusive. A printed “passed” string or
exit zero alone is insufficient. JUnit setup/teardown errors are not assertion
failure reproductions. Rust compact/custom/bench output is unsupported.

Use `node --test --test-reporter=tap` for Node 24. Nested identities join the
reporter's emitted, TAP-escaped names with `::`; names containing that separator
and duplicate full identities are inconclusive. Suites are not executed tests;
ordinary parent tests count alongside their children, matching Node's summary.
TODO is counted as skipped, not passed. Cancellations, timeouts, hook/runner
failures, missing typed diagnostics/plans/summaries and unexpected trailing
output cannot establish a regression or PASS. This is not a general TAP/YAML
parser; older/unrecognized reporter formats remain inconclusive, not guessed.

`scripts/scout_native_run.py` captures one bounded command on an authorized POSIX
worker. It checks reviewed source hashes before/after, records executable and log
digests, caps output at 2 MiB, and owns a fresh pytest report path. A timeout, source
change, malformed/missing report, or surviving owned process group invalidates a
verdict. It stops only the group it created. The CPU CLI hides CUDA devices but is
not security isolation. It refuses Windows execution; it never starts local WSL.
Saved-log parsing remains usable on Windows.

Example with an already compatible private environment and exact source export:

```sh
python3 -B scripts/scout_native_run.py \
  --cwd /private/source --output /private/fresh-result \
  --format pytest-junit --expect-test tests.test_contract::test_case \
  --source package/subject.py=REVIEWED_SHA256 \
  --source tests/test_contract.py=REVIEWED_TEST_SHA256 --timeout 60 \
  -- /private/venv/bin/python -B -m pytest tests/test_contract.py -q
```

Use `go test -json -count=1` or Rust `--format pretty` for those respective formats.
The tool observes the supplied files and executable, not every dependency or
which package a test imports. Independently prove actual imports/binary provenance,
consumer reachability, numerical assertions and repository contribution policy.
Export raw Git-blob bytes and use identical test bytes on both implementations.
Do not compare a source fragment against an unrelated installed package.

For a concrete complete-module/real-native-dependency frontend comparison, see
[the TileLang reshape example](../examples/scout-native-tilelang/README.md).
It distinguishes layout assertions from import/setup errors without claiming an
exact full-package build or treating an existing author's repair as new work.

`compare_regression` in the result module checks a predeclared complete selection:
named regressions fail only on baseline, controls pass on both, and repeat counts
match. Extra/unaccounted cases, changed cardinality, missing or skipped controls
do not qualify. This is captured-log discrimination, not a semantic oracle.

`wall_seconds` includes invocation setup/identity checks; `command_wall_seconds`
includes child startup, compilation and pipe closure. Neither is active GPU time,
native kernel latency, or total research cost. Also retain discovery, failed setup,
transfer, model and owner-review costs; unknown costs are not zero.

Offline and process-lifecycle controls:

```sh
python -B -m unittest discover -s tests -p 'test_scout_native*.py'
```

Windows skips POSIX process controls. Run them on an authorized Linux worker before
shipping changes to process handling. The controls synthesize output to test the
capture protocol; separately replay a real repository's native baseline/candidate.
The optional native Node tests use an already installed Node 24 (PATH or
`SCOUT_TEST_NODE`); they never install a runtime or start WSL.
Neither test counts nor a published fix establish an evidence-selector benefit,
recall, conversion-rate improvement, or a paper result.

## When a compatible worker cannot fetch dependencies

First distinguish transport failure from an incompatible dependency or test.
If another authorized machine can acquire public artifacts, it can deliver an
offline wheelhouse; it need not share the worker's operating system. Select wheels
using the **worker's** Python version, platform tags and dependency markers, not
the downloading machine's. Retain lockfile versions, artifact URLs and hashes.
Verify transferred bytes again before installation in a fresh private environment.

Use the actual install subcommand's help: flags accepted by `uv sync` need not be
accepted by `uv pip install`. Admit unavoidable source builds individually;
do not silently replace pinned packages or enable arbitrary native compilation.
Check installed dependency consistency, then run the repository's real test entry
point with normal package imports. A resolved wheelhouse is not a passing test.
Network isolation can protect shared services, but does not provide filesystem
isolation or qualify integrations whose service dependencies were absent.

Keep one usable private environment tied to its source/lock/platform identity for
subsequent matched tests. Preserve setup failures and acquisition/transfer time;
do not report the final fast verification step as total environment preparation.
