#!/usr/bin/env python3
"""Validate a frozen cohort's fail-closed pre-GPU readiness decision."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from community_knowledge import read_object, sha256_file
from schema_utils import validate_json_file


SCHEMA = "community_pre_gpu_readiness.schema.json"


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def resolve_inside(base: Path, relative: str) -> Path:
    base = base.resolve()
    path = (base / relative).resolve()
    try:
        path.relative_to(base)
    except ValueError as error:
        raise ValueError(
            f"identity path escapes the artifact root: {relative}"
        ) from error
    return path


def validate_identity(base: Path, identity: dict, label: str) -> Path:
    path = resolve_inside(base, identity["path"])
    if not path.is_file():
        raise FileNotFoundError(f"{label} is missing: {path}")
    if sha256_file(path) != identity["sha256"]:
        raise ValueError(f"{label} hash changed: {identity['path']}")
    return path


def validate_commit_ancestry(root: Path, ancestor: str, descendant: str) -> None:
    for label, commit in (("frozen protocol", ancestor), ("governance", descendant)):
        result = subprocess.run(
            ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
            cwd=root,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            raise ValueError(f"{label} commit is unavailable: {commit}")
    ancestry = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if ancestry.returncode != 0:
        raise ValueError("governance commit does not descend from the frozen protocol")


def blocker_count(blockers: dict) -> int:
    count = 0
    for label, values in blockers.items():
        if not isinstance(values, list):
            raise ValueError(f"blocker group must be an array: {label}")
        if any(not isinstance(value, str) or not value for value in values):
            raise ValueError(
                f"blocker group contains an empty/non-string value: {label}"
            )
        count += len(values)
    return count


def weight_complete(task: dict) -> bool:
    materialization = task.get("weight_materialization")
    if not isinstance(materialization, dict):
        return False
    if (
        "pair_complete" in materialization
        and materialization["pair_complete"] is not True
    ):
        return False
    states = []
    if isinstance(materialization.get("state"), str):
        states.append(materialization["state"])
    for value in materialization.values():
        if isinstance(value, dict) and isinstance(value.get("state"), str):
            states.append(value["state"])
    return bool(states) and all(state == "COMPLETE_HASH_VERIFIED" for state in states)


def validate_readiness(readiness_path: Path, artifact_root: Path) -> dict:
    root = repository_root()
    errors = validate_json_file(readiness_path, root / "schemas" / SCHEMA)
    if errors:
        raise ValueError("invalid pre-GPU readiness schema: " + "; ".join(errors))
    readiness = read_object(readiness_path)
    artifact_root = artifact_root.resolve()
    identities = 0

    def check(identity: dict | None, label: str) -> Path | None:
        nonlocal identities
        if identity is None:
            return None
        path = validate_identity(artifact_root, identity, label)
        identities += 1
        return path

    if readiness.get("supersedes") is not None:
        check(readiness["supersedes"], "superseded readiness")
    protocol = readiness["protocol_binding"]
    validate_commit_ancestry(
        root,
        protocol["frozen_discovery_and_arm_protocol_commit"],
        protocol["governance_validator_commit"],
    )
    suite_path = check(protocol["temporal_suite"], "temporal suite")
    assert suite_path is not None
    suite = read_object(suite_path)
    if protocol.get("packet_leakage_audit") is not None:
        check(protocol["packet_leakage_audit"], "packet leakage audit")
    for name, identity in readiness.get("supplemental_audits", {}).items():
        check(identity, f"supplemental audit {name}")
    if readiness.get("supervisor_correction") is not None:
        check(readiness["supervisor_correction"], "supervisor correction")

    environment_path = check(
        readiness["formal_resource"]["environment"], "frozen environment"
    )
    assert environment_path is not None
    environment = read_object(environment_path)
    suite_protocol = suite.get("protocol")
    suite_environment = (
        suite_protocol.get("environment_identity")
        if isinstance(suite_protocol, dict)
        else None
    )
    if not isinstance(suite_environment, dict):
        raise ValueError("temporal suite has no environment identity")
    suite_environment_path = validate_identity(
        suite_path.parent, suite_environment, "temporal-suite environment"
    )
    identities += 1
    if suite_environment_path != environment_path or suite_environment.get(
        "sha256"
    ) != readiness["formal_resource"]["environment"].get("sha256"):
        raise ValueError("frozen environment identity differs from the temporal suite")
    frozen_resources = environment.get("resources")
    if not isinstance(frozen_resources, dict) or not frozen_resources:
        raise ValueError("frozen environment has no task resources")

    tasks = readiness["task_freezes"]
    primary_tasks = readiness["cohort_binding"]["primary_tasks"]
    if set(tasks) != set(primary_tasks) or set(tasks) != set(frozen_resources):
        raise ValueError(
            "task freezes, cohort primary tasks and frozen environment resources differ"
        )
    suite_tasks = suite.get("tasks")
    if not isinstance(suite_tasks, list):
        raise ValueError("temporal suite has no task list")
    suite_by_id = {
        item.get("task_id"): item
        for item in suite_tasks
        if isinstance(item, dict) and isinstance(item.get("task_id"), str)
    }
    readiness_task_ids = [task.get("task_id") for task in tasks.values()]
    if (
        any(
            not isinstance(task_id, str) or not task_id
            for task_id in readiness_task_ids
        )
        or len(readiness_task_ids) != len(set(readiness_task_ids))
        or len(suite_by_id) != len(suite_tasks)
        or set(suite_by_id) != set(readiness_task_ids)
    ):
        raise ValueError("temporal suite task set differs from the frozen readiness")
    formal_resource_id = readiness["formal_resource"]["resource_id"]
    for task_id, task in tasks.items():
        stable_task_id = task["task_id"]
        frozen = frozen_resources[task_id]
        if task["formal_resource_id"] != frozen.get("resource_id"):
            raise ValueError(f"task resource id drift: {task_id}")
        if task["formal_resource_id"] != formal_resource_id:
            raise ValueError(
                f"task is not bound to the formal cohort resource: {task_id}"
            )
        if task["formal_gpu_uuids"] != frozen.get("gpu_uuids"):
            raise ValueError(f"task GPU UUID drift: {task_id}")
        if len(task["formal_gpu_uuids"]) != frozen.get("required_gpu_count"):
            raise ValueError(f"task GPU count does not match UUID lock: {task_id}")
        check(task["intake"], f"{task_id} intake")
        task_packet_path = check(task["task_packet"], f"{task_id} task packet")
        assert task_packet_path is not None
        suite_packet = suite_by_id[stable_task_id].get("packet")
        if not isinstance(suite_packet, dict):
            raise ValueError(f"temporal suite has no task packet: {task_id}")
        suite_packet_path = validate_identity(
            suite_path.parent, suite_packet, f"temporal-suite task packet {task_id}"
        )
        identities += 1
        if suite_packet_path != task_packet_path or suite_packet.get("sha256") != task[
            "task_packet"
        ].get("sha256"):
            raise ValueError(
                f"task packet identity differs from the temporal suite: {task_id}"
            )
        check(task["bounded_supervisor"], f"{task_id} bounded supervisor")
        if task.get("target_access_preflight") is not None:
            check(task["target_access_preflight"], f"{task_id} target access preflight")
        materialization = task.get("weight_materialization", {})
        if "path" in materialization and "sha256" in materialization:
            check(materialization, f"{task_id} weight materialization")
        for role, value in materialization.items():
            if isinstance(value, dict) and "path" in value and "sha256" in value:
                check(value, f"{task_id} {role} materialization")

    lock = readiness["environment_lock"]
    check(lock["capture_script"], "live-lock capture script")
    check(lock["latest_attempt"], "latest live-lock attempt")
    check(lock["live_gpu_uuid_lock"], "live GPU UUID lock")
    check(lock["live_package_lock"], "live package lock")

    if readiness["authorization"]["gpu_dispatch_authorized"]:
        raise ValueError(
            "a pre-GPU readiness artifact must not grant dispatch authorization"
        )
    if (
        readiness["execution"]["compile_started"]
        or readiness["execution"]["gpu_started"]
    ):
        raise ValueError("pre-GPU evidence was written after compile/GPU execution")
    if readiness["execution"]["gpu_seconds"] != 0:
        raise ValueError("pre-GPU evidence reports nonzero GPU time")

    blockers = blocker_count(readiness["remaining_pre_gpu_blockers"])
    state = readiness["state"]
    eligible = readiness["eligible_to_execute_arms"]
    if state == "PRE_GPU_GATE_BLOCKED":
        if eligible or blockers == 0:
            raise ValueError("BLOCKED requires eligible=false and at least one blocker")
    else:
        if not eligible or blockers != 0:
            raise ValueError("READY requires eligible=true and zero blockers")
        if readiness["formal_resource"]["state"] != "AUTHENTICATED":
            raise ValueError("READY requires an authenticated formal cohort resource")
        if lock["live_gpu_uuid_lock"] is None or lock["live_package_lock"] is None:
            raise ValueError("READY requires hash-bound live GPU and package locks")
        if not readiness["authorization"]["operator_workload_hardware_intake_frozen"]:
            raise ValueError("READY requires frozen operator/workload/hardware intake")
        for task_id, task in tasks.items():
            if task["preflight_status"] != "PASS":
                raise ValueError(f"READY requires a passing live preflight: {task_id}")
            if not weight_complete(task):
                raise ValueError(f"READY requires complete frozen weights: {task_id}")

    return {
        "status": "PASS",
        "cycle_id": readiness["cycle_id"],
        "state": state,
        "eligible_to_execute_arms": eligible,
        "formal_resource_id": formal_resource_id,
        "task_count": len(tasks),
        "validated_identities": identities,
        "blocker_count": blockers,
        "gpu_dispatch_authorized": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--readiness", required=True, type=Path)
    parser.add_argument("--artifact-root", required=True, type=Path)
    args = parser.parse_args()
    result = validate_readiness(args.readiness, args.artifact_root)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
