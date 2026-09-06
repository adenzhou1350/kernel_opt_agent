#!/usr/bin/env python3
"""Materialize and score leakage-resistant community-knowledge A/B trials."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import subprocess
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from statistics import median

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
REPEAT_SUMMARY_SCHEMA = "community-ab-repeat-summary-v1"
SCHEDULE_SCHEMA = "community-evaluation-schedule-v1"
SOURCE_RECEIPT_SCHEMA = "community-trial-source-receipt-v1"
EXECUTION_AUDIT_SCHEMA = "community-trial-execution-audit-v1"
SUITE_RUN_SUMMARY_SCHEMA = "community-suite-run-summary-v1"
TASK_PACKET_AUDIT_SCHEMA = "community-task-packet-audit-v1"
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
    validate_identity(
        base, suite["protocol"]["environment_identity"], "runtime environment"
    )
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


def source_tree_snapshot(source: Path) -> dict:
    """Return a deterministic content-only identity for a materialized source tree."""
    source = source.resolve()
    if not source.is_dir():
        raise FileNotFoundError(f"materialized source tree is missing: {source}")
    entries = []
    for path in sorted(item for item in source.rglob("*") if item.is_file()):
        entries.append(
            {
                "path": path.relative_to(source).as_posix(),
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    if not entries:
        raise ValueError("materialized source tree is empty")
    encoded = json.dumps(
        entries, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return {
        "schema_version": "community-source-tree-v1",
        "file_count": len(entries),
        "content_bytes": sum(item["size"] for item in entries),
        "root_sha256": hashlib.sha256(encoded).hexdigest(),
        "entries": entries,
    }


def safe_extract_zip(archive: Path, destination: Path) -> None:
    """Extract a git archive without traversal or live-link materialization.

    Git ZIP archives store a symlink's target as its blob payload. Writing that
    payload as a regular file matches Git for Windows with ``core.symlinks=false``
    and prevents a link from escaping the isolated trial.
    """
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(archive) as zipped:
        for info in zipped.infolist():
            relative = PurePosixPath(info.filename)
            if relative.is_absolute() or not relative.parts or ".." in relative.parts:
                raise ValueError(f"unsafe source archive member: {info.filename}")
            target = (destination / Path(*relative.parts)).resolve()
            try:
                target.relative_to(destination)
            except ValueError as error:
                raise ValueError(
                    f"source archive member escapes destination: {info.filename}"
                ) from error
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zipped.open(info) as source_stream, target.open("wb") as target_stream:
                shutil.copyfileobj(source_stream, target_stream)


def run_git(repository: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        text=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise ValueError(f"git {' '.join(arguments)} failed: {detail}")
    return completed.stdout.strip()


def prepare_trial_source(
    trial_dir: Path, repository: Path, root: Path | None = None
) -> dict:
    """Materialize and bind the exact historical source revision for one trial."""
    root = root or repository_root()
    trial_dir = trial_dir.resolve()
    trial = validate_trial(trial_dir, root)
    repository = repository.resolve()
    if not repository.is_dir():
        raise FileNotFoundError(f"source repository is missing: {repository}")
    source_dir = trial_dir / "source"
    receipt_path = trial_dir / "source_receipt.json"
    tree_path = trial_dir / "source_tree.json"
    if source_dir.exists() or receipt_path.exists() or tree_path.exists():
        raise ValueError("trial source has already been materialized")

    revision = trial["source_checkout"]["revision"]
    resolved_revision = run_git(repository, "rev-parse", f"{revision}^{{commit}}")
    if resolved_revision != revision:
        raise ValueError(
            f"source revision resolved to {resolved_revision}, expected {revision}"
        )
    tree_id = run_git(repository, "rev-parse", f"{revision}^{{tree}}")

    with tempfile.TemporaryDirectory(prefix="source-materialization-", dir=trial_dir) as temporary:
        temporary_path = Path(temporary)
        archive_path = temporary_path / "source.zip"
        archive_result = subprocess.run(
            ["git", "archive", "--format=zip", "--output", str(archive_path), revision],
            cwd=repository,
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if archive_result.returncode:
            detail = archive_result.stderr.strip() or archive_result.stdout.strip()
            raise ValueError(f"git archive failed: {detail}")
        archive_sha256 = sha256_file(archive_path)
        extracted = temporary_path / "extracted"
        safe_extract_zip(archive_path, extracted)
        extracted.rename(source_dir)

    source_tree = source_tree_snapshot(source_dir)
    atomic_json(tree_path, source_tree)
    receipt = {
        "schema_version": SOURCE_RECEIPT_SCHEMA,
        "generated_at": now(),
        "claim_boundary": "EXACT_HISTORICAL_SOURCE_MATERIALIZATION",
        "trial_identity": identity_for(trial_dir / "trial.json", trial_dir),
        "repository": trial["source_checkout"]["repository"],
        "revision": revision,
        "git_tree": tree_id,
        "archive_sha256": archive_sha256,
        "symlink_policy": "BLOB_TEXT_NO_LIVE_LINKS",
        "source_root": "source",
        "source_tree": identity_for(tree_path, trial_dir),
        "source_root_sha256": source_tree["root_sha256"],
    }
    errors = validate_instance(
        receipt,
        read_object(root / "schemas" / "community_trial_source_receipt.schema.json"),
    )
    if errors:
        raise ValueError("invalid source receipt: " + "; ".join(errors))
    atomic_json(receipt_path, receipt)
    return validate_source_receipt(trial_dir, root)


def validate_source_receipt(
    trial_dir: Path, root: Path | None = None
) -> dict:
    root = root or repository_root()
    trial_dir = trial_dir.resolve()
    trial = validate_trial(trial_dir, root)
    receipt_path = trial_dir / "source_receipt.json"
    errors = validate_json_file(
        receipt_path,
        root / "schemas" / "community_trial_source_receipt.schema.json",
    )
    if errors:
        raise ValueError("invalid source receipt: " + "; ".join(errors))
    receipt = read_object(receipt_path)
    validate_identity(trial_dir, receipt["trial_identity"], "source receipt trial")
    if receipt["repository"] != trial["source_checkout"]["repository"]:
        raise ValueError("source receipt repository differs from trial")
    if receipt["revision"] != trial["source_checkout"]["revision"]:
        raise ValueError("source receipt revision differs from trial")
    tree_path = validate_identity(
        trial_dir, receipt["source_tree"], "source tree manifest"
    )
    recorded_tree = read_object(tree_path)
    observed_tree = source_tree_snapshot(resolve_inside(trial_dir, receipt["source_root"]))
    if observed_tree != recorded_tree:
        raise ValueError("materialized source tree changed after binding")
    if receipt["source_root_sha256"] != observed_tree["root_sha256"]:
        raise ValueError("source root hash differs from source tree manifest")
    return {
        "status": "PASS",
        "trial_id": trial["trial_id"],
        "revision": receipt["revision"],
        "git_tree": receipt["git_tree"],
        "file_count": observed_tree["file_count"],
        "content_bytes": observed_tree["content_bytes"],
        "source_root_sha256": observed_tree["root_sha256"],
    }


def audit_codex_execution(
    trial_dir: Path,
    transcript_name: str = "executor.jsonl",
    stderr_name: str = "executor.stderr.log",
    sandbox_mode: str = "AUDITED_UNRESTRICTED",
    root: Path | None = None,
) -> dict:
    """Audit an isolated Codex JSONL transcript without trusting its summary."""
    root = root or repository_root()
    trial_dir = trial_dir.resolve()
    trial = validate_trial(trial_dir, root)
    transcript_path = resolve_inside(trial_dir, transcript_name)
    stderr_path = resolve_inside(trial_dir, stderr_name)
    if not transcript_path.is_file():
        raise FileNotFoundError(f"executor transcript is missing: {transcript_path}")
    if not stderr_path.is_file():
        raise FileNotFoundError(f"executor stderr log is missing: {stderr_path}")

    commands = []
    completed_commands = 0
    failed_commands = 0
    declined_commands = 0
    max_declared_repairs = 0
    turn_completed = False
    malformed_lines = 0
    # JSONL records are delimited only by physical LF/CRLF bytes.  str.splitlines()
    # also splits valid JSON string data on Unicode U+2028/U+2029, which can occur
    # in minified JavaScript captured in command output and creates a false audit
    # failure.  TextIO iteration preserves those code points inside the record.
    with transcript_path.open(encoding="utf-8", newline="") as transcript:
        for line in transcript:
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                malformed_lines += 1
                continue
            if event.get("type") == "turn.completed":
                turn_completed = True
            item = event.get("item") or {}
            if (
                event.get("type") == "item.started"
                and item.get("type") == "command_execution"
            ):
                commands.append(str(item.get("command", "")))
            if (
                event.get("type") == "item.completed"
                and item.get("type") == "command_execution"
            ):
                status = item.get("status")
                if status == "completed":
                    completed_commands += 1
                    if item.get("exit_code") not in (None, 0):
                        failed_commands += 1
                elif status == "failed":
                    failed_commands += 1
                elif status == "declined":
                    declined_commands += 1
            if (
                event.get("type") == "item.completed"
                and item.get("type") == "agent_message"
            ):
                try:
                    message = json.loads(item.get("text", ""))
                except (json.JSONDecodeError, TypeError):
                    continue
                declared = message.get("technical_repair_attempts")
                if isinstance(declared, int):
                    max_declared_repairs = max(max_declared_repairs, declared)

    normalized = "\n".join(commands)
    forbidden_patterns = {
        "NETWORK_COMMAND": r"(?i)(Invoke-WebRequest|curl(?:\.exe)?\s|wget\s|https?://|ssh\s|scp\s)",
        "REMOTE_GIT_COMMAND": r"(?i)git\s+(fetch|clone|pull|remote)\b",
        "PARENT_TRAVERSAL": r"(?<!\.)\.\.[\\/]",
    }
    violations = [
        name for name, pattern in forbidden_patterns.items() if re.search(pattern, normalized)
    ]
    trial_windows = str(trial_dir).lower()
    trial_wsl = "/mnt/" + trial_windows[0] + trial_windows[2:].replace("\\", "/")
    external_paths = []
    for command in commands:
        for match in re.findall(r"(?i)[a-z]:\\[^\s'\";]+", command):
            lowered = match.rstrip(".,)").lower()
            while "\\\\" in lowered:
                lowered = lowered.replace("\\\\", "\\")
            if lowered.startswith(trial_windows):
                continue
            if "codex-runtimes\\codex-primary-runtime" in lowered:
                continue
            external_paths.append(hashlib.sha256(lowered.encode()).hexdigest())
        for match in re.findall(r"/mnt/[a-z]/[^\s'\";]+", command):
            lowered = match.rstrip(".,)").lower()
            if not lowered.startswith(trial_wsl):
                external_paths.append(hashlib.sha256(lowered.encode()).hexdigest())
    if external_paths:
        violations.append("EXTERNAL_DATA_PATH")
    if malformed_lines:
        violations.append("MALFORMED_TRANSCRIPT")

    repair_lower_bound = max(failed_commands, declined_commands, max_declared_repairs)
    if repair_lower_bound > trial["budget"]["max_technical_repairs"]:
        violations.append("TECHNICAL_REPAIR_BUDGET_EXCEEDED")
    result_path = trial_dir / "result.json"
    result_identity = identity_for(result_path, trial_dir) if result_path.is_file() else None
    if not turn_completed:
        violations.append("TURN_NOT_COMPLETED")
    if result_identity is None:
        violations.append("RESULT_MISSING")
    else:
        result_errors = validate_json_file(
            result_path, root / "schemas" / "community_trial_result.schema.json"
        )
        if result_errors:
            violations.append("RESULT_SCHEMA_INVALID")

    violations = sorted(set(violations))
    receipt = {
        "schema_version": EXECUTION_AUDIT_SCHEMA,
        "generated_at": now(),
        "claim_boundary": "TRANSCRIPT_AND_RESULT_INTEGRITY_ONLY",
        "status": "PASS" if not violations else "FAIL",
        "sandbox_mode": sandbox_mode,
        "auditor_identity": {
            "implementation": identity_for(
                root / "scripts" / "community_evaluation.py", root
            ),
            "contract": identity_for(
                root / "schemas" / "community_trial_execution_audit.schema.json",
                root,
            ),
        },
        "trial_identity": identity_for(trial_dir / "trial.json", trial_dir),
        "transcript_identity": identity_for(transcript_path, trial_dir),
        "stderr_identity": identity_for(stderr_path, trial_dir),
        "result_identity": result_identity,
        "observations": {
            "command_count": len(commands),
            "completed_command_count": completed_commands,
            "failed_command_count": failed_commands,
            "declined_command_count": declined_commands,
            "max_agent_declared_technical_repairs": max_declared_repairs,
            "technical_repair_lower_bound": repair_lower_bound,
            "turn_completed": turn_completed,
            "malformed_line_count": malformed_lines,
            "external_path_hashes": sorted(set(external_paths)),
        },
        "violations": violations,
    }
    errors = validate_instance(
        receipt,
        read_object(root / "schemas" / "community_trial_execution_audit.schema.json"),
    )
    if errors:
        raise ValueError("invalid execution audit: " + "; ".join(errors))
    atomic_json(trial_dir / "execution_audit.json", receipt)
    return receipt


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
    # Executors are required to retain measurements here. Materializing the
    # directory avoids charging one arm a repair merely because its first
    # read-only inspection happens before it writes evidence.
    (output / "evidence").mkdir(parents=True, exist_ok=True)

    suite_base = suite_path.parent
    task_source = validate_identity(suite_base, task["packet"], "task packet")
    prompt_source = validate_identity(
        suite_base, suite["protocol"]["prompt_identity"], "trial prompt"
    )
    environment_source = validate_identity(
        suite_base, suite["protocol"]["environment_identity"], "runtime environment"
    )
    task_target = output / "input" / "task.json"
    prompt_target = output / "input" / "prompt.md"
    environment_target = output / "input" / "environment.json"
    result_schema_target = output / "input" / "result.schema.json"
    executor_prompt_target = output / "input" / "executor.md"
    shutil.copyfile(task_source, task_target)
    shutil.copyfile(prompt_source, prompt_target)
    shutil.copyfile(environment_source, environment_target)
    shutil.copyfile(
        root / "schemas" / "community_trial_result.schema.json",
        result_schema_target,
    )
    shutil.copyfile(
        root / "knowledge" / "community" / "executor_prompt.md",
        executor_prompt_target,
    )

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
        "success_thresholds": {
            "minimum_material_speedup": suite["protocol"][
                "minimum_material_speedup"
            ]
        },
        "access_policy": {
            "network": "DISABLED",
            "community_knowledge": knowledge_policy,
        },
        "source_checkout": {
            "repository": task["repository"],
            "revision": task["base_revision"],
        },
        "task_input": identity_for(task_target, output),
        "prompt_input": identity_for(prompt_target, output),
        "environment_input": identity_for(environment_target, output),
        "result_contract": identity_for(result_schema_target, output),
        "executor_prompt": identity_for(executor_prompt_target, output),
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
    validate_identity(
        trial_dir, trial["environment_input"], "trial runtime environment"
    )
    validate_identity(trial_dir, trial["result_contract"], "trial result contract")
    validate_identity(trial_dir, trial["executor_prompt"], "trial executor prompt")
    source_checkout = trial["source_checkout"]
    if len(source_checkout["revision"]) != 40 or any(
        character not in "0123456789abcdef"
        for character in source_checkout["revision"]
    ):
        raise ValueError("trial source revision must be a full lowercase commit hash")
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


def assess_trial(
    trial_dir: Path,
    root: Path | None = None,
    require_execution_audit: bool = False,
) -> dict:
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

    if require_execution_audit:
        audit_path = trial_dir / "execution_audit.json"
        if not audit_path.is_file():
            raise ValueError("valid execution audit required: file is missing")
        audit_errors = validate_json_file(
            audit_path,
            root / "schemas" / "community_trial_execution_audit.schema.json",
        )
        if audit_errors:
            raise ValueError("valid execution audit required: " + "; ".join(audit_errors))
        audit = read_object(audit_path)
        if audit["status"] != "PASS":
            raise ValueError("passing execution audit required")
        validate_identity(
            root,
            audit["auditor_identity"]["implementation"],
            "execution auditor implementation",
        )
        validate_identity(
            root,
            audit["auditor_identity"]["contract"],
            "execution auditor contract",
        )
        if audit["trial_identity"] != identity_for(trial_dir / "trial.json", trial_dir):
            raise ValueError("execution audit is stale for trial manifest")
        if audit["result_identity"] != identity_for(result_path, trial_dir):
            raise ValueError("execution audit is stale for trial result")

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
    minimum_material_speedup = trial["success_thresholds"][
        "minimum_material_speedup"
    ]
    improved = [
        item
        for item in correct
        if item["speedup"] is not None
        and item["speedup"] >= minimum_material_speedup
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
        "success_thresholds": trial["success_thresholds"],
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
    if control["success_thresholds"] != community["success_thresholds"]:
        raise ValueError("paired trials differ in success thresholds")
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


def exact_two_sided_sign_p(wins: int, losses: int) -> float | None:
    observations = wins + losses
    if observations == 0:
        return None
    tail = min(wins, losses)
    probability = sum(math.comb(observations, k) for k in range(tail + 1))
    return min(1.0, 2.0 * probability / (2**observations))


def summarize_pair_rows(rows: list[dict]) -> dict:
    if len(rows) < 2:
        raise ValueError("at least two paired repeats are required")

    def values(field: str) -> list[float]:
        return [float(row[field]) for row in rows if row[field] is not None]

    def median_or_none(field: str) -> float | None:
        observed = values(field)
        return float(median(observed)) if observed else None

    def wins(field: str) -> tuple[int, int, int]:
        observed = values(field)
        return (
            sum(value > 0 for value in observed),
            sum(value < 0 for value in observed),
            sum(value == 0 for value in observed),
        )

    first_wins, first_losses, first_ties = wins("first_correct_seconds_saved")
    family_wins, family_losses, family_ties = wins("architecture_family_gain")
    speed_wins, speed_losses, speed_ties = wins("best_speedup_gain")
    elapsed_wins, elapsed_losses, elapsed_ties = wins("elapsed_seconds_saved")
    return {
        "paired_medians": {
            "elapsed_seconds_saved": median_or_none("elapsed_seconds_saved"),
            "time_to_first_correct_seconds_saved": median_or_none(
                "first_correct_seconds_saved"
            ),
            "architecture_family_count_gain": median_or_none(
                "architecture_family_gain"
            ),
            "best_speedup_gain": median_or_none("best_speedup_gain"),
        },
        "arm_medians": {
            arm: {
                "elapsed_seconds": median_or_none(f"{arm}_elapsed_seconds"),
                "time_to_first_correct_seconds": median_or_none(
                    f"{arm}_first_correct_seconds"
                ),
                "architecture_family_count": median_or_none(
                    f"{arm}_architecture_family_count"
                ),
                "best_speedup": median_or_none(f"{arm}_best_speedup"),
            }
            for arm in ("control", "community_augmented")
        },
        "paired_wins": {
            "faster_time_to_first_correct": {
                "community": first_wins,
                "control": first_losses,
                "ties": first_ties,
                "two_sided_exact_sign_p": exact_two_sided_sign_p(
                    first_wins, first_losses
                ),
            },
            "greater_architecture_family_coverage": {
                "community": family_wins,
                "control": family_losses,
                "ties": family_ties,
            },
            "higher_best_speedup": {
                "community": speed_wins,
                "control": speed_losses,
                "ties": speed_ties,
            },
            "lower_elapsed_seconds": {
                "community": elapsed_wins,
                "control": elapsed_losses,
                "ties": elapsed_ties,
            },
        },
        "material_improvement_repeats": {
            "control": sum(row["control_material_improvement"] for row in rows),
            "community_augmented": sum(
                row["community_augmented_material_improvement"] for row in rows
            ),
        },
    }


def aggregate_pair_reports(
    pair_paths: list[Path], output: Path, root: Path | None = None
) -> dict:
    root = root or repository_root()
    if len(pair_paths) < 2:
        raise ValueError("at least two pair reports are required")
    reports = []
    rows = []
    suite_id = None
    task_id = None
    repeats = set()
    for raw_path in pair_paths:
        pair_path = raw_path.resolve()
        errors = validate_json_file(
            pair_path, root / "schemas" / "community_ab_report.schema.json"
        )
        if errors:
            raise ValueError("invalid paired report: " + "; ".join(errors))
        report = read_object(pair_path)
        suite_id = suite_id or report["suite_id"]
        task_id = task_id or report["task_id"]
        if report["suite_id"] != suite_id or report["task_id"] != task_id:
            raise ValueError("pair reports must belong to one suite and task")
        if report["repeat_index"] in repeats:
            raise ValueError("duplicate repeat index in pair reports")
        repeats.add(report["repeat_index"])
        assessments = {}
        for arm, key in (
            ("CONTROL", "control_assessment"),
            ("COMMUNITY_AUGMENTED", "community_assessment"),
        ):
            assessment_path = validate_identity(
                pair_path.parent, report[key], f"{arm} assessment"
            )
            assessment_errors = validate_json_file(
                assessment_path,
                root / "schemas" / "community_trial_assessment.schema.json",
            )
            if assessment_errors:
                raise ValueError(
                    "invalid trial assessment: " + "; ".join(assessment_errors)
                )
            assessment = read_object(assessment_path)
            if (
                assessment["arm"] != arm
                or assessment["suite_id"] != suite_id
                or assessment["task_id"] != task_id
                or assessment["repeat_index"] != report["repeat_index"]
            ):
                raise ValueError("paired assessment identity does not match report")
            assessments[arm] = assessment
        control = assessments["CONTROL"]
        community = assessments["COMMUNITY_AUGMENTED"]
        control_metrics = control["metrics"]
        community_metrics = community["metrics"]
        rows.append(
            {
                "control_elapsed_seconds": control["budget_usage"]["elapsed_seconds"],
                "community_augmented_elapsed_seconds": community["budget_usage"][
                    "elapsed_seconds"
                ],
                "elapsed_seconds_saved": control["budget_usage"]["elapsed_seconds"]
                - community["budget_usage"]["elapsed_seconds"],
                "control_first_correct_seconds": control_metrics[
                    "time_to_first_correct_seconds"
                ],
                "community_augmented_first_correct_seconds": community_metrics[
                    "time_to_first_correct_seconds"
                ],
                "first_correct_seconds_saved": report["deltas"][
                    "time_to_first_correct_seconds_saved"
                ],
                "control_architecture_family_count": control_metrics[
                    "architecture_family_count"
                ],
                "community_augmented_architecture_family_count": community_metrics[
                    "architecture_family_count"
                ],
                "architecture_family_gain": report["deltas"][
                    "architecture_family_count_gain"
                ],
                "control_best_speedup": control_metrics["best_speedup"],
                "community_augmented_best_speedup": community_metrics["best_speedup"],
                "best_speedup_gain": report["deltas"]["best_speedup_gain"],
                "control_material_improvement": int(
                    control_metrics["time_to_first_improvement_seconds"] is not None
                ),
                "community_augmented_material_improvement": int(
                    community_metrics["time_to_first_improvement_seconds"] is not None
                ),
            }
        )
        reports.append(pair_path)

    output = output.resolve()
    summary = {
        "schema_version": REPEAT_SUMMARY_SCHEMA,
        "generated_at": now(),
        "claim_boundary": "REPEATED_PAIRS_SINGLE_TASK",
        "suite_id": suite_id,
        "task_id": task_id,
        "repeat_count": len(rows),
        "pair_reports": [identity_for(path, output.parent) for path in reports],
        **summarize_pair_rows(rows),
    }
    errors = validate_instance(
        summary,
        read_object(root / "schemas" / "community_ab_repeat_summary.schema.json"),
    )
    if errors:
        raise ValueError("invalid repeat summary: " + "; ".join(errors))
    atomic_json(output, summary)
    return summary


PACKET_AUDIT_STOPWORDS = {
    "and", "are", "for", "from", "into", "only", "the", "this", "that",
    "then", "while", "with", "without", "existing", "already", "available",
}


def packet_audit_tokens(value: object) -> set[str]:
    text = value if isinstance(value, str) else json.dumps(value, sort_keys=True)
    return {
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if len(token) >= 3 and token not in PACKET_AUDIT_STOPWORDS
    }


def audit_task_packets(
    suite_path: Path, output: Path, root: Path | None = None
) -> dict:
    """Detect task packets that reveal too much of their held-out oracle.

    This is a suite-authoring diagnostic, never an executor input: it reads the
    hidden oracle and therefore must remain outside every materialized trial.
    """
    root = root or repository_root()
    suite_path = suite_path.resolve()
    suite_errors = validate_json_file(
        suite_path, root / "schemas" / "community_temporal_suite.schema.json"
    )
    if suite_errors:
        raise ValueError("invalid temporal suite: " + "; ".join(suite_errors))
    suite = read_object(suite_path)
    rows = []
    for task in suite["tasks"]:
        packet_path = validate_identity(
            suite_path.parent, task["packet"], "task packet"
        )
        oracle_path = validate_identity(
            suite_path.parent, task["hidden_oracle"], "hidden oracle"
        )
        packet = read_object(packet_path)
        oracle = read_object(oracle_path)
        mechanism = str(oracle.get("key_mechanism", ""))
        mechanism_tokens = packet_audit_tokens(mechanism)
        packet_tokens = packet_audit_tokens(packet)
        recall = (
            len(mechanism_tokens & packet_tokens) / len(mechanism_tokens)
            if mechanism_tokens
            else 0.0
        )
        family_hits = []
        for family in oracle.get("solution_families", []):
            family_tokens = packet_audit_tokens(str(family).replace("-", " "))
            required = max(1, math.ceil(len(family_tokens) * 2 / 3))
            if family_tokens and len(family_tokens & packet_tokens) >= required:
                family_hits.append(str(family))
        if recall >= 0.60 or len(family_hits) >= 2:
            risk = "HIGH"
        elif recall >= 0.40 or family_hits:
            risk = "MEDIUM"
        else:
            risk = "LOW"
        reasons = []
        if recall >= 0.40:
            reasons.append(
                f"task packet contains {recall:.0%} of distinctive oracle mechanism tokens"
            )
        if family_hits:
            reasons.append("solution-family language appears in the task packet")
        if not reasons:
            reasons.append("no material lexical solution leakage detected")
        rows.append(
            {
                "task_id": task["task_id"],
                "risk": risk,
                "key_mechanism_token_recall": recall,
                "solution_family_hits": sorted(family_hits),
                "reasons": reasons,
            }
        )
    report = {
        "schema_version": TASK_PACKET_AUDIT_SCHEMA,
        "generated_at": now(),
        "claim_boundary": "LEXICAL_SOLUTION_LEAKAGE_DIAGNOSTIC_ONLY",
        "suite_identity": identity_for(suite_path, suite_path.parent),
        "tasks": rows,
        "counts": {
            risk: sum(row["risk"] == risk for row in rows)
            for risk in ("LOW", "MEDIUM", "HIGH")
        },
    }
    errors = validate_instance(
        report,
        read_object(root / "schemas" / "community_task_packet_audit.schema.json"),
    )
    if errors:
        raise ValueError("invalid task-packet audit: " + "; ".join(errors))
    atomic_json(output.resolve(), report)
    return report


def summarize_schedule_run(
    schedule_path: Path, output: Path, root: Path | None = None
) -> dict:
    """Summarize compliant, invalid and unfinished trials without hiding failures."""
    root = root or repository_root()
    schedule_path = schedule_path.resolve()
    validate_schedule(schedule_path, root)
    schedule = read_object(schedule_path)
    rows = []
    for entry in schedule["entries"]:
        trial_dir = resolve_inside(schedule_path.parent, entry["trial_directory"])
        audit_path = trial_dir / "execution_audit.json"
        assessment_path = trial_dir / "assessment.json"
        status = "INCOMPLETE"
        violations = []
        audit_identity = None
        assessment_identity = None
        metrics = None
        if audit_path.is_file():
            audit_errors = validate_json_file(
                audit_path,
                root / "schemas" / "community_trial_execution_audit.schema.json",
            )
            if audit_errors:
                status = "INVALID"
                violations = ["INVALID_EXECUTION_AUDIT"]
            else:
                audit = read_object(audit_path)
                audit_identity = identity_for(audit_path, schedule_path.parent)
                if audit["status"] != "PASS":
                    status = "INVALID"
                    violations = list(audit["violations"])
                elif assessment_path.is_file():
                    assessment_errors = validate_json_file(
                        assessment_path,
                        root / "schemas" / "community_trial_assessment.schema.json",
                    )
                    if assessment_errors:
                        status = "INVALID"
                        violations = ["INVALID_ASSESSMENT"]
                    else:
                        assessment = read_object(assessment_path)
                        status = "PASS"
                        assessment_identity = identity_for(
                            assessment_path, schedule_path.parent
                        )
                        metrics = assessment["metrics"]
                else:
                    violations = ["ASSESSMENT_MISSING"]
        else:
            violations = ["EXECUTION_AUDIT_MISSING"]
        rows.append(
            {
                "order_index": entry["order_index"],
                "task_id": entry["task_id"],
                "repeat_index": entry["repeat_index"],
                "arm": entry["arm"],
                "status": status,
                "violations": violations,
                "audit_identity": audit_identity,
                "assessment_identity": assessment_identity,
                "metrics": metrics,
            }
        )
    pairs = []
    pair_keys = sorted({(row["task_id"], row["repeat_index"]) for row in rows})
    for task_id, repeat_index in pair_keys:
        members = [
            row
            for row in rows
            if row["task_id"] == task_id and row["repeat_index"] == repeat_index
        ]
        by_arm = {row["arm"]: row for row in members}
        pair_status = (
            "COMPARABLE"
            if set(by_arm) == set(ARMS)
            and all(by_arm[arm]["status"] == "PASS" for arm in ARMS)
            else "NOT_COMPARABLE"
        )
        pairs.append(
            {
                "task_id": task_id,
                "repeat_index": repeat_index,
                "status": pair_status,
                "arm_status": {
                    arm: by_arm.get(arm, {}).get("status", "INCOMPLETE")
                    for arm in ARMS
                },
            }
        )
    report = {
        "schema_version": SUITE_RUN_SUMMARY_SCHEMA,
        "generated_at": now(),
        "claim_boundary": "PROTOCOL_COMPLIANCE_AND_OBSERVED_METRICS_ONLY",
        "schedule_identity": identity_for(schedule_path, schedule_path.parent),
        "trials": rows,
        "pairs": pairs,
        "counts": {
            arm: {
                status: sum(
                    row["arm"] == arm and row["status"] == status for row in rows
                )
                for status in ("PASS", "INVALID", "INCOMPLETE")
            }
            for arm in ARMS
        },
    }
    errors = validate_instance(
        report,
        read_object(root / "schemas" / "community_suite_run_summary.schema.json"),
    )
    if errors:
        raise ValueError("invalid suite run summary: " + "; ".join(errors))
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
    prepare_source = subparsers.add_parser("prepare-source")
    prepare_source.add_argument("--trial", type=Path, required=True)
    prepare_source.add_argument("--repository", type=Path, required=True)
    validate_source = subparsers.add_parser("validate-source")
    validate_source.add_argument("--trial", type=Path, required=True)
    audit_execution = subparsers.add_parser("audit-execution")
    audit_execution.add_argument("--trial", type=Path, required=True)
    audit_execution.add_argument("--transcript", default="executor.jsonl")
    audit_execution.add_argument("--stderr", default="executor.stderr.log")
    audit_execution.add_argument(
        "--sandbox-mode",
        choices=("WORKSPACE_WRITE", "AUDITED_UNRESTRICTED"),
        default="AUDITED_UNRESTRICTED",
    )
    assess = subparsers.add_parser("assess-trial")
    assess.add_argument("--trial", type=Path, required=True)
    assess.add_argument("--require-execution-audit", action="store_true")
    compare = subparsers.add_parser("compare")
    compare.add_argument("--control", type=Path, required=True)
    compare.add_argument("--community", type=Path, required=True)
    compare.add_argument("--output", type=Path, required=True)
    aggregate = subparsers.add_parser("aggregate-repeats")
    aggregate.add_argument("--pairs", type=Path, nargs="+", required=True)
    aggregate.add_argument("--output", type=Path, required=True)
    task_packet_audit = subparsers.add_parser("audit-task-packets")
    task_packet_audit.add_argument("--suite", type=Path, required=True)
    task_packet_audit.add_argument("--output", type=Path, required=True)
    summarize_schedule = subparsers.add_parser("summarize-schedule")
    summarize_schedule.add_argument("--schedule", type=Path, required=True)
    summarize_schedule.add_argument("--output", type=Path, required=True)
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
        elif args.operation == "prepare-source":
            result = prepare_trial_source(args.trial, args.repository)
        elif args.operation == "validate-source":
            result = validate_source_receipt(args.trial)
        elif args.operation == "audit-execution":
            result = audit_codex_execution(
                args.trial, args.transcript, args.stderr, args.sandbox_mode
            )
        elif args.operation == "assess-trial":
            result = assess_trial(
                args.trial,
                require_execution_audit=args.require_execution_audit,
            )
        elif args.operation == "aggregate-repeats":
            result = aggregate_pair_reports(args.pairs, args.output)
        elif args.operation == "audit-task-packets":
            result = audit_task_packets(args.suite, args.output)
        elif args.operation == "summarize-schedule":
            result = summarize_schedule_run(args.schedule, args.output)
        else:
            result = compare_trials(args.control, args.community, args.output)
    except Exception as error:
        print(f"ERROR: {error}", file=__import__("sys").stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
