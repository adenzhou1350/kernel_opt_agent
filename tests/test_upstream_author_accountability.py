#!/usr/bin/env python3
"""Focused tests for explicit human author accountability issuance."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "kernel_opt.py"


def command(output: Path) -> list[str]:
    return [
        sys.executable,
        str(SCRIPT),
        "upstream-author-accountability",
        "--candidate-id",
        "candidate",
        "--repository",
        "example/project",
        "--branch",
        "perf/candidate",
        "--commit",
        "a" * 40,
        "--submitter-identity",
        "human@example.com",
        "--commit-attribution",
        "PASS",
        "--attested-at",
        "2026-09-12T04:00:00Z",
        "--output",
        str(output),
        "--attest-changed-lines-reviewed",
        "--attest-relevant-tests-rerun",
        "--attest-can-defend-change",
        "--attest-ai-assistance-disclosed",
    ]


def test_explicit_attestation_is_written_once(tmp_path: Path) -> None:
    output = tmp_path / "accountability.json"
    completed = subprocess.run(command(output), capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    record = json.loads(output.read_text(encoding="utf-8"))
    assert record["candidate_commit"] == "a" * 40
    assert record["checks"] == {
        "changed_lines_reviewed": True,
        "relevant_tests_rerun": True,
        "can_defend_change": True,
        "ai_assistance_disclosed": True,
        "commit_attribution": "PASS",
    }
    duplicate = subprocess.run(command(output), capture_output=True, text=True)
    assert duplicate.returncode != 0
    assert "refusing to replace" in duplicate.stderr


def test_every_human_attestation_flag_is_required(tmp_path: Path) -> None:
    output = tmp_path / "missing.json"
    missing = command(output)
    missing.remove("--attest-relevant-tests-rerun")
    completed = subprocess.run(missing, capture_output=True, text=True)
    assert completed.returncode != 0
    assert not output.exists()


def test_invalid_commit_fails_before_write(tmp_path: Path) -> None:
    output = tmp_path / "invalid.json"
    invalid = command(output)
    invalid[invalid.index("--commit") + 1] = "not-a-commit"
    completed = subprocess.run(invalid, capture_output=True, text=True)
    assert completed.returncode != 0
    assert "candidate_commit" in completed.stderr
    assert not output.exists()
