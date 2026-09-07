#!/usr/bin/env python3
"""Aggregate explicit, evidence-bound work cycles into a time-to-value rollup."""

from __future__ import annotations

import argparse
import math
from collections import Counter
from datetime import datetime
from pathlib import Path

from community_knowledge import atomic_json, now, read_object, sha256_file
from community_work_cycle import MILESTONES, PHASES, parse_time, summarize
from schema_utils import validate_instance, validate_json_file


SCHEMA_VERSION = "community-time-to-value-rollup-v1"
CLAIM_BOUNDARY = "EXPLICIT_WORK_CYCLE_ROLLUP_NOT_DELIVERY_OR_PERFORMANCE_GUARANTEE"
BUCKETS = (
    "research_seconds",
    "materialization_seconds",
    "environment_preparation_seconds",
    "implementation_seconds",
    "compute_seconds",
    "validation_seconds",
    "packaging_seconds",
    "external_wait_seconds",
    "unattributed_legacy_seconds",
)


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def identity(path: Path) -> dict:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {"path": path.as_posix(), "sha256": sha256_file(path)}


def stable(value: dict) -> dict:
    return {key: item for key, item in value.items() if key != "generated_at"}


def cycle_end(ledger: dict) -> datetime:
    if ledger.get("ended_at") is not None:
        return parse_time(ledger["ended_at"], "ended_at")
    ends = [
        parse_time(span["ended_at"], f"{span['span_id']}.ended_at")
        for span in ledger["spans"]
        if span["ended_at"] is not None
    ]
    if not ends:
        return parse_time(ledger["started_at"], "started_at")
    return max(ends)


