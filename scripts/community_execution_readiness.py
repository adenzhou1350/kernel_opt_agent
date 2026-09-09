#!/usr/bin/env python3
"""Validate a supplemental, fail-closed community execution-contract gate."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from community_knowledge import read_object, sha256_file
from schema_utils import validate_json_file


SCHEMA = "community_execution_readiness.schema.json"


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def resolve_inside(base: Path, relative: str) -> Path:
    base = base.resolve()
    path = (base / relative).resolve()
    try:
        path.relative_to(base)
    except ValueError as error:
        raise ValueError(f"identity path escapes the artifact root: {relative}") from error
    return path


def validate_identity(base: Path, value: dict, label: str) -> Path:
    path = resolve_inside(base, value["path"])
    if not path.is_file():
        raise FileNotFoundError(f"{label} is missing: {path}")
    if sha256_file(path) != value["sha256"]:
        raise ValueError(f"{label} hash changed: {value['path']}")
    return path


def validate_execution_readiness(gate_path: Path, artifact_root: Path) -> dict:
    root = repository_root()
    errors = validate_json_file(gate_path, root / "schemas" / SCHEMA)
    if errors:
        raise ValueError("invalid execution-readiness schema: " + "; ".join(errors))
    gate = read_object(gate_path)
    artifact_root = artifact_root.resolve()
    identities = 0

    binding = gate["validator_binding"]
    commit_check = subprocess.run(
        ["git", "cat-file", "-e", f"{binding['repository_commit']}^{{commit}}"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if commit_check.returncode != 0:
        raise ValueError("execution-readiness validator commit is unavailable")
    if sha256_file(root / "schemas" / SCHEMA) != binding["schema_sha256"]:
        raise ValueError("execution-readiness schema identity changed")
    if sha256_file(Path(__file__)) != binding["validator_sha256"]:
        raise ValueError("execution-readiness validator identity changed")

    def check(value: dict | None, label: str) -> Path | None:
        nonlocal identities
        if value is None:
            return None
        path = validate_identity(artifact_root, value, label)
        identities += 1
        return path

    base_path = check(gate["base_readiness"], "base pre-GPU readiness")
    assert base_path is not None
    base = read_object(base_path)
    if base.get("cycle_id") != gate["cycle_id"]:
        raise ValueError("supplemental gate cycle differs from base readiness")
    frozen_tasks = base.get("task_freezes")
    if not isinstance(frozen_tasks, dict) or not frozen_tasks:
        raise ValueError("base readiness has no frozen tasks")
    if set(gate["tasks"]) != set(frozen_tasks):
        raise ValueError("supplemental gate task keys differ from base readiness")

    passed = 0
    blocked = 0
    missing_bindings = 0
    for key, task in gate["tasks"].items():
        if task["task_id"] != frozen_tasks[key].get("task_id"):
            raise ValueError(f"stable task id differs from base readiness: {key}")
        manifest_path = check(task["harness_manifest"], f"{key} harness manifest")
        workload_path = check(task["workload"], f"{key} workload")
        assert manifest_path is not None and workload_path is not None
        manifest = read_object(manifest_path)
        if manifest.get("task_id") != task["task_id"]:
            raise ValueError(f"harness manifest task id differs: {key}")
        for name in ("runner", "sealed_argv", "output_schema"):
            if check(task[name], f"{key} {name.replace('_', ' ')}") is None:
                missing_bindings += 1
        required = set(task["required_capabilities"])
        checks = task["capability_checks"]
        if set(checks) != required:
            raise ValueError(f"capability checks differ from required set: {key}")
        for capability, result in checks.items():
            evidence = check(result["evidence"], f"{key} {capability} evidence")
            if result["status"] == "PASS":
                if evidence is None:
                    raise ValueError(f"PASS capability lacks bound evidence: {key}/{capability}")
                passed += 1
            else:
                blocked += 1

    state = gate["state"]
    eligible = gate["eligible_by_this_gate"]
    blockers = gate["remaining_blockers"]
    if state == "EXECUTION_CONTRACT_READY":
        if not eligible or blockers or blocked or missing_bindings:
            raise ValueError(
                "READY requires eligible=true, no blockers, all capabilities PASS, "
                "and complete runner/argv/output bindings"
            )
    elif eligible or not blockers:
        raise ValueError("BLOCKED requires eligible=false and at least one blocker")

    return {
        "status": "PASS",
        "cycle_id": gate["cycle_id"],
        "state": state,
        "eligible_by_this_gate": eligible,
        "task_count": len(gate["tasks"]),
        "validated_identities": identities,
        "passed_capabilities": passed,
        "blocked_capabilities": blocked,
        "missing_execution_bindings": missing_bindings,
        "gpu_dispatch_authorized": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gate", required=True, type=Path)
    parser.add_argument("--artifact-root", required=True, type=Path)
    args = parser.parse_args()
    result = validate_execution_readiness(args.gate, args.artifact_root)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
