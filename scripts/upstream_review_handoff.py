#!/usr/bin/env python3
"""Route prospective reviewer waits without repeated or premature pings."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path


ROOT_KEYS = {"schema_version", "pull_request", "observation", "reviewers", "policy"}
PR_KEYS = {"url", "repository", "number", "state", "draft"}
OBSERVATION_KEYS = {
    "ready_since",
    "observed_at",
    "source",
    "prospective_lower_bound_only",
}
REVIEWER_KEYS = {"state", "handles", "feedback_state"}
POLICY_KEYS = {"follow_up_after_hours", "escalate_after_hours"}
PR_STATES = {"OPEN", "CLOSED", "MERGED"}
REVIEWER_STATES = {
    "NONE",
    "QUEUED_UNTIL_READY",
    "REQUESTED",
    "APPROVED",
    "CHANGES_REQUESTED",
}


def exact_keys(value: object, expected: set[str], path: str, errors: list[str]) -> dict:
    if not isinstance(value, dict):
        errors.append(f"{path}: must be an object")
        return {}
    missing = sorted(expected - set(value))
    extra = sorted(set(value) - expected)
    if missing:
        errors.append(f"{path}: missing keys {missing}")
    if extra:
        errors.append(f"{path}: unexpected keys {extra}")
    return value


def parse_timestamp(value: object, path: str, errors: list[str]) -> datetime | None:
    if not isinstance(value, str):
        errors.append(f"{path}: must be an RFC3339 string")
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        errors.append(f"{path}: invalid RFC3339 timestamp")
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        errors.append(f"{path}: timezone is required")
        return None
    return parsed


def validate(record: object) -> list[str]:
    errors: list[str] = []
    root = exact_keys(record, ROOT_KEYS, "root", errors)
    if root.get("schema_version") != "upstream-review-handoff-v1":
        errors.append("schema_version must be upstream-review-handoff-v1")

    pull = exact_keys(root.get("pull_request"), PR_KEYS, "pull_request", errors)
    state = pull.get("state")
    draft = pull.get("draft")
    if state not in PR_STATES:
        errors.append("pull_request.state: invalid state")
    if not isinstance(draft, bool):
        errors.append("pull_request.draft: must be boolean")
    if state in {"CLOSED", "MERGED"} and draft:
        errors.append("pull_request: closed or merged PR cannot be draft")
    number = pull.get("number")
    repository = pull.get("repository")
    url = pull.get("url")
    if not isinstance(number, int) or isinstance(number, bool) or number < 1:
        errors.append("pull_request.number: must be a positive integer")
    if not isinstance(repository, str) or repository.count("/") != 1:
        errors.append("pull_request.repository: must be owner/repository")
    if not isinstance(url, str) or not url.startswith("https://github.com/"):
        errors.append("pull_request.url: must be a GitHub pull-request URL")
    elif isinstance(repository, str) and isinstance(number, int):
        expected_url = f"https://github.com/{repository}/pull/{number}"
        if url != expected_url:
            errors.append("pull_request.url: does not match repository and number")

    observation = exact_keys(
        root.get("observation"), OBSERVATION_KEYS, "observation", errors
    )
    observed_at = parse_timestamp(
        observation.get("observed_at"), "observation.observed_at", errors
    )
    ready_since_raw = observation.get("ready_since")
    ready_since = None
    if ready_since_raw is not None:
        ready_since = parse_timestamp(
            ready_since_raw, "observation.ready_since", errors
        )
    if observation.get("source") != "DASHBOARD_FIRST_OBSERVED_READY":
        errors.append("observation.source: invalid source")
    if observation.get("prospective_lower_bound_only") is not True:
        errors.append("observation.prospective_lower_bound_only: must be true")
    is_ready = state == "OPEN" and draft is False
    if is_ready and ready_since is None:
        errors.append("observation.ready_since: required for an open Ready PR")
    if not is_ready and ready_since is not None:
        errors.append(
            "observation.ready_since: must be null unless the PR is open Ready"
        )
    if (
        ready_since is not None
        and observed_at is not None
        and observed_at < ready_since
    ):
        errors.append("observation: observed_at precedes ready_since")

    reviewers = exact_keys(root.get("reviewers"), REVIEWER_KEYS, "reviewers", errors)
    reviewer_state = reviewers.get("state")
    handles = reviewers.get("handles")
    if reviewer_state not in REVIEWER_STATES:
        errors.append("reviewers.state: invalid state")
    if not isinstance(handles, list) or any(
        not isinstance(handle, str) or not handle for handle in handles
    ):
        errors.append("reviewers.handles: must be non-empty strings")
    elif len(handles) != len(set(handles)):
        errors.append("reviewers.handles: duplicate handles")
    if reviewer_state == "NONE" and handles:
        errors.append("reviewers: NONE requires no handles")
    if reviewer_state in {"REQUESTED", "APPROVED", "CHANGES_REQUESTED"} and not handles:
        errors.append(f"reviewers: {reviewer_state} requires at least one handle")
    if reviewers.get("feedback_state") not in {"NONE", "AUTHOR_ACTION_REQUIRED"}:
        errors.append("reviewers.feedback_state: invalid state")
    if (
        reviewer_state == "CHANGES_REQUESTED"
        and reviewers.get("feedback_state") != "AUTHOR_ACTION_REQUIRED"
    ):
        errors.append("reviewers: CHANGES_REQUESTED requires AUTHOR_ACTION_REQUIRED")

    policy = exact_keys(root.get("policy"), POLICY_KEYS, "policy", errors)
    follow_up = policy.get("follow_up_after_hours")
    escalate = policy.get("escalate_after_hours")
    for name, value in (
        ("follow_up_after_hours", follow_up),
        ("escalate_after_hours", escalate),
    ):
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
            errors.append(f"policy.{name}: must be a positive number")
    if (
        isinstance(follow_up, (int, float))
        and not isinstance(follow_up, bool)
        and isinstance(escalate, (int, float))
        and not isinstance(escalate, bool)
        and escalate <= follow_up
    ):
        errors.append("policy: escalate_after_hours must exceed follow_up_after_hours")
    return errors


def classify(record: dict) -> dict:
    pull = record["pull_request"]
    observation = record["observation"]
    reviewers = record["reviewers"]
    policy = record["policy"]
    ready_since = observation["ready_since"]
    age_hours = None
    if ready_since is not None:
        age_hours = (
            datetime.fromisoformat(observation["observed_at"].replace("Z", "+00:00"))
            - datetime.fromisoformat(ready_since.replace("Z", "+00:00"))
        ).total_seconds() / 3600

    if pull["state"] in {"CLOSED", "MERGED"}:
        state, action, owner = "TERMINAL", "NO_ACTION", "NONE"
    elif pull["draft"]:
        state, action, owner = "NOT_READY", "CONTINUE_QUALIFICATION", "EXECUTION_LANE"
    elif reviewers["feedback_state"] == "AUTHOR_ACTION_REQUIRED":
        state, action, owner = "AUTHOR_FEEDBACK_REQUIRED", "RESPOND_TO_REVIEW", "AUTHOR"
    elif reviewers["state"] == "APPROVED":
        state, action, owner = "APPROVED", "WAIT_FOR_CI_OR_MERGE", "MAINTAINER"
    elif reviewers["state"] == "NONE":
        state, action, owner = "REVIEWERS_MISSING", "REQUEST_TOPIC_REVIEWERS", "AUTHOR"
    elif age_hours is not None and age_hours >= policy["escalate_after_hours"]:
        state, action, owner = (
            "REVIEW_CHANNEL_ESCALATION_DUE",
            "ONE_TOPIC_SPECIFIC_CHANNEL_ESCALATION",
            "AUTHOR",
        )
    elif age_hours is not None and age_hours >= policy["follow_up_after_hours"]:
        state, action, owner = (
            "TARGETED_FOLLOW_UP_DUE",
            "ONE_TARGETED_REVIEWER_FOLLOW_UP",
            "AUTHOR",
        )
    else:
        state, action, owner = "NORMAL_REVIEW_WAIT", "WAIT", "REVIEWER"

    return {
        "schema_version": "upstream-review-handoff-decision-v1",
        "input_sha256": hashlib.sha256(
            (
                json.dumps(
                    record, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                )
                + "\n"
            ).encode()
        ).hexdigest(),
        "state": state,
        "recommended_action": action,
        "external_action_owner": owner,
        "observed_ready_age_hours": round(age_hours, 6)
        if age_hours is not None
        else None,
        "prospective_lower_bound_only": True,
        "automatic_message_authorized": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        record = json.loads(args.input.read_text(encoding="utf-8"))
    except Exception as error:
        print(json.dumps({"status": "FAIL", "errors": [str(error)]}, indent=2))
        return 1
    errors = validate(record)
    if errors:
        print(json.dumps({"status": "FAIL", "errors": errors}, indent=2))
        return 1
    result = {"status": "PASS", "errors": [], "decision": classify(record)}
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
