#!/usr/bin/env python3
"""Aggregate explicit, hash-bound work-cycle ledgers across four lanes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import median

from artifact_io import atomic_json, now, read_object, sha256_file
from community_lane_topology import LANE_IDS, validate_topology
from community_work_cycle import parse_time, summarize, validate_ledger
from schema_utils import validate_instance


MANIFEST_VERSION = "community-portfolio-manifest-v1"
REPORT_VERSION = "community-portfolio-report-v1"


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


def metrics(ledgers: list[tuple[Path, dict]]) -> dict:
    first_correct: list[float] = []
    first_improvement: list[float] = []
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
        "qualified_results_per_gpu_hour": (
            qualified / (gpu_seconds / 3600.0) if gpu_seconds > 0 else None
        ),
    }


def build_report(manifest_path: Path) -> dict:
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

    totals = metrics(all_ledgers)
    report = {
        "schema_version": REPORT_VERSION,
        "generated_at": now(),
        "claim_boundary": "DESCRIPTIVE_PORTFOLIO_ACCOUNTING_NOT_STRATEGY_CAUSALITY",
        "manifest_identity": {
            "path": manifest_path.as_posix(),
            "sha256": sha256_file(manifest_path),
        },
        "lanes": lane_reports,
        "totals": totals,
    }
    errors = validate_instance(
        report, read_object(root() / "schemas/community_portfolio_report.schema.json")
    )
    if errors:
        raise ValueError("invalid community portfolio report: " + "; ".join(errors))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = build_report(args.manifest)
    if args.output:
        atomic_json(args.output.resolve(), result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
