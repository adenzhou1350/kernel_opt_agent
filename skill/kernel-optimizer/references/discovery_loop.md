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

## Repairable implementation loop

Candidate source lives under `runs/<run>/candidates/<id>/`. Register an argv-form
build, correctness and smoke command with `kernel_opt.py candidate add`, then use
`kernel_opt.py candidate run`.

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
