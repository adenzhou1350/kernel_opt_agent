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
from candidate_value_gate import evaluate, request_template  # noqa: E402
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


def bind_strict_candidate_start(tmp_path: Path, selected: Path) -> None:
    cycle = json.loads(selected.read_text(encoding="utf-8"))
    request = request_template()
    request["candidate_id"] = cycle["cycle_id"]
    request_path = write_json(
        tmp_path / f"{cycle['cycle_id']}-candidate-value-request.json", request
    )
    decision = evaluate(request)
    decision["generated_at"] = cycle["started_at"]
    decision["request_identity"] = {
        "path": request_path.name,
        "sha256": sha256_file(request_path),
    }
    decision_path = write_json(
        tmp_path / f"{cycle['cycle_id']}-candidate-value-decision.json", decision
    )
    start = next(
        item
        for item in cycle["milestones"]
        if item["kind"] == "FIRST_CANDIDATE_PROPOSED"
    )
    start["at"] = cycle["started_at"]
    start["evidence"] = [
        {"path": decision_path.name, "sha256": sha256_file(decision_path)}
    ]
    write_json(selected, cycle)


def test_portfolio_aggregates_four_explicit_lanes(tmp_path: Path) -> None:
    report = build_report(manifest(tmp_path))
    assert len(report["lanes"]) == 4
    assert report["totals"]["ledger_count"] == 4
    assert report["totals"]["prospective_count"] == 4
    assert report["totals"]["strict_candidate_start_count"] == 0
    assert report["totals"]["non_strict_candidate_start_count"] == 4
    assert report["totals"]["correctness_pass_count"] == 4
    assert report["totals"]["material_improvement_count"] == 4
    assert report["totals"]["gpu_seconds"] == 120.0
    assert report["totals"]["median_time_to_first_correct_seconds"] == 30.0
    assert report["totals"]["median_time_to_first_improvement_seconds"] == 120.0
    assert report["totals"]["qualified_results_per_gpu_hour"] == 120.0
    assert report["schema_version"] == "community-portfolio-report-v6"
    assert report["active_delivery_queue"] == []
    assert report["delivery_action_inventory"] == []
    assert report["action_attestation_identities"] == []
    assert report["attention_summary"]["active_count"] == 0
    assert report["attention_summary"]["lane_without_active_phase_count"] == 4
    assert report["totals"]["median_candidate_to_draft_seconds"] is None
    assert report["totals"]["median_draft_to_ready_seconds"] is None
    assert report["totals"]["prospective_draft_to_ready_conversion_rate"] is None
    assert report["prospective_phase_time"] == {
        "ledger_count": 4,
        "active_span_count": 0,
        "accounted_phase_seconds": 120.0,
        "attributed_active_seconds": 120.0,
        "phase_seconds": {
            "COMMUNITY_RESEARCH": 0.0,
            "BOTTLENECK_DIAGNOSIS": 0.0,
            "CANDIDATE_IMPLEMENTATION": 0.0,
            "COMPILE_AND_MEASURE": 0.0,
            "CORRECTNESS_VALIDATION": 0.0,
            "PERFORMANCE_VALIDATION": 120.0,
            "WHOLE_MODEL_VALIDATION": 0.0,
            "UPSTREAM_PACKAGING": 0.0,
            "ENVIRONMENT_SETUP": 0.0,
            "GOVERNANCE_VALIDATION": 0.0,
            "EXTERNAL_WAIT": 0.0,
            "UNATTRIBUTED_LEGACY_WORK": 0.0,
        },
        "environment_seconds": 0.0,
        "governance_seconds": 0.0,
        "environment_governance_seconds": 0.0,
        "environment_governance_share_of_attributed_active": 0.0,
        "external_wait_seconds": 0.0,
        "external_wait_share_of_accounted_phase_time": 0.0,
        "productive_seconds": 120.0,
        "productive_share_of_attributed_active": 1.0,
        "unattributed_legacy_seconds": 0.0,
        "parallel_overlap_semantics": (
            "SUM_OF_LEDGER_PHASE_SPANS_PARALLEL_CANDIDATES_MAY_OVERLAP"
        ),
        "claim_boundary": (
            "SELECTED_HASH_BOUND_PROSPECTIVE_LEDGER_PHASE_TIME_NOT_WALL_CLOCK_"
            "OR_LABOR_TIME"
        ),
    }
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
        if lane_index == 0:
            bind_strict_candidate_start(tmp_path, selected)
        identity["sha256"] = sha256_file(selected)
    write_json(path, value)

    totals = build_report(path)["totals"]
    assert totals["prospective_draft_opened_count"] == 1
    assert totals["prospective_pr_ready_count"] == 1
    assert totals["strict_candidate_start_count"] == 1
    assert totals["non_strict_candidate_start_count"] == 2
    assert totals["median_candidate_to_draft_seconds"] == 250.0
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


