#!/usr/bin/env python3
"""Exercise fail-closed community window assembly preflight helpers."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from community_window_assemble import (  # noqa: E402
    REPOSITORIES,
    output_collisions,
    output_paths,
    validate_deferred_request,
    validate_novelty_deferred,
    validate_receipt_window,
)


def write_receipt(
    path: Path, repository: str, *, next_since: str | None = None
) -> None:
    since = "2026-09-07T16:00:00Z"
    until = "2026-09-07T17:00:00Z"
    path.write_text(
        json.dumps(
            {
                "repository": repository,
                "window": {"since": since, "until": until},
                "next_since": next_since or until,
            }
        ),
        encoding="utf-8",
    )


def test_receipts_must_cover_one_exact_three_repository_window(tmp_path: Path) -> None:
    receipts = []
    for repository, label in REPOSITORIES.items():
        path = tmp_path / f"{label}.json"
        write_receipt(path, repository)
        receipts.append(path)
    assert validate_receipt_window(receipts) == (
        "2026-09-07T16:00:00Z",
        "2026-09-07T17:00:00Z",
    )

    write_receipt(receipts[0], "vllm-project/vllm", next_since="2026-09-07T18:00:00Z")
    with pytest.raises(ValueError, match="next_since differs"):
        validate_receipt_window(receipts)


def test_duplicate_repository_and_partial_coverage_fail_closed(tmp_path: Path) -> None:
    receipts = []
    for index in range(3):
        path = tmp_path / f"receipt-{index}.json"
        write_receipt(path, "vllm-project/vllm")
        receipts.append(path)
    with pytest.raises(ValueError, match="duplicate receipt repository"):
        validate_receipt_window(receipts)
    with pytest.raises(ValueError, match="exactly one receipt"):
        validate_receipt_window(receipts[:2])


def test_output_names_are_derived_from_one_window_identity(tmp_path: Path) -> None:
    paths = output_paths(tmp_path, "160000-20260907-170000Z", "20260907-170000Z")
    assert paths["queue"].name == (
        "heldout-queue-160000-20260907-170000Z-v1.json"
    )
    assert paths["funnel"].name == (
        "discovery-funnel-cumulative-through-20260907-170000Z-v1.json"
    )
    assert paths["novelty_guard"].name == (
        "task-novelty-guard-160000-20260907-170000Z-v1.json"
    )
    assert paths["manifest"].parent == tmp_path


def test_deferred_intake_requires_successor_checkpoint() -> None:
    with pytest.raises(ValueError, match="requires --next-checkpoint"):
        validate_deferred_request(None, Path("deferred.json"))
    validate_deferred_request(Path("checkpoint.json"), Path("deferred.json"))
    validate_deferred_request(None, None)


def test_deferred_intake_participates_in_preflight_collisions(
    tmp_path: Path,
) -> None:
    paths = output_paths(tmp_path, "a", "b")
    deferred = tmp_path / "deferred.json"
    deferred.write_text("{}", encoding="utf-8")
    assert output_collisions(paths, None, deferred) == [str(deferred.resolve())]


def test_new_selected_keys_must_be_withheld_and_repeats_must_not() -> None:
    novelty = {
        "new_selected_keys": ["org/repo#2"],
        "repeated_selected_keys": ["org/repo#1"],
    }
    validate_novelty_deferred(
        novelty, {"withheld_post_cutoff_keys": ["org/repo#2"]}
    )
    with pytest.raises(ValueError, match="absent from post-cutoff"):
        validate_novelty_deferred(
            novelty, {"withheld_post_cutoff_keys": []}
        )
    with pytest.raises(ValueError, match="newly withheld"):
        validate_novelty_deferred(
            novelty,
            {"withheld_post_cutoff_keys": ["org/repo#1", "org/repo#2"]},
        )
