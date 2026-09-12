#!/usr/bin/env python3
"""Focused tests for source-tree supersession decisions."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from source_tree_supersession import evaluate  # noqa: E402


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        stdout=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def repository(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.name", "Test User")
    git(repo, "config", "user.email", "test@example.com")
    (repo / "kernel.py").write_text("VALUE = 1\n", encoding="utf-8")
    git(repo, "add", "kernel.py")
    git(repo, "commit", "-m", "initial")
    return repo, git(repo, "rev-parse", "HEAD")


def test_metadata_only_commit_reuses_source_tree(tmp_path: Path) -> None:
    repo, validated = repository(tmp_path)
    git(repo, "commit", "--amend", "--no-edit", "--date=2026-09-11T00:00:00Z")
    replacement = git(repo, "rev-parse", "HEAD")

    result = evaluate(repo, validated, replacement)

    assert (
        result["validated_source"]["commit"] != result["replacement_source"]["commit"]
    )
    assert result["validated_source"]["tree"] == result["replacement_source"]["tree"]
    assert result["changed_paths"] == []
    assert result["source_requalification_required"] is False
    assert result["decision"] == "SOURCE_TREE_EQUIVALENT_REBIND_NON_SOURCE_IDENTITIES"


def test_content_change_requires_requalification(tmp_path: Path) -> None:
    repo, validated = repository(tmp_path)
    (repo / "kernel.py").write_text("VALUE = 2\n", encoding="utf-8")
    git(repo, "add", "kernel.py")
    git(repo, "commit", "-m", "change source")

    result = evaluate(repo, validated, "HEAD")

    assert result["changed_paths"] == ["kernel.py"]
    assert result["source_requalification_required"] is True
    assert result["decision"] == "SOURCE_TREE_CHANGED_REQUALIFICATION_REQUIRED"


def test_dirty_worktree_fails_closed(tmp_path: Path) -> None:
    repo, validated = repository(tmp_path)
    (repo / "kernel.py").write_text("UNCOMMITTED = True\n", encoding="utf-8")

    with pytest.raises(ValueError, match="clean worktree"):
        evaluate(repo, validated, validated)


def test_untracked_file_fails_closed(tmp_path: Path) -> None:
    repo, validated = repository(tmp_path)
    (repo / "untracked.py").write_text("VALUE = 2\n", encoding="utf-8")

    with pytest.raises(ValueError, match="clean worktree"):
        evaluate(repo, validated, validated)


def test_http_remote_credentials_are_not_persisted(tmp_path: Path) -> None:
    repo, validated = repository(tmp_path)
    git(
        repo, "remote", "add", "origin", "https://token:secret@example.com/org/repo.git"
    )

    result = evaluate(repo, validated, validated)

    assert result["repository"]["origin_url"] == "https://example.com/org/repo.git"
    assert "token" not in str(result)
    assert "secret" not in str(result)


def test_missing_or_option_like_ref_fails_closed(tmp_path: Path) -> None:
    repo, validated = repository(tmp_path)
    with pytest.raises(ValueError, match="must not begin"):
        evaluate(repo, validated, "--help")
    with pytest.raises(ValueError, match="rev-parse"):
        evaluate(repo, validated, "missing-ref")
