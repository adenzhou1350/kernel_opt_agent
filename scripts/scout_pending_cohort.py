"""Freeze unfinished Scout follow-ups without reading their later answers.

This is read-only enrollment for a shadow pilot, not a routing experiment or a
quality label. The native rule and lineage IDs stay outside model-visible input.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sqlite3
import time
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit


def enroll(db_path, *, created_after, limit=12, per_repo_cap=4, scan_limit=200):
    if (
        not math.isfinite(created_after)
        or created_after < 0
        or not 1 <= limit <= scan_limit <= 2000
        or not 1 <= per_repo_cap <= limit
    ):
        raise ValueError("invalid cutoff or bounded sample caps")
    db = sqlite3.connect(f"file:{Path(db_path).resolve().as_posix()}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        db.execute("BEGIN")
        # Never SELECT result, model answer, charge, or terminal-state strata.
        rows = db.execute(
            "SELECT j.id,j.packet,j.created,s.policy_version,s.packet_sha256,"
            "s.recorded_at,s.suggested_action,s.reason FROM jobs j "
            "JOIN research_action_shadow s ON s.job_id=j.id "
            "WHERE j.created>=? AND j.finished IS NULL "
            "AND j.state IN ('PENDING','RUNNING') "
            "ORDER BY j.created,j.id LIMIT ?",
            (created_after, scan_limit),
        ).fetchall()
        snapshot_at = time.time()
    finally:
        db.close()

    inputs, selection = [], {}
    counts, paths, packets = Counter(), set(), set()
    for row in rows:
        try:
            packet = json.loads(row["packet"])
        except (TypeError, ValueError):
            continue
        if (
            not isinstance(packet, dict)
            or {"result", "analysis", "state", "decision"} & packet.keys()
        ):
            continue
        research = packet.get("research")
        if (
            not isinstance(research, dict)
            or research.get("stage") not in ("source_followup", "reproduction_plan")
            or not research.get("parent_job_id")
            or not isinstance(packet.get("untrusted_prior_analysis"), str)
            or not isinstance(packet.get("repo"), str)
        ):
            continue
        digest = hashlib.sha256(row["packet"].encode("utf-8")).hexdigest()
        if digest != row["packet_sha256"] or digest in packets:
            continue
        sources = packet.get("sources")
        if not isinstance(sources, list) or not sources:
            continue
        urls = []
        for source in sources:
            if not isinstance(source, dict) or not isinstance(source.get("url"), str):
                break
            parsed = urlsplit(source["url"])
            if parsed.scheme != "https" or parsed.netloc not in (
                "github.com",
                "raw.githubusercontent.com",
            ):
                break
            urls.append(source["url"])
        if len(urls) != len(sources):
            continue
        repo = packet["repo"].casefold()
        # Exact primary-source URL dedup is not semantic independence. Report it.
        cluster = (repo, urls[0])
        if counts[repo] >= per_repo_cap or cluster in paths:
            continue
        visible = dict(packet)
        visible["research"] = {
            key: value
            for key, value in research.items()
            if key not in ("parent_job_id", "root_job_id")
        }
        case_id = hashlib.sha256(row["id"].encode()).hexdigest()[:20]
        inputs.append(
            {
                "case_id": case_id,
                "original_packet_sha256": digest,
                "packet": visible,
            }
        )
        selection[case_id] = {
            "job_id": row["id"],
            "created": row["created"],
            "lineage_root_job_id": research.get("root_job_id")
            or research["parent_job_id"],
            "native_rule": {
                key: row[key]
                for key in (
                    "policy_version",
                    "recorded_at",
                    "suggested_action",
                    "reason",
                )
            },
        }
        counts[repo] += 1
        paths.add(cluster)
        packets.add(digest)
        if len(inputs) == limit:
            break
    metadata = {
        "created_after": created_after,
        "snapshot_at": snapshot_at,
        "scanned_unfinished_rows": len(rows),
        "requested": limit,
        "enrolled": len(inputs),
        "per_repo_cap": per_repo_cap,
        "repo_counts": dict(counts),
        "selection": selection,
        "limits": [
            "Unfinished at the read transaction snapshot, not necessarily at later scoring.",
            "Recent bounded queue slice, not random population sampling.",
            "Exact source URL dedup does not make same-revision cases independent.",
            "Enrollment alone is not budget-matched routing execution or accuracy evidence.",
            "Keep outcome-side metadata away from routers and blind adjudicators.",
        ],
    }
    return inputs, metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--created-after", type=float, required=True)
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument("--per-repo-cap", type=int, default=4)
    parser.add_argument("--scan-limit", type=int, default=200)
    args = parser.parse_args()
    inputs, metadata = enroll(
        args.db,
        created_after=args.created_after,
        limit=args.limit,
        per_repo_cap=args.per_repo_cap,
        scan_limit=args.scan_limit,
    )
    args.output_dir.mkdir(parents=True, exist_ok=False)
    body = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in inputs
    ).encode()
    (args.output_dir / "blind-inputs.jsonl").write_bytes(body)
    metadata["blind_inputs_sha256"] = hashlib.sha256(body).hexdigest()
    (args.output_dir / "selection-outcome-side.json").write_bytes(
        (json.dumps(metadata, ensure_ascii=False, indent=2) + "\n").encode()
    )
    print(
        json.dumps(
            {
                "enrolled": len(inputs),
                "requested": args.limit,
                "repo_counts": metadata["repo_counts"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
