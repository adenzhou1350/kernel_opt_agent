#!/usr/bin/env python3
"""Classify public pull-request checks without treating policy gates as regressions."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from schema_utils import validate_json_file


SNAPSHOT_SCHEMA = "upstream_ci_snapshot.schema.json"
DECISION_SCHEMA = "upstream_ci_route_decision.schema.json"
FAILURE_CONCLUSIONS = {"FAILURE", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED"}

POLICY_GATE_MARKERS = (
    "block draft pr",
    "require run-ci label",
    "require run-ci-extra label",
    "maintainer authorization required",
    "workflow approval required",
)
CANDIDATE_FAILURE_MARKERS = (
    "assertionerror",
    "candidate test failure",
    "compilation failed",
    "failed tests:",
    "lint failed",
    "test failures",
    "tests failed",
    "type check failed",
)
INFRASTRUCTURE_FAILURE_MARKERS = (
    "hosted runner lost communication",
    "network timeout",
    "no space left on device",
    "runner unavailable",
    "service unavailable",
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("observed_at must include a timezone")
    return parsed


def classify_check(check: dict) -> str:
    status = check["status"]
    conclusion = check["conclusion"]
    if status != "COMPLETED":
        return "RUNNING"
    if conclusion in {"SUCCESS", "NEUTRAL"}:
        return "SUCCESS"
    if conclusion == "SKIPPED":
        return "SKIPPED"
    if conclusion not in FAILURE_CONCLUSIONS:
        return "UNKNOWN_FAILURE"

    evidence = "\n".join([check["name"], *check["evidence_lines"]]).casefold()
    if any(marker in evidence for marker in CANDIDATE_FAILURE_MARKERS):
        return "CANDIDATE_FAILURE"
    if any(marker in evidence for marker in INFRASTRUCTURE_FAILURE_MARKERS):
        return "INFRASTRUCTURE_FAILURE"
    if any(marker in evidence for marker in POLICY_GATE_MARKERS):
        return "POLICY_GATE"
    return "UNKNOWN_FAILURE"


def validate_snapshot(snapshot_path: Path, schema_root: Path) -> dict:
    errors = validate_json_file(snapshot_path, schema_root / SNAPSHOT_SCHEMA)
    if errors:
        raise ValueError("invalid CI snapshot: " + "; ".join(errors))
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    parse_time(snapshot["observed_at"])
    check_ids = [check["check_id"] for check in snapshot["checks"]]
    if len(check_ids) != len(set(check_ids)):
        raise ValueError("check_id values must be unique")
    for check in snapshot["checks"]:
        completed = check["status"] == "COMPLETED"
        if completed != (check["conclusion"] is not None):
            raise ValueError(
                f"{check['check_id']}: completed checks require a conclusion "
                "and live checks require null"
            )
    return snapshot


def route(snapshot: dict, snapshot_path: Path) -> dict:
    classified = [
        {
            "check_id": check["check_id"],
            "name": check["name"],
            "classification": classify_check(check),
            "details_url": check["details_url"],
        }
        for check in snapshot["checks"]
    ]
    counts = Counter(item["classification"] for item in classified)
    normalized_counts = {
        key.casefold(): counts[key]
        for key in (
            "SUCCESS",
            "SKIPPED",
            "RUNNING",
            "POLICY_GATE",
            "CANDIDATE_FAILURE",
            "INFRASTRUCTURE_FAILURE",
            "UNKNOWN_FAILURE",
        )
    }

    if counts["CANDIDATE_FAILURE"]:
        stage, action, owner = (
            "CANDIDATE_FAILURE",
            "RESPOND_TO_CANDIDATE_FAILURE",
            "AUTHOR",
        )
    elif counts["UNKNOWN_FAILURE"]:
        stage, action, owner = "UNKNOWN_FAILURE", "INSPECT_FAILED_CHECKS", "AUTHOR"
    elif counts["INFRASTRUCTURE_FAILURE"]:
        stage, action, owner = (
            "INFRASTRUCTURE_FAILURE",
            "ROUTE_INFRASTRUCTURE_FAILURE",
            "CONTROL_PLANE",
        )
    elif counts["POLICY_GATE"]:
        stage = "POLICY_GATE"
        action = (
            "KEEP_DRAFT_AND_WAIT"
            if snapshot["draft"]
            else "WAIT_FOR_MAINTAINER_CI_AUTHORIZATION"
        )
        owner = "MAINTAINER"
    elif counts["RUNNING"]:
        stage, action, owner = (
            "RUNNING",
            "WAIT_FOR_CHECK_COMPLETION",
            "CONTROL_PLANE",
        )
    else:
        stage, action, owner = "PASS", "CI_PASS", "CONTROL_PLANE"

    failure_total = sum(
        counts[key]
        for key in (
            "POLICY_GATE",
            "CANDIDATE_FAILURE",
            "INFRASTRUCTURE_FAILURE",
            "UNKNOWN_FAILURE",
        )
    )
    return {
        "schema_version": "upstream-ci-route-decision-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "snapshot": {"path": str(snapshot_path), "sha256": sha256_file(snapshot_path)},
        "repository": snapshot["repository"],
        "pull_request_number": snapshot["pull_request_number"],
        "head_sha": snapshot["head_sha"],
        "draft": snapshot["draft"],
        "counts": normalized_counts,
        "github_ci_stage": stage,
        "candidate_test_failure": bool(counts["CANDIDATE_FAILURE"]),
        "only_policy_gate_failures": bool(failure_total)
        and failure_total == counts["POLICY_GATE"],
        "recommended_action": action,
        "external_action_owner": owner,
        "classified_checks": classified,
        "claim_boundary": (
            "ROUTING_ONLY_NO_CI_RERUN_COMMENT_READY_TRANSITION_OR_MERGE_AUTHORIZATION"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    schema_root = Path(__file__).resolve().parents[1] / "schemas"
    try:
        snapshot_path = args.snapshot.resolve()
        snapshot = validate_snapshot(snapshot_path, schema_root)
        decision = route(snapshot, snapshot_path)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(decision, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        errors = validate_json_file(args.output, schema_root / DECISION_SCHEMA)
        if errors:
            raise ValueError("invalid generated decision: " + "; ".join(errors))
    except Exception as error:
        print(json.dumps({"status": "FAIL", "errors": [str(error)]}, indent=2))
        return 1
    print(json.dumps(decision, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
