"""Read-only Scout-to-delivery funnel audit for a creation-time cohort.

Delivery outcomes are a *current snapshot*, not independently adjudicated lead
value. An absent delivery row is pending/unselected, never a negative label.
This time-window view complements the repository's lifetime Kimi Scout funnel.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import time
from collections import Counter, defaultdict
from pathlib import Path


def blocker_class(reason: str) -> str:
    if "relative import requires package context" in reason:
        return "package_context"
    if "full module exceeds" in reason:
        return "module_size"
    if "owner-run CPU profile" in reason:
        return "repository_profile"
    if "unsupported installed-package closure" in reason:
        return "missing_dependencies"
    return "other"


def audit(scout_db: Path, delivery_db: Path, start: float, end: float) -> dict:
    if not 0 < start < end:
        raise ValueError("require 0 < start < end")
    if not scout_db.is_file() or not delivery_db.is_file():
        raise FileNotFoundError("both existing SQLite files are required")
    connection = sqlite3.connect(scout_db.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        connection.execute(
            "ATTACH DATABASE ? AS deliverydb",
            (delivery_db.resolve().as_uri() + "?mode=ro",),
        )
        connection.execute("PRAGMA query_only=ON")
        groups = defaultdict(
            lambda: {
                "jobs": 0,
                "charged_tokens_or_reservation": 0,
                "reported_model_tokens": 0,
                "jobs_with_reported_usage": 0,
                "scout_states": Counter(),
                "delivery_states": Counter(),
                "environment_blockers": Counter(),
            }
        )
        query = """SELECT COALESCE(json_extract(j.packet,'$.repo'),'') AS repo,
                          COALESCE(json_extract(j.packet,'$.research.stage'),'') AS stage,
                          COALESCE(s.source_class,'unknown') AS source_class,
                          j.state, j.charge,
                          CASE WHEN json_valid(j.result)
                          THEN json_extract(j.result,'$.usage.total_tokens') END,
                          d.state, COALESCE(d.reason,'')
                   FROM jobs AS j
                   LEFT JOIN research_action_shadow AS s ON s.job_id=j.id
                   LEFT JOIN deliverydb.delivery AS d ON d.source_job_id=j.id
                   WHERE j.created>=? AND j.created<?"""
        for (
            repo,
            stage,
            source_class,
            state,
            charge,
            usage_tokens,
            delivery_state,
            reason,
        ) in connection.execute(query, (start, end)):
            group = groups[(repo, stage, source_class)]
            group["jobs"] += 1
            group["charged_tokens_or_reservation"] += max(0, charge or 0)
            if type(usage_tokens) is int and usage_tokens >= 0:
                group["reported_model_tokens"] += usage_tokens
                group["jobs_with_reported_usage"] += 1
            group["scout_states"][state] += 1
            group["delivery_states"][delivery_state or "NOT_DELIVERED"] += 1
            if delivery_state == "ENVIRONMENT_BLOCKED":
                group["environment_blockers"][blocker_class(reason)] += 1
        rows = []
        for (repo, stage, source_class), group in groups.items():
            rows.append(
                {
                    "repo": repo,
                    "stage": stage,
                    "source_class": source_class,
                    **{
                        key: dict(sorted(value.items()))
                        if isinstance(value, Counter)
                        else value
                        for key, value in group.items()
                    },
                }
            )
        rows.sort(
            key=lambda row: (
                -row["charged_tokens_or_reservation"],
                row["repo"],
                row["stage"],
            )
        )
        return {
            "schema_version": "scout-funnel-snapshot-v1",
            "created_from": start,
            "created_before": end,
            "observed_at": time.time(),
            "groups": rows,
            "claim_boundary": (
                "Reported tokens are not billed cost; charge may include reservation "
                "when usage is unavailable. Scout REVIEW and delivery states "
                "are not independent value labels. NOT_DELIVERED is censored, not a negative."
            ),
        }
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scout-db", required=True, type=Path)
    parser.add_argument("--delivery-db", required=True, type=Path)
    parser.add_argument("--from", dest="start", required=True, type=float)
    parser.add_argument("--before", dest="end", required=True, type=float)
    args = parser.parse_args()
    print(
        json.dumps(
            audit(args.scout_db, args.delivery_db, args.start, args.end),
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
