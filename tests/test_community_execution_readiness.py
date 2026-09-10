#!/usr/bin/env python3
"""Exercise the supplemental community execution-contract gate."""

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

from community_execution_readiness import validate_execution_readiness  # noqa: E402
from community_knowledge import sha256_file  # noqa: E402


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def identity(path: Path, base: Path) -> dict:
    return {"path": path.relative_to(base).as_posix(), "sha256": sha256_file(path)}


def build_fixture(base: Path) -> tuple[Path, dict]:
    evidence = base / "evidence.json"
    write_json(evidence, {"status": "PASS"})
    task_files: dict[str, dict[str, Path]] = {}
    task_freezes = {}
    for key in ("task-a", "task-b"):
        files = {}
        for name in ("workload", "runner", "argv", "output-schema"):
            path = base / key / f"{name}.json"
            write_json(path, {"name": name})
            files[name] = path
        manifest = base / key / "harness.json"
        stable_id = f"stable-{key}"
        write_json(manifest, {"task_id": stable_id})
        files["manifest"] = manifest
        task_files[key] = files
        task_freezes[key] = {"task_id": stable_id}
    readiness = base / "readiness.json"
    write_json(readiness, {"cycle_id": "cycle-1", "task_freezes": task_freezes})

    tasks = {}
    for key, files in task_files.items():
        tasks[key] = {
            "task_id": task_freezes[key]["task_id"],
            "harness_manifest": identity(files["manifest"], base),
            "workload": identity(files["workload"], base),
            "runner": identity(files["runner"], base),
            "sealed_argv": identity(files["argv"], base),
            "output_schema": identity(files["output-schema"], base),
            "required_capabilities": ["CASE_COVERAGE", "METRIC_OUTPUTS"],
            "capability_checks": {
                "CASE_COVERAGE": {
                    "status": "PASS",
                    "evidence": identity(evidence, base),
                },
                "METRIC_OUTPUTS": {
                    "status": "PASS",
                    "evidence": identity(evidence, base),
                },
            },
        }
    gate = {
        "schema_version": "community-execution-readiness-v1",
        "generated_at": "2026-09-09T00:00:00Z",
        "cycle_id": "cycle-1",
        "state": "EXECUTION_CONTRACT_READY",
        "claim_boundary": "STATIC_EXECUTION_CONTRACT_GATE_NOT_EXECUTION_NOT_CORRECTNESS_OR_PERFORMANCE_EVIDENCE",
        "validator_binding": {
            "repository_commit": subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip(),
            "schema_sha256": sha256_file(
                ROOT / "schemas" / "community_execution_readiness.schema.json"
            ),
            "validator_sha256": sha256_file(
                ROOT / "scripts" / "community_execution_readiness.py"
            ),
        },
        "base_readiness": identity(readiness, base),
        "technical_amendment": {
            "amendment_id": "common-harness-repair-v1",
            "applies_to_arms": ["CONTROL", "COMMUNITY_AUGMENTED"],
            "same_harness_workload_metrics_across_arms": True,
            "frozen_dimensions_unchanged": {
                "task_identity": True,
                "workload": True,
                "schedule": True,
                "metric_weights": True,
                "hidden_solution_boundary": True,
            },
        },
        "tasks": tasks,
        "remaining_blockers": [],
        "eligible_by_this_gate": True,
        "gpu_dispatch_authorized": False,
        "hidden_oracle_exposed": False,
        "execution": {
            "compile_started": False,
            "gpu_started": False,
            "gpu_seconds": 0.0,
        },
    }
    gate_path = base / "gate.json"
    write_json(gate_path, gate)
    return gate_path, gate


def test_execution_readiness_requires_semantic_full_harness_canary() -> None:
    with tempfile.TemporaryDirectory() as temp:
        base = Path(temp)
        gate_path, ready = build_fixture(base)
        ready["tasks"]["task-a"]["required_capabilities"].append("FULL_HARNESS_DRY_RUN")
        ready["tasks"]["task-a"]["capability_checks"]["FULL_HARNESS_DRY_RUN"] = {
            "status": "PASS",
            "evidence": ready["tasks"]["task-a"]["capability_checks"]["CASE_COVERAGE"][
                "evidence"
            ],
        }
        write_json(gate_path, ready)
        with pytest.raises(ValueError, match="invalid full-harness canary schema"):
            validate_execution_readiness(gate_path, base)


def test_execution_readiness_is_hash_bound_and_fail_closed() -> None:
    with tempfile.TemporaryDirectory() as temp:
        base = Path(temp)
        gate_path, ready = build_fixture(base)
        result = validate_execution_readiness(gate_path, base)
        assert result["state"] == "EXECUTION_CONTRACT_READY"
        assert result["eligible_by_this_gate"] is True
        assert result["passed_capabilities"] == 4

        missing_evidence = copy.deepcopy(ready)
        missing_evidence["tasks"]["task-a"]["capability_checks"]["CASE_COVERAGE"][
            "evidence"
        ] = None
        write_json(gate_path, missing_evidence)
        with pytest.raises(ValueError, match="PASS capability lacks bound evidence"):
            validate_execution_readiness(gate_path, base)

        incomplete_checks = copy.deepcopy(ready)
        del incomplete_checks["tasks"]["task-a"]["capability_checks"]["METRIC_OUTPUTS"]
        write_json(gate_path, incomplete_checks)
        with pytest.raises(ValueError, match="capability checks differ"):
            validate_execution_readiness(gate_path, base)

        missing_binding = copy.deepcopy(ready)
        missing_binding["tasks"]["task-a"]["output_schema"] = None
        write_json(gate_path, missing_binding)
        with pytest.raises(ValueError, match="complete runner/argv/output bindings"):
            validate_execution_readiness(gate_path, base)

        blocked = copy.deepcopy(ready)
        blocked["state"] = "EXECUTION_CONTRACT_BLOCKED"
        blocked["eligible_by_this_gate"] = False
        blocked["remaining_blockers"] = ["task-a: output schema incomplete"]
        blocked["tasks"]["task-a"]["output_schema"] = None
        blocked["tasks"]["task-a"]["capability_checks"]["METRIC_OUTPUTS"] = {
            "status": "BLOCKED",
            "evidence": None,
        }
        write_json(gate_path, blocked)
        result = validate_execution_readiness(gate_path, base)
        assert result["state"] == "EXECUTION_CONTRACT_BLOCKED"
        assert result["missing_execution_bindings"] == 1
        assert result["blocked_capabilities"] == 1

        changed_workload = Path(base / "task-a" / "workload.json")
        write_json(changed_workload, {"name": "changed"})
        with pytest.raises(ValueError, match="workload hash changed"):
            validate_execution_readiness(gate_path, base)
