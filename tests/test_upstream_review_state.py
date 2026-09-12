#!/usr/bin/env python3
"""Exercise cross-lane GitHub review-state classification."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/upstream_review_state.py"


def base() -> dict:
    return {
        "schema_version": "upstream-review-state-v1",
        "pull_request": {
            "url": "https://github.com/sgl-project/sglang/pull/38882",
            "repository": "sgl-project/sglang",
            "number": 38882,
            "state": "OPEN",
            "draft": True,
            "internal_candidate_status": "CURRENT_MAIN_REPLAY_ELIGIBLE",
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
        "ci": {"state": "FAIL", "classification": "DRAFT_GATE_CASCADE"},
        "reviewers": {
            "state": "QUEUED_UNTIL_READY",
            "handles": ["merrymercy", "Ying1123"],
            "early_review_handles": [],
        },
    }


def run(record: dict, expected_code: int = 0) -> dict:
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "input.json"
        path.write_text(json.dumps(record), encoding="utf-8")
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), str(path)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    assert completed.returncode == expected_code, (completed.stdout, completed.stderr)
    return json.loads(completed.stdout)


def main() -> None:
    sglang = run(base())["decision"]
    assert sglang["github_review_stage"] == "DRAFT"
    assert sglang["recommended_action"] == "KEEP_DRAFT_CONTINUE_QUALIFICATION"
    assert sglang["test_failure"] is False

    early_review = base()
    early_review["reviewers"]["early_review_handles"] = [
        "danghungdo",
        "hnyls2002",
    ]
    decision = run(early_review)["decision"]
    assert decision["recommended_action"] == "CONTINUE_QUALIFICATION_WITH_EARLY_REVIEW"
    assert decision["external_action_owner"] == "EXECUTION_LANE_AND_REVIEWER"

    vllm = base()
    vllm["pull_request"].update(
        {
            "url": "https://github.com/vllm-project/vllm/pull/56261",
            "repository": "vllm-project/vllm",
            "number": 56261,
            "draft": False,
            "internal_candidate_status": "DRAFT_PENDING_QUALIFICATION",
        }
    )
    vllm["ci"] = {"state": "FAIL", "classification": "MAINTAINER_AUTHORIZATION"}
    vllm["reviewers"] = {
        "state": "REQUESTED",
        "handles": ["ApostaC"],
        "early_review_handles": [],
    }
    decision = run(vllm)["decision"]
    assert decision["github_review_stage"] == "READY"
    assert decision["recommended_action"] == "WAIT_FOR_MAINTAINER_CI_AND_REVIEW"
    assert decision["test_failure"] is False

    mooncake = copy.deepcopy(vllm)
    mooncake["pull_request"].update(
        {
            "url": "https://github.com/kvcache-ai/Mooncake/pull/4019",
            "repository": "kvcache-ai/Mooncake",
            "number": 4019,
            "internal_candidate_status": None,
        }
    )
    mooncake["ci"] = {"state": "PASS", "classification": "PASS"}
    mooncake["reviewers"] = {
        "state": "REQUESTED",
        "handles": ["ShangmingCai"],
        "early_review_handles": [],
    }
    assert run(mooncake)["decision"]["recommended_action"] == "WAIT_FOR_REVIEW"

    absent = base()
    absent["pull_request"].update(
        {"url": None, "number": None, "state": "ABSENT", "draft": False}
    )
    absent["ci"] = {"state": "NOT_RUN", "classification": "NOT_REQUESTED"}
    absent["reviewers"] = {
        "state": "NONE",
        "handles": [],
        "early_review_handles": [],
    }
    decision = run(absent)["decision"]
    assert decision["github_review_stage"] == "NOT_SUBMITTED"
    assert decision["recommended_action"] == "OPEN_DRAFT"

    ready_draft = base()
    ready_draft["ready_gates"] = {key: "PASS" for key in READY_KEYS}
    assert (
        run(ready_draft)["decision"]["recommended_action"]
        == "MARK_READY_AND_REQUEST_REVIEW"
    )

    failed = base()
    failed["draft_minimum"]["focused_correctness"] = "FAIL"
    failed["ci"] = {"state": "FAIL", "classification": "TEST_FAILURE"}
    decision = run(failed)["decision"]
    assert decision["recommended_action"] == "CLOSE_OR_REVISE_FAILED_CANDIDATE"
    assert decision["test_failure"] is True

    invalid = base()
    invalid["pull_request"]["draft"] = False
    result = run(invalid, expected_code=1)
    assert result["status"] == "FAIL"
    assert any("DRAFT_GATE_CASCADE" in error for error in result["errors"])

    invalid_early_review = base()
    invalid_early_review["pull_request"]["draft"] = False
    invalid_early_review["ci"] = {"state": "PENDING", "classification": "RUNNING"}
    invalid_early_review["reviewers"] = {
        "state": "REQUESTED",
        "handles": ["owner"],
        "early_review_handles": ["owner"],
    }
    result = run(invalid_early_review, expected_code=1)
    assert any("early_review_handles" in error for error in result["errors"])
    print("upstream review-state test: PASS")


READY_KEYS = {
    "official_correctness",
    "production_reachability",
    "materiality",
    "target_workload",
    "known_regression",
}


if __name__ == "__main__":
    main()
