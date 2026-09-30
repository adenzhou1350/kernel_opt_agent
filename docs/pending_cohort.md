# Small, unfinished-task shadow cohorts

`scripts/scout_pending_cohort.py` takes a bounded **read-only snapshot** of
unfinished Scout follow-up/reproduction-plan jobs created after a chosen cutoff.
Unlike the historical development sampler, enrollment is not stratified by the
task's later answer. It checks each packet against the admission-time shadow
hash, keeps prior hypotheses, and exports no current answer or token charge.

```text
python scripts/scout_pending_cohort.py --db /path/to/scout.sqlite \
  --created-after UNIX_UTC_CUTOFF --limit 12 --per-repo-cap 4 \
  --output-dir /path/to/fresh-local-cohort
```

The output directory must be new. Fewer than the requested number of cases is a
valid undersized draw, not permission to fill it with successful historical
examples. The tool neither mutates Scout nor routes, rejects or executes tasks.

`blind-inputs.jsonl` contains decision input. `selection-outcome-side.json` holds
original job IDs, lineage roots and the native rule: keep that second file away
from model prompts and blind adjudicators. Exact-source-URL dedup and repository
caps limit repetition but do **not** make variants from one commit independent.
Group related lineages/revisions when splitting development and evaluation.

Before calling a scorer, review/sanitize the inputs and freeze the same rendered
view and option meanings for every router. Explicitly record clipping. Existing
`semantic_option_shadow.py --unlabeled` can measure latency and option-order
stability; its probabilities are uncalibrated. Keep independent reproductions,
verification cost and upstream outcomes separate from route predictions.

The tasks were unfinished at the database snapshot, not necessarily at later
scoring. Log prediction times and forbid viewing later outcomes before freezing
predictions. Enrollment alone is **not** an online budget-matched experiment,
an independent quality label, or evidence of accuracy, PR conversion or recall.
An exposed pilot cannot become an untouched holdout. To test utility, compare
rules, cheap and strong models and the optional scorer under the same complete
cost budget; include a constant-action baseline and audit missed valuable leads.

## Initial bounded pilot (2026-09-30)

The first live snapshot enrolled 5 of 12 requested cases: 1 SGLang and 4
FlashInfer follow-ups. A separate owner-reviewed public-text view was capped at
6,000 characters and used four non-authorizing actions: inspect missing source,
run a bounded CPU/compiler reproduction, prepare an environment, or abstain.
Ten forward/reverse scorer calls took 1.10 seconds total (median 110ms). One of
five cases switched from source to CPU when option order was reversed; mean
total-variation distance was 0.188 (maximum 0.373). There were no independent
action/value labels or executed routing arms, so no accuracy or benefit estimate
is claimed. These results retain the scorer as advisory-only, not a queue score
or automatic rejection policy. Raw inputs/results remain in ignored local runs.
