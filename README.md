# Kernel Optimization Agent

For a human review of the framework boundary, execution flow, directory
ownership and contract map, start with [REVIEW.md](REVIEW.md). This README is
the operator quick start; `AGENTS.md` contains mandatory agent policy.

This repository turns GPU-kernel optimization into a reproducible loop driven
by workload contracts, hardware evidence and falsifiable microbenchmarks.

It deliberately contains no application-specific algorithm, workload or
performance result.  Hardware facts are separated from empirical measurements;
measurements are keyed by device and software environment.

## Start a run

An agent launched with this directory as its working tree is governed by
`AGENTS.md` and must request operator computation, workload and target hardware
before tuning.  The same gate is enforced by the command line:

```bash
python3 scripts/kernel_opt.py new-run --help
python3 scripts/kernel_opt.py new-run --print-intake
```

Once three manifests are available:

```bash
python3 scripts/kernel_opt.py new-run \
  --operator operator.json \
  --workload workload.json \
  --hardware hardware.json
```

`scripts/kernel_opt.py` is the stable public command surface. Individual
scripts remain implementation modules:

```bash
python3 scripts/kernel_opt.py --help
python3 scripts/kernel_opt.py new-run --operator operator.json --workload workload.json --hardware hardware.json
python3 scripts/kernel_opt.py next --run runs/<run-id>
```

Before rebuilding a test environment, compare the requested workflow with an
already materialized closure:

```bash
python3 scripts/kernel_opt.py qualification-environment \
  --closure cached-environment.json \
  --request candidate-environment-request.json \
  --output environment-reuse.json
```

The comparison separates reusable dependency/toolchain state from a source-
bound native extension and the actual imported module. It permits a cheap
source rebind or bounded extension rebuild without treating an image, ISA,
workflow, test-contract, dependency-lock or GPU-visibility mismatch as a cache
hit. The result is advisory reuse routing only: it never authorizes a build,
test, GPU run, correctness claim or performance claim. Templates are available
with `--print-closure-template` and `--print-request-template`.

Before a model download, JIT compile or native build, fail fast on implicit or
unusable framework caches:

```bash
python3 scripts/kernel_opt.py environment-cache-preflight --print-template \
  > cache-preflight-request.json
python3 scripts/kernel_opt.py environment-cache-preflight \
  --request cache-preflight-request.json \
  --output cache-preflight-result.json
```

The request binds every intended cache path, its environment variable, a
workload-sized free-space floor and whether a temporary write probe is allowed.
The result distinguishes path drift, missing or non-directory roots,
writeability and insufficient space before an expensive command starts. It is
only an environment preflight and never authorizes download, build, execution,
correctness or performance claims.

When the worker cannot clone source, create a deterministic transport directly
from committed Git blobs. The builder never reads tracked files from the
working tree, so dirty files, checkout line-ending conversion and export rules
cannot change the payload:

```bash
python3 scripts/kernel_opt.py qualification-source-bundle --build \
  --repo /path/to/framework --commit <full-commit> \
  --repository-url https://github.com/org/framework.git \
  --archive framework-source.tar.gz --manifest framework-source.manifest.json
python3 scripts/kernel_opt.py qualification-source-bundle --verify \
  --archive framework-source.tar.gz --manifest framework-source.manifest.json \
  --extract-root /immutable/new/source-root
```

The manifest binds the repository identity, commit, tree, archive digest and
every file, executable mode and safe relative symlink. Verification rejects
tampering, duplicate or special entries, traversal, escaping symlinks and an
existing extraction target. This is source transport only: it does not approve
materialization, install dependencies, build native code, launch a workload or
authorize GPU use.

For several autonomous lanes sharing multiple GPU machines, queue validation
work independently from the task that discovered it:

```bash
python3 scripts/kernel_opt.py resource-broker --database broker.sqlite \
  submit --job job.json
python3 scripts/kernel_opt.py resource-broker --database broker.sqlite \
  bind-gate --job same-job-with-ready-gate.json
python3 scripts/kernel_opt.py resource-broker --database broker.sqlite \
  withdraw --job-id stale-job --reason-path decisions/supersession.json \
  --reason-sha256 <sha256>
python3 scripts/kernel_opt.py resource-broker --database broker.sqlite \
  acquire --inventory inventory.json
python3 scripts/kernel_opt.py resource-broker --database broker.sqlite \
  plan --inventory inventory.json
python3 scripts/kernel_opt.py resource-broker --database broker.sqlite snapshot
```

