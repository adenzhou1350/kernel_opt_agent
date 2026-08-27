# Hardware routing and provenance

The core schemas are vendor-neutral. Use an adapter only after device vendor,
architecture and tools are discovered. Hardware evidence is fail-closed.

## Official-source gate

For a new target, search vendor-official sources for four roles: programming
model, instruction set, exact-architecture tuning guide and exact-device
product specification. Archive the retrieved artifact inside the run and
record HTTPS URL, document title/version, exact section or table locator,
retrieval time and SHA-256 in `hardware_evidence.json`.

The allowed vendor domains and semantic document roles come from the
repository-owned adapter policy. A manifest cannot declare its own trusted
domains. The acquisition tool performs the HTTPS download itself and records
requested/final URL, HTTP status, timestamp and content hash; a local file
asserted to have come from a URL is not official-source evidence. Each fact
also needs a structured locator, exact supporting text present in the archived
artifact, target applicability and an approved semantic review.

Only `VENDOR_OFFICIAL_DOCUMENT` may support a documented hardware fact.
Official target-device tools or APIs may support queried capacity and identity
fields, but cannot create undocumented throughput or latency specifications.
Standalone microbenchmarks create `TARGET_MEASUREMENT` service evidence, not
documented specifications.

Do not use a third-party table, search-result snippet, neighboring GPU,
architecture-name analogy or model memory. When the exact architecture is not
documented clearly, stop model construction and ask the developer to provide
the official document location. Preserve the missing field as unknown.

For NVIDIA targets, record at least compute capability, SM count, warp size,
register/shared-memory limits, L2 and memory size when queryable, driver, CUDA
runtime/toolkit, compiler, power/clock state, profiler and disassembler access.
Route architecture-specific work through a capability record rather than a GPU
name check.

Keep documented specifications under `hardware/specs/` and empirical results
under `hardware/measurements/`.  Every specification field has provenance;
every empirical result has source hash, raw samples and environment identity.
Do not populate a device with values inferred from a similar model.

When a tool or counter is unavailable, record it as unavailable and downgrade
the conclusion.  Do not substitute a counter from another architecture.

## Resource discovery

Archive and disassemble the launched final binary, prove the target
architecture embedded in it, classify every static instruction site, then run
`scripts/kernel_opt.py resources-discover` with the official evidence manifest. The result
is a conservative material-resource set covering observed instruction,
allocation, synchronization and memory boundaries. Every mapping carries its
official document locator. An unknown SASS class or missing document role
enters `unresolved_mappings` and blocks planning.

Broad catch-all instruction classes are forbidden. A previously unseen
mnemonic must be explicitly reviewed before any resource-completeness claim.

The completeness claim is deliberately bounded to resource boundaries implied
by the final binary and documented execution model. Proprietary internal
pipelines remain unknown; they must not be invented to make the graph look
complete.
