# Optional Kimi scout

A small **hypothesis inbox**, not an autonomous PR publisher. It polls explicitly
selected public repositories, supplies unresolved issue reports, short source
excerpts, related-PR context and three
reviewed knowledge lessons to the configured Kimi model, and saves at most one
lead per request. Unchanged evidence and incidental PR-title-list churn cost no
new model call. No ordinary kernel
work needs this service, and it does not resurrect the historical GPU broker.

## Safety and cost boundary

- Reuses the existing Kimi Code **1.30.0** default model and API-key configuration.
  No key is copied into this repository, a prompt, a subprocess command, or logs.
  OAuth and other CLI versions fail with a specific error until reviewed.
- Calls the installed provider with **zero tools**. The CLI agent runtime, MCP,
  plugins, hooks, skills, Shell and file tools are never loaded. Prompts cannot
  authorize commands. No GPU, SSH, git writes, PRs, service control, or autonomous
  code execution. API calls go only to the user's configured Kimi endpoint.
- Controller fetches use fixed HTTPS GitHub API/raw hosts, bounded reads and no
  redirects. With `--github-auth`, the existing Git credential helper is used only
  for controller-side API GET requests. Repositories must be public; credentials
  are never included in evidence. No interactive login is started.
- Default trial: **24 hours, concurrency 2, 12 attempted requests per rolling
  24 hours, 200,000 tokens/reserved-token units, 4,096 output tokens/request**.
  This cap includes any hidden thinking the configured endpoint elects to use;
  the client requests disabled thinking / low effort, but does not assume the
  endpoint honors it. A length-terminated answer is not accepted as a finding.
  Conservative input-byte plus output reservations are atomic before dispatch.
  Valid reported usage replaces reservations even when answer validation fails;
  unknown usage keeps the full reservation. This is not a dollar-cost estimate.
  The Kimi account's own limits still apply. There are no automatic model retries.
- Two consecutive errors pause new calls for 15 minutes, escalating to at most
  one hour during repeated outages. The worker stays alive, drains in-flight
  calls and resumes with new work after cooldown; failed jobs are not replayed.
  Interrupted jobs are not replayed either. Local storage/infrastructure errors
  still stop the process with an explicit failure reason.
  `stop` prevents new requests; bounded requests already in flight finish.
  OS-level single-runner locking prevents duplicate daemons on the same inbox.
- Results require supplied URLs and source excerpts (ignoring only whitespace
  and displayed line-number prefixes). This checks provenance,
  **not truth**. `REVIEW` is an unverified lead; `NEEDS_CONTEXT` needs human/owner
  investigation. Neither means correct, fast, novel, or upstream-ready.
- Raw evidence/results stay in ignored `runs/`. Knowledge suggestions are not
  automatically written into the reviewed library. Review, deduplicate, then use
  the normal `knowledge add` workflow if a finding will help a future decision.

## Run

Only the backend needs the existing Kimi environment. Find its interpreter using
`uv tool dir` if Kimi was installed by uv; normally it is
`<uv-tool-dir>/kimi-cli/Scripts/python.exe` on Windows or
`<uv-tool-dir>/kimi-cli/bin/python` on Linux. The controller uses Python 3.10+.

```sh
python scripts/kimi_scout.py --root runs/kimi-scout init
<kimi-python> -I -B -X utf8 scripts/kimi_scout_backend.py --check
python scripts/kimi_scout.py --root runs/kimi-scout run \
  --kimi-python <kimi-python> --feeds templates/kimi-scout-feeds.json \
  --hours 24 --concurrency 2 --max-jobs 12
```

Add `--github-auth` only if the public GitHub API needs your existing login's
higher rate limit. Do not substitute an authenticated private repository.
On Windows, launch with `Start-Process -WindowStyle Hidden` and explicit log paths
to keep this local worker running after the terminal closes. This program does
not modify startup tasks or prevent sleep; the computer and network must stay on.
It does not require a recurring Codex conversation or spend Codex tokens itself.

For explicitly authorized continuous operation (no local daily call/token caps):

```sh
python scripts/kimi_scout.py --root runs/kimi-scout run \
  --kimi-python <kimi-python> --feeds templates/kimi-scout-feeds.json \
  --hours 0 --concurrency 4 --max-jobs 0 --token-budget 0 --poll-seconds 300
```

