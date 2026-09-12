#!/usr/bin/env python3
"""Recompute short-lived Draft publication freshness from exact Git refs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from upstream_delivery_inbox import validate_draft_freshness


MAX_TTL_HOURS = 6.0
GIT_COMMIT = re.compile(r"[0-9a-f]{40}")
REPOSITORY = re.compile(r"[^/\s]+/[^/\s]+")


def run_git(
    root: Path, *arguments: str, check: bool = True
) -> subprocess.CompletedProcess[bytes]:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if check and completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(f"git {' '.join(arguments)} failed: {detail}")
    return completed


def resolve_commit(root: Path, ref: str) -> str:
    value = (
        run_git(root, "rev-parse", "--verify", f"{ref}^{{commit}}")
        .stdout.decode("ascii")
        .strip()
    )
    if GIT_COMMIT.fullmatch(value) is None:
        raise ValueError(f"{ref!r} did not resolve to a lowercase Git commit")
    return value


def tree_entry(root: Path, commit: str, path: str) -> bytes:
    return run_git(root, "ls-tree", "-z", commit, "--", path).stdout


def touched_paths(root: Path, base: str, candidate: str) -> list[str]:
    raw = run_git(
        root,
        "diff",
        "--name-only",
        "--diff-filter=ACDMRTUXB",
        "-z",
        base,
        candidate,
        "--",
    ).stdout
    paths = [item.decode("utf-8") for item in raw.split(b"\0") if item]
    if not paths:
        raise ValueError(
            "candidate has no changed paths relative to upstream merge-base"
        )
    return paths


def parse_observed_at(value: str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("observed-at must be ISO-8601") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("observed-at must include a timezone")
    return parsed


def isoformat(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def build(args: argparse.Namespace) -> tuple[dict, dict]:
    root = args.repository_root.resolve()
    if REPOSITORY.fullmatch(args.repository) is None:
        raise ValueError("repository must be an owner/name pair")
    if not args.candidate_id.strip() or not args.branch.strip():
        raise ValueError("candidate-id and branch must be non-empty")
    if not (0 < args.ttl_hours <= MAX_TTL_HOURS):
        raise ValueError(
            f"ttl-hours must be greater than zero and at most {MAX_TTL_HOURS:g}"
        )
    if args.exact_head_pull_request_count != 0:
        raise ValueError(
            "exact-head-pull-request-count must be zero for Draft eligibility"
        )

    candidate = resolve_commit(root, args.candidate_ref)
    upstream = resolve_commit(root, args.upstream_ref)
    fork = resolve_commit(root, args.fork_ref)
    if fork != candidate:
        raise ValueError("fork ref does not resolve to the candidate commit")

    merge_base = (
        run_git(root, "merge-base", upstream, candidate).stdout.decode("ascii").strip()
    )
    if GIT_COMMIT.fullmatch(merge_base) is None:
        raise ValueError("candidate and upstream do not have a valid merge-base")
    paths = touched_paths(root, merge_base, candidate)
    changed_upstream = [
        path
        for path in paths
        if tree_entry(root, merge_base, path) != tree_entry(root, upstream, path)
    ]
    if changed_upstream:
        raise ValueError(
            "candidate touched paths changed upstream: " + ", ".join(changed_upstream)
        )

    merge = run_git(
        root, "merge-tree", "--write-tree", upstream, candidate, check=False
    )
    if merge.returncode != 0:
        detail = merge.stdout.decode("utf-8", errors="replace").strip()
        raise ValueError(f"candidate conflicts with upstream: {detail}")

    observed = parse_observed_at(args.observed_at)
    expires = observed + timedelta(hours=args.ttl_hours)
    record = {
        "schema_version": "upstream-delivery-freshness-v1",
        "observed_at": isoformat(observed),
        "expires_at": isoformat(expires),
        "candidate_id": args.candidate_id,
        "repository": args.repository,
        "branch": args.branch,
        "candidate_commit": candidate,
        "upstream_main_commit": upstream,
        "fork_branch_commit": fork,
        "checks": {
            "fork_branch_matches_candidate": True,
            "touched_paths_unchanged": True,
            "merge_conflict": False,
            "exact_head_pull_request_count": 0,
            "draft_submission_eligible": True,
        },
        "claim_boundary": (
            "LOCAL_GIT_REF_DRIFT_AND_MERGE_RECOMPUTED_"
            "PUBLIC_PR_COUNT_EXTERNALLY_OBSERVED_NOT_PUBLICATION_AUTHORIZATION"
        ),
    }
    errors = validate_draft_freshness(
        record,
        candidate_id=args.candidate_id,
        repository=args.repository,
        branch=args.branch,
        commit=candidate,
        inbox_observed_at=record["observed_at"],
    )
    if errors:
        raise ValueError("invalid Draft freshness: " + "; ".join(errors))
    details = {
        "candidate_ref": args.candidate_ref,
        "upstream_ref": args.upstream_ref,
        "fork_ref": args.fork_ref,
        "merge_base": merge_base,
        "touched_path_count": len(paths),
    }
    return record, details


def write_once(path: Path, value: dict) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError as error:
        raise FileExistsError(
            f"refusing to replace existing freshness evidence: {path}"
        ) from error
    with os.fdopen(descriptor, "wb") as output:
        output.write(payload)
        output.flush()
        os.fsync(output.fileno())
    return hashlib.sha256(payload).hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--candidate-ref", required=True)
    parser.add_argument("--upstream-ref", required=True)
    parser.add_argument("--fork-ref", required=True)
    parser.add_argument("--exact-head-pull-request-count", type=int, required=True)
    parser.add_argument("--observed-at")
    parser.add_argument("--ttl-hours", type=float, default=4.0)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    record, details = build(args)
    output = args.output.resolve()
    digest = write_once(output, record)
    print(
        json.dumps(
            {
                "status": "PASS",
                "path": output.as_posix(),
                "sha256": digest,
                "candidate_commit": record["candidate_commit"],
                "upstream_main_commit": record["upstream_main_commit"],
                **details,
                "claim_boundary": record["claim_boundary"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
