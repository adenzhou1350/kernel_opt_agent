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


def review_handoff(ready: dict, observed_at: str, ready_since: str) -> dict:
    pull = ready["pull_request"]
    return {
        "schema_version": "upstream-review-handoff-v1",
        "pull_request": {
            key: pull[key] for key in ("url", "repository", "number", "state", "draft")
        },
        "observation": {
            "ready_since": ready_since,
            "observed_at": observed_at,
            "source": "DASHBOARD_FIRST_OBSERVED_READY",
            "prospective_lower_bound_only": True,
        },
        "reviewers": {
            "state": ready["reviewers"]["state"],
            "handles": ready["reviewers"]["handles"],
            "feedback_state": "NONE",
        },
        "policy": {"follow_up_after_hours": 24, "escalate_after_hours": 72},
    }


def draft_freshness(
    *,
    candidate_id: str,
    repository: str,
    branch: str,
    commit: str,
) -> dict:
    return {
        "schema_version": "upstream-delivery-freshness-v1",
        "observed_at": "2026-09-11T07:30:00Z",
        "expires_at": "2026-09-11T12:30:00Z",
        "candidate_id": candidate_id,
        "repository": repository,
        "branch": branch,
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

        handoff_path = root / "handoff.json"
        handoff_sha = write_json(
            handoff_path,
            review_handoff(
                ready,
                observed_at="2026-09-11T08:00:00Z",
                ready_since="2026-09-10T07:00:00Z",
            ),
        )
        v2 = copy.deepcopy(base)
        v2["schema_version"] = "upstream-delivery-inbox-v2"
        for candidate in v2["candidates"]:
            candidate["review_handoff"] = None
        v2["candidates"][1]["review_handoff"] = {
            "path": handoff_path.name,
            "sha256": handoff_sha,
        }
        write_json(manifest, v2)
        v2_inbox = run(manifest)["inbox"]
        assert v2_inbox["schema_version"] == "upstream-delivery-inbox-result-v2"
        assert v2_inbox["actionable_count"] == 2
        follow_up_item = next(
            item
            for item in v2_inbox["items"]
            if item["candidate_id"] == "vllm-packed-lm-head"
        )
        assert follow_up_item["review_state_action"] == "WAIT_FOR_REVIEW"
        assert follow_up_item["recommended_action"] == (
            "ONE_TARGETED_REVIEWER_FOLLOW_UP"
        )
        assert follow_up_item["external_action_owner"] == "AUTHOR"
        assert follow_up_item["review_handoff"]["observed_ready_age_hours"] == 25
        assert follow_up_item["review_handoff"]["automatic_message_authorized"] is False

        body_path = root / "draft-body.md"
        body_raw = b"## Summary\n\nValidated Draft body.\n"
        body_path.write_bytes(body_raw)
        body_sha = hashlib.sha256(body_raw).hexdigest()
        freshness_path = root / "freshness.json"
        candidate_commit = "a" * 40
        freshness_sha = write_json(
            freshness_path,
            {"candidate": {"commit": candidate_commit}, "status": "PASS"},
        )
        draft_materials = {
            "title": "Reduce redundant Mooncake grouping",
            "submission_type": "DRAFT_PULL_REQUEST",
            "repository": "vllm-project/vllm",
            "branch": "perf/mooncake-lazy-group-cache",
            "commit": candidate_commit,
            "action_url": (
                "https://github.com/vllm-project/vllm/compare/main..."
                "aden-q/vllm:perf/mooncake-lazy-group-cache?expand=1"
            ),
            "body": {"path": body_path.name, "sha256": body_sha},
            "freshness_evidence": {
                "path": freshness_path.name,
                "sha256": freshness_sha,
            },
        }
        v3 = copy.deepcopy(base)
        v3["schema_version"] = "upstream-delivery-inbox-v3"
        for candidate in v3["candidates"]:
            candidate["review_handoff"] = None
            candidate["draft_materials"] = None
        v3["candidates"][0]["draft_materials"] = draft_materials
        v3["candidates"][1]["review_handoff"] = {
            "path": handoff_path.name,
            "sha256": handoff_sha,
        }
        write_json(manifest, v3)
        v3_inbox = run(manifest)["inbox"]
        assert v3_inbox["schema_version"] == "upstream-delivery-inbox-result-v3"
        draft_item = next(
            item
            for item in v3_inbox["items"]
            if item["candidate_id"] == "mooncake-lazy-group-cache"
        )
        assert draft_item["recommended_action"] == "OPEN_DRAFT"
        assert draft_item["draft_materials"]["commit"] == candidate_commit
        assert draft_item["draft_materials"]["body"]["bytes"] == len(body_raw)

        standard_freshness = draft_freshness(
            candidate_id="mooncake-lazy-group-cache",
            repository="vllm-project/vllm",
            branch="perf/mooncake-lazy-group-cache",
            commit=candidate_commit,
        )
        freshness_sha = write_json(freshness_path, standard_freshness)
        v4 = copy.deepcopy(v3)
        v4["schema_version"] = "upstream-delivery-inbox-v4"
        v4["candidates"][0]["draft_materials"]["freshness_evidence"]["sha256"] = (
            freshness_sha
        )
        write_json(manifest, v4)
        v4_inbox = run(manifest)["inbox"]
        assert v4_inbox["schema_version"] == "upstream-delivery-inbox-result-v4"
        v4_item = next(
            item
            for item in v4_inbox["items"]
            if item["candidate_id"] == "mooncake-lazy-group-cache"
        )
        assert v4_item["recommended_action"] == "OPEN_DRAFT"
        assert v4_item["draft_materials"]["freshness_validation"] == {
            "status": "PASS",
            "errors": [],
        }

        stale_v4 = copy.deepcopy(v4)
        stale_freshness = copy.deepcopy(standard_freshness)
        stale_freshness["expires_at"] = "2026-09-11T07:59:59Z"
        stale_v4["candidates"][0]["draft_materials"]["freshness_evidence"]["sha256"] = (
            write_json(freshness_path, stale_freshness)
        )
        write_json(manifest, stale_v4)
        stale_inbox = run(manifest)["inbox"]
        stale_item = next(
            item
            for item in stale_inbox["items"]
            if item["candidate_id"] == "mooncake-lazy-group-cache"
        )
        assert stale_item["recommended_action"] == "REFRESH_DRAFT_FRESHNESS"
        assert stale_item["external_action_owner"] == "EXECUTION_LANE"
        assert stale_item["draft_materials"]["freshness_validation"]["status"] == (
            "REFRESH_REQUIRED"
        )
        assert any(
            "evidence is stale" in error
            for error in stale_item["draft_materials"]["freshness_validation"]["errors"]
        )
        assert stale_inbox["actionable_count"] == v4_inbox["actionable_count"] - 1

        mismatched_v4 = copy.deepcopy(v4)
        mismatched_freshness = copy.deepcopy(standard_freshness)
        mismatched_freshness["candidate_commit"] = "c" * 40
        mismatched_v4["candidates"][0]["draft_materials"]["freshness_evidence"][
            "sha256"
        ] = write_json(freshness_path, mismatched_freshness)
        write_json(manifest, mismatched_v4)
        mismatched_inbox = run(manifest)["inbox"]
        mismatched_item = next(
            item
            for item in mismatched_inbox["items"]
            if item["candidate_id"] == "mooncake-lazy-group-cache"
        )
        assert mismatched_item["recommended_action"] == "REFRESH_DRAFT_FRESHNESS"
        assert any(
            "candidate_commit" in error
            for error in mismatched_item["draft_materials"]["freshness_validation"][
                "errors"
            ]
        )

        hidden_freshness_v4 = copy.deepcopy(v4)
        hidden_freshness = copy.deepcopy(standard_freshness)
        hidden_freshness["hidden_oracle"] = True
        hidden_freshness_v4["candidates"][0]["draft_materials"]["freshness_evidence"][
            "sha256"
        ] = write_json(freshness_path, hidden_freshness)
        write_json(manifest, hidden_freshness_v4)
        hidden_freshness_inbox = run(manifest)["inbox"]
        hidden_freshness_item = next(
            item
            for item in hidden_freshness_inbox["items"]
            if item["candidate_id"] == "mooncake-lazy-group-cache"
        )
        assert hidden_freshness_item["recommended_action"] == (
            "REFRESH_DRAFT_FRESHNESS"
        )
        assert any(
            "unexpected keys" in error
            for error in hidden_freshness_item["draft_materials"][
                "freshness_validation"
            ]["errors"]
        )

        # Restore the v3 fixture used by the compatibility mutation tests below.
        freshness_sha = write_json(
            freshness_path,
            {"candidate": {"commit": candidate_commit}, "status": "PASS"},
        )
        v3["candidates"][0]["draft_materials"]["freshness_evidence"]["sha256"] = (
            freshness_sha
        )

        missing_materials = copy.deepcopy(v3)
        missing_materials["candidates"][0]["draft_materials"] = None
        write_json(manifest, missing_materials)
        missing_materials_inbox = run(manifest)["inbox"]
        missing_item = next(
            item
            for item in missing_materials_inbox["items"]
            if item["candidate_id"] == "mooncake-lazy-group-cache"
        )
        assert missing_item["review_state_action"] == "OPEN_DRAFT"
        assert missing_item["recommended_action"] == "COMPLETE_DRAFT_MATERIALS"
        assert missing_item["external_action_owner"] == "EXECUTION_LANE"
        assert missing_item["draft_materials"] is None

        body_drift = copy.deepcopy(v3)
        body_drift["candidates"][0]["draft_materials"]["body"]["sha256"] = "0" * 64
        write_json(manifest, body_drift)
        failure = run(manifest, expected_code=1)
        assert any(
            "draft_materials.body.sha256" in error for error in failure["errors"]
        )

        freshness_drift = copy.deepcopy(v3)
        freshness_drift["candidates"][0]["draft_materials"]["freshness_evidence"][
            "sha256"
        ] = "0" * 64
        write_json(manifest, freshness_drift)
        failure = run(manifest, expected_code=1)
        assert any(
            "draft_materials.freshness_evidence.sha256" in error
            for error in failure["errors"]
        )

        wrong_repository = copy.deepcopy(v3)
        wrong_repository["candidates"][0]["draft_materials"]["repository"] = (
            "sgl-project/sglang"
        )
        wrong_repository["candidates"][0]["draft_materials"]["action_url"] = (
            "https://github.com/sgl-project/sglang/compare/main...branch?expand=1"
        )
        write_json(manifest, wrong_repository)
        failure = run(manifest, expected_code=1)
        assert any(
            "does not match review_state" in error for error in failure["errors"]
        )

        wrong_action_url = copy.deepcopy(v3)
        wrong_action_url["candidates"][0]["draft_materials"]["action_url"] = (
            "https://github.com/other/project/compare/main...branch?expand=1"
        )
        write_json(manifest, wrong_action_url)
        failure = run(manifest, expected_code=1)
        assert any("repository compare URL" in error for error in failure["errors"])

        missing_commit = copy.deepcopy(v3)
        missing_commit["candidates"][0]["draft_materials"]["commit"] = "b" * 40
        write_json(manifest, missing_commit)
        failure = run(manifest, expected_code=1)
        assert any(
            "does not bind the candidate commit" in error for error in failure["errors"]
        )

        hidden_key = copy.deepcopy(v3)
        hidden_key["candidates"][0]["draft_materials"]["hidden_oracle"] = True
        write_json(manifest, hidden_key)
        failure = run(manifest, expected_code=1)
        assert any("unexpected keys" in error for error in failure["errors"])

        missing_handoff = copy.deepcopy(v2)
        missing_handoff["candidates"][1]["review_handoff"] = None
        write_json(manifest, missing_handoff)
        failure = run(manifest, expected_code=1)
        assert any(
            "required for an open Ready PR" in error for error in failure["errors"]
        )

        mismatched_handoff = json.loads(handoff_path.read_text(encoding="utf-8"))
        mismatched_handoff["pull_request"]["number"] = 999
        mismatched_handoff["pull_request"]["url"] = (
            "https://github.com/vllm-project/vllm/pull/999"
        )
        v2["candidates"][1]["review_handoff"]["sha256"] = write_json(
            handoff_path, mismatched_handoff
        )
        write_json(manifest, v2)
        failure = run(manifest, expected_code=1)
        assert any(
            "does not match review_state" in error for error in failure["errors"]
        )

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
