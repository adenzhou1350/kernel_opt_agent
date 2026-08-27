# Microarchitecture-rooted planning

Create `models/optimization_plan.json` and
`models/microarchitecture_model.json` before tuning implementation details.
Do not begin with a launch-parameter sweep.

The designated global scheduler also owns
`models/global_schedule_state.json`, `models/resource_balance.json`,
`models/tradeoff_frontier.json` and `models/experiment_queue.json`.  Stage
workers may submit evidence or experiment proposals but must not edit the
global decision state directly.

## Planning order

1. Freeze the mathematical contract, workload distribution and objective.
2. Decompose mandatory work and construct the mathematical DAG.
3. Discover the target architecture and create a resource graph for only the
   resources relevant to this workload.
4. Map the current schedule onto that graph, including ownership, instruction
   dependencies, synchronization, memory boundaries and schedule-only edges.
5. Establish production-exact baselines and calibrated resource curves.
6. Generate 2--4 architecture candidates and rank them by their
   resource-constrained objective intervals. Identify the single uncertainty
   that can flip the top-two order. Rank only experiments that resolve that
   decision by candidate-specific value, expected uncertainty reduction and cost.
7. Define correctness, evidence, acceptance and stop gates before generating a
   candidate.

The experiment rank must come from decision sensitivity: maximum weighted
objective loss from choosing the wrong top-two candidate, probability their
ordering can flip, expected uncertainty reduction and experiment cost. A broad
whole-stage removable-time window is not candidate-specific value. A convenient
or already written probe does not outrank a more decision-relevant question.

Update the plan after every decision.  A rejected experiment must remove or
weaken a hypothesis; an accepted experiment must update the achieved schedule
and remaining bound gap.  Do not preserve a stale plan merely to retain its
original sequence.

## Resource graph

Represent the target GPU as interacting resources rather than a single peak:

- launch/front end, work distributors, warp schedulers and issue paths;
- register file capacity, allocation granularity, banks and live ranges;
- Tensor Core, SIMT FP/INT and special-function pipelines;
- LSU, shared-memory/L1 banks, L2 and device-memory paths;
- asynchronous-copy or tensor-memory engines when present;
- barriers, reconvergence and producer-consumer ownership transfers;
- CTA, cluster and distributed-shared-memory resources when present.

For every relevant node record topology, concurrency, documented ceiling,
calibrated service curve, latency, throughput, allocation constraints and
evidence grade.  Mark unknown properties as unknown.  Architecture names alone
are not evidence that an instruction or resource is available.

## Schedule model

For every workload case map logical operations to thread, warp, CTA, grid and
cluster ownership.  Record:

- useful and padded instruction work;
- dependency-chain length, available ILP and memory-level parallelism;
- bytes and transactions at each memory boundary;
- register/shared-memory lifetime and occupancy constraints;
- serialization from barriers, handoffs, address generation and instruction
  issue;
- overlap that is legal in the mathematical DAG and feasible on the resource
  graph.

Build the resource-constrained critical path from calibrated service, latency
and dependency terms.  Compare it with the achieved production schedule.  A
roofline maximum alone is not a schedule proof.

For every material compute or memory resource, maintain a production work
point, a matched saturation point or an explicit missing-evidence request.  For
compute, separate whole-device coverage, eligible-time fraction and eligible-
window issue efficiency.  For memory, keep request, L2 and device-memory bytes
and rates separate.  Do not permit a missing material row to disappear from a
summary merely because utilization cannot yet be calculated.

## Required plan gates

The plan is executable only when it names the baseline identities, workload
weights, model uncertainties, experiment queue, correctness gates, evidence
required for acceptance and stop criteria.  Claims of a proven limit require
the remaining gap to be reconciled with measurement resolution and every
material unknown to be listed in the limit certificate.

The executable plan must also define the P0--P4 microbenchmark requirements,
cross-layer prediction tolerances and the exact phase sequence enforced by
`scripts/kernel_opt.py advance`. A design family may enter implementation only after
its expected SASS signatures, resource mapping and falsification experiment are
registered. No experiment may dispatch without the role-separated decision,
measurability and global-supervisor approval contracts described in
`decision_supervision.md`.
