"""Durable public-evidence frontier, not an autonomous code-executing agent.

One controller producer supplies fresh evidence to the existing bounded workers.
No model-produced URL, command, or local path is ever executed or fetched.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path

import kimi_scout as scout
import kimi_scout_shadow as shadow
from kimi_scout_context import PublicContext
from scout_audit_context import contextual_audit_header, contextual_audit_owners
from scout_discussion_context import discussion_sources
from scout_generated_context import contract_requests
from scout_import_context import import_requests
from scout_symbol_references import reference_requests
from scout_issue_excerpt import issue_evidence, issue_text_excerpt
from scout_lesson_context import fit_lesson_context, lesson_suggestions
from scout_publication_context import (
    fit_publication_context,
    owner_deferral_context,
    publication_context,
)

SOURCE_SUFFIXES = (
    ".py",
    ".cu",
    ".cuh",
    ".cpp",
    ".cc",
    ".c",
    ".cxx",
    ".h",
    ".hpp",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
)
OPTIONAL_SOURCE_UNAVAILABLE = frozenset(
    {
        "binary source is not supported",
        "source exceeds read budget",
        "public source exceeds read budget",
    }
)


class QueueFull(Exception):
    """Defer a fetched packet without advancing its evidence cursor."""


def refill_error_code(exc):
    """Expose only known controller error codes, never fetched text or URLs."""
    if isinstance(exc, ValueError):
        known = {
            "research packet cannot fit evidence budget": "packet_budget",
            "public source exceeds read budget": "source_budget",
            "source exceeds read budget": "source_budget",
            "source path is absent from the public snapshot": "source_snapshot",
            "configured tree root is absent": "tree_root_absent",
            "invalid public issue page": "issue_page",
            "issue response does not match requested issue": "issue_identity",
            "invalid issue comments": "issue_comments",
            "invalid public duplicate search": "duplicate_search",
        }
        return "ValueError:" + known.get(str(exc), "other")
    return type(exc).__name__


def idle_refill_delay(ready_at, now):
    """Sleep until a future retry, ignoring deadlines that already expired."""
    future = (deadline - now for deadline in ready_at.values() if deadline > now)
    return min(30, max(0.01, min(future, default=30)))


def refill_retry_delay(made, failure, empty_refills, *, cursor_advanced=False):
    """Back off a repository only when it repeatedly yields no new evidence."""
    if failure:
        return 60
    if made:
        return 0.2
    if cursor_advanced:
        # Seen source windows still move the scan toward a fresh revision.
        return 0.5
    return min(120, 5 * 2 ** max(0, empty_refills - 1))


def companion_source_paths(path, files):
    """Find exact-revision test/policy context without guessing generated names."""
    stem = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]

    def sibling_source_component(candidate):
        # A matching basename is not a component link. Compare only paths in
        # the same src root; separate test trees keep the existing fallback.
        source_dirs = path.split("/")[:-1]
        candidate_dirs = candidate.split("/")[:-1]
        if "src" not in source_dirs or "src" not in candidate_dirs:
            return False
        source_root = source_dirs.index("src")
        candidate_root = candidate_dirs.index("src")
        if source_dirs[:source_root] != candidate_dirs[:candidate_root]:
            return False
        source_component = source_dirs[source_root + 1 : source_root + 2]
        candidate_component = candidate_dirs[candidate_root + 1 : candidate_root + 2]
        return bool(
            source_component
            and candidate_component
            and source_component != candidate_component
        )

    def locality(candidate):
        name = candidate.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        exact = name in {
            stem,
            f"test_{stem}",
            f"{stem}_test",
            f"{stem}.test",
            f"{stem}.spec",
        }
        common = 0
        for left, right in zip(path.split("/")[:-1], candidate.split("/")[:-1]):
            if left != right:
                break
            common += 1
        # src/tui/utils and test/tui/utils belong together even when another
        # component has the same basename. Keep repository locality primary.
        mirrored = 0
        directories = [
            [
                part
                for part in name.split("/")[:-1]
                if part not in {"src", "test", "tests"}
            ]
            for name in (path, candidate)
        ]
        for left, right in zip(*directories):
            if left != right:
                break
            mirrored += 1
        return not exact, -common, -mirrored, candidate

    tests = sorted(
        (
            p
            for p in files
            if p != path
            and "test" in p
            and stem in p
            and p.endswith(SOURCE_SUFFIXES)
            and not sibling_source_component(p)
        ),
        key=locality,
    )
    parts = path.split("/")
    readme = None
    if "experimental" in parts:
        index = parts.index("experimental")
        if index + 1 < len(parts) - 1:
            feature = parts[index + 1]
            feature_root = "/".join(parts[: index + 2])
            candidate_readme = f"{feature_root}/README.md"
            if candidate_readme in files:
                readme = candidate_readme
            feature_tests = sorted(
                p
                for p in files
                if p.startswith("tests/experimental/")
                and "test" in p
                and (
                    f"/{feature}/" in p
                    or p.rsplit("/", 1)[-1].rsplit(".", 1)[0]
                    in {f"test_{feature}", f"{feature}_test"}
                    or p.rsplit("/", 1)[-1].startswith(f"test_{feature}_")
                    or (
                        "_" in feature
                        and p.rsplit("/", 1)[-1]
                        .rsplit(".", 1)[0]
                        .endswith(f"_{feature}")
                    )
                )
                and p.endswith(SOURCE_SUFFIXES)
            )
            tests = feature_tests + [p for p in tests if p not in feature_tests]
    return tests[:1], readme


def followup_test_request(packet, snapshot, analysis):
    """Suggest one observed companion test, never a model-produced fetch target.

    Prefer tests in the source component over unrelated same-named monorepo files.
    Only use primary source from the current pinned snapshot. A quoted constant
    present in both that source and the hypothesis can anchor its test window;
    it is a literal search hint, not proof of behavior or test coverage.
    """
    repo = packet["repo"]
    prefix = f"https://raw.githubusercontent.com/{repo}/{snapshot['commit']}/"
    hints = "\n".join(
        analysis.get(field, "") for field in ("hypothesis", "next_check", "title")
    )[:16000]
    for source in packet["sources"][:2]:
        url = source["url"]
        if not url.startswith(prefix):
            continue
        path = urllib.parse.unquote(url[len(prefix) :])
        if path not in snapshot["files"]:
            continue
        tests, _ = companion_source_paths(path, snapshot["files"])
        if not tests:
            continue
        request = {"path": tests[0], "hints": hints, "max_lines": 80}
        constants = set(re.findall(r"""["']([A-Z][A-Z0-9_]{4,})["']""", source["text"]))
        anchor_hints = "\n".join(
            analysis.get(field, "") for field in ("title", "hypothesis", "next_check")
        )[:16000]
        anchor = next(
            (
                word
                for word in re.findall(r"\b[A-Z][A-Z0-9_]{4,}\b", anchor_hints)
                if word in constants and len(word) <= 512
            ),
            None,
        )
        if anchor:
            request["exact_hint"] = anchor
        return request
    return None


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
        if "source_windows" in spec and (
            type(spec["source_windows"]) is not int
            or not 1 <= spec["source_windows"] <= 32
        ):
            raise ValueError("repository source_windows must be 1..32")
        if type(spec.get("followup_import_context", False)) is not bool:
            raise ValueError("followup_import_context must be a boolean")
        if type(spec.get("followup_code_search", False)) is not bool:
            raise ValueError("followup_code_search must be a boolean")
        if type(spec.get("followup_discussion_context", False)) is not bool:
            raise ValueError("followup_discussion_context must be a boolean")
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
        skip_labels = spec.get("issue_skip_labels", [])
        if (
            not isinstance(skip_labels, list)
            or len(skip_labels) > 16
            or any(
                not isinstance(label, str) or not label or len(label) > 100
                for label in skip_labels
            )
        ):
            raise ValueError("issue_skip_labels must be a bounded list of label names")
    return value


def source_paths(snapshot, spec):
    test_dirs = {"test", "tests", "__tests__", "fixtures"}

    def implementation_path(path):
        parts = path.lower().split("/")
        name = parts[-1]
        stem = name.rsplit(".", 1)[0]
        if any(
            path.startswith(prefix)
            and test_dirs.intersection(prefix.lower().split("/"))
            for prefix in spec["source_prefixes"]
        ):
            return True
        return not (
            any(part in test_dirs for part in parts[:-1])
            or stem in {"conftest", "test"}
            or stem.startswith("test_")
            or stem.endswith(("_test", ".test", ".spec"))
        )

    return sorted(
        p
        for p in snapshot["files"]
        if any(p.startswith(prefix) for prefix in spec["source_prefixes"])
        and p.endswith(SOURCE_SUFFIXES)
        and not p.endswith("__init__.py")
        and implementation_path(p)
        and not re.search(r"(?:^|/)(?:generated|third_party|vendor)/|_hdim\d+_", p)
    )


def changed_first_paths(paths, current_blobs, previous_blobs, limit=512):
    """Move changed Git blobs to the front without dropping any source paths."""
    changed = [
        path for path in paths if current_blobs[path] != previous_blobs.get(path)
    ][:limit]
    changed_set = set(changed)
    return changed + [path for path in paths if path not in changed_set], changed


def continuation_request(packet, snapshot, analysis):
    """Honor an explicit tail request only against an observed same-pin window.

    Model text selects no URL or arbitrary line: its requested boundary must
    equal the recorded end of exactly one truncated public source window.
    """
    next_check = analysis.get("next_check", "")
    if not isinstance(next_check, str):
        return None
    boundaries = set()
    for expression in (
        r"\bafter\s+line\s+(\d{1,7})\b",
        r"行\s*(\d{1,7})\s*(?:之后|以后|后)",
    ):
        boundaries.update(
            int(value)
            for value in re.findall(expression, next_check[:2000], re.IGNORECASE)
        )
    ranges = []
    for expression in (
        r"\blines?\s+(\d{1,7})\s*[-–—]\s*(\d{1,7})\b",
        r"(?<!\d)(\d{1,7})\s*[-–—]\s*(\d{1,7})\s*行",
    ):
        ranges.extend(
            (int(first), int(last))
            for first, last in re.findall(expression, next_check[:2000], re.IGNORECASE)
        )
    # A requested interval may describe the missing tail, not an arbitrary
    # remote source. Permit only the observed end or its immediate successor.
    if any(first < 2 or last < first for first, last in ranges):
        return None
    ranges = set(ranges)
    if len(boundaries) > 1 or len(ranges) > 1 or not (boundaries or ranges):
        return None
    repo, commit = packet.get("repo"), snapshot.get("commit")
    if not isinstance(repo, str) or not isinstance(commit, str):
        return None
    prefix = f"https://raw.githubusercontent.com/{repo}/{commit}/"
    matches = []
    for source in packet.get("sources", [])[:8]:
        url = source.get("url", "")
        if not isinstance(url, str) or not url.startswith(prefix):
            continue
        path = urllib.parse.unquote(url[len(prefix) :])
        start, end, total = (
            source.get(key) for key in ("start_line", "end_line", "total_lines")
        )
        if (
            path in snapshot.get("files", [])
            and path.endswith(SOURCE_SUFFIXES)
            and source.get("truncated") is True
            and all(type(value) is int for value in (start, end, total))
            and 1 <= start <= end < total
            and (not boundaries or boundaries == {end})
            and all(first in (end, end + 1) for first, _ in ranges)
            and all(last <= total for _, last in ranges)
        ):
            request = {"path": path, "start": max(start, end - 19), "max_lines": 120}
            if ranges:
                last = next(iter(ranges))[1]
                if last >= request["start"] + 120:
                    request["tail_start"] = last - 119
            matches.append(request)
    return matches[0] if len(matches) == 1 else None


def relevant_paths(snapshot, hints, exclude=()):
    """Rank *observed tree members*; never interpret hints as a fetch target."""
    hints = hints[:16000]
    # A report often names FlashInferMLASparseMetadataBuilder, not its
    # flashinfer_mla_sparse.py module. Keep CamelCase prefix hints weaker than
    # literal paths/filenames, and require a complete component boundary.
    class_prefixes = set()
    for symbol in re.findall(r"\b[A-Z][A-Za-z0-9]{5,127}\b", hints):
        if not any(char.islower() for char in symbol):
            continue
        class_prefixes.update(
            symbol[:end].lower()
            for end in range(10, len(symbol) + 1)
            if end == len(symbol) or symbol[end].isupper()
        )
    hints = hints.lower()
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
        compact = stem.replace("_", "")
        if "_" in stem and len(compact) >= 10 and compact in class_prefixes:
            score += 20 + min(len(compact), 20)
        if score:
            ranked.append((-score, path))
    return [path for _, path in sorted(ranked)]


def same_file_kernel_definition(packet, snapshot):
    """Find one called Python kernel whose definition was outside the first window."""
    repo = packet["repo"]
    prefix = re.compile(
        rf"https://raw\.githubusercontent\.com/{re.escape(repo)}/[0-9a-f]{{40}}/(.+)"
    )
    files = set(snapshot["files"])
    sources = packet["sources"]
    for source in sources[:2]:
        match = prefix.fullmatch(source["url"])
        if match is None:
            continue
        path = urllib.parse.unquote(match.group(1))
        if path not in files or not path.endswith(".py"):
            continue
        for symbol in re.findall(r"\b([A-Za-z_]\w*_kernel)\s*\[", source["text"]):
            definition = re.compile(rf"\bdef\s+{re.escape(symbol)}\s*\(")
            if not any(definition.search(item["text"]) for item in sources):
                return path, symbol
    return None


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


def _report_lifecycle_identity(source):
    """Only bounded report-state changes, not observation timestamps, are evidence."""
    match = re.fullmatch(
        r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/(issues|pull)/[1-9][0-9]*",
        source["url"],
    )
    kind = source.get("observed_report_kind")
    state = source.get("observed_report_state")
    if (
        match is None
        or kind != ("issue" if match[1] == "issues" else "pull_request")
        or state not in ("open", "closed")
    ):
        return None
    reason = source.get("observed_report_state_reason")
    return [
        kind,
        state,
        reason
        if reason in ("completed", "not_planned", "reopened", "duplicate")
        else None,
    ]


def evidence_identity(source):
    lifecycle = _report_lifecycle_identity(source)
    text = source["text"]
    if lifecycle is not None:
        text = scout.dumps([text, lifecycle])
    return re.sub(r"/[0-9a-f]{40}/", "/REV/", source["url"]), text


def retrieval_identity(source):
    # This controller metadata only prevents budget trimming from looking like
    # fresh retrieval. Quotes remain limited to the delivered text.
    digest = source.get("_scout_pretrim_sha256")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        digest = hashlib.sha256(source["text"].encode("utf-8")).hexdigest()
    lifecycle = _report_lifecycle_identity(source)
    if lifecycle is not None:
        digest = hashlib.sha256(
            scout.dumps([digest, lifecycle]).encode("utf-8")
        ).hexdigest()
    return evidence_identity(source)[0], digest


class ResearchProducer:
    def __init__(
        self,
        root,
        config_path,
        github_auth=False,
        context=None,
        min_free_disk_mb=0,
    ):
        self.root = Path(root)
        self.min_free_disk_mb = min_free_disk_mb
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
        self.refill_wake = threading.Event()
        self.thread = None
        self.lock = threading.RLock()
        self.inflight_repos = set()
        self.completed_repos = set()
        with scout.connect(root) as db:
            shadow.initialize(db)
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

    def disk_paused(self):
        if not self.min_free_disk_mb:
            return False
        free_mb = scout.available_disk_mb(self.root)
        return free_mb is None or free_mb < self.min_free_disk_mb

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
                "source_windows": spec.get("source_windows", self.config["source_windows"]),
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
        self,
        key,
        spec,
        sources,
        stage,
        *,
        parent=None,
        focus_issue=None,
        question="",
        frontier=None,
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
            "lesson_suggestions": lesson_suggestions(
                question
                + " "
                + " ".join(s["url"].rsplit("/", 1)[-1] for s in sources)
                + " "
                + spec["question"],
                exclude=(card["id"] for card in self.lessons),
            ),
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
        if frontier is not None:
            packet["research"]["frontier"] = frontier
        if parent:
            packet["untrusted_prior_analysis"] = parent["analysis"][:2500]
        publications = publication_context(self.root, spec["repo"], sources)
        if publications:
            packet["owner_publications"] = publications
        deferrals = owner_deferral_context(self.root, spec["repo"], sources)
        if deferrals:
            packet["owner_deferrals"] = deferrals
        fit_publication_context(packet, scout.MAX_INPUT_BYTES, scout.SYSTEM)
        # Keep every supplied URL and source type but shrink explicitly, within the existing cap.
        fit_lesson_context(packet, scout.MAX_INPUT_BYTES, scout.SYSTEM)
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
                peripheral
                or [
                    s
                    for s in packet["sources"]
                    if not s.get("requested_definition_complete")
                    and len(s["text"]) >= 300
                ]
                or packet["sources"],
                key=lambda x: len(x["text"].encode("utf-8")),
            )
            if len(longest["text"]) < 300:
                raise ValueError("research packet cannot fit evidence budget")
            longest.setdefault(
                "_scout_pretrim_sha256",
                hashlib.sha256(longest["text"].encode("utf-8")).hexdigest(),
            )
            size = int(len(longest["text"]) * 0.75)
            longest["text"] = (
                issue_text_excerpt(longest["text"], size)
                if longest.get("issue_excerpt") == "head-tail"
                else longest["text"][:size]
            )
            longest["truncated"] = True
            if "requested_definition_complete" in longest:
                longest["requested_definition_complete"] = False
            if "start_line" in longest:
                longest["end_line"] = (
                    longest["start_line"] + len(longest["text"].splitlines()) - 1
                )
            if "exact_hint" in longest:
                longest["exact_hint_matched"] = longest["exact_hint"] in longest["text"]
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
                shadow.record(db, job, packet, scout.dumps(packet))
                db.executemany(
                    "INSERT OR IGNORE INTO research_seen VALUES (?,?)",
                    ((key, job), (evidence_key, job)),
                )
            self.state["followups_created" if parent else "discovery_created"] += 1
        return True

    def snapshot(self, spec, progress):
        # Source sweeps keep a stable revision until their cursor completes.
        snapshot = self.context.snapshot(
            spec["repo"], progress.get("commit") or spec.get("ref", "main")
        )
        progress["commit"] = snapshot["commit"]
        return snapshot

    def current_snapshot(self, spec):
        # Issue triage and follow-ups must not inherit a long sweep's pinned SHA.
        # The context layer bounds mutable-ref refreshes with SNAPSHOT_TTL.
        return self.context.snapshot(spec["repo"], spec.get("ref", "main"))

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
            if set(item.get("labels", [])) & set(spec.get("issue_skip_labels", [])):
                items.pop(0)
                continue
            key = f"issue:{spec['repo']}:{item['number']}:{item.get('updated_at', '')}"
            if self.seen(key):
                items.pop(0)
                continue
            sources = [
                issue_evidence(
                    item["html_url"],
                    item["title"],
                    item.get("body") or "",
                    already_truncated=item.get("truncated", False),
                )
            ]
            snapshot = self.current_snapshot(spec)
            if self.stopped():
                return False
            matches = relevant_paths(snapshot, sources[0]["text"])
            if matches:
                try:
                    sources.append(
                        self.context.source(
                            spec["repo"],
                            snapshot["commit"],
                            matches[0],
                            hints=sources[0]["text"],
                        )
                    )
                except ValueError as exc:
                    if str(exc) not in OPTIONAL_SOURCE_UNAVAILABLE:
                        raise
            created = self.emit(
                key,
                spec,
                sources,
                "issue_triage",
                focus_issue=item["number"],
                question=(
                    "First triage: distinguish an actionable current-source question from "
                    "stale/resolved/user-configuration reports. Name exact missing source "
                    "symbols if needed. If the reporter already supplied a tested patch "
                    "and offered to submit it, preserve the finding as author-owned work; "
                    "suggest independent validation rather than a competing PR."
                ),
            )
            items.pop(0)
            return created
        return False

    def source_audit(self, spec, progress):
        prefixes = sorted(set(spec["source_prefixes"]))
        if progress.get("source_prefixes") != prefixes:
            # A completed sweep's cooldown belongs to its selected paths, not
            # the repository alone. Recheck a changed (or legacy unrecorded)
            # selection now; the scope and seen keys below still prevent
            # duplicate model work when the effective paths have not changed.
            progress["source_prefixes"] = prefixes
            progress.pop("sources_after", None)
        windows = spec.get("source_windows", self.config["source_windows"])
        previous_windows = progress.get("source_windows", 3)
        if previous_windows != windows:
            cursor = progress.get("source_cursor", 0)
            path_index, window_index = divmod(cursor, previous_windows)
            progress["source_cursor"] = path_index * windows + min(
                window_index, windows - 1
            )
            progress.pop("sources_after", None)
            progress.pop("last_sweep_commit", None)
            progress.pop("last_sweep_scope", None)
            progress.pop("source_priority", None)
            progress.pop("priority_reference_commit", None)
        progress["source_windows"] = windows
        if time.time() < progress.get("sources_after", 0):
            if time.time() < progress.get("revision_check_after", 0):
                return False
            latest = self.current_snapshot(spec)
            progress["revision_check_after"] = time.time() + 900
            previous = progress.get("commit") or progress.get("last_sweep_commit")
            if not previous or latest["commit"] == previous:
                return False
            # A completed sweep sleeps for 30 minutes; the existing 15-minute
            # revision check must still admit changed source during that sleep.
            progress["priority_reference_commit"] = previous
            progress["commit"] = latest["commit"]
            progress["source_cursor"] = 0
            progress.pop("source_priority", None)
            progress.pop("sources_after", None)
        snapshot = self.snapshot(spec, progress)
        if time.time() >= progress.get("revision_check_after", 0):
            latest = self.current_snapshot(spec)
            progress["revision_check_after"] = time.time() + 900
            if latest["commit"] != snapshot["commit"]:
                # A long pinned sweep must not hide newer source for days.
                # Previously queued packets remain versioned by their old SHA.
                progress["priority_reference_commit"] = snapshot["commit"]
                progress["commit"] = latest["commit"]
                progress["source_cursor"] = 0
                progress.pop("source_priority", None)
                snapshot = latest
        paths = source_paths(snapshot, spec)
        alphabetical_paths = paths
        progress["available_sources"] = len(paths)
        scope = hashlib.sha256(scout.dumps([windows, paths]).encode()).hexdigest()
        # Once a complete sweep has seen this exact revision, another pass
        # cannot create fresh source evidence. Keep issue/follow-up discovery
        # active, but avoid walking thousands of already-seen windows again.
        if (
            progress.get("source_cursor", 0) == 0
            and progress.get("last_sweep_commit") == snapshot["commit"]
            and progress.get("last_sweep_scope") == scope
        ):
            progress["sources_after"] = time.time() + 1800
            progress.pop("commit", None)
            return False
        priority = progress.get("source_priority", {})
        if (
            priority.get("commit") != snapshot["commit"]
            or priority.get("scope") != scope
        ):
            # A cursor already in flight belongs to the old ordering. Restart
            # the sweep on a scope change or upgrade; seen keys keep this
            # idempotent. Persist the new prefix across process restarts.
            if priority and progress.get("source_cursor", 0):
                progress["source_cursor"] = 0
            changed = []
            previous = progress.get("priority_reference_commit") or progress.get(
                "last_sweep_commit"
            )
            if (
                progress.get("source_cursor", 0) == 0
                and previous
                and previous != snapshot["commit"]
            ):
                old = self.context.snapshot(spec["repo"], previous)
                _, changed = changed_first_paths(paths, snapshot["blobs"], old["blobs"])
            priority = {
                "commit": snapshot["commit"],
                "scope": scope,
                "paths": changed,
                "base_commit": previous,
            }
            progress["source_priority"] = priority
            progress.pop("priority_reference_commit", None)
        prioritized = [path for path in priority["paths"] if path in paths]
        prioritized_set = set(prioritized)
        paths = prioritized + [path for path in paths if path not in prioritized_set]
        total = len(paths) * windows
        scan_end = min(total, progress.get("source_cursor", 0) + 2048)
        while True:
            if self.stopped():
                return False
            cursor = progress.get("source_cursor", 0)
            if cursor >= total:
                progress.update(
                    source_cursor=0,
                    sources_after=time.time() + 1800,
                    last_sweep_commit=snapshot["commit"],
                    last_sweep_scope=scope,
                )
                progress.pop(
                    "commit", None
                )  # Refresh revision only after this bounded sweep.
                progress.pop("source_priority", None)
                progress.pop("priority_reference_commit", None)
                return False
            if cursor >= scan_end:
                return False
            batch_end = min(scan_end, cursor + 256)
            keys = []
            for index in range(cursor, batch_end):
                batch_path, batch_window = paths[index // windows], index % windows
                keys.append(
                    f"source:{spec['repo']}:{batch_path}:"
                    f"{snapshot['blobs'][batch_path]}:{1 + batch_window * 120}"
                )
            with scout.connect(self.root) as db:
                seen = {
                    row[0]
                    for row in db.execute(
                        f"SELECT key FROM research_seen WHERE key IN "
                        f"({','.join('?' for _ in keys)})",
                        keys,
                    )
                }
            unseen = next((i for i, key in enumerate(keys) if key not in seen), None)
            if unseen is None:
                progress["source_cursor"] = batch_end
                continue
            cursor += unseen
            progress["source_cursor"] = cursor
            path, window = paths[cursor // windows], cursor % windows
            start = 1 + window * 120
            key = keys[unseen]
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
            source = contextual_audit_header(
                self.context, spec["repo"], snapshot["commit"], path, source
            )
            source = contextual_audit_owners(
                self.context, spec["repo"], snapshot["commit"], path, source
            )
            sources = [source]
            if self.stopped():
                return False
            stem = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
            tests, readme = companion_source_paths(path, snapshot["files"])
            if tests:
                try:
                    sources.append(
                        self.context.source(
                            spec["repo"],
                            snapshot["commit"],
                            tests[0],
                            hints=stem,
                            max_lines=70,
                        )
                    )
                except ValueError as exc:
                    if str(exc) not in OPTIONAL_SOURCE_UNAVAILABLE:
                        raise
            if readme:
                try:
                    sources.append(
                        self.context.source(
                            spec["repo"],
                            snapshot["commit"],
                            readme,
                            hints="supported hardware experimental opt-in validation",
                            max_lines=60,
                        )
                    )
                except ValueError as exc:
                    if str(exc) not in OPTIONAL_SOURCE_UNAVAILABLE:
                        raise
            created = self.emit(
                key,
                spec,
                sources,
                "source_audit",
                question=(
                    f"Review only this supplied source window ({path}:{start}) and any supplied test or feature policy. "
                    "Find at most one concrete boundary/correctness/production-impact gap. "
                    "Documented experimental opt-in or an unsupported GPU is not itself a bug. "
                    "Missing surrounding code is uncertainty, not a bug. Prefer no_lead to speculative refactoring. "
                    "Do not call it novel; later stages check related work."
                ),
                frontier={
                    "policy": "changed_blobs_first_v1",
                    "commit": snapshot["commit"],
                    "base_commit": priority.get("base_commit"),
                    "changed_blob": path in prioritized_set,
                    "source_rank": cursor // windows + 1,
                    "alphabetical_rank": alphabetical_paths.index(path) + 1,
                },
            )
            progress["source_cursor"] = (
                (cursor // windows + 1) * windows
                if (start + 120 > source.get("total_lines", 0)
                    or source.get("end_line") == source.get("total_lines"))
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
            snapshot = self.current_snapshot(spec)
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
            definition_request = same_file_kernel_definition(packet, snapshot)
            if definition_request is not None:
                path, symbol = definition_request
                try:
                    definition_source = self.context.source(
                        spec["repo"],
                        snapshot["commit"],
                        path,
                        hints=f"def {symbol}(",
                        max_lines=100,
                    )
                except ValueError as exc:
                    if str(exc) not in OPTIONAL_SOURCE_UNAVAILABLE:
                        raise
                else:
                    if re.search(
                        rf"\bdef\s+{re.escape(symbol)}\s*\(",
                        definition_source["text"],
                    ):
                        sources.append(definition_source)
            paths = relevant_paths(snapshot, hints)
            continuation = continuation_request(packet, snapshot, analysis_value)
            if continuation:
                paths = [continuation["path"]] + [
                    path for path in paths if path != continuation["path"]
                ]
            cached_source = getattr(self.context, "cached_source_text", None)
            references = []
            if (
                callable(cached_source)
                and not continuation
                and definition_request is None
            ):
                references = reference_requests(
                    packet, snapshot, analysis_value, cached_source
                )
            # Explicit cached same-file references replace the usual reads,
            # not an extra tier or a reachability verdict.
            contracts = [] if references else contract_requests(packet, snapshot, hints=hints)
            test_request = (
                None
                if contracts
                else followup_test_request(packet, snapshot, analysis_value)
            )
            if references:
                test_request = None
            imports = []
            if (
                spec.get("followup_import_context", False)
                and callable(cached_source)
                and not references
                and not contracts
                and not continuation
                and definition_request is None
            ):
                # Explicit missing definitions precede another reproduction plan.
                # Keep the existing two-read ceiling, not another model/source tier.
                missing_context = analysis_value.get("decision") == "needs_context"
                imports = import_requests(
                    packet,
                    snapshot,
                    analysis_value,
                    cached_source,
                    limit=2 if missing_context else 1,
                )
                if imports and missing_context:
                    test_request = None
                imported_paths = {request["path"] for request in imports}
                paths = [path for path in paths if path not in imported_paths]
            code_requests = []
            code_lookup = getattr(self.context, "code_search_paths", None)
            request_text = analysis_value.get("next_check", "")
            symbols = list(
                dict.fromkeys(
                    re.findall(
                        r"\breferences\(([A-Za-z_][A-Za-z0-9_-]{3,127})\)",
                        request_text[:2000] if isinstance(request_text, str) else "",
                    )
                )
            )
            if (
                spec.get("followup_code_search", False)
                and callable(code_lookup)
                and analysis_value.get("decision") == "needs_context"
                and 1 <= len(symbols) <= 2
                and not references
                and not imports
                and not contracts
                and not continuation
                and definition_request is None
            ):
                # One current-index discovery query, never a model-provided URL.
                # Replace ordinary reads; pinned source must contain the literal.
                progress["code_search_requests"] = (
                    progress.get("code_search_requests", 0) + 1
                )
                try:
                    found = code_lookup(spec["repo"], snapshot, symbols[0])
                except (ValueError, OSError) as exc:
                    progress["code_search_error"] = type(exc).__name__
                else:
                    progress.pop("code_search_error", None)
                    found = [
                        path
                        for path in found[:2]
                        if path in snapshot["files"] and path.endswith(SOURCE_SUFFIXES)
                    ]
                    code_requests = [
                        {"path": path, "max_lines": 80, "exact_hint": symbols[0]}
                        for path in found
                    ]
                    if len(found) == 1 and len(symbols) == 2:
                        code_requests.append(
                            {
                                "path": found[0],
                                "max_lines": 80,
                                "exact_hint": symbols[1],
                            }
                        )
                    if code_requests:
                        test_request = None

            if test_request:
                paths = [path for path in paths if path != test_request["path"]]
            # Prefer the observed variant's registration/contract over an unrelated
            # lexical match, or replace one lexical match with a component test.
            # Neither hint increases the ordinary follow-up's source read count.
            lexical_budget = max(
                0, (1 if contracts or test_request else 2) - len(imports)
            )
            lexical_requests = (
                references
                or code_requests
                or [{"path": path} for path in paths[:lexical_budget]]
            )
            if continuation and lexical_requests:
                lexical_requests[0].update(
                    {key: continuation[key] for key in ("start", "max_lines")}
                )
                if "tail_start" in continuation and lexical_budget >= 2:
                    # Replace the second lexical read, never add a third one.
                    # Visible ranges remain separate; neither claims completeness.
                    lexical_requests = [
                        lexical_requests[0],
                        {
                            "path": continuation["path"],
                            "start": continuation["tail_start"],
                            "max_lines": 120,
                        },
                    ]
            for request in lexical_requests:
                if self.stopped():
                    return False
                read_request = {
                    key: value for key, value in request.items() if key != "reference_scan"
                }
                try:
                    sources.append(
                        self.context.source(
                            spec["repo"],
                            snapshot["commit"],
                            **read_request,
                            hints=hints,
                            request_hints=analysis_value.get("next_check", "")[:2000],
                        )
                    )
                except ValueError as exc:
                    if str(exc) not in OPTIONAL_SOURCE_UNAVAILABLE:
                        raise
                else:
                    if request in references and "reference_scan" in request:
                        sources[-1]["reference_scan"] = dict(request["reference_scan"])
                    if request in code_requests:
                        if request["exact_hint"] not in sources[-1]["text"]:
                            sources.pop()  # Search-index drift, not a new source claim.
                        else:
                            sources[-1]["code_search_hint"] = {
                                "symbol": request["exact_hint"],
                                "scope": "Non-exhaustive current-index path hint, independently read at the pinned revision; lexical occurrence only.",
                            }
            for request in contracts or imports + (
                [test_request] if test_request else []
            ):
                if self.stopped():
                    return False
                try:
                    sources.append(
                        self.context.source(spec["repo"], snapshot["commit"], **request)
                    )
                except ValueError as exc:
                    if str(exc) not in OPTIONAL_SOURCE_UNAVAILABLE:
                        raise
            if self.stopped():
                return False
            title = (
                sources[0]["text"].splitlines()[0]
                if number
                else json.loads(row["result"])["analysis"]["title"]
            )
            sources.extend(self.context.duplicate_sources(spec["repo"], title))
            if spec.get("followup_discussion_context", False):
                sources.extend(discussion_sources(self.context, spec["repo"], title))
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
                    "Inspect what tests actually assert: a passing characterization test can document buggy behavior, not endorse it. "
                    "If already fixed or covered by an existing PR, say no_lead; do not propose a competing copy. "
                    "If an issue or discussion author supplied a tested fix and offered a PR, treat it as author-owned work "
                    "and identify missing validation rather than proposing our own PR. "
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
            return False, refill_error_code(exc)
        finally:
            with self.lock:
                self.state["repos"][repo] = progress
                self.inflight_repos.discard(repo)
                self.save()

    def notify_completion(self, receipt):
        """Wake eligible followups from a persisted result, not model suggestions."""
        if receipt.get("state") not in {"REVIEW", "NEEDS_CONTEXT"}:
            return False
        with scout.connect(self.root) as db:
            row = db.execute(
                "SELECT state,packet FROM jobs WHERE id=?", (receipt["job_id"],)
            ).fetchone()
        if row is None or row["state"] != receipt["state"]:
            return False
        packet = json.loads(row["packet"])
        repo = packet.get("repo")
        depth = packet.get("research", {}).get("depth", 0)
        if repo not in {s["repo"] for s in self.config["repos"]} or not (
            type(depth) is int and 0 <= depth < 2
        ):
            return False
        with self.lock:
            self.completed_repos.add(repo)
            self.refill_wake.set()
        return True

    def wake_completed_refills(self, ready_at, empty_refills, active, failed):
        """Coordinator-only: clear empty backoff, never a live request/error backoff."""
        with self.lock:
            for repo in list(self.completed_repos):
                if repo in active or (
                    repo in failed and ready_at.get(repo, 0) > time.monotonic()
                ):
                    continue
                ready_at.pop(repo, None)
                empty_refills.pop(repo, None)
                self.completed_repos.remove(repo)

    def parallel_loop(self):
        active, ready_at, empty_refills = {}, {}, {}
        failed = set()
        pool = ThreadPoolExecutor(
            max_workers=self.config["context_workers"],
            thread_name_prefix="public-research-context",
        )
        try:
            while not self.stopped():
                self.refill_wake.clear()
                error = None
                for repo, (future, progress, initial_cursor) in list(active.items()):
                    if not future.done():
                        continue
                    made, failure = self.finish_refill(repo, future, progress)
                    del active[repo]
                    if failure:
                        failed.add(repo)
                    else:
                        failed.discard(repo)
                    cursor_advanced = progress.get("source_cursor", 0) != initial_cursor
                    if made:
                        empty_refills.pop(repo, None)
                    elif cursor_advanced and not failure:
                        empty_refills.pop(repo, None)
                    elif not failure:
                        empty_refills[repo] = min(6, empty_refills.get(repo, 0) + 1)
                    ready_at[repo] = time.monotonic() + refill_retry_delay(
                        made,
                        failure,
                        empty_refills.get(repo, 0),
                        cursor_advanced=cursor_advanced,
                    )
                    error = f"{repo}:{failure}" if failure else error
                self.wake_completed_refills(ready_at, empty_refills, active, failed)
                while (
                    not self.stopped()
                    and not self.disk_paused()
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
                    ready_at.pop(repo, None)
                    # One refill per repository keeps its cache writes disjoint
                    # from other workers, including shared .tmp cache filenames.
                    with self.lock:
                        self.inflight_repos.add(repo)
                    initial_cursor = progress.get("source_cursor", 0)
                    future = pool.submit(
                        self.refill,
                        spec,
                        progress,
                        first,
                        self.config["refill_batch"],
                    )
                    future.add_done_callback(lambda _: self.refill_wake.set())
                    active[repo] = (future, progress, initial_cursor)
                queued = self.pending()
                phase = (
                    "DISK_PAUSED"
                    if self.disk_paused()
                    else "BACKOFF"
                    if error
                    else "REFILLING"
                    if active
                    else "READY"
                    if queued >= self.config["queue_target"]
                    else "WAITING_FOR_NEW_EVIDENCE"
                )
                delay = 5
                if queued < self.config["queue_target"] and ready_at:
                    delay = idle_refill_delay(ready_at, time.monotonic())
                self.publish(
                    phase,
                    error=error,
                    next_scan=None if active else time.time() + delay,
                )
                if self.stopped():
                    break
                self.refill_wake.wait(delay)
        finally:
            # Retain the single-runner lock until every bounded public GET has
            # returned; stopped workers cannot publish a late model packet.
            pool.shutdown(wait=True)
            for repo, (future, progress, _) in active.items():
                self.finish_refill(repo, future, progress)
            self.save()
            self.publish("STOPPED")

    def loop(self):
        if self.config["context_workers"] > 1:
            self.parallel_loop()
            return
        while not self.stopped():
            try:
                if self.disk_paused():
                    self.publish("DISK_PAUSED")
                    self.halt.wait(5)
                    continue
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
        self.refill_wake.set()
        if self.thread:
            # Keep single_runner locked until the bounded in-flight GET returns;
            # never allow an old producer to overlap a restarted daemon.
            self.thread.join()
