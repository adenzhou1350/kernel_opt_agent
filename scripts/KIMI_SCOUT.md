# Optional Kimi scout

A small **hypothesis inbox**, not an autonomous PR publisher. It polls explicitly
selected public repositories, supplies unresolved issue reports, short source
excerpts, related-PR context and at most one context-matched advisory lesson to
the configured Kimi model, and saves at most one
lead per request. Unchanged evidence and incidental PR-title-list churn cost no
new model call. No ordinary kernel
work needs this service, and it does not resurrect the historical GPU broker.

Knowledge uses the existing lexical search, not a fixed GPU advice bundle.
Matches retain applicability, exceptions, evidence and status; a lexical match
does not prove relevance. Optional advice is omitted before source windows are
trimmed when the prompt is full. Historical packets are not rewritten, and this
change alone does not establish higher finding accuracy or PR conversion.

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
- Kimi/Python child-process temporary files and uv/XDG/Hugging Face caches are
  scoped to `<root>/runtime-storage`; the WSL verifier also receives a temp path
  on that volume. Put `--root` where there is enough free space. The installed
  Kimi interpreter, its small credential directory, and shared WSL/container
  image storage stay in their existing locations; other projects' caches are
  not migrated.

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
  configured workers independently consume them. It rotates repositories,
  issue triage, source windows and follow-ups. State survives daemon restarts.
- Discovery includes up to ten pages of open issues per sweep and up to three
  120-line windows per eligible file in configured source prefixes, with related
  tests where identifiable. **This is partial sampling, not complete code review.**
  Repository snapshots, exact source blobs and public evidence are cached locally.
  On a new repository revision, changed Git blobs are sampled first; unchanged
  blobs keep their deduplication identity. Mutable refs are refreshed after 900
  seconds, so a stale snapshot is not treated as a new source fact.
- Named Python/JavaScript/TypeScript hints prefer a matching declaration over
  incidental comment, import or call mentions; qualified method names precede
  their enclosing class. Explicit line starts and matched exact literals retain
  priority. This is a lexical window heuristic, not parsing or complete-function
  coverage; unmatched hints keep keyword scoring and later code may still need
  another window. Read and packet limits are unchanged.
- Leads and context requests receive at most two follow-ups, only when new public
  evidence is available. The controller can add issue comments, observed tree
  members and bounded related-work search. Model hints cannot introduce arbitrary
  fetch URLs or paths. The final output is a falsification/reproduction **plan**;
  actual tests, GPU validation and PR decisions still belong to the owner.
- An explicit same-file line interval must start at an observed truncated
  window's end or its immediate successor, and end within that pinned file.
  For a long interval, two available ordinary read slots show its head and tail
  rather than another lexical file match. The raw cache is shared; this adds no
  read slot or model call. Both excerpts retain their own visible ranges and
  truncation flags: gaps and packet clipping are not complete-function coverage.
  If a contract/test read already uses the second slot, it remains reserved.
  A captured malformed-JSON lead replay now includes its outer error handler
  within the existing 24,000-byte prompt cap. This is exposed development
  retrieval evidence, not prospective cost savings or PR-conversion proof.
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
For a ten-repository frontier with a persistently empty paid queue, 4–6 context
workers are a reasonable measured trial; the supported ceiling is 16. Increase
this only when public-context supply is the observed bottleneck. It does not add
paid model calls itself, and one repository still has at most one active refill.
The local memory/disk guards and provider backoff still apply at 16. A full
worker pool cannot create useful work when all sampled evidence is unchanged.
For large monorepos, optional `tree_roots` selects explicit top-level directories
(OpenClaw uses `src`). The controller resolves their Git tree identities from
the root and caches a deliberately partial snapshot. Metadata stays capped at
8 MB per tree, source files at 1 MB, and model packets at 24 KB. Unselected
subtrees are not reviewed; a large tree never becomes a large paid prompt.

