#!/usr/bin/env python3
"""Focused tests for the pre-implementation candidate value gate."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from candidate_value_gate import evaluate  # noqa: E402


def request() -> dict:
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
