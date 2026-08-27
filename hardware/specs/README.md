# Documented specifications

Store one provenance-rich record per architecture or device model. Every fact
must bind to a vendor-official HTTPS source with document title/version, exact
section or table locator, retrieval time and content SHA-256. Do not infer
missing values from a neighboring GPU, third-party table or architecture name.
When an exact official document cannot be found, request its location from the
developer and record the field under `unknowns`; do not create a specification.
Architecture capabilities and device-model capacities belong in separate
records when their scopes differ.  A specification uses `hardware-spec-v3`,
binds the repository-trusted vendor policy, keeps the archived official bytes
inside its own directory, and carries a structured locator plus semantic review
for every persisted fact.  A URL and an unverified content hash are insufficient.

A theoretical rate must include clock assumptions, datatype, sparsity mode,
instruction shape and derivation.  Marketing peak numbers without conditions
must not enter a limit certificate.
