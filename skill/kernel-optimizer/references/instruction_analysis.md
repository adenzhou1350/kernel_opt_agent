# PTX and SASS admission

Static instruction analysis is a mandatory candidate gate when the target
backend produces inspectable device code.  If the binary cannot be extracted,
record the missing evidence and use `INCONCLUSIVE` for any claim that depends on
instruction formation or scheduling.

## Source-to-hardware chain

Archive source identity, compiler options, toolchain versions, PTX when
available, final binary identity, resource usage and disassembly.  Analyze the
final machine code actually launched; PTX alone does not establish generated
instructions.

Before compiling a candidate, record its expected signatures:

- instruction families and approximate dynamic counts;
- load/store width, address spaces, cache operators and transaction pattern;
- tensor/SIMT/SFU operation form and accumulator dependencies;
- barriers, waits, branches, predicates and reconvergence;
- asynchronous-copy, TMA, cluster or DSM instructions when intended;
- register allocation, local-memory traffic, stack and spill expectations.

After compilation, put observed results in `static/instruction_audit.json` and
explain every material mismatch.  Reject the causal hypothesis when the
compiler did not generate the mechanism being tested.

## Critical-path analysis

Construct dependency chains from producer to consumer and map instructions to
the target resource graph.  Account for issue pressure, latency hiding, active
warps, register lifetimes, scoreboarding, address/predicate work and barriers.
Use static counts as evidence about the binary, not as dynamic counts unless a
validated execution model or runtime counter supports the conversion.

Compare baseline and candidate on matched source scope and launch geometry.
Attribute a timing change only when the predicted instruction/resource change
is present and competing explanations have a discriminating control.

Convert workload-specific SASS into dynamic work by resolving CFG paths, loop
trip counts, predicates and tail activity for every workload case.  Build a
register/memory/barrier dependency graph and map instruction families to the
calibrated target resource graph.  Static site counts alone cannot establish a
throughput or latency bound.

The schedule model distinguishes instruction issue limits, execution-pipe
service, dependency latency, occupancy/latency hiding, CTA waves and coupled
resource interference.  When a proprietary scheduler or cache behavior remains
unknown, bound the residual and record a discriminating test instead of
inventing a precise attribution.

## Required evidence

An accepted performance candidate records:

1. source, PTX/final-binary hashes and compiler identity;
2. registers, shared memory, stack and spills;
3. expected versus observed instruction signatures;
4. resource mapping and dependency-chain change;
5. paired GPU-active timing and correctness;
6. runtime counters when available, or an explicit counter-access limitation.

Missing optional counters weaken attribution.  Missing final-binary identity or
the absence of the intended instruction invalidates the attribution.
