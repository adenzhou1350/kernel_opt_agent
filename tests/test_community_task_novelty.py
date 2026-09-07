#!/usr/bin/env python3
"""Test predecessor-checkpoint task novelty classification."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from community_task_novelty import derive_task_novelty  # noqa: E402
from community_evaluation import validate_suite_task_novelty  # noqa: E402


def checkpoint(*keys: str) -> dict:
    return {"state": {"unique_candidate_keys": list(keys)}}


def queue(items: list[dict], selected_count: int) -> dict:
    return {"items": items, "inventory": {"selected_count": selected_count}}


def item(number: int, selection: str = "SELECTED") -> dict:
    return {
        "repository": "org/repo",
        "pr_number": number,
        "selection": selection,
    }


def test_selected_observations_are_partitioned_by_predecessor_key() -> None:
    report = derive_task_novelty(
        checkpoint("org/repo#1", "other/repo#9"),
        queue([item(2), item(1), item(3, "BACKLOG")], selected_count=2),
    )
    assert report["new_selected_keys"] == ["org/repo#2"]
    assert report["repeated_selected_keys"] == ["org/repo#1"]
    assert report["inventory"] == {
        "selected_observation_count": 2,
        "new_selected_count": 1,
        "repeated_selected_count": 1,
    }
    assert report["policy"]["materialization_gate"] == "ONLY_NEW_SELECTED_KEYS"


def test_inventory_mismatch_and_duplicate_selected_key_fail_closed() -> None:
    with pytest.raises(ValueError, match="inventory differs"):
        derive_task_novelty(checkpoint(), queue([item(1)], selected_count=0))
    with pytest.raises(ValueError, match="duplicate selected"):
        derive_task_novelty(
            checkpoint(), queue([item(1), item(1)], selected_count=2)
        )


def test_suite_v3_tasks_must_be_unique_allowed_prs_with_exact_availability() -> None:
    suite = {
        "tasks": [
            {
                "task_id": "org.repo.2",
                "repository": "org/repo",
                "pr_number": 2,
                "available_at": "2026-09-07T20:00:00Z",
            }
        ]
    }
    guard = {"new_selected_keys": ["org/repo#2"]}
    source_queue = {
        "items": [
            {
                "repository": "org/repo",
                "pr_number": 2,
                "selection": "SELECTED",
                "earliest_public_at": "2026-09-07T20:00:00Z",
            }
        ]
    }
    validate_suite_task_novelty(suite, guard, source_queue)

    blocked = {"tasks": [{**suite["tasks"][0], "pr_number": 1}]}
    with pytest.raises(ValueError, match="absent from novelty allow-list"):
        validate_suite_task_novelty(blocked, guard, source_queue)

    prospective = {
        "tasks": [
            {
                "task_id": "prospective",
                "repository": "org/repo",
                "available_at": "2026-09-07T20:00:00Z",
            }
        ]
    }
    with pytest.raises(ValueError, match="requires PR-backed"):
        validate_suite_task_novelty(prospective, guard, source_queue)

    duplicate = {"tasks": [suite["tasks"][0], suite["tasks"][0]]}
    with pytest.raises(ValueError, match="repeats task key"):
        validate_suite_task_novelty(duplicate, guard, source_queue)

    wrong_time = {
        "tasks": [
            {**suite["tasks"][0], "available_at": "2026-09-07T20:00:01Z"}
        ]
    }
    with pytest.raises(ValueError, match="availability differs"):
        validate_suite_task_novelty(wrong_time, guard, source_queue)
