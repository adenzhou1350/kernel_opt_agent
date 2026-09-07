#!/usr/bin/env python3
"""Exercise evidence-bound work-cycle timing and fail-closed guards."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from community_knowledge import atomic_json, sha256_file  # noqa: E402
from community_work_cycle import (  # noqa: E402
    close_cycle,
    evaluate_budget,
    pair_baseline,
    start_phase,
    summarize,
    validate_ledger,
    write_ledger,
)
from schema_utils import validate_instance  # noqa: E402


def identity(path: Path) -> dict:
    return {"path": path.as_posix(), "sha256": sha256_file(path)}


def ledger(evidence: Path) -> dict:
    return {
        "schema_version": "community-work-cycle-v1",
        "cycle_id": "cycle-1",
        "task_id": "task-1",
        "started_at": "2026-09-07T04:00:00Z",
        "observation_mode": "PROSPECTIVE_EXACT",
        "claim_boundary": "WORK_CYCLE_TIMING_NOT_PERFORMANCE_CAUSALITY",
        "minimum_material_speedup": 1.02,
        "spans": [
            {
                "span_id": "research",
                "phase": "COMMUNITY_RESEARCH",
                "actor": "AGENT",
                "resource_id": None,
                "started_at": "2026-09-07T04:00:00Z",
                "ended_at": "2026-09-07T04:01:00Z",
                "status": "COMPLETE",
                "evidence": [identity(evidence)],
            },
            {
                "span_id": "compute",
                "phase": "COMPILE_AND_MEASURE",
                "actor": "GPU",
                "resource_id": "local-sm89",
                "started_at": "2026-09-07T04:01:00Z",
                "ended_at": "2026-09-07T04:03:00Z",
                "status": "COMPLETE",
                "evidence": [identity(evidence)],
            },
            {
                "span_id": "validate",
                "phase": "CORRECTNESS_VALIDATION",
                "actor": "GPU",
                "resource_id": "local-sm89",
                "started_at": "2026-09-07T04:03:00Z",
                "ended_at": "2026-09-07T04:04:00Z",
                "status": "COMPLETE",
                "evidence": [identity(evidence)],
            },
        ],
        "milestones": [
            {
                "kind": "FIRST_CANDIDATE_PROPOSED",
                "at": "2026-09-07T04:01:00Z",
                "evidence": [identity(evidence)],
            },
            {
                "kind": "FIRST_SCREEN_CORRECT",
                "at": "2026-09-07T04:04:00Z",
                "evidence": [identity(evidence)],
            },
            {
                "kind": "FIRST_MATERIAL_IMPROVEMENT",
                "at": "2026-09-07T04:04:00Z",
                "evidence": [identity(evidence)],
            },
            {
                "kind": "FIRST_QUALIFIED_RESULT",
                "at": "2026-09-07T04:04:00Z",
                "evidence": [identity(evidence)],
            },
        ],
        "outcome": {
            "correctness": "PASS",
            "best_speedup": 1.10,
            "best_whole_model_speedup": None,
            "upstream_ready": False,
            "pull_request_url": None,
            "merged": False,
        },
    }


def test_work_cycle_summary_and_guards() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        evidence = base / "evidence.json"
        evidence.write_text('{"ok": true}\n', encoding="utf-8")
        cycle = base / "cycle.json"
        atomic_json(cycle, ledger(evidence))
        assert validate_ledger(cycle)["cycle_id"] == "cycle-1"
        report = summarize(cycle)
        assert report["buckets"]["research_seconds"] == 60
        assert report["buckets"]["compute_seconds"] == 120
        assert report["buckets"]["validation_seconds"] == 60
        assert report["wall_clock"]["observed_seconds"] == 240
        assert report["wall_clock"]["unaccounted_seconds"] == 0
        assert report["time_to_milestone_seconds"]["FIRST_QUALIFIED_RESULT"] == 240
        schema = json.loads(
            (ROOT / "schemas/community_work_cycle_summary.schema.json").read_text(
                encoding="utf-8"
            )
        )
        assert not validate_instance(report, schema)

        broken = ledger(evidence)
        broken["spans"][1]["started_at"] = "2026-09-07T04:00:30Z"
        original = cycle.read_bytes()
        try:
            write_ledger(cycle, broken)
        except ValueError as error:
            assert "overlap" in str(error)
        else:
            raise AssertionError("overlapping primary phases must fail")
        assert cycle.read_bytes() == original

        below = ledger(evidence)
        below["outcome"]["best_speedup"] = 1.01
        atomic_json(cycle, below)
        try:
            validate_ledger(cycle)
        except ValueError as error:
            assert "threshold" in str(error)
        else:
            raise AssertionError("sub-threshold improvement must fail")


def test_pair_baseline_reads_bound_assessments() -> None:
    pair = (
        ROOT.parent
        / "community-validation/temporal-unseen-2026-09-07/run-v3/paired-r1.json"
    )
    if not pair.is_file():
        return
    report = pair_baseline([pair])
    assert report["pair_count"] == 1
    assert report["arm_medians"]["control"]["elapsed_seconds"] > 0
    assert (
        report["arm_medians"]["community_augmented"][
            "time_to_first_improvement_seconds"
        ]
        > 0
    )


def test_v2_requires_explicit_close_and_complete_wall_clock_coverage() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        evidence = base / "evidence.json"
        evidence.write_text('{"ok": true}\n', encoding="utf-8")
        cycle = ledger(evidence)
        cycle.update(
            {
                "schema_version": "community-work-cycle-v2",
                "status": "CLOSED",
                "ended_at": "2026-09-07T04:04:00Z",
                "maximum_unaccounted_seconds": 0,
            }
        )
        path = base / "cycle-v2.json"
        atomic_json(path, cycle)
        assert validate_ledger(path)["status"] == "CLOSED"
        report = summarize(path)
        assert report["timing_integrity"] == {
            "ledger_schema_version": "community-work-cycle-v2",
            "cycle_status": "CLOSED",
            "maximum_unaccounted_seconds": 0,
            "coverage_status": "PASS",
        }

        broken = json.loads(path.read_text(encoding="utf-8"))
        broken["spans"][1]["started_at"] = "2026-09-07T04:01:10Z"
        broken["spans"][1]["ended_at"] = "2026-09-07T04:03:00Z"
        atomic_json(path, broken)
        try:
            validate_ledger(path)
        except ValueError as error:
            assert "unaccounted time" in str(error)
        else:
            raise AssertionError("v2 accepted an unclassified wall-clock gap")


def test_v2_cannot_close_with_an_unclassified_gap() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        evidence = base / "evidence.json"
        evidence.write_text('{"ok": true}\n', encoding="utf-8")
        cycle = ledger(evidence)
        cycle.update(
            {
                "schema_version": "community-work-cycle-v2",
                "status": "ACTIVE",
                "ended_at": None,
                "maximum_unaccounted_seconds": 0,
            }
        )
        path = base / "cycle-v2-active.json"
        atomic_json(path, cycle)
        args = type("Args", (), {"ledger": path, "at": "2026-09-07T04:04:10Z"})()
        try:
            close_cycle(args)
        except ValueError as error:
            assert "unaccounted time" in str(error)
        else:
            raise AssertionError("v2 closed while ten seconds were unclassified")


def test_materialization_and_environment_time_are_not_laundered_as_implementation() -> (
    None
):
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        evidence = base / "evidence.json"
        evidence.write_text('{"ok": true}\n', encoding="utf-8")
        cycle = ledger(evidence)
        cycle["spans"][0]["phase"] = "TASK_MATERIALIZATION"
        cycle["spans"][1]["phase"] = "ENVIRONMENT_PREPARATION"
        cycle["milestones"].insert(
            2,
            {
                "kind": "FIRST_MATERIALIZATION_DECISION",
                "at": "2026-09-07T04:04:00Z",
                "evidence": [identity(evidence)],
            },
        )
        path = base / "materialization-cycle.json"
        atomic_json(path, cycle)

        report = summarize(path)
        assert report["buckets"]["research_seconds"] == 0
        assert report["buckets"]["materialization_seconds"] == 60
        assert report["buckets"]["environment_preparation_seconds"] == 120
        assert report["buckets"]["implementation_seconds"] == 0
        assert (
            report["time_to_milestone_seconds"]["FIRST_MATERIALIZATION_DECISION"] == 240
        )


def test_budget_gate_blocks_new_work_after_phase_overrun() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        evidence = base / "evidence.json"
        evidence.write_text('{"ok": true}\n', encoding="utf-8")
        cycle = ledger(evidence)
        cycle.update(
            {
                "schema_version": "community-work-cycle-v2",
                "status": "ACTIVE",
                "ended_at": None,
                "maximum_unaccounted_seconds": 5,
                "budget_policy": {
                    "enforcement": "FAIL_CLOSED_BEFORE_NEW_PHASE_OR_EXPENSIVE_COMMAND",
                    "maximum_cycle_seconds": 300,
                    "phase_seconds": {"COMMUNITY_RESEARCH": 30},
                },
            }
        )
        cycle["spans"] = [cycle["spans"][0]]
        cycle["milestones"] = []
        cycle["outcome"] = {
            "correctness": "NOT_RUN",
            "best_speedup": None,
            "best_whole_model_speedup": None,
            "upstream_ready": False,
            "pull_request_url": None,
            "merged": False,
        }
        path = base / "budgeted-cycle.json"
        atomic_json(path, cycle)

        status = evaluate_budget(path, "2026-09-07T04:01:00Z")
        assert status["status"] == "EXCEEDED"
        assert status["violations"] == [
            {
                "scope": "PHASE",
                "phase": "COMMUNITY_RESEARCH",
                "observed_seconds": 60,
                "limit_seconds": 30,
                "overrun_seconds": 30,
            }
        ]
        assert not status["allowed_actions"]["start_new_phase"]
        assert not status["allowed_actions"]["dispatch_expensive_work"]
        assert status["allowed_actions"]["end_active_phase"]

        args = type(
            "Args",
            (),
            {
                "ledger": path,
                "span_id": "implementation",
                "phase": "CANDIDATE_IMPLEMENTATION",
                "actor": "AGENT",
                "resource_id": None,
                "at": "2026-09-07T04:01:00Z",
            },
        )()
        try:
            start_phase(args)
        except ValueError as error:
            assert "budget does not allow" in str(error)
        else:
            raise AssertionError("phase overrun allowed a new work phase")


def test_legacy_v2_without_budget_policy_remains_operable() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        evidence = base / "evidence.json"
        evidence.write_text('{"ok": true}\n', encoding="utf-8")
        cycle = ledger(evidence)
        cycle.update(
            {
                "schema_version": "community-work-cycle-v2",
                "status": "ACTIVE",
                "ended_at": None,
                "maximum_unaccounted_seconds": 5,
            }
        )
        cycle["spans"] = [cycle["spans"][0]]
        cycle["milestones"] = []
        path = base / "legacy-v2-cycle.json"
        atomic_json(path, cycle)
        status = evaluate_budget(path, "2026-09-07T04:01:00Z")
        assert status["status"] == "NOT_CONFIGURED"
        assert status["allowed_actions"]["start_new_phase"]
        assert not status["allowed_actions"]["dispatch_expensive_work"]

        args = type(
            "Args",
            (),
            {
                "ledger": path,
                "span_id": "implementation",
                "phase": "CANDIDATE_IMPLEMENTATION",
                "actor": "AGENT",
                "resource_id": None,
                "at": "2026-09-07T04:01:00Z",
            },
        )()
        updated = start_phase(args)
        assert updated["spans"][-1]["status"] == "ACTIVE"


if __name__ == "__main__":
    test_work_cycle_summary_and_guards()
    test_pair_baseline_reads_bound_assessments()
    test_v2_requires_explicit_close_and_complete_wall_clock_coverage()
    test_v2_cannot_close_with_an_unclassified_gap()
    test_materialization_and_environment_time_are_not_laundered_as_implementation()
    test_budget_gate_blocks_new_work_after_phase_overrun()
    test_legacy_v2_without_budget_policy_remains_operable()
