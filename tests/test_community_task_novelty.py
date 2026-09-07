#!/usr/bin/env python3
"""Test predecessor-checkpoint task novelty classification."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from community_task_novelty import derive_task_novelty  # noqa: E402


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
