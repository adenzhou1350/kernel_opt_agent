# Compare observed work, not incomplete totals

`python -B scripts/scout_arm_costs.py <arms.json>` summarizes saved observations
without contacting a model, network or worker. This is an optional offline tool,
not a live gate, study protocol, price estimator or quality classifier.

The JSON object maps arm names to an `attempts` list. Each attempt has a unique
`id`, a `stage` (`selection`, `acquisition`, `review`, `verification`), a `status`
(`success`, `failure`, `not_run`), and optional nonnegative `model_tokens`,
`call_seconds`, `body_bytes`, `gpu_seconds`. Tokens and bytes are integers.
Missing values or explicit null mean **unknown**, never zero. Non-applicable
units need explicit zero. Record retries and failures, not just accepted answers;
a skipped stage needs an explicit `not_run` entry. Do not mark attempted failures
as skipped or silently omit setup, cold compilation or owner verification.

Set `inventory_complete: true` only after accounting for every attempt and
shared/setup costs according to the declared experiment. The tool cannot prove
this declaration. A total in a given unit is reported only if all four stages
are present, the inventory is declared complete, and no attempt is missing that
unit. Otherwise it reports the known subtotal and the missing measurement IDs.
Complete tokens do not make GPU seconds or owner work complete.

`call_seconds` sums non-overlapping invocation durations, not end-to-end latency.
Keep outer/inner nested timers out of the same sum. Supply measured arm-level
`elapsed_wall_seconds` separately; parallel calls can sum to more than elapsed
wall time. Distinguish physical acquisition costs from logical shared-cache
reads; do not charge one physical GET twice or treat shared cache as measured
counterfactual uncached latency. Body bytes are not wire traffic. GPU seconds
must use the same device-count convention for every arm. Token counts with
different providers/cache rates are not interchangeable dollars.

No winner or matched-budget claim is produced. Those require a predeclared
resource cap, comparable inputs and execution conditions, independently judged
utility and suitable uncertainty estimates. Existing exposed development cases
remain development cases; filling missing historical measurements with new runs
does not reconstruct their original costs or create a prospective holdout.

Offline accounting controls:

```text
python -B -m unittest tests.test_scout_arm_costs
```
