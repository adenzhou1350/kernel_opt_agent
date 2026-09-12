#!/usr/bin/env python3
"""Focused tests for explicit portfolio PR-stage reconciliation."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from community_portfolio_pr_audit import (  # noqa: E402
    compare_stage,
    ledger_stage,
    parse_binding,
    requires_reconciliation,
)


def cycle(*milestones: str, url: str | None = None, merged: bool = False) -> dict:
    return {
        "milestones": [{"kind": kind} for kind in milestones],
        "outcome": {"pull_request_url": url, "merged": merged},
    }


def observed(stage: str) -> dict:
    return {
        "current_stage": stage,
        "current_stage_since": "2026-01-01T00:10:00Z",
    }


def test_detects_missing_draft_and_ready_transitions() -> None:
    draft = compare_stage(
        "cycle", "https://github.com/o/r/pull/1", cycle(), observed("DRAFT")
    )
    ready = compare_stage(
        "cycle",
        "https://github.com/o/r/pull/1",
        cycle("PR_DRAFT_OPENED"),
        observed("READY"),
    )
    assert draft["status"] == "LEDGER_LAGS_EXTERNAL"
    assert draft["suggested_stage"] == "DRAFT"
    assert ready["status"] == "LEDGER_LAGS_EXTERNAL"
    assert ready["suggested_stage"] == "READY"


def test_stage_comparison_is_fail_closed_for_snapshot_regression_and_close() -> None:
    ready_cycle = cycle("PR_DRAFT_OPENED", "PR_READY_FOR_REVIEW")
    assert ledger_stage(ready_cycle) == "READY"
    assert (
        compare_stage(
            "cycle", "https://github.com/o/r/pull/1", ready_cycle, observed("DRAFT")
        )["status"]
        == "EXTERNAL_SNAPSHOT_LAGS_LEDGER"
    )
    assert (
        compare_stage(
            "cycle", "https://github.com/o/r/pull/1", ready_cycle, observed("CLOSED")
        )["status"]
        == "EXTERNAL_CLOSED_UNREPRESENTED"
    )


def test_every_non_aligned_public_stage_requires_reconciliation() -> None:
    ready_cycle = cycle("PR_DRAFT_OPENED", "PR_READY_FOR_REVIEW")
    aligned = compare_stage(
        "cycle", "https://github.com/o/r/pull/1", ready_cycle, observed("READY")
    )
    regressed = compare_stage(
        "cycle", "https://github.com/o/r/pull/1", ready_cycle, observed("DRAFT")
    )
    closed = compare_stage(
        "cycle", "https://github.com/o/r/pull/1", ready_cycle, observed("CLOSED")
    )
    assert requires_reconciliation(aligned) is False
    assert requires_reconciliation(regressed) is True
    assert requires_reconciliation(closed) is True


def test_binding_requires_an_explicit_github_pull_request() -> None:
    assert parse_binding("cycle=https://github.com/o/r/pull/1") == (
        "cycle",
        "https://github.com/o/r/pull/1",
    )
    with pytest.raises(argparse.ArgumentTypeError):
        parse_binding("cycle=not-a-pr")