Hash-named CUDA `_kernel.cu` / `_binding.cu` follow-ups also try the
nearest unambiguous, observed package `*_jit.py` or `registry.py` and its README.
They retain one ordinary source window and add at most an 80-line registry
window plus 60 README lines, under the same packet/read/cache limits. The exact
physical-module mapping is preferred over an earlier module record; missing or
clipped anchors are explicitly marked. Ambiguous/missing conventions do not
reject a lead or imply completeness. The registry is not executed and retrieval
does not establish CUDA correctness, coverage or a useful PR.

Other source follow-ups can replace one lexical match with an observed companion
test (at most 80 lines), preferring the same component in a monorepo. A quoted
constant present in both the pinned source and hypothesis anchors the test
window when available. Foreign/stale source, missing tests or unsupported names
leave ordinary search intact; generated CUDA registration context keeps priority.
This adds no source reads. Tests are evidence to inspect, not an automatic veto:
some intentionally characterize existing buggy behavior, and a green test does
not prove that the behavior is desirable or that a fix is novel.

The review stage tries to disprove a lead using supplied callers/tests/related
work; the last stage produces a minimal reproduction **plan**. Neither executes
model-generated code, marks a PR Ready, or promotes knowledge automatically.
An enqueue-time shadow record may suggest a cheap next action for later audit;
it is advisory, not a test result or an automatic publication decision.
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

## Opt-in delivery workers (actual tests, separate from discovery)

The owner can connect the backlog to `kimi_scout_delivery.py`. Unlike the
tool-free discovery daemon, this explicitly enabled controller stages public
modules and executes generated code **only inside the restricted verifier**.
Kimi still has zero tools or host command access; the controller accepts bounded
exact string edits, never model-selected commands, images or output paths.

```sh
python scripts/kimi_scout_delivery.py --root runs/kimi-scout \
  --kimi-python <kimi-python> --github-auth --concurrency 4 --execution-concurrency 2
# Graceful stop: no new model/container stages; in-flight work drains.
python scripts/kimi_scout_delivery.py --root runs/kimi-scout --stop
```

If an unauthenticated public GitHub metadata request hits the API limit before
the model or verifier starts, stop the delivery worker, enable `--github-auth`,
and explicitly requeue that exact unused `FAILED/HTTPError` job once with
`--retry-preflight-job <candidate-id>`. The command requires zero reported model
tokens, no job artifacts, and an inactive worker lock; it writes an audit receipt.
It will not retry a model call, sandbox run, or a second transport failure.

Windows delivery refuses to start by default because its sandbox uses local WSL.
Only after explicit human authorization for the current task, pass
`--allow-local-wsl --wsl Ubuntu` to use the existing WSL Docker daemon. Selecting a
distribution alone is not authorization. Discovery, the dashboard and owner-only
commands (including `--stop`) do not need this opt-in. Linux invokes the same fixed
verifier directly. Both cached images use `--pull never`.
`stdlib` is the Python 3.10 image above; `torch-cpu` is a pinned public vLLM CPU CI
image with Python 3.12 and CPU Torch. Selection is based on observed required
imports, not a model instruction. These are **adapted single-module CPU screens**,
not full-repository tests, official dependency qualification or GPU evidence.
Missing packages, package-relative imports, native/GPU code and other languages
are explicit environment blockers; the worker does not install them or fabricate
equivalent toy implementations. Lazy/optional imports remain runtime unknowns.

Terminal scout leads are admitted round-robin across repositories with exact
path/hypothesis deduplication. The Python delivery worker only admits packets
with an immutable `.py` source URL. C++/TypeScript and other-language leads stay
in the research database for a matching verifier instead of consuming a Python
delivery slot and ending as `ENVIRONMENT_BLOCKED`. This admission check does not
assert that a Python module is independently runnable. One lead gets generation,
at most one repair using real output, and a separate skeptical call only for
before-fail/fixed-pass.
`REPRODUCED` still needs owner assertion/reachability/novelty review; `NO_BUG`
is a model rejection, not an executed proof. No PR or knowledge is auto-published.
When a reproduced candidate lacks a demonstrated consumer, sufficient value or
target-environment evidence, explicitly defer that candidate instead of calling
it `NO_BUG`:

