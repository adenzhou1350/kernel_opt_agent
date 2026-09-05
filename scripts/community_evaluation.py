#!/usr/bin/env python3
"""Materialize and score leakage-resistant community-knowledge A/B trials."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path

from community_knowledge import (
    atomic_json,
    now,
    read_object,
    sha256_file,
    validate_corpus,
    validate_graph,
)
from schema_utils import validate_instance, validate_json_file


SUITE_SCHEMA = "community-temporal-suite-v1"
TRIAL_SCHEMA = "community-evaluation-trial-v1"
RESULT_SCHEMA = "community-trial-result-v1"
ASSESSMENT_SCHEMA = "community-trial-assessment-v1"
REPORT_SCHEMA = "community-ab-report-v1"
SCHEDULE_SCHEMA = "community-evaluation-schedule-v1"
ARMS = ("CONTROL", "COMMUNITY_AUGMENTED")
METRICS = {
    "TIME_TO_FIRST_CORRECT",
    "TIME_TO_FIRST_IMPROVEMENT",
    "BEST_SPEEDUP",
    "ARCHITECTURE_FAMILY_COVERAGE",
    "HELDOUT_CORRECTNESS",
    "WHOLE_MODEL_SPEEDUP",
    "UPSTREAM_READINESS",
}


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp must include a timezone: {value}")
    return parsed


def resolve_inside(base: Path, relative: str) -> Path:
    path = (base / relative).resolve()
    try:
        path.relative_to(base.resolve())
    except ValueError as error:
        raise ValueError(f"identity path escapes its artifact root: {relative}") from error
    return path


def validate_identity(base: Path, identity: dict, label: str) -> Path:
    path = resolve_inside(base, identity["path"])
    if not path.is_file():
        raise FileNotFoundError(f"{label} is missing: {path}")
    if sha256_file(path) != identity["sha256"]:
        raise ValueError(f"{label} hash changed: {identity['path']}")
    return path


def validate_suite(
    suite_path: Path, corpus: Path, root: Path | None = None
) -> dict:
    root = root or repository_root()
    suite_path = suite_path.resolve()
    schema_errors = validate_json_file(
        suite_path, root / "schemas" / "community_temporal_suite.schema.json"
    )
    if schema_errors:
        raise ValueError("invalid temporal suite: " + "; ".join(schema_errors))
    suite = read_object(suite_path)
    if suite["schema_version"] != SUITE_SCHEMA:
        raise ValueError("unsupported temporal suite schema")
    if set(suite["protocol"]["metrics"]) != METRICS:
        raise ValueError("temporal suite must measure the complete metric set")

    base = suite_path.parent
    graph_path = validate_identity(base, suite["training_graph"], "training graph")
    validate_corpus(corpus, root)
    validate_graph(graph_path, corpus, root)
    graph = read_object(graph_path)
    cutoff = parse_time(suite["cutoff_at"])
    for node in graph["nodes"]:
        if parse_time(node["source_available_at"]) > cutoff:
            raise ValueError(
                f"temporal leakage: {node['event_id']} source evidence "
                "was available after cutoff"
            )
    training_sources: set[tuple[str, int]] = set()
    for event_identity in graph["input_identity"]["events"]:
        event_path = validate_identity(corpus, event_identity, "training event")
        event = read_object(event_path)
        source = event["source_snapshot"]
        training_sources.add((source["repository"], source["pr_number"]))

    validate_identity(base, suite["protocol"]["prompt_identity"], "trial prompt")
    task_ids: set[str] = set()
    for task in suite["tasks"]:
        if task["task_id"] in task_ids:
            raise ValueError(f"duplicate task_id: {task['task_id']}")
        task_ids.add(task["task_id"])
        if parse_time(task["available_at"]) <= cutoff:
            raise ValueError(
                f"temporal leakage: task {task['task_id']} is not after cutoff"
            )
        if (task["repository"], task["pr_number"]) in training_sources:
            raise ValueError(
                f"temporal leakage: held-out task {task['task_id']} is in training graph"
            )
        validate_identity(base, task["packet"], f"task packet {task['task_id']}")
        validate_identity(base, task["hidden_oracle"], f"hidden oracle {task['task_id']}")
    return {
        "status": "PASS",
        "suite_id": suite["suite_id"],
        "training_event_count": len(graph["nodes"]),
        "task_count": len(suite["tasks"]),
        "cutoff_at": suite["cutoff_at"],
    }


def identity_for(path: Path, base: Path) -> dict:
    return {
        "path": path.resolve().relative_to(base.resolve()).as_posix(),
        "sha256": sha256_file(path),
    }


def materialize_trial(
    suite_path: Path,
    corpus: Path,
    task_id: str,
    arm: str,
    repeat_index: int,
    output: Path,
    root: Path | None = None,
) -> dict:
    root = root or repository_root()
    validate_suite(suite_path, corpus, root)
    if arm not in ARMS:
        raise ValueError(f"arm must be one of {ARMS}")
    suite_path = suite_path.resolve()
    suite = read_object(suite_path)
    if repeat_index < 1 or repeat_index > suite["protocol"]["repeats"]:
        raise ValueError("repeat index is outside the frozen protocol")
    task = next((item for item in suite["tasks"] if item["task_id"] == task_id), None)
    if task is None:
        raise ValueError(f"unknown task_id: {task_id}")
    output = output.resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"trial directory is not empty: {output}")
    (output / "input").mkdir(parents=True, exist_ok=True)

    suite_base = suite_path.parent
    task_source = validate_identity(suite_base, task["packet"], "task packet")
    prompt_source = validate_identity(
        suite_base, suite["protocol"]["prompt_identity"], "trial prompt"
    )
    task_target = output / "input" / "task.json"
    prompt_target = output / "input" / "prompt.md"
    shutil.copyfile(task_source, task_target)
    shutil.copyfile(prompt_source, prompt_target)

    graph_identity = None
    knowledge_policy = "WITHHELD"
    if arm == "COMMUNITY_AUGMENTED":
        (output / "knowledge").mkdir(parents=True, exist_ok=True)
        graph_source = validate_identity(
            suite_base, suite["training_graph"], "training graph"
        )
        graph_target = output / "knowledge" / "community_graph.json"
        shutil.copyfile(graph_source, graph_target)
        graph_identity = identity_for(graph_target, output)
        knowledge_policy = "FROZEN_GRAPH_ONLY"

    trial_id = f"{suite['suite_id']}.{task_id}.r{repeat_index}.{arm.lower()}"
    manifest = {
        "schema_version": TRIAL_SCHEMA,
        "trial_id": trial_id,
        "created_at": now(),
        "suite_identity": {
            "path": str(suite_path),
            "sha256": sha256_file(suite_path),
        },
        "suite_id": suite["suite_id"],
        "task_id": task_id,
        "repeat_index": repeat_index,
        "arm": arm,
        "status": "MATERIALIZED",
        "budget": suite["protocol"]["budgets"],
        "access_policy": {
            "network": "DISABLED",
            "community_knowledge": knowledge_policy,
        },
        "task_input": identity_for(task_target, output),
        "prompt_input": identity_for(prompt_target, output),
        "community_graph": graph_identity,
    }
    errors = validate_instance(
        manifest,
        read_object(root / "schemas" / "community_evaluation_trial.schema.json"),
    )
    if errors:
        raise ValueError("invalid materialized trial: " + "; ".join(errors))
    atomic_json(output / "trial.json", manifest)
    return manifest


def schedule_key(seed: int, *parts: object) -> str:
    value = ":".join([str(seed), *(str(part) for part in parts)])
    return hashlib.sha256(value.encode()).hexdigest()


def planned_trials(suite: dict) -> list[tuple[str, int, str]]:
    seed = int(suite["protocol"]["random_seed"])
    blocks = [
        (task["task_id"], repeat_index)
        for task in suite["tasks"]
        for repeat_index in range(1, int(suite["protocol"]["repeats"]) + 1)
    ]
    blocks.sort(key=lambda item: schedule_key(seed, *item))
    plan = []
    for task_id, repeat_index in blocks:
        arms = sorted(
            ARMS,
            key=lambda arm: schedule_key(seed, task_id, repeat_index, arm),
        )
        plan.extend((task_id, repeat_index, arm) for arm in arms)
    return plan


def validate_schedule(
    schedule_path: Path, root: Path | None = None
) -> dict:
    root = root or repository_root()
    schedule_path = schedule_path.resolve()
    errors = validate_json_file(
        schedule_path,
        root / "schemas" / "community_evaluation_schedule.schema.json",
    )
    if errors:
        raise ValueError("invalid evaluation schedule: " + "; ".join(errors))
    schedule = read_object(schedule_path)
    suite_identity = schedule["suite_identity"]
    suite_path = Path(suite_identity["path"]).resolve()
    if not suite_path.is_file() or sha256_file(suite_path) != suite_identity["sha256"]:
        raise ValueError("evaluation schedule suite identity is stale")
    suite = read_object(suite_path)
    if schedule["random_seed"] != suite["protocol"]["random_seed"]:
        raise ValueError("evaluation schedule random seed differs from suite")
    expected = planned_trials(suite)
    observed = [
        (entry["task_id"], entry["repeat_index"], entry["arm"])
        for entry in schedule["entries"]
    ]
    if observed != expected:
        raise ValueError("evaluation schedule order was edited or incompletely materialized")
    if [entry["order_index"] for entry in schedule["entries"]] != list(
        range(1, len(expected) + 1)
    ):
        raise ValueError("evaluation schedule order indices are not contiguous")
    for entry in schedule["entries"]:
        trial_dir = resolve_inside(schedule_path.parent, entry["trial_directory"])
        trial_manifest = trial_dir / "trial.json"
        if (
            not trial_manifest.is_file()
            or sha256_file(trial_manifest) != entry["trial_manifest_sha256"]
        ):
            raise ValueError(
                f"scheduled trial manifest changed: {entry['trial_directory']}"
            )
        validate_trial(trial_dir, root)
    return {
        "status": "PASS",
        "entry_count": len(expected),
        "random_seed": schedule["random_seed"],
    }


def materialize_suite(
    suite_path: Path,
    corpus: Path,
    output: Path,
    root: Path | None = None,
) -> dict:
    root = root or repository_root()
    validate_suite(suite_path, corpus, root)
    suite_path = suite_path.resolve()
    suite = read_object(suite_path)
    output = output.resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"schedule directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    entries = []
    for order_index, (task_id, repeat_index, arm) in enumerate(
        planned_trials(suite), start=1
    ):
        directory_name = (
            f"{order_index:03d}-{task_id}-r{repeat_index}-{arm.lower()}"
        )
        trial_dir = output / "trials" / directory_name
        materialize_trial(
            suite_path,
            corpus,
            task_id,
            arm,
            repeat_index,
            trial_dir,
            root,
        )
        entries.append(
            {
                "order_index": order_index,
                "task_id": task_id,
                "repeat_index": repeat_index,
                "arm": arm,
                "trial_directory": f"trials/{directory_name}",
                "trial_manifest_sha256": sha256_file(trial_dir / "trial.json"),
            }
        )
    schedule = {
        "schema_version": SCHEDULE_SCHEMA,
        "generated_at": now(),
        "claim_boundary": "EXECUTION_ORDER_ONLY",
        "suite_identity": {
            "path": str(suite_path),
            "sha256": sha256_file(suite_path),
        },
        "random_seed": suite["protocol"]["random_seed"],
        "entries": entries,
    }
    schedule_path = output / "schedule.json"
    atomic_json(schedule_path, schedule)
    result = validate_schedule(schedule_path, root)
    return {**result, "schedule": str(schedule_path)}


def validate_trial(trial_dir: Path, root: Path | None = None) -> dict:
    root = root or repository_root()
    trial_dir = trial_dir.resolve()
    trial_path = trial_dir / "trial.json"
    errors = validate_json_file(
        trial_path, root / "schemas" / "community_evaluation_trial.schema.json"
    )
    if errors:
        raise ValueError("invalid trial manifest: " + "; ".join(errors))
    trial = read_object(trial_path)
    validate_identity(trial_dir, trial["task_input"], "trial task input")
    validate_identity(trial_dir, trial["prompt_input"], "trial prompt input")
    graph = trial["community_graph"]
    if trial["arm"] == "CONTROL":
        if graph is not None or (trial_dir / "knowledge").exists():
            raise ValueError("control trial must not contain community knowledge")
    else:
        if graph is None:
            raise ValueError("community trial is missing its frozen graph")
        validate_identity(trial_dir, graph, "trial community graph")
    return trial


def nullable_min(values: list[float]) -> float | None:
    return min(values) if values else None


def nullable_max(values: list[float]) -> float | None:
    return max(values) if values else None


def assess_trial(trial_dir: Path, root: Path | None = None) -> dict:
    root = root or repository_root()
    trial_dir = trial_dir.resolve()
    trial = validate_trial(trial_dir, root)
    result_path = trial_dir / "result.json"
    errors = validate_json_file(
        result_path, root / "schemas" / "community_trial_result.schema.json"
    )
    if errors:
        raise ValueError("invalid trial result: " + "; ".join(errors))
    result = read_object(result_path)
    for field in ("trial_id", "task_id", "arm"):
        if result[field] != trial[field]:
            raise ValueError(f"trial result {field} does not match manifest")

    candidate_ids: set[str] = set()
    for candidate in result["candidates"]:
        candidate_id = candidate["candidate_id"]
        if candidate_id in candidate_ids:
            raise ValueError(f"duplicate candidate_id: {candidate_id}")
        candidate_ids.add(candidate_id)
        if candidate["evaluated_at_seconds"] < candidate["proposed_at_seconds"]:
            raise ValueError(f"candidate {candidate_id} was evaluated before proposal")
        if candidate["evaluated_at_seconds"] > result["elapsed_seconds"]:
            raise ValueError(f"candidate {candidate_id} exceeds observed wall time")
        if candidate["speedup"] is not None and candidate["measurement_attempts"] < 1:
            raise ValueError(f"candidate {candidate_id} has speedup without measurement")
        if (
            candidate["whole_model_speedup"] is not None
            and candidate["heldout_correctness"] == "NOT_RUN"
        ):
            raise ValueError(
                f"candidate {candidate_id} has whole-model speedup without held-out validation"
            )
        if candidate["upstream_ready"] and (
            candidate["correctness"] != "PASS"
            or candidate["heldout_correctness"] != "PASS"
            or not candidate["evidence"]
        ):
            raise ValueError(
                f"candidate {candidate_id} cannot be upstream-ready without complete evidence"
            )
        for identity in candidate["evidence"]:
            validate_identity(
                trial_dir, identity, f"candidate evidence {candidate_id}"
            )

    budget = trial["budget"]
    usage = {
        "elapsed_seconds": result["elapsed_seconds"],
        "candidate_count": len(result["candidates"]),
        "compile_attempts": sum(
            item["compile_attempts"] for item in result["candidates"]
        ),
        "measurement_attempts": sum(
            item["measurement_attempts"] for item in result["candidates"]
        ),
        "technical_repair_attempts": result["technical_repair_attempts"],
        "causal_revisions": result["causal_revisions"],
    }
    limits = {
        "elapsed_seconds": "wall_clock_seconds",
        "candidate_count": "max_candidates",
        "compile_attempts": "max_compile_attempts",
        "measurement_attempts": "max_measurements",
        "technical_repair_attempts": "max_technical_repairs",
        "causal_revisions": "max_causal_revisions",
    }
    exceeded = [
        name for name, budget_name in limits.items() if usage[name] > budget[budget_name]
    ]
    if exceeded:
        raise ValueError("trial exceeded frozen budget: " + ", ".join(exceeded))

    correct = [
        item for item in result["candidates"] if item["correctness"] == "PASS"
    ]
    improved = [
        item
        for item in correct
        if item["speedup"] is not None and item["speedup"] > 1.0
    ]
    heldout = [
        item for item in correct if item["heldout_correctness"] == "PASS"
    ]
    assessment = {
        "schema_version": ASSESSMENT_SCHEMA,
        "generated_at": now(),
        "claim_boundary": "SINGLE_TRIAL_OBSERVATION",
        "trial_identity": identity_for(trial_dir / "trial.json", trial_dir),
        "result_identity": identity_for(result_path, trial_dir),
        "suite_id": trial["suite_id"],
        "task_id": trial["task_id"],
        "repeat_index": trial["repeat_index"],
        "arm": trial["arm"],
        "metrics": {
            "time_to_first_correct_seconds": nullable_min(
                [item["evaluated_at_seconds"] for item in correct]
            ),
            "time_to_first_improvement_seconds": nullable_min(
                [item["evaluated_at_seconds"] for item in improved]
            ),
            "best_speedup": nullable_max(
                [float(item["speedup"]) for item in correct if item["speedup"] is not None]
            ),
            "architecture_family_count": len(
                {item["architecture_family"] for item in result["candidates"]}
            ),
            "heldout_pass_count": len(heldout),
            "best_whole_model_speedup": nullable_max(
                [
                    float(item["whole_model_speedup"])
                    for item in heldout
                    if item["whole_model_speedup"] is not None
                ]
            ),
            "upstream_ready_count": sum(
                1 for item in heldout if item["upstream_ready"]
            ),
        },
        "budget_usage": usage,
    }
    assessment_errors = validate_instance(
        assessment,
        read_object(root / "schemas" / "community_trial_assessment.schema.json"),
    )
    if assessment_errors:
        raise ValueError("invalid trial assessment: " + "; ".join(assessment_errors))
    atomic_json(trial_dir / "assessment.json", assessment)
    return assessment


def difference(control: float | int | None, community: float | int | None) -> float | None:
    if control is None or community is None:
        return None
    return float(community) - float(control)


def seconds_saved(control: float | None, community: float | None) -> float | None:
    if control is None or community is None:
        return None
    return float(control) - float(community)


def compare_trials(
    control_dir: Path,
    community_dir: Path,
    output: Path,
    root: Path | None = None,
) -> dict:
    root = root or repository_root()
    control = assess_trial(control_dir, root)
    community = assess_trial(community_dir, root)
    if control["arm"] != "CONTROL" or community["arm"] != "COMMUNITY_AUGMENTED":
        raise ValueError("compare requires CONTROL then COMMUNITY_AUGMENTED")
    for field in ("suite_id", "task_id", "repeat_index"):
        if control[field] != community[field]:
            raise ValueError(f"paired trials differ in {field}")
    control_metrics = control["metrics"]
    community_metrics = community["metrics"]
    control_path = control_dir.resolve() / "assessment.json"
    community_path = community_dir.resolve() / "assessment.json"
    report = {
        "schema_version": REPORT_SCHEMA,
        "generated_at": now(),
        "claim_boundary": "PAIRED_TRIAL_ONLY",
        "suite_id": control["suite_id"],
        "task_id": control["task_id"],
        "repeat_index": control["repeat_index"],
        "control_assessment": {
            "path": str(control_path),
            "sha256": sha256_file(control_path),
        },
        "community_assessment": {
            "path": str(community_path),
            "sha256": sha256_file(community_path),
        },
        "deltas": {
            "time_to_first_correct_seconds_saved": seconds_saved(
                control_metrics["time_to_first_correct_seconds"],
                community_metrics["time_to_first_correct_seconds"],
            ),
            "time_to_first_improvement_seconds_saved": seconds_saved(
                control_metrics["time_to_first_improvement_seconds"],
                community_metrics["time_to_first_improvement_seconds"],
            ),
            "best_speedup_gain": difference(
                control_metrics["best_speedup"], community_metrics["best_speedup"]
            ),
            "architecture_family_count_gain": difference(
                control_metrics["architecture_family_count"],
                community_metrics["architecture_family_count"],
            ),
            "heldout_pass_count_gain": difference(
                control_metrics["heldout_pass_count"],
                community_metrics["heldout_pass_count"],
            ),
            "best_whole_model_speedup_gain": difference(
                control_metrics["best_whole_model_speedup"],
                community_metrics["best_whole_model_speedup"],
            ),
            "upstream_ready_count_gain": difference(
                control_metrics["upstream_ready_count"],
                community_metrics["upstream_ready_count"],
            ),
        },
    }
    errors = validate_instance(
        report, read_object(root / "schemas" / "community_ab_report.schema.json")
    )
    if errors:
        raise ValueError("invalid A/B report: " + "; ".join(errors))
    atomic_json(output.resolve(), report)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="operation", required=True)
    validate = subparsers.add_parser("validate-suite")
    validate.add_argument("--suite", type=Path, required=True)
    validate.add_argument("--corpus", type=Path, required=True)
    materialize = subparsers.add_parser("materialize-trial")
    materialize.add_argument("--suite", type=Path, required=True)
    materialize.add_argument("--corpus", type=Path, required=True)
    materialize.add_argument("--task", required=True)
    materialize.add_argument("--arm", choices=ARMS, required=True)
    materialize.add_argument("--repeat", type=int, default=1)
    materialize.add_argument("--output", type=Path, required=True)
    materialize_all = subparsers.add_parser("materialize-suite")
    materialize_all.add_argument("--suite", type=Path, required=True)
    materialize_all.add_argument("--corpus", type=Path, required=True)
    materialize_all.add_argument("--output", type=Path, required=True)
    validate_order = subparsers.add_parser("validate-schedule")
    validate_order.add_argument("--schedule", type=Path, required=True)
    assess = subparsers.add_parser("assess-trial")
    assess.add_argument("--trial", type=Path, required=True)
    compare = subparsers.add_parser("compare")
    compare.add_argument("--control", type=Path, required=True)
    compare.add_argument("--community", type=Path, required=True)
    compare.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.operation == "validate-suite":
            result = validate_suite(args.suite, args.corpus)
        elif args.operation == "materialize-trial":
            result = materialize_trial(
                args.suite,
                args.corpus,
                args.task,
                args.arm,
                args.repeat,
                args.output,
            )
        elif args.operation == "materialize-suite":
            result = materialize_suite(args.suite, args.corpus, args.output)
        elif args.operation == "validate-schedule":
            result = validate_schedule(args.schedule)
        elif args.operation == "assess-trial":
            result = assess_trial(args.trial)
        else:
            result = compare_trials(args.control, args.community, args.output)
    except Exception as error:
        print(f"ERROR: {error}", file=__import__("sys").stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
