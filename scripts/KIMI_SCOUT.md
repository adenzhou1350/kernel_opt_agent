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
- Two consecutive provider/infrastructure errors pause new calls for 15 minutes, escalating to at most
  one hour during repeated outages. The worker stays alive, drains in-flight
  calls and resumes with new work after cooldown; failed jobs are not replayed.
  Interrupted jobs are not replayed either. Local storage/infrastructure errors
  still stop the process with an explicit failure reason.
  `stop` prevents new requests; bounded requests already in flight finish.
  OS-level single-runner locking prevents duplicate daemons on the same inbox.
  An isolated invalid answer/citation fails only that job; eight consecutive
  invalid answers also activate cooldown to prevent a paid bad-output loop.
- Results require supplied URLs and source excerpts (ignoring only whitespace
  and displayed line-number prefixes). This checks provenance,
  **not truth**. `REVIEW` is an unverified lead; `NEEDS_CONTEXT` needs human/owner
  investigation or bounded public-source enrichment. Neither means correct,
  fast, novel, or upstream-ready.
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

## Continuous research queue (optional)

Replace `--feeds` with `--research templates/kimi-scout-research.json` to pursue
an explicit public-repository objective rather than wait only for recent issues:

```sh
python scripts/kimi_scout.py --root runs/kimi-scout run \
  --kimi-python <kimi-python> --research templates/kimi-scout-research.json \
  --github-auth --hours 0 --concurrency 4 --max-jobs 0 --token-budget 0
```

This deliberately allows continuing paid Kimi usage until stopped. It is a local
queue producer, not Codex Goal mode and not an unrestricted Kimi agent. No extra
Codex conversation, recurring wakeup or agent-to-agent messaging is required.

- A separate controller thread maintains up to 24 pending packets, while the
  existing four workers independently consume them. It rotates repositories,
  issue triage, source windows and follow-ups. State survives daemon restarts.
- Discovery includes up to ten pages of open issues per sweep and up to three
  120-line windows per eligible file in configured source prefixes, with related
  tests where identifiable. **This is partial sampling, not complete code review.**
  Repository snapshots, exact source blobs and public evidence are cached locally.
- Leads and context requests receive at most two follow-ups, only when new public
  evidence is available. The controller can add issue comments, observed tree
  members and bounded related-work search. Model hints cannot introduce arbitrary
  fetch URLs or paths. The final output is a falsification/reproduction **plan**;
  actual tests, GPU validation and PR decisions still belong to the owner.
- Source-window content and issue evidence are deduplicated. Timestamp-only issue
  updates and unchanged snippets under a new commit do not buy a repeated call.
  No-lead, failed and interrupted calls are not automatically retried.
- After a sweep, the producer waits for new public evidence rather than
  manufacturing more prompts. API failures back off separately; provider and
  bad-answer circuit breakers and account limits still apply. Four concurrent
slots are a ceiling, not a guarantee of nonstop paid requests.

### Optional 8–16 worker trial

`--concurrency 8 --review-priority` enables up to eight model calls with a
work-conserving preference cycle: three discovery, three skeptical source-review,
and two reproduction-plan claims per eight claims. These are queue preferences,
not fixed agents or a guarantee of independent truth. If a preferred stage is
absent, the oldest available packet uses that capacity; discovery is not starved.
Defaults remain unchanged. Do not start a second runner on the same inbox.

`--concurrency 16 --review-priority` raises the ceiling to sixteen; the same
3/3/2 preference cycle repeats (approximately 6/6/4 claims, not fixed roles).
Compare real completion throughput, p50/p95 latency, source/JSON failures and
provider errors against the eight-worker window before keeping the increase.
Sixteen working requests establish a tested lower bound, not the provider's
maximum capacity or a promise of sixteen useful findings. Do not probe higher
limits by creating duplicate work or bypassing provider backoff.

`templates/kimi-scout-research-wide.json` covers vLLM, SGLang, Quack, FlashInfer,
TileLang, FlashAttention, Mooncake, Megatron-LM, DeepSpeed and OpenClaw. Source
sampling includes TypeScript/JavaScript for OpenClaw; these are application
correctness leads, not operator-performance results. Its optional
`context_workers: 3` overlaps bounded
public context reads across repositories to reduce an empty model queue; this is
separate from paid model concurrency. Each repository has at most one active
refill, and the producer drains before releasing its single-runner lock.
For large monorepos, optional `tree_roots` selects explicit top-level directories
(OpenClaw uses `src`). The controller resolves their Git tree identities from
the root and caches a deliberately partial snapshot. Metadata stays capped at
8 MB per tree, source files at 1 MB, and model packets at 24 KB. Unselected
subtrees are not reviewed; a large tree never becomes a large paid prompt.

The review stage tries to disprove a lead using supplied callers/tests/related
work; the last stage produces a minimal reproduction **plan**. Neither executes
model-generated code, marks a PR Ready, or promotes knowledge automatically.
Only exact source quotations pass validation. Malformed output is recorded once,
not silently repaired or retried. Compare occupancy, failure mix, terminal leaf
leads and owner review time before assuming eight workers halve delivery time.

`research.json` displays the objective, queue buffer, producer state and cumulative
source windows (not full-file coverage). SQLite stores the durable frontier and
dedup keys. Per-call packets include stage and parent/root lineage. REVIEW calls
within one chain are not multiple candidate PRs. Public caches and all raw
results remain local under the ignored run directory; reviewed knowledge is
never automatically overwritten.

