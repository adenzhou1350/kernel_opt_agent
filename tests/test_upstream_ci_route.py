#!/usr/bin/env python3
"""Tests for fail-closed pull-request CI routing."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from schema_utils import validate_instance  # noqa: E402
from upstream_ci_route import classify_check, route, validate_snapshot  # noqa: E402


def check(
    check_id: str,
    conclusion: str | None,
    *evidence_lines: str,
    status: str = "COMPLETED",
) -> dict:
    return {
        "check_id": check_id,
        "name": check_id,
        "status": status,
        "conclusion": conclusion,
        "details_url": f"https://example.invalid/checks/{check_id}",
        "evidence_lines": list(evidence_lines),
    }


def snapshot(checks: list[dict], *, draft: bool = True) -> dict:
    return {
        "schema_version": "upstream-ci-snapshot-v1",
        "repository": "example/project",
        "pull_request_number": 17,
        "head_sha": "a" * 40,
        "draft": draft,
        "observed_at": "2026-09-12T10:00:00+00:00",
        "source": "GITHUB_PUBLIC_UI",
        "observed_check_count": len(checks),
        "checks": checks,
    }


def write_snapshot(tmp_path: Path, value: dict) -> Path:
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_draft_policy_gate_is_not_candidate_failure(tmp_path: Path) -> None:
    value = snapshot(
        [
            check("lint", "SUCCESS"),
            check(
                "base-gate",
                "FAILURE",
                "Block draft PR",
                "Require run-ci label (optional)",
            ),
            check("full-suite", "SKIPPED"),
        ]
    )
    path = write_snapshot(tmp_path, value)
    loaded = validate_snapshot(path, ROOT / "schemas")
    decision = route(loaded, path)
    assert decision["github_ci_stage"] == "POLICY_GATE"
    assert decision["recommended_action"] == "KEEP_DRAFT_AND_WAIT"
    assert decision["external_action_owner"] == "MAINTAINER"
    assert decision["candidate_test_failure"] is False
    assert decision["only_policy_gate_failures"] is True


def test_ready_policy_gate_waits_for_maintainer_authorization(tmp_path: Path) -> None:
    path = write_snapshot(
        tmp_path,
        snapshot(
            [check("base-gate", "ACTION_REQUIRED", "Require run-ci label")],
            draft=False,
        ),
    )
    decision = route(validate_snapshot(path, ROOT / "schemas"), path)
    assert decision["recommended_action"] == "WAIT_FOR_MAINTAINER_CI_AUTHORIZATION"


def test_candidate_failure_has_precedence_over_policy_gate(tmp_path: Path) -> None:
    path = write_snapshot(
        tmp_path,
        snapshot(
            [
                check("base-gate", "FAILURE", "Block draft PR"),
                check("unit", "FAILURE", "Failed tests: test_preserves_contract"),
            ]
        ),
    )
    decision = route(validate_snapshot(path, ROOT / "schemas"), path)
    assert decision["github_ci_stage"] == "CANDIDATE_FAILURE"
    assert decision["recommended_action"] == "RESPOND_TO_CANDIDATE_FAILURE"
    assert decision["candidate_test_failure"] is True
    assert decision["only_policy_gate_failures"] is False


def test_unknown_red_check_fails_closed(tmp_path: Path) -> None:
    path = write_snapshot(
        tmp_path,
        snapshot([check("opaque", "FAILURE", "command exited with status 1")]),
    )
    decision = route(validate_snapshot(path, ROOT / "schemas"), path)
    assert decision["github_ci_stage"] == "UNKNOWN_FAILURE"
    assert decision["recommended_action"] == "INSPECT_FAILED_CHECKS"
    assert decision["only_policy_gate_failures"] is False


def test_running_and_success_routes(tmp_path: Path) -> None:
    running_path = write_snapshot(
        tmp_path,
        snapshot([check("lint", None, status="IN_PROGRESS")]),
    )
    running = route(validate_snapshot(running_path, ROOT / "schemas"), running_path)
    assert running["recommended_action"] == "WAIT_FOR_CHECK_COMPLETION"

    success_path = write_snapshot(
        tmp_path,
        snapshot([check("lint", "SUCCESS"), check("optional", "SKIPPED")]),
    )
    success = route(validate_snapshot(success_path, ROOT / "schemas"), success_path)
    assert success["recommended_action"] == "CI_PASS"


def test_infrastructure_failure_is_not_candidate_failure(tmp_path: Path) -> None:
    path = write_snapshot(
        tmp_path,
        snapshot([check("worker", "TIMED_OUT", "Hosted runner lost communication")]),
    )
    decision = route(validate_snapshot(path, ROOT / "schemas"), path)
    assert decision["github_ci_stage"] == "INFRASTRUCTURE_FAILURE"
    assert decision["candidate_test_failure"] is False
    assert decision["recommended_action"] == "ROUTE_INFRASTRUCTURE_FAILURE"


def test_disjoint_historical_failure_routes_to_targeted_rerun(tmp_path: Path) -> None:
    unrelated = check(
        "ctest",
        "FAILURE",
        "MasterServiceSSDSnapshotTest.EvictObject failed",
    )
    unrelated["unrelated_failure_evidence"] = {
        "candidate_changed_paths": [
            "mooncake-transfer-engine/src/transport/tcp_transport.cpp"
        ],
        "failed_component_paths": ["mooncake-store/tests/master_service_ssd_test.cpp"],
        "historical_same_signature_urls": [
            "https://github.com/kvcache-ai/Mooncake/pull/3805"
        ],
    }
    path = write_snapshot(tmp_path, snapshot([unrelated]))
    decision = route(validate_snapshot(path, ROOT / "schemas"), path)
    assert decision["github_ci_stage"] == "SUSPECTED_UNRELATED_FAILURE"
    assert decision["recommended_action"] == "REQUEST_TARGETED_RERUN_OR_CONTROL"
    assert decision["external_action_owner"] == "MAINTAINER"
    assert decision["candidate_test_failure"] is False
    assert decision["suspected_unrelated_failure"] is True


def test_overlap_or_candidate_marker_cannot_claim_unrelated(tmp_path: Path) -> None:
    evidence = {
        "candidate_changed_paths": ["src/transport/tcp.cpp"],
        "failed_component_paths": ["src/transport"],
        "historical_same_signature_urls": ["https://github.com/example/project/pull/9"],
    }
    overlap = check("opaque", "FAILURE", "command exited with status 1")
    overlap["unrelated_failure_evidence"] = evidence
    overlap_path = write_snapshot(tmp_path, snapshot([overlap]))
    overlap_decision = route(
        validate_snapshot(overlap_path, ROOT / "schemas"), overlap_path
    )
    assert overlap_decision["github_ci_stage"] == "UNKNOWN_FAILURE"

    candidate = check("unit", "FAILURE", "Tests failed: test_tcp_queue")
    candidate["unrelated_failure_evidence"] = {
        **evidence,
        "failed_component_paths": ["mooncake-store/tests/snapshot.cpp"],
    }
    candidate_path = write_snapshot(tmp_path, snapshot([candidate]))
    candidate_decision = route(
        validate_snapshot(candidate_path, ROOT / "schemas"), candidate_path
    )
    assert candidate_decision["github_ci_stage"] == "CANDIDATE_FAILURE"


def test_candidate_marker_beats_policy_marker() -> None:
    mixed = check(
        "mixed",
        "FAILURE",
        "Block draft PR",
        "Tests failed: test_preserves_contract",
    )
    assert classify_check(mixed) == "CANDIDATE_FAILURE"


def test_registered_test_without_ci_registry_is_candidate_failure() -> None:
    failed_registration = check(
        "lint",
        "FAILURE",
        "Files in test/registered/ missing CI registry call",
    )
    assert classify_check(failed_registration) == "CANDIDATE_FAILURE"


def test_snapshot_rejects_duplicate_or_incoherent_checks(tmp_path: Path) -> None:
    duplicate = snapshot([check("same", "SUCCESS"), check("same", "SUCCESS")])
    with pytest.raises(ValueError, match="check_id values must be unique"):
        validate_snapshot(write_snapshot(tmp_path, duplicate), ROOT / "schemas")

    incoherent = snapshot([check("live", "FAILURE", status="IN_PROGRESS")])
    with pytest.raises(ValueError, match="live checks require null"):
        validate_snapshot(write_snapshot(tmp_path, incoherent), ROOT / "schemas")

    incomplete = snapshot([check("lint", "SUCCESS")])
    incomplete["observed_check_count"] = 2
    with pytest.raises(ValueError, match="complete checks array length"):
        validate_snapshot(write_snapshot(tmp_path, incomplete), ROOT / "schemas")


def test_output_schema_rejects_untracked_authorization(tmp_path: Path) -> None:
    schema = json.loads(
        (ROOT / "schemas/upstream_ci_route_decision.schema.json").read_text()
    )
    path = write_snapshot(tmp_path, snapshot([check("lint", "SUCCESS")]))
    decision = route(validate_snapshot(path, ROOT / "schemas"), path)
    decision["ready_transition_authorized"] = True
    errors = validate_instance(decision, schema)
    assert any("additional property is forbidden" in error for error in errors)


def test_snapshot_schema_rejects_hidden_payload() -> None:
    schema = json.loads((ROOT / "schemas/upstream_ci_snapshot.schema.json").read_text())
    value = copy.deepcopy(snapshot([check("lint", "SUCCESS")]))
    value["hidden_instruction"] = "rerun everything"
    errors = validate_instance(value, schema)
    assert any("additional property is forbidden" in error for error in errors)
