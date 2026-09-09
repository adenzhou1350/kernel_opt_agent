#!/usr/bin/env python3
"""Validate a resource-only amendment without mutating a frozen cohort."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from community_knowledge import read_object, sha256_file
from community_pre_gpu_readiness import validate_readiness
from schema_utils import validate_json_file

SCHEMA = "community_resource_amendment.schema.json"
SAFE_POINTER_TERMS = (
    "resource",
    "endpoint",
    "gpu",
    "device",
    "hardware",
    "packet",
    "server-contract",
    "server_contract",
    "sealed-argv",
    "sealed_argv",
    "environment",
    "memory_query_argv",
)


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def resolve_inside(root: Path, relative: str) -> Path:
    root = root.resolve()
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise ValueError(f"identity escapes artifact root: {relative}") from error
    return path


def checked_identity(root: Path, identity: dict, label: str) -> Path:
    path = resolve_inside(root, identity["path"])
    if not path.is_file():
        raise FileNotFoundError(f"{label} missing: {path}")
    if sha256_file(path) != identity["sha256"]:
        raise ValueError(f"{label} hash changed: {identity['path']}")
    return path


def pointer_token(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def differences(left: object, right: object, pointer: str = "") -> set[str]:
    if type(left) is not type(right):
        return {pointer or "/"}
    if isinstance(left, dict):
        changed: set[str] = set()
        for key in set(left) | set(right):
            child = f"{pointer}/{pointer_token(str(key))}"
            if key not in left or key not in right:
                changed.add(child)
            else:
                changed |= differences(left[key], right[key], child)
        return changed
    if isinstance(left, list):
        if len(left) != len(right):
            return {pointer or "/"}
        changed: set[str] = set()
        for index, (a, b) in enumerate(zip(left, right, strict=True)):
            changed |= differences(a, b, f"{pointer}/{index}")
        return changed
    return set() if left == right else {pointer or "/"}


def allowed(pointer: str, prefixes: list[str]) -> bool:
    return any(pointer == prefix or pointer.startswith(prefix + "/") for prefix in prefixes)


def validate_amendment(path: Path, artifact_root: Path) -> dict:
    repo = repository_root()
    errors = validate_json_file(path, repo / "schemas" / SCHEMA)
    if errors:
        raise ValueError("invalid resource amendment schema: " + "; ".join(errors))
    amendment = read_object(path)
    artifact_root = artifact_root.resolve()
    original_root = resolve_inside(
        artifact_root, amendment["original_artifact_root"]
    )
    effective_root = resolve_inside(
        artifact_root, amendment["effective_artifact_root"]
    )
    if original_root == effective_root:
        raise ValueError("original and effective artifact roots must be distinct")
    readiness_path = checked_identity(
        artifact_root, amendment["original_readiness"], "original readiness"
    )
    readiness = read_object(readiness_path)
    canonical_readiness = validate_readiness(readiness_path, readiness_path.parent)
    feasibility = read_object(
        checked_identity(
            artifact_root, amendment["feasibility_audit"], "feasibility audit"
        )
    )
    if (
        readiness.get("cycle_id") != amendment["cycle_id"]
        or feasibility.get("cycle_id") != amendment["cycle_id"]
    ):
        raise ValueError("cycle identity mismatch")
    if (
        readiness.get("state") != "PRE_GPU_GATE_BLOCKED"
        or readiness.get("eligible_to_execute_arms") is not False
        or canonical_readiness.get("state") != "PRE_GPU_GATE_BLOCKED"
        or canonical_readiness.get("eligible_to_execute_arms") is not False
    ):
        raise ValueError("original readiness must be fail-closed")
    if (
        feasibility.get("decision")
        != "RESOURCE_CAPACITY_COMPATIBLE_MIGRATION_NOT_YET_EXECUTION_READY"
    ):
        raise ValueError("feasibility audit does not permit a resource amendment")
    old = amendment["old_resource"]
    new = amendment["new_resource"]
    if old == new or set(old["gpu_uuids"]) & set(new["gpu_uuids"]):
        raise ValueError("old and new resources must be distinct")
    prefixes = amendment["allowed_resource_pointers"]
    unsafe_prefixes = [
        value
        for value in prefixes
        if value == "/"
        or not any(term in value.lower() for term in SAFE_POINTER_TERMS)
    ]
    if unsafe_prefixes:
        raise ValueError(
            f"allowlist contains non-resource pointers: {sorted(unsafe_prefixes)}"
        )
    labels: set[str] = set()
    all_differences: dict[str, list[str]] = {}
    effective_texts: list[str] = []
    for item in amendment["closure"]:
        if item["label"] in labels:
            raise ValueError(f"duplicate closure label: {item['label']}")
        labels.add(item["label"])
        original_path = checked_identity(
            artifact_root, item["original"], f"{item['label']} original"
        )
        effective_path = checked_identity(
            artifact_root, item["effective"], f"{item['label']} effective"
        )
        try:
            original_path.relative_to(original_root)
            effective_path.relative_to(effective_root)
        except ValueError as error:
            raise ValueError(
                f"closure path is outside its declared artifact root: {item['label']}"
            ) from error
        original = read_object(original_path)
        effective = read_object(effective_path)
        changed = sorted(differences(original, effective))
        if any(not allowed(value, prefixes) for value in changed):
            raise ValueError(f"non-resource drift in {item['label']}: {changed}")
        all_differences[item["label"]] = changed
        effective_texts.append(json.dumps(effective, sort_keys=True))
    task_ids = set(readiness.get("task_freezes", {}))
    required_labels = {"temporal-suite", "environment"}
    for task_id in task_ids:
        required_labels |= {
            f"task-packet:{task_id}",
            f"server-contract:{task_id}",
            f"sealed-argv:{task_id}",
        }
    if not task_ids or labels != required_labels:
        raise ValueError(
            "effective closure labels differ from the complete task resource closure: "
            f"expected={sorted(required_labels)} actual={sorted(labels)}"
        )
    combined = "\n".join(effective_texts)
    stale = [old["endpoint"], old["resource_id"], *old["gpu_uuids"]]
    found = sorted(value for value in stale if value in combined)
    if found:
        raise ValueError(f"effective closure retains old resource identities: {found}")
    required_new = [new["endpoint"], new["resource_id"], *new["gpu_uuids"]]
    if not all(value in combined for value in required_new):
        raise ValueError("effective closure does not bind every new resource identity")
    return {
        "status": "PASS_RESOURCE_ONLY_AMENDMENT",
        "cycle_id": amendment["cycle_id"],
        "closure_items": len(labels),
        "differences": all_differences,
        "gpu_dispatch_authorized": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--amendment", required=True, type=Path)
    parser.add_argument("--artifact-root", required=True, type=Path)
    args = parser.parse_args()
    result = validate_amendment(args.amendment, args.artifact_root)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