The resource broker atomically reserves an exact GPU gang on one compatible
worker, prefers a reusable environment closure, and backfills a smaller
runnable job when a larger high-priority gang cannot currently fit. It is
deliberately non-launching: the returned lease identifies only the worker, GPU
UUIDs, environment, budget, and callback task. The task-specific authorization
and atomic dispatcher remain mandatory before starting a process. A missed
heartbeat keeps its GPUs reserved in `STALE_REQUIRES_RECONCILIATION` until a
hash-bound terminal result releases them, so a possibly running job is never
made available by timeout alone.
`bind-gate` lets the controller atomically move an existing
`BLOCKED_AUTHORIZATION` job into the queue after an external supervisor gate is
available. It accepts only the same complete job with a READY gate identity;
any workload, source, environment, resource, budget, priority, origin or
callback drift is rejected. The broker binds that identity but does not certify
its authorization semantics or launch work.
An unleased blocked or queued job whose immutable body is superseded can be
withdrawn with a hash-bound reason. Withdrawal preserves the terminal audit
record and is forbidden once any lease exists; it never counts as an
experimental result.
Jobs that require a particular topology or must avoid service GPUs can bind an
exact gang through optional `resource.required_gpu_uuids`. Its cardinality must
equal `gpu_count`; the broker waits unless every named UUID is simultaneously
free on one compatible host, and records that exact sorted set in the lease.
The read-only `plan` view classifies every
queued item as immediately reservable, waiting for GPUs, requiring environment
preparation, or having no compatible resource. It is suitable for a dashboard
but is not a reservation.

For a fresh `upstream-delivery-inbox-v5` candidate routed to
`COMPLETE_AUTHOR_ACCOUNTABILITY`, automation may gather the exact commit,
evidence, pending gates, proposed PR body and fail-closed attestation command
into one create-once packet:

```bash
python3 scripts/kernel_opt.py upstream-author-review-packet delivery-inbox.json \
  --candidate-id NAME --output author-review-packet.md
```

The packet is machine-prepared convenience only. It cannot attest human review
or authorize publishing.

Use `community-action-attest` to create a short-lived, create-once current-state
record for one validated ACTIVE work-cycle span. The command derives its cycle,
resource and ledger identities and requires evidence; `RESOLVED` and
`SUPERSEDED` retire stale declared work without rewriting history:

```bash
python3 scripts/kernel_opt.py community-action-attest \
  --ledger work-cycle.json --span-id active-span --state ACTIVE \
  --action-owner AGENT --valid-for-seconds 1800 \
  --evidence current-result.json --output current-action.json
```

Register a new prospective candidate ledger without hand-editing manifest
path/hash fields:

```bash
python3 scripts/kernel_opt.py community-portfolio-register \
  --manifest /path/to/current-portfolio-manifest.json \
  --register SGLANG_OPTIMIZATION=/path/to/new-community-work-cycle.json \
  --output /path/to/superseding-portfolio-manifest.json
```

The command validates the old manifest, the complete new ledger evidence
closure, the prospective accounting boundary and duplicate cycle/task
identities. Lane selection stays explicit; filenames and task prose are never
used to guess ownership.

The run is intentionally blocked until `hardware_evidence.json` archives exact
vendor-official documents for the programming model, ISA, target-architecture
tuning guide and device specification. If the agent cannot find one of those
official documents, the developer must provide its location; inferred hardware
facts and neighboring-device values are forbidden.

After the exact launched binary is archived inside the run, disassemble it with
a hash-bound tool/architecture receipt, classify every static instruction site,
and build the conservative resource set. Unknown or multiply classified SASS
mnemonics are a hard stop:

```bash
python3 scripts/kernel_opt.py sass-archive \
  --binary runs/<run-id>/static/launched.cubin \
  --output-sass runs/<run-id>/static/final.sass \
  --output-receipt runs/<run-id>/static/disassembly_receipt.json \
  --vendor NVIDIA --device-name '<exact device>' --compute-capability 12.0
python3 scripts/kernel_opt.py sass-count \
  --input runs/<run-id>/static/final.sass \
  --binary runs/<run-id>/static/launched.cubin \
  --disassembly-receipt runs/<run-id>/static/disassembly_receipt.json \
  --output runs/<run-id>/static/sass-summary.json
python3 scripts/kernel_opt.py resources-discover \
  --sass-summary runs/<run-id>/static/sass-summary.json \
  --hardware-evidence runs/<run-id>/hardware_evidence.json \
  --output runs/<run-id>/models/resource_discovery.json
python3 scripts/kernel_opt.py next --run runs/<run-id>
```

Use `scripts/kernel_opt.py hardware-discover` to create a hardware snapshot,
then use the selected microbenchmarks and analysis commands to build evidence. `runs/` is
for generated artifacts; reusable knowledge belongs in `hardware/`,
`microbench/`, `schemas/` or the skill references.

