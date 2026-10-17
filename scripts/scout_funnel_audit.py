"""Read-only Scout-to-delivery funnel audit for a creation-time cohort.

Delivery outcomes are a *current snapshot*, not independently adjudicated lead
value. An absent delivery row is pending/unselected, never a negative label.
This time-window view complements the repository's lifetime Kimi Scout funnel.
"""

from __future__ import annotations

import argparse
import json
import re
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


PR_URL = re.compile(
    r"https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/pull/[1-9][0-9]*"
)
JOB_ID = re.compile(r"[0-9a-f]{24}")
MAX_RECEIPT_READS = 256
MAX_RECEIPT_BYTES = 262_144


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate receipt field")
        value[key] = item
    return value


def receipt_usage(root, job_id, state, charge):
    """Read only bounded final accounting bound to the selected SQLite job.

    This does not authenticate a receipt or accept the model's failed answer.
    A missing/partial/unbound counter remains outside the known-token sum.
    """
    if not isinstance(job_id, str) or not JOB_ID.fullmatch(job_id):
        return None
    path = root / "results" / (job_id + ".json")
    try:
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(root) or not resolved.is_file():
            return None
        with resolved.open("rb") as stream:
            raw = stream.read(MAX_RECEIPT_BYTES + 1)
        if len(raw) > MAX_RECEIPT_BYTES:
            return None
        value = json.loads(raw, object_pairs_hook=_unique_object)
        if not isinstance(value, dict):
            return None
        accounting = value.get("token_accounting")
        reported = accounting.get("reported_usage") if isinstance(accounting, dict) else None
        tokens = reported.get("total_tokens") if isinstance(reported, dict) else None
        if (
            value.get("job_id") == job_id
            and value.get("state") == state
            and value.get("charge_basis") == "provider_report"
            and type(tokens) is int and tokens >= 0
            and type(value.get("charged_tokens_or_reservation")) is int
            and value["charged_tokens_or_reservation"] == tokens == charge
        ):
            return tokens
    except (OSError, ValueError, RuntimeError):
        pass
    return None


