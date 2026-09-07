#!/usr/bin/env python3
"""Record fail-closed postselection feedback for future community cohorts."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from community_knowledge import atomic_json, read_object, sha256_file  # noqa: E402
from schema_utils import validate_json_file  # noqa: E402


ASSESSMENT_SCHEMA = ROOT / "schemas/community_postselection_task_assessment.schema.json"
FEEDBACK_SCHEMA = ROOT / "schemas/community_screening_feedback.schema.json"


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
        timezone.utc
    )


def identity(path: Path) -> dict:
    resolved = path.resolve()
    return {"path": resolved.as_posix(), "sha256": sha256_file(resolved)}


def validate_identity(row: dict, label: str) -> Path:
    path = Path(row["path"]).resolve()
    if not path.is_file():
        raise ValueError(f"{label} evidence is missing: {path}")
    observed = sha256_file(path)
    if observed != row["sha256"]:
        raise ValueError(f"{label} evidence hash changed")
    return path


def validated_assessment(path: Path) -> dict:
    path = path.resolve()
    errors = validate_json_file(path, ASSESSMENT_SCHEMA)
    if errors:
        raise ValueError("invalid postselection assessment: " + "; ".join(errors))
    value = read_object(path)
    decision = value["materialization_decision"]
    if decision["status"] != "OPTIMIZATION_TASK":
        if decision["gpu_dispatch"] or decision["compile_or_benchmark"]:
            raise ValueError("non-optimization feedback cannot claim GPU execution")
    if value["future_policy_observation"]["status"] != (
        "RECORDED_FOR_FUTURE_COHORT_ONLY"
    ):
        raise ValueError("screening feedback must remain future-cohort-only")
    return value


def linked_inputs(assessment: dict) -> tuple[dict, dict, dict]:
    evidence = assessment["frozen_selection_evidence"]
    queue_path = validate_identity(evidence["queue"], "queue")
    screen_path = validate_identity(evidence["screen"], "screen")
    audit_path = validate_identity(evidence["chain_audit"], "chain audit")
    queue = read_object(queue_path)
    screen = read_object(screen_path)
    audit = read_object(audit_path)
    candidate = assessment["candidate"]
    key = (candidate["repository"], int(candidate["pr_number"]))
    queue_items = [
        item
        for item in queue["items"]
        if (item["repository"], int(item["pr_number"])) == key
    ]
    screen_items = [
        item
        for item in screen["items"]
        if (item["repository"], int(item["pr_number"])) == key
    ]
    if len(queue_items) != 1 or queue_items[0]["selection"] != "SELECTED":
        raise ValueError("assessment candidate is not one selected queue item")
    if len(screen_items) != 1:
        raise ValueError("assessment candidate is not one preselection screen item")
    queue_item = queue_items[0]
    screen_item = screen_items[0]
    if queue_item["title"] != candidate["title"]:
        raise ValueError("assessment title differs from frozen queue")
    if queue_item["earliest_public_at"] != candidate["earliest_public_at"]:
        raise ValueError("assessment earliest_public_at differs from frozen queue")
    frozen = assessment["frozen_selection_evidence"]
    if frozen["preselection_decision"] != screen_item["status"]:
        raise ValueError("assessment preselection status differs from frozen screen")
    if frozen["preselection_rule"] != screen_item["matched_rule_id"]:
        raise ValueError("assessment preselection rule differs from frozen screen")
    if candidate["repository"] not in audit["observations"]["observed_repositories"]:
        raise ValueError("assessment repository is absent from the chain audit")
    if parse_time(candidate["earliest_public_at"]) < parse_time(
        audit["observations"]["cutoff_at"]
    ):
        raise ValueError("screening feedback cannot learn from a pre-cutoff candidate")
    return queue, screen, audit


def build_feedback(
    assessment_path: Path,
    observation_id: str,
    available_at: str,
) -> dict:
    assessment_path = assessment_path.resolve()
    assessment = validated_assessment(assessment_path)
    _, _, audit = linked_inputs(assessment)
    if parse_time(available_at) < parse_time(assessment["generated_at"]):
        raise ValueError("feedback cannot be available before its assessment")
    candidate = assessment["candidate"]
    selection = assessment["frozen_selection_evidence"]
    decision = assessment["materialization_decision"]
    knowledge = assessment["knowledge_value"]
    result = {
        "schema_version": "community-screening-feedback-v1",
        "observation_id": observation_id,
        "available_at": available_at,
        "claim_boundary": (
            "FUTURE_COHORT_SCREENING_FEEDBACK_NOT_CURRENT_COHORT_SELECTION_OR_"
            "PERFORMANCE_EVIDENCE"
        ),
        "cohort": {
            "cutoff_at": audit["observations"]["cutoff_at"],
            "git_commit": audit["observations"]["git_commit"],
            "excluded_from_same_cohort": True,
        },
        "candidate": {
            "repository": candidate["repository"],
            "pr_number": candidate["pr_number"],
            "title": candidate["title"],
            "earliest_public_at": candidate["earliest_public_at"],
            "head_sha": candidate["head_sha"],
        },
        "preselection": {
            "status": selection["preselection_decision"],
            "matched_rule_id": selection["preselection_rule"],
        },
        "postselection": {
            "status": decision["status"],
            "reason_codes": sorted(decision["reason_codes"]),
            "gpu_dispatched": decision["gpu_dispatch"],
            "task_materialized": decision["task_materialized"],
        },
        "context_signature": sorted(decision["reason_codes"]),
        "activation_policy": {
            "minimum_distinct_candidates": 2,
            "current_distinct_candidates": 1,
            "status": "INSUFFICIENT_EVIDENCE",
            "action": "RECORD_ONLY_DO_NOT_ROUTE",
        },
        "knowledge_value": {
            "event_family": knowledge["event_family"],
            "positive_method": knowledge["positive_method"],
            "negative_experience": knowledge["negative_experience"],
            "falsification": knowledge["falsification"],
        },
        "evidence": {
            "assessment": identity(assessment_path),
            "queue": selection["queue"],
            "screen": selection["screen"],
            "chain_audit": selection["chain_audit"],
        },
    }
    errors = validate_json_file_object(result, FEEDBACK_SCHEMA)
    if errors:
        raise ValueError("invalid screening feedback: " + "; ".join(errors))
    return result


def validate_json_file_object(value: dict, schema_path: Path) -> list[str]:
    """Validate an object without writing it by using the shared schema helper."""
    from schema_utils import validate_instance

    return validate_instance(value, read_object(schema_path))


def validate_feedback(path: Path) -> dict:
    path = path.resolve()
    errors = validate_json_file(path, FEEDBACK_SCHEMA)
    if errors:
        raise ValueError("invalid screening feedback: " + "; ".join(errors))
    observed = read_object(path)
    assessment_path = validate_identity(observed["evidence"]["assessment"], "assessment")
    expected = build_feedback(
        assessment_path,
        observed["observation_id"],
        observed["available_at"],
    )
    if observed != expected:
        raise ValueError("screening feedback is stale or was edited")
    return {
        "status": "PASS",
        "observation_id": observed["observation_id"],
        "candidate": (
            f"{observed['candidate']['repository']}#"
            f"{observed['candidate']['pr_number']}"
        ),
        "activation_status": observed["activation_policy"]["status"],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    operations = parser.add_subparsers(dest="operation", required=True)
    build = operations.add_parser("build")
    build.add_argument("--assessment", type=Path, required=True)
    build.add_argument("--observation-id", required=True)
    build.add_argument("--available-at", required=True)
    build.add_argument("--output", type=Path, required=True)
    validate = operations.add_parser("validate")
    validate.add_argument("--feedback", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.operation == "build":
            value = build_feedback(
                args.assessment, args.observation_id, args.available_at
            )
            atomic_json(args.output.resolve(), value)
            result = {
                "status": "PASS",
                "feedback": str(args.output.resolve()),
                "observation_id": value["observation_id"],
                "activation_status": value["activation_policy"]["status"],
            }
        else:
            result = validate_feedback(args.feedback)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
