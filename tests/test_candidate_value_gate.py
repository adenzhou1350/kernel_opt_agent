#!/usr/bin/env python3
"""Focused tests for the pre-implementation candidate value gate."""

from __future__ import annotations

import copy
import hashlib
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from candidate_value_gate import evaluate, request_template  # noqa: E402


def evidence_ref() -> dict:
    path = Path(__file__).resolve()
    return {
        "path": path.as_posix(),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def request() -> dict:
    identity = evidence_ref()
    return {
        "schema_version": "candidate-value-gate-v1",
        "candidate_id": "candidate",
        "production_path_reachability": "CONFIRMED",
        "expected_gain": {
            "whole_workload_lower_percent": 3.2,
            "whole_workload_median_percent": 3.7,
            "whole_workload_upper_percent": 4.5,
        },
        "workload_coverage_fraction": 0.5,
        "maintenance_surface": {
            "production_files_changed": 2,
            "production_lines_changed": 100,
            "adds_protocol_variant": False,
            "adds_public_api": False,
        },
        "delivery_evidence": {
            "focused_correctness_pass": True,
            "clean_commit": True,
            "reproduction_command_present": True,
            "real_workload_pass": True,
            "target_hardware_pass": True,
            "no_regression_pass": True,
        },
        "evidence": {
            "production_path": identity.copy(),
            "expected_gain": identity.copy(),
            "delivery": identity.copy(),
        },
        "policy": {
            "materiality_floor_percent": 2.0,
            "narrow_scope_fraction": 0.1,
            "minimum_gain_density_percent_per_point": 0.75,
        },
    }


def test_high_value_candidate_can_reach_ready() -> None:
    result = evaluate(request())
    assert result["recommended_action"] == "READY_FOR_REVIEW"
    assert result["review_cost_points"] == 2.5


def test_template_is_fail_closed_and_schema_valid() -> None:
    value = request_template()
    assert value["candidate_id"] == "replace-me"
    assert evaluate(value)["recommended_action"] == "PROVE_REACHABILITY_FIRST"


def test_confirmed_path_with_unknown_ceiling_requests_quantification() -> None:
    value = request_template()
    value["candidate_id"] = "confirmed-path"
    value["production_path_reachability"] = "CONFIRMED"
    value["evidence"]["production_path"] = evidence_ref()
    result = evaluate(value)
    assert result["recommended_action"] == "QUANTIFY_WHOLE_WORKLOAD_CEILING"
    assert result["optimistic_gain_density_percent_per_point"] is None


def test_low_surface_draft_can_open_while_ceiling_is_quantified() -> None:
    value = request()
    value["expected_gain"] = {
        "whole_workload_lower_percent": None,
        "whole_workload_median_percent": None,
        "whole_workload_upper_percent": None,
    }
    result = evaluate(value)
    assert (
        result["recommended_action"]
        == "OPEN_OR_KEEP_DRAFT_AND_QUANTIFY_WHOLE_WORKLOAD_CEILING"
    )
    assert result["optimistic_gain_density_percent_per_point"] is None

    value["maintenance_surface"]["adds_protocol_variant"] = True
    assert evaluate(value)["recommended_action"] == "QUANTIFY_WHOLE_WORKLOAD_CEILING"


def test_narrow_protocol_change_is_held_at_draft() -> None:
    value = request()
    value["expected_gain"] = {
        "whole_workload_lower_percent": 2.2,
        "whole_workload_median_percent": 2.9,
        "whole_workload_upper_percent": 2.9,
    }
    value["workload_coverage_fraction"] = 0.05
    value["maintenance_surface"] = {
        "production_files_changed": 4,
        "production_lines_changed": 80,
        "adds_protocol_variant": True,
        "adds_public_api": False,
    }
    result = evaluate(value)
    assert result["recommended_action"] == "HOLD_AT_DRAFT_LOW_VALUE_DENSITY"
    assert result["optimistic_gain_density_percent_per_point"] < 0.75


def test_optimistic_ceiling_can_stop_before_qualification() -> None:
    value = request()
    value["expected_gain"] = {
        "whole_workload_lower_percent": None,
        "whole_workload_median_percent": None,
        "whole_workload_upper_percent": 1.8,
    }
    assert (
        evaluate(value)["recommended_action"]
        == "STOP_LOW_VALUE_BEFORE_HEAVY_VALIDATION"
    )


def test_disproven_production_path_stops_without_more_qualification() -> None:
    value = request()
    value["candidate_id"] = "default-backend-unreachable"
    value["production_path_reachability"] = "DISPROVEN"
    value["expected_gain"] = {
        "whole_workload_lower_percent": 0.0,
        "whole_workload_median_percent": 0.0,
        "whole_workload_upper_percent": 0.0,
    }
    value["workload_coverage_fraction"] = 0.0
    result = evaluate(value)
    assert result["recommended_action"] == "STOP_UNREACHABLE_PRODUCTION_PATH"
    assert result["optimistic_gain_density_percent_per_point"] == 0.0

    value["expected_gain"]["whole_workload_upper_percent"] = 0.1
    with pytest.raises(ValueError, match="requires a zero whole-workload interval"):
        evaluate(value)

    value["expected_gain"]["whole_workload_upper_percent"] = 0.0
    value["workload_coverage_fraction"] = 0.01
    with pytest.raises(ValueError, match="requires zero workload coverage"):
        evaluate(value)


def test_draft_minimum_precedes_expensive_qualification() -> None:
    value = request()
    value["delivery_evidence"]["real_workload_pass"] = False
    assert (
        evaluate(value)["recommended_action"]
        == "OPEN_OR_KEEP_DRAFT_PENDING_QUALIFICATION"
    )
    value["delivery_evidence"]["focused_correctness_pass"] = False
    assert evaluate(value)["recommended_action"] == "COMPLETE_DRAFT_MINIMUM"


def test_unproven_path_and_invalid_requests_fail_closed() -> None:
    value = request()
    value["production_path_reachability"] = "UNPROVEN"
    assert evaluate(value)["recommended_action"] == "PROVE_REACHABILITY_FIRST"
    value["production_path_reachability"] = "INFERRED"
    assert evaluate(value)["recommended_action"] == "PROVE_REACHABILITY_FIRST"

    extra = copy.deepcopy(value)
    extra["unreviewed"] = True
    with pytest.raises(ValueError, match="additional property"):
        evaluate(extra)

    bad_interval = request()
    bad_interval["expected_gain"]["whole_workload_lower_percent"] = 5.0
    with pytest.raises(ValueError, match="interval is not ordered"):
        evaluate(bad_interval)

    incomplete_interval = request()
    incomplete_interval["expected_gain"]["whole_workload_lower_percent"] = None
    with pytest.raises(ValueError, match="both be known or null"):
        evaluate(incomplete_interval)

    missing_upper = request()
    missing_upper["expected_gain"]["whole_workload_upper_percent"] = None
    with pytest.raises(ValueError, match="upper must be known"):
        evaluate(missing_upper)

    bad_evidence = request()
    bad_evidence["evidence"]["production_path"]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="production_path evidence hash mismatch"):
        evaluate(bad_evidence)


def test_material_claims_require_evidence_identities() -> None:
    confirmed = request()
    confirmed["evidence"]["production_path"] = None
    with pytest.raises(ValueError, match="reachability requires evidence"):
        evaluate(confirmed)

    numeric = request()
    numeric["evidence"]["expected_gain"] = None
    with pytest.raises(ValueError, match="numeric whole-workload interval"):
        evaluate(numeric)

    delivery = request()
    delivery["evidence"]["delivery"] = None
    with pytest.raises(ValueError, match="positive delivery evidence"):
        evaluate(delivery)
