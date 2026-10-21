# Fresh source-choice v4: executable pair, incomplete miss audit

The [pre-frozen frame](scout_source_choice_readiness_v4.md) qualified a new slot,
not a replacement for failed/incomplete v3 cases. This result is **not evidence
of discovery or cost superiority**, and is not submission-ready paper evidence.

## Original subject and entry

`pypa/installer` at `97609d8b7c202f3a8e5174747559e83c61a4cc95`, target
`src/installer/_core.py`. The filename-only companion was `tests/test_core.py`.
All 57 tracked files were retained as raw Git bytes. The official Flit build's
19 tracked package members matched those bytes. The original selected module
collected and passed nine tests, not the complete nox/coverage/OS matrix.

The final investigation payload contained 69 files / 3,912,520 bytes, including
expanded source. That exact payload passed the original-module command before
model calls, with pre/post input hashes equal. An earlier successful test had
used a separate unpack step and was insufficient to qualify the final inputs;
its receipt remains retained, not relabelled. Exact-payload preparation finished
321.34 seconds after source creation, inside the original 600-second ceiling.

Both policies reused the unchanged default loop/parser from
[mini-swe-agent `04d809c`](https://github.com/SWE-agent/mini-swe-agent/tree/04d809ceab9df28f9adaed044884180159172930),
with the same GLM-5.3 low-effort configuration and offline nonroot Python 3.12
CPU sandbox: 1 CPU, 512 MiB, no GPU/network/host mounts. The rule ran first.

## Retained outcomes

| Policy | Queries | Inclusive reported tokens | Cached input subset | Native actions | Wall seconds, including release | Conclusion |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Deterministic reads + one GLM review | 1 | 11,222 | 0 | 5 | 16.72 | Valid `INCOMPLETE`; suspicion, no witness |
| GLM-chosen source/native observations | 7 | 27,003 | 19,776 | 7 | 32.90 | Valid bounded `NO_FINDING` |

There were no retries, unknown-usage requests or rescued model runs. All 12
comparison containers were removed, both sessions released, and all 69 original
inputs remained unchanged. Cached input is already a subset of reported input,
not a discount subtracted from total tokens. Query/wall/token ceilings matched;
realized compute did not. Provider price and active owner effort were not metered.

The direct policy investigated a path-classification suspicion rather than
repeating all companion tests as source text. Its generated probe compared
`posixpath.commonpath` with `commonprefix`; it **did not invoke installer itself
or execute the parent version**. Its old-version loop assertion was inferred.
The final original-module command did pass nine tests. Missing `git` inside its
first shell pipeline was retained, not treated as a successful Git observation.

## Separate owner adjudication

Both predictions froze before label-stripped owner review. Acquisition counts
and writing style still reveal policy, and the owner prepared the case: this was
not independent blinded human adjudication.

Four complete synthetic wheels exercised original `WheelFile.validate_record`,
`installer.install`, and `SchemeDictionaryDestination`. Ordinary root and
`.data2` prefix-sibling routing passed. An absolute member was rejected during
record validation; a traversal member was rejected during destination writing.
Neither was a demonstrated supported-contract defect. The source contract
requires wheel-root-relative paths; no generic `InvalidWheelSource` guarantee
for every malformed input was found.

Two **owner probe** errors were retained before corrected controls passed:

- RECORD self-entry was wrongly assumed to be last; the project sorts paths.
- Rejection was wrongly assumed to erase earlier valid metadata writes; there
  is no documented atomic-install guarantee. The control must instead check
  that the invalid member is not written outside its target.

These were not project defects or model findings. All six adjudication command
containers and three sessions were cleaned up. The common adjudication froze
after 374.31 seconds, within its original 1,200-second ceiling.

## Missing audit and interpretation

The separate 1,200-second owner miss-audit clock expired before native dispatch.
Its driver rejected admission; the empty output directory and failed invocation
are retained. Elapsed time included a controller interruption, not a measured
active-thinking duration. No clock reset, replacement slot or later investigation
is counted as a successful audit. **Audited misses remain unknown, not zero.**

The result establishes an executable two-policy interface, not higher useful-PR
yield: neither produced a qualified defect or new PR. The cheaper realized rule
output left uncertainty; the longer direct investigation resolved some context,
but one slot cannot establish its value. Known metadata exposure, unrandomized
order, cached-token differences, owner probe errors and incomplete miss audit
remain limitations. No recall, monetary savings, generalization or novelty claim
is supported. Cheap/strong roles, handoff/reset controls and applicable published
method comparisons still need separate qualified prospective cohorts.
