#!/usr/bin/env python3
"""Focused tests for qualification failure routing."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from qualification_route import evaluate, request_template  # noqa: E402


def attempt() -> dict:
    value = request_template()
    value.update(
        {
            "candidate_id": "candidate",
            "failure_stage": "COMPLETE",
            "tests_collected": 6,
            "tests_executed": 6,
            "exact_source_import_verified": True,
        }
    )
    return value


def test_complete_exact_source_attempt_passes() -> None:
    result = evaluate(attempt())
    assert result["classification"] == "QUALIFICATION_PASS"
    assert result["recommended_action"] == "ACCEPT_THIS_QUALIFICATION_GATE"


def test_official_workflow_native_build_contradiction_is_not_candidate_failure() -> (
    None
):
    value = attempt()
    value.update(
        {
            "workflow_requires_native_build": True,
            "native_build_authorized": False,
            "failure_stage": "NOT_STARTED",
            "tests_collected": 0,
            "tests_executed": 0,
            "exact_source_import_verified": False,
        }
    )
    result = evaluate(value)
    assert result["classification"] == "EXECUTION_CONTRACT_BLOCKED"
    assert result["candidate_disposition"] == "RETAIN"
    assert result["recommended_action"] == (
        "AUTHORIZE_INTRINSIC_BUILD_OR_USE_PREBUILT_CLOSURE"
    )


@pytest.mark.parametrize(
    ("failure", "action"),
    [
        ("IMPORT_SOURCE_MISMATCH", "USE_IMPORT_BOUND_CLOSURE"),
        ("IMAGE_UNAVAILABLE", "MATERIALIZE_PINNED_PREBUILT_CLOSURE"),
        ("ISA_INCOMPATIBLE", "USE_CACHED_OR_PREBUILT_CLOSURE"),
        ("PLATFORM_UNSUPPORTED", "REPAIR_ENVIRONMENT_WITHIN_BUDGET"),
    ],
)
def test_environment_failures_retain_candidate(failure: str, action: str) -> None:
    value = attempt()
    value.update(
        {
            "failure_stage": "TEST_COLLECTION",
            "environment_failure": failure,
            "tests_executed": 0,
            "exact_source_import_verified": False,
        }
    )
    result = evaluate(value)
    assert result["classification"] == "ENVIRONMENT_BLOCKED"
    assert result["candidate_disposition"] == "RETAIN"
    assert result["recommended_action"] == action


def test_environment_repair_budget_stops_dependency_chasing() -> None:
    value = attempt()
    value.update(
        {
            "failure_stage": "TOOLCHAIN_SETUP",
            "environment_failure": "TOOLCHAIN_TIMEOUT",
            "tests_executed": 0,
            "exact_source_import_verified": False,
            "technical_repair_attempts": 1,
            "technical_repair_budget": 1,
        }
    )
    result = evaluate(value)
    assert result["recommended_action"] == "STOP_BOUNDED_ENVIRONMENT_REPAIR"
    assert result["candidate_disposition"] == "RETAIN"


def test_only_exact_source_assertion_failure_rejects_candidate() -> None:
    value = attempt()
    value["candidate_assertion_failures"] = 1
    result = evaluate(value)
    assert result["classification"] == "CANDIDATE_FAILED"
    assert result["candidate_disposition"] == "REJECT_OR_REVISE"

    value["exact_source_import_verified"] = False
    with pytest.raises(ValueError, match="exact imported-source"):
        evaluate(value)


def test_executed_tests_without_import_binding_are_invalid_evidence() -> None:
    value = attempt()
    value["exact_source_import_verified"] = False
    result = evaluate(value)
    assert result["classification"] == "EVIDENCE_INVALID"
    assert result["recommended_action"] == "BIND_ACTUAL_IMPORTED_SOURCE"
    assert result["candidate_disposition"] == "RETAIN"


def test_partial_execution_does_not_become_pass() -> None:
    value = attempt()
    value["tests_executed"] = 5
    value["failure_stage"] = "TEST_BODY"
    result = evaluate(value)
    assert result["classification"] == "INCOMPLETE"
    assert result["recommended_action"] == "CONTINUE_SEALED_TESTS"


def test_invalid_counts_and_unknown_fields_fail_closed() -> None:
    value = attempt()
    value["tests_executed"] = 7
    with pytest.raises(ValueError, match="exceeds tests_collected"):
        evaluate(value)

    value = attempt()
    value["candidate_assertion_failures"] = 7
    with pytest.raises(ValueError, match="exceed executed tests"):
        evaluate(value)

    value = copy.deepcopy(attempt())
    value["hidden"] = True
    with pytest.raises(ValueError, match="additional property"):
        evaluate(value)

    value = attempt()
    value["candidate_assertion_failures"] = 1
    value["environment_failure"] = "PLATFORM_UNSUPPORTED"
    value["failure_stage"] = "TEST_BODY"
    with pytest.raises(ValueError, match="mutually exclusive"):
        evaluate(value)

    value = attempt()
    value["workflow_requires_native_build"] = True
    with pytest.raises(ValueError, match="unauthorized intrinsic native build"):
        evaluate(value)
