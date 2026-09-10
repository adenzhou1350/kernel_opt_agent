#!/usr/bin/env python3
"""Route an open Draft toward Ready, revision, or bounded closure."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path


ROOT_KEYS = {"schema_version", "pull_request", "observation", "qualification", "policy"}
PR_KEYS = {"url", "repository", "number", "state", "draft"}
OBSERVATION_KEYS = {
    "draft_since",
    "last_material_progress_at",
    "observed_at",
    "source",
    "prospective_lower_bound_only",
}
QUALIFICATION_KEYS = {"status", "value_status", "next_gate", "blocker_owner"}
POLICY_KEYS = {"stale_after_hours"}


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


def timestamp(value: object, path: str, errors: list[str]) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        errors.append(f"{path}: must be an RFC3339 string or null")
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
    if root.get("schema_version") != "upstream-draft-progress-v1":
        errors.append("schema_version must be upstream-draft-progress-v1")

    pull = exact_keys(root.get("pull_request"), PR_KEYS, "pull_request", errors)
    state = pull.get("state")
    draft = pull.get("draft")
    if state not in {"OPEN", "CLOSED", "MERGED"}:
        errors.append("pull_request.state: invalid state")
    if not isinstance(draft, bool):
        errors.append("pull_request.draft: must be boolean")
    if state in {"CLOSED", "MERGED"} and draft:
        errors.append("pull_request: closed or merged PR cannot be draft")
    repository = pull.get("repository")
    number = pull.get("number")
    url = pull.get("url")
    if not isinstance(repository, str) or repository.count("/") != 1:
        errors.append("pull_request.repository: must be owner/repository")
    if not isinstance(number, int) or isinstance(number, bool) or number < 1:
        errors.append("pull_request.number: must be a positive integer")
    if isinstance(repository, str) and isinstance(number, int):
        if url != f"https://github.com/{repository}/pull/{number}":
            errors.append("pull_request.url: does not match repository and number")

    observation = exact_keys(
        root.get("observation"), OBSERVATION_KEYS, "observation", errors
    )
    draft_since = timestamp(
        observation.get("draft_since"), "observation.draft_since", errors
    )
    progress_at = timestamp(
        observation.get("last_material_progress_at"),
        "observation.last_material_progress_at",
        errors,
    )
    observed_at = timestamp(
        observation.get("observed_at"), "observation.observed_at", errors
    )
    if observation.get("source") != "DASHBOARD_STAGE_HISTORY":
        errors.append("observation.source: invalid source")
    if observation.get("prospective_lower_bound_only") is not True:
        errors.append("observation.prospective_lower_bound_only: must be true")
    is_draft = state == "OPEN" and draft is True
    if is_draft and (draft_since is None or progress_at is None):
        errors.append("observation: an open Draft requires both progress timestamps")
    if not is_draft and (draft_since is not None or progress_at is not None):
        errors.append(
            "observation: progress timestamps are only valid for an open Draft"
        )
    if draft_since and progress_at and progress_at < draft_since:
        errors.append("observation: material progress precedes draft_since")
    if observed_at and draft_since and observed_at < draft_since:
        errors.append("observation: observed_at precedes draft_since")
    if observed_at and progress_at and observed_at < progress_at:
        errors.append("observation: observed_at precedes last material progress")

    qualification = exact_keys(
        root.get("qualification"), QUALIFICATION_KEYS, "qualification", errors
    )
    status = qualification.get("status")
    value_status = qualification.get("value_status")
    if status not in {"ACTIVE", "PASS", "FAILED", "ENVIRONMENT_BLOCKED"}:
        errors.append("qualification.status: invalid status")
    if value_status not in {"POSITIVE", "UNPROVEN", "DISPROVEN"}:
        errors.append("qualification.value_status: invalid status")
    if status == "PASS" and value_status != "POSITIVE":
        errors.append("qualification: PASS requires POSITIVE value")
    if not isinstance(qualification.get("next_gate"), str) or not qualification.get(
        "next_gate"
    ):
        errors.append("qualification.next_gate: must be non-empty")
    if qualification.get("blocker_owner") not in {
        "EXECUTION_LANE",
        "MAINTAINER",
        "USER",
        "EXTERNAL_RESOURCE",
        "NONE",
    }:
        errors.append("qualification.blocker_owner: invalid owner")

    policy = exact_keys(root.get("policy"), POLICY_KEYS, "policy", errors)
    stale_after = policy.get("stale_after_hours")
    if (
        not isinstance(stale_after, (int, float))
        or isinstance(stale_after, bool)
        or stale_after <= 0
    ):
        errors.append("policy.stale_after_hours: must be a positive number")
    return errors


def classify(record: dict) -> dict:
    pull = record["pull_request"]
    observation = record["observation"]
    qualification = record["qualification"]
    draft_age = None
    progress_age = None
    if observation["draft_since"] is not None:
        observed_at = datetime.fromisoformat(
            observation["observed_at"].replace("Z", "+00:00")
        )
        draft_age = (
            observed_at
            - datetime.fromisoformat(observation["draft_since"].replace("Z", "+00:00"))
        ).total_seconds() / 3600
        progress_age = (
            observed_at
            - datetime.fromisoformat(
                observation["last_material_progress_at"].replace("Z", "+00:00")
            )
        ).total_seconds() / 3600

    if pull["state"] in {"CLOSED", "MERGED"}:
        state, action, owner = "TERMINAL", "NO_ACTION", "NONE"
    elif not pull["draft"]:
        state, action, owner = "NOT_DRAFT", "USE_REVIEW_HANDOFF", "REVIEWER"
    elif (
        qualification["status"] == "FAILED"
        or qualification["value_status"] == "DISPROVEN"
    ):
        state, action, owner = "EXIT_REQUIRED", "CLOSE_OR_REVISE_DRAFT", "AUTHOR"
    elif qualification["status"] == "PASS":
        state, action, owner = "READY_TRANSITION_DUE", "MARK_READY", "AUTHOR"
    elif (
        progress_age is not None
        and progress_age >= record["policy"]["stale_after_hours"]
    ):
        if qualification["status"] == "ENVIRONMENT_BLOCKED":
            state, action = "STALE_EXTERNAL_GATE", "EXTERNALIZE_GATE_OR_CLOSE_DRAFT"
        else:
            state, action = "STALE_QUALIFICATION", "REPLAN_OR_CLOSE_DRAFT"
        owner = qualification["blocker_owner"]
    else:
        state, action, owner = (
            "ACTIVE_QUALIFICATION",
            "CONTINUE_BOUNDED_QUALIFICATION",
            qualification["blocker_owner"],
        )

    return {
        "schema_version": "upstream-draft-progress-decision-v1",
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
        "observed_draft_age_hours": round(draft_age, 6)
        if draft_age is not None
        else None,
        "material_progress_age_hours": round(progress_age, 6)
        if progress_age is not None
        else None,
        "prospective_lower_bound_only": True,
        "automatic_close_or_ready_authorized": False,
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
