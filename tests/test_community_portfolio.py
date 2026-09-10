#!/usr/bin/env python3
"""Focused tests for four-lane work-cycle portfolio accounting."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from artifact_io import sha256_file  # noqa: E402
from community_portfolio import build_report  # noqa: E402


LANES = (
    "VLLM_OPTIMIZATION",
    "VLLM_A800_ADAPTATION",
    "MOONCAKE_OPTIMIZATION",
    "SGLANG_OPTIMIZATION",
)


def write_json(path: Path, value: dict) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def ledger(tmp_path: Path, lane: str, index: int, gpu: bool = False) -> Path:
    evidence = write_json(tmp_path / f"evidence-{index}.json", {"status": "PASS"})
    spans = []
    if gpu:
        spans.append(
            {
                "span_id": "gpu",
                "phase": "PERFORMANCE_VALIDATION",
                "actor": "GPU",
                "resource_id": "gpu-test",
                "started_at": "2026-01-01T00:01:00Z",
                "ended_at": "2026-01-01T00:03:00Z",
                "status": "COMPLETE",
                "evidence": [{"path": evidence.name, "sha256": sha256_file(evidence)}],
            }
        )
    value = {
        "schema_version": "community-work-cycle-v1",
        "cycle_id": f"cycle-{index}",
        "task_id": f"{lane.lower()}-{index}",
        "started_at": "2026-01-01T00:00:00Z",
        "observation_mode": "PROSPECTIVE_EXACT",
        "claim_boundary": "WORK_CYCLE_TIMING_NOT_PERFORMANCE_CAUSALITY",
        "minimum_material_speedup": 1.02,
        "spans": spans,
        "milestones": [
            {
                "kind": "FIRST_CANDIDATE_PROPOSED",
                "at": "2026-01-01T00:00:10Z",
                "evidence": [{"path": evidence.name, "sha256": sha256_file(evidence)}],
            },
            {
                "kind": "FIRST_SCREEN_CORRECT",
                "at": "2026-01-01T00:00:30Z",
                "evidence": [{"path": evidence.name, "sha256": sha256_file(evidence)}],
            },
            {
                "kind": "FIRST_MATERIAL_IMPROVEMENT",
                "at": "2026-01-01T00:02:00Z",
                "evidence": [{"path": evidence.name, "sha256": sha256_file(evidence)}],
            },
            {
                "kind": "FIRST_QUALIFIED_RESULT",
                "at": "2026-01-01T00:03:00Z",
                "evidence": [{"path": evidence.name, "sha256": sha256_file(evidence)}],
            },
        ],
        "outcome": {
            "correctness": "PASS",
            "best_speedup": 1.05,
            "best_whole_model_speedup": None,
            "upstream_ready": False,
            "pull_request_url": None,
            "merged": False,
        },
    }
    return write_json(tmp_path / f"ledger-{index}.json", value)


def manifest(tmp_path: Path, duplicate: bool = False) -> Path:
    topology = ROOT / "knowledge/community/lane_topology.v3.json"
    ledgers = [
        ledger(tmp_path, lane, index, gpu=index == 0)
        for index, lane in enumerate(LANES)
    ]
    if duplicate:
        ledgers[1] = ledgers[0]
    value = {
        "schema_version": "community-portfolio-manifest-v1",
        "claim_boundary": "EXPLICIT_LEDGER_SELECTION_NOT_CAUSAL_COMPARISON",
        "lane_topology_identity": {
            "path": topology.as_posix(),
            "sha256": sha256_file(topology),
        },
        "lanes": [
            {
                "lane_id": lane,
                "thread_id": f"00000000-0000-0000-0000-00000000000{index}",
                "work_cycle_ledgers": [
                    {"path": ledgers[index].name, "sha256": sha256_file(ledgers[index])}
                ],
            }
            for index, lane in enumerate(LANES)
        ],
    }
    return write_json(tmp_path / "manifest.json", value)


def test_portfolio_aggregates_four_explicit_lanes(tmp_path: Path) -> None:
    report = build_report(manifest(tmp_path))
    assert len(report["lanes"]) == 4
    assert report["totals"]["ledger_count"] == 4
    assert report["totals"]["prospective_count"] == 4
    assert report["totals"]["correctness_pass_count"] == 4
    assert report["totals"]["material_improvement_count"] == 4
    assert report["totals"]["gpu_seconds"] == 120.0
    assert report["totals"]["median_time_to_first_correct_seconds"] == 30.0
    assert report["totals"]["median_time_to_first_improvement_seconds"] == 120.0
    assert report["totals"]["qualified_results_per_gpu_hour"] == 120.0
    assert report["schema_version"] == "community-portfolio-report-v3"
    assert report["totals"]["median_candidate_to_draft_seconds"] is None
    assert report["totals"]["median_draft_to_ready_seconds"] is None
    assert report["totals"]["prospective_draft_to_ready_conversion_rate"] is None
    assert report["totals"]["delivery_funnel"] == {
        "candidate_proposed": 4,
        "screen_correct": 4,
        "material_improvement": 4,
        "qualified_result": 4,
        "upstream_ready": 0,
        "pr_opened": 0,
        "pr_ready_for_review": 0,
        "merged": 0,
        "leading_constraint": "UPSTREAM_READINESS",
    }


def test_empty_lane_exposes_missing_evidence_without_guessing(tmp_path: Path) -> None:
    path = manifest(tmp_path)
    value = json.loads(path.read_text(encoding="utf-8"))
    value["lanes"][0]["work_cycle_ledgers"] = []
    write_json(path, value)
    report = build_report(path)
    first = next(
        lane for lane in report["lanes"] if lane["lane_id"] == "VLLM_OPTIMIZATION"
    )
    assert first["delivery_funnel"]["leading_constraint"] == "NO_EVIDENCE"


def test_downstream_correctness_closes_candidate_stage_without_guessing_speedup(
    tmp_path: Path,
) -> None:
    path = manifest(tmp_path)
    value = json.loads(path.read_text(encoding="utf-8"))
    identity = value["lanes"][0]["work_cycle_ledgers"][0]
    selected = tmp_path / identity["path"]
    cycle = json.loads(selected.read_text(encoding="utf-8"))
    cycle["milestones"] = [
        item for item in cycle["milestones"] if item["kind"] == "FIRST_SCREEN_CORRECT"
    ]
    write_json(selected, cycle)
    identity["sha256"] = sha256_file(selected)
    write_json(path, value)

    report = build_report(path)
    first = next(
        lane for lane in report["lanes"] if lane["lane_id"] == "VLLM_OPTIMIZATION"
    )
    assert first["delivery_funnel"] == {
        "candidate_proposed": 1,
        "screen_correct": 1,
        "material_improvement": 0,
        "qualified_result": 0,
        "upstream_ready": 0,
        "pr_opened": 0,
        "pr_ready_for_review": 0,
        "merged": 0,
        "leading_constraint": "MATERIAL_IMPROVEMENT",
    }


def test_portfolio_constraint_is_earliest_incomplete_candidate_stage(
    tmp_path: Path,
) -> None:
    path = manifest(tmp_path)
    value = json.loads(path.read_text(encoding="utf-8"))
    identity = value["lanes"][1]["work_cycle_ledgers"][0]
    selected = tmp_path / identity["path"]
    cycle = json.loads(selected.read_text(encoding="utf-8"))
    cycle["milestones"] = [
        item
        for item in cycle["milestones"]
        if item["kind"] == "FIRST_CANDIDATE_PROPOSED"
    ]
    cycle["outcome"] = {
        "correctness": "NOT_RUN",
        "best_speedup": None,
        "best_whole_model_speedup": None,
        "upstream_ready": False,
        "pull_request_url": None,
        "merged": False,
    }
    write_json(selected, cycle)
    identity["sha256"] = sha256_file(selected)
    write_json(path, value)

    report = build_report(path)
    assert report["totals"]["delivery_funnel"]["candidate_proposed"] == 4
    assert report["totals"]["delivery_funnel"]["screen_correct"] == 3
    assert report["totals"]["delivery_funnel"]["leading_constraint"] == "CORRECTNESS"


def test_same_ledger_cannot_be_counted_in_two_lanes(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="cannot be counted more than once"):
        build_report(manifest(tmp_path, duplicate=True))


def test_manifest_must_bind_all_four_lanes(tmp_path: Path) -> None:
    path = manifest(tmp_path)
    value = json.loads(path.read_text(encoding="utf-8"))
    value["lanes"][3]["lane_id"] = "VLLM_OPTIMIZATION"
    write_json(path, value)
    with pytest.raises(ValueError, match="each autonomous lane exactly once"):
        build_report(path)


def test_delivery_speed_and_conversion_use_only_prospective_exact_cycles(
    tmp_path: Path,
) -> None:
    path = manifest(tmp_path)
    value = json.loads(path.read_text(encoding="utf-8"))
    for lane_index in (0, 1):
        identity = value["lanes"][lane_index]["work_cycle_ledgers"][0]
        selected = tmp_path / identity["path"]
        cycle = json.loads(selected.read_text(encoding="utf-8"))
        evidence = cycle["milestones"][0]["evidence"]
        cycle["milestones"].extend(
            [
                {
                    "kind": "PR_DRAFT_OPENED",
                    "at": "2026-01-01T00:04:10Z",
                    "evidence": evidence,
                },
                {
                    "kind": "PR_READY_FOR_REVIEW",
                    "at": "2026-01-01T00:10:10Z",
                    "evidence": evidence,
                },
            ]
        )
        cycle["outcome"]["pull_request_url"] = "https://example.com/pull/1"
        if lane_index == 1:
            cycle["observation_mode"] = "LEGACY_MILESTONE_BOUNDS"
        write_json(selected, cycle)
        identity["sha256"] = sha256_file(selected)
    write_json(path, value)

    totals = build_report(path)["totals"]
    assert totals["prospective_draft_opened_count"] == 1
    assert totals["prospective_pr_ready_count"] == 1
    assert totals["median_candidate_to_draft_seconds"] == 240.0
    assert totals["median_draft_to_ready_seconds"] == 360.0
    assert totals["prospective_draft_to_ready_conversion_rate"] == 1.0


def test_claimed_work_cycle_version_without_canonical_fields_is_rejected(
    tmp_path: Path,
) -> None:
    path = manifest(tmp_path)
    value = json.loads(path.read_text(encoding="utf-8"))
    fake = write_json(
        tmp_path / "claimed-ledger.json",
        {
            "schema_version": "community-work-cycle-v1",
            "outcome": {"correctness": "PASS"},
        },
    )
    value["lanes"][0]["work_cycle_ledgers"] = [
        {"path": fake.name, "sha256": sha256_file(fake)}
    ]
    write_json(path, value)
    with pytest.raises(ValueError):
        build_report(path)