```sh
python scripts/kimi_scout_delivery.py --root runs/kimi-scout \
  --park-owner-job <candidate-id> --park-reason "<review finding>" \
  --park-evidence-url https://github.com/owner/repo/blob/<40-char-commit>/path.py#L1 \
  --reopen-when "<new evidence that would change the decision>"
```

`OWNER_PARKED` leaves the current owner queue but preserves tests, source, tokens,
prior status and the decision in SQLite. It is neither a false-positive verdict
nor a qualified PR, and does not suppress other hypotheses. The command makes
no model/network/GPU calls. An immediate database transaction serializes the
decision with worker writes; active candidates cannot be parked. When the worker
is idle, it refreshes the queue without replacing its PID/state/heartbeat;
otherwise the running worker owns the next snapshot refresh. Revisit only
when the recorded evidence condition is met; no automatic retry is implied.

An owner may also park a terminal `ENVIRONMENT_BLOCKED` lead after reviewing
public counterevidence or existing author-owned work. This retains the failed or
not-run attempt exactly; it does not pretend an environment was repaired, a test
executed or the bug disproved. Active, published and negative verdicts remain
ineligible for this operation.

Repeating the command with only a corrected line fragment on the same pinned
document updates that locator and retains the previous link in a bounded history.
It preserves the decision, original timestamp, reproduction evidence and costs.
A different document/revision, reason or reopening condition is not a locator
correction and is rejected; it must not be smuggled in as an idempotent repeat.

Before setting up an environment for an old lead, optionally compare its pinned
source with the current default branch:

```sh
python scripts/scout_source_freshness.py --github-auth \
  https://raw.githubusercontent.com/owner/repo/<40-char-commit>/path.py
```

The read-only helper accepts at most 32 URLs, resolves each repository's target
head once, and compares file blob identities. `--target-ref` explicitly selects
a supported release branch instead. Changed blobs need inspection; absent paths
may have moved. API failures are `INCONCLUSIVE`, never deletion evidence.
Unchanged source does not prove reachability, novelty or qualification. It makes
no model call and does not execute source or change the queue. For an inspected
removal, owner parking also accepts a same-repository immutable
`https://github.com/owner/repo/commit/<40-char-commit>` evidence URL.

After independently reviewing and publishing a candidate, link its exact ID to
the existing PR. This records publication; it does not create or verify the PR:

```sh
python scripts/kimi_scout_delivery.py --root runs/kimi-scout \
  --mark-pr-job <candidate-id> --pr-url https://github.com/owner/repo/pull/123
```

The normal path requires a matching owner-handoff artifact. If the owner instead
independently reproduced an `ENVIRONMENT_BLOCKED` or `INCONCLUSIVE` candidate in
a suitable environment, add `--owner-reproduced-after-block`. For an explicitly reviewed
legacy `REPRODUCED` entry without a handoff, use `--owner-verified-legacy` instead.
These are separate owner attestations, not automatic evidence upgrades.
Inconclusive test verdicts are preserved, not rewritten as passing Scout tests.
Prior results and reported costs remain intact; neither flag can promote an
executing candidate. Repeating the same link is idempotent, while a different repository or
replacement PR is rejected. Like parking, publication can be recorded while the
worker runs without overwriting its snapshots. It makes no model/network/GPU
calls and implies no CI, maintainer approval or merge.
The owner queue groups only byte-identical patch files within one repository:
the displayed entry lists duplicate job IDs found in its bounded scan. Every
original job and its evidence stays in SQLite. The raw owner-ready count is
not a count of distinct fixes, and exact bytes cannot detect semantic duplicates.
Source and result artifacts are preserved in ignored `delivery/jobs/`; a separate
small SQLite table records terminal outcomes without rewriting discovery history.

