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
    pair_baseline,
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


if __name__ == "__main__":
    test_work_cycle_summary_and_guards()
    test_pair_baseline_reads_bound_assessments()
