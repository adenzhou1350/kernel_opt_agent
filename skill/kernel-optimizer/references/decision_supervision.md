# Candidate decisions and independent supervision

This contract prevents local tuning, resource enumeration and unbounded
microbenchmark expansion from replacing global optimization.

## Four non-overlapping roles

- `GLOBAL_SCHEDULER`: owns the mathematical/current DAG, resource model,
  candidate frontier and candidate-specific decision value.
- `MICROARCHITECTURE_ANALYST`: decides whether the scheduler's abstract unknown
  is measurable, maps it to an observable and states confounders/precision.
- `EXPERIMENT_AGENT`: materializes source, commands, controls and outputs; it
  does not approve its own method.
- `GLOBAL_SUPERVISOR`: audits the first three roles, owns veto/budget/stop
  authority and alone approves dispatch.

All four actor IDs must differ. This is an epistemic separation, not merely a
staffing suggestion.

## Decision contract before measurement

Generate 2--4 candidates that differ in schedule, fusion, ownership or
resource allocation. For every weighted workload case estimate mandatory work,
boundary bytes, dependency constraints, allocation, coverage and the
resource-constrained objective interval. Keep only the Pareto-relevant set.

The decision contract names the top two and one unresolved quantity. It must
state:

- exact model field/equation and current interval;
- interval of the top-two objective delta;
- decision boundary and required absolute precision;
- result intervals mapped to candidate ranking/action;
- maximum weighted objective value obtainable from resolving it;
- separate screening and qualification budgets plus revision limit.

If the top-two delta interval does not include zero, its ordering cannot flip:
do not create an experiment. An unknown resource row alone has zero dispatch
authority.

## Measurability before implementation

The analyst classifies the quantity as `ATOMIC_IDENTIFIABLE`,
`PARTIALLY_IDENTIFIABLE` or `NOT_IDENTIFIABLE`. It records the observable,
measurement window, causal formula, assumptions, confounders, controls,
falsification condition and expected precision.

Use `ATOMIC_MICROBENCH` only for `ATOMIC_IDENTIFIABLE`. A partially or
non-identifiable quantity routes to `CANDIDATE_AB`, existing evidence or
`NO_MEASUREMENT`. Expected precision must be no worse than the decision
contract's required precision.

## Screening, qualification and stop behavior

Screening cheaply rejects architecture candidates; it is not proof.
Qualification compares at most the surviving top two with production-matched
inputs, layout, launch semantics and correctness. Configuration count,
samples/configuration, process launches, wall time and revisions may not exceed
the frozen tier budget.

The supervisor approval hashes the objective, an immutable frontier snapshot,
decision contract,
measurability contract and exact experiment. Any edit invalidates approval. A
technical failure enters `AWAITING_SUPERVISOR_REVIEW`. A technically valid
experiment that rejects its causal mapping enters `HALT_AND_REPLAN`. Neither
state retries automatically.

## Capability calibration

For recurring optimization work, freeze predictions before measurements and
retain blind held-out cases. Grade evidence as exact mathematical, official
hardware, final-binary static, calibrated atomic, production-matched or
inferred. Compare predicted candidate ordering, resource work, latency interval
and SASS signature with observations. Persistent residuals change the model or
widen uncertainty; they never justify silently fitting the answer.
