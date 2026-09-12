#!/usr/bin/env python3
"""Record and summarize evidence-bound optimization work-cycle timing."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

from artifact_io import atomic_json, now, read_object, sha256_file
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
    "ENVIRONMENT_SETUP",
    "GOVERNANCE_VALIDATION",
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
PR_STAGE_MILESTONES = {
    "DRAFT": "PR_DRAFT_OPENED",
    "READY": "PR_READY_FOR_REVIEW",
    "MERGED": "PR_MERGED",
}
AUDIT_EXCLUDED_DIRS = {".git", ".venv", "__pycache__", "node_modules"}


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
    explicit_overhead_spans = sum(
        span["phase"] in {"ENVIRONMENT_SETUP", "GOVERNANCE_VALIDATION"}
        for span in ledger["spans"]
    )
    attributed_active = (
        accounted
        - phase_seconds["EXTERNAL_WAIT"]
        - phase_seconds["UNATTRIBUTED_LEGACY_WORK"]
    )
    overhead_seconds = (
        phase_seconds["ENVIRONMENT_SETUP"] + phase_seconds["GOVERNANCE_VALIDATION"]
    )
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
            "environment_seconds": phase_seconds["ENVIRONMENT_SETUP"],
            "governance_seconds": phase_seconds["GOVERNANCE_VALIDATION"],
            "external_wait_seconds": phase_seconds["EXTERNAL_WAIT"],
            "unattributed_legacy_seconds": phase_seconds["UNATTRIBUTED_LEGACY_WORK"],
        },
        "wall_clock": {
            "observed_seconds": observed,
            "accounted_seconds": accounted,
            "unaccounted_seconds": max(0.0, observed - accounted),
        },
        "phase_coverage": {
            "explicit_environment_or_governance_spans": explicit_overhead_spans,
            "environment_governance_measurement_status": (
                "MEASURED" if explicit_overhead_spans else "NOT_SEPARATELY_RECORDED"
            ),
        },
        "ratios": {
            "environment_governance_share_of_attributed_active": (
                overhead_seconds / attributed_active
                if explicit_overhead_spans and attributed_active > 0
                else None
            ),
            "environment_governance_share_of_accounted": (
                overhead_seconds / accounted
                if explicit_overhead_spans and accounted > 0
                else None
            ),
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


def audit_roots(
    roots: list[Path], at: str | None = None, max_active_phase_seconds: float = 21600
) -> dict:
    """Find prospective ledgers whose timing instrumentation needs attention.

    This is deliberately a read-only operational audit rather than another
    evidence artifact schema.  It lets a controller inspect existing lanes
    without asking each lane to restate its status.
    """
    if max_active_phase_seconds <= 0:
        raise ValueError("max_active_phase_seconds must be positive")
    observed_at = parse_time(timestamp(at), "at")
    rows = []
    invalid = []
    seen: set[Path] = set()
    for configured_root in roots:
        configured_root = configured_root.resolve()
        candidates = (
            [configured_root]
            if configured_root.is_file()
            else configured_root.rglob("*.json")
            if configured_root.is_dir()
            else []
        )
        for path in candidates:
            path = path.resolve()
            if path in seen or any(part in AUDIT_EXCLUDED_DIRS for part in path.parts):
                continue
            seen.add(path)
            try:
                if path.stat().st_size > 2 * 1024 * 1024:
                    continue
                raw = read_object(path)
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                continue
            if raw.get("schema_version") != LEDGER_SCHEMA:
                continue
            try:
                ledger = validate_ledger_object(raw, path)
            except (OSError, ValueError) as error:
                invalid.append({"path": path.as_posix(), "error": str(error)})
                continue
            if ledger["observation_mode"] != "PROSPECTIVE_EXACT":
                continue
            active = [span for span in ledger["spans"] if span["status"] == "ACTIVE"]
            closed = [span for span in ledger["spans"] if span["status"] != "ACTIVE"]
            explicitly_attributed = [
                span
                for span in ledger["spans"]
                if span["phase"] != "UNATTRIBUTED_LEGACY_WORK"
            ]
            overhead = [
                span
                for span in ledger["spans"]
                if span["phase"] in {"ENVIRONMENT_SETUP", "GOVERNANCE_VALIDATION"}
            ]
            active_seconds = None
            if active:
                active_seconds = (
                    observed_at
                    - parse_time(active[0]["started_at"], "active.started_at")
                ).total_seconds()
                if active_seconds < 0:
                    raise ValueError(f"audit time precedes active phase: {path}")
            milestone_kinds = {item["kind"] for item in ledger["milestones"]}
            alerts = []
            if not explicitly_attributed:
                alerts.append("NO_EXACT_PHASE_ATTRIBUTION")
            if not ledger["spans"]:
                alerts.append("NO_PRIMARY_PHASE")
            if active_seconds is not None and active_seconds > max_active_phase_seconds:
                alerts.append("ACTIVE_PHASE_OVER_THRESHOLD")
            if "PR_MERGED" in milestone_kinds:
                delivery_stage = "MERGED"
            elif "PR_READY_FOR_REVIEW" in milestone_kinds:
                delivery_stage = "READY"
            elif "PR_DRAFT_OPENED" in milestone_kinds:
                delivery_stage = "DRAFT"
            else:
                delivery_stage = "PRE_PR"
            rows.append(
                {
                    "cycle_id": ledger["cycle_id"],
                    "task_id": ledger["task_id"],
                    "ledger_path": path.as_posix(),
                    "active_phase": active[0]["phase"] if active else None,
                    "active_phase_seconds": active_seconds,
                    "closed_span_count": len(closed),
                    "phases_observed": sorted(
                        {span["phase"] for span in ledger["spans"]}
                    ),
                    "exact_phase_attribution": bool(explicitly_attributed),
                    "explicit_environment_governance": bool(overhead),
                    "delivery_stage": delivery_stage,
                    "alerts": alerts,
                }
            )
    rows.sort(key=lambda row: (row["task_id"], row["cycle_id"]))
    tracked = sum(row["exact_phase_attribution"] for row in rows)
    overhead_observed = sum(row["explicit_environment_governance"] for row in rows)
    if not rows:
        status = "NO_PROSPECTIVE_CYCLES"
    elif not tracked:
        status = "BLIND"
    elif tracked < len(rows):
        status = "PARTIAL"
    else:
        status = "TRACKED"
    if not rows:
        overhead_status = "NO_PROSPECTIVE_CYCLES"
    elif not overhead_observed:
        overhead_status = "BLIND"
    elif overhead_observed < len(rows):
        overhead_status = "PARTIAL"
    else:
        overhead_status = "MEASURED"
    return {
        "status": status,
        "environment_governance_measurement_status": overhead_status,
        "claim_boundary": "READ_ONLY_CURRENT_LEDGER_OPERABILITY_NOT_PERFORMANCE_CAUSALITY",
        "observed_at": observed_at.isoformat(),
        "max_active_phase_seconds": max_active_phase_seconds,
        "prospective_cycle_count": len(rows),
        "exact_phase_tracked_count": tracked,
        "explicit_environment_governance_count": overhead_observed,
        "environment_governance_measurement_debt_count": len(rows) - overhead_observed,
        "attention_cycle_count": sum(bool(row["alerts"]) for row in rows),
        "invalid_ledger_count": len(invalid),
        "invalid_ledgers": invalid,
        "cycles": rows,
    }


def init_ledger(args: argparse.Namespace) -> dict:
    if args.output.exists():
        raise FileExistsError(args.output)
    candidate_evidence = getattr(args, "candidate_evidence", None) or []
    if candidate_evidence and args.observation_mode != "PROSPECTIVE_EXACT":
        raise ValueError(
            "candidate evidence bootstrap requires PROSPECTIVE_EXACT observation"
        )
    started_at = timestamp(args.started_at)
    candidate_identities = [evidence_identity(path) for path in candidate_evidence]
    initial_phase = getattr(args, "initial_phase", None)
    if args.observation_mode == "PROSPECTIVE_EXACT" and initial_phase is None:
        initial_phase = "BOTTLENECK_DIAGNOSIS"
    spans = []
    if initial_phase is not None:
        spans.append(
            {
                "span_id": getattr(args, "initial_span_id", "initial"),
                "phase": initial_phase,
                "actor": getattr(args, "initial_actor", "AGENT"),
                "resource_id": getattr(args, "initial_resource_id", None),
                "started_at": started_at,
                "ended_at": None,
                "status": "ACTIVE",
                "evidence": [],
            }
        )
    ledger = {
        "schema_version": LEDGER_SCHEMA,
        "cycle_id": args.cycle_id,
        "task_id": args.task_id,
        "started_at": started_at,
        "observation_mode": args.observation_mode,
        "claim_boundary": "WORK_CYCLE_TIMING_NOT_PERFORMANCE_CAUSALITY",
        "minimum_material_speedup": args.minimum_material_speedup,
        "spans": spans,
        "milestones": (
            [
                {
                    "kind": "FIRST_CANDIDATE_PROPOSED",
                    "at": started_at,
                    "evidence": candidate_identities,
                }
            ]
            if candidate_identities
            else []
        ),
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


def receipt_field(receipt: dict, name: str, label: str):
    """Read one top-level field from a machine receipt without guessing aliases."""

    if name not in receipt:
        raise ValueError(f"receipt lacks {label} field: {name}")
    return receipt[name]


def import_phase_receipt(args: argparse.Namespace) -> dict:
    """Import exact wall time from an immutable, already-produced machine receipt."""

    ledger_path = args.ledger.resolve()
    ledger = validate_ledger(ledger_path)
    if ledger["observation_mode"] != "PROSPECTIVE_EXACT":
        raise ValueError("receipt import requires a PROSPECTIVE_EXACT ledger")
    active = [span for span in ledger["spans"] if span["status"] == "ACTIVE"]
    if len(active) > 1:
        raise ValueError("more than one primary phase is active")
    if any(span["span_id"] == args.span_id for span in ledger["spans"]):
        raise ValueError(f"duplicate span_id: {args.span_id}")

    receipt_path = args.receipt.resolve()
    receipt = read_object(receipt_path)
    started_value = receipt_field(receipt, args.started_at_field, "start timestamp")
    ended_value = receipt_field(receipt, args.ended_at_field, "end timestamp")
    if not isinstance(started_value, str) or not isinstance(ended_value, str):
        raise ValueError("receipt timestamps must be strings")
    started = parse_time(started_value, args.started_at_field)
    ended = parse_time(ended_value, args.ended_at_field)
    if ended < started:
        raise ValueError("receipt end timestamp precedes start timestamp")

    measured_seconds = (ended - started).total_seconds()
    if args.duration_field is not None:
        duration = receipt_field(receipt, args.duration_field, "duration")
        if isinstance(duration, bool) or not isinstance(duration, (int, float)):
            raise ValueError("receipt duration must be a number")
        if duration < 0:
            raise ValueError("receipt duration must be non-negative")
        tolerance = max(1.0, measured_seconds * 0.01)
        if abs(float(duration) - measured_seconds) > tolerance:
            raise ValueError("receipt duration conflicts with its timestamps")

    receipt_identity = evidence_identity(receipt_path)
    if active:
        if started < parse_time(active[0]["started_at"], "active.started_at"):
            raise ValueError("receipt starts before the active phase")
        active[0]["ended_at"] = started_value
        active[0]["status"] = "COMPLETE"
        active[0]["evidence"] = [receipt_identity]

    ledger["spans"].append(
        {
            "span_id": args.span_id,
            "phase": args.phase,
            "actor": args.actor,
            "resource_id": args.resource_id,
            "started_at": started_value,
            "ended_at": ended_value,
            "status": args.status,
            "evidence": [receipt_identity],
        }
    )
    write_ledger(ledger_path, ledger)
    return ledger


def switch_phase(args: argparse.Namespace) -> dict:
    """Close the active phase and start its successor at one shared timestamp."""
    ledger = validate_ledger(args.ledger)
    active = [span for span in ledger["spans"] if span["status"] == "ACTIVE"]
    if len(active) != 1:
        raise ValueError("exactly one primary phase must be active")
    if any(span["span_id"] == args.span_id for span in ledger["spans"]):
        raise ValueError(f"duplicate span_id: {args.span_id}")
    transition_at = timestamp(args.at)
    parse_time(transition_at, "transition_at")
    if parse_time(transition_at, "transition_at") < parse_time(
        active[0]["started_at"], "active.started_at"
    ):
        raise ValueError("phase transition precedes active phase")
    active[0]["ended_at"] = transition_at
    active[0]["status"] = args.status
    active[0]["evidence"] = [evidence_identity(path) for path in args.evidence]
    ledger["spans"].append(
        {
            "span_id": args.span_id,
            "phase": args.phase,
            "actor": args.actor,
            "resource_id": args.resource_id,
            "started_at": transition_at,
            "ended_at": None,
            "status": "ACTIVE",
            "evidence": [],
        }
    )
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


def record_pr_stage(args: argparse.Namespace) -> dict:
    """Atomically bind a PR URL and one observed GitHub delivery stage."""
    ledger = validate_ledger(args.ledger)
    kind = PR_STAGE_MILESTONES[args.stage]
    milestones = {item["kind"] for item in ledger["milestones"]}
    if kind in milestones:
        raise ValueError(f"duplicate milestone: {kind}")
    existing_url = ledger["outcome"]["pull_request_url"]
    if existing_url is not None and existing_url != args.url:
        raise ValueError("pull request URL changed within one work cycle")
    if args.stage == "READY" and "PR_DRAFT_OPENED" not in milestones:
        raise ValueError("READY requires an observed PR_DRAFT_OPENED milestone")
    if args.stage == "MERGED" and "PR_READY_FOR_REVIEW" not in milestones:
        raise ValueError("MERGED requires an observed PR_READY_FOR_REVIEW milestone")
    ledger["outcome"]["pull_request_url"] = args.url
    if args.stage == "MERGED":
        ledger["outcome"]["merged"] = True
    ledger["milestones"].append(
        {
            "kind": kind,
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


def run_phase_command(args: argparse.Namespace) -> tuple[dict, int]:
    """Run one command inside a phase and close the span on every bounded outcome."""

    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        raise ValueError("run-phase requires a command after --")
    if args.timeout_seconds is not None and args.timeout_seconds <= 0:
        raise ValueError("timeout-seconds must be positive")
    receipt_path = args.receipt.resolve()
    if receipt_path.exists():
        raise FileExistsError(receipt_path)
    cwd = args.cwd.resolve()
    if not cwd.is_dir():
        raise NotADirectoryError(cwd)

    ledger = validate_ledger(args.ledger)
    started_at = timestamp(None)
    start_phase(
        argparse.Namespace(
            ledger=args.ledger,
            span_id=args.span_id,
            phase=args.phase,
            actor=args.actor,
            resource_id=args.resource_id,
            at=started_at,
        )
    )
    monotonic_started = time.monotonic()
    exit_code: int | None = None
    error: str | None = None
    outcome = "PASS"
    try:
        process = subprocess.run(
            command,
            cwd=cwd,
            timeout=args.timeout_seconds,
            check=False,
        )
        exit_code = process.returncode
        if exit_code != 0:
            outcome = "COMMAND_FAILED"
    except subprocess.TimeoutExpired:
        outcome = "TIMED_OUT"
        exit_code = 124
        error = f"command exceeded {args.timeout_seconds} seconds"
    except OSError as launch_error:
        outcome = "LAUNCH_FAILED"
        exit_code = 127
        error = f"{type(launch_error).__name__}: {launch_error}"
    ended_at = timestamp(None)
    span_status = "COMPLETE" if outcome == "PASS" else "INTERRUPTED"
    receipt = {
        "schema_version": "community-phase-command-receipt-v1",
        "claim_boundary": "COMMAND_WALL_TIME_AND_EXIT_STATUS_NOT_RESULT_CORRECTNESS",
        "cycle_id": ledger["cycle_id"],
        "task_id": ledger["task_id"],
        "span_id": args.span_id,
        "phase": args.phase,
        "actor": args.actor,
        "resource_id": args.resource_id,
        "started_at": started_at,
        "ended_at": ended_at,
        "duration_seconds": max(0.0, time.monotonic() - monotonic_started),
        "working_directory": cwd.as_posix(),
        "command": command,
        "timeout_seconds": args.timeout_seconds,
        "outcome": {
            "status": outcome,
            "exit_code": exit_code,
            "span_status": span_status,
            "error": error,
        },
    }
    errors = validate_instance(
        receipt,
        read_object(root() / "schemas/community_phase_command_receipt.schema.json"),
    )
    if errors:
        raise ValueError("invalid phase command receipt: " + "; ".join(errors))
    atomic_json(receipt_path, receipt)
    end_phase(
        argparse.Namespace(
            ledger=args.ledger,
            span_id=args.span_id,
            at=ended_at,
            status=span_status,
            evidence=[receipt_path],
        )
    )
    return receipt, int(exit_code)


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
    init.add_argument(
        "--candidate-evidence",
        type=Path,
        action="append",
        help=(
            "atomically bind candidate-selection evidence and mark "
            "FIRST_CANDIDATE_PROPOSED"
        ),
    )
    init.add_argument("--initial-phase", choices=PHASES)
    init.add_argument("--initial-span-id", default="initial")
    init.add_argument(
        "--initial-actor", choices=("AGENT", "CPU", "GPU", "EXTERNAL"), default="AGENT"
    )
    init.add_argument("--initial-resource-id")
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
    switch = commands.add_parser("switch-phase")
    switch.add_argument("--ledger", type=Path, required=True)
    switch.add_argument("--span-id", required=True)
    switch.add_argument("--phase", choices=PHASES, required=True)
    switch.add_argument(
        "--actor", choices=("AGENT", "CPU", "GPU", "EXTERNAL"), required=True
    )
    switch.add_argument("--resource-id")
    switch.add_argument(
        "--status", choices=("COMPLETE", "INTERRUPTED"), default="COMPLETE"
    )
    switch.add_argument("--at")
    switch.add_argument("--evidence", type=Path, action="append", required=True)
    run = commands.add_parser("run-phase")
    run.add_argument("--ledger", type=Path, required=True)
    run.add_argument("--span-id", required=True)
    run.add_argument("--phase", choices=PHASES, required=True)
    run.add_argument(
        "--actor", choices=("AGENT", "CPU", "GPU", "EXTERNAL"), required=True
    )
    run.add_argument("--resource-id")
    run.add_argument("--cwd", type=Path, default=Path.cwd())
    run.add_argument("--timeout-seconds", type=float)
    run.add_argument("--receipt", type=Path, required=True)
    run.add_argument("command", nargs=argparse.REMAINDER)
    imported = commands.add_parser("import-phase-receipt")
    imported.add_argument("--ledger", type=Path, required=True)
    imported.add_argument("--span-id", required=True)
    imported.add_argument("--phase", choices=PHASES, required=True)
    imported.add_argument(
        "--actor", choices=("AGENT", "CPU", "GPU", "EXTERNAL"), required=True
    )
    imported.add_argument("--resource-id")
    imported.add_argument("--receipt", type=Path, required=True)
    imported.add_argument("--started-at-field", default="started_at")
    imported.add_argument("--ended-at-field", default="finished_at")
    imported.add_argument("--duration-field")
    imported.add_argument(
        "--status", choices=("COMPLETE", "INTERRUPTED"), required=True
    )
    milestone = commands.add_parser("mark")
    milestone.add_argument("--ledger", type=Path, required=True)
    milestone.add_argument("--kind", choices=MILESTONES, required=True)
    milestone.add_argument("--at")
    milestone.add_argument("--evidence", type=Path, action="append", required=True)
    pr_stage = commands.add_parser("record-pr-stage")
    pr_stage.add_argument("--ledger", type=Path, required=True)
    pr_stage.add_argument("--stage", choices=tuple(PR_STAGE_MILESTONES), required=True)
    pr_stage.add_argument("--url", required=True)
    pr_stage.add_argument("--at")
    pr_stage.add_argument("--evidence", type=Path, action="append", required=True)
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
    audit = commands.add_parser("audit-root")
    audit.add_argument("--root", type=Path, action="append", required=True)
    audit.add_argument("--at")
    audit.add_argument("--max-active-phase-seconds", type=float, default=21600)
    audit.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    exit_code = 0
    if args.operation == "init":
        result = init_ledger(args)
    elif args.operation == "start-phase":
        result = start_phase(args)
    elif args.operation == "end-phase":
        result = end_phase(args)
    elif args.operation == "switch-phase":
        result = switch_phase(args)
    elif args.operation == "run-phase":
        result, exit_code = run_phase_command(args)
    elif args.operation == "import-phase-receipt":
        result = import_phase_receipt(args)
    elif args.operation == "mark":
        result = mark(args)
    elif args.operation == "record-pr-stage":
        result = record_pr_stage(args)
    elif args.operation == "record-outcome":
        result = record_outcome(args)
    elif args.operation == "validate":
        ledger = validate_ledger(args.ledger)
        result = {"status": "PASS", "cycle_id": ledger["cycle_id"]}
    elif args.operation == "summarize":
        result = summarize(args.ledger)
        atomic_json(args.output.resolve(), result)
    elif args.operation == "summarize-pairs":
        result = pair_baseline(args.pair)
        atomic_json(args.output.resolve(), result)
    else:
        result = audit_roots(args.root, args.at, args.max_active_phase_seconds)
        if args.output:
            atomic_json(args.output.resolve(), result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
