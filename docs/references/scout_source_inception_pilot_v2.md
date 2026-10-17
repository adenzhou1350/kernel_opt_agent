# Source-inception feasibility pilot v2

Frozen before reading the selected implementation/test files or calling models.
This is a separate two-case study, not replacement/completion of
[pilot v1](scout_prospective_observation_pilot.md). V1 keeps its original queue,
cutoff, empty enrollment and unavailable controller. No known-positive repair,
historical model output or successful development batch fills either cohort.

## Enrollment

Select exactly these metadata-pinned slots in this order, including unavailable,
incompatible, unchanged-source and no-finding outcomes; do not replace a slot:

| Slot | Public repository and commit | Implementation | Companion test |
| --- | --- | --- | --- |
| 0 | python-humanize/humanize `785e5dcc0d0308ad0dff3f6cc0faa7085ad0375b` | src/humanize/number.py | tests/test_number.py |
| 1 | pytest-dev/pluggy `09fabb162b8f84af0292b827c94e0149b82d448a` | src/pluggy/_hooks.py | testing/test_hookcaller.py |

The repositories were chosen for existing Python/native capability, not observed
defects. The owner has prior experience with both repositories and may recognize
historical source; record exposure during preparation. These are not unknown
training data, random repositories, independent human adjudication or a
cross-language evaluation. Read contribution policies before any external work.

Original evidence is lines 1–80 of the implementation, with exact pin/path and
companion-path metadata. Reject oversize/encoding failures rather than silently
clip. Observation 1 is lines 81–160 of that same file (EOF may yield no text).
Observation 2 is companion lines 1–80. Observation 3 runs the first top-level
`test_*` function in that companion (or first `test_*` method in its first test
class), preserving its parametrization/fixtures. AST selection is only location,
not a contract oracle; absent/unrunnable entries remain unavailable or failed.

## Comparison and budgets

Reuse v1's six arms, cyclic order, strict literal-ID and final-review interfaces,
common MiniMax-M3 reviewer, no retries/answer repair, 300-second arm ceiling,
90-second per-call ceiling, 1,024/2,048 selector/reviewer output caps, 16,000-byte
per-prompt and 48,000-byte per-arm ceilings, and 4,500-character delivered
observation bound. Bind current coordinator/adapters, prompts, provider
configuration and menu identities before dispatch. GLM-5.3 uses explicit `low`
effort; the private gateway's realized effort remains unverified. Neither
provider is labeled cheap or strong without independent price/capability evidence.

This study stops at two slots, 20 model attempts or 75,000 observed provider
tokens (post-call stop; retain overshoot). Unknown usage or an unsettled dispatch
stops new calls for that case. Native observations are reviewed, CPU-only,
network-disabled, nonroot, at most 60 seconds / 512 MiB / 64 tasks. No generated
code, installation or dependency build occurs inside an observation.

A separately metered shared preparation allowance of 600 seconds may package an
existing reviewed pure-Python pytest stack for the already installed offline
sandbox. Each case also retains v1's 600-second preparation and 1,200-second
adjudication/audited-miss ceilings. Failed preparation does not permit expanding
resources or changing the native selection. Cache immutable physical observations
once, show standalone and amortized cost, and retain logical reads; do not call
cached evidence free or count it as independent repetitions.

Freeze all predictions before owner adjudication. Strip arm/provider labels and
deduplicate hypotheses, then apply identical native contract checks and a bounded
arm-blinded source/native audit. Record owner exposure, actual preparation,
acquisition, calls and adjudication separately, with unknown effort/prices null.
Compare reproduced findings, unresolved/false proposals, audited misses, invalid
answers, unavailable observations and actual cost. No bootstrap/generalization,
population recall, selector efficacy, priced superiority, equivalent ReAct/
SWE-Search baseline or paper novelty claim follows from these two cases. If
learned selection ties while costing more, retain that result and prefer the
simpler behavior; publication remains conditional on substantially stronger
evidence and normal contribution review.
