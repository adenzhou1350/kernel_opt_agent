#!/usr/bin/env python3
"""Exercise fail-closed pre-GPU readiness and frozen resource identity gates."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from community_knowledge import sha256_file  # noqa: E402
from community_pre_gpu_readiness import validate_readiness  # noqa: E402


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def identity(path: Path, base: Path) -> dict:
    return {"path": path.relative_to(base).as_posix(), "sha256": sha256_file(path)}


def build_fixture(base: Path) -> tuple[Path, dict]:
    dummy_paths = {}
    for name in (
        "previous",
        "suite",
        "intake-a",
        "intake-b",
        "packet-a",
        "packet-b",
        "supervisor-a",
        "supervisor-b",
        "capture",
        "attempt",
        "weight-a",
        "weight-b",
        "gpu-lock",
        "package-lock",
    ):
        path = base / f"{name}.json"
        write_json(path, {"name": name})
        dummy_paths[name] = path
    environment_path = base / "environment.json"
    write_json(
        environment_path,
        {
            "resources": {
                "task-a": {
                    "resource_id": "shared-sm120",
                    "gpu_uuids": ["GPU-a", "GPU-b"],
                    "required_gpu_count": 2,
                },
                "task-b": {
                    "resource_id": "shared-sm120",
                    "gpu_uuids": ["GPU-a"],
                    "required_gpu_count": 1,
                },
            }
        },
    )
    write_json(
        dummy_paths["suite"],
        {
            "protocol": {
                "environment_identity": identity(environment_path, base),
            },
            "tasks": [
                {
                    "task_id": "task-a",
                    "packet": identity(dummy_paths["packet-a"], base),
                },
                {
                    "task_id": "task-b",
                    "packet": identity(dummy_paths["packet-b"], base),
                },
            ],
        },
    )
    current_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    task_a = {
        "task_id": "task-a",
        "intake": identity(dummy_paths["intake-a"], base),
        "task_packet": identity(dummy_paths["packet-a"], base),
        "formal_resource_id": "shared-sm120",
        "formal_gpu_uuids": ["GPU-a", "GPU-b"],
        "preflight_status": "NOT_RUN",
        "weight_materialization": {
            "pair_complete": False,
            "target": {"state": "NOT_MATERIALIZED"},
            "drafter": {
                **identity(dummy_paths["weight-a"], base),
                "state": "COMPLETE_HASH_VERIFIED",
            },
        },
        "bounded_supervisor": identity(dummy_paths["supervisor-a"], base),
    }
    task_b = {
        "task_id": "task-b",
        "intake": identity(dummy_paths["intake-b"], base),
        "task_packet": identity(dummy_paths["packet-b"], base),
        "formal_resource_id": "shared-sm120",
        "formal_gpu_uuids": ["GPU-a"],
        "preflight_status": "NOT_RUN",
        "weight_materialization": {
            **identity(dummy_paths["weight-b"], base),
            "state": "COMPLETE_HASH_VERIFIED",
        },
        "bounded_supervisor": identity(dummy_paths["supervisor-b"], base),
    }
    readiness = {
        "schema_version": "meta-cycle-materialization-readiness-v6",
        "generated_at": "2026-09-09T00:00:00Z",
        "cycle_id": "cycle-1",
        "state": "PRE_GPU_GATE_BLOCKED",
        "eligible_to_execute_arms": False,
        "claim_boundary": "PRE_GPU_ONLY",
        "supersedes": identity(dummy_paths["previous"], base),
        "cohort_binding": {
            "cohort_freeze_sha256": "0" * 64,
            "primary_tasks": ["task-a", "task-b"],
            "reserve_touched": False,
        },
        "protocol_binding": {
            "frozen_discovery_and_arm_protocol_commit": current_commit,
            "governance_validator_commit": current_commit,
            "temporal_suite": identity(dummy_paths["suite"], base),
        },
        "formal_resource": {
            "environment": identity(environment_path, base),
            "resource_id": "shared-sm120",
            "endpoint": "shared.example:22",
            "state": "UNREACHABLE",
        },
        "task_freezes": {"task-a": task_a, "task-b": task_b},
        "environment_lock": {
            "capture_script": identity(dummy_paths["capture"], base),
            "latest_attempt": identity(dummy_paths["attempt"], base),
            "live_gpu_uuid_lock": None,
            "live_package_lock": None,
        },
        "authorization": {
            "operator_workload_hardware_intake_frozen": True,
            "gpu_dispatch_authorized": False,
        },
        "remaining_pre_gpu_blockers": {"shared": ["resource unavailable"]},
        "execution": {
            "compile_started": False,
            "gpu_started": False,
            "gpu_seconds": 0.0,
            "v9_started": False,
        },
        "hidden_oracle_exposed": False,
        "shared_default_promotion": "NOT_AUTHORIZED",
    }
    readiness_path = base / "readiness.json"
    write_json(readiness_path, readiness)
    return readiness_path, readiness


def test_pre_gpu_readiness_fail_closed_and_resource_bound() -> None:
    with tempfile.TemporaryDirectory() as temp:
        base = Path(temp)
        readiness_path, blocked = build_fixture(base)
        result = validate_readiness(readiness_path, base)
        assert result["state"] == "PRE_GPU_GATE_BLOCKED"
        assert result["eligible_to_execute_arms"] is False
        assert result["blocker_count"] == 1

        drifted = copy.deepcopy(blocked)
        drifted["task_freezes"]["task-b"]["formal_gpu_uuids"] = ["GPU-other"]
        write_json(readiness_path, drifted)
        with pytest.raises(ValueError, match="GPU UUID drift"):
            validate_readiness(readiness_path, base)

        unavailable_commit = copy.deepcopy(blocked)
        unavailable_commit["protocol_binding"]["governance_validator_commit"] = "f" * 40
        write_json(readiness_path, unavailable_commit)
        with pytest.raises(ValueError, match="governance commit is unavailable"):
            validate_readiness(readiness_path, base)

        wrong_suite_packet = copy.deepcopy(blocked)
        wrong_suite_packet["task_freezes"]["task-b"]["task_packet"] = identity(
            base / "packet-a.json", base
        )
        write_json(readiness_path, wrong_suite_packet)
        with pytest.raises(ValueError, match="task packet identity differs"):
            validate_readiness(readiness_path, base)

        wrong_suite_environment = copy.deepcopy(blocked)
        alternate_environment = base / "alternate-environment.json"
        write_json(
            alternate_environment,
            json.loads((base / "environment.json").read_text()),
        )
        suite = json.loads((base / "suite.json").read_text())
        suite["protocol"]["environment_identity"] = identity(
            alternate_environment, base
        )
        write_json(base / "suite.json", suite)
        wrong_suite_environment["protocol_binding"]["temporal_suite"] = identity(
            base / "suite.json", base
        )
        write_json(readiness_path, wrong_suite_environment)
        with pytest.raises(ValueError, match="environment identity differs"):
            validate_readiness(readiness_path, base)

        write_json(
            base / "suite.json",
            {
                "protocol": {
                    "environment_identity": identity(base / "environment.json", base),
                },
                "tasks": [
                    {
                        "task_id": "task-a",
                        "packet": identity(base / "packet-a.json", base),
                    },
                    {
                        "task_id": "task-b",
                        "packet": identity(base / "packet-b.json", base),
                    },
                ],
            },
        )
        blocked["protocol_binding"]["temporal_suite"] = identity(
            base / "suite.json", base
        )

        premature = copy.deepcopy(blocked)
        premature["state"] = "PRE_GPU_GATE_READY"
        premature["eligible_to_execute_arms"] = True
        premature["remaining_pre_gpu_blockers"] = {"shared": []}
        write_json(readiness_path, premature)
        with pytest.raises(ValueError, match="authenticated formal cohort resource"):
            validate_readiness(readiness_path, base)

        ready = copy.deepcopy(premature)
        ready["formal_resource"]["state"] = "AUTHENTICATED"
        ready["environment_lock"]["live_gpu_uuid_lock"] = identity(
            base / "gpu-lock.json", base
        )
        ready["environment_lock"]["live_package_lock"] = identity(
            base / "package-lock.json", base
        )
        ready["task_freezes"]["task-a"]["preflight_status"] = "PASS"
        ready["task_freezes"]["task-a"]["weight_materialization"] = {
            **identity(base / "weight-a.json", base),
            "state": "COMPLETE_HASH_VERIFIED",
        }
        ready["task_freezes"]["task-b"]["preflight_status"] = "PASS"
        write_json(readiness_path, ready)
        result = validate_readiness(readiness_path, base)
        assert result["state"] == "PRE_GPU_GATE_READY"
        assert result["eligible_to_execute_arms"] is True
        assert result["gpu_dispatch_authorized"] is False

        conflated = copy.deepcopy(ready)
        conflated["authorization"]["gpu_dispatch_authorized"] = True
        write_json(readiness_path, conflated)
        with pytest.raises(ValueError, match="must not grant dispatch authorization"):
            validate_readiness(readiness_path, base)