Fresh research packets also carry bounded, read-only `owner_publications` hints
from this inbox's existing PR links. Same-file entries are shown first, with at
most three distinct links from the latest 24 published candidate records per
repository. The summaries are prior untrusted hypotheses, not fetched PR titles
or proof that a new bug is covered. Inspect the linked PR and actual callers;
never reject a candidate just because it shares a file. Missing/busy/malformed
local data is optional, and the memory is dropped before primary evidence would
be clipped. New publication records alone do not replay identical source jobs.
Existing packets are unchanged. This reduces repeated context acquisition in
principle; the implementation tests do not establish improved yield or recall.

An owner can also record a source-only contribution that never entered delivery
in `<root>/owner-publication-notes.json`. This optional list accepts at most 24
objects with exactly `repo`, `prior_hypothesis` (<=200 characters), `source_url`
(same repository, raw.githubusercontent.com with a full commit SHA), and `pr_url`
(canonical same-repository GitHub PR URL). These links join the same three-item
advisory hint budget and are deduplicated with delivery links. They do not create
delivery rows, change old verdicts, imply successful tests or CI, or increase the
delivery conversion count. Keep local artifact paths and extra status fields out
of notes. Missing/corrupt notes are ignored; a corrupt delivery DB does not erase
independent valid owner links. No network or model call is made to read them.

New packets can also carry at most two `owner_deferrals` for the same source
file, read from the latest 24 owner-parked records per repository. Each includes
the old hypothesis, pinned public evidence, reason and explicit reopening
condition. Notes are capped and marked when clipped; raw test logs are not read.
Notes containing recognizable task-local artifact paths are omitted before
export, without editing the original records. Pinned public repository paths
remain eligible. This narrow guard is not a complete privacy/secret detector.
This is advisory history, **not a no-bug verdict or a rejection filter**. New
callers, contracts and distinct defects can overturn an earlier deferral. It
adds no network/model calls, does not replay seen source, and is dropped before
publication hints or primary source need clipping. Tests verify plumbing and
resource bounds, not fewer misses, higher PR conversion or model accuracy.

For owner-reviewed source leads that never entered delivery, an optional
`<root>/owner-source-notes.json` list can supply the same advisory history without
creating a fake execution row. Keep at most 24 notes / 64 KiB total, oldest first.
Each note has exactly `repo`, `prior_hypothesis` (<=200 characters), `source_url`
(same-repository raw URL at a 40-hex commit), `reason`, `reopen_when` (<=1000
characters each), and `evidence_url` (same-repository pinned blob/commit URL).
Existing same-file, privacy, deduplication and two-note display caps still apply.
Unknown fields, symlinks, oversized/malformed history and unrelated notes are
ignored. No raw logs, automatic job suppression, retries, or quality promotion.
Notes are read for newly admitted packets; changing a note alone buys no call.

Interrupted attempts are not retried. STOP and uncertain container cleanup block
new execution stages; repeated failures cool down admissions.

The dashboard shows discovery and delivery capacities separately. Divide the
desired model-call ceiling between the two processes (for example 8 + 8), while
keeping CPU container concurrency at 1 or 2. Do not increase search to fill idle
slots when the available evidence or compatible verification work is exhausted.
For an offline read-only cost and outcome snapshot, run
`python scripts/kimi_scout_funnel.py --root runs/kimi-scout`. It separates
research jobs, terminal review leaves, reported model tokens, delivery outcomes
and the most common environment blockers by repository. A review leaf is still
an unvalidated hypothesis. The report deliberately leaves linked PR count null:
the inbox does not have an audited lead-to-PR identity, so it cannot claim a PR
conversion rate. Use this snapshot before widening a frontier or increasing
model concurrency.
`--max-jobs N` is a bounded admission trial; zero continues on unseen leads. This
is separately authorized paid model usage, not free work merely because slots
are empty. On resume, explicitly archive the delivery STOP marker; keep the DB
and completed/failed artifacts so old candidates are not silently replayed.

Delivery supports up to 16 slots, but this is a ceiling, not a useful-work target.
Vacant workers immediately replenish a depleted queue; only a genuinely exhausted
frontier backs off. For example, use 4 discovery + 12 delivery to keep the same
16-call ceiling. The viewer shows both the total and each stage separately.

