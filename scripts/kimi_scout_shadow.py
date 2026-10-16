"""Pre-decision, advisory-only evidence-action baseline for Scout research.

This records a cheap deterministic suggestion in the same transaction as queue
admission. It never reads a model result, rejects a lead, or dispatches work.
"""

from __future__ import annotations

from contextlib import closing
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import time
from urllib.parse import urlsplit


POLICY_VERSION = "predecision-native-test-baseline-v1"
SOURCE_EXTENSIONS = (
    ".py", ".cu", ".cuh", ".cpp", ".h", ".hpp",
    ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs",
)
PINNED_SOURCE = re.compile(
    r"^/(?P<owner>[^/]+)/(?P<repo>[^/]+)/(?P<commit>[0-9a-f]{40})/"
    r"(?P<path>[^?#]+)$"
)


def enroll_future_source_audits(root, *, created_after, repositories, count=4):
    """Read the first future admissions, never their results or current states.

    Freeze cutoff/repositories/count before admission. Incomplete frames keep
    their prefix; missing or mismatched queue-time records retain their slots,
    not replacement cases. Output is private trial input, not a public dataset,
    independent oracle, execution permission or proof of budget equality.
    """
    if (type(created_after) not in (int, float) or not math.isfinite(created_after)
            or created_after < 0 or type(count) is not int or not 1 <= count <= 20):
        raise ValueError("finite cutoff and count within 1..20 required")
    if (not isinstance(repositories, (list, tuple)) or not 1 <= len(repositories) <= 64
            or any(not isinstance(repo, str) or not re.fullmatch(
                r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo)
                or any(part in (".", "..") for part in repo.split("/")) for repo in repositories)):
        raise ValueError("explicit repository frame required")
    repositories = sorted(set(repositories))
    path = (Path(root) / "scout.sqlite").resolve(strict=True)
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=15)) as db:
        rows = db.execute(
            "SELECT j.id,j.created,j.packet,s.packet_sha256,s.job_created,s.recorded_at "
            "FROM jobs AS j INDEXED BY scout_jobs_created "
            "LEFT JOIN research_action_shadow AS s ON s.job_id=j.id "
            "WHERE j.created>? AND json_extract(j.packet,'$.research.stage')='source_audit' "
            "AND json_extract(j.packet,'$.repo') IN ("
            + ",".join("?" for _ in repositories) + ") ORDER BY j.created,j.id LIMIT ?",
            (created_after, *repositories, count),
        ).fetchall()
    cases = []
    for ident, created, body, recorded_hash, recorded_created, recorded_at in rows:
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        packet = json.loads(body)
        if recorded_hash is None:
            status = "MISSING_PREDECISION_RECORD"
        elif recorded_hash != digest or recorded_created != created:
            status = "PREDECISION_PACKET_BINDING_MISMATCH"
        elif (type(recorded_at) not in (int, float) or not math.isfinite(recorded_at)
              or recorded_at < created):
            status = "INVALID_PREDECISION_TIME"
        else:
            status = "BOUND_PREDECISION_PACKET"
        cases.append(dict(job_id=ident, created=created, packet_sha256=digest,
                          predecision_status=status, packet_body=body,
                          owner_context_present=bool(packet.get("owner_deferrals")
                                                     or packet.get("owner_publications"))))
    return dict(status="FRAME_COMPLETE" if len(cases) == count else "FRAME_INCOMPLETE",
                created_after=created_after, repositories=repositories, requested_count=count,
                cases=cases, replacement_on_failure=False, model_calls=0,
                scope="First admitted source-audit jobs by created/id, irrespective of outcomes. "
                "Queue-time binding is not unseen training data, independent adjudication, "
                "native testability, PR yield or a budget-matched experiment.")


def initialize(db) -> None:
    db.execute("""CREATE TABLE IF NOT EXISTS research_action_shadow (
        job_id TEXT PRIMARY KEY,
        policy_version TEXT NOT NULL,
        packet_sha256 TEXT NOT NULL,
        job_created REAL NOT NULL,
        recorded_at REAL NOT NULL,
        repo TEXT NOT NULL,
        stage TEXT NOT NULL,
        source_commit TEXT,
        source_extension TEXT,
        source_class TEXT,
        has_test_source INTEGER NOT NULL,
        changed_blob INTEGER,
        input_bytes INTEGER NOT NULL,
        suggested_action TEXT NOT NULL,
        reason TEXT NOT NULL,
        authority TEXT NOT NULL
    )""")


