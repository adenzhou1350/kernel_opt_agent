# Optional tool-free HTTP backend

Scout can use an explicitly configured OpenAI-compatible chat-completions
endpoint without starting a Kimi SDK process for every worker. This is an
alternative transport for the existing queue, not a second agent framework.
The default Kimi backend is unchanged. HTTP mode additionally needs `httpx`
installed in the controller's existing Python environment.

Keep a controller-owned JSON file outside Git:

```json
{
  "endpoint": "https://example.org/v1/chat/completions",
  "model": "your-model",
  "alias": "your-observed-model"
}
```

An optional `api_key` is sent only to that endpoint. No Kimi configuration,
GitHub token or ambient proxy settings are inherited. Plain HTTP requires
`"allow_http": true`; use it only for an explicitly authorized trusted network.
Redirects are not followed. Do not put internal addresses or secrets in commits.

```sh
python scripts/kimi_scout.py --root PRIVATE_RUN run \
  --kimi-python /existing/python \
  --openai-backend-config /private/provider.json \
  --concurrency 4 --max-jobs 16 --hours 1
```

`--kimi-python` remains a required legacy CLI argument; HTTP mode runs in the
controller and does not launch that interpreter. HTTP, resident Kimi and SSH
backend flags are mutually exclusive. Start with a bounded pilot and increase
concurrency only after observing real response validity, deadline cleanup and
controller memory. A memory estimate for SDK children is not a measurement of
HTTP threads, but a smaller estimate also needs evidence and reserve headroom.
Preserve existing shared-host memory/disk guards and drain owned work before
switching a running controller; do not run two controllers against one inbox.
HTTP mode permits up to 100 in-flight requests; SDK/SSH Kimi stays capped at 16.
This is an admission ceiling, not a target occupancy. An empty deduplicated
evidence frontier cannot be accelerated by raising it. Track completed valid
answers per minute, latency, provider errors and independent reproductions;
do not refill capacity with repeated old hypotheses or fabricated evidence.

Keep admission pauses distinct from terminal stops. The optional
`scout_linux_memory.supervisor_memory_action` separates a configured admission
floor from a lower critical drain floor. While paused, keep the same controller
alive and let its existing reservation guard refuse new calls; do not clear STOP
or restart/replay work. Unknown telemetry or critical pressure still drains.
Choose thresholds from the actual worker, not a universal recommendation.
`--worker-memory-mb` reserves RAM for each already-submitted and next request
in addition to `--min-free-memory-mb`. Admission requires measured available
RAM >= floor + (in-flight + 1) * worker reservation. Recheck between claims.
Defaults remain unchanged (zero extra reservation); this is conservative
accounting, not a guarantee of future allocations. Linux observations include
visible cgroup ancestors and do not discount inactive file cache. A high count
may require a separately reviewed floor/reservation combination; do not silently
disable guards or mistake host-wide RAM for container headroom. HTTP capacity
tests do not establish a particular provider's throughput or answer quality.

Requests contain only the supplied evidence, with no model tools or conversation
history. Responses are bounded to 1 MiB and the existing visible-text limit.
Reasoning text is not persisted or shown as a result. Reported completion tokens
remain inclusive: do not add reasoning tokens a second time. Missing usage/cache
counters remain unknown. Truncation, extra choices, tool requests, malformed
answers and unsupported source citations are failures, not qualified leads.
HTTP mode permits an explicitly selected output budget up to 32,768 tokens;
Kimi's default remains 4,096. A forced-thinking model may consume a small cap
before emitting any visible answer. Preserve that failed trial and choose a
new bounded budget rather than silently retrying or treating HTTP 200 as success.
For example, the [GLM thinking-mode documentation](https://docs.z.ai/guides/capabilities/thinking-mode)
explicitly says GLM-5.3 thinking cannot be disabled. Verify the actual endpoint;
do not assume every compatible service honors Kimi-specific thinking switches.

There are no transport retries or automatic provider fallback. Authentication
and permission errors preserve the existing supervisor's terminal-denial route.
Only `finish_reason=stop` with a nonempty visible answer can reach the ordinary
Scout result validator. A tool-free `length` response is an answer-budget
failure, not a provider outage: it stays `FAILED`, keeps its usage and visible
partial answer, and is not replayed. Repeated answer failures still use the
existing answer-quality circuit; transport and access-denial guards remain.
The dashboard identifies this backend as `openai_http`
and results retain the configured model alias. Neither high request throughput
nor a valid source citation establishes correctness, novelty or PR readiness;
owner-side independent reproduction and the target project's rules still apply.