def test_unattested_active_spans_remain_inventory_not_current_actions(
    tmp_path: Path,
) -> None:
    path = manifest(tmp_path)
    value = json.loads(path.read_text(encoding="utf-8"))
    cases = (
        (0, "EXTERNAL_WAIT", "EXTERNAL", "USER_BROWSER_CONFIRMATION"),
        (1, "ENVIRONMENT_SETUP", "AGENT", None),
        (2, "EXTERNAL_WAIT", "EXTERNAL", "GITHUB_AUTH"),
    )
    for lane_index, phase, actor, resource_id in cases:
        identity = value["lanes"][lane_index]["work_cycle_ledgers"][0]
        selected = tmp_path / identity["path"]
        cycle = json.loads(selected.read_text(encoding="utf-8"))
        cycle["spans"].append(
            {
                "span_id": "active",
                "phase": phase,
                "actor": actor,
                "resource_id": resource_id,
                "started_at": "2026-01-01T00:04:00Z",
                "ended_at": None,
                "status": "ACTIVE",
                "evidence": [],
            }
        )
        write_json(selected, cycle)
        identity["sha256"] = sha256_file(selected)
    write_json(path, value)

    report = build_report(path)
    assert report["active_delivery_queue"] == []
    inventory = report["delivery_action_inventory"]
    assert [row["action_class"] for row in inventory] == [
        "USER_CONFIRMATION",
        "CREDENTIAL",
        "ENVIRONMENT",
    ]
    assert {row["verification_status"] for row in inventory} == {"UNVERIFIED"}
    assert [row["needs_user_action"] for row in inventory] == [False, False, False]
    assert report["attention_summary"] == {
        "active_count": 0,
        "declared_active_count": 3,
        "confirmed_active_count": 0,
        "needs_user_action_count": 0,
        "lane_without_active_phase_count": 4,
        "oldest_active_seconds": None,
        "counts_by_action_class": {
            "USER_CONFIRMATION": 0,
            "CREDENTIAL": 0,
            "ENVIRONMENT": 0,
            "GOVERNANCE": 0,
            "GPU_EXECUTION": 0,
            "EXTERNAL_DEPENDENCY": 0,
            "ACTIVE_WORK": 0,
        },
        "counts_by_verification_status": {
            "CONFIRMED_ACTIVE": 0,
            "UNVERIFIED": 3,
            "EXPIRED": 0,
            "RESOLVED": 0,
            "SUPERSEDED": 0,
        },
    }


def action_attestation(
    tmp_path: Path,
    manifest_path: Path,
    *,
    lane_index: int = 0,
    state: str = "ACTIVE",
    owner: str = "USER",
    valid_until: str | None = "2099-01-01T00:00:00Z",
) -> Path:
    manifest_value = json.loads(manifest_path.read_text(encoding="utf-8"))
    ledger_identity = manifest_value["lanes"][lane_index]["work_cycle_ledgers"][0]
    ledger_path = tmp_path / ledger_identity["path"]
    cycle = json.loads(ledger_path.read_text(encoding="utf-8"))
    active = next(span for span in cycle["spans"] if span["status"] == "ACTIVE")
    evidence = write_json(tmp_path / f"action-{lane_index}-evidence.json", {"ok": True})
    return write_json(
        tmp_path / f"action-{lane_index}-{state.lower()}.json",
        {
            "schema_version": "community-action-attestation-v1",
            "claim_boundary": "CURRENT_ACTION_STATE_ONLY_NOT_LEDGER_MUTATION",
            "generated_at": "2026-01-01T00:05:00Z",
            "valid_until": valid_until,
            "ledger_identity": {
                "path": ledger_path.name,
                "sha256": sha256_file(ledger_path),
            },
            "cycle_id": cycle["cycle_id"],
            "span_id": active["span_id"],
            "state": state,
            "action_owner": owner,
            "resource_id": active.get("resource_id"),
            "evidence": [{"path": evidence.name, "sha256": sha256_file(evidence)}],
        },
    )


