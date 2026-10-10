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

```text
python -B -m unittest tests.test_scout_model_usage
```
