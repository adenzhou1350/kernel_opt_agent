#!/usr/bin/env python3
"""Exercise explicit work-cycle aggregation and duplicate/staleness guards."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from community_knowledge import atomic_json, sha256_file  # noqa: E402
from community_time_to_value import build_rollup  # noqa: E402
from community_work_cycle import summarize  # noqa: E402
from schema_utils import validate_instance  # noqa: E402


def identity(path: Path) -> dict:
    return {"path": path.resolve().as_posix(), "sha256": sha256_file(path)}


def cycle(
    cycle_id: str,
    task_id: str,
    started_at: str,
    ended_at: str,
    evidence: Path,
    *,
    valuable: bool,
) -> dict:
    span = {
        "span_id": "research",
        "phase": "COMMUNITY_RESEARCH",
        "actor": "AGENT",
        "resource_id": None,
        "started_at": started_at,
        "ended_at": ended_at,
        "status": "COMPLETE",
        "evidence": [identity(evidence)],
    }
    milestones = []
    outcome = {
        "correctness": "NOT_RUN",
        "best_speedup": None,
        "best_whole_model_speedup": None,
        "upstream_ready": False,
        "pull_request_url": None,
        "merged": False,
    }
    if valuable:
        span["phase"] = "COMPILE_AND_MEASURE"
        milestones = [
            {
                "kind": name,
                "at": ended_at,
                "evidence": [identity(evidence)],
            }
            for name in (
                "FIRST_CANDIDATE_PROPOSED",
                "FIRST_SCREEN_CORRECT",
                "FIRST_MATERIALIZATION_DECISION",
                "FIRST_MATERIAL_IMPROVEMENT",
                "FIRST_QUALIFIED_RESULT",
                "UPSTREAM_PACKAGE_READY",
                "PR_DRAFT_OPENED",
                "PR_READY_FOR_REVIEW",
            )
        ]
        outcome = {
            "correctness": "PASS",
            "best_speedup": 1.10,
            "best_whole_model_speedup": 1.04,
            "upstream_ready": True,
            "pull_request_url": "https://example.com/pull/1",
            "merged": False,
        }
    return {
        "schema_version": "community-work-cycle-v2",
        "cycle_id": cycle_id,
        "task_id": task_id,
        "started_at": started_at,
        "ended_at": ended_at,
        "status": "CLOSED",
        "observation_mode": "PROSPECTIVE_EXACT",
        "claim_boundary": "WORK_CYCLE_TIMING_NOT_PERFORMANCE_CAUSALITY",
        "minimum_material_speedup": 1.02,
        "maximum_unaccounted_seconds": 0,
        "budget_policy": {
            "maximum_cycle_seconds": 7200,
            "phase_seconds": {
                "COMMUNITY_RESEARCH": 600,
                "BOTTLENECK_DIAGNOSIS": 600,
                "TASK_MATERIALIZATION": 900,
                "ENVIRONMENT_PREPARATION": 1800,
                "CANDIDATE_IMPLEMENTATION": 1200,
                "COMPILE_AND_MEASURE": 2400,
                "CORRECTNESS_VALIDATION": 900,
                "PERFORMANCE_VALIDATION": 900,
                "WHOLE_MODEL_VALIDATION": 1200,
                "UPSTREAM_PACKAGING": 900,
                "EXTERNAL_WAIT": 3600,
                "UNATTRIBUTED_LEGACY_WORK": 0,
            },
            "enforcement": "FAIL_CLOSED_BEFORE_NEW_PHASE_OR_EXPENSIVE_COMMAND",
        },
        "spans": [span],
        "milestones": milestones,
        "outcome": outcome,
    }


def test_rollup_reports_first_value_and_refuses_duplicate_cycles(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence.json"
    atomic_json(evidence, {"ok": True})
    first = tmp_path / "cycle-1.json"
    second = tmp_path / "cycle-2.json"
    atomic_json(
        first,
        cycle(
            "cycle-1",
            "task-1",
            "2026-09-08T00:00:00Z",
            "2026-09-08T00:04:00Z",
            evidence,
            valuable=True,
        ),
    )
    atomic_json(
        second,
        cycle(
            "cycle-2",
            "task-2",
            "2026-09-08T00:05:00Z",
            "2026-09-08T00:06:00Z",
            evidence,
            valuable=False,
        ),
    )
    first_summary = tmp_path / "summary-1.json"
    second_summary = tmp_path / "summary-2.json"
    atomic_json(first_summary, summarize(first))
    atomic_json(second_summary, summarize(second))

    report = build_rollup([second_summary, first_summary], "test-cohort", ROOT)
    assert report["inventory"]["cycle_count"] == 2
    assert report["cohort_clock"]["summed_cycle_seconds"] == 300
    assert report["cohort_clock"]["elapsed_seconds"] == 360
    assert report["bucket_seconds"]["compute_seconds"] == 240
    assert report["bucket_seconds"]["research_seconds"] == 60
    assert report["outcomes"]["best_speedup"] == 1.10
    improvement = report["milestones"]["FIRST_MATERIAL_IMPROVEMENT"]
    assert improvement["elapsed_from_cohort_start_seconds"] == 240
    assert improvement["cycle_id"] == "cycle-1"
    assert not report["censoring"]["first_material_improvement_unobserved"]
    schema = json.loads(
        (ROOT / "schemas/community_time_to_value_rollup.schema.json").read_text(
            encoding="utf-8"
        )
    )
    assert not validate_instance(report, schema)

    duplicate = tmp_path / "summary-duplicate.json"
    atomic_json(duplicate, summarize(first))
    with pytest.raises(ValueError, match="duplicate cycle_id"):
        build_rollup([first_summary, duplicate], "test-cohort", ROOT)
    with pytest.raises(ValueError, match="duplicate work-cycle summary path"):
        build_rollup([first_summary, first_summary], "test-cohort", ROOT)

    predecessor_path = tmp_path / "predecessor.json"
    atomic_json(
        predecessor_path,
        build_rollup([first_summary], "test-cohort", ROOT),
    )
    extended = build_rollup(
        [second_summary],
        "test-cohort",
        ROOT,
        predecessor_path=predecessor_path,
        expected_predecessor_sha256=sha256_file(predecessor_path),
    )
    assert extended["inventory"]["cycle_count"] == 2
    assert extended["input_identity"]["predecessor_rollup"] == identity(
        predecessor_path
    )
    with pytest.raises(ValueError, match="expected predecessor SHA-256"):
        build_rollup(
            [second_summary],
            "test-cohort",
            ROOT,
            predecessor_path=predecessor_path,
        )
    with pytest.raises(ValueError, match="SHA-256 differs"):
        build_rollup(
            [second_summary],
            "test-cohort",
            ROOT,
            predecessor_path=predecessor_path,
            expected_predecessor_sha256="0" * 64,
        )


def test_predecessor_chain_survives_later_evidence_changes(tmp_path: Path) -> None:
    old_evidence = tmp_path / "old-evidence.json"
    new_evidence = tmp_path / "new-evidence.json"
    atomic_json(old_evidence, {"version": 1})
    atomic_json(new_evidence, {"version": 1})
    old_ledger = tmp_path / "old-cycle.json"
    new_ledger = tmp_path / "new-cycle.json"
    atomic_json(
        old_ledger,
        cycle(
            "old-cycle",
            "old-task",
            "2026-09-08T00:00:00Z",
            "2026-09-08T00:01:00Z",
            old_evidence,
            valuable=False,
        ),
    )
    old_summary = tmp_path / "old-summary.json"
    atomic_json(old_summary, summarize(old_ledger))
    predecessor_path = tmp_path / "predecessor.json"
    atomic_json(
        predecessor_path,
        build_rollup([old_summary], "durable-cohort", ROOT),
    )
    predecessor_sha256 = sha256_file(predecessor_path)

    atomic_json(old_evidence, {"version": 2})
    atomic_json(
        new_ledger,
        cycle(
            "new-cycle",
            "new-task",
            "2026-09-08T00:02:00Z",
            "2026-09-08T00:03:00Z",
            new_evidence,
            valuable=False,
        ),
    )
    new_summary = tmp_path / "new-summary.json"
    atomic_json(new_summary, summarize(new_ledger))

    extended = build_rollup(
        [new_summary],
        "durable-cohort",
        ROOT,
        predecessor_path=predecessor_path,
        expected_predecessor_sha256=predecessor_sha256,
    )
    assert extended["inventory"]["cycle_count"] == 2
    assert extended["input_identity"]["predecessor_rollup"] == identity(
        predecessor_path
    )


def test_rollup_recomputes_each_summary(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence.json"
    atomic_json(evidence, {"ok": True})
    ledger = tmp_path / "cycle.json"
    atomic_json(
        ledger,
        cycle(
            "cycle-1",
            "task-1",
            "2026-09-08T00:00:00Z",
            "2026-09-08T00:01:00Z",
            evidence,
            valuable=False,
        ),
    )
    summary_path = tmp_path / "summary.json"
    report = summarize(ledger)
    report["phase_seconds"]["COMMUNITY_RESEARCH"] = 61
    atomic_json(summary_path, report)
    with pytest.raises(ValueError, match="stale or edited"):
        build_rollup([summary_path], "test-cohort", ROOT)
