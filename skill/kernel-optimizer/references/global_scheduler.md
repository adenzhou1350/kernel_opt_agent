# Global scheduler and resource-modeling owner

## Role boundary

Every optimization run designates exactly one `GLOBAL_SCHEDULER` and exactly
one independent `GLOBAL_SUPERVISOR`.  The scheduler constructs the global
model and proposes decisions.  The supervisor audits whether the proposal can
change a global decision, owns experiment budget/stop authority and is the only
role allowed to approve dispatch.  Their actor identities must differ.

The global scheduler is the only role allowed to:

- freeze the material resource set and resource-constrained DAG;
- construct and rank 2--4 architecture schedule candidates;
- propose, supersede or close experiment requests;
- compare schedule candidates across stage boundaries;
- accept or reject a candidate for the weighted production objective;
- mark the resource balance or tradeoff frontier validated;
- authorize a limit certificate or human-facing limit report.

Only the global supervisor may veto or approve an experiment dispatch, approve
a revised method after a technical failure, consume screening/qualification
budget, or force `HALT_AND_REPLAN`.  The microarchitecture analyst who declares
identifiability and the experimenter who implements the probe must also be
different actors.  Artifact gates enforce this separation even in a
single-process execution.

Stage/kernel agents own implementation and evidence collection for an assigned
scope.  They may append proposals and result references, but they cannot edit a
global decision, change another stage's resource budget or call a local win a
global optimum.

## Required inputs

The owner consumes the frozen operator/workload/hardware contracts, production
baseline, mathematical and current DAGs, final-binary instruction/resource
audit, hardware specification/measurement database, reusable microbenchmark
catalog and every stage result.

## Required outputs

The owner maintains four machine-readable artifacts:

1. `global_schedule_state.json`: role identity, material resources, artifact
   versions, decision authority, current model state and report gate.
2. `resource_balance.json`: every material resource for every workload case,
   including work, service point, matched saturation, utilization semantics,
   critical-path contribution and missing evidence.
3. `tradeoff_frontier.json`: current and candidate schedules with compute,
   bytes by boundary, allocation, coverage, synchronization, predicted DAG
   time, measured time and Pareto/decision status.
4. `experiment_queue.json`: model-driven microbenchmark requests, catalog
   resolution, controls, expected SASS, result, decision impact and promotion
   disposition.

Per decision, the owner also creates `decision-contract-v1` with frozen
objective/frontier and 2--4 candidate identities, and a separate analyst
creates `measurability-contract-v1`.  Per experiment, the supervisor creates a
single-use `supervisor-approval-v1` binding the exact decision, method,
experiment and budget.

These are not summaries of work done after tuning.  They drive the next action
and must be updated after every accepted, rejected or inconclusive result.

## Resource accounting contract

For every material resource row record:

- mandatory valid work and legal minimum;
- actual useful, padded, redundant or amplified work;
- production topology and service point;
- matched saturation point or `UNKNOWN`;
- utilization value with numerator, denominator, time window and units, or a
  bounded unknown;
- exposed critical-path contribution and coupling evidence;
- causes of non-saturation selected from the shared vocabulary;
- evidence grade, source identity and unresolved request IDs.

Compute efficiency is decomposed as:

`device efficiency = coverage × eligible-time fraction × eligible-window issue efficiency`

Only multiply factors whose windows and denominators are compatible.  If
`FLOP/(active SM × kernel time)` is used, it already includes idle eligible
time and must not be multiplied by a second duty factor.

Memory is accounted independently at request, shared/L1, L2 and device-memory
boundaries.  `request bytes / time` is a request-service rate, not L2 or HBM
utilization.  A boundary utilization requires measured boundary bytes and a
matched saturation curve for the same mechanism.

## Candidate-driven dispatch loop

For each unresolved global decision:

1. Generate at most 2--4 materially different schedule/fusion candidates.
2. Compute lower bounds, feasible intervals, mandatory work, boundary bytes,
   allocation and synchronization for every candidate.
3. Select the top two. Register exactly one uncertain model quantity only when
   its interval crosses their ordering boundary. State the equation, precision,
   outcome-to-ranking map and maximum decision value.
4. Let the microarchitecture analyst determine whether that quantity is
   atomically identifiable. `NOT_IDENTIFIABLE` routes to candidate A/B or no
   measurement, never to an arbitrary atomic probe.
5. Rank requests using candidate-specific decision value, probability of a
   top-two flip, expected uncertainty reduction and experiment cost.
6. Query `microbench/catalog.json` by resource, mechanism, boundary and required
   qualification using the deterministic matcher; retain its hash-bound receipt.
7. Reuse a package only when instruction mechanism, timing, cache boundary and
   configurable geometry can represent the request.
8. Otherwise create a run-local candidate under `microbench_candidates/`.
9. Record expected final SASS, DCE sink, timing, correctness, cache, geometry,
   saturation criterion and cross-layer prediction before execution.
10. Materialize source identities, argv-form commands, parameter matrix,
    controls and output contracts. The supervisor then audits role separation,
    identifiability, precision, decision value and tier budget. Only a
    hash-bound approval permits `DISPATCHED`.
11. Bind immutable results back to the request and update the resource/DAG
   model before ranking another experiment.
12. Route application-independent validated candidates through the existing
   append-only promotion gate; keep application-shaped probes run-local.

No experiment may be executed merely because it is easy or because a model
field is unknown. Every dispatched request must prove that its result can
change the top-two candidate decision within the registered precision.

`PROPOSED` means a frozen decision contract found a discriminating question.
`PLANNED` means the exact experiment exists but is not runnable without
supervisor approval. `DISPATCHED` means the executable contract and approval
both passed validation. `AWAITING_SUPERVISOR_REVIEW` follows a technical
failure; `HALT_AND_REPLAN` follows a causal rejection. Neither automatically
returns to `PLANNED`. `RESOLVED` means a valid immutable result is bound; it is
not closed until its reconciliation records applied revisions of every named
global model.

## Candidate decision

The global scheduler compares current and candidate schedules using their
resource-constrained DAG prediction and production measurement.  The decision
must include changes in bytes at each memory boundary, valid/padded compute,
register/shared allocation, CTA waves, device coverage, synchronization,
correctness and uncertainty.  A local kernel speedup is rejected when its
weighted end-to-end cost is worse or when cross-stage evidence is missing.

## Human-report gate

A human report may omit raw experiment mechanics from its primary view, but it
must not omit a material resource.  Each resource displays measured work point
and utilization or `尚未测量` plus the dispatched experiment.  A theoretical-
limit report is forbidden until the global state, resource balance, tradeoff
frontier and production model are validated under their pre-registered error
gates.