def build_rollup(
    summary_paths: list[Path],
    cohort_id: str,
    root: Path | None = None,
    predecessor_path: Path | None = None,
) -> dict:
    root = (root or repository_root()).resolve()
    summary_paths = list(summary_paths)
    predecessor_identity = None
    if predecessor_path is not None:
        predecessor_path = predecessor_path.resolve()
        errors = validate_json_file(
            predecessor_path,
            root / "schemas/community_time_to_value_rollup.schema.json",
        )
        if errors:
            raise ValueError("invalid predecessor rollup: " + "; ".join(errors))
        predecessor = read_object(predecessor_path)
        if predecessor["cohort_id"] != cohort_id:
            raise ValueError("predecessor rollup cohort_id differs")
        for value in predecessor["input_identity"]["summaries"]:
            path = Path(value["path"]).resolve()
            if not path.is_file() or sha256_file(path) != value["sha256"]:
                raise ValueError(f"predecessor summary changed: {path}")
            summary_paths.append(path)
        predecessor_identity = identity(predecessor_path)
    if not summary_paths:
        raise ValueError("at least one work-cycle summary is required")
    resolved_paths = [path.resolve() for path in summary_paths]
    if len(set(resolved_paths)) != len(resolved_paths):
        raise ValueError("duplicate work-cycle summary path")
    summary_schema = root / "schemas/community_work_cycle_summary.schema.json"
    rows = []
    cycle_ids: set[str] = set()
    ledger_paths: set[Path] = set()
    for summary_path in sorted(resolved_paths):
        errors = validate_json_file(summary_path, summary_schema)
        if errors:
            raise ValueError(
                f"invalid work-cycle summary {summary_path}: " + "; ".join(errors)
            )
        summary = read_object(summary_path)
        if summary["cycle_id"] in cycle_ids:
            raise ValueError(f"duplicate cycle_id: {summary['cycle_id']}")
        cycle_ids.add(summary["cycle_id"])
        ledger_path = Path(summary["cycle_identity"]["path"]).resolve()
        if ledger_path in ledger_paths:
            raise ValueError(f"duplicate cycle ledger: {ledger_path}")
        ledger_paths.add(ledger_path)
        if (
            not ledger_path.is_file()
            or sha256_file(ledger_path) != summary["cycle_identity"]["sha256"]
        ):
            raise ValueError(f"cycle ledger changed: {ledger_path}")
        expected = summarize(ledger_path)
        if stable(summary) != stable(expected):
            raise ValueError(f"work-cycle summary is stale or edited: {summary_path}")
        ledger = read_object(ledger_path)
        rows.append(
            {
                "summary_path": summary_path,
                "summary": summary,
                "ledger_path": ledger_path,
                "ledger": ledger,
                "started": parse_time(ledger["started_at"], "started_at"),
                "ended": cycle_end(ledger),
            }
        )
    rows.sort(key=lambda row: (row["started"], row["summary"]["cycle_id"]))
    cohort_start = min(row["started"] for row in rows)
    cohort_end = max(row["ended"] for row in rows)

    phase_seconds = {
        phase: math.fsum(float(row["summary"]["phase_seconds"][phase]) for row in rows)
        for phase in PHASES
    }
    bucket_seconds = {
        bucket: math.fsum(
            float(row["summary"]["buckets"].get(bucket, 0)) for row in rows
        )
        for bucket in BUCKETS
    }
    milestone_rows: dict[str, list[tuple[datetime, dict]]] = {
        name: [] for name in MILESTONES
    }
    for row in rows:
        for milestone in row["ledger"]["milestones"]:
            milestone_rows[milestone["kind"]].append(
                (parse_time(milestone["at"], f"{milestone['kind']}.at"), row)
            )
    milestones = {}
    for name in MILESTONES:
        observed = sorted(
            milestone_rows[name],
            key=lambda item: (item[0], item[1]["summary"]["cycle_id"]),
        )
        first_at = observed[0][0] if observed else None
        first_row = observed[0][1] if observed else None
        milestones[name] = {
            "cycles_reaching": len(observed),
            "first_at": first_at.isoformat() if first_at is not None else None,
            "elapsed_from_cohort_start_seconds": (
                (first_at - cohort_start).total_seconds()
                if first_at is not None
                else None
            ),
            "cycle_id": (
                first_row["summary"]["cycle_id"] if first_row is not None else None
            ),
            "task_id": (
                first_row["summary"]["task_id"] if first_row is not None else None
            ),
        }

    correctness = Counter(row["summary"]["outcome"]["correctness"] for row in rows)
    speedups = [
        float(value)
        for row in rows
        if (value := row["summary"]["outcome"]["best_speedup"]) is not None
    ]
    whole_model_speedups = [
        float(value)
        for row in rows
        if (value := row["summary"]["outcome"]["best_whole_model_speedup"])
        is not None
    ]
    observation_modes = Counter(row["summary"]["observation_mode"] for row in rows)
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now(),
        "claim_boundary": CLAIM_BOUNDARY,
        "cohort_id": cohort_id,
        "input_identity": {
            "summaries": [identity(row["summary_path"]) for row in rows],
            "ledgers": [identity(row["ledger_path"]) for row in rows],
        },
        "inventory": {
            "cycle_count": len(rows),
            "unique_task_count": len(
                {row["summary"]["task_id"] for row in rows}
            ),
            "prospective_exact_count": int(observation_modes["PROSPECTIVE_EXACT"]),
            "legacy_milestone_bounds_count": int(
                observation_modes["LEGACY_MILESTONE_BOUNDS"]
            ),
        },
        "cohort_clock": {
            "started_at": cohort_start.isoformat(),
            "ended_at": cohort_end.isoformat(),
            "elapsed_seconds": (cohort_end - cohort_start).total_seconds(),
            "summed_cycle_seconds": math.fsum(
                float(row["summary"]["wall_clock"]["observed_seconds"])
                for row in rows
            ),
        },
        "phase_seconds": phase_seconds,
        "bucket_seconds": bucket_seconds,
        "outcomes": {
            "correctness": {
                "PASS": int(correctness["PASS"]),
                "FAIL": int(correctness["FAIL"]),
                "NOT_RUN": int(correctness["NOT_RUN"]),
            },
            "upstream_ready_cycles": sum(
                bool(row["summary"]["outcome"]["upstream_ready"]) for row in rows
            ),
            "cycles_with_pull_request": sum(
                row["summary"]["outcome"]["pull_request_url"] is not None
                for row in rows
            ),
            "merged_cycles": sum(
                bool(row["summary"]["outcome"]["merged"]) for row in rows
            ),
            "best_speedup": max(speedups) if speedups else None,
            "best_whole_model_speedup": (
                max(whole_model_speedups) if whole_model_speedups else None
            ),
        },
        "milestones": milestones,
        "censoring": {
            "first_material_improvement_unobserved": (
                milestones["FIRST_MATERIAL_IMPROVEMENT"]["first_at"] is None
            ),
            "first_review_ready_pr_unobserved": (
                milestones["PR_READY_FOR_REVIEW"]["first_at"] is None
            ),
        },
        "limitations": [
            (
                "Only explicitly supplied summaries are included; directory "
                "globbing is intentionally unsupported."
            ),
            (
                "Summed cycle seconds are additive work-cycle observations and "
                "may exceed cohort wall time when cycles overlap."
            ),
            (
                "Legacy milestone bounds are descriptive and are never upgraded "
                "to prospective exact timing."
            ),
            "Unobserved milestones remain null and are not replaced by forecasts.",
        ],
        "status": "PASS",
    }
    if predecessor_identity is not None:
        report["input_identity"]["predecessor_rollup"] = predecessor_identity
    errors = validate_instance(
        report, read_object(root / "schemas/community_time_to_value_rollup.schema.json")
    )
    if errors:
        raise ValueError("invalid time-to-value rollup: " + "; ".join(errors))
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort-id", required=True)
    parser.add_argument("--summary", type=Path, action="append", default=[])
    parser.add_argument(
        "--predecessor",
        type=Path,
        help="reuse every hash-bound summary from a prior rollup before appending",
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_rollup(
        args.summary,
        args.cohort_id,
        predecessor_path=args.predecessor,
    )
    atomic_json(args.output.resolve(), report)
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
