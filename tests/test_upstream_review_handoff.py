#!/usr/bin/env python3
"""Exercise prospective reviewer wait and escalation routing."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/upstream_review_handoff.py"


def base() -> dict:
    return {
        "schema_version": "upstream-review-handoff-v1",
        "pull_request": {
            "url": "https://github.com/vllm-project/vllm/pull/56308",
            "repository": "vllm-project/vllm",
            "number": 56308,
            "state": "OPEN",
            "draft": False,
        },
        "observation": {
            "ready_since": "2026-09-10T20:00:00Z",
            "observed_at": "2026-09-10T22:00:00Z",
            "source": "DASHBOARD_FIRST_OBSERVED_READY",
            "prospective_lower_bound_only": True,
        },
        "reviewers": {
            "state": "REQUESTED",
            "handles": ["mgoin"],
            "feedback_state": "NONE",
        },
        "policy": {"follow_up_after_hours": 24, "escalate_after_hours": 72},
    }


def base_v2() -> dict:
    record = base()
    record["schema_version"] = "upstream-review-handoff-v2"
    record["follow_up"] = {
        "state": "NONE",
        "sent_at": None,
        "target_handle": None,
        "comment_url": None,
        "receipt_sha256": None,
    }
    return record


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
    normal = run(base())["decision"]
    assert normal["state"] == "NORMAL_REVIEW_WAIT"
    assert normal["external_action_owner"] == "REVIEWER"
    assert normal["automatic_message_authorized"] is False

    follow_up = base()
    follow_up["observation"]["observed_at"] = "2026-09-11T21:00:00Z"
    decision = run(follow_up)["decision"]
    assert decision["state"] == "TARGETED_FOLLOW_UP_DUE"
    assert decision["recommended_action"] == "ONE_TARGETED_REVIEWER_FOLLOW_UP"

    sent = base_v2()
    sent["observation"]["observed_at"] = "2026-09-11T21:00:00Z"
    sent["follow_up"] = {
        "state": "SENT",
        "sent_at": "2026-09-11T20:30:00Z",
        "target_handle": "mgoin",
        "comment_url": (
            "https://github.com/vllm-project/vllm/pull/56308#issuecomment-5649092664"
        ),
        "receipt_sha256": "a" * 64,
    }
    decision = run(sent)["decision"]
    assert decision["state"] == "TARGETED_FOLLOW_UP_SENT_WAIT_FOR_RESPONSE"
    assert decision["recommended_action"] == "WAIT"
    assert decision["external_action_owner"] == "REVIEWER"
    assert decision["follow_up_recorded"] is True

    sent_escalation = copy.deepcopy(sent)
    sent_escalation["observation"]["observed_at"] = "2026-09-13T21:00:00Z"
    decision = run(sent_escalation)["decision"]
    assert decision["state"] == "REVIEW_CHANNEL_ESCALATION_DUE"

    wrong_reviewer = copy.deepcopy(sent)
    wrong_reviewer["follow_up"]["target_handle"] = "not-requested"
    result = run(wrong_reviewer, expected_code=1)
    assert any("requested reviewer" in error for error in result["errors"])

    wrong_comment = copy.deepcopy(sent)
    wrong_comment["follow_up"]["comment_url"] = (
        "https://github.com/vllm-project/vllm/pull/1#issuecomment-5649092664"
    )
    result = run(wrong_comment, expected_code=1)
    assert any("comment on the pull request" in error for error in result["errors"])

    future_follow_up = copy.deepcopy(sent)
    future_follow_up["follow_up"]["sent_at"] = "2026-09-11T22:00:00Z"
    result = run(future_follow_up, expected_code=1)
    assert any("exceeds observed_at" in error for error in result["errors"])

    escalation = base()
    escalation["observation"]["observed_at"] = "2026-09-13T21:00:00Z"
    assert run(escalation)["decision"]["state"] == "REVIEW_CHANNEL_ESCALATION_DUE"

    missing = base()
    missing["reviewers"] = {
        "state": "NONE",
        "handles": [],
        "feedback_state": "NONE",
    }
    assert run(missing)["decision"]["recommended_action"] == "REQUEST_TOPIC_REVIEWERS"

    feedback = base()
    feedback["reviewers"].update(
        {"state": "CHANGES_REQUESTED", "feedback_state": "AUTHOR_ACTION_REQUIRED"}
    )
    assert run(feedback)["decision"]["recommended_action"] == "RESPOND_TO_REVIEW"

    approved = base()
    approved["reviewers"]["state"] = "APPROVED"
    assert run(approved)["decision"]["recommended_action"] == "WAIT_FOR_CI_OR_MERGE"

    draft = base()
    draft["pull_request"]["draft"] = True
    draft["observation"]["ready_since"] = None
    draft["reviewers"]["state"] = "QUEUED_UNTIL_READY"
    assert run(draft)["decision"]["recommended_action"] == "CONTINUE_QUALIFICATION"

    reversed_clock = base()
    reversed_clock["observation"]["observed_at"] = "2026-09-10T19:00:00Z"
    result = run(reversed_clock, expected_code=1)
    assert any("precedes ready_since" in error for error in result["errors"])

    naive_clock = copy.deepcopy(base())
    naive_clock["observation"]["observed_at"] = "2026-09-10T22:00:00"
    result = run(naive_clock, expected_code=1)
    assert any("timezone is required" in error for error in result["errors"])
    print("upstream review-handoff test: PASS")


if __name__ == "__main__":
    main()