def source_facts(packet: dict) -> tuple[str | None, str | None, bool]:
    """Use only immutable source URLs already present at queue admission."""
    matches = []
    for source in packet.get("sources", []):
        url = urlsplit(source.get("url", ""))
        if url.scheme != "https" or url.netloc != "raw.githubusercontent.com":
            continue
        match = PINNED_SOURCE.fullmatch(url.path)
        if not match:
            continue
        if f"{match['owner']}/{match['repo']}".casefold() != packet.get("repo", "").casefold():
            continue
        path = match["path"]
        if not path.lower().endswith(SOURCE_EXTENSIONS):
            continue
        matches.append((match["commit"], path))
    if not matches:
        return None, None, False
    primary_commit, primary_path = matches[0]
    extension = "." + primary_path.rsplit(".", 1)[-1].lower()
    has_test = any(
        commit == primary_commit
        and path != primary_path
        and ("test" in path.lower() or ".spec." in path.lower())
        for commit, path in matches[1:]
    )
    return primary_commit, extension, has_test


def source_class(packet: dict) -> str | None:
    """A path stratum for later analysis, never an automatic exclusion."""
    for source in packet.get("sources", []):
        url = urlsplit(source.get("url", ""))
        if url.netloc != "raw.githubusercontent.com":
            continue
        match = PINNED_SOURCE.fullmatch(url.path)
        if match and f"{match['owner']}/{match['repo']}".casefold() == packet.get(
            "repo", ""
        ).casefold():
            return "experimental" if "/experimental/" in f"/{match['path']}" else "other"
    return None


def suggest(packet: dict) -> tuple[str, str]:
    """A non-rejecting rules baseline, not a correctness or PR decision."""
    stage = packet.get("research", {}).get("stage")
    source_commit, extension, has_test = source_facts(packet)
    frontier_commit = packet.get("research", {}).get("frontier", {}).get("commit")
    if source_commit and frontier_commit and source_commit != frontier_commit:
        return "VERIFY_PINNED_SOURCE", "SOURCE_FRONTIER_COMMIT_MISMATCH"
    if stage == "source_audit":
        if source_commit is None:
            return "VERIFY_PINNED_SOURCE", "NO_SAME_REPOSITORY_PINNED_SOURCE"
        if extension in {".cu", ".cuh"}:
            return "VERIFY_BUILD_ARCH_AND_NATIVE_TEST", "CUDA_SOURCE_NEEDS_TARGET_CLOSURE"
        if has_test:
            return "CHECK_TEST_AND_DOWNSTREAM_CONTRACT", "TEST_SOURCE_IN_PACKET"
        if extension == ".py":
            return "CHECK_PYTHON_ENV_AND_TEST", "PINNED_PYTHON_SOURCE_NO_TEST"
        return "FIND_REPOSITORY_NATIVE_TEST", "PINNED_NONPYTHON_SOURCE_NO_TEST"
    if stage == "issue_triage":
        return "VERIFY_ISSUE_ON_CURRENT_SOURCE", "ISSUE_IS_NOT_REPRODUCTION"
    if stage in {"source_followup", "reproduction_plan"}:
        return "DESIGN_INDEPENDENT_REPRO", "HYPOTHESIS_NEEDS_CONTROL"
    return "REVIEW_EVIDENCE_SCOPE", "UNKNOWN_STAGE_ABSTAIN_FROM_STOP"


def record(db, job_id: str, packet: dict, packet_body: str) -> None:
    """Record before execution, using no result, state transition, or future fact."""
    row = db.execute(
        "SELECT state,created,packet FROM jobs WHERE id=?", (job_id,)
    ).fetchone()
    if row is None or row["state"] != "PENDING" or row["packet"] != packet_body:
        raise ValueError("shadow action requires this exact pending packet")
    commit, extension, has_test = source_facts(packet)
    frontier = packet.get("research", {}).get("frontier", {})
    changed = frontier.get("changed_blob")
    if not isinstance(changed, bool) or not re.fullmatch(
        r"[0-9a-f]{40}", str(frontier.get("base_commit", ""))
    ):
        changed = None
    action, reason = suggest(packet)
    db.execute(
        """INSERT OR IGNORE INTO research_action_shadow VALUES
        (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            job_id,
            POLICY_VERSION,
            hashlib.sha256(packet_body.encode("utf-8")).hexdigest(),
            row["created"],
            time.time(),
            packet.get("repo", ""),
            packet.get("research", {}).get("stage", ""),
            commit,
            extension,
            source_class(packet),
            int(has_test),
            None if changed is None else int(changed),
            len(packet_body.encode("utf-8")),
            action,
            reason,
            "ADVISORY_ONLY_NO_REJECTION_NO_EXECUTION",
        ),
    )
