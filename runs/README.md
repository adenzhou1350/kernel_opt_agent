# Local run workspace

This directory is intentionally empty in Git. `kernel_opt.py new-run` creates
run-local contracts, raw samples, logs, downloaded references, binaries and
derived reports here.

Run output is evidence, not reusable source code. Store completed evidence in
an external artifact location with its immutable manifest and SHA-256
identities. Keep only reusable, application-independent assets in the source
repository:

- schemas and command-line tooling in `schemas/` and `scripts/`;
- reusable optimization guidance in `skill/`;
- promoted microbenchmarks in `microbench/`;
- portable hardware descriptions and qualified measurements in `hardware/`.

Historical run artifacts removed from the default branch remain recoverable
from Git commit `b540118a85f4fa1c61d3396575c623dc2c657cb1`.
