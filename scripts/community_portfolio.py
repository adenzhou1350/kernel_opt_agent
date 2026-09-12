#!/usr/bin/env python3
"""Aggregate explicit, hash-bound work-cycle ledgers across four lanes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import median

from artifact_io import atomic_json, now, read_object, sha256_file
from community_lane_topology import LANE_IDS, validate_topology
from community_work_cycle import (
    PHASES,
    evidence_path,
    parse_time,
    summarize,
    validate_candidate_value_decision,
    validate_ledger,
)
from schema_utils import validate_instance


MANIFEST_VERSION = "community-portfolio-manifest-v1"
REPORT_VERSION = "community-portfolio-report-v6"
ACTION_ATTESTATION_VERSION = "community-action-attestation-v1"


def root() -> Path:
    return Path(__file__).resolve().parents[1]


def resolve_identity(base: Path, identity: dict, label: str) -> Path:
    relative = Path(identity["path"])
    path = relative if relative.is_absolute() else (base / relative)
    path = path.resolve()
    if not path.is_file() or sha256_file(path) != identity["sha256"]:
        raise ValueError(f"{label} identity changed: {identity['path']}")
    return path


def seconds(start: str, end: str) -> float:
    return (
        parse_time(end, "ended_at") - parse_time(start, "started_at")
    ).total_seconds()


def nullable_median(values: list[float]) -> float | None:
    return median(values) if values else None


def has_strict_candidate_start(path: Path, ledger: dict) -> bool:
    """Accept timing origin only when the candidate-value decision recomputes."""

    starts = [
        milestone
        for milestone in ledger["milestones"]
        if milestone["kind"] == "FIRST_CANDIDATE_PROPOSED"
    ]
    if len(starts) != 1 or len(starts[0]["evidence"]) != 1:
        return False
    milestone = starts[0]
    if milestone["at"] != ledger["started_at"]:
        return False
    decision_path = evidence_path(milestone["evidence"][0], path)
    try:
        decision = validate_candidate_value_decision(decision_path)
    except (FileNotFoundError, KeyError, TypeError, ValueError):
        return False
    return parse_time(
        decision["generated_at"], "candidate-value decision generated_at"
    ) <= parse_time(milestone["at"], "FIRST_CANDIDATE_PROPOSED.at")


def action_class(span: dict) -> str:
    """Classify an active phase without guessing from free-form task prose."""

    resource_id = span.get("resource_id") or ""
    if resource_id.startswith("USER_"):
        return "USER_CONFIRMATION"
    if resource_id.endswith("_AUTH") or resource_id.endswith("_CREDENTIAL"):
        return "CREDENTIAL"
    if span["phase"] == "ENVIRONMENT_SETUP":
        return "ENVIRONMENT"
    if span["phase"] == "GOVERNANCE_VALIDATION":
        return "GOVERNANCE"
    if span["actor"] == "GPU":
        return "GPU_EXECUTION"
    if span["actor"] == "EXTERNAL":
        return "EXTERNAL_DEPENDENCY"
    return "ACTIVE_WORK"


def load_action_attestations(
    paths: list[Path], ledgers: list[tuple[Path, dict]]
) -> tuple[dict[tuple[str, str, str], tuple[dict, dict]], list[dict]]:
    """Validate explicit current-state claims for selected active ledger spans."""

    active_spans = {
        (path.resolve().as_posix(), ledger["cycle_id"], span["span_id"]): span
        for path, ledger in ledgers
        for span in ledger["spans"]
        if span["status"] == "ACTIVE"
    }
    attestations: dict[tuple[str, str, str], tuple[dict, dict]] = {}
    identities = []
    for raw_path in paths:
        path = raw_path.resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        attestation = read_object(path)
        errors = validate_instance(
            attestation,
            read_object(root() / "schemas/community_action_attestation.schema.json"),
        )
        if errors:
            raise ValueError("invalid action attestation: " + "; ".join(errors))
        if attestation["schema_version"] != ACTION_ATTESTATION_VERSION:
            raise ValueError("unsupported action attestation")

        ledger_path = resolve_identity(
            path.parent, attestation["ledger_identity"], "attested ledger"
        )
        key = (
            ledger_path.as_posix(),
            attestation["cycle_id"],
            attestation["span_id"],
        )
        span = active_spans.get(key)
        if span is None:
            raise ValueError("action attestation does not select an active ledger span")
        if key in attestations:
            raise ValueError("duplicate action attestation for one active span")
        if attestation["resource_id"] != span.get("resource_id"):
            raise ValueError("action attestation resource_id changed")

        generated = parse_time(attestation["generated_at"], "generated_at")
        if generated < parse_time(span["started_at"], "span.started_at"):
            raise ValueError("action attestation predates its active span")
        if attestation["state"] == "ACTIVE":
            if attestation["action_owner"] == "NONE":
                raise ValueError("active action attestation requires an owner")
            if attestation["valid_until"] is None:
                raise ValueError("active action attestation requires valid_until")
            if parse_time(attestation["valid_until"], "valid_until") <= generated:
                raise ValueError(
                    "action attestation validity must extend past generation"
                )
        else:
            if attestation["action_owner"] != "NONE":
                raise ValueError("inactive action attestation owner must be NONE")
            if attestation["valid_until"] is not None:
                raise ValueError("inactive action attestation cannot have valid_until")

        for index, identity in enumerate(attestation["evidence"]):
            resolve_identity(path.parent, identity, f"action evidence {index}")
        identity = {"path": path.as_posix(), "sha256": sha256_file(path)}
        attestations[key] = (attestation, identity)
        identities.append(identity)
    return attestations, identities


def active_delivery_queue(
    lane_ledgers: list[tuple[str, str, list[tuple[Path, dict]]]],
    observed_at: str,
    attestations: dict[tuple[str, str, str], tuple[dict, dict]],
) -> tuple[list[dict], list[dict], dict]:
    """Expose only freshness-attested actions while retaining declared history."""

    observed = parse_time(observed_at, "observed_at")
    inventory = []
    for lane_id, thread_id, ledgers in lane_ledgers:
        constraint = delivery_funnel(ledgers)["leading_constraint"]
        for path, ledger in ledgers:
            for span in ledger["spans"]:
                if span["status"] != "ACTIVE":
                    continue
                started = parse_time(span["started_at"], "started_at")
                category = action_class(span)
                if observed < started:
                    raise ValueError("portfolio observation precedes active span")
                key = (path.resolve().as_posix(), ledger["cycle_id"], span["span_id"])
                bound = attestations.get(key)
                if bound is None:
                    verification_status = "UNVERIFIED"
                    owner = "NONE"
                    attestation_identity = None
                    attested_at = None
                    valid_until = None
                else:
                    attestation, attestation_identity = bound
                    attested_at = attestation["generated_at"]
                    valid_until = attestation["valid_until"]
                    if parse_time(attested_at, "attested_at") > observed:
                        raise ValueError("action attestation is newer than the report")
                    owner = attestation["action_owner"]
                    if attestation["state"] == "ACTIVE":
                        verification_status = (
                            "CONFIRMED_ACTIVE"
                            if observed <= parse_time(valid_until, "valid_until")
                            else "EXPIRED"
                        )
                    else:
                        verification_status = attestation["state"]
                inventory.append(
                    {
                        "lane_id": lane_id,
                        "thread_id": thread_id,
                        "cycle_id": ledger["cycle_id"],
                        "ledger_path": path.as_posix(),
                        "span_id": span["span_id"],
                        "phase": span["phase"],
                        "actor": span["actor"],
                        "resource_id": span.get("resource_id"),
                        "active_since": span["started_at"],
                        "active_seconds": (observed - started).total_seconds(),
                        "action_class": category,
                        "needs_user_action": (
                            verification_status == "CONFIRMED_ACTIVE"
                            and owner == "USER"
                        ),
                        "leading_constraint": constraint,
                        "verification_status": verification_status,
                        "action_owner": owner,
                        "attestation_identity": attestation_identity,
                        "attested_at": attested_at,
                        "valid_until": valid_until,
                    }
                )
    action_priority = {
        "USER_CONFIRMATION": 0,
        "CREDENTIAL": 1,
        "EXTERNAL_DEPENDENCY": 2,
        "GOVERNANCE": 3,
        "ENVIRONMENT": 4,
        "GPU_EXECUTION": 5,
        "ACTIVE_WORK": 6,
    }
    inventory.sort(
        key=lambda row: (
            action_priority[row["action_class"]],
            row["active_since"],
            row["lane_id"],
            row["cycle_id"],
        )
    )
    rows = [
        row for row in inventory if row["verification_status"] == "CONFIRMED_ACTIVE"
    ]
    counts = {
        category: sum(row["action_class"] == category for row in rows)
        for category in (
            "USER_CONFIRMATION",
            "CREDENTIAL",
            "ENVIRONMENT",
            "GOVERNANCE",
            "GPU_EXECUTION",
            "EXTERNAL_DEPENDENCY",
            "ACTIVE_WORK",
        )
    }
    summary = {
        "active_count": len(rows),
        "declared_active_count": len(inventory),
        "confirmed_active_count": len(rows),
        "needs_user_action_count": sum(row["needs_user_action"] for row in rows),
        "lane_without_active_phase_count": len(LANE_IDS)
        - len({row["lane_id"] for row in rows}),
        "oldest_active_seconds": max(
            (row["active_seconds"] for row in rows), default=None
        ),
        "counts_by_action_class": counts,
        "counts_by_verification_status": {
            status: sum(row["verification_status"] == status for row in inventory)
            for status in (
                "CONFIRMED_ACTIVE",
                "UNVERIFIED",
                "EXPIRED",
                "RESOLVED",
                "SUPERSEDED",
            )
        },
    }
    return rows, inventory, summary


def delivery_funnel(ledgers: list[tuple[Path, dict]]) -> dict:
    """Expose the first evidence-backed delivery stage that remains unclosed."""

    counts = {
        "candidate_proposed": 0,
        "screen_correct": 0,
        "material_improvement": 0,
        "qualified_result": 0,
        "upstream_ready": 0,
        "pr_opened": 0,
        "pr_ready_for_review": 0,
        "merged": 0,
    }
    milestone_keys = {
        "FIRST_CANDIDATE_PROPOSED": "candidate_proposed",
        "FIRST_SCREEN_CORRECT": "screen_correct",
        "FIRST_MATERIAL_IMPROVEMENT": "material_improvement",
        "FIRST_QUALIFIED_RESULT": "qualified_result",
        "PR_READY_FOR_REVIEW": "pr_ready_for_review",
    }
    for _, ledger in ledgers:
        kinds = {item["kind"] for item in ledger["milestones"]}
        outcome = ledger["outcome"]

        # A correctness result or any later delivery artifact proves that a
        # candidate existed even when an older ledger omitted the earliest
        # milestone.  Keep the later stages strict: a speedup, qualification,
        # or review state is counted only from its canonical field/milestone.
        candidate_exists = bool(kinds) or any(
            (
                outcome["correctness"] != "NOT_RUN",
                outcome["best_speedup"] is not None,
                outcome["best_whole_model_speedup"] is not None,
                outcome["upstream_ready"],
                outcome["pull_request_url"] is not None,
                outcome["merged"],
            )
        )
        counts["candidate_proposed"] += int(candidate_exists)
        counts["screen_correct"] += int(
            "FIRST_SCREEN_CORRECT" in kinds or outcome["correctness"] == "PASS"
        )
        for kind, key in milestone_keys.items():
            if key not in {"candidate_proposed", "screen_correct"}:
                counts[key] += int(kind in kinds)
        counts["upstream_ready"] += int(outcome["upstream_ready"])
        counts["pr_opened"] += int(outcome["pull_request_url"] is not None)
        counts["merged"] += int(outcome["merged"])

    if not ledgers:
        constraint = "NO_EVIDENCE"
    else:
        ordered_constraints = (
            ("candidate_proposed", len(ledgers), "CANDIDATE_DISCOVERY"),
            ("screen_correct", counts["candidate_proposed"], "CORRECTNESS"),
            (
                "material_improvement",
                counts["screen_correct"],
                "MATERIAL_IMPROVEMENT",
            ),
            ("qualified_result", counts["material_improvement"], "QUALIFIED_RESULT"),
            ("upstream_ready", counts["qualified_result"], "UPSTREAM_READINESS"),
            ("pr_opened", counts["upstream_ready"], "PR_CREATION"),
            (
                "pr_ready_for_review",
                counts["pr_opened"],
                "PR_REVIEW_READINESS",
            ),
            ("merged", counts["pr_ready_for_review"], "UPSTREAM_REVIEW"),
        )
        constraint = next(
            (
                label
                for key, required, label in ordered_constraints
                if counts[key] < required
            ),
            "COMPLETE",
        )
    return {**counts, "leading_constraint": constraint}


def metrics(ledgers: list[tuple[Path, dict]]) -> dict:
    first_correct: list[float] = []
    first_improvement: list[float] = []
    candidate_to_draft: list[float] = []
    draft_to_ready: list[float] = []
    gpu_seconds = 0.0
    qualified = 0
    counts = {
        "ledger_count": len(ledgers),
        "prospective_count": 0,
        "legacy_count": 0,
        "correctness_pass_count": 0,
        "correctness_fail_count": 0,
        "material_improvement_count": 0,
        "upstream_ready_count": 0,
        "draft_or_ready_pr_count": 0,
        "merged_count": 0,
        "prospective_draft_opened_count": 0,
        "prospective_pr_ready_count": 0,
        "strict_candidate_start_count": 0,
        "non_strict_candidate_start_count": 0,
    }
    for path, ledger in ledgers:
        mode_key = (
            "prospective_count"
            if ledger["observation_mode"] == "PROSPECTIVE_EXACT"
            else "legacy_count"
        )
        counts[mode_key] += 1
        outcome = ledger["outcome"]
        if outcome["correctness"] == "PASS":
            counts["correctness_pass_count"] += 1
        elif outcome["correctness"] == "FAIL":
            counts["correctness_fail_count"] += 1
        counts["upstream_ready_count"] += int(outcome["upstream_ready"])
        counts["draft_or_ready_pr_count"] += int(
            outcome["pull_request_url"] is not None
        )
        counts["merged_count"] += int(outcome["merged"])

        milestone_kinds = {item["kind"] for item in ledger["milestones"]}
        counts["material_improvement_count"] += int(
            "FIRST_MATERIAL_IMPROVEMENT" in milestone_kinds
        )
        qualified += int("FIRST_QUALIFIED_RESULT" in milestone_kinds)
        if ledger["observation_mode"] == "PROSPECTIVE_EXACT":
            strict_candidate_start = has_strict_candidate_start(path, ledger)
            counts["strict_candidate_start_count"] += int(strict_candidate_start)
            counts["non_strict_candidate_start_count"] += int(
                not strict_candidate_start
            )
            milestone_times = {
                item["kind"]: item["at"] for item in ledger["milestones"]
            }
            draft_at = milestone_times.get("PR_DRAFT_OPENED")
            ready_at = milestone_times.get("PR_READY_FOR_REVIEW")
            candidate_at = milestone_times.get("FIRST_CANDIDATE_PROPOSED")
            counts["prospective_draft_opened_count"] += int(draft_at is not None)
            counts["prospective_pr_ready_count"] += int(ready_at is not None)
            if (
                strict_candidate_start
                and candidate_at is not None
                and draft_at is not None
            ):
                candidate_to_draft.append(seconds(candidate_at, draft_at))
            if draft_at is not None and ready_at is not None:
                draft_to_ready.append(seconds(draft_at, ready_at))
        for span in ledger["spans"]:
            if span["actor"] == "GPU" and span["status"] != "ACTIVE":
                gpu_seconds += seconds(span["started_at"], span["ended_at"])

        if not any(span["status"] == "ACTIVE" for span in ledger["spans"]):
            timing = summarize(path)["time_to_milestone_seconds"]
            if timing["FIRST_SCREEN_CORRECT"] is not None:
                first_correct.append(timing["FIRST_SCREEN_CORRECT"])
            if timing["FIRST_MATERIAL_IMPROVEMENT"] is not None:
                first_improvement.append(timing["FIRST_MATERIAL_IMPROVEMENT"])

    return {
        **counts,
        "gpu_seconds": gpu_seconds,
        "median_time_to_first_correct_seconds": nullable_median(first_correct),
        "median_time_to_first_improvement_seconds": nullable_median(first_improvement),
        "median_candidate_to_draft_seconds": nullable_median(candidate_to_draft),
        "median_draft_to_ready_seconds": nullable_median(draft_to_ready),
        "prospective_draft_to_ready_conversion_rate": (
            counts["prospective_pr_ready_count"]
            / counts["prospective_draft_opened_count"]
            if counts["prospective_draft_opened_count"] > 0
            else None
        ),
        "qualified_results_per_gpu_hour": (
            qualified / (gpu_seconds / 3600.0) if gpu_seconds > 0 else None
        ),
        "delivery_funnel": delivery_funnel(ledgers),
    }


def prospective_phase_time(ledgers: list[tuple[Path, dict]], observed_at: str) -> dict:
    """Sum selected prospective phase spans without implying wall-clock labor."""

    observed = parse_time(observed_at, "observed_at")
    phase_seconds = {phase: 0.0 for phase in PHASES}
    ledger_count = 0
    active_span_count = 0
    for _path, ledger in ledgers:
        if ledger["observation_mode"] != "PROSPECTIVE_EXACT":
            continue
        ledger_count += 1
        for span in ledger["spans"]:
            started = parse_time(span["started_at"], "span.started_at")
            if span["status"] == "ACTIVE":
                ended = observed
                active_span_count += 1
            else:
                ended = parse_time(span["ended_at"], "span.ended_at")
            if ended < started:
                raise ValueError(
                    f"portfolio observation precedes span start: {span['span_id']}"
                )
            phase_seconds[span["phase"]] += (ended - started).total_seconds()

    environment = phase_seconds["ENVIRONMENT_SETUP"]
    governance = phase_seconds["GOVERNANCE_VALIDATION"]
    overhead = environment + governance
    external_wait = phase_seconds["EXTERNAL_WAIT"]
    unattributed = phase_seconds["UNATTRIBUTED_LEGACY_WORK"]
    productive = sum(
        value
        for phase, value in phase_seconds.items()
        if phase
        not in {
            "ENVIRONMENT_SETUP",
            "GOVERNANCE_VALIDATION",
            "EXTERNAL_WAIT",
            "UNATTRIBUTED_LEGACY_WORK",
        }
    )
    attributed_active = overhead + productive
    accounted = attributed_active + external_wait + unattributed
    return {
        "ledger_count": ledger_count,
        "active_span_count": active_span_count,
        "accounted_phase_seconds": accounted,
        "attributed_active_seconds": attributed_active,
        "phase_seconds": phase_seconds,
        "environment_seconds": environment,
        "governance_seconds": governance,
        "environment_governance_seconds": overhead,
        "environment_governance_share_of_attributed_active": (
            overhead / attributed_active if attributed_active > 0 else None
        ),
        "external_wait_seconds": external_wait,
        "external_wait_share_of_accounted_phase_time": (
            external_wait / accounted if accounted > 0 else None
        ),
        "productive_seconds": productive,
        "productive_share_of_attributed_active": (
            productive / attributed_active if attributed_active > 0 else None
        ),
        "unattributed_legacy_seconds": unattributed,
        "parallel_overlap_semantics": (
            "SUM_OF_LEDGER_PHASE_SPANS_PARALLEL_CANDIDATES_MAY_OVERLAP"
        ),
        "claim_boundary": (
            "SELECTED_HASH_BOUND_PROSPECTIVE_LEDGER_PHASE_TIME_NOT_WALL_CLOCK_"
            "OR_LABOR_TIME"
        ),
    }


def validate_report(report: dict) -> list[str]:
    """Validate strict legacy cores plus versioned phase/action extensions."""

    timing_origin_fields = {
        "strict_candidate_start_count",
        "non_strict_candidate_start_count",
    }
    v5_projection = {
        key: value
        for key, value in report.items()
        if key not in {"action_attestation_identities", "delivery_action_inventory"}
    }
    v5_projection["totals"] = {
        key: value
        for key, value in report["totals"].items()
        if key not in timing_origin_fields
    }
    v5_projection["lanes"] = [
        {key: value for key, value in lane.items() if key not in timing_origin_fields}
        for lane in report["lanes"]
    ]
    v5_projection["schema_version"] = "community-portfolio-report-v5"
    v5_projection["active_delivery_queue"] = [
        {
            key: value
            for key, value in row.items()
            if key
            not in {
                "verification_status",
                "action_owner",
                "attestation_identity",
                "attested_at",
                "valid_until",
            }
        }
        for row in report["active_delivery_queue"]
    ]
    v5_projection["attention_summary"] = {
        key: value
        for key, value in report["attention_summary"].items()
        if key
        not in {
            "declared_active_count",
            "confirmed_active_count",
            "counts_by_verification_status",
        }
    }
    v4_projection = {
        key: value
        for key, value in v5_projection.items()
        if key != "prospective_phase_time"
    }
    v4_projection["schema_version"] = "community-portfolio-report-v4"
    errors = validate_instance(
        v4_projection,
        read_object(root() / "schemas/community_portfolio_report_v4.schema.json"),
    )
    errors.extend(
        validate_instance(
            v5_projection,
            read_object(root() / "schemas/community_portfolio_report_v5.schema.json"),
        )
    )
    errors.extend(
        validate_instance(
            report,
            read_object(root() / "schemas/community_portfolio_report_v6.schema.json"),
        )
    )
    return errors


def build_report(
    manifest_path: Path, action_attestation_paths: list[Path] | None = None
) -> dict:
    manifest_path = manifest_path.resolve()
    manifest = read_object(manifest_path)
    errors = validate_instance(
        manifest,
        read_object(root() / "schemas/community_portfolio_manifest.schema.json"),
    )
    if errors:
        raise ValueError("invalid community portfolio manifest: " + "; ".join(errors))
    if manifest["schema_version"] != MANIFEST_VERSION:
        raise ValueError("unsupported community portfolio manifest")

    topology_path = resolve_identity(
        manifest_path.parent, manifest["lane_topology_identity"], "lane topology"
    )
    validate_topology(topology_path)
    lane_ids = [lane["lane_id"] for lane in manifest["lanes"]]
    if len(lane_ids) != len(set(lane_ids)) or set(lane_ids) != LANE_IDS:
        raise ValueError("manifest must contain each autonomous lane exactly once")

    seen_hashes: set[str] = set()
    seen_cycles: set[tuple[str, str]] = set()
    lane_reports = []
    lane_ledgers = []
    all_ledgers: list[tuple[Path, dict]] = []
    for lane in manifest["lanes"]:
        ledgers = []
        identities = []
        for index, identity in enumerate(lane["work_cycle_ledgers"]):
            if identity["sha256"] in seen_hashes:
                raise ValueError("one ledger identity cannot be counted more than once")
            path = resolve_identity(
                manifest_path.parent,
                identity,
                f"{lane['lane_id']} ledger {index}",
            )
            ledger = validate_ledger(path)
            cycle_key = (ledger["cycle_id"], ledger["task_id"])
            if cycle_key in seen_cycles:
                raise ValueError("duplicate cycle/task selection")
            seen_hashes.add(identity["sha256"])
            seen_cycles.add(cycle_key)
            ledgers.append((path, ledger))
            all_ledgers.append((path, ledger))
            identities.append(identity)
        row = {
            "lane_id": lane["lane_id"],
            "thread_id": lane["thread_id"],
            "ledger_identities": identities,
            **metrics(ledgers),
        }
        lane_reports.append(row)
        lane_ledgers.append((lane["lane_id"], lane["thread_id"], ledgers))

    generated_at = now()
    attestations, attestation_identities = load_action_attestations(
        action_attestation_paths or [], all_ledgers
    )
    totals = metrics(all_ledgers)
    queue, inventory, attention = active_delivery_queue(
        lane_ledgers, generated_at, attestations
    )
    report = {
        "schema_version": REPORT_VERSION,
        "generated_at": generated_at,
        "claim_boundary": (
            "DESCRIPTIVE_PORTFOLIO_AND_DELIVERY_FUNNEL_NOT_STRATEGY_CAUSALITY"
        ),
        "manifest_identity": {
            "path": manifest_path.as_posix(),
            "sha256": sha256_file(manifest_path),
        },
        "action_attestation_identities": attestation_identities,
        "lanes": lane_reports,
        "totals": totals,
        "active_delivery_queue": queue,
        "delivery_action_inventory": inventory,
        "attention_summary": attention,
        "prospective_phase_time": prospective_phase_time(all_ledgers, generated_at),
    }
    errors = validate_report(report)
    if errors:
        raise ValueError("invalid community portfolio report: " + "; ".join(errors))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument(
        "--action-attestation",
        type=Path,
        action="append",
        default=[],
        help=(
            "hash-bind a current ACTIVE/RESOLVED/SUPERSEDED state for one "
            "selected ledger span; repeat for multiple actions"
        ),
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = build_report(args.manifest, args.action_attestation)
    if args.output:
        atomic_json(args.output.resolve(), result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
