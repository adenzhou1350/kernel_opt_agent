#!/usr/bin/env python3
"""Record and summarize evidence-bound optimization work-cycle timing."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

from community_knowledge import atomic_json, now, read_object, sha256_file
from schema_utils import validate_instance, validate_json_file


LEDGER_SCHEMA = "community-work-cycle-v1"
SUMMARY_SCHEMA = "community-work-cycle-summary-v1"
PAIR_BASELINE_SCHEMA = "community-work-cycle-pair-baseline-v1"
PHASES = (
    "COMMUNITY_RESEARCH",
    "BOTTLENECK_DIAGNOSIS",
    "CANDIDATE_IMPLEMENTATION",
    "COMPILE_AND_MEASURE",
    "CORRECTNESS_VALIDATION",
    "PERFORMANCE_VALIDATION",
    "WHOLE_MODEL_VALIDATION",
    "UPSTREAM_PACKAGING",
    "EXTERNAL_WAIT",
    "UNATTRIBUTED_LEGACY_WORK",
)
MILESTONES = (
    "FIRST_CANDIDATE_PROPOSED",
    "FIRST_SCREEN_CORRECT",
    "FIRST_MATERIAL_IMPROVEMENT",
    "FIRST_QUALIFIED_RESULT",
    "UPSTREAM_PACKAGE_READY",
    "PR_DRAFT_OPENED",
    "PR_READY_FOR_REVIEW",
    "PR_MERGED",
)


def root() -> Path:
    return Path(__file__).resolve().parents[1]


def parse_time(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{label} must be ISO-8601") from error
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc)


def timestamp(value: str | None) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat()
    parse_time(value, "timestamp")
    return value


def evidence_identity(path: Path) -> dict:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {"path": path.as_posix(), "sha256": sha256_file(path)}


def evidence_path(identity: dict, ledger_path: Path) -> Path:
    path = Path(identity["path"])
    return path if path.is_absolute() else (ledger_path.parent / path).resolve()


def validate_ledger_object(
    ledger: dict, ledger_path: Path, allow_active: bool = True
) -> dict:
    ledger_path = ledger_path.resolve()
    errors = validate_instance(
        ledger, read_object(root() / "schemas/community_work_cycle.schema.json")
    )
    if errors:
        raise ValueError("invalid work-cycle ledger: " + "; ".join(errors))
    if ledger["schema_version"] != LEDGER_SCHEMA:
        raise ValueError("unsupported work-cycle ledger")
    cycle_start = parse_time(ledger["started_at"], "started_at")
    span_ids: set[str] = set()
    intervals: list[tuple[datetime, datetime, str]] = []
    for span in ledger["spans"]:
        if span["span_id"] in span_ids:
            raise ValueError(f"duplicate span_id: {span['span_id']}")
        span_ids.add(span["span_id"])
        started = parse_time(span["started_at"], f"{span['span_id']}.started_at")
        if started < cycle_start:
            raise ValueError(f"span starts before cycle: {span['span_id']}")
        ended_value = span["ended_at"]
        if span["status"] == "ACTIVE":
            if ended_value is not None:
                raise ValueError(f"active span has ended_at: {span['span_id']}")
            if not allow_active:
                raise ValueError(f"cannot summarize active span: {span['span_id']}")
        else:
            if ended_value is None:
                raise ValueError(f"closed span lacks ended_at: {span['span_id']}")
            ended = parse_time(ended_value, f"{span['span_id']}.ended_at")
            if ended < started:
                raise ValueError(f"negative span: {span['span_id']}")
            if not span["evidence"]:
                raise ValueError(f"closed span lacks evidence: {span['span_id']}")
            intervals.append((started, ended, span["span_id"]))
        for identity in span["evidence"]:
            evidence = evidence_path(identity, ledger_path)
            if not evidence.is_file() or sha256_file(evidence) != identity["sha256"]:
                raise ValueError(f"span evidence changed: {identity['path']}")
    intervals.sort()
    for previous, current in zip(intervals, intervals[1:]):
        if current[0] < previous[1]:
            raise ValueError(f"primary spans overlap: {previous[2]} and {current[2]}")

    milestones: dict[str, datetime] = {}
    for item in ledger["milestones"]:
        kind = item["kind"]
        if kind in milestones:
            raise ValueError(f"duplicate milestone: {kind}")
        at = parse_time(item["at"], f"{kind}.at")
        if at < cycle_start:
            raise ValueError(f"milestone precedes cycle: {kind}")
        milestones[kind] = at
        for identity in item["evidence"]:
            evidence = evidence_path(identity, ledger_path)
            if not evidence.is_file() or sha256_file(evidence) != identity["sha256"]:
                raise ValueError(f"milestone evidence changed: {identity['path']}")

    ordered = [
        "FIRST_CANDIDATE_PROPOSED",
        "FIRST_SCREEN_CORRECT",
        "FIRST_MATERIAL_IMPROVEMENT",
        "FIRST_QUALIFIED_RESULT",
        "UPSTREAM_PACKAGE_READY",
        "PR_READY_FOR_REVIEW",
        "PR_MERGED",
    ]
    seen = [(kind, milestones[kind]) for kind in ordered if kind in milestones]
    for previous, current in zip(seen, seen[1:]):
        if current[1] < previous[1]:
            raise ValueError(f"milestone order violated: {previous[0]} -> {current[0]}")
    if "PR_DRAFT_OPENED" in milestones and "PR_READY_FOR_REVIEW" in milestones:
        if milestones["PR_READY_FOR_REVIEW"] < milestones["PR_DRAFT_OPENED"]:
            raise ValueError("PR_READY_FOR_REVIEW precedes PR_DRAFT_OPENED")

    outcome = ledger["outcome"]
    if "FIRST_MATERIAL_IMPROVEMENT" in milestones:
        if outcome["correctness"] != "PASS":
            raise ValueError("material improvement requires correctness PASS")
        if (
            outcome["best_speedup"] is None
            or outcome["best_speedup"] < ledger["minimum_material_speedup"]
        ):
            raise ValueError("material improvement does not meet frozen threshold")
    if "UPSTREAM_PACKAGE_READY" in milestones and not outcome["upstream_ready"]:
        raise ValueError("upstream-ready milestone conflicts with outcome")
    pr_milestones = {"PR_DRAFT_OPENED", "PR_READY_FOR_REVIEW", "PR_MERGED"}
    if pr_milestones & milestones.keys() and outcome["pull_request_url"] is None:
        raise ValueError("PR milestone requires pull_request_url")
    if "PR_MERGED" in milestones and not outcome["merged"]:
        raise ValueError("PR_MERGED conflicts with outcome")
    return ledger


def validate_ledger(path: Path, allow_active: bool = True) -> dict:
    path = path.resolve()
    return validate_ledger_object(read_object(path), path, allow_active)


def write_ledger(path: Path, ledger: dict) -> None:
    """Validate a proposed mutation before replacing the authoritative ledger."""
    path = path.resolve()
    validate_ledger_object(ledger, path)
    atomic_json(path, ledger)


def summarize(path: Path) -> dict:
    path = path.resolve()
    ledger = validate_ledger(path, allow_active=False)
    cycle_start = parse_time(ledger["started_at"], "started_at")
    phase_seconds = {phase: 0.0 for phase in PHASES}
    end_points = [cycle_start]
    for span in ledger["spans"]:
        started = parse_time(span["started_at"], "span.started_at")
        ended = parse_time(span["ended_at"], "span.ended_at")
        phase_seconds[span["phase"]] += (ended - started).total_seconds()
        end_points.append(ended)
    milestone_times = {
        item["kind"]: parse_time(item["at"], item["kind"])
        for item in ledger["milestones"]
    }
    end_points.extend(milestone_times.values())
    observed = (max(end_points) - cycle_start).total_seconds()
    accounted = sum(phase_seconds.values())
    time_to = {
        kind: (
            (milestone_times[kind] - cycle_start).total_seconds()
            if kind in milestone_times
            else None
        )
        for kind in MILESTONES
    }
    report = {
        "schema_version": SUMMARY_SCHEMA,
        "generated_at": now(),
        "claim_boundary": "DESCRIPTIVE_TIMING_ONLY",
        "cycle_identity": {
            "path": path.as_posix(),
            "sha256": sha256_file(path),
        },
        "cycle_id": ledger["cycle_id"],
        "task_id": ledger["task_id"],
        "observation_mode": ledger["observation_mode"],
        "phase_seconds": phase_seconds,
        "buckets": {
            "research_seconds": phase_seconds["COMMUNITY_RESEARCH"]
            + phase_seconds["BOTTLENECK_DIAGNOSIS"],
            "implementation_seconds": phase_seconds["CANDIDATE_IMPLEMENTATION"],
            "compute_seconds": phase_seconds["COMPILE_AND_MEASURE"],
            "validation_seconds": phase_seconds["CORRECTNESS_VALIDATION"]
            + phase_seconds["PERFORMANCE_VALIDATION"]
            + phase_seconds["WHOLE_MODEL_VALIDATION"],
            "packaging_seconds": phase_seconds["UPSTREAM_PACKAGING"],
            "external_wait_seconds": phase_seconds["EXTERNAL_WAIT"],
            "unattributed_legacy_seconds": phase_seconds["UNATTRIBUTED_LEGACY_WORK"],
        },
        "wall_clock": {
            "observed_seconds": observed,
            "accounted_seconds": accounted,
            "unaccounted_seconds": max(0.0, observed - accounted),
        },
        "time_to_milestone_seconds": time_to,
        "outcome": ledger["outcome"],
    }
    errors = validate_instance(
        report,
        read_object(root() / "schemas/community_work_cycle_summary.schema.json"),
    )
    if errors:
        raise ValueError("invalid work-cycle summary: " + "; ".join(errors))
    return report


def read_bound_identity(identity: dict, label: str) -> tuple[Path, dict]:
    path = Path(identity["path"]).resolve()
    if not path.is_file() or sha256_file(path) != identity["sha256"]:
        raise ValueError(f"{label} identity changed")
    return path, read_object(path)


def pair_baseline(paths: list[Path]) -> dict:
    rows = []
    for path in paths:
        path = path.resolve()
        errors = validate_json_file(
            path, root() / "schemas/community_ab_report.schema.json"
        )
        if errors:
            raise ValueError("invalid paired report: " + "; ".join(errors))
        pair = read_object(path)
        _, control = read_bound_identity(
            pair["control_assessment"], "control assessment"
        )
        _, augmented = read_bound_identity(
            pair["community_assessment"], "community assessment"
        )

        def arm(assessment: dict) -> dict:
            return {
                "elapsed_seconds": assessment["budget_usage"]["elapsed_seconds"],
                "time_to_first_correct_seconds": assessment["metrics"][
                    "time_to_first_correct_seconds"
                ],
                "time_to_first_improvement_seconds": assessment["metrics"][
                    "time_to_first_improvement_seconds"
                ],
                "best_speedup": assessment["metrics"]["best_speedup"],
                "upstream_ready_count": assessment["metrics"]["upstream_ready_count"],
            }

        rows.append(
            {
                "pair_identity": {"path": path.as_posix(), "sha256": sha256_file(path)},
                "suite_id": pair["suite_id"],
                "task_id": pair["task_id"],
                "repeat_index": pair["repeat_index"],
                "control": arm(control),
                "community_augmented": arm(augmented),
            }
        )

    metrics = (
        "elapsed_seconds",
        "time_to_first_correct_seconds",
        "time_to_first_improvement_seconds",
        "best_speedup",
        "upstream_ready_count",
    )
    arm_medians = {}
    for arm_name in ("control", "community_augmented"):
        arm_medians[arm_name] = {}
        for metric in metrics:
            values = [
                row[arm_name][metric]
                for row in rows
                if row[arm_name][metric] is not None
            ]
            arm_medians[arm_name][metric] = median(values) if values else None
    report = {
        "schema_version": PAIR_BASELINE_SCHEMA,
        "generated_at": now(),
        "claim_boundary": "EXISTING_PAIRED_MILESTONES_NOT_PHASE_ATTRIBUTION",
        "pair_count": len(rows),
        "pairs": rows,
        "arm_medians": arm_medians,
        "limitations": [
            "Legacy trial results record candidate proposal/evaluation milestones but not non-overlapping research, implementation, compute, validation and packaging spans.",
            "Phase allocation must remain unattributed for these trials; prospective work-cycle ledgers provide exact spans going forward.",
        ],
    }
    errors = validate_instance(
        report,
        read_object(root() / "schemas/community_work_cycle_pair_baseline.schema.json"),
    )
    if errors:
        raise ValueError("invalid paired timing baseline: " + "; ".join(errors))
    return report


def init_ledger(args: argparse.Namespace) -> dict:
    if args.output.exists():
        raise FileExistsError(args.output)
    ledger = {
        "schema_version": LEDGER_SCHEMA,
        "cycle_id": args.cycle_id,
        "task_id": args.task_id,
        "started_at": timestamp(args.started_at),
        "observation_mode": args.observation_mode,
        "claim_boundary": "WORK_CYCLE_TIMING_NOT_PERFORMANCE_CAUSALITY",
        "minimum_material_speedup": args.minimum_material_speedup,
        "spans": [],
        "milestones": [],
        "outcome": {
            "correctness": "NOT_RUN",
            "best_speedup": None,
            "best_whole_model_speedup": None,
            "upstream_ready": False,
            "pull_request_url": None,
            "merged": False,
        },
    }
    write_ledger(args.output, ledger)
    return ledger


def start_phase(args: argparse.Namespace) -> dict:
    ledger = validate_ledger(args.ledger)
    if any(span["status"] == "ACTIVE" for span in ledger["spans"]):
        raise ValueError("another primary phase is already active")
    if any(span["span_id"] == args.span_id for span in ledger["spans"]):
        raise ValueError(f"duplicate span_id: {args.span_id}")
    ledger["spans"].append(
        {
            "span_id": args.span_id,
            "phase": args.phase,
            "actor": args.actor,
            "resource_id": args.resource_id,
            "started_at": timestamp(args.at),
            "ended_at": None,
            "status": "ACTIVE",
            "evidence": [],
        }
    )
    write_ledger(args.ledger, ledger)
    return ledger


def end_phase(args: argparse.Namespace) -> dict:
    ledger = validate_ledger(args.ledger)
    matching = [span for span in ledger["spans"] if span["span_id"] == args.span_id]
    if len(matching) != 1 or matching[0]["status"] != "ACTIVE":
        raise ValueError("span is not active")
    span = matching[0]
    span["ended_at"] = timestamp(args.at)
    span["status"] = args.status
    span["evidence"] = [evidence_identity(path) for path in args.evidence]
    write_ledger(args.ledger, ledger)
    return ledger


def mark(args: argparse.Namespace) -> dict:
    ledger = validate_ledger(args.ledger)
    if any(item["kind"] == args.kind for item in ledger["milestones"]):
        raise ValueError(f"duplicate milestone: {args.kind}")
    ledger["milestones"].append(
        {
            "kind": args.kind,
            "at": timestamp(args.at),
            "evidence": [evidence_identity(path) for path in args.evidence],
        }
    )
    write_ledger(args.ledger, ledger)
    return ledger


def record_outcome(args: argparse.Namespace) -> dict:
    ledger = validate_ledger(args.ledger)
    ledger["outcome"] = {
        "correctness": args.correctness,
        "best_speedup": args.best_speedup,
        "best_whole_model_speedup": args.best_whole_model_speedup,
        "upstream_ready": args.upstream_ready,
        "pull_request_url": args.pull_request_url,
        "merged": args.merged,
    }
    write_ledger(args.ledger, ledger)
    return ledger


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    init = commands.add_parser("init")
    init.add_argument("--cycle-id", required=True)
    init.add_argument("--task-id", required=True)
    init.add_argument("--started-at")
    init.add_argument(
        "--observation-mode",
        choices=("PROSPECTIVE_EXACT", "LEGACY_MILESTONE_BOUNDS"),
        default="PROSPECTIVE_EXACT",
    )
    init.add_argument("--minimum-material-speedup", type=float, default=1.02)
    init.add_argument("--output", type=Path, required=True)
    start = commands.add_parser("start-phase")
    start.add_argument("--ledger", type=Path, required=True)
    start.add_argument("--span-id", required=True)
    start.add_argument("--phase", choices=PHASES, required=True)
    start.add_argument(
        "--actor", choices=("AGENT", "CPU", "GPU", "EXTERNAL"), required=True
    )
    start.add_argument("--resource-id")
    start.add_argument("--at")
    end = commands.add_parser("end-phase")
    end.add_argument("--ledger", type=Path, required=True)
    end.add_argument("--span-id", required=True)
    end.add_argument(
        "--status", choices=("COMPLETE", "INTERRUPTED"), default="COMPLETE"
    )
    end.add_argument("--at")
    end.add_argument("--evidence", type=Path, action="append", required=True)
    milestone = commands.add_parser("mark")
    milestone.add_argument("--ledger", type=Path, required=True)
    milestone.add_argument("--kind", choices=MILESTONES, required=True)
    milestone.add_argument("--at")
    milestone.add_argument("--evidence", type=Path, action="append", required=True)
    outcome = commands.add_parser("record-outcome")
    outcome.add_argument("--ledger", type=Path, required=True)
    outcome.add_argument(
        "--correctness", choices=("PASS", "FAIL", "NOT_RUN"), required=True
    )
    outcome.add_argument("--best-speedup", type=float)
    outcome.add_argument("--best-whole-model-speedup", type=float)
    outcome.add_argument("--upstream-ready", action="store_true")
    outcome.add_argument("--pull-request-url")
    outcome.add_argument("--merged", action="store_true")
    validate = commands.add_parser("validate")
    validate.add_argument("--ledger", type=Path, required=True)
    summary = commands.add_parser("summarize")
    summary.add_argument("--ledger", type=Path, required=True)
    summary.add_argument("--output", type=Path, required=True)
    pairs = commands.add_parser("summarize-pairs")
    pairs.add_argument("--pair", type=Path, action="append", required=True)
    pairs.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.operation == "init":
        result = init_ledger(args)
    elif args.operation == "start-phase":
        result = start_phase(args)
    elif args.operation == "end-phase":
        result = end_phase(args)
    elif args.operation == "mark":
        result = mark(args)
    elif args.operation == "record-outcome":
        result = record_outcome(args)
    elif args.operation == "validate":
        ledger = validate_ledger(args.ledger)
        result = {"status": "PASS", "cycle_id": ledger["cycle_id"]}
    elif args.operation == "summarize":
        result = summarize(args.ledger)
        atomic_json(args.output.resolve(), result)
    else:
        result = pair_baseline(args.pair)
        atomic_json(args.output.resolve(), result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
