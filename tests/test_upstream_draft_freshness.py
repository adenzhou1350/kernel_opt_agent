#!/usr/bin/env python3
"""Focused tests for exact-ref Draft freshness generation."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "kernel_opt.py"


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def repository(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "repository"
    root.mkdir()
    git(root, "init", "-b", "main")
    git(root, "config", "user.name", "Test User")
    git(root, "config", "user.email", "test@example.com")
    (root / "candidate.txt").write_text("base\n", encoding="utf-8")
    git(root, "add", "candidate.txt")
    git(root, "commit", "-m", "base")
    git(root, "checkout", "-b", "topic")
    (root / "candidate.txt").write_text("candidate\n", encoding="utf-8")
    git(root, "commit", "-am", "candidate")
    candidate = git(root, "rev-parse", "HEAD")
    git(root, "update-ref", "refs/remotes/fork/topic", candidate)
    git(root, "checkout", "main")
    return root, candidate


def command(root: Path, output: Path) -> list[str]:
    return [
        sys.executable,
        str(CLI),
        "upstream-draft-freshness",
        "--repository-root",
        str(root),
        "--candidate-id",
        "candidate",
        "--repository",
        "example/project",
        "--branch",
        "topic",
        "--candidate-ref",
        "topic",
        "--upstream-ref",
        "main",
        "--fork-ref",
        "refs/remotes/fork/topic",
        "--exact-head-pull-request-count",
        "0",
        "--observed-at",
        "2026-09-12T08:00:00Z",
        "--ttl-hours",
        "4",
        "--output",
        str(output),
    ]


def test_exact_refs_generate_valid_short_lived_freshness(tmp_path: Path) -> None:
    root, candidate = repository(tmp_path)
    output = tmp_path / "freshness.json"
    completed = subprocess.run(command(root, output), capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    record = json.loads(output.read_text(encoding="utf-8"))
    assert record["candidate_commit"] == candidate
    assert record["fork_branch_commit"] == candidate
    assert record["observed_at"] == "2026-09-12T08:00:00Z"
    assert record["expires_at"] == "2026-09-12T12:00:00Z"
    assert record["checks"] == {
        "draft_submission_eligible": True,
        "exact_head_pull_request_count": 0,
        "fork_branch_matches_candidate": True,
        "merge_conflict": False,
        "touched_paths_unchanged": True,
    }
    duplicate = subprocess.run(command(root, output), capture_output=True, text=True)
    assert duplicate.returncode != 0
    assert "refusing to replace" in duplicate.stderr


def test_upstream_change_to_candidate_path_fails_closed(tmp_path: Path) -> None:
    root, _ = repository(tmp_path)
    (root / "candidate.txt").write_text("upstream drift\n", encoding="utf-8")
    git(root, "commit", "-am", "upstream drift")
    output = tmp_path / "freshness.json"
    completed = subprocess.run(command(root, output), capture_output=True, text=True)
    assert completed.returncode != 0
    assert "touched paths changed upstream" in completed.stderr
    assert not output.exists()


def test_fork_ref_mismatch_fails_closed(tmp_path: Path) -> None:
    root, _ = repository(tmp_path)
    git(root, "update-ref", "refs/remotes/fork/topic", "main")
    output = tmp_path / "freshness.json"
    completed = subprocess.run(command(root, output), capture_output=True, text=True)
    assert completed.returncode != 0
    assert "fork ref does not resolve" in completed.stderr
    assert not output.exists()


def test_existing_exact_head_pr_and_excessive_ttl_fail_closed(tmp_path: Path) -> None:
    root, _ = repository(tmp_path)
    output = tmp_path / "freshness.json"
    existing = command(root, output)
    existing[existing.index("--exact-head-pull-request-count") + 1] = "1"
    completed = subprocess.run(existing, capture_output=True, text=True)
    assert completed.returncode != 0
    assert "must be zero" in completed.stderr
    assert not output.exists()

    excessive = command(root, output)
    excessive[excessive.index("--ttl-hours") + 1] = "6.1"
    completed = subprocess.run(excessive, capture_output=True, text=True)
    assert completed.returncode != 0
    assert "at most 6" in completed.stderr
    assert not output.exists()
