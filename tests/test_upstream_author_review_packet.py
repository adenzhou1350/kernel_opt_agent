#!/usr/bin/env python3
"""Focused tests for exact-commit author review packet preparation."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "kernel_opt.py"


def write(path: Path, value: object | str) -> dict[str, str]:
    raw = (
        value.encode("utf-8")
        if isinstance(value, str)
        else (json.dumps(value, sort_keys=True) + "\n").encode("utf-8")
    )
    path.write_bytes(raw)
    return {"path": path.name, "sha256": hashlib.sha256(raw).hexdigest()}


def review_state() -> dict:
    return {
        "schema_version": "upstream-review-state-v1",
        "pull_request": {
            "url": None,
            "repository": "example/project",
            "number": None,
            "state": "ABSENT",
            "draft": False,
            "internal_candidate_status": "DRAFT_MINIMUM_READY",
        },
        "draft_minimum": {
            "clean_minimal_commit": "PASS",
            "focused_correctness": "PASS",
            "lint_format": "PASS",
            "reproduction": "PASS",
            "claim_boundary": "PASS",
        },
        "ready_gates": {
            "official_correctness": "PENDING",
            "production_reachability": "PASS",
            "materiality": "PENDING",
            "target_workload": "PENDING",
            "known_regression": "PASS",
        },
        "ci": {"state": "NOT_RUN", "classification": "NOT_REQUESTED"},
        "reviewers": {"state": "NONE", "handles": [], "early_review_handles": []},
    }


def freshness(commit: str) -> dict:
    return {
        "schema_version": "upstream-delivery-freshness-v1",
        "observed_at": "2026-09-12T04:00:00Z",
        "expires_at": "2026-09-12T09:00:00Z",
        "candidate_id": "candidate",
        "repository": "example/project",
        "branch": "perf/candidate",
        "candidate_commit": commit,
        "upstream_main_commit": "b" * 40,
        "fork_branch_commit": commit,
        "checks": {
            "fork_branch_matches_candidate": True,
            "touched_paths_unchanged": True,
            "merge_conflict": False,
            "exact_head_pull_request_count": 0,
            "draft_submission_eligible": True,
        },
        "claim_boundary": "LOCAL_REFS_AND_EXACT_HEAD_PR_QUERY_AT_OBSERVED_TIME",
    }


def inbox(tmp_path: Path, *, action_ready: bool = True) -> Path:
    commit = "a" * 40
    state = review_state()
    if not action_ready:
        state["draft_minimum"]["lint_format"] = "PENDING"
    state_source = write(tmp_path / "review-state.json", state)
    body_source = write(tmp_path / "body.md", "Summary\n\nTest Plan\n")
    freshness_source = write(tmp_path / "freshness.json", freshness(commit))
    manifest = {
        "schema_version": "upstream-delivery-inbox-v5",
        "observed_at": "2026-09-12T04:30:00Z",
        "candidates": [
            {
                "candidate_id": "candidate",
                "lane_id": "vllm",
                "review_state": state_source,
                "review_handoff": None,
                "draft_materials": {
                    "title": "Improve candidate",
                    "submission_type": "DRAFT_PULL_REQUEST",
                    "repository": "example/project",
                    "branch": "perf/candidate",
                    "commit": commit,
                    "action_url": (
                        "https://github.com/example/project/compare/"
                        "main...human:project:perf/candidate?expand=1"
                    ),
                    "body": body_source,
                    "freshness_evidence": freshness_source,
                    "author_accountability": None,
                },
            }
        ],
    }
    path = tmp_path / "inbox.json"
    write(path, manifest)
    return path


def command(manifest: Path, output: Path, candidate_id: str = "candidate") -> list[str]:
    return [
        sys.executable,
        str(SCRIPT),
        "upstream-author-review-packet",
        str(manifest),
        "--candidate-id",
        candidate_id,
        "--output",
        str(output),
    ]


def test_packet_gathers_exact_identity_body_gates_and_command(tmp_path: Path) -> None:
    manifest = inbox(tmp_path)
    output = tmp_path / "AUTHOR_REVIEW.md"
    completed = subprocess.run(
        command(manifest, output), capture_output=True, text=True
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    packet = output.read_text(encoding="utf-8")
    assert result["claim_boundary"] == "MACHINE_PREPARED_HUMAN_REVIEW_PACKET_ONLY"
    assert "a" * 40 in packet
    assert "Summary\n\nTest Plan" in packet
    assert "`clean_minimal_commit`" in packet
    assert "`official_correctness`" in packet
    assert "REPLACE_WITH_YOUR_NAME_OR_EMAIL" in packet
    assert "upstream-author-accountability" in packet


def test_packet_requires_exact_pending_author_action(tmp_path: Path) -> None:
    manifest = inbox(tmp_path, action_ready=False)
    output = tmp_path / "AUTHOR_REVIEW.md"
    completed = subprocess.run(
        command(manifest, output), capture_output=True, text=True
    )
    assert completed.returncode != 0
    assert "not awaiting exact-commit" in completed.stderr
    assert not output.exists()


def test_packet_rejects_unknown_candidate_and_overwrite(tmp_path: Path) -> None:
    manifest = inbox(tmp_path)
    output = tmp_path / "AUTHOR_REVIEW.md"
    unknown = subprocess.run(
        command(manifest, output, "missing"), capture_output=True, text=True
    )
    assert unknown.returncode != 0
    assert "resolve exactly once" in unknown.stderr
    first = subprocess.run(command(manifest, output), capture_output=True, text=True)
    assert first.returncode == 0
    duplicate = subprocess.run(
        command(manifest, output), capture_output=True, text=True
    )
    assert duplicate.returncode != 0
    assert "refusing to replace" in duplicate.stderr

