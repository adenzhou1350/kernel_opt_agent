# Preserve provider usage before comparing model costs

`scripts.scout_model_usage.messages_usage(raw_usage)` is an optional, offline,
standard-library helper for a **documented Messages-style disjoint-counter
convention**, not an API client or automatic provider detector.

Total input is uncached `input_tokens` + `cache_creation_input_tokens` +
`cache_read_input_tokens`. Add `output_tokens` for total observed tokens.
MiniMax documents the convention in its
[cache usage reference](https://platform.minimax.io/docs/api-reference/anthropic-api-compatible-cache).
Its [passive caching example](https://platform.minimax.io/docs/api-reference/text-prompt-caching)
also returns separate cache-read counters through the Messages endpoint.

Missing counters remain unknown, not zero. Preserve the raw response, requested
and returned model, finish reason, request identity and elapsed time separately.
Malformed/truncated answers and failed attempts still incur reported usage;
a parsed model JSON object from a CLI is not provider usage metadata. Do not
replace an unmetered attempt's usage with a later successful call.

OpenAI-style `prompt_tokens` already includes cached input in the documented
MiniMax example. This helper rejects that shape rather than adding cached tokens
twice. Token totals across providers are not equivalent prices or compute. Keep
cache categories, plan/pricing uncertainty, setup and native verification costs
visible; this helper neither computes a winner nor proves matched budgets.

## Account for every attempted call, not only usable answers

`summarize_token_attempts(attempts)` is a small offline reducer in the same
module. Supply a list of records with exactly `attempt_id`, `arm`, `total_tokens`,
`usage_final` and `elapsed_seconds`. IDs must be unique across all arms. For a
Messages provider, use the inclusive `total_tokens` from `messages_usage`; for
Scout's Kimi backend, use its already-inclusive total without adding cached input.
Keep provider responses and source identities separately; this reducer cannot
authenticate counters or model identity and never invokes a model.
Elapsed observations must be in 0..1e9 seconds or null; at most 4,096 attempts
are accepted per reduction. Larger studies can aggregate separate batches while
retaining missingness and checking IDs across batches.

Charge selectors, unsuccessful calls, truncated output and invalid JSON answers,
not only downstream reviews that parsed successfully. A retry is another attempt
with its own ID. Interrupted-stream `observed_usage` is not final usage: set
`usage_final=false`. With no reported total, set `total_tokens=null`, not zero.
Only an explicit final zero is a measured zero-cost token count.

Per arm, `observed_token_sum` includes partial observations, while
`final_token_total` is null if any included attempt has missing/nonfinal usage.
Missing elapsed observations likewise leave `call_seconds_total` null.
Summed call time is not experiment makespan, especially under concurrency.
An empty list returns no arms, not evidence of a free successful experiment.
The reducer cannot detect omitted calls: reconcile IDs against the predeclared
attempt roster, including orphan/failed processes, before claiming completeness.

Identical output/window caps do not imply equal actual spend. Account for target
selection in the selected arm; report shared discovery/acquisition/setup once,
and keep native validation, owner effort and unknown billed dollars separate.
Tokens from different models/tokenizers are not a common monetary or compute
budget. Freeze a cost basis, limits and matching tolerance before new admissions;
do not discard costly failed cases or trim outcomes afterwards to manufacture a
match. This helper reports observations, not matched-budget efficacy or a winner.

```text
python -B -m unittest tests.test_scout_model_usage
```
