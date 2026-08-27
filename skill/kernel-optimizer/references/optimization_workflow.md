# Optimization workflow

The enforced sequence is `PLANNING -> BASELINE -> MODELING -> EXPERIMENT ->
PRODUCTION_VALIDATION -> CERTIFICATION -> COMPLETE`.  Use
`scripts/kernel_opt.py advance --check-only --to <phase>` to inspect the next gate and
rerun without `--check-only` only after every finding is resolved.  Do not edit
`run_state.json` by hand.

At every step run `scripts/kernel_opt.py next --run <run>`. Its action order is:

1. close exact official hardware evidence or request developer documentation;
2. discover final-binary material resources and reject unresolved mappings;
3. calibrate P0;
4. build 2--4 candidates and identify the single uncertainty that can flip the
   top-two ordering;
5. map that uncertainty to a defensible observable and choose screening or
   qualification;
6. materialize the bounded experiment and obtain independent supervisor approval;
7. execute and bind immutable evidence;
8. reconcile resource balance, schedule DAG, frontier and queue;
9. check the next phase gate.

The controller may safely create manifests and receipts. It must not execute an
incomplete command contract or interpret an arbitrary result without the global
scheduler's boundary-aware reconciliation.

## Baseline gate

Freeze source hashes, ABI, inputs and environment.  Verify correctness before
timing.  Report CPU dispatch, individual GPU active time and end-to-end latency
separately.  Use warmup, clock/load checks, raw samples and an interleaved order
when comparing close candidates.

Before entering `MODELING`, every weighted workload case must have correctness,
CPU dispatch, GPU active and end-to-end baseline evidence with source and raw
sample identities.

## Hypothesis gate

Change one scheduling/resource hypothesis at a time when possible.  State the
expected observable consequence in latency, instructions, transactions,
occupancy or stalls.  Select a particle benchmark that can falsify it.

Before entering `EXPERIMENT`, the run must contain a populated mandatory-work
ledger, mathematical/current DAG, target resource graph, initial SASS/resource
schedule and executable P0--P4 microbenchmark plan.  P0 measurement calibration
must already pass.

An experiment hypothesis is admissible only after candidate screening. The
decision contract must contain 2--4 candidates, the top two, their objective
intervals and a single uncertainty whose interval crosses the decision
boundary. The measurability contract must say how an observable estimates that
quantity, with confounders, controls, falsification and precision. If the
ordering cannot flip, stop measuring and implement or qualify the winner.

## Candidate gate

Require numerical correctness on primary and boundary workloads.  Audit source
identity, launch geometry, registers, spills, shared memory, static instruction
mix and applicable runtime counters.  Missing counters make the conclusion
weaker; they do not justify inventing attribution.

Complete `static/instruction_audit.json` before accepting a candidate.  Confirm
that final SASS contains the mechanism predicted by the hypothesis and map its
dependency/resource change back to the microarchitecture model.  PTX without
the launched binary is insufficient for this gate.

Before entering `PRODUCTION_VALIDATION`, P0--P3 evidence, cross-layer component
prediction, a correct accepted candidate and a matching final-binary audit must
pass.  Before `CERTIFICATION`, P4 must cover every weighted workload case and
the production-model residual must pass or be explicitly bounded.

## Decision gate

ACCEPT only when correctness passes and the weighted objective improves with a
stable paired confidence interval.  REJECT when correctness fails or evidence
contradicts the hypothesis.  Use INCONCLUSIVE for noise, environment drift or
missing discriminating evidence.  Preserve rejected candidates and reasons.

Stop when a defensible bound is reached, remaining hypotheses are below the
measurement resolution, or further work needs new authority/hardware.  Never
stop merely because one implementation beats a prior library.

Use cheap screening only to remove candidates. Qualification is reserved for
the surviving top two and uses production-matched controls. Both tiers have
pre-registered configuration, sample, process-launch, wall-clock and revision
budgets. A technical failure requires supervisor review; a causal rejection
requires a new frontier/decision contract. Sunk implementation effort is not a
reason to spend another sample.

Before closing a run, harvest eligible run-local microbenchmarks and execute the
repository-purity audit.  A failed promotion is not bypassed: either repair the
generic benchmark or explicitly classify the probe as application-shaped.
