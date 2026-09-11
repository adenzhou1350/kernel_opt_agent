#!/usr/bin/env python3
"""Exercise the evidence-bound upstream delivery inbox."""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/upstream_delivery_inbox.py"


def review_state(
    repository: str, state: str = "ABSENT", number: int | None = None
) -> dict:
    submitted = state != "ABSENT"
    return {
        "schema_version": "upstream-review-state-v1",
        "pull_request": {
            "url": f"https://github.com/{repository}/pull/{number}"
            if submitted
            else None,
            "repository": repository,
            "number": number if submitted else None,
            "state": state,
            "draft": submitted and state == "OPEN",
            "internal_candidate_status": "FOCUSED_PASS",
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
            "production_reachability": "PENDING",
            "materiality": "PENDING",
            "target_workload": "PENDING",
            "known_regression": "PASS",
        },
        "ci": {"state": "NOT_RUN", "classification": "NOT_REQUESTED"},
        "reviewers": {"state": "NONE", "handles": [], "early_review_handles": []},
    }


def write_json(path: Path, value: dict) -> str:
    raw = (json.dumps(value, sort_keys=True) + "\n").encode()
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def run(manifest: Path, expected_code: int = 0) -> dict:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), str(manifest)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert completed.returncode == expected_code, (completed.stdout, completed.stderr)
    return json.loads(completed.stdout)


def main() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        mooncake = root / "mooncake.json"
        vllm = root / "vllm.json"
        mooncake_sha = write_json(mooncake, review_state("vllm-project/vllm"))
        ready = review_state("vllm-project/vllm", "OPEN", 56261)
        ready["pull_request"]["draft"] = False
        ready["ready_gates"] = {key: "PASS" for key in ready["ready_gates"]}
        ready["ci"] = {"state": "PASS", "classification": "PASS"}
        ready["reviewers"] = {
            "state": "REQUESTED",
            "handles": ["reviewer"],
            "early_review_handles": [],
        }
        vllm_sha = write_json(vllm, ready)
        manifest = root / "inbox.json"
        base = {
            "schema_version": "upstream-delivery-inbox-v1",
            "observed_at": "2026-09-11T08:00:00Z",
            "candidates": [
                {
                    "candidate_id": "mooncake-lazy-group-cache",
                    "lane_id": "mooncake",
                    "review_state": {"path": mooncake.name, "sha256": mooncake_sha},
                },
                {
                    "candidate_id": "vllm-packed-lm-head",
                    "lane_id": "vllm",
                    "review_state": {"path": vllm.name, "sha256": vllm_sha},
                },
            ],
        }
        write_json(manifest, base)
        inbox = run(manifest)["inbox"]
        assert inbox["candidate_count"] == 2
        assert inbox["actionable_count"] == 1
        assert [item["recommended_action"] for item in inbox["items"]] == [
            "OPEN_DRAFT",
            "WAIT_FOR_REVIEW",
        ]
        assert inbox["items"][0]["draft_minimum_progress"] == {
            "failed": [],
            "passed": [
                "claim_boundary",
                "clean_minimal_commit",
                "focused_correctness",
                "lint_format",
                "reproduction",
            ],
            "passed_count": 5,
            "pending": [],
            "total_count": 5,
        }
        assert inbox["items"][0]["ready_gate_progress"]["pending"] == [
            "materiality",
            "official_correctness",
            "production_reachability",
            "target_workload",
        ]
        assert inbox["items"][0]["internal_candidate_status"] == "FOCUSED_PASS"

        less_ready_path = root / "less-ready.json"
        less_ready = review_state("sgl-project/sglang")
        less_ready["draft_minimum"]["clean_minimal_commit"] = "PENDING"
        less_ready_sha = write_json(less_ready_path, less_ready)
        more_ready_path = root / "more-ready.json"
        more_ready = copy.deepcopy(less_ready)
        more_ready["ready_gates"]["production_reachability"] = "PASS"
        more_ready_sha = write_json(more_ready_path, more_ready)
        progress_manifest = copy.deepcopy(base)
        progress_manifest["candidates"] = [
            {
                "candidate_id": "less-ready",
                "lane_id": "sglang",
                "review_state": {
                    "path": less_ready_path.name,
                    "sha256": less_ready_sha,
                },
            },
            {
                "candidate_id": "more-ready",
                "lane_id": "sglang",
                "review_state": {
                    "path": more_ready_path.name,
                    "sha256": more_ready_sha,
                },
            },
        ]
        write_json(manifest, progress_manifest)
        progress = run(manifest)["inbox"]["items"]
        assert [item["candidate_id"] for item in progress] == [
            "more-ready",
            "less-ready",
        ]
        assert progress[0]["draft_minimum_progress"]["pending"] == [
            "clean_minimal_commit"
        ]
        assert progress[0]["ready_gate_progress"]["passed_count"] == 2

        bad_sha = copy.deepcopy(base)
        bad_sha["candidates"][0]["review_state"]["sha256"] = "0" * 64
        write_json(manifest, bad_sha)
        failure = run(manifest, expected_code=1)
        assert any("expected" in error for error in failure["errors"])

        duplicate_id = copy.deepcopy(base)
        duplicate_id["candidates"][1]["candidate_id"] = duplicate_id["candidates"][0][
            "candidate_id"
        ]
        write_json(manifest, duplicate_id)
        failure = run(manifest, expected_code=1)
        assert any("duplicate identity" in error for error in failure["errors"])

        duplicate_pr = copy.deepcopy(base)
        duplicate_review = copy.deepcopy(ready)
        duplicate_path = root / "duplicate.json"
        duplicate_sha = write_json(duplicate_path, duplicate_review)
        duplicate_pr["candidates"].append(
            {
                "candidate_id": "duplicate-pr",
                "lane_id": "other",
                "review_state": {"path": duplicate_path.name, "sha256": duplicate_sha},
            }
        )
        write_json(manifest, duplicate_pr)
        failure = run(manifest, expected_code=1)
        assert any("already bound" in error for error in failure["errors"])

        naive = copy.deepcopy(base)
        naive["observed_at"] = "2026-09-11T08:00:00"
        write_json(manifest, naive)
        failure = run(manifest, expected_code=1)
        assert any("timezone is required" in error for error in failure["errors"])

    print("upstream delivery inbox test: PASS")


if __name__ == "__main__":
    main()
