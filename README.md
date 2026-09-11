# Kernel Optimization Agent

For a human review of the framework boundary, execution flow, directory
ownership and contract map, start with [REVIEW.md](REVIEW.md). This README is
the operator quick start; `AGENTS.md` contains mandatory agent policy.

Record the complete delivery cycle separately from performance metrics:

```bash
python3 scripts/kernel_opt.py community-timing init \
  --cycle-id <cycle-id> --task-id <task-id> \
  --minimum-material-speedup 1.02 --output work-cycle.json
python3 scripts/kernel_opt.py community-timing switch-phase \
  --ledger work-cycle.json --span-id environment-1 \
  --phase ENVIRONMENT_SETUP --actor CPU \
  --evidence discovery-receipt.json
python3 scripts/kernel_opt.py community-timing end-phase \
  --ledger work-cycle.json --span-id environment-1 \
  --evidence discovery-receipt.json
python3 scripts/kernel_opt.py community-timing run-phase \
  --ledger work-cycle.json --span-id governance-1 \
  --phase GOVERNANCE_VALIDATION --actor CPU --timeout-seconds 600 \
  --receipt governance-command-receipt.json -- \
  python3 -m pip check
python3 scripts/kernel_opt.py community-timing import-phase-receipt \
  --ledger work-cycle.json --span-id remote-env-1 \
  --phase ENVIRONMENT_SETUP --actor CPU --resource-id worker-sm120 \
  --receipt worker-terminal.json --started-at-field started_at \
  --ended-at-field finished_at --duration-field elapsed_seconds \
  --status INTERRUPTED
python3 scripts/kernel_opt.py community-timing summarize \
  --ledger work-cycle.json --output work-cycle-summary.json
python3 scripts/kernel_opt.py community-timing audit-root \
  --root /path/to/framework-evidence \
  --max-active-phase-seconds 21600
```

Start a `PROSPECTIVE_EXACT` ledger when a framework candidate is selected,
before editing production source. `init` atomically opens an active
`BOTTLENECK_DIAGNOSIS` span by default, so timing cannot silently start after
the work. Override it with `--initial-phase` when the first activity is already
known. Use `switch-phase` to close the current span and open its successor at
one timestamp; this avoids gaps between separate end/start commands. Bind the
selection receipt immediately:

```bash
python3 scripts/kernel_opt.py community-timing mark \
  --ledger work-cycle.json --kind FIRST_CANDIDATE_PROPOSED \
  --evidence candidate-value-decision.json
```

Record GitHub transitions atomically with their stable URL, observed event time
and immutable event receipt:

```bash
python3 scripts/kernel_opt.py community-timing record-pr-stage \
  --ledger work-cycle.json --stage DRAFT \
  --url https://github.com/owner/repository/pull/123 \
  --evidence github-pr-draft-event.json
python3 scripts/kernel_opt.py community-timing record-pr-stage \
  --ledger work-cycle.json --stage READY \
  --url https://github.com/owner/repository/pull/123 \
  --evidence github-pr-ready-event.json
```

`READY` requires an observed Draft milestone and `MERGED` requires an observed
Ready milestone. Do not backfill missing timestamps from memory or filesystem
mtimes; such a cycle remains `LEGACY_MILESTONE_BOUNDS` and is excluded from
exact candidate-to-Draft and Draft-to-Ready timing.

The ledger uses non-overlapping primary wall-clock spans for community research,
bottleneck diagnosis, implementation, compile/measurement, correctness,
performance, whole-model validation, upstream packaging, environment setup,
governance validation and external wait. Use `ENVIRONMENT_SETUP` only for
dependency/toolchain/runtime repair, and `GOVERNANCE_VALIDATION` only for
contracts, authorization, evidence closure and policy checks. The summary
reports their seconds and their share of attributed active work. If neither
phase was recorded, that ratio is `null` with
`NOT_SEPARATELY_RECORDED` rather than a misleading zero. Do not retroactively
reclassify legacy spans.
For a bounded command, prefer `run-phase`: it runs the exact argv without a
shell, writes an immutable wall-time/exit-status receipt, and closes the span
on success, non-zero exit, launch failure, or timeout. A passing command receipt
is not correctness or performance evidence.
When a governed worker already produced an immutable terminal receipt, use
`import-phase-receipt` to bind its exact start/end timestamps instead of
reconstructing wall time. The prospective ledger must already predate the
receipt; optional duration-field reconciliation rejects inconsistent receipts.
Importing timing does not validate the worker result or change its outcome.
Hash-bound milestones report time to the first candidate, correct result,
material improvement, qualified result, upstream-ready package, draft PR,
ready-for-review PR and merge. Legacy trials may retain milestone bounds but
must leave unavailable phase attribution under `UNATTRIBUTED_LEGACY_WORK`.
This prevents a fast kernel result from hiding days spent packaging or waiting
for external review.

Controllers can run `audit-root` across lane evidence directories without
messaging the execution lanes. It reports prospective ledgers that have no
exact phase attribution, no primary phase, or an overlong active phase. It
separately reports environment/governance measurement debt; a normally closed
bounded cycle is not mistaken for an abandoned active cycle. The audit is
read-only and intentionally does not create another evidence schema or infer
historical timing.

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
