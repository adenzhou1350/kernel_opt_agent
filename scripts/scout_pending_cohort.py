"""Freeze Scout decision inputs without reading their later answers.

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

try:
    from .scout_evidence_acquisition import pinned_raw_url
except ImportError:
    from scout_evidence_acquisition import pinned_raw_url


DECISION_STAGES = {
    "initial": frozenset(("source_audit", "issue_triage")),
    "followup": frozenset(("source_followup", "reproduction_plan")),
}


def compact_acquisition_view(packet):
    """Optional <=6500-character shared input for acquisition-only comparisons.

    Include a bounded source catalog before allocating snippet text. Prioritize
    pinned code in original order, not candidate scores or observed outcomes.
    This is not the live Scout prompt or a definition/relevance resolver.
    """
    if not isinstance(packet, dict) or not isinstance(packet.get("sources"), list):
        raise ValueError("invalid input packet")
    try:
        prior = json.loads(packet.get("untrusted_prior_analysis", "{}"))
    except (ValueError, TypeError) as error:
        raise ValueError("invalid untrusted prior") from error
    if not isinstance(prior, dict):
        raise ValueError("invalid untrusted prior")
    sources = []
    for index, source in enumerate(packet["sources"][:24]):
        if (
            not isinstance(source, dict)
            or not isinstance(source.get("url"), str)
            or len(source["url"]) > 2048
            or not isinstance(source.get("text"), str)
            or any(
                source.get(key) is not None and type(source.get(key)) is not int
                for key in ("start_line", "end_line")
            )
        ):
            raise ValueError("invalid source catalog entry")
        sources.append(
            {
                "url": source["url"],
                "original_index": index,
                "start_line": source.get("start_line"),
                "end_line": source.get("end_line"),
                "original_chars": len(source["text"]),
                "text": "",
                "clipped": bool(source["text"]),
            }
        )
    view = {
        "repo": str(packet.get("repo", ""))[:200],
        "question": str(packet.get("question", ""))[:300],
        "hypothesis_unverified": str(prior.get("hypothesis", ""))[:800],
        "next_check_unverified": str(prior.get("next_check", ""))[:500],
        "uncertainty": str(prior.get("uncertainty", ""))[:250],
        "sources": sources,
        "catalog_omitted": max(0, len(packet["sources"]) - len(sources)),
        "scope": "Untrusted partial source and earlier hypothesis; not correctness evidence. Ranges describe original snippets, not clipped text. Empty text is catalog-only.",
    }

    def fits():
        return len(json.dumps(view, ensure_ascii=False, sort_keys=True)) <= 6500

    if not fits():
        raise ValueError("source catalog exceeds shared view budget")
    order = sorted(
        range(len(sources)),
        key=lambda i: (not pinned_raw_url(sources[i]["url"]), i),
    )[:3]
    # Allocate evenly across chosen snippets, measuring actual serialized size
    # (quotes/backslashes can expand it). No tail clipping of the finished JSON.
    low, high = 0, 1100

    def fill(width):
        for index in order:
            sources[index]["text"] = packet["sources"][index]["text"][:width]
            sources[index]["clipped"] = (
                len(sources[index]["text"]) < sources[index]["original_chars"]
            )

    while low < high:
        width = (low + high + 1) // 2
        fill(width)
        if fits():
            low = width
        else:
            high = width - 1
    fill(low)
    return view


def enroll(
    db_path,
    *,
    created_after,
    limit=12,
    per_repo_cap=4,
    scan_limit=200,
    decision_point="followup",
    enrollment="unfinished",
):
    if (
        not math.isfinite(created_after)
        or created_after < 0
        or not 1 <= limit <= scan_limit <= 2000
        or not 1 <= per_repo_cap <= limit
        or decision_point not in DECISION_STAGES
        or enrollment not in ("unfinished", "admission_recorded")
    ):
        raise ValueError("invalid cutoff or bounded sample caps")
    db = sqlite3.connect(f"file:{Path(db_path).resolve().as_posix()}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        db.execute("BEGIN")
        # Never SELECT result, model answer, charge, or terminal-state strata.
        unfinished_clause = (
            "AND j.finished IS NULL AND j.state IN ('PENDING','RUNNING') "
            if enrollment == "unfinished"
            else ""
        )
        rows = db.execute(
            "SELECT j.id,j.packet,j.created,s.policy_version,s.packet_sha256,"
            "s.recorded_at,s.suggested_action,s.reason FROM jobs j "
            "JOIN research_action_shadow s ON s.job_id=j.id "
            "WHERE j.created>=? "
            + unfinished_clause
            + "ORDER BY j.created,j.id LIMIT ?",
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
            or research.get("stage") not in DECISION_STAGES[decision_point]
            or not isinstance(packet.get("repo"), str)
        ):
            continue
        if decision_point == "initial":
            if (
                research.get("parent_job_id")
                or research.get("root_job_id")
                or "untrusted_prior_analysis" in packet
            ):
                continue
        elif not research.get("parent_job_id") or not isinstance(
            packet.get("untrusted_prior_analysis"), str
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
            or research.get("parent_job_id")
            or row["id"],
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
        "enrollment": enrollment,
        "decision_point": decision_point,
        "created_after": created_after,
        "snapshot_at": snapshot_at,
        "scanned_rows": len(rows),
        "scanned_unfinished_rows": len(rows) if enrollment == "unfinished" else None,
        "requested": limit,
        "enrolled": len(inputs),
        "per_repo_cap": per_repo_cap,
        "repo_counts": dict(counts),
        "selection": selection,
        "limits": [
            (
                "Unfinished at the read transaction snapshot, not necessarily at later scoring."
                if enrollment == "unfinished"
                else "Admission-recorded inputs may already have completed; no later answer or state was used for selection."
            ),
            "A predeclared cutoff and predictions frozen before outcome access require separate evidence; this export alone is not prospective execution.",
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
    parser.add_argument(
        "--decision-point", choices=tuple(DECISION_STAGES), default="followup"
    )
    parser.add_argument(
        "--enrollment",
        choices=("unfinished", "admission_recorded"),
        default="unfinished",
        help="admission_recorded retains fast-completed tasks without reading their answers",
    )
    args = parser.parse_args()
    inputs, metadata = enroll(
        args.db,
        created_after=args.created_after,
        limit=args.limit,
        per_repo_cap=args.per_repo_cap,
        scan_limit=args.scan_limit,
        decision_point=args.decision_point,
        enrollment=args.enrollment,
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
