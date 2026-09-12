#!/usr/bin/env python3
"""Focused tests for the autonomous optimization-lane topology."""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from artifact_io import sha256_tracked_text  # noqa: E402
from community_lane_topology import LANE_IDS, validate_topology  # noqa: E402


def topology() -> dict:
    return json.loads(
        (ROOT / "knowledge/community/lane_topology.v3.json").read_text(encoding="utf-8")
    )


def write(tmp_path: Path, value: dict) -> Path:
    path = tmp_path / "topology.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_checked_in_topology_is_exactly_four_autonomous_execution_lanes() -> None:
    result = validate_topology(ROOT / "knowledge/community/lane_topology.v3.json")
    assert result["status"] == "PASS"
    assert set(result["lane_ids"]) == LANE_IDS
    assert result["control_plane_role"] == "SUPERVISOR_REPOSITORY_MAINTAINER"


def test_strategy_evaluation_cannot_replace_a_framework_lane(tmp_path: Path) -> None:
    value = topology()
    value["execution_lanes"][0]["lane_id"] = "STRATEGY_EVALUATION"
    with pytest.raises(ValueError, match="invalid community lane topology"):
        validate_topology(write(tmp_path, value))


def test_duplicate_lane_fails_closed(tmp_path: Path) -> None:
    value = topology()
    value["execution_lanes"][1] = copy.deepcopy(value["execution_lanes"][0])
    with pytest.raises(ValueError, match="duplicate execution lane"):
        validate_topology(write(tmp_path, value))


def test_superseded_governance_hash_is_content_bound(tmp_path: Path) -> None:
    value = topology()
    value["supersedes"]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="superseded governance identity changed"):
        validate_topology(write(tmp_path, value))


def test_tracked_text_identity_accepts_only_crlf_checkout_translation(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(["git", "init", "-q", str(repository)], check=True)
    subprocess.run(
        ["git", "-C", str(repository), "config", "core.autocrlf", "false"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repository), "config", "user.email", "test@example.com"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repository), "config", "user.name", "Test"], check=True
    )
    tracked = repository / "policy.json"
    committed = b'{"value": 1}\n'
    tracked.write_bytes(committed)
    subprocess.run(["git", "-C", str(repository), "add", "policy.json"], check=True)
    subprocess.run(
        ["git", "-C", str(repository), "commit", "-q", "-m", "policy"], check=True
    )

    tracked.write_bytes(committed.replace(b"\n", b"\r\n"))
    assert (
        sha256_tracked_text(repository, tracked)
        == hashlib.sha256(committed).hexdigest()
    )

    tracked.write_bytes(b'{"value": 2}\r\n')
    with pytest.raises(ValueError, match="worktree content changed"):
        sha256_tracked_text(repository, tracked)
