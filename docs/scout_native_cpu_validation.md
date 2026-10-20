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
| Were particular code lines in one saved request? | [Request-content diagnostic](#request-content-diagnostic); not semantic recall |
| Transfer exact committed bytes? | [Source bundle](#commit-exact-source-before-native-validation) |
| Run a reviewed native command? | `scout_native_run.py --help`; [runtime/export/cleanup](references/scout_native_cpu_validation_notes.md#check-the-deployed-native-runner-not-another-checkout) |
| Capture owner-reviewed GPU pytest without another process wrapper? | [Optional shared-GPU guard](#optional-owner-reviewed-gpu-capture) |
| Compare regressions and controls? | `scout_native_results.compare_regression`; [wider pytest/Go cohorts](#complete-pytest-cohorts) |
| Reanalyze two retained native captures without rerunning tests? | [`compare-saved`](#compare-saved-captures-without-target-execution) |
| Check byte-range caching through its real caller? | [Buffered-file versus BytesIO oracle](../examples/native-file-cache/README.md); bounded serial memory backend, not network/performance qualification |
| Check backend integer rounding before a full compiler build? | [Reviewed CuTeDSL scalar/MLIR witness](../examples/native-cutedsl-truncdiv/README.md); not vector, compiler or GPU qualification |
| Check config lifetime across successive alias loads? | [Shared-class serialization witness](../examples/config-alias-serialization/README.md); copied-helper and full-package `get_config` modes, with distinct source/runtime scope |
| Test a model/backend without migrating production? | [Finite public batch](#finite-public-batch-without-a-task-specific-executor) |
| Reuse task-private dependencies? | [Content versus isolation](#dependency-reuse-content-is-not-isolation) |
| Setup/collection failed before assertions? | [Platform/package routes](#package-and-language-routes); retain failure, not a bug verdict |
| Check an existing sequential loop's native-feedback mechanics? | [No-model agent/sandbox canary](../examples/native-agent-loop/README.md); custom environment and known fixture, not efficacy or real-provider qualification |

Before paid CPU reproduction generation, the delivery worker queries the selected
fixed Docker image with `kimi_scout_verify.py --check-runtime --profile PROFILE`.
This is a five-second read-only image inspection: no pull, target execution or
package installation. Failure is an environment blocker, not a no-bug result.
The worker saves `runtime-preflight.json`; an unavailable daemon, permissions,
missing image or incompatible verifier can all reject this check. A successful
lookup proves neither imports nor relevance of the eventual target test. Actual
isolated execution and cleanup checks still apply. GPU review-only proposals
do not require a CPU runtime and gain no execution authority from this check.

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

Written guides and enabled PR settings are not the whole contribution surface.
Inspect the target's workflow filenames for contribution guards before publishing.
For an observed literal path, reuse `--document-path .github/workflows/close-unattended-prs.yml`;
this pins the YAML without executing it or following its `uses:` references.
Read a referenced action at the **configured revision**, not just its current README.
For example, [w3lib's pinned guard workflow](https://github.com/scrapy/w3lib/blob/9ded4ea3137a6db9dc04e32d3186f61007f3cb4d/.github/workflows/close-unattended-prs.yml)
uses [an action](https://github.com/scrapy/unattended-pr-guard/blob/2ea7eff575dd0912d03cf3e3ae7acf65052c6445/README.md)
that can close PRs from cross-repository activity or agent-prefixed branches,
with documented exemptions and maintainer intervention. This is a timestamped
delivery constraint, not a native correctness verdict, a universal AI ban or a
guaranteed prediction for an account. Preserve the candidate while resolving the
actual maintainer-supported route; do not rename branches, disguise authorship,
switch accounts or change prose to evade a guard. No exhaustive workflow scan or
automatic eligibility classifier is added by this route.

### Withdrawn scope must also cover queued work

On an authorized delivery host, repeat `kimi_scout_delivery.py --exclude-repo
OWNER/REPO` for explicitly withdrawn repositories. This filters new intake,
pending-work capacity and atomic claims, including work queued before the flag
was set. GitHub repository identity is case-insensitive. It does not terminate
an already running call or delete/relabel historical evidence as no-bug.

Keep this explicit scope with the worker's launch configuration across migration;
copying source jobs alone can re-admit a previously parked candidate. Restore
owner dispositions through the existing owner-intake/park operations, rather
than changing completed source verdicts. Exclusion is an owner decision, not an
automatic interpretation of policy text or proof that a repository has no bugs.
Removing the flag needs a separately justified scope decision, not a queue stall.

### Local pinned packet

`scout_git_source.py --repo LOCAL_REPO --spec selection.json --output FRESH.json`
reads raw Git blobs, not converted/dirty checkout text. Select literal paths,
inclusive ranges or complete Python definitions with decorators. Missing or
ambiguous definitions and oversized packets reject rather than truncate.
Keep necessary callers/context; do not trim repeatedly just to force acceptance.
The public repository name is a declaration, not verified public provenance.
See [selection format and bounds](references/scout_native_cpu_worked_routes.md#local-pinned-packet).

### Request-content diagnostic

Before calling a known defect a model miss, check the actual saved request:

```sh
python scripts/scout_source_exposure.py --packet exact-job-packet.json --request JOB.request.json --expected reviewed-source-packet.json
```

Export the **exact original packet string**, not a reformatted JSON copy, and
the existing saved request. The expected packet contains exactly one reviewed
immutable raw-source URL and numbered lines, obtainable with the existing
`scout_git_source.py` selection route. Review its public provenance separately.
No source/model/network call, queue write or target execution occurs here.

The diagnostic matches the complete saved prompt to that packet, then compares
numbered text at the exact repository/revision/path. Metadata claiming a larger
window does not supply missing text; conflicting source lines stay inconsistent.
Missing/mismatched request files remain unknown, not zero exposure. Different
windows in the **same** packet can jointly supply lines, but do not union jobs
to claim one request contained both sides of a cross-function defect.

This only establishes saved request content relative to the reviewed expectation,
not provider receipt/attention, source reachability, defect detection or semantic
recall. A known fix or explicit duplicate exclusion in the question invalidates
using that request as an unbiased discovery test, even with complete coverage.
Keep historical diagnostics outside frozen prospective enrollment and do not
replace unavailable study cases with owner-selected known bugs.

### Model effort before fan-out

Use explicit attempt/token/time budgets and reviewed provider/effort settings.
Record failed calls and actual usage; do not repair answers, retry failed rows
or infer cost/quality from concurrency. Accepted parameters do not prove a
gateway realized them. Distinguish format validity, exact source evidence and
native correctness. A correct diagnosis may still suggest an incomplete repair;
test inherited and reflected contracts as applicable. See the
[known-case counterexample](references/scout_known_case_calibration.md) and
[effort and quote examples](references/scout_native_cpu_worked_routes.md#model-effort-before-fan-out).

HTTP receipts preserve `backend_request_controls.configured_reasoning_effort`
on success and failure without copying the endpoint or credentials. Explicit
`null` means that controller omitted the setting; a missing field in an older
or different backend is unknown, not an inferred default. This records the
loaded configuration, not proof the request reached the provider or the gateway
realized it. A visible answer rejected for an invalid quote remains `FAILED`;
do not trim/repair it into acceptance or overwrite a terminal row during a
separately budgeted development calibration. Keep frozen study arms unchanged.

### Installed code is not an enabled acquisition route

Verify both the running controller's source and its loaded repository settings.
For example, `followup_code_search` defaults to **false**: deploying a new hint
reader does not enable its opt-in GitHub search. Enable it explicitly only for
the reviewed scope, and retain search errors and physical-read costs. The current
controller loads its research configuration at startup; changing a file alone
does not establish activation. Use the existing owned drain/start path, preserve
queue/seen/backoff state, and verify actual new packets or retained configuration.
Never reset cursors or replay terminal rows merely to demonstrate a new route.
An enabled flag is not proof a later request used it or improved discovery.

Before adding a repository, prefer a narrow source area whose real package tests
can already run. At fsspec `941e6f910a1d4683f31a56a9adf78dccb50ecdcf`, the unchanged
[`test_caches.py`](https://github.com/fsspec/filesystem_spec/blob/941e6f910a1d4683f31a56a9adf78dccb50ecdcf/fsspec/tests/test_caches.py)
and [`test_mapping.py`](https://github.com/fsspec/filesystem_spec/blob/941e6f910a1d4683f31a56a9adf78dccb50ecdcf/fsspec/tests/test_mapping.py)
cohort passed 266 cases on native Windows CPython 3.14, with no errors/skips.
The existing native runner verified working source hashes, actual import paths
and owned Job Object cleanup. Raw Git and checkout bytes were checked separately.
This supports ordinary discovery in those two modules, not new bugs, Linux or
all-version coverage, automatic execution authority or evidence-selector benefit.
A new queue on another host is not recovery of a lost frozen research cohort.

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

## Optional installed CPU sandbox adapter

For an already reviewed `agent-sandbox` installation, an owner can inject its
existing `call(action, arguments)` client into the delivery library:

```python
from kimi_scout_delivery import Delivery
from scout_sandbox_verify import SandboxCPU

worker = Delivery(args, cpu_verifier=SandboxCPU(owner_client.call, image=cpu_image_sha256))
```

The owner supplies the exact CPU image and transport; neither comes from model
output. This library opt-in does not grant credentials, Docker access, GPU use,
installation or arbitrary host commands to the model. The ordinary CLI keeps
its existing direct-Docker route. For a private Kimi configuration, use
`--backend-config-file PATH` (or the same args field); only the completion
subprocess receives that path, not the model prompt.

This adapter supports **stdlib only**, not Torch, HTTPX or complete target
packages. It checks the installed CPU image, runs each arm in a fresh restricted
container, restores the pre-execution file checkpoint for the candidate, and
checks broker isolation, input hashes, termination, persistence and cleanup.
Both arms reuse the verifier's unittest harness and summary parser. A fresh
`sandbox-N.jsonl` journal reserves dispatch and records session/run handles before
side effects. On transport or infrastructure uncertainty, stop and inspect that
same session's history/evidence; do not overwrite the journal, replay the call
or continue with the candidate. Sessions without a conclusive cleanup remain
available for inspection until the installed broker's bounded expiry.

Broker evidence binds uploaded files and execution controls, not the truth of
untrusted stdout. A before-fail/after-pass screen still needs assertion review,
actual repository/package tests, prior-art checks and applicable contribution
rules before publication. This route does not change the default verification
scope or qualify a dependency-heavy lead by extracting an easier function.

## Optional owner-reviewed GPU capture

The CLI and `--export-runtime` remain CPU-only. On an authorized Linux NVIDIA
worker, the existing `kimi_scout_gpu_verify.run_native(...)` library companion
reuses native pytest/JUnit capture plus its cooperating UUID lock:

```python
from kimi_scout_gpu_verify import run_native

result = run_native(
    gpu_uuid=reviewed_full_uuid, lock_dir=shared_lock_directory,
    min_free_mib=16384, cwd=private_checkout, output=fresh_output,
    command=reviewed_pytest_argv, sources=reviewed_path_sha256_pairs,
    format="pytest-junit", expected_tests=exact_collected_ids, timeout=180,
    environment=private_environment,
)
```

For a reviewed distributed test, use `gpu_uuids=[uuid0, uuid1]` instead of
`gpu_uuid`. The owner-only library accepts at most eight distinct full UUIDs,
preserves that list's CUDA ordinal order, and acquires every cooperating lock in
a common sorted order before sampling or launching. Contention releases partial
acquisitions without launching. Each selected device keeps its own reserve,
admission/running/postflight evidence; any lost reserve or failed observation
makes the whole command inconclusive. Per-device samples are not atomic across
the set. The three-file CLI remains single-device/non-distributed, and the
native CLI/export stays CPU-only. Review all ranks, local communication,
tensor bounds, dependencies and cleanup; no extra device authority is inferred.

An owner-reviewed two-B300 component pair exercised this path with real vLLM
NCCL groups and a Triton replay-padding kernel, including a peer with no masked
rows. That proves the tested capture/communication path, not eight-device,
arbitrary-code isolation, complete PCP batch preparation or whole-model serving.

Review and transfer both companion and native-runtime source explicitly; no
model, Scout delivery worker or exported CPU tool gains GPU authority here.
The companion checks that the loaded capture accepts its UUID and execution
guard keywords before acquiring locks. An older export must be replaced in a
fresh task-private directory with matching reviewed tools, not used without the
guard. Signature compatibility alone does not prove that a wrapper enforces it.
This route requires a working `/usr/bin/nvidia-smi`, including compute-process
queries. Torch/CUDA availability alone is insufficient. A missing telemetry
executable rejects admission before launching the test child; do not substitute
Torch allocator counters for device/process telemetry or alter a shared driver
to force admission. A canary in the current isolated GPU sandbox failed this
fixed-path telemetry invocation before starting its pytest child. That image uses
its own external monitor; this companion is not qualified for it without a
separately reviewed telemetry integration.

A subsequent authorized native B300 canary exercised the committed helper with
two reviewed 128-element float32 CUDA tests: both passed, with ordinal/UUID
verification, three admission snapshots, running samples, and postflight under
one cooperating lock. The device was shared, not empty. This establishes that
small native capture path only, not sandbox compatibility, arbitrary-code
isolation, vLLM/model qualification or performance. Keep the failed sandbox
attempt separately; a native-worker pass does not repair that image's telemetry.

The reviewed child still must prove its visible CUDA ordinal/UUID mapping,
bound tensor sizes and any cooperative Torch allocator cap, and isolate its
dependencies and caches. This helper injects no Torch harness or memory quota.

Admission records three fresh device/process/load snapshots, allowing sharing
with adequate headroom. Execution samples about once per second, **including
after output EOF**, then queries postflight under the same lock. The reserve
cannot be weaker than 6144 MiB. High utilization blocks admission, not one's own
running kernels. Telemetry failure or reserve loss makes even an exit-zero/JUnit
pass `INCONCLUSIVE`; cleanup signals only the owned process group. Bounded
`execution_guard` evidence in `result.json` keeps preflight, latest running,
postflight, extrema and count, not an ever-growing sample list. NVML process
visibility can be incomplete, and sampled checks are not isolation or a hard
VRAM/wall-time quota. Native CPU-accounting deltas include the guard's reaped
telemetry subprocesses; they are not isolated workload/GPU-busy measurements.

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

- vLLM compilation: an official commit-specific CPU wheel can restore complete
  module/native-extension imports without borrowing a mismatched GPU runtime.
  Check the actual wheel's commit, Python/ABI/glibc, dependency resolution and
  CPU library paths first; latest main may have no published wheel. An unchanged
  source blob supports only that component's transfer, not a latest-main build.
  CPU configuration disables CUDA graphs: assertions that a partition wrapper
  became active can fail before the alleged cleanup bug is reached. Do not
  bypass platform selection or label those failures as a CUDA reproduction.
  The normal [CPU configuration route](https://github.com/vllm-project/vllm/blob/e68efc685ab1e6f1eda004ced7157e3ca411da2f/vllm/platforms/cpu.py)
  also switches `VLLM_COMPILE` to `DYNAMO_TRACE_ONCE`; a manually constructed
  `VllmBackend` failure alone therefore does not establish a normal CPU-serving
  failure. Verify the platform-adjusted mode before funding a repair.
  For direct backend tests, preserve its configuration lifecycle: the documented
  [`post_init_cudagraph_sizes`](https://github.com/vllm-project/vllm/blob/e68efc685ab1e6f1eda004ced7157e3ca411da2f/vllm/config/compilation.py)
  also initializes `compile_sizes`; importing the backend is not engine setup.
  Keep an unsupported-pass failure separate from an explicit public CPU override
  used in a component diagnostic. Never silently disable passes to claim default
  serving qualification. Use a same-backend healthy control and the full paired
  inventory before attributing a repair; retain failed preparation and costs.
- HTTP proxies: [real-HTTP boundary reproduction](../examples/native-http-proxy/README.md)
  uses the ordinary vLLM example lifespan/HTTPX pools against synthetic loopback
  P/D services, with original upstream status and healthy JSON/SSE controls.
  It independently reproduces an author-owned public report; it is not a fix,
  GPU/RDMA test, automatic delivery profile or fresh discovery/study result.
- Python: [HTTPcore fixtures](references/scout_native_cpu_validation_notes.md#httpcore-plugins-and-behavior-matched-test-context), [Humanize translations](references/scout_native_cpu_validation_notes.md#humanize-core-baseline-with-translation-gaps-retained), [CPU transport logic versus RDMA proof](references/scout_native_cpu_worked_routes.md#cpu-transport-logic-before-rdma-qualification).
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

Where full wheels and pip fit the authorized worker, prefer the standard
[offline wheelhouse startup example](../examples/native-python-wheelhouse/README.md)
before writing another installed-directory exporter. Target offline resolution
still must succeed; small-sandbox file limits and missing conditional artifacts
are setup failures, not target bug verdicts or permission to weaken limits.

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

### Compare saved captures without target execution

For a small predeclared complete selection, pass the two existing native capture
directories rather than writing another report loader:

```sh
python -B scripts/scout_native_results.py compare-saved \
  --baseline /saved/before --candidate /saved/after --format pytest-junit \
  --regression tests.test_contract::test_regression \
  --control tests.test_contract::test_control \
  --common-source tests/test_contract.py
```

Repeat the case/common-file flags as needed; identities and source keys must be
reviewed from the saved captures, not guessed from command-line node names. The
library equivalent is `compare_saved_regression`. It reads `result.json` and the
native runner's format-specific file (`junit.xml` for pytest, `terminal.log` for
Go/Rust/Node), with bounded raw UTF-8 reads. It preserves CRLF for digest checks,
does not follow obsolete absolute report paths in copied metadata, and never
falls back from a missing/changed file reporter to matching stdout.

The existing captured comparison retains source/test/executable digests, report
cardinality and cleanup failures. Exit 0 means `MATCHED_REGRESSION_OBSERVED`,
1 means `PATTERN_NOT_OBSERVED`, and 2 means inconclusive or invalid/missing input.
This command executes no target, repairs no report and changes no queue. A match
is captured accounting, not authenticity, meaningful assertions, production
reachability, complete environment parity, performance or PR qualification.
For wider cohorts, use the existing suite comparators rather than silently
ignoring extra cases to make this small-selection check pass. Export the native
runtime as a complete set so the capture/report filenames stay synchronized.

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

New failed calls retain sanitized final provider usage in SQLite without an
accepted analysis; failure verdicts and receipt result contracts stay unchanged.
The lifetime funnel reports unknown-usage and terminal-unknown counts explicitly.
For older rows, reuse `scout_funnel_audit.py --receipts-root` with its selected
database/time-window arguments and bounded read-only receipt recovery. Do not
backfill old verdicts, count a reservation/partial observation as final usage, or
call reported token counters billed cost.

CPU accounting scopes differ by platform; setup/model/human costs are separate.
No narrow test count, synthetic success or unpriced call establishes PR yield,
recall, total-cost superiority or research benefit. See
[report/accounting details](references/scout_native_cpu_worked_routes.md#keep-the-outcome-useful).
