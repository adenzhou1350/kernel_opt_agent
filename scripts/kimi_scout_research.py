"""Durable public-evidence frontier, not an autonomous code-executing agent.

One controller producer supplies fresh evidence to the existing bounded workers.
No model-produced URL, command, or local path is ever executed or fetched.
"""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
import re
import threading
import time

import kimi_scout as scout
from kimi_scout_context import PublicContext

SOURCE_SUFFIXES = (
    ".py",
    ".cu",
    ".cuh",
    ".cpp",
    ".h",
    ".hpp",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
)


class QueueFull(Exception):
    """Defer a fetched packet without advancing its evidence cursor."""


def configuration(path):
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("objective"), str):
        raise ValueError("research configuration needs an objective")
    if (
        type(value.get("queue_target")) is not int
        or not 4 <= value["queue_target"] <= 128
    ):
        raise ValueError("research queue_target must be 4..128")
    context_workers = value.setdefault("context_workers", 1)
    if type(context_workers) is not int or not 1 <= context_workers <= 16:
        raise ValueError("research context_workers must be 1..16")
    source_windows = value.setdefault("source_windows", 3)
    if type(source_windows) is not int or not 1 <= source_windows <= 12:
        raise ValueError("research source_windows must be 1..12")
    refill_batch = value.setdefault("refill_batch", 4)
    if type(refill_batch) is not int or not 1 <= refill_batch <= 16:
        raise ValueError("research refill_batch must be 1..16")
    repos = value.get("repos")
    if not isinstance(repos, list) or not 1 <= len(repos) <= 24:
        raise ValueError("research needs 1..24 explicit public repositories")
    names = set()
    for spec in repos:
        repo = scout.public_repo(spec["repo"])
        if repo in names:
            raise ValueError("duplicate research repository")
        names.add(repo)
        prefixes = spec.get("source_prefixes")
        if (
            not isinstance(prefixes, list)
            or not prefixes
            or not all(
                isinstance(p, str)
                and p
                and not p.startswith(("/", "\\"))
                and ".." not in p.split("/")
                and "\\" not in p
                and ":" not in p
                for p in prefixes
            )
        ):
            raise ValueError("research needs safe explicit source prefixes")
        if not isinstance(spec.get("question"), str):
            raise ValueError("research repository needs a question")
        roots = spec.get("tree_roots", [])
        if (
            not isinstance(roots, list)
            or len(roots) > 8
            or any(
                not isinstance(r, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", r)
                for r in roots
            )
        ):
            raise ValueError("tree_roots needs safe top-level directories")
        if roots and any(p.split("/")[0] not in roots for p in prefixes):
            raise ValueError("source prefixes must lie in configured tree roots")
    return value


def source_paths(snapshot, spec):
    return sorted(
        p
        for p in snapshot["files"]
        if any(p.startswith(prefix) for prefix in spec["source_prefixes"])
        and p.endswith(SOURCE_SUFFIXES)
        and not p.endswith("__init__.py")
        and not re.search(r"(?:^|/)(?:generated|third_party|vendor)/|_hdim\d+_", p)
    )


def relevant_paths(snapshot, hints, exclude=()):
    """Rank *observed tree members*; never interpret hints as a fetch target."""
    hints = hints.lower()[:16000]
    words = set(re.findall(r"[a-z][a-z0-9_]{3,}", hints))
    ranked = []
    for path in snapshot["files"]:
        if path in exclude or not path.endswith(SOURCE_SUFFIXES):
            continue
        name = path.rsplit("/", 1)[-1].lower()
        stem = name.rsplit(".", 1)[0]
        exact_path = path.lower() in hints
        if (
            stem in {"__init__", "utils", "test", "common", "setup", "kernel"}
            and not exact_path
        ):
            continue
        score = 100 if exact_path else 50 if name in hints else 0
        if len(stem) >= 5 and stem in words:
            score += 10
        if score:
            ranked.append((-score, path))
    return [path for _, path in sorted(ranked)]


def distinct_sources(sources):
    """Keep distinct code windows, but prefer full issue context over search snippets."""
    unique = {}
    for source in sources:
        url = source["url"]
        key = (
            url,
            source["text"]
            if url.startswith("https://raw.githubusercontent.com/")
            else None,
        )
        unique.setdefault(key, dict(source))
    return list(unique.values())


def evidence_identity(source):
    return re.sub(r"/[0-9a-f]{40}/", "/REV/", source["url"]), source["text"]


def retrieval_identity(source):
    # This controller metadata only prevents budget trimming from looking like
    # fresh retrieval. Quotes remain limited to the delivered text.
    digest = source.get("_scout_pretrim_sha256")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        digest = hashlib.sha256(source["text"].encode("utf-8")).hexdigest()
    return evidence_identity(source)[0], digest


class ResearchProducer:
    def __init__(self, root, config_path, github_auth=False, context=None):
        self.root = Path(root)
        self.config = configuration(config_path)
        self.context = context or PublicContext(
            root,
            github_auth,
            tree_roots={
                s["repo"]: s["tree_roots"]
                for s in self.config["repos"]
                if s.get("tree_roots")
            },
        )
        self.halt = threading.Event()
        self.thread = None
        self.lock = threading.RLock()
        self.inflight_repos = set()
        with scout.connect(root) as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS research_seen (key TEXT PRIMARY KEY, job TEXT)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS research_meta (key TEXT PRIMARY KEY, value TEXT)"
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS research_jobs_repo_finished "
                "ON jobs(json_extract(packet,'$.repo'),finished DESC) "
                "WHERE state IN ('REVIEW','NEEDS_CONTEXT')"
            )
            row = db.execute(
                "SELECT value FROM research_meta WHERE key='frontier'"
            ).fetchone()
        self.state = (
            json.loads(row[0])
            if row
            else {
                "turn": 0,
                "repos": {},
                "followups_created": 0,
                "discovery_created": 0,
            }
        )
        self.lessons = scout.reviewed_lessons()

    def stopped(self):
        return self.halt.is_set() or (self.root / "STOP").exists()

    def pending(self):
        with scout.connect(self.root) as db:
            return db.execute(
                "SELECT count(*) FROM jobs WHERE state='PENDING'"
            ).fetchone()[0]

    def seen(self, key):
        with scout.connect(self.root) as db:
            return (
                db.execute("SELECT 1 FROM research_seen WHERE key=?", (key,)).fetchone()
                is not None
            )

    def remember(self, key, job=None):
        with scout.connect(self.root) as db:
            db.execute("INSERT OR IGNORE INTO research_seen VALUES (?,?)", (key, job))

    def save(self):
        with self.lock, scout.connect(self.root) as db:
            db.execute(
                "INSERT OR REPLACE INTO research_meta VALUES ('frontier',?)",
                (scout.dumps(self.state),),
            )

    def publish(self, phase, error=None, next_scan=None):
        with self.lock:
            try:
                self._publish(phase, error, next_scan)
            except PermissionError:
                # Dashboard telemetry is recoverable; a Windows reader can
                # briefly block replacement even after bounded write retries.
                # The next loop refreshes it without discarding frontier work.
                pass

    def _publish(self, phase, error, next_scan):
        goals = [
            {
                "repo": spec["repo"],
                **{
                    k: self.state["repos"].get(spec["repo"], {}).get(k, 0)
                    for k in ("scanned_sources", "available_sources", "issue_page")
                },
            }
            for spec in self.config["repos"]
        ]
        scout.write_json(
            self.root / "research.json",
            {
                "enabled": True,
                "objective": self.config["objective"],
                "phase": phase,
                "updated_at": time.time(),
                "queue_target": self.config["queue_target"],
                "context_workers": self.config["context_workers"],
                "source_windows": self.config["source_windows"],
                "refill_batch": self.config["refill_batch"],
                "context_inflight": len(self.inflight_repos),
                "queued": self.pending(),
                "goals": goals,
                "followups_created": self.state["followups_created"],
                "discovery_created": self.state["discovery_created"],
                "scanned_sources": sum(g["scanned_sources"] for g in goals),
                "next_scan_at": next_scan,
                "last_error": error,
            },
        )

    def emit(
        self, key, spec, sources, stage, *, parent=None, focus_issue=None, question=""
    ):
        if self.stopped() or self.seen(key):
            return False
        sources = distinct_sources(sources)
        # Timestamp-only updates and changes outside the delivered source window
        # are not fresh evidence. Do not let job names/blob identities defeat dedup.
        fingerprint = hashlib.sha256(
            scout.dumps(
                {
                    "repo": spec["repo"],
                    "stage": stage,
                    "sources": sorted(evidence_identity(s) for s in sources),
                }
            ).encode()
        ).hexdigest()
        evidence_key = "evidence:" + fingerprint
        if self.seen(evidence_key):
            self.remember(key)
            return False
        packet = {
            "name": f"{spec['repo']}:{stage}:{fingerprint[:12]}",
            "repo": spec["repo"],
            "question": spec["question"] + "\n" + question,
            "sources": sources,
            "reviewed_lessons": self.lessons,
            "research": {
                "stage": stage,
                "parent_job_id": parent["id"] if parent else None,
                "root_job_id": parent["root"] if parent else None,
                "depth": parent["depth"] + 1 if parent else 0,
                "objective": self.config["objective"],
            },
            "evidence_scope": "Partial public-source evidence, not exhaustive review or proof of novelty. Do not invent results.",
        }
        if focus_issue:
            packet["focus_issue"] = focus_issue
        if parent:
            packet["untrusted_prior_analysis"] = parent["analysis"][:2500]
        # Keep every supplied URL and source type but shrink explicitly, within the existing cap.
        while (
            len((scout.SYSTEM + scout.dumps(packet)).encode("utf-8"))
            > scout.MAX_INPUT_BYTES
        ):
            # Related-work search snippets are peripheral to the code contract;
            # shrink those first so fresh same-file windows reach the reviewer.
            peripheral = [
                s
                for s in packet["sources"]
                if s.get("search_exhaustive") is False and len(s["text"]) >= 300
            ]
            longest = max(
                peripheral or packet["sources"],
                key=lambda x: len(x["text"].encode("utf-8")),
            )
            if len(longest["text"]) < 300:
                raise ValueError("research packet cannot fit evidence budget")
            longest.setdefault(
                "_scout_pretrim_sha256",
                hashlib.sha256(longest["text"].encode("utf-8")).hexdigest(),
            )
            longest["text"] = longest["text"][: int(len(longest["text"]) * 0.75)]
            longest["truncated"] = True
        if not packet["sources"] or self.stopped():
            return False
        # Queue admission, job insertion and both dedup keys commit together.
        # Different repository fetches never hold this lock across network I/O.
        with self.lock:
            with scout.connect(self.root) as db:
                db.execute("BEGIN IMMEDIATE")
                if (
                    self.stopped()
                    or db.execute(
                        "SELECT 1 FROM research_seen WHERE key=?", (key,)
                    ).fetchone()
                ):
                    return False
                if db.execute(
                    "SELECT 1 FROM research_seen WHERE key=?", (evidence_key,)
                ).fetchone():
                    db.execute(
                        "INSERT OR IGNORE INTO research_seen VALUES (?,NULL)", (key,)
                    )
                    return False
                queued = db.execute(
                    "SELECT count(*) FROM jobs WHERE state='PENDING'"
                ).fetchone()[0]
                if queued >= self.config["queue_target"]:
                    raise QueueFull
                job = scout.enqueue(self.root, packet, db=db)
                db.executemany(
                    "INSERT OR IGNORE INTO research_seen VALUES (?,?)",
                    ((key, job), (evidence_key, job)),
                )
            self.state["followups_created" if parent else "discovery_created"] += 1
        return True

    def snapshot(self, spec, progress):
        snapshot = self.context.snapshot(
            spec["repo"], progress.get("commit") or spec.get("ref", "main")
        )
        progress["commit"] = snapshot["commit"]
        return snapshot

    def issue(self, spec, progress):
        if time.time() < progress.get("issues_after", 0):
            return False
        items = progress.setdefault("issues", [])
        if not items:
            page = progress.get("issue_page", 0) + 1
            if page > 10:
                progress.update(issue_page=0, issues_after=time.time() + 1800)
                return False
            items = self.context.issue_page(spec["repo"], page)
            progress["issue_page"] = page
            progress["issues"] = items
            if not items:
                # The API mixes PRs with issues. A filtered PR-only page is not
                # EOF: keep the cursor so the next refill reads the next page.
                if getattr(items, "exhausted", True):
                    progress.update(issue_page=0, issues_after=time.time() + 1800)
                return False
        for _ in range(min(len(items), 30)):
            if self.stopped():
                return False
            item = items[0]
            key = f"issue:{spec['repo']}:{item['number']}:{item.get('updated_at', '')}"
            if self.seen(key):
                items.pop(0)
                continue
            sources = [
                scout.evidence(
                    item["html_url"],
                    item["title"] + "\n" + (item.get("body") or ""),
                    5000,
                )
            ]
            snapshot = self.snapshot(spec, progress)
            if self.stopped():
                return False
            matches = relevant_paths(snapshot, sources[0]["text"])
            if matches:
                sources.append(
                    self.context.source(
                        spec["repo"],
                        snapshot["commit"],
                        matches[0],
                        hints=sources[0]["text"],
                    )
                )
            created = self.emit(
                key,
                spec,
                sources,
                "issue_triage",
                focus_issue=item["number"],
                question="First triage: distinguish an actionable current-source question from stale/resolved/user-configuration reports. Name exact missing source symbols if needed.",
            )
            items.pop(0)
            return created
        return False

    def source_audit(self, spec, progress):
        windows = self.config["source_windows"]
        previous_windows = progress.get("source_windows", 3)
        if previous_windows != windows:
            cursor = progress.get("source_cursor", 0)
            path_index, window_index = divmod(cursor, previous_windows)
            progress["source_cursor"] = path_index * windows + min(
                window_index, windows - 1
            )
            progress.pop("sources_after", None)
        progress["source_windows"] = windows
        if time.time() < progress.get("sources_after", 0):
            return False
        snapshot = self.snapshot(spec, progress)
        paths = source_paths(snapshot, spec)
        progress["available_sources"] = len(paths)
        for _ in range(40):
            if self.stopped():
                return False
            cursor = progress.get("source_cursor", 0)
            if cursor >= len(paths) * windows:
                progress.update(source_cursor=0, sources_after=time.time() + 1800)
                progress.pop(
                    "commit", None
                )  # Refresh revision only after this bounded sweep.
                return False
            path, window = paths[cursor // windows], cursor % windows
            start = 1 + window * 120
            key = f"source:{spec['repo']}:{path}:{snapshot['blobs'][path]}:{start}"
            if self.seen(key):
                progress["source_cursor"] = cursor + 1
                continue
            try:
                source = self.context.source(
                    spec["repo"], snapshot["commit"], path, start=start
                )
            except ValueError as exc:
                if str(exc) not in {
                    "binary source is not supported",
                    "source exceeds read budget",
                    "public source exceeds read budget",
                    "source start line is beyond end of file",
                }:
                    raise
                self.remember(key)
                progress["source_cursor"] = (cursor // windows + 1) * windows
                progress["skipped_sources"] = progress.get("skipped_sources", 0) + 1
                continue
            if start > source.get("total_lines", 0):
                self.remember(key)
                progress["source_cursor"] = (cursor // windows + 1) * windows
                continue
            sources = [source]
            if self.stopped():
                return False
            stem = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
            tests = [
                p
                for p in snapshot["files"]
                if p != path
                and "test" in p
                and stem in p
                and p.endswith(SOURCE_SUFFIXES)
            ]
            if tests:
                sources.append(
                    self.context.source(
                        spec["repo"], snapshot["commit"], tests[0], hints=stem
                    )
                )
            created = self.emit(
                key,
                spec,
                sources,
                "source_audit",
                question=(
                    f"Review only this supplied source window ({path}:{start}) and any supplied tests. "
                    "Find at most one concrete boundary/correctness/production-impact gap. Missing surrounding code is uncertainty, not a bug. Prefer no_lead to speculative refactoring. Do not call it novel; later stages check related work."
                ),
            )
            progress["source_cursor"] = (
                (cursor // windows + 1) * windows
                if start + 120 > source.get("total_lines", 0)
                else cursor + 1
            )
            progress["scanned_sources"] = progress.get("scanned_sources", 0) + int(
                created
            )
            return created
        return False

    def followup(self, spec, progress):
        with scout.connect(self.root) as db:
            rows = list(
                db.execute(
                    """SELECT j.id,j.packet,j.result FROM jobs AS j
                    WHERE j.state IN ('REVIEW','NEEDS_CONTEXT')
                      AND json_extract(j.packet,'$.repo')=?
                      AND COALESCE(json_extract(j.packet,'$.research.depth'),0)<2
                      AND NOT EXISTS (
                        SELECT 1 FROM research_seen AS s WHERE s.key =
                          'followup:' || CASE
                            WHEN json_extract(j.packet,'$.focus_issue') THEN
                              'issue:' || json_extract(j.packet,'$.repo') || ':' ||
                              json_extract(j.packet,'$.focus_issue')
                            ELSE COALESCE(
                              NULLIF(json_extract(j.packet,'$.research.root_job_id'),''),
                              j.id)
                            END || ':' ||
                            (COALESCE(json_extract(j.packet,'$.research.depth'),0)+1)
                      )
                    ORDER BY j.finished DESC LIMIT 1500""",
                    (spec["repo"],),
                )
            )
        for row in rows:
            if self.stopped():
                return False
            packet = json.loads(row["packet"])
            if packet.get("repo") != spec["repo"]:
                continue
            research = packet.get("research", {})
            depth = research.get("depth", 0)
            if depth >= 2:
                continue  # Handoff to the owner, never a self-replicating model chain.
            root = research.get("root_job_id") or row["id"]
            number = packet.get("focus_issue")
            if not number:
                matches = {
                    int(m.group(1))
                    for s in packet["sources"]
                    if (
                        m := re.fullmatch(
                            r"https://github\.com/"
                            + re.escape(spec["repo"])
                            + r"/issues/(\d+)",
                            s["url"],
                        )
                    )
                }
                if len(matches) == 1:
                    number = matches.pop()
                elif not research:
                    continue  # Legacy multi-report integration trials are not candidate chains.
            chain = f"issue:{spec['repo']}:{number}" if number else root
            key = f"followup:{chain}:{depth + 1}"
            if self.seen(key):
                continue
            analysis_value = json.loads(row["result"])["analysis"]
            analysis = scout.dumps(analysis_value)
            snapshot = self.snapshot(spec, progress)
            if self.stopped():
                return False
            sources = (
                self.context.issue_sources(spec["repo"], number)
                if number
                else list(packet["sources"][:1])
            )
            hints = "\n".join(
                [
                    analysis_value.get(field, "")
                    for field in ("next_check", "hypothesis", "title")
                ]
                + [ref["quote"] for ref in analysis_value.get("evidence", [])]
                + [s["url"] + "\n" + s["text"] for s in sources]
            )
            paths = relevant_paths(snapshot, hints)
            for path in paths[:2]:
                if self.stopped():
                    return False
                sources.append(
                    self.context.source(
                        spec["repo"], snapshot["commit"], path, hints=hints
                    )
                )
            if self.stopped():
                return False
            title = (
                sources[0]["text"].splitlines()[0]
                if number
                else json.loads(row["result"])["analysis"]["title"]
            )
            sources.extend(self.context.duplicate_sources(spec["repo"], title))
            sources = distinct_sources(sources)
            old_evidence = {retrieval_identity(s) for s in packet["sources"]}
            if not any(retrieval_identity(s) not in old_evidence for s in sources):
                self.remember(
                    key
                )  # No new evidence: never pay just to rephrase an answer.
                continue
            stage = "source_followup" if depth == 0 else "reproduction_plan"
            return self.emit(
                key,
                spec,
                sources,
                stage,
                focus_issue=number,
                parent={
                    "id": row["id"],
                    "root": root,
                    "depth": depth,
                    "analysis": analysis,
                },
                question=(
                    (
                        "Role: skeptical reviewer, not the original proposer. Check caller preconditions, "
                        "tests, reachability and existing fixes; missing context is not a defect. "
                        if depth == 0
                        else "Role: reproduction planner. Retain only a still-supported hypothesis; "
                        "give a minimal regression test plan, dependencies and expected before/after assertions. "
                    )
                    + "Try to disprove the prior untrusted hypothesis using new source and related items. "
                    "If already fixed or covered by an existing PR, say no_lead; do not propose a competing copy. "
                    "Give one minimal runnable test PLAN (not a claim of execution), exact source location, expected boundary, and stop condition. "
                    "This chain has at most two followups; remaining environment/GPU questions must be handed to the owner."
                ),
            )
        return False

    def tick(self):
        """At most one new packet per tick; FIFO workers run independently."""
        if self.stopped() or self.pending() >= self.config["queue_target"]:
            return False
        spec, progress, first = self.next_refill()
        try:
            return self.refill(spec, progress, first)
        finally:
            with self.lock:
                self.state["repos"][spec["repo"]] = progress
                self.save()

    def next_refill(self, exclude=()):
        """Coordinator-only selection; workers own isolated progress copies."""
        repos = self.config["repos"]
        with self.lock:
            for _ in repos:
                turn = self.state["turn"]
                self.state["turn"] += 1
                spec = repos[turn % len(repos)]
                if spec["repo"] not in exclude:
                    return (
                        spec,
                        deepcopy(self.state["repos"].get(spec["repo"], {})),
                        (turn // len(repos)) % 3,
                    )
        return None

    def refill(self, spec, progress, first, batch_size=1):
        methods = (self.followup, self.issue, self.source_audit)
        # Context retrieval is much slower than model consumption. Refill a
        # bounded batch from each already-open repository frontier instead of
        # paying that latency again for every single queued job. A complete
        # dry rotation still stops immediately, and emit() remains the atomic
        # queue-target guard while other repository refills run concurrently.
        made = 0
        dry = 0
        cursor = first
        try:
            while (
                made < batch_size
                and not self.stopped()
                and self.pending() < self.config["queue_target"]
            ):
                created = methods[cursor % len(methods)](spec, progress)
                cursor += 1
                if created:
                    made += 1
                    dry = 0
                else:
                    dry += 1
                    if dry >= len(methods):
                        break
            return made > 0
        except QueueFull:
            return made > 0

    def finish_refill(self, repo, future, progress):
        """Only the coordinator merges worker state and persists the frontier."""
        try:
            return future.result(), None
        except Exception as exc:
            return False, type(exc).__name__
        finally:
            with self.lock:
                self.state["repos"][repo] = progress
                self.inflight_repos.discard(repo)
                self.save()

    def parallel_loop(self):
        active, ready_at = {}, {}
        pool = ThreadPoolExecutor(
            max_workers=self.config["context_workers"],
            thread_name_prefix="public-research-context",
        )
        try:
            while not self.stopped():
                error = None
                for repo, (future, progress) in list(active.items()):
                    if not future.done():
                        continue
                    made, failure = self.finish_refill(repo, future, progress)
                    del active[repo]
                    ready_at[repo] = time.monotonic() + (
                        60 if failure else 0.2 if made else 5
                    )
                    error = failure or error
                while (
                    not self.stopped()
                    and len(active) < self.config["context_workers"]
                    and self.pending() < self.config["queue_target"]
                ):
                    excluded = set(active) | {
                        repo
                        for repo, deadline in ready_at.items()
                        if deadline > time.monotonic()
                    }
                    work = self.next_refill(excluded)
                    if work is None:
                        break
                    spec, progress, first = work
                    repo = spec["repo"]
                    # One refill per repository keeps its cache writes disjoint
                    # from other workers, including shared .tmp cache filenames.
                    with self.lock:
                        self.inflight_repos.add(repo)
                    active[repo] = (
                        pool.submit(
                            self.refill,
                            spec,
                            progress,
                            first,
                            self.config["refill_batch"],
                        ),
                        progress,
                    )
                queued = self.pending()
                phase = (
                    "BACKOFF"
                    if error
                    else "REFILLING"
                    if active
                    else "READY"
                    if queued >= self.config["queue_target"]
                    else "WAITING_FOR_NEW_EVIDENCE"
                )
                delay = 0.2 if active else 5
                if not active and queued < self.config["queue_target"] and ready_at:
                    delay = min(5, max(0.01, min(ready_at.values()) - time.monotonic()))
                self.publish(
                    phase,
                    error=error,
                    next_scan=None if active else time.time() + delay,
                )
                self.halt.wait(delay)
        finally:
            # Retain the single-runner lock until every bounded public GET has
            # returned; stopped workers cannot publish a late model packet.
            pool.shutdown(wait=True)
            for repo, (future, progress) in active.items():
                self.finish_refill(repo, future, progress)
            self.save()
            self.publish("STOPPED")

    def loop(self):
        if self.config["context_workers"] > 1:
            self.parallel_loop()
            return
        while not self.stopped():
            try:
                if self.pending() >= self.config["queue_target"]:
                    self.publish("READY")
                    self.halt.wait(5)
                    continue
                self.publish("REFILLING")
                made = self.tick()
                self.publish(
                    "REFILLING" if made else "WAITING_FOR_NEW_EVIDENCE",
                    next_scan=None if made else time.time() + 5,
                )
                self.halt.wait(0.2 if made else 5)
            except Exception as exc:
                # Only exception class is public: URLs/body/credential errors stay private.
                self.publish(
                    "BACKOFF", error=type(exc).__name__, next_scan=time.time() + 60
                )
                self.halt.wait(60)
        self.publish("STOPPED")

    def start(self):
        self.thread = threading.Thread(
            target=self.loop, name="public-research-producer", daemon=True
        )
        self.thread.start()

    def stop(self):
        self.halt.set()
        if self.thread:
            # Keep single_runner locked until the bounded in-flight GET returns;
            # never allow an old producer to overlap a restarted daemon.
            self.thread.join()