def test_fresh_attestation_is_required_for_current_user_action(
    tmp_path: Path,
) -> None:
    path = manifest(tmp_path)
    value = json.loads(path.read_text(encoding="utf-8"))
    identity = value["lanes"][0]["work_cycle_ledgers"][0]
    selected = tmp_path / identity["path"]
    cycle = json.loads(selected.read_text(encoding="utf-8"))
    cycle["spans"].append(
        {
            "span_id": "user-confirmation",
            "phase": "EXTERNAL_WAIT",
            "actor": "EXTERNAL",
            "resource_id": "USER_BROWSER_CONFIRMATION",
            "started_at": "2026-01-01T00:04:00Z",
            "ended_at": None,
            "status": "ACTIVE",
            "evidence": [],
        }
    )
    write_json(selected, cycle)
    identity["sha256"] = sha256_file(selected)
    write_json(path, value)
    attestation = action_attestation(tmp_path, path)

    report = build_report(path, [attestation])

    assert len(report["active_delivery_queue"]) == 1
    row = report["active_delivery_queue"][0]
    assert row["verification_status"] == "CONFIRMED_ACTIVE"
    assert row["action_owner"] == "USER"
    assert row["needs_user_action"] is True
    assert report["attention_summary"]["needs_user_action_count"] == 1
    assert report["attention_summary"]["declared_active_count"] == 1


@pytest.mark.parametrize(
    ("state", "owner", "valid_until", "expected"),
    [
        ("ACTIVE", "USER", "2026-01-01T00:06:00Z", "EXPIRED"),
        ("RESOLVED", "NONE", None, "RESOLVED"),
        ("SUPERSEDED", "NONE", None, "SUPERSEDED"),
    ],
)
def test_noncurrent_attestations_never_create_user_work(
    tmp_path: Path,
    state: str,
    owner: str,
    valid_until: str | None,
    expected: str,
) -> None:
    path = manifest(tmp_path)
    value = json.loads(path.read_text(encoding="utf-8"))
    identity = value["lanes"][0]["work_cycle_ledgers"][0]
    selected = tmp_path / identity["path"]
    cycle = json.loads(selected.read_text(encoding="utf-8"))
    cycle["spans"].append(
        {
            "span_id": "user-confirmation",
            "phase": "EXTERNAL_WAIT",
            "actor": "EXTERNAL",
            "resource_id": "USER_BROWSER_CONFIRMATION",
            "started_at": "2026-01-01T00:04:00Z",
            "ended_at": None,
            "status": "ACTIVE",
            "evidence": [],
        }
    )
    write_json(selected, cycle)
    identity["sha256"] = sha256_file(selected)
    write_json(path, value)
    attestation = action_attestation(
        tmp_path,
        path,
        state=state,
        owner=owner,
        valid_until=valid_until,
    )

    report = build_report(path, [attestation])

    assert report["active_delivery_queue"] == []
    row = report["delivery_action_inventory"][0]
    assert row["verification_status"] == expected
    assert report["attention_summary"]["needs_user_action_count"] == 0
    expected_seconds = 120.0 if expected == "EXPIRED" else 60.0
    assert row["active_seconds"] == expected_seconds
    assert report["prospective_phase_time"]["external_wait_seconds"] == (
        expected_seconds
    )


def test_action_attestation_resource_drift_is_rejected(tmp_path: Path) -> None:
    path = manifest(tmp_path)
    value = json.loads(path.read_text(encoding="utf-8"))
    identity = value["lanes"][0]["work_cycle_ledgers"][0]
    selected = tmp_path / identity["path"]
    cycle = json.loads(selected.read_text(encoding="utf-8"))
    cycle["spans"].append(
        {
            "span_id": "current",
            "phase": "EXTERNAL_WAIT",
            "actor": "EXTERNAL",
            "resource_id": "USER_REVIEW",
            "started_at": "2026-01-01T00:04:00Z",
            "ended_at": None,
            "status": "ACTIVE",
            "evidence": [],
        }
    )
    write_json(selected, cycle)
    identity["sha256"] = sha256_file(selected)
    write_json(path, value)
    attestation = action_attestation(tmp_path, path)
    attestation_value = json.loads(attestation.read_text(encoding="utf-8"))
    attestation_value["resource_id"] = "USER_DIFFERENT_REVIEW"
    write_json(attestation, attestation_value)

    with pytest.raises(ValueError, match="resource_id changed"):
        build_report(path, [attestation])