`--gpu-proposals` additionally prepares small Torch/Triton GPU tests from compatible
source or CPU attempts that require CUDA. These end as `GPU_REVIEW_REQUIRED`, with
fixed-name candidate/test files and hashes; they **do not run GPU code, connect to
a host, install packages or grant approval**. Availability of an idle GPU does not
resolve missing package context, a different architecture, or non-Python sources.
Adding `--route-blocked-gpu` explicitly routes up to 24 old CPU/CUDA blockers once,
preserving their old terminal records. It does not repeat CPU execution or retry
GPU execution. Malformed proposals get at most one format repair, then become
inconclusive; they do not trigger a provider-outage cooldown. A saved successful
model response is reused rather than regenerated for that one repair.

The explicit GPU verifier is for owner-reviewed source and tests only. On shared
hosts without a container sandbox, never feed arbitrary unreviewed model output
to that verifier. Inspect code, use an idle exact UUID, and keep each comparison
task-private. This is adapted GPU correctness evidence, not an official repository
suite, performance qualification, or a ready PR.

After reviewing all three files, bind their SHA256 values in a JSON object with
exactly `baseline`, `candidate`, and `test` keys. On the chosen Linux worker, use
the existing compatible Torch interpreter:

```sh
python -B scripts/kimi_scout_gpu_verify.py \
  --baseline baseline.py --candidate candidate.py --test test_subject.py \
  --gpu-uuid GPU-<full-device-uuid> --reviewed-sha256 reviewed.json \
  > gpu-result.json
```

This explicit tool checks the reviewed bytes, coordinates through the existing
per-UUID flock directory, samples idleness before and after each arm, and uses
separate processes with private caches and a 30-second arm timeout. It drops root
privileges for test children and terminates only their own process groups. These
are accident-limiting controls, **not network/filesystem isolation**; code review
is still required. CLI success means a comparison completed, not that a bug or PR
has been qualified. Keep the raw result and inspect both arms' tests and cleanup.

For bounded context-acquisition trials, a repository spec may set
`"followup_import_context": true` (default false). A follow-up's `next_check`
can then select named relative imports from the already cached, pinned primary
source. Only unique members of that same observed tree qualify; .js-to-.ts and
aliases are lookup hints, not proof of runtime resolution or caller reachability.
Supported syntax is module-level relative Python imports and a conservative
JS/TS import prefix. Bare packages, wildcards, missing/oversized cache entries,
ambiguous targets and revision drift retain the ordinary search.

Explicitly requested same-file free functions can also select a definition
window from that cache. Python uses module-level AST ownership; JS/TS uses
lexical function-declaration hints, not a complete language parser. Methods,
duplicate declarations and competing imported/local names abstain. Already
supplied definition windows are not fetched again. Missing context does not
prove a defect, and selecting a declaration does not resolve every caller.

Issue/source hints also associate bounded CamelCase class prefixes with compound
snake-case module names already present in the pinned tree. Literal paths and
filenames rank first. A single exact observed class can anchor a source window
past long issue headers; qualified methods keep precedence. This is a naming
heuristic, not a symbol index, and adds no reads or packet budget. Ambiguous
classes retain lexical selection; inspect the delivered window before testing.

This substitutes at most two definition reads for existing lexical/test reads.
Import lookup does not fetch or fill the primary cache; selected definitions use
the ordinary bounded source-acquisition path. It adds no model call, execution
or publication authority.
Missing-context decisions prefer definitions; retained lead decisions keep a
companion test plus at most one definition. Generated-kernel contract acquisition
is unchanged. This does not find reverse callers or establish a bug from imports.
Keep the trial opt-in until fresh, budget-matched outcomes justify promotion;
offline tests establish acquisition boundaries, not improved PR yield or savings.

