#!/usr/bin/env python3
"""Validate a model mirror by exact executor-visible payload identity."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from community_knowledge import read_object, sha256_file
from schema_utils import validate_json_file

SCHEMA = "community_model_source_amendment.schema.json"
SENSITIVE_NAMES = {
    "config.json",
    "configuration.json",
    "generation_config.json",
    "model.safetensors.index.json",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer_config.json",
}
SENSITIVE_SUFFIXES = {
    ".bin",
    ".dll",
    ".dylib",
    ".gguf",
    ".model",
    ".pt",
    ".pth",
    ".py",
    ".safetensors",
    ".so",
}


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def resolve_inside(root: Path, relative: str) -> Path:
    root = root.resolve()
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise ValueError(f"path escapes artifact root: {relative}") from error
    return path


def normalized_relative(value: str) -> str:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"unsafe relative path: {value}")
    normalized = path.as_posix()
    if normalized in {"", "."} or normalized != value.replace("\\", "/"):
        raise ValueError(f"non-canonical relative path: {value}")
    return normalized


def executor_sensitive(path: str) -> bool:
    value = Path(path)
    return value.name in SENSITIVE_NAMES or value.suffix.lower() in SENSITIVE_SUFFIXES


def checked_file(root: Path, row: dict, label: str) -> None:
    relative = normalized_relative(row["path"])
    path = resolve_inside(root, relative)
    if path.is_symlink():
        raise ValueError(f"{label} must not be a symlink: {relative}")
    if not path.is_file():
        raise FileNotFoundError(f"{label} missing: {relative}")
    if path.stat().st_size != row["bytes"]:
        raise ValueError(f"{label} byte count changed: {relative}")
    if sha256_file(path) != row["sha256"]:
        raise ValueError(f"{label} hash changed: {relative}")


def validate_source(artifact_root: Path, source: dict, label: str) -> dict[str, dict]:
    source_root = resolve_inside(artifact_root, source["root"])
    if not source_root.is_dir():
        raise FileNotFoundError(f"{label} source root missing: {source['root']}")
    executor: dict[str, dict] = {}
    excluded: dict[str, dict] = {}
    for row in source["executor_inventory"]:
        relative = normalized_relative(row["path"])
        if relative in executor:
            raise ValueError(f"duplicate {label} executor path: {relative}")
        checked_file(source_root, row, f"{label} executor file")
        executor[relative] = row
    for row in source["excluded_files"]:
        relative = normalized_relative(row["path"])
        if relative in excluded or relative in executor:
            raise ValueError(f"duplicate or overlapping {label} path: {relative}")
        if executor_sensitive(relative):
            raise ValueError(
                f"executor-sensitive file cannot be excluded in {label}: {relative}"
            )
        checked_file(source_root, row, f"{label} excluded file")
        excluded[relative] = row
    actual: set[str] = set()
    for path in source_root.rglob("*"):
        if path.is_symlink():
            raise ValueError(
                f"{label} source contains a symlink: "
                f"{path.relative_to(source_root).as_posix()}"
            )
        if path.is_file():
            actual.add(path.relative_to(source_root).as_posix())
    declared = set(executor) | set(excluded)
    if actual != declared:
        missing = sorted(declared - actual)
        unexpected = sorted(actual - declared)
        raise ValueError(
            f"{label} inventory is not complete: missing={missing} "
            f"unexpected={unexpected}"
        )
    return executor


def executor_digest(inventory: dict[str, dict]) -> str:
    payload = [
        {
            "path": path,
            "bytes": inventory[path]["bytes"],
            "sha256": inventory[path]["sha256"],
        }
        for path in sorted(inventory)
    ]
    encoded = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_amendment(path: Path, artifact_root: Path) -> dict:
    repo = repository_root()
    errors = validate_json_file(path, repo / "schemas" / SCHEMA)
    if errors:
        raise ValueError("invalid model source amendment schema: " + "; ".join(errors))
    amendment = read_object(path)
    artifact_root = artifact_root.resolve()
    original = amendment["original_source"]
    replacement = amendment["replacement_source"]
    if resolve_inside(artifact_root, original["root"]) == resolve_inside(
        artifact_root, replacement["root"]
    ):
        raise ValueError("original and replacement roots must be distinct")
    if original == replacement:
        raise ValueError("replacement source must differ from original source metadata")
    original_inventory = validate_source(artifact_root, original, "original")
    replacement_inventory = validate_source(artifact_root, replacement, "replacement")
    if set(original_inventory) != set(replacement_inventory):
        raise ValueError(
            "executor-visible path set differs: "
            f"missing={sorted(set(original_inventory) - set(replacement_inventory))} "
            f"unexpected={sorted(set(replacement_inventory) - set(original_inventory))}"
        )
    mismatches = []
    for relative in sorted(original_inventory):
        before = original_inventory[relative]
        after = replacement_inventory[relative]
        if (before["bytes"], before["sha256"]) != (
            after["bytes"],
            after["sha256"],
        ):
            mismatches.append(relative)
    if mismatches:
        raise ValueError(f"executor-visible content differs: {mismatches}")
    digest = executor_digest(original_inventory)
    if digest != executor_digest(replacement_inventory):
        raise ValueError("executor inventory digest differs")
    return {
        "status": "PASS_MODEL_SOURCE_CONTENT_EQUIVALENCE",
        "cycle_id": amendment["cycle_id"],
        "task_id": amendment["task_id"],
        "component": amendment["component"],
        "logical_model_id": amendment["logical_model_id"],
        "executor_files": len(original_inventory),
        "executor_payload_sha256": digest,
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
