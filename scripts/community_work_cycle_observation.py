#!/usr/bin/env python3
"""Validate a unified observation envelope for one optimization arm."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from community_knowledge import read_object, sha256_file
from community_work_cycle import summarize, validate_ledger
from schema_utils import validate_json_file


SCHEMA_VERSION = "community-work-cycle-observation-v1"
VALIDATION_PHASES = {
    "CORRECTNESS_VALIDATION",
    "PERFORMANCE_VALIDATION",
    "WHOLE_MODEL_VALIDATION",
}


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def resolve_inside(base: Path, relative: str) -> Path:
    base = base.resolve()
    path = (base / relative).resolve()
    try:
        path.relative_to(base)
    except ValueError as error:
        raise ValueError(f"identity path escapes its observation root: {relative}") from error
    return path


def validate_identity(base: Path, identity: dict, label: str) -> Path:
    path = resolve_inside(base, identity["path"])
    if not path.is_file():
        raise FileNotFoundError(f"{label} is missing: {path}")
    if sha256_file(path) != identity["sha256"]:
        raise ValueError(f"{label} hash changed: {identity['path']}")
    return path


def seconds(started_at: str, ended_at: str) -> float:
    start = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    end = datetime.fromisoformat(ended_at.replace("Z", "+00:00"))
    return (end - start).total_seconds()


def close(left: float, right: float) -> bool:
    return abs(left - right) <= 1e-9 * max(1.0, abs(left), abs(right))


def validate_observation(
    observation_path: Path, root: Path | None = None
) -> dict:
    root = (root or repository_root()).resolve()
    observation_path = observation_path.resolve()
    errors = validate_json_file(
        observation_path,
        root / "schemas/community_work_cycle_observation.schema.json",
    )
    if errors:
        raise ValueError("invalid work-cycle observation: " + "; ".join(errors))
    observation = read_object(observation_path)
    if observation["schema_version"] != SCHEMA_VERSION:
        raise ValueError("unsupported work-cycle observation schema")
    base = observation_path.parent

    ledger_path = validate_identity(base, observation["ledger_identity"], "work-cycle ledger")
    ledger = validate_ledger(ledger_path, allow_active=False)
    if ledger["task_id"] != observation["task_id"]:
        raise ValueError("observation task_id does not match work-cycle ledger")

    assessment_path = validate_identity(
        base, observation["assessment_identity"], "trial assessment"
    )
    assessment_errors = validate_json_file(
        assessment_path, root / "schemas/community_trial_assessment.schema.json"
    )
    if assessment_errors:
        raise ValueError("invalid trial assessment: " + "; ".join(assessment_errors))
    assessment = read_object(assessment_path)
    if (
        assessment["suite_id"] != observation["suite_id"]
        or assessment["task_id"] != observation["task_id"]
        or assessment["repeat_index"] != observation["repeat_index"]
        or assessment["arm"] != observation["arm"]
    ):
        raise ValueError("observation identity does not match trial assessment")

    for index, source in enumerate(observation["candidate_sources"]):
        validate_identity(base, source["identity"], f"candidate source {index + 1}")
    candidate_count = assessment["budget_usage"]["candidate_count"]
    if bool(observation["candidate_sources"]) != (candidate_count > 0):
        raise ValueError(
            "candidate_sources must be non-empty exactly when candidates were evaluated"
        )
    if observation["arm"] == "CONTROL":
        forbidden = {"COMMUNITY_EVENT", "METHOD", "HYBRID"}
        if any(source["kind"] in forbidden for source in observation["candidate_sources"]):
            raise ValueError("CONTROL observation cannot claim community-derived sources")
        if observation["search_policy"]["community_knowledge_exposed"]:
            raise ValueError("CONTROL observation cannot expose community knowledge")
    elif not observation["search_policy"]["community_knowledge_exposed"]:
        raise ValueError("COMMUNITY_AUGMENTED observation must expose frozen knowledge")

    regression = observation["regression"]
    if regression["failure_count"] > regression["test_count"]:
        raise ValueError("regression failure_count exceeds test_count")
    if regression["test_count"] == 0:
        if regression["rate"] is not None or regression["evidence"]:
            raise ValueError("zero regression denominator requires null rate and no evidence")
    else:
        expected_rate = regression["failure_count"] / regression["test_count"]
        if regression["rate"] is None or not close(regression["rate"], expected_rate):
            raise ValueError("regression rate does not match counts")
        if not regression["evidence"]:
            raise ValueError("measured regression rate requires evidence")
    for index, identity in enumerate(regression["evidence"]):
        validate_identity(base, identity, f"regression evidence {index + 1}")

    real_workload = observation["real_workload"]
    ledger_speedup = ledger["outcome"]["best_whole_model_speedup"]
    if real_workload["status"] == "NOT_RUN":
        if real_workload["speedup"] is not None or real_workload["evidence"]:
            raise ValueError("NOT_RUN real workload must not claim speedup or evidence")
        if ledger_speedup is not None:
            raise ValueError("ledger whole-model speedup conflicts with NOT_RUN workload")
    else:
        if (
            real_workload["speedup"] is None
            or ledger_speedup is None
            or not close(real_workload["speedup"], ledger_speedup)
            or not real_workload["evidence"]
        ):
            raise ValueError("real workload result must match ledger and bind evidence")
    for index, identity in enumerate(real_workload["evidence"]):
        validate_identity(base, identity, f"real workload evidence {index + 1}")

    ledger_summary = summarize(ledger_path)
    gpu_seconds = sum(
        seconds(span["started_at"], span["ended_at"])
        for span in ledger["spans"]
        if span["actor"] == "GPU" and span["ended_at"] is not None
    )
    validation_seconds = sum(
        seconds(span["started_at"], span["ended_at"])
        for span in ledger["spans"]
        if span["phase"] in VALIDATION_PHASES and span["ended_at"] is not None
    )
    expected_usage = {
        "wall_clock_seconds": ledger_summary["wall_clock"]["observed_seconds"],
        "gpu_seconds": gpu_seconds,
        "validation_seconds": validation_seconds,
    }
    for key, expected in expected_usage.items():
        if not close(observation["resource_usage"][key], expected):
            raise ValueError(f"resource_usage.{key} does not match work-cycle ledger")
    if ledger["outcome"]["correctness"] == "PASS" and validation_seconds == 0:
        raise ValueError("correctness PASS requires recorded validation time")

    return {
        "observation": observation,
        "ledger": ledger,
        "assessment": assessment,
        "ledger_path": ledger_path,
        "assessment_path": assessment_path,
        "gpu_seconds": gpu_seconds,
        "validation_seconds": validation_seconds,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["validate"])
    parser.add_argument("--observation", required=True, type=Path)
    args = parser.parse_args()
    result = validate_observation(args.observation)
    print(
        json.dumps(
            {
                "status": "PASS",
                "task_id": result["observation"]["task_id"],
                "arm": result["observation"]["arm"],
                "repeat_index": result["observation"]["repeat_index"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
