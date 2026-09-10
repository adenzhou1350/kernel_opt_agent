#!/usr/bin/env python3
"""Classify GitHub Draft, CI, reviewer and qualification handoffs."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


DRAFT_KEYS = {
    "clean_minimal_commit",
    "focused_correctness",
    "lint_format",
    "reproduction",
    "claim_boundary",
}
READY_KEYS = {
    "official_correctness",
    "production_reachability",
    "materiality",
    "target_workload",
    "known_regression",
}
PR_KEYS = {"url", "repository", "number", "state", "draft", "internal_candidate_status"}
CI_KEYS = {"state", "classification"}
REVIEWER_KEYS = {"state", "handles"}
ROOT_KEYS = {
    "schema_version",
    "pull_request",
    "draft_minimum",
    "ready_gates",
    "ci",
    "reviewers",
}

DRAFT_VALUES = {"PASS", "FAIL", "PENDING"}
READY_VALUES = DRAFT_VALUES | {"NOT_APPLICABLE"}
PR_STATES = {"ABSENT", "OPEN", "CLOSED", "MERGED"}
CI_STATES = {"PASS", "FAIL", "PENDING", "NOT_RUN"}
CI_CLASSES = {
    "TEST_FAILURE",
    "MAINTAINER_AUTHORIZATION",
    "DRAFT_GATE_CASCADE",
    "RUNNING",
    "PASS",
    "NOT_REQUESTED",
}
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


def validate(record: object) -> list[str]:
    errors: list[str] = []
    root = exact_keys(record, ROOT_KEYS, "root", errors)
    if root.get("schema_version") != "upstream-review-state-v1":
        errors.append("schema_version must be upstream-review-state-v1")

    pull = exact_keys(root.get("pull_request"), PR_KEYS, "pull_request", errors)
    state = pull.get("state")
    draft = pull.get("draft")
    if state not in PR_STATES:
        errors.append("pull_request.state: invalid state")
    if not isinstance(draft, bool):
        errors.append("pull_request.draft: must be boolean")
    if not isinstance(pull.get("repository"), str) or not pull.get("repository"):
        errors.append("pull_request.repository: must be non-empty")
    number = pull.get("number")
    url = pull.get("url")
    if state == "ABSENT":
        if draft:
            errors.append("pull_request: ABSENT cannot be draft")
        if number is not None or url is not None:
            errors.append("pull_request: ABSENT requires null number and url")
    else:
        if not isinstance(number, int) or isinstance(number, bool) or number < 1:
            errors.append(
                "pull_request.number: submitted PR requires a positive integer"
            )
        if not isinstance(url, str) or not url.startswith("https://github.com/"):
            errors.append("pull_request.url: submitted PR requires a GitHub URL")
    if state in {"CLOSED", "MERGED"} and draft:
        errors.append("pull_request: closed or merged PR cannot be draft")

    draft_checks = exact_keys(
        root.get("draft_minimum"), DRAFT_KEYS, "draft_minimum", errors
    )
    for key, value in draft_checks.items():
        if value not in DRAFT_VALUES:
            errors.append(f"draft_minimum.{key}: invalid status")
    ready_checks = exact_keys(
        root.get("ready_gates"), READY_KEYS, "ready_gates", errors
    )
    for key, value in ready_checks.items():
        if value not in READY_VALUES:
            errors.append(f"ready_gates.{key}: invalid status")

    ci = exact_keys(root.get("ci"), CI_KEYS, "ci", errors)
    if ci.get("state") not in CI_STATES:
        errors.append("ci.state: invalid state")
    if ci.get("classification") not in CI_CLASSES:
        errors.append("ci.classification: invalid classification")
    if ci.get("classification") == "PASS" and ci.get("state") != "PASS":
        errors.append("ci: PASS classification requires PASS state")
    if ci.get("classification") == "TEST_FAILURE" and ci.get("state") != "FAIL":
        errors.append("ci: TEST_FAILURE requires FAIL state")
    if (
        ci.get("classification") == "MAINTAINER_AUTHORIZATION"
        and ci.get("state") == "PASS"
    ):
        errors.append("ci: maintainer authorization cannot have PASS state")
    if ci.get("classification") == "DRAFT_GATE_CASCADE" and not (
        state == "OPEN" and draft is True
    ):
        errors.append("ci: DRAFT_GATE_CASCADE requires an open GitHub Draft")

    reviewers = exact_keys(root.get("reviewers"), REVIEWER_KEYS, "reviewers", errors)
    reviewer_state = reviewers.get("state")
    handles = reviewers.get("handles")
    if reviewer_state not in REVIEWER_STATES:
        errors.append("reviewers.state: invalid state")
    if not isinstance(handles, list) or any(
        not isinstance(item, str) or not item for item in handles
    ):
        errors.append("reviewers.handles: must be a list of non-empty strings")
    elif len(handles) != len(set(handles)):
        errors.append("reviewers.handles: duplicate handles")
    if reviewer_state == "QUEUED_UNTIL_READY" and not (
        state == "OPEN" and draft is True
    ):
        errors.append("reviewers: QUEUED_UNTIL_READY requires an open GitHub Draft")
    if state == "ABSENT" and reviewer_state != "NONE":
        errors.append("reviewers: absent PR must have NONE state")
    return errors


def classify(record: dict) -> dict:
    pull = record["pull_request"]
    draft_checks = record["draft_minimum"]
    ready_checks = record["ready_gates"]
    ci = record["ci"]
    reviewers = record["reviewers"]

    if "FAIL" in draft_checks.values() or "FAIL" in ready_checks.values():
        quality = "FAILED"
    elif all(value in {"PASS", "NOT_APPLICABLE"} for value in ready_checks.values()):
        quality = "READY_GATES_PASS"
    elif all(value == "PASS" for value in draft_checks.values()):
        quality = "DRAFT_MINIMUM_READY"
    else:
        quality = "PENDING"

    state = pull["state"]
    github_stage = (
        "DRAFT"
        if state == "OPEN" and pull["draft"]
        else (
            "READY"
            if state == "OPEN"
            else {
                "ABSENT": "NOT_SUBMITTED",
                "CLOSED": "CLOSED",
                "MERGED": "MERGED",
            }[state]
        )
    )
    test_failure = (
        ci["classification"] == "TEST_FAILURE"
        or draft_checks["focused_correctness"] == "FAIL"
        or ready_checks["official_correctness"] == "FAIL"
    )

    if state == "MERGED":
        action, owner = "NO_ACTION_MERGED", "NONE"
    elif state == "CLOSED":
        action, owner = "NO_ACTION_CLOSED", "NONE"
    elif quality == "FAILED" or test_failure:
        action, owner = "CLOSE_OR_REVISE_FAILED_CANDIDATE", "AUTHOR"
    elif state == "ABSENT":
        if quality in {"DRAFT_MINIMUM_READY", "READY_GATES_PASS"}:
            action, owner = "OPEN_DRAFT", "AUTHOR"
        else:
            action, owner = "COMPLETE_DRAFT_MINIMUM", "EXECUTION_LANE"
    elif pull["draft"]:
        if quality == "READY_GATES_PASS":
            action, owner = "MARK_READY_AND_REQUEST_REVIEW", "AUTHOR"
        else:
            action, owner = "KEEP_DRAFT_CONTINUE_QUALIFICATION", "EXECUTION_LANE"
    elif reviewers["state"] == "CHANGES_REQUESTED":
        action, owner = "RESPOND_TO_REVIEW", "AUTHOR"
    elif ci["classification"] in {"MAINTAINER_AUTHORIZATION", "NOT_REQUESTED"} or ci[
        "state"
    ] in {"PENDING", "NOT_RUN"}:
        action, owner = "WAIT_FOR_MAINTAINER_CI_AND_REVIEW", "MAINTAINER"
    elif reviewers["state"] in {"REQUESTED", "APPROVED"}:
        action, owner = "WAIT_FOR_REVIEW", "REVIEWER"
    else:
        action, owner = "WAIT_FOR_REVIEW", "REVIEWER"

    return {
        "schema_version": "upstream-review-decision-v1",
        "input_sha256": hashlib.sha256(
            (
                json.dumps(
                    record, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                )
                + "\n"
            ).encode()
        ).hexdigest(),
        "github_review_stage": github_stage,
        "candidate_quality": quality,
        "recommended_action": action,
        "external_action_owner": owner,
        "test_failure": test_failure,
        "internal_candidate_status_is_informational": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        record = json.loads(args.input.read_text(encoding="utf-8"))
    except Exception as error:
        result = {"status": "FAIL", "errors": [str(error)]}
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 1
    errors = validate(record)
    if errors:
        result = {"status": "FAIL", "errors": errors}
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
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