def audit(scout_db: Path, delivery_db: Path, start: float, end: float,
          receipts_root: Path | None = None) -> dict:
    if not 0 < start < end:
        raise ValueError("require 0 < start < end")
    if not scout_db.is_file() or not delivery_db.is_file():
        raise FileNotFoundError("both existing SQLite files are required")
    if receipts_root is not None:
        receipts_root = receipts_root.resolve(strict=True)
        if receipts_root != scout_db.resolve().parent:
            raise ValueError("receipt root must be the selected Scout database directory")
    recovery = {"enabled": receipts_root is not None, "attempted": 0,
                "recovered": 0, "unavailable_or_unbound": 0,
                "read_limit": MAX_RECEIPT_READS, "over_limit": 0}
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
                "jobs_with_receipt_usage": 0,
                "scout_states": Counter(),
                "delivery_states": Counter(),
                "environment_blockers": Counter(),
                "pr_open_candidate_rows": 0,
                "_unique_pr_urls": set(),
            }
        )
        delivery_columns = {
            row[1]
            for row in connection.execute("PRAGMA deliverydb.table_info(delivery)")
        }
        pr_url = (
            "CASE WHEN json_valid(d.result) THEN json_extract(d.result,'$.pr.url') END"
            if "result" in delivery_columns
            else "NULL"
        )
        owner_score = (
            "CASE WHEN json_valid(d.result) "
            "THEN CASE WHEN json_type(d.result,'$.owner_score')='integer' "
            "THEN json_extract(d.result,'$.owner_score') END END"
            if "result" in delivery_columns
            else "NULL"
        )
        query = f"""SELECT j.id,
                          COALESCE(json_extract(j.packet,'$.repo'),'') AS repo,
                          COALESCE(json_extract(j.packet,'$.research.stage'),'') AS stage,
                          COALESCE(s.source_class,'unknown') AS source_class,
                          j.state, j.charge,
                          CASE WHEN json_valid(j.result) THEN
                          CASE WHEN json_type(j.result,'$.usage.total_tokens')='integer'
                          THEN json_extract(j.result,'$.usage.total_tokens') END END,
                          d.state, COALESCE(d.reason,''), {pr_url}, {owner_score}
                   FROM jobs AS j
                   LEFT JOIN research_action_shadow AS s ON s.job_id=j.id
                   LEFT JOIN deliverydb.delivery AS d ON d.source_job_id=j.id
                   WHERE j.created>=? AND j.created<?"""
        if receipts_root is not None:
            query += " ORDER BY j.created,j.id"
        seen_jobs = set()
        unique_pr_urls = set()
        pr_open_candidate_rows = 0
        invalid_pr_link_rows = 0
        score_buckets = defaultdict(
            lambda: {
                "owner_review_required_rows": 0,
                "pr_open_candidate_rows": 0,
                "_unique_pr_urls": set(),
            }
        )
        unscored_owner_candidate_rows = 0
        for (
            job_id,
            repo,
            stage,
            source_class,
            state,
            charge,
            usage_tokens,
            delivery_state,
            reason,
            linked_pr_url,
            recorded_owner_score,
        ) in connection.execute(query, (start, end)):
            group = groups[(repo, stage, source_class)]
            if job_id not in seen_jobs:
                seen_jobs.add(job_id)
                group["jobs"] += 1
                group["charged_tokens_or_reservation"] += max(0, charge or 0)
                if not (type(usage_tokens) is int and usage_tokens >= 0) and receipts_root is not None:
                    if recovery["attempted"] < MAX_RECEIPT_READS:
                        recovery["attempted"] += 1
                        usage_tokens = receipt_usage(receipts_root, job_id, state, charge)
                        if usage_tokens is not None:
                            recovery["recovered"] += 1
                            group["jobs_with_receipt_usage"] += 1
                        else:
                            recovery["unavailable_or_unbound"] += 1
                    else:
                        recovery["over_limit"] += 1
                if type(usage_tokens) is int and usage_tokens >= 0:
                    group["reported_model_tokens"] += usage_tokens
                    group["jobs_with_reported_usage"] += 1
                group["scout_states"][state] += 1
            group["delivery_states"][delivery_state or "NOT_DELIVERED"] += 1
            if delivery_state == "ENVIRONMENT_BLOCKED":
                group["environment_blockers"][blocker_class(reason)] += 1
            if delivery_state in ("OWNER_REVIEW_REQUIRED", "PR_OPEN"):
                if type(recorded_owner_score) is int and recorded_owner_score >= 0:
                    score_buckets[recorded_owner_score][
                        "owner_review_required_rows"
                        if delivery_state == "OWNER_REVIEW_REQUIRED"
                        else "pr_open_candidate_rows"
                    ] += 1
                else:
                    unscored_owner_candidate_rows += 1
            if delivery_state == "PR_OPEN":
                pr_open_candidate_rows += 1
                group["pr_open_candidate_rows"] += 1
                match = PR_URL.fullmatch(linked_pr_url or "")
                if match and match.group(1).casefold() == repo.casefold():
                    group["_unique_pr_urls"].add(linked_pr_url)
                    unique_pr_urls.add(linked_pr_url)
                    if type(recorded_owner_score) is int and recorded_owner_score >= 0:
                        score_buckets[recorded_owner_score]["_unique_pr_urls"].add(
                            linked_pr_url
                        )
                else:
                    invalid_pr_link_rows += 1
        rows = []
        for (repo, stage, source_class), group in groups.items():
            group["jobs_without_known_usage_in_projection"] = (
                group["jobs"] - group["jobs_with_reported_usage"]
            )
            group["unique_linked_prs"] = len(group.pop("_unique_pr_urls"))
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
        owner_score_snapshot = [
            {
                "owner_score": score,
                "owner_review_required_rows": bucket["owner_review_required_rows"],
                "pr_open_candidate_rows": bucket["pr_open_candidate_rows"],
                "unique_linked_prs": len(bucket["_unique_pr_urls"]),
            }
            for score, bucket in sorted(score_buckets.items())
        ]
        return {
            "schema_version": "scout-funnel-snapshot-v3",
            "created_from": start,
            "created_before": end,
            "observed_at": time.time(),
            "pr_open_candidate_rows": pr_open_candidate_rows,
            "unique_linked_prs": len(unique_pr_urls),
            "invalid_pr_link_rows": invalid_pr_link_rows,
            "owner_score_snapshot": owner_score_snapshot,
            "unscored_owner_candidate_rows": unscored_owner_candidate_rows,
            "groups": rows,
            "receipt_recovery": recovery,
            "claim_boundary": (
                "Reported tokens are not billed cost; charge may include reservation "
                "when usage is unavailable. Default known usage reads accepted-result "
                "JSON only: failed calls can have final usage in separate receipts. "
                "Optional bounded receipt recovery checks job/state/charge bindings, "
                "not authenticity; missing projection usage is not proof that the "
                "provider reported none. Neither path changes verdicts or replays work. "
                "Scout REVIEW and delivery states "
                "are not independent value labels. NOT_DELIVERED is censored, not a negative. "
                "PR_OPEN counts candidate links, while unique_linked_prs deduplicates "
                "canonical PR URLs; neither proves review, merge, or value. A PR shared "
                "across groups appears once globally but can appear in multiple groups. "
                "Owner-score buckets are candidate-row snapshots, not score accuracy "
                "or conversion estimates: owner selection, duplicates, and pending reviews "
                "censor their outcomes."
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
    parser.add_argument("--receipts-root", type=Path,
                        help="optional selected Scout run directory; read at most 256 bound receipts")
    args = parser.parse_args()
    print(
        json.dumps(
            audit(args.scout_db, args.delivery_db, args.start, args.end, args.receipts_root),
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