Repositories that route bug reports through GitHub Discussions may separately
opt into `"followup_discussion_context": true` (default false). A follow-up then
performs one repository-scoped Discussion search using a bounded lexical title
anchor, retaining at most three reports and three comments per report. It uses
the controller's configured GitHub auth only after verifying public repository
visibility, rejects cross-repository results, and caches results for 15 minutes.
API/auth failures are retrieval failures, not proof that no prior work exists.
Discussion text remains untrusted evidence and cannot publish or reject a lead.
An author already offering a tested fix should receive missing validation, not
a competing PR. Narrow search and clipping are non-exhaustive; owner publication
review still checks the actual discussion, issue and PR history. This opt-in
adds no model call, executable code or new delivery qualification rule.

The HTTPX multipart example is a development counterexample: issue/PR-only
search missed [HTTPX Discussion #3789](https://github.com/encode/httpx/discussions/3789),
whose author already had the same tested fix.
Native reproduction confirmed the bug but did not make it novel. This motivates
the acquisition option; it does not prove improved conversion or token savings.

Offline checks (no network, credentials, or paid model calls):

```sh
python -B tests/test_kimi_scout.py
python -B tests/test_kimi_scout_verify.py
python -B tests/test_scout_import_context.py
python -B tests/test_scout_import_followup.py
python -B tests/test_scout_discussion_context.py
<kimi-python> -I -B -X utf8 tests/test_kimi_scout_backend.py
```

Implementation references: [Kimi CLI](https://github.com/MoonshotAI/kimi-cli),
[custom-agent/tool behavior](https://moonshotai.github.io/kimi-cli/en/customization/agents.html).
The version-pinned backend is intentionally separate from the ordinary CLI:
print mode auto-approves tools, which is inappropriate for an unattended scout.

### Explicit cached reference context

For missing C-family/Python/JavaScript/TypeScript symbol uses, a `next_check` can ask
`references(exact_identifier)` (at most two identifiers). The controller uses
only an existing bounded source cache at the same immutable commit and
an observed tree path. It replaces the ordinary follow-up reads with at most
two 80-line windows around the first and last unseen code matches. No extra
model call, cache-fill step, source execution or source-read budget is added.
Explicit line continuations and Python kernel-definition requests keep priority.

The primary source is the default. An explicitly named already supplied file
may select a secondary source; ambiguous basenames abstain. Python AST loads and
attributes exclude definitions and literal/comment text, without executing code.
JS/TS lexical masking omits comments, strings and simple template interpolations.
Unsupported slash/template syntax stops the scan: only earlier complete lines
can supply references, with windows clamped to the scanned prefix. Returned
`reference_scan` metadata marks this evidence incomplete and records its last
scanned line. Matches on the unsupported line or later are not admitted. A
complete scan keeps the existing request shape; neither case resolves bindings.

This is lexical context, not a parser, exhaustive use list or reachability proof.
Ordinary comments, strings and preprocessor directives are excluded; local
declarations and inactive conditional branches may remain. C++ raw strings,
missing cache/symbols, drift or unsupported paths leave the old selection intact.
Macros, aliases and numeric lowering are not resolved: an offset macro can have
no references while actual pointer operands use an expanded number. Request the
actual variable when the supplied source exposes it. Do not infer unused/safe
code from abstention, nor a race from equal offsets alone.

Offline regression: `python -B -m unittest tests.test_scout_symbol_references`.
The development CUDA example motivates the helper; it does not measure PR yield,
false-positive rate, generalization or paid-token savings.

### Issue comment recency

Issue follow-ups use the last three-comment page implied by the issue's observed
comment count instead of always reading page one. The existing single comment
GET (300 kB cap) and three 1,200-character comment excerpts are unchanged.
This can expose later maintainer decisions or implementation ownership without
adding another retrieval tier or treating either as automatic authorization.

The sample is partial: a final page may contain only one or two comments,
older relevant replies can be omitted, and comment deletion/count drift can make
the selected page stale or empty. Selection/page and truncation are explicit.
Do not infer that no owner or fix exists from a missing comment; confirm public
state before implementing or publishing. Offline boundary coverage is in
`tests/test_kimi_scout_context.py`; development observations are not evidence of
a measured false-positive reduction or PR-conversion improvement.