def test_duplicate_action_attestation_is_rejected(tmp_path: Path) -> None:
    path = manifest(tmp_path)
    value = json.loads(path.read_text(encoding="utf-8"))
    identity = value["lanes"][0]["work_cycle_ledgers"][0]
    selected = tmp_path / identity["path"]
    cycle = json.loads(selected.read_text(encoding="utf-8"))
    cycle["spans"].append(
        {
            "span_id": "current",
            "phase": "ENVIRONMENT_SETUP",
            "actor": "AGENT",
            "resource_id": None,
            "started_at": "2026-01-01T00:04:00Z",
            "ended_at": None,
            "status": "ACTIVE",
            "evidence": [],
        }
    )
    write_json(selected, cycle)
    identity["sha256"] = sha256_file(selected)
    write_json(path, value)
    attestation = action_attestation(tmp_path, path, owner="AGENT")

    with pytest.raises(ValueError, match="duplicate action attestation"):
        build_report(path, [attestation, attestation])


def test_action_attestation_evidence_drift_is_rejected(tmp_path: Path) -> None:
    path = manifest(tmp_path)
    value = json.loads(path.read_text(encoding="utf-8"))
    identity = value["lanes"][0]["work_cycle_ledgers"][0]
    selected = tmp_path / identity["path"]
    cycle = json.loads(selected.read_text(encoding="utf-8"))
    cycle["spans"].append(
        {
            "span_id": "current",
            "phase": "EXTERNAL_WAIT",
            "actor": "EXTERNAL",
            "resource_id": "USER_REVIEW",
            "started_at": "2026-01-01T00:04:00Z",
            "ended_at": None,
            "status": "ACTIVE",
            "evidence": [],
        }
    )
    write_json(selected, cycle)
    identity["sha256"] = sha256_file(selected)
    write_json(path, value)
    attestation = action_attestation(tmp_path, path)
    write_json(tmp_path / "action-0-evidence.json", {"ok": False})

    with pytest.raises(ValueError, match="action evidence 0 identity changed"):
        build_report(path, [attestation])


def test_phase_time_separates_overhead_external_wait_and_productive_work(
    tmp_path: Path,
) -> None:
    path = manifest(tmp_path)
    value = json.loads(path.read_text(encoding="utf-8"))
    identity = value["lanes"][0]["work_cycle_ledgers"][0]
    selected = tmp_path / identity["path"]
    cycle = json.loads(selected.read_text(encoding="utf-8"))
    evidence = cycle["milestones"][0]["evidence"]
    cycle["spans"].extend(
        [
            {
                "span_id": "environment",
                "phase": "ENVIRONMENT_SETUP",
                "actor": "AGENT",
                "resource_id": None,
                "started_at": "2026-01-01T00:00:00Z",
                "ended_at": "2026-01-01T00:00:10Z",
                "status": "COMPLETE",
                "evidence": evidence,
            },
            {
                "span_id": "governance",
                "phase": "GOVERNANCE_VALIDATION",
                "actor": "AGENT",
                "resource_id": None,
                "started_at": "2026-01-01T00:00:10Z",
                "ended_at": "2026-01-01T00:00:20Z",
                "status": "COMPLETE",
                "evidence": evidence,
            },
            {
                "span_id": "external",
                "phase": "EXTERNAL_WAIT",
                "actor": "EXTERNAL",
                "resource_id": "MAINTAINER_REVIEW",
                "started_at": "2026-01-01T00:00:20Z",
                "ended_at": "2026-01-01T00:00:50Z",
                "status": "COMPLETE",
                "evidence": evidence,
            },
        ]
    )
    write_json(selected, cycle)
    identity["sha256"] = sha256_file(selected)
    write_json(path, value)

    phase_time = build_report(path)["prospective_phase_time"]
    assert phase_time["accounted_phase_seconds"] == 170.0
    assert phase_time["attributed_active_seconds"] == 140.0
    assert phase_time["environment_governance_seconds"] == 20.0
    assert phase_time[
        "environment_governance_share_of_attributed_active"
    ] == pytest.approx(1 / 7)
    assert phase_time["external_wait_seconds"] == 30.0
    assert phase_time["external_wait_share_of_accounted_phase_time"] == pytest.approx(
        3 / 17
    )
    assert phase_time["productive_seconds"] == 120.0
    assert phase_time["productive_share_of_attributed_active"] == pytest.approx(6 / 7)
