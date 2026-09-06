# Fast production-candidate discovery

The discovery lane exists to produce working production candidates quickly. It
does not produce an acceptance claim, a hardware fact or a limit certificate.
Those remain owned by supervised qualification and certification.

## Portfolio before polishing

After a correct production baseline exists, first create 4--12 opportunity
records with `kernel_opt.py opportunity add`, then rank them. Each record must
name the source model term, whether it is decomposition-conditional,
current-schedule or empirical, its current objective contribution, optimistic
gain ceiling, likely gain interval, confidence, rewrite families and an
implementation budget. Source model artifacts are run-relative and SHA-256-
bound; a changed ledger invalidates the ranking. The numeric invariant is `0 <= likely lower <= likely
upper <= optimistic ceiling <= current contribution`.

For maps created by the current tool, every opportunity must also pass a
`production_impact_gate` before candidate registration. Measure the target
component inside a representative end-to-end trace or frozen production
decomposition, bind that evidence by SHA-256, and derive
`1 / ((1 - share) + share / component_speedup_ceiling)`. Reject the opportunity
when this best-case Amdahl speedup does not clear the map policy's frozen
materiality floor; an opportunity may not lower that policy locally.
Do not substitute an isolated microbenchmark speedup for the component's
production share: a 2x rewrite of 0.04% of latency is globally immaterial.

An opportunity map is a search prior, not a proof of a global optimum. In
particular, work required by the current four-stage decomposition may disappear
under legal fusion. The `ABSOLUTE_GLOBAL_OPTIMUM` scope is therefore forbidden
for opportunity records.

After ranking, generate 6--12 candidates across
at least four materially different architecture families. Vary mathematical
decomposition, fusion boundaries, materialization, CTA/warp ownership,
register/shared-memory dataflow, persistent scheduling, instruction mechanism
or workload specialization. Parameter variants of the same schedule count as
one family.

Each candidate must bind to one ranked opportunity, use one of its rewrite
families and state a predicted global-gain interval below that opportunity's
ceiling. Cover at least three opportunities by default rather than producing
many variants of the same hypothesis. Give every family a small implementation budget before
spending qualification effort on any one family.

Before registration, every candidate must include a hash-bound
`dependency_contract` with status `PROVEN_LEGAL`. It records the mathematical
dependencies that remain, the implementation boundaries that change, forbidden
rewrites, numerical-ordering constraints and the source evidence used for that
decision. A literature or profiler match is not a legality proof. If the
contract cannot explain why the rewrite preserves the operator DAG, do not
compile it; re-audit the dataflow or choose another opportunity.

When the portfolio lacks architecture diversity, run `kernel_opt.py method
recommend --run <run>`. It matches reusable, source-attributed method cards to
the frozen operator, workload, hardware and ranked opportunity map. A match is
only a `DISCOVERY_PRIOR_ONLY` candidate-generation hint: it cannot increase a
modeled gain, validate a hardware capability, accept a candidate or support a
limit claim. Missing hard capabilities fail closed, architecture affinities
outside the source scope require adaptation, and every recommendation receipt
is hash-bound to both run inputs and the reusable card set.

Turn a matched method into one or more run-local production candidates, not a
literature summary. Preserve its stated failure modes, bottleneck shifts and
validation recipe in the candidate hypothesis. If no method applies, widen the
opportunity/decomposition analysis rather than forcing a fashionable technique
onto the operator.

## Repairable implementation loop

Candidate source lives under `runs/<run>/candidates/<id>/`. Register an argv-form
build, correctness and smoke command with `kernel_opt.py candidate add`, then use
`kernel_opt.py candidate run`.

The smoke result is `candidate-smoke-result-v5` and must bind correctness to the
same anchor and edge cases used for screening. Select `EXACT_IDENTITY` when the
public contract promises bitwise, token-ID or byte identity; the baseline and
candidate SHA-256 digests must then be equal. Use `TOLERANCE_BOUNDED` or
`PROPERTY_BASED` only when the frozen operator contract explicitly permits it,
and bind each passing case to run-local evidence. A faster architecture that
changes a greedy token stream, even reproducibly, is a correctness failure and
must not enter performance promotion.

The v5 runtime contract also binds the production and observed execution modes,
treatment materialization, compile-cache identity, and the source of every
logical extent used to select a path. Compiled or CUDA Graph candidates cannot
rely on runtime monkeypatches, and a candidate whose behavior depends on valid
rows cannot infer them from a symbolic or padded physical tensor shape. Timing
accounting separates setup, compile, warmup, and steady-state windows. A shared
persistent engine is admissible only when in-process switching is eligible and
preserves treatment identity; otherwise use isolated persistent-per-arm or
cold-per-arm processes.

Use `kernel_opt.py persistent-run` when setup, compilation, model loading or
graph capture would otherwise be repeated for every smoke request. Its NDJSON
`persistent-session-v1` handshake requires the worker to report exactly one
engine initialization and a sealed session identity. Every result must echo
the requested treatment identity and provide an output SHA-256. A
`SINGLE_TREATMENT` worker may amortize setup across repeated prompts or shapes;
it must not compare arms. A `SHARED_TREATMENTS` worker is legal only when it
declares safe switching and actually returns the active treatment identity.
Give every attempt a fresh output path: receipts and protocol logs are
append-only evidence, including failures and timeouts.

A compiler error, import error, layout/type mismatch, missing build artifact or
invalid smoke harness is a `TECHNICAL_FAILURE`. It may be repaired repeatedly
within the candidate's technical-attempt budget. It does not consume the
decision contract's causal-revision budget and must never be recorded as a
performance rejection.

The smoke test uses one representative anchor and one edge case, minimal warmup
and a small sample count. Its result is discovery-only. A survivor is promoted
to the existing sealed A/B qualification flow, which reruns production-matched
correctness, timing and final-binary audits.
The observed global gain and prediction residual are written back to the
opportunity map so later estimates can be recalibrated.

## Close measured dead ends explicitly

An observation that says “reject” does not remove an opportunity from the
scheduler. Use `kernel_opt.py opportunity close` only when run-local evidence
supports a global stop disposition such as a measured rejection, a measured
service roof, a materiality floor, or a hard dependency block. The closure
certificate must include the evidence SHA-256 and concrete reopen conditions.

Closed opportunities score zero and are omitted from method matching,
candidate registration and next-action routing. If every opportunity is
closed, the only valid discovery action is `OPPORTUNITY_PORTFOLIO_CLOSED`.
Resume with `kernel_opt.py opportunity reopen` only after naming the changed
condition; the event remains in the map so the agent cannot silently repeat a
previous dead end.

## Successive halving

Use discovery budget in this order:

1. compile and minimal correctness for every architecture family;
2. cheap anchor/edge screening for every valid implementation;
3. retain at most four candidates for broader screening;
4. promote at most two candidates to supervised qualification;
5. apply full resource modeling and limit certification only to finalists.

Promotion is blocked while any registered candidate remains proposed or under
repair, so a convenient early result cannot suppress unexplored families.

Do not build a new atomic microbenchmark when a direct candidate smoke test can
eliminate a candidate more cheaply. Do not wait for every resource-model field
to close before writing the first production candidate.

No hardware measurement is authorized while there is no opportunity-linked
candidate that has passed smoke screening. A measurement is useful only when a
named uncertainty can change the ordering of working candidates.

Default budgets are twenty real wall-clock minutes per candidate, two hours
from the first registered candidate for the whole portfolio, and eight
technical repairs per candidate. Count agent reasoning and source-editing time,
not only GPU command duration. Expiry pauses discovery for a portfolio-level
decision and must not silently fall through into more measurement.