Zero disables only that named limit; per-call timeout/output limits, dedup,
tool prohibition and provider account limits remain. This may consume ongoing
paid account usage until stopped. Runtime JSON represents disabled caps/deadline
as `null`. Finite rolling budgets pause claims rather than permanently exiting;
capacity becomes available again as attempts age out of the 24-hour window.
Example feeds split up to eight unresolved reports per repository into distinct
small packets. They poll for changed evidence, not repeated answers to unchanged
questions; being alive does not imply four paid calls are always in flight.

```sh
python scripts/kimi_scout.py --root runs/kimi-scout status
python scripts/kimi_scout.py --root runs/kimi-scout stop
```

State is in `scout.sqlite`, summaries in `results/*.json`, untrusted model answers
in `results/*.answer.json` (including parse failures), worker state/deadline in
`runtime.json`, and the latest fetch errors in `last-feed.json`. Remove only this
inbox's `STOP` file explicitly before restarting. Restarting does not reset the
rolling daily budget. Raising limits is a deliberate operator action.

For ad-hoc cheap review, `add packet.json` accepts a small, **already reviewed
public-only** JSON packet with `name`, `question`, and `sources` containing
`{url,text}`. A public URL alone does not prove arbitrary pasted text is public:
the person preparing that packet must remove private logs and credentials.
Never point this tool at an arbitrary directory of private files. The background
feed mode fetches public material itself and never scans local worktrees.

Edit the example feed's exact line windows and questions to suit current work.
Issue samples are deliberately small and cannot prove novelty. If Kimi keeps
requesting missing context, improve the packet rather than adding an unrestricted
agent or repeatedly paying for the same question. Existing PRs such as Quack
#161 and our FlashAttention #2902 should be reviewed, not duplicated.

## Live local dashboard

```sh
python scripts/kimi_scout_dashboard.py --root runs/kimi-scout --port 8767
```

Open `http://127.0.0.1:8767`. The viewer is read-only and loopback-only: it has
no start/stop/dispatch endpoints, does not load Kimi credentials, and does not
expose the inbox as a file server. It can stay open independently of the scout.
On Windows, use `Start-Process -WindowStyle Hidden` with explicit output/error
logs for a background viewer; it does not install startup tasks or keep the PC
awake. Other machines cannot access this loopback address.

The page refreshes every two seconds while visible. It shows worker slots,
queue/history filters, evidence packets, visible assistant replies, duration,
actual reported usage and reservations separately. Historical integration trials
are included in the totals. `REVIEW` is **unverified**, not a qualified PR.
Each task is a separate bounded model request, not a persistent multi-turn agent
conversation. A queue with no new evidence shows idle workers, not fake activity.

New requests save their exact public input to `results/<id>.request.json` and
throttled visible-output snapshots to `results/<id>.live.json`. Hidden reasoning,
provider config and credentials are never copied to the viewer. Live snapshots
are best-effort observability, not accepted findings. Legacy jobs have saved
evidence/results but no token-by-token replay or exact historical system prompt;
the page labels those limitations. Restart the scout after upgrading to enable
new snapshots and heartbeats; do not replay past paid calls just for the UI.

Offline viewer tests (temporary local HTTP server only):

```sh
python -B tests/test_kimi_scout_dashboard.py
```

## Evaluate before expanding

Review the first batch for useful leads, incorrect claims, and missing context.
Track accepted leads, owner review time, actual tokens and downstream GPU time.
Keep it only if this lowers **total cost per useful validated change**, not just
the cost of producing plausible PR prose. A batch with zero real leads is allowed.

Offline checks (no network, credentials, or paid model calls):

```sh
python -B tests/test_kimi_scout.py
<kimi-python> -I -B -X utf8 tests/test_kimi_scout_backend.py
```

Implementation references: [Kimi CLI](https://github.com/MoonshotAI/kimi-cli),
[custom-agent/tool behavior](https://moonshotai.github.io/kimi-cli/en/customization/agents.html).
The version-pinned backend is intentionally separate from the ordinary CLI:
print mode auto-approves tools, which is inappropriate for an unattended scout.