Each run designates one `GLOBAL_SCHEDULER` and an independent
`GLOBAL_SUPERVISOR`. The scheduler maintains the global resource balance,
2--4-candidate tradeoff frontier and candidate-driven experiment queue. The
supervisor alone approves a hash-bound, budgeted dispatch. Stage workers cannot
accept a local candidate or approve their own probe. Phase gates reject a
run whose material resources are omitted, whose unknown utilization is not
bound to an experiment request, or whose accepted candidate lacks a global
tradeoff decision.

The shortest legal experiment path is:

```bash
python3 scripts/kernel_opt.py experiment-rank --run runs/<run-id>
python3 scripts/kernel_opt.py experiment-materialize --run runs/<run-id> --request-id <id>
# Complete the sealed experiment.json, then independent review:
python3 scripts/kernel_opt.py experiment-approve --run runs/<run-id> --request-id <id> \
  --supervisor-id <registered-id> --rationale '<decision-boundary review>'
python3 scripts/kernel_opt.py experiment-dispatch --run runs/<run-id> --request-id <id>
```

Dispatch fails when the top-two ordering cannot flip, the quantity is not
identifiable at the required precision, any role identity overlaps, a tier
budget is exceeded, or any approved artifact changed.

Run phases are non-skippable.  Inspect and advance the next gate with:

```bash
python3 scripts/kernel_opt.py advance --run runs/<run-id> --to BASELINE --check-only
python3 scripts/kernel_opt.py advance --run runs/<run-id> --to BASELINE
```

The enforced order is planning, production-exact baseline, modeling,
P0--P3 experiments, production/P4 validation, certification and completion.

## Clean asset lifecycle

Each directory has one owner:

- `runs/` contains mutable application work, raw evidence, binaries and new
  microbenchmark candidates.
- `microbench/` contains promoted application-independent source packages only.
- `hardware/measurements/` contains immutable results keyed by complete device
  and software identity.
- `skill/`, `scripts/`, `schemas/` and `templates/` contain only reusable
  instructions, automation and contracts.

Create candidates with `scripts/kernel_opt.py microbench-new`. At each accepted
hypothesis and before closing a run, execute `scripts/kernel_opt.py
microbench-harvest --run <run> --promote`; only candidates whose
correctness, controls, clean build, two independent cold starts, genericity and
static-instruction evidence are hash-bound and pass are added to the catalog.
Mechanism, device-calibrated and production-predictive claims have progressively
stronger gates. Device qualification additionally requires an
`EVIDENCE_CLOSED_V2` record in `hardware/measurements/index.json`; a string
`PASS` or an unregistered result is rejected. Promotion is append-only and never overwrites an
existing package. `scripts/kernel_opt.py audit` rejects undeclared files,
caches, generated outputs, production dependencies and task-specific content
in reusable directories.

Cold validation commands are argv-form JSON executed by `scripts/kernel_opt.py
microbench-reproduce`. The executor rejects source-tree
outputs and stale pre-existing artifacts, then binds logs and fresh outputs to
its own identity. Promotion accepts PASS check results only when those exact
artifacts occur in a trusted reproduction receipt.

## Evidence classes

- `FACT`: queried or statically verified.
- `MEASURED`: backed by immutable raw samples.
- `INFERRED`: derived from stated facts and measurements.
- `HYPOTHESIS`: awaiting a discriminating experiment.
- `REJECTED`: falsified or measured with an invalid method.

See `skill/kernel-optimizer/references/` for the optimization protocol.

## CPU-only qualification environment preparation

When a new qualification closure must be built, the controller can issue a
short-lived approval with `qualification-environment-authorize --issue` after
reviewing the exact materialization plan, environment request and still-blocked
broker job. The approval requires every preparation step to declare
`gpu=false` and forbids GPU devices, workloads, service mutation, broker
submission, gate binding and acquisition. It may allow network access only for
dependency materialization; it never authorizes the later GPU test or turns the
prepared closure into correctness evidence.

Add `--dispatcher-bound` when the approval will be consumed by the shared
worker-local dispatcher. Omitting it preserves the legacy v1 approval format
for existing run-local audit and materializer flows.

Run an approved standard plan through the worker-local dispatcher instead of
calling its materializer directly:

```bash
python3 scripts/kernel_opt.py qualification-environment-dispatch \
  --artifact-root /path/to/run \
  --approval /path/to/run/experiments/materialization-approval.json \
  --approval-sha256 <controller-reviewed-sha256>
```