Refill and worker claims use SQLite indexes, installed idempotently on restart
without resetting history or budgets. Followup eligibility (repository, depth and
already-seen chain) is filtered before the retrieval limit; recent activity in a
busy repository cannot hide an older candidate in another. A GitHub issues page
containing only pull requests advances pagination rather than ending the scan.
If slots are idle with an empty queue, inspect context supply and source coverage
before increasing model concurrency. Exhausted scopes and no-new-evidence stops
are normal; do not manufacture repeated calls to improve occupancy.

Follow-ups retain distinct excerpts of the same immutable raw-source URL;
URL deduplication must not discard a newly supplied constructor or caller window.
Each citation must match one delivered excerpt, not a concatenation across gaps.
Generic filenames such as `kernel.py` are not evidence that two files are related;
prefer the owning observed path. Excerpts remain partial: retaining a new window
does not establish that the complete API contract has been inspected.

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

The handoff overview reports the last 15 minutes of completions, rate and failures,
the last completion time, and current slot occupancy (not GPU utilization).
Repository cards aggregate the full inbox, not just the 500 visible history rows.
Only REVIEW jobs without a child are counted as current review leaves; a leaf is
still an unverified hypothesis, not a cross-chain-deduplicated or PR-ready result.
Reproduction-plan leaves have not executed tests. The lifetime call/token ledger
is collapsed separately. An offline or stale-heartbeat process cannot appear as
confirmed live occupancy. Updating this viewer does not require restarting scout
workers or replaying analysis.

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
python -B tests/test_kimi_scout_dashboard_briefing.py
```

## Evaluate before expanding

Review the first batch for useful leads, incorrect claims, and missing context.
Track accepted leads, owner review time, actual tokens and downstream GPU time.
Keep it only if this lowers **total cost per useful validated change**, not just
the cost of producing plausible PR prose. A batch with zero real leads is allowed.

When terminal leads accumulate, the limiting stage is owner verification, not
discovery capacity. Group existing leads by owning path/symbol and hypothesis,
check the complete caller/input contract and related work, then choose a small
reproducible batch in environments already available. Record an actual baseline
failure/fixed pass, a concrete rejection, or an environment blocker once. More
reproduction-plan prose is not another validation stage. The separate opt-in
executor below supplies an isolated execution boundary; this scout still has no tools.
Measure verified findings per reported token and owner review time on that batch;
do not divide delivered PRs by all calls as a precision estimate while most leads
remain unreviewed. More occupied slots alone are not a quality improvement.

## Opt-in CPU test execution

`kimi_scout_verify.py` runs one owner-staged public Python module before and after
a change, using the same selected `unittest` file. The test imports `subject`.
Invoke it explicitly inside Linux/WSL with an existing Docker daemon:

```sh
python3 scripts/kimi_scout_verify.py --baseline /public/before.py \
  --candidate /public/after.py --test /public/test_subject.py --timeout 60
```

It uses the cached official uv Python 3.10 image pinned by its full SHA256 in the
script, with `--pull never` and explicit `runc` (not a GPU runtime). Each sequential
run has no network, a read-only root,
UID 65534, no capabilities/new privileges, 512 MiB memory, one CPU, 64 processes,
and a private 64 MiB scratch tmpfs. Only immutable copies of the selected module
and test files are mounted read-only; directories, symlinks, credentials, Docker
sockets and GPU devices are not mounted. Dependencies are not installed.
Docker disk logging is disabled; only the bounded attached output is collected.

JSON output records input hashes, image, exit codes, elapsed time and bounded
untrusted test output. Timeouts, truncated output, missing/zero test counts or
failed cleanup are inconclusive. The label is always `TEST_RESULT_NOT_PR_READY`:
a reviewer must judge whether assertions exercise the real defect and whether
the change meets repository requirements. Generated tests can be wrong or weak.
The reported test count and output are untrusted observations, not semantic proof
or evidence that an advisory snippet is a qualified contribution.
This command makes no Kimi calls, does not consume the scout queue, and does not
publish changes. Host-side commands are fixed; model code runs only in Docker.

Suggested small-batch workflow: select a reproducible public-source lead, ask
Kimi for tests that import the real module, inspect the proposed test, run both
versions, and return actual logs for at most one test-repair attempt. Keep the
first failure as evidence; do not silently weaken assertions or mark environment
failures as candidate defects. Package/native/GPU tests need their own compatible
isolation and are not supported by this stdlib-only entry point.

A known-regression pilot used 6,600 reported Kimi tokens for generation plus one
repair: an initial malformed quote failed both versions; after repair the same
six tests gave baseline 5 pass / 1 error and fixed 6 pass. This demonstrates the
feedback loop, not new bug discovery or improved scout precision. Review still
found a redundant assertion in the generated test.

Offline checks (no network, credentials, or paid model calls):

```sh
python -B tests/test_kimi_scout.py
python -B tests/test_kimi_scout_verify.py
<kimi-python> -I -B -X utf8 tests/test_kimi_scout_backend.py
```

Implementation references: [Kimi CLI](https://github.com/MoonshotAI/kimi-cli),
[custom-agent/tool behavior](https://moonshotai.github.io/kimi-cli/en/customization/agents.html).
The version-pinned backend is intentionally separate from the ordinary CLI:
print mode auto-approves tools, which is inappropriate for an unattended scout.
