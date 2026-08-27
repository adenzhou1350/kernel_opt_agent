# Microbenchmark lifecycle and repository purity

Microbenchmarks have two states:

- Run-local candidate: application-shaped or not yet independently validated;
  keep it under `runs/<run-id>/microbench_candidates/`.
- Published particle: application-independent, parameterized, validated and
  immutable; keep it under `microbench/` and register it in the catalog.

Never develop directly in `microbench/`.  Never copy production kernels,
application imports, model names, fixed application paths, raw results,
profiles or compiled artifacts into a published package.

## Automatic accumulation

When an experiment creates a probe that may answer a reusable hardware or
programming-model question:

1. Create a run-local candidate with `scripts/kernel_opt.py microbench-new`.
2. Reduce it to one explicit question and expose workload-shaped constants as
   parameters.
3. Add DCE protection, correctness checks, positive/negative controls, cache
   semantics, known pollution and allowed/forbidden claims.
4. Validate it from a clean build and record structured, hash-bound check
   results next to the candidate. Evidence must include correctness, controls,
   measurement smoke, static-instruction validation, two independent cold-start
   reproduction receipts and application terms removed. A literal `PASS` is
   never evidence.
   Run each cold validation through
   `scripts/kernel_opt.py microbench-reproduce`; every PASS check artifact must
   appear in one of its receipts, and two distinct process IDs are mandatory.
5. Run `scripts/kernel_opt.py microbench-harvest --run ... --promote`. Promotion is
   append-only and fails closed: an invalid candidate remains run-local.
6. Run `scripts/kernel_opt.py audit`. Do not close the optimization run while
   an eligible candidate is unreviewed or the purity audit fails.

This accumulation is automatic workflow behavior, not automatic belief.  A
measured result is registered separately under a complete hardware/software
identity; publishing source does not turn one device result into a portable
hardware fact.

Qualification is monotonic. `STATIC_VALIDATED` establishes source/build/control
integrity only. `MECHANISM_VALIDATED` additionally proves the intended machine
mechanism. `DEVICE_CALIBRATED` must cite an `EVIDENCE_CLOSED_V2` measurement
registration containing official target evidence, P0 receipt, source, binary,
final SASS and raw samples. `PRODUCTION_PREDICTIVE` additionally needs matched
production validation. Lower levels mark stronger checks `NOT_APPLICABLE`; they
may not pre-claim them.

## Promotion requirements

A published definition declares its question, controlled variables, source and
driver files, measurement semantics, DCE/correctness controls, portability
constraints, known pollution and claim boundary.  Promotion requires:

- no imports or dependencies on production/application source;
- no undeclared files, symlinks, generated code or binary outputs;
- no absolute task paths or application-specific vocabulary;
- deterministic clean-build and smoke commands backed by immutable outputs;
- two reproduction receipts from distinct cold processes;
- qualification-specific structured check results and registered measurements;
- a new stable ID and destination; published packages are never overwritten.

If generalization changes the tested mechanism, keep the candidate local and
create a new discriminating validation rather than promoting by inspection.

## Directory ownership

- `runs/`: mutable task plans, candidates, raw data, traces and binaries.
- `microbench/`: promoted reusable definitions and source only.
- `hardware/measurements/`: immutable registered results and static evidence.
- `hardware/specs/`: sourced specifications, never measured guesses.
- `skill/`: concise agent instructions and routed references only.
- `scripts/`: application-independent repository automation only.
- `schemas/` and `templates/`: machine-readable contracts without run data.

Caches, temporary files and build products are forbidden outside their owning
run or immutable measurement bundle.  The repository audit is the enforcement
mechanism; prose alone is not sufficient.
