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

For a read-only Linux diagnosis on the actual controller host, run
`python scripts/scout_linux_memory.py`. This reports the unchanged conservative
admission value, the visible cgroup limit/current/headroom and optional
anon/file/inactive-file/shmem/dirty/mapped counters plus memory events. It does
not write cgroups, clear cache, restart a controller or credit cache as capacity.
Missing optional statistics remain unavailable; membership changes are marked
stale. The observation is non-atomic and does not prove the process is leaking.

Distinguish this raw charge reserve from physical RAM exhaustion:
[Docker's Linux CLI](https://docs.docker.com/reference/cli/docker/container/stats/)
subtracts inactive-file cache for its usage display, whereas this admission probe
does not. That display convention is not an allocation guarantee. The
[kernel's cgroup documentation](https://docs.kernel.org/admin-guide/cgroup-v2.html#memory)
defines inactive-file as reclaim-list state and explains OOM when the hard
limit cannot be reduced. A large cache and zero OOM events explain why different
displays disagree; they alone do not establish reclaimability, safe concurrency
or permission to stop another task. Keep those conclusions separate.

Requests contain only the supplied evidence, with no model tools or conversation
history. Responses are bounded to 1 MiB and the existing visible-text limit.
Reasoning text is not persisted or shown as a result. Reported completion tokens
remain inclusive: do not add reasoning tokens a second time. Missing usage/cache
counters remain unknown. Truncation, extra choices, tool requests, malformed
answers and unsupported source citations are failures, not qualified leads.
If supplied, the numeric `completion_tokens_details.reasoning_tokens` subset is
retained as `usage.reported_reasoning_output_tokens`, including length failures.
Missing, malformed or greater-than-completion values remain unknown, not zero.
This provider-reported observation is not independently measured cost, latency
or answer quality; it is never added to the inclusive charge. Do not infer a
visible-token count by retokenizing text or reconstruct past reasoning usage.
HTTP mode permits an explicitly selected output budget up to 32,768 tokens;
Kimi's default remains 4,096. A forced-thinking model may consume a small cap
before emitting any visible answer. Preserve that failed trial and choose a
new bounded task/budget rather than silently retrying or treating HTTP 200 as success.
For example, the [GLM thinking-mode documentation](https://docs.z.ai/guides/capabilities/thinking-mode)
explicitly says GLM-5.3 thinking cannot be disabled. Verify the actual endpoint;
do not assume every compatible service honors Kimi-specific thinking switches.

Admit the actual task interface before expanding occupancy. A literal-copy
canary can pass while a whole-file defect hunt exhausts its answer budget.
Try a separately recorded, source-bound small question with an independently
checked native answer before spending on more broad calls; keep the failed
requests and their reported usage. If context, task or output cap changes, the
new observation is not a controlled efficiency or quality comparison. A valid
small answer proves neither fresh discovery nor the ability to review a large
packet. Include known related fixes before pursuing a lead and use the existing
window reader for missing context, rather than asking every worker to rediscover
already-reviewed bugs. This is adaptable admission guidance, not a mandatory
question size or a claim that smaller prompts always work better.

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
