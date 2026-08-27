# Particle microbenchmarks

This directory is an append-only library of promoted, application-independent
particle benchmarks.  Each package owns a `benchmark.json` descriptor declaring
its questions, controlled variables, source/driver/analyzer files, DCE and
correctness controls, cache semantics, known pollution and claim boundary.
It also records the highest demonstrated qualification from static validation
through mechanism validation, device calibration and production prediction.
Publishing source never upgrades that qualification.

Do not develop here.  New probes begin under
`runs/<run-id>/microbench_candidates/` and enter this directory only through
`scripts/promote_microbench.py`.  Raw data, profiles, compiled output, caches,
production imports and application-specific names or paths are forbidden.

The first NVIDIA CUDA benchmark provides matched-grid launch, necessary
producer-consumer barrier, contiguous global-load and global-store service
curves.  It is synthetic: its measurements may populate the hardware database,
but they do not replace a production-matched operator probe.

Use raw samples for fitting.  Never copy a result between device/software
identities, and never treat cache-resident throughput as DRAM throughput.
Run `scripts/audit_repository.py` after every promotion.
