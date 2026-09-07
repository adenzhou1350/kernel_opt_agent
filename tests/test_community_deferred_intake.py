#!/usr/bin/env python3
"""Exercise fail-closed future-cohort metadata intake."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parents[1] if ROOT.parent.name == ".worktrees" else ROOT.parent
sys.path.insert(0, str(ROOT / "scripts"))

from community_deferred_intake import (  # noqa: E402
    build_deferred_intake,
    derive_deferred_intake,
    verify_identity,
)
from community_knowledge import atomic_json, sha256_file  # noqa: E402
from schema_utils import validate_instance  # noqa: E402


def checkpoint(keys: list[str], audits: list[dict]) -> dict:
    return {
        "input_identity": {
            "audit_prefix": audits,
            "corpus_index": {"path": "/corpus/index.json", "sha256": "1" * 64},
            "source_root": "/source",
        },
        "state": {"unique_candidate_keys": keys},
    }


def receipt(repository: str, candidates: list[dict]) -> dict:
    return {
        "repository": repository,
        "window": {
            "since": "2026-09-07T17:00:00Z",
            "until": "2026-09-07T18:00:00Z",
        },
        "candidates": candidates,
    }


def candidate(number: int, public_at: str) -> dict:
    return {
        "pr_number": number,
        "title": f"candidate {number}",
        "created_at": public_at,
        "earliest_public_at": public_at,
        "updated_at": "2026-09-07T17:30:00Z",
        "classifications": ["KERNEL_OR_RUNTIME"],
        "selection_score": 40,
    }


def rows() -> list[tuple[Path, dict]]:
    return [
        (Path("moon.json"), receipt("kvcache-ai/Mooncake", [])),
        (Path("sglang.json"), receipt("sgl-project/sglang", [candidate(2, "2026-09-06T00:00:00Z")])),
        (Path("vllm.json"), receipt("vllm-project/vllm", [candidate(3, "2026-09-07T14:00:00Z")])),
    ]


def test_diff_defers_pre_cutoff_and_withholds_heldout() -> None:
    audit_a = {"path": "/audit-a.json", "sha256": "a" * 64}
    audit_b = {"path": "/audit-b.json", "sha256": "b" * 64}
    predecessor = checkpoint(["vllm-project/vllm#1"], [audit_a])
    successor = checkpoint(
        [
            "vllm-project/vllm#1",
            "sgl-project/sglang#2",
            "vllm-project/vllm#3",
        ],
        [audit_a, audit_b],
    )
    report = derive_deferred_intake(
        predecessor, successor, rows(), "2026-09-07T13:00:00Z"
    )
    assert report["inventory"] == {
        "previous_unique_candidates": 1,
        "current_unique_candidates": 3,
        "new_unique_candidates": 2,
        "deferred_pre_cutoff_count": 1,
        "withheld_post_cutoff_count": 1,
        "receipt_candidate_count": 2,
        "reobserved_candidate_count": 0,
    }
    assert [item["pr_number"] for item in report["items"]] == [2]
    assert report["items"][0]["hypothesis_status"] == "UNREAD"
    assert report["withheld_post_cutoff_keys"] == ["vllm-project/vllm#3"]
    report["input_identity"] = {
        "predecessor_checkpoint": {"path": "/pre.json", "sha256": "c" * 64},
        "successor_checkpoint": {"path": "/post.json", "sha256": "d" * 64},
        "receipts": [
            {"path": f"/{name}.json", "sha256": str(index) * 64}
            for index, name in enumerate(("a", "b", "c"), start=1)
        ],
    }
    schema = json.loads(
        (ROOT / "schemas/community_deferred_intake.schema.json").read_text(
            encoding="utf-8"
        )
    )
    assert not validate_instance(report, schema)


def test_checkpoint_must_be_monotonic_exact_one_window_extension() -> None:
    audit_a = {"path": "/audit-a.json", "sha256": "a" * 64}
    audit_b = {"path": "/audit-b.json", "sha256": "b" * 64}
    predecessor = checkpoint(["vllm-project/vllm#1"], [audit_a])
    with pytest.raises(ValueError, match="removed candidate"):
        derive_deferred_intake(
            predecessor,
            checkpoint(["sgl-project/sglang#2"], [audit_a, audit_b]),
            rows(),
            "2026-09-07T13:00:00Z",
        )
    with pytest.raises(ValueError, match="exact one-window extension"):
        derive_deferred_intake(
            predecessor,
            checkpoint(
                ["vllm-project/vllm#1", "sgl-project/sglang#2"],
                [audit_a, audit_b, {"path": "/audit-c", "sha256": "c" * 64}],
            ),
            rows(),
            "2026-09-07T13:00:00Z",
        )


def test_new_candidates_must_be_bound_to_current_receipts() -> None:
    audit_a = {"path": "/audit-a.json", "sha256": "a" * 64}
    audit_b = {"path": "/audit-b.json", "sha256": "b" * 64}
    predecessor = checkpoint([], [audit_a])
    successor = checkpoint(["vllm-project/vllm#99"], [audit_a, audit_b])
    with pytest.raises(ValueError, match="missing from receipts"):
        derive_deferred_intake(
            predecessor, successor, rows(), "2026-09-07T13:00:00Z"
        )


def test_identity_hash_drift_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "source.json"
    atomic_json(path, {"version": 1})
    value = {"path": path.as_posix(), "sha256": sha256_file(path)}
    assert verify_identity(value, "source") == path.resolve()
    atomic_json(path, {"version": 2})
    with pytest.raises(ValueError, match="source changed"):
        verify_identity(value, "source")


def test_window_12_real_artifacts_replay_to_seven_deferred_items() -> None:
    cohort = (
        WORKSPACE
        / "community-validation/prospective-heldout-outcome-v4-2026-09-07"
    )
    future = WORKSPACE / "community-validation/future-runner-validation-2026-09-07"
    source_root = WORKSPACE / ".worktrees/kernel-opt-materialization-v2"
    corpus = WORKSPACE / "community-optimization-corpus"
    predecessor = future / "funnel-checkpoint-through-174153-v1.json"
    successor = future / "funnel-checkpoint-through-184724-full-v1.json"
    receipts = [
        cohort / f"heldout174153-20260907-184724Z-{name}-dry-run.json"
        for name in ("vllm", "sglang", "mooncake")
    ]
    required = [predecessor, successor, source_root, corpus, *receipts]
    if not all(path.exists() for path in required):
        pytest.skip("window 12 integration artifacts are unavailable")
    report = build_deferred_intake(
        predecessor,
        successor,
        receipts,
        "2026-09-07T13:00:00Z",
        corpus,
        source_root,
        ROOT,
    )
    assert report["inventory"]["new_unique_candidates"] == 7
    assert report["inventory"]["deferred_pre_cutoff_count"] == 7
    assert report["inventory"]["reobserved_candidate_count"] == 3
    assert report["withheld_post_cutoff_keys"] == []
    assert all(item["hypothesis_status"] == "UNREAD" for item in report["items"])
