"""Durable public-evidence frontier, not an autonomous code-executing agent.

One controller producer supplies fresh evidence to the existing bounded workers.
No model-produced URL, command, or local path is ever executed or fetched.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import threading
import time

import kimi_scout as scout
from kimi_scout_context import PublicContext


def configuration(path):
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("objective"), str):
        raise ValueError("research configuration needs an objective")
    if (
        type(value.get("queue_target")) is not int
        or not 4 <= value["queue_target"] <= 64
    ):
        raise ValueError("research queue_target must be 4..64")
    repos = value.get("repos")
    if not isinstance(repos, list) or not 1 <= len(repos) <= 8:
        raise ValueError("research needs 1..8 explicit public repositories")
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
    return value


def source_paths(snapshot, spec):
    return sorted(
        p
        for p in snapshot["files"]
        if any(p.startswith(prefix) for prefix in spec["source_prefixes"])
        and p.endswith((".py", ".cu", ".cuh", ".cpp", ".h", ".hpp"))
        and not p.endswith("__init__.py")
        and not re.search(r"(?:^|/)(?:generated|third_party|vendor)/|_hdim\d+_", p)
    )


def relevant_paths(snapshot, hints, exclude=()):
    """Rank *observed tree members*; never interpret hints as a fetch target."""
    hints = hints.lower()[:16000]
    words = set(re.findall(r"[a-z][a-z0-9_]{3,}", hints))
    ranked = []
    for path in snapshot["files"]:
        if path in exclude or not path.endswith(
            (".py", ".cu", ".cuh", ".cpp", ".h", ".hpp")
        ):
            continue
        name = path.rsplit("/", 1)[-1].lower()
        stem = name.rsplit(".", 1)[0]
        if stem in {"__init__", "utils", "test", "common", "setup"}:
            continue
        score = 100 if path.lower() in hints else 50 if name in hints else 0
        if len(stem) >= 5 and stem in words:
            score += 10
        if score:
            ranked.append((-score, path))
    return [path for _, path in sorted(ranked)]


class ResearchProducer:
    def __init__(self, root, config_path, github_auth=False, context=None):
        self.root = Path(root)
        self.config = configuration(config_path)
        self.context = context or PublicContext(root, github_auth)
        self.halt = threading.Event()
        self.thread = None
        with scout.connect(root) as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS research_seen (key TEXT PRIMARY KEY, job TEXT)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS research_meta (key TEXT PRIMARY KEY, value TEXT)"
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
        with scout.connect(self.root) as db:
            db.execute(
                "INSERT OR REPLACE INTO research_meta VALUES ('frontier',?)",
                (scout.dumps(self.state),),
            )

    def publish(self, phase, error=None, next_scan=None):
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
        # Exact excerpts remain quotable; deduplicate repeated URLs before budget trimming.
        unique = {}
        for item in sources:
            unique.setdefault(item["url"], dict(item))
        # Timestamp-only updates and changes outside the delivered source window
        # are not fresh evidence. Do not let job names/blob identities defeat dedup.
        fingerprint = hashlib.sha256(
            scout.dumps(
                {
                    "repo": spec["repo"],
                    "stage": stage,
                    "sources": sorted(
                        (re.sub(r"/[0-9a-f]{40}/", "/REV/", s["url"]), s["text"])
                        for s in unique.values()
                    ),
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
            "sources": list(unique.values()),
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
            longest = max(
                packet["sources"], key=lambda x: len(x["text"].encode("utf-8"))
            )
            if len(longest["text"]) < 300:
                raise ValueError("research packet cannot fit evidence budget")
            longest["text"] = longest["text"][: int(len(longest["text"]) * 0.75)]
            longest["truncated"] = True
        if not packet["sources"] or self.stopped():
            return False
        job = scout.enqueue(self.root, packet)
        self.remember(key, job)
        self.remember(evidence_key, job)
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
        if time.time() < progress.get("sources_after", 0):
            return False
        snapshot = self.snapshot(spec, progress)
        paths = source_paths(snapshot, spec)
        progress["available_sources"] = len(paths)
        for _ in range(40):
            if self.stopped():
                return False
            cursor = progress.get("source_cursor", 0)
            if cursor >= len(paths) * 3:
                progress.update(source_cursor=0, sources_after=time.time() + 1800)
                progress.pop(
                    "commit", None
                )  # Refresh revision only after this bounded sweep.
                return False
            path, window = paths[cursor // 3], cursor % 3
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
                progress["source_cursor"] = (cursor // 3 + 1) * 3
                progress["skipped_sources"] = progress.get("skipped_sources", 0) + 1
                continue
            if start > source.get("total_lines", 0):
                self.remember(key)
                progress["source_cursor"] = (cursor // 3 + 1) * 3
                continue
            sources = [source]
            stem = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
            tests = [
                p
                for p in snapshot["files"]
                if p != path and "test" in p and stem in p and p.endswith(".py")
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
                (cursor // 3 + 1) * 3
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
                    "SELECT id,packet,result FROM jobs WHERE state IN ('REVIEW','NEEDS_CONTEXT') ORDER BY finished DESC LIMIT 1500"
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
            analysis = scout.dumps(json.loads(row["result"])["analysis"])
            snapshot = self.snapshot(spec, progress)
            sources = (
                self.context.issue_sources(spec["repo"], number)
                if number
                else list(packet["sources"][:1])
            )
            hints = analysis + "\n" + "\n".join(s["text"] for s in sources)
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
            old_evidence = {(s["url"], s["text"]) for s in packet["sources"]}
            if not any((s["url"], s["text"]) not in old_evidence for s in sources):
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
                    "Try to disprove the prior untrusted hypothesis using new source and related items. "
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
        repos = self.config["repos"]
        turn = self.state["turn"]
        self.state["turn"] += 1
        spec = repos[turn % len(repos)]
        progress = self.state["repos"].setdefault(spec["repo"], {})
        methods = (self.followup, self.issue, self.source_audit)
        # Rotate both repositories and kinds, even after a provider/source error.
        first = (turn // len(repos)) % 3
        try:
            for offset in range(3):
                if self.stopped():
                    break
                if methods[(first + offset) % 3](spec, progress):
                    return True
            return False
        finally:
            self.save()

    def loop(self):
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
