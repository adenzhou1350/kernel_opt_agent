# Evidence-relative verdict calibration

This is an owner-exposed, known-case diagnostic, not a new discovery, paper
result, model ranking or prospective comparison. The complete sanitized inputs
and all eight returned answers are in [cpu-cache-verdicts.json](cpu-cache-verdicts.json).
Private provider envelopes, credentials, worker paths and logs are not included.
The original six calls were not overwritten or rescored after observing answers.

## Question and observation boundary

The precise claim was that **an actual dense layer requesting
`turboquant_k8v4` reaches the active CPU selector, which accepts it instead of
rejecting it**. It was not whether a global constructor option was accepted,
whether generation worked, or whether the whole package was bug-free.

Use the [native cache-format fixture](../native-cpu-cache-dtype/README.md) for
source revisions, environment, model derivation, unchanged regression and
limitations. The three initial views were:

| View | Supplied observations | M3 / GLM verdicts |
| --- | --- | --- |
| A | Two-layer construction accepted; boundary-skip helper; all actual selections were `auto` | `unproven` / `unproven` |
| B | Three-layer construction accepted; boundary-skip helper; parent selector source, but no executed middle-layer dispatch | `unproven` / `unproven` |
| C | Three-layer child raises the dtype-specific selector error before weight loading; author selector source | `refuted` / `refuted` |

The owner initially expected B to be `supported`, knowing the actual caller and
fixture. **That extra connection was not in B's delivered view.** The supplied
helper definition did not prove its invocation or the middle layer's realized
dtype. Both B abstentions correctly identified that missing edge. Retain the
original expectation as an audit defect; do not report a 4/6 accuracy or count
those two answers as demonstrated missed defects. A label for full-context
target truth is not automatically the right label for an evidence-limited task.

## Acquire the missing edge, separately

One new logging-only run appended the same observer used for the two-layer
negative control to a **fresh private copy** of the parent's `cpu.py`. It called
the original classmethod unchanged and logged return/raise outcomes. The other
backend module and native libraries were unchanged. This was a diagnostic
instrumented arm, not an unmodified source qualification or a full PR build.

The same spawned worker recorded consecutive events:

```json
{"event":"select","dtype":"turboquant_k8v4","config":"dense DECODER; use_mla=False; use_sparse=False"}
{"event":"return","selected":"vllm.v1.attention.backends.cpu_attn.CPUAttentionBackend"}
```

The abbreviated display above is not the full raw event. The sanitized model
input retains the complete selector config and matching PID. The actual child
module path was checked against the task's private parent copy. The unchanged
rejection assertion still failed, as expected for the parent; default `auto`
generation remained `[107, 92]`. **No unsupported-cache generation was done.**
Native capture: 60.049 seconds wall, 45.80 user + 2.51 system reaped-child CPU
seconds, two-CPU affinity, 12 GiB address-space limit. No network, GPU, install,
native build or shared-service change. No runner-required post-exit group
cleanup; application resource-tracker warnings remain, not a no-leak claim.
Setup, copying, model preparation and owner effort are outside these timings.

The new observation O4 was added only to B. Two separately charged continuation
requests, GLM then M3, both returned `supported`. This is not answer repair,
replacement of the initial calls, a new independent case, or evidence that an
autonomous selector could acquire O4. The owner performed that acquisition.

## Account for all calls and inspect explanations

Initial six calls used 7,595 reported tokens; the two continuations used 3,453.
All eight returned schema-valid JSON with existing observation IDs and known
reported usage: **11,048 tokens total**, no retries or fallback. Each call had
2,048 output-token and 60-second limits; the initial/continuation post-call token
stops were 25,000/7,000. MiniMax-M3 used temperature 0.1; GLM-5.3 used the existing
low-effort client configuration. Gateway realization and sampling equivalence
were not verified. M3 and GLM cache counters have different conventions; the
normalized totals include reported cache reads without adding them twice.
Prices, complete setup cost and owner effort are unknown. These are not
equal-priced or equal-realized-compute budgets, and latency is client lifecycle,
not isolated server inference time.

Do not equate schema-valid labels with faithful reasoning. M3's two B reasons
conflate unsupported-format construction with the separate `auto` generation
control; they do not establish unsupported-cache generation. GLM's continuation
reason also mentions O3 although its selected `evidence_ids` are only O4/O1:
ID-existence validation is weaker than checking every supporting statement.
Keep the exact text, review polarity and claim scope separately, and do not
silently repair responses into semantic passes.

This changes the next experiment's rubric, not Scout's production routing:

- Freeze the claim and exactly delivered observations before adjudicating an
  evidence-relative verdict; keep full-context target truth separately.
- Audit whether expected labels need a caller/dispatch fact unavailable to the
  arm. Investigate disagreement before calling it model error.
- Charge separately acquired evidence and continuations; never replace original
  answers, count continuations as independent cases, or claim free native facts.
- Grade rationale faithfulness separately from format and final label.

The next efficacy study still needs fresh groups, runnable equal-action menus,
native cost/availability controls, fixed-acquisition/rule baselines, calibrated
model costs, a complete existing-agent comparator, and blinded adjudication.
This calibration supplies none of those results and produced no new PR.
