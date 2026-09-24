#!/usr/bin/env python3
"""Read-only Scout funnel: count evidence, not supposed independent PRs.

This deliberately does not infer merged PRs from REVIEW or delivery states.
The Scout and delivery databases remain live and are opened read-only.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter, defaultdict
from contextlib import closing
from pathlib import Path


def _readonly(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise FileNotFoundError(path)
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    connection.execute("PRAGMA query_only=ON")
    return connection


def inspect(root: Path) -> dict:
    root = root.resolve()
    states: Counter[str] = Counter()
    stages: dict[str, Counter[str]] = defaultdict(Counter)
    repositories: dict[str, dict] = defaultdict(
        lambda: {
            "research_jobs": 0,
            "review_leaves": 0,
            "reported_tokens": 0,
            "delivery": Counter(),
        }
    )
    parents: set[str] = set()
    reviews: list[tuple[str, str]] = []
    reported_tokens = 0
    jobs_with_reported_usage = 0

    with closing(_readonly(root / "scout.sqlite")) as connection:
        for job_id, state, repo, stage, parent, tokens in connection.execute(
            "SELECT id,state,json_extract(packet,'$.repo'),"
            "json_extract(packet,'$.research.stage'),"
            "json_extract(packet,'$.research.parent_job_id'),"
            "json_extract(result,'$.usage.total_tokens') FROM jobs"
        ):
            repo = repo or "unknown"
            stage = stage or "legacy"
            states[state] += 1
            stages[stage][state] += 1
            repositories[repo]["research_jobs"] += 1
            if isinstance(parent, str):
                parents.add(parent)
            if state == "REVIEW":
                reviews.append((job_id, repo))
            if type(tokens) is int and tokens >= 0:
                reported_tokens += tokens
                repositories[repo]["reported_tokens"] += tokens
                jobs_with_reported_usage += 1

    for job_id, repo in reviews:
        if job_id not in parents:
            repositories[repo]["review_leaves"] += 1

    delivery_states: Counter[str] = Counter()
    blockers: Counter[str] = Counter()
    delivery_path = root / "delivery" / "delivery.sqlite"
    if delivery_path.is_file():
        with closing(_readonly(delivery_path)) as connection:
            for repo, state, reason in connection.execute(
                "SELECT repo,state,reason FROM delivery"
            ):
                delivery_states[state] += 1
                repositories[repo]["delivery"][state] += 1
                if state != "ENVIRONMENT_BLOCKED":
                    continue
                if reason == "no immutable same-repository Python source URL in packet":
                    blockers["no_python_source"] += 1
                elif (reason or "").startswith(
                    "unsupported installed-package closure:"
                ):
                    blockers["package_closure"] += 1
                else:
                    blockers["other"] += 1

    return {
        "scope": "read-only point-in-time funnel; REVIEW and review leaves are hypotheses, not PRs",
        "research": {
            "jobs": sum(states.values()),
            "states": dict(sorted(states.items())),
            "stages": {
                stage: dict(sorted(counts.items()))
                for stage, counts in sorted(stages.items())
            },
            "review_leaves": sum(row["review_leaves"] for row in repositories.values()),
            "reported_tokens": reported_tokens,
            "jobs_with_reported_usage": jobs_with_reported_usage,
        },
        "delivery": {
            "jobs": sum(delivery_states.values()),
            "states": dict(sorted(delivery_states.items())),
            "environment_blockers": dict(sorted(blockers.items())),
        },
        "repositories": [
            {
                "repo": repo,
                "research_jobs": row["research_jobs"],
                "review_leaves": row["review_leaves"],
                "reported_tokens": row["reported_tokens"],
                "delivery": dict(sorted(row["delivery"].items())),
            }
            for repo, row in sorted(repositories.items())
        ],
        "linked_pr_count": None,
        "linked_pr_note": "Scout has no audited lead-to-PR linkage; do not call REVIEW a PR conversion.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    args = parser.parse_args(argv)
    print(json.dumps(inspect(args.root), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
