# Precision and cross-layer qualification

Microbenchmark precision is a causal property, not a sample-count property.
Statistics reduce random noise; they do not repair dead-code elimination,
wrong cache state, CPU launch gaps, compiler substitutions or an unmatched
production geometry.

## Qualification ladder

Use five evidence layers:

- `P0`: timer, clock, launch, graph, DCE and measurement-system controls.
- `P1`: isolated instruction or single-resource latency/throughput.
- `P2`: coupled-resource overlap and interference.
- `P3`: workload-shaped component with matched grid, allocation and layout.
- `P4`: production-exact binary and end-to-end validation.

Every run records all five.  `NOT_APPLICABLE` requires a technical reason; P0,
P1, P3 and P4 cannot be skipped for a performance-limit claim.  P2 may be
inapplicable only when the schedule has no material resource coupling.

A reusable benchmark progresses through `DRAFT`, `STATIC_VALIDATED`,
`MECHANISM_VALIDATED`, `DEVICE_CALIBRATED` and, when demonstrated in a matched
component, `PRODUCTION_PREDICTIVE`.  Published source retains the highest
supported qualification; publication never upgrades the evidence grade.

## Mechanism controls

Before timing, declare logical work, expected PTX/SASS, dynamic-repeat mapping,
dependency structure, DCE protection, cache state and expected result.  Verify
the final binary.  Require zero-work, live-result, monotonicity and at least one
directional positive/negative control.  Missing or substituted target
instructions invalidate the experiment.

Choose timing by question:

- dependent instruction latency: in-kernel cycle/global timer with bracket
  control and an explicit dependency chain;
- steady issue throughput: many independent streams over a steady region;
- sub-microsecond kernel active time: verified native graph batching or CUPTI
  activity, with direct-launch comparison where graph scheduling may matter;
- production kernel: GPU events or CUPTI activity;
- CPU dispatch and cold start: separate host measurements.

Profiler-counter collection is never mixed into the timing distribution used
for acceptance.  Record clocks, power/thermal state, competing load, timer
resolution, warmup, raw samples and independent-process replication.

## Memory experiments

Declare working set, unique/alias addresses, alignment, stride, vector width,
cache operator, warm/cold policy, eviction location and whether loads are
consumed or stores must persist.  Do not label a result L2 or device-memory
bandwidth without evidence that identifies that boundary.

## Coupled resources

For every material pair measure `A-only`, `B-only`, `A+B serial` and `A+B
overlapped` with matched geometry and allocation.  Compare the combined result
with both `T_A + T_B` and `max(T_A,T_B)`.  Sweep occupancy, dependency, role and
working-set axes selectively to determine whether the interaction comes from
issue contention, latency hiding, register pressure, memory hierarchy,
synchronization or a producer-consumer handoff.

Treat a resource rate as a conditional surface over launch geometry, active
warps, registers, shared memory, instruction mix, dependencies and cache state,
not as one portable scalar.

## Cross-layer validity

P1/P2 measurements must predict P3 components, and the resulting resource
schedule must predict P4.  Pre-register acceptable model error in the run.  A
failed prediction forces model revision; it cannot be explained away after the
candidate timing is known.  Preserve raw data, source/binary identities,
controls, residuals and rejected methods.
