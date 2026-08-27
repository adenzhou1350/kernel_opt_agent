# Modeling layers

## Mandatory-work ledger

Count useful and padded bytes at every known memory boundary, scalar/SFU work,
SIMT operations, tensor operations, reductions, synchronization sites and
producer-consumer handoffs.  Distinguish valid work from schedule padding.

For each memory boundary retain legal-minimum bytes, unique bytes, request
bytes, transactions, L2 bytes, device-memory bytes and shared-memory bytes when
they are material. Unknown boundaries remain explicit but do not automatically
generate an experiment. A request is legal only when a decision contract proves
that resolving one unknown can flip the top-two candidate ordering. Do not
collapse boundaries into one global-memory number.

## DAGs

Maintain two graphs:

- Mathematical DAG: true data dependencies and legal parallelism.
- Current schedule DAG: mathematical edges plus implementation serialization,
  barriers, ownership transfers and resource reuse.

Label schedule-only edges; they are optimization candidates, not mathematical
requirements.

## Bounds

Keep separate values for:

- silicon lower bound from documented device ceilings;
- calibrated resource service bound from matched microbenchmarks;
- dependency lower bound from a resource-constrained DAG;
- feasible achieved time from a correct implementation;
- production-exact observed time.

For a resource curve fit `T(r)=alpha+beta*r`, document what belongs to the
intercept, what one repeat represents, cache state, DCE protection and source or
sink pollution.  A measured slope is not automatically a silicon lower bound.

The final lower bound is at least the maximum of critical-path, tensor, SIMT,
memory, SFU, instruction-front-end and synchronization resource constraints.
Do not add terms that can overlap; do not take a maximum of terms that are
forced to serialize.

## Microarchitecture grounding

Build bounds on the resource graph described in
`microarchitecture_planning.md`.  Each rate or latency must be a documented
ceiling, a matched calibrated measurement or an explicitly labeled unknown.
Use final-binary instruction evidence to connect logical work to resource work;
do not infer Tensor Core, asynchronous copy, cache policy or vector width from
source syntax alone.

For coupled resources, measure A-only, B-only and A+B when practical.  Use the
three observations to distinguish serialization, overlap and shared-resource
interference.  Preserve launch geometry, active-wave count, allocation and
working-set state when applying the result to a production schedule.

## Limit outcomes

Produce a per-workload ladder: documented-silicon lower bound, calibrated
resource bound, dependency bound, feasible resource-schedule bound, predicted
production time and achieved time.  Include uncertainty and residuals at every
step.

Use `PROVEN_WITHIN_MODEL` only when mandatory work, final-binary instructions,
material resource service and production prediction are all validated and the
remaining gap is within the pre-registered tolerance.  Use
`ARCHITECTURALLY_EXPLAINED` when an absolute bound cannot be closed but SASS,
microarchitecture evidence and bounded residuals explain the achieved result
and identify falsification tests.  Otherwise remain `INCOMPLETE` or `BLOCKED`.

## Resource balance and compute-memory tradeoffs

The per-case resource balance must contain every material Tensor Core, SIMT,
SFU, asynchronous-copy, request-service, L2, device-memory, shared-memory,
front-end and synchronization resource used by the final binary.  Each row
records mandatory work, actual work, production service, matched saturation,
utilization or a bounded unknown, critical-path contribution, non-saturation
causes and evidence.

For a compute pipeline, define whole-device efficiency only through compatible
factors: device coverage, eligible-time fraction and eligible-window issue
efficiency.  For a memory boundary, utilization is achieved boundary bytes per
kernel-active time divided by a mechanism- and geometry-matched saturation
rate.  Documented peaks remain a separate background ceiling.

Every schedule candidate must enter a compute-memory tradeoff frontier with
changes in valid/padded operations, bytes at each boundary, allocation,
parallel coverage, synchronization and predicted resource-constrained DAG
time.  Compare candidates by the weighted latency objective subject to
correctness; never accept a byte-saving rewrite from arithmetic intensity
alone.

Generate 2--4 architecture candidates before local parameter tuning. For each,
propagate documented/measured uncertainty through the resource-constrained DAG
to an objective interval. The mathematical/modeling owner emits only the
abstract quantity, equation, candidate delta interval, decision boundary and
required precision. A separate microarchitecture analyst determines how or
whether it can be observed; see `decision_supervision.md`.
