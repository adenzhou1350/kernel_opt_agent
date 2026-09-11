#!/usr/bin/env python3
"""Exercise deterministic discovery of explicit upstream-readiness signals."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/upstream_readiness_discovery.py"


def write_json(path: Path, value: dict) -> str:
    raw = (json.dumps(value, sort_keys=True) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def readiness(
    candidate_id: str,
    recorded_at: str,
    *,
    branch: str = "perf/direct",
    commit: str = "abc123",
    status: str = "READY_TO_CREATE_NON_DRAFT_PR_PENDING_ACTION_CONFIRMATION",
) -> dict:
    return {
        "candidate": candidate_id,
        "recorded_at": recorded_at,
        "status": status,
        "source": {"branch": branch, "commit": commit},
        "pull_request": {"base": "example/project:main"},
    }


def run(*arguments: str, expected_code: int = 0) -> dict:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), *arguments],
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == expected_code, (completed.stdout, completed.stderr)
    return json.loads(completed.stdout)


def main() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        older = root / "candidate" / "upstream-delivery-readiness-v1.json"
        newer = root / "upstream_delivery_readiness_v2.json"
        ignored = root / "ignored" / "upstream-delivery-readiness-v1.json"
        too_deep = root / "one" / "two" / "upstream-delivery-readiness-v1.json"
        write_json(older, readiness("candidate-a", "2026-09-11T08:00:00Z"))
        newer_sha = write_json(
            newer,
            readiness("candidate-a", "2026-09-11T09:00:00Z", commit="def456"),
        )
        write_json(
            ignored,
            readiness("not-ready", "2026-09-11T10:00:00Z", status="DRAFT"),
        )
        write_json(too_deep, readiness("too-deep", "2026-09-11T10:00:00Z"))

        manifest_path = root / "inbox.json"
        write_json(
            manifest_path,
            {
                "schema_version": "upstream-delivery-inbox-v1",
                "observed_at": "2026-09-11T09:30:00Z",
                "candidates": [
                    {
                        "candidate_id": "candidate-a",
                        "lane_id": "sglang",
                        "review_state": {
                            "path": "review.json",
                            "sha256": "0" * 64,
                        },
                    }
                ],
            },
        )
        result = run(str(root), "--manifest", str(manifest_path))["discovery"]
        assert result["scanned_file_count"] == 3
        assert result["ready_signal_count"] == 1
        assert result["registered_count"] == 1
        assert result["unregistered_count"] == 0
        assert result["items"][0]["commit"] == "def456"
        assert result["items"][0]["artifact"]["sha256"] == newer_sha
        assert result["items"][0]["registered_in_delivery_inbox"] is True
        assert result["items"][0]["timestamp_quality"] == "RFC3339_TIMEZONE_BOUND"
        assert result["source_aliases"] == []
        assert "NOT_REVIEW_STATE_VALIDATION" in result["claim_boundary"]

        write_json(
            root / "alias" / "upstream-delivery-readiness-v1.json",
            readiness(
                "candidate-alias",
                "2026-09-11T11:00:00Z",
                commit="def456",
            ),
        )
        alias_result = run(str(root))["discovery"]
        assert alias_result["ready_signal_count"] == 2
        assert alias_result["source_alias_count"] == 1
        assert alias_result["source_aliases"][0]["candidate_ids"] == [
            "candidate-a",
            "candidate-alias",
        ]

        invalid = root / "bad" / "upstream-delivery-readiness-v1.json"
        write_json(invalid, readiness("bad-time", "2026-09-11T12:00:00"))
        invalid_result = run(str(root))["discovery"]
        assert invalid_result["ready_signal_count"] == 3
        bad_time = next(
            item
            for item in invalid_result["items"]
            if item["candidate_id"] == "bad-time"
        )
        assert bad_time["timestamp_quality"] == "FILE_MTIME_FALLBACK"
        assert bad_time["recorded_at_normalized"] is None
        assert any(
            "timezone is required" in error and "retained as discovery-only" in error
            for error in invalid_result["errors"]
        )

        invalid_manifest = json.loads(manifest_path.read_text())
        invalid_manifest["unexpected"] = True
        write_json(manifest_path, invalid_manifest)
        failure = run(str(root), "--manifest", str(manifest_path), expected_code=1)
        assert any(
            "invalid delivery inbox manifest" in error for error in failure["errors"]
        )

    print("upstream readiness discovery test: PASS")


if __name__ == "__main__":
    main()
