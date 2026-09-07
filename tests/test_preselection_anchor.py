#!/usr/bin/env python3
"""Regression tests for Git-anchored held-out preregistration."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from community_evaluation import (  # noqa: E402
    build_preselection_anchor,
    validate_preselection_anchor,
)
from community_knowledge import atomic_json, sha256_file  # noqa: E402


def git(repository: Path, *arguments: str, timestamp: str | None = None) -> str:
    environment = os.environ.copy()
    if timestamp is not None:
        environment["GIT_AUTHOR_DATE"] = timestamp
        environment["GIT_COMMITTER_DATE"] = timestamp
    completed = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        env=environment,
        text=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode:
        raise AssertionError(completed.stderr)
    return completed.stdout.strip()


def main() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        repository = Path(temporary)
        schemas = repository / "schemas"
        schemas.mkdir()
        for name in (
            "community_heldout_preregistration.schema.json",
            "community_preselection_anchor.schema.json",
        ):
            shutil.copyfile(ROOT / "schemas" / name, schemas / name)
        policy_path = repository / "policy.json"
        profile_path = repository / "profile.json"
        atomic_json(policy_path, {"policy": "frozen"})
        atomic_json(profile_path, {"profile": "frozen"})
        preregistration_path = repository / "preregistration.json"
        atomic_json(
            preregistration_path,
            {
                "schema_version": "community-heldout-preregistration-v1",
                "preregistration_id": "test-preselection",
                "cutoff_at": "2026-01-02T00:00:00Z",
                "claim_boundary": "PROTOCOL_FROZEN_BEFORE_DISCOVERY",
                "repositories": ["example/project"],
                "policy_identity": {
                    "path": "policy.json",
                    "sha256": sha256_file(policy_path),
                },
                "execution_profile_identity": {
                    "path": "profile.json",
                    "sha256": sha256_file(profile_path),
                },
                "selection": {
                    "max_items": 4,
                    "random_seed": 7,
                    "eligibility_time_field": "earliest_public_at",
                    "required_receipt_schema": "community-sync-receipt-v2",
                },
            },
        )
        git(repository, "init")
        git(repository, "config", "user.name", "Test")
        git(repository, "config", "user.email", "test@example.com")
        git(repository, "add", ".")
        git(
            repository,
            "commit",
            "-m",
            "freeze preregistration",
            timestamp="2026-01-01T00:00:00Z",
        )
        commit = git(repository, "rev-parse", "HEAD")
        anchor = build_preselection_anchor(
            preregistration_path, commit, repository
        )
        anchor_path = repository / "anchor.json"
        atomic_json(anchor_path, anchor)
        assert validate_preselection_anchor(anchor_path, repository)["status"] == "PASS"

        original = json.loads(preregistration_path.read_text(encoding="utf-8"))
        tampered = json.loads(json.dumps(original))
        tampered["selection"]["max_items"] = 5
        atomic_json(preregistration_path, tampered)
        try:
            validate_preselection_anchor(anchor_path, repository)
        except ValueError as error:
            assert "input changed" in str(error)
        else:
            raise AssertionError("tampered preregistration passed anchor validation")
        atomic_json(preregistration_path, original)

        git(
            repository,
            "commit",
            "--allow-empty",
            "-m",
            "late commit",
            timestamp="2026-01-03T00:00:00Z",
        )
        late_commit = git(repository, "rev-parse", "HEAD")
        try:
            build_preselection_anchor(
                preregistration_path, late_commit, repository
            )
        except ValueError as error:
            assert "later than its discovery cutoff" in str(error)
        else:
            raise AssertionError("post-cutoff Git commit was accepted as preregistration")
    print("preselection anchor test: PASS")


if __name__ == "__main__":
    main()