New approvals bind the exact dispatcher bytes and are single-use. The
dispatcher revalidates the approval, plan, still-blocked job, executor and
deadline, atomically claims the approval, forces CUDA visibility off and runs
the one sealed argv without a shell. A crash or nonzero exit consumes the
claim and requires a fresh versioned plan and approval; it is never retried
automatically. Its terminal receipt proves only the executor process outcome.
The materializer's own evidence still decides whether the closure succeeded,
and neither receipt authorizes a GPU, workload, service or broker transition.
Legacy v1 approvals remain validatable for audit but cannot be dispatched.

The versioned dispatcher receipt includes exact process `started_at`,
`completed_at` and monotonic `duration_seconds` so a controller can account for
environment wall time without inferring it from file timestamps. These timing
fields remain process evidence only; they do not accept the resulting closure
or change correctness, performance, GPU or workload state.

Managed workers may already run inside a GPU container and have no nested
container runtime. Collect a read-only worker attestation before planning an
environment directly on such a worker:

```bash
CUDA_VISIBLE_DEVICES=-1 python3 scripts/kernel_opt.py \
  qualification-environment-worker --collect \
  --worker-id worker-shared-sm120 --host-id shared-8x-sm120-32g \
  --storage-root /workspace --output worker-runtime-attestation.json
```

The request binds that exact worker and attestation with
`runtime_provenance.kind=ATTESTED_PREPROVISIONED_WORKER` and a null image
digest. Reuse fails closed on worker or runtime drift. Pre-mounted device nodes
are recorded honestly while Torch must see no CUDA device during collection;
the receipt is not a lease or workload authorization.

CPU isolation may intentionally make `torch.cuda.get_arch_list()` empty. The
worker attestation therefore falls back to the non-device-initializing
`torch._C._cuda_getArchFlags()` metadata while still binding the Torch module,
build configuration and native libraries. Materializers should consume that
attested value rather than exposing a GPU to rediscover compiled targets.
The same attestation records `nvcc`, C/C++ compilers, Ninja, Git, CMake and
Make as exact resolved path/version/SHA identities (or explicit nulls). Plans
that need a source fetch or native build can therefore reject an incompatible
worker before consuming a long materialization budget.
For a preprovisioned worker, set `runtime_worker.required_toolchain` in the
materialization plan to the exact attested identities needed by that plan. The
approval gate rejects a missing or drifted required tool before issuing an
approval; plans without this optional field keep their existing behavior.

The recorded GPU process list is a historical observation. A shared service
may be running when a later CPU-only preparation starts. Capture live process
rows immediately before and after and call
`validate_cpu_only_process_transition`: it accepts stable pre-existing process
identities (and memory-use drift) but fails closed on any added, removed or
replaced GPU process. This avoids treating a protected service as a reason to
rebuild the runtime while still proving that preparation did not mutate GPU
occupancy.

Framework imports are not necessarily read-only: DeepSpeed, SGLang, Triton,
Torch and model tooling can create caches before any test or GPU call. Use
`cpu_only_cache_environment` to derive XDG, model, compiler and temporary cache
paths under the exact closure root, create those directories before the first
import, and bind the resulting environment in the execution plan. This keeps
worker image filesystems immutable and prevents unrelated `/root` capacity
from deciding whether an otherwise reusable environment can materialize.
The same contract is available to shell-oriented executors without importing
the module:

```bash
python scripts/qualification_environment_worker.py \
  --cache-environment /workspace/kernel-opt/closures/<closure-id>
```

The command emits one JSON object containing the complete environment mapping;
consumers must create and bind every emitted path before the first framework
import rather than partially reconstructing the mapping.

Framework imports may also write informational logs to stdout before a probe
prints its machine result. Use `parse_final_json_object` to require the final
non-empty line to be one JSON object. Earlier logs remain permitted, while a
missing result, trailing diagnostic or non-object JSON still fails closed.

## Seeded hardware evidence

The first adapter and historical dataset target an RTX 5090 / SM120 environment.
They live under `hardware/measurements/nvidia/rtx5090_sm120_gpu6/` and include a
hardware snapshot, raw launch/barrier/load/store samples, service-curve fits,
the compiled binary identity, resource usage and SASS.  The counter-access
probe is archived separately and currently reports `DENIED`; no stall-counter
claim is permitted from that environment.

Those historical records are explicitly `LEGACY_UNQUALIFIED`: they may be
inspected, but they cannot parameterize a hardware model. A usable measurement
must be re-run and registered as `EVIDENCE_CLOSED_V2` with official target
evidence, P0 calibration, source, binary, final SASS and raw samples. New device
models receive separate snapshots and measurement directories rather than
inheriting values.
