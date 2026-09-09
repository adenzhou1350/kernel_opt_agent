#!/usr/bin/env python3
"""Validate a model mirror by exact executor-visible payload identity."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from community_knowledge import read_object, sha256_file
from schema_utils import validate_json_file

SCHEMAS = {
    "community-model-source-amendment-v1": (
        "community_model_source_amendment.schema.json"
    ),
    "community-model-source-amendment-v2": (
        "community_model_source_amendment_v2.schema.json"
    ),
}
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


def checked_identity(root: Path, row: dict, label: str) -> Path:
    relative = normalized_relative(row["path"])
    path = resolve_inside(root, relative)
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{label} missing or unsafe: {relative}")
    if sha256_file(path) != row["sha256"]:
        raise ValueError(f"{label} hash changed: {relative}")
    return path


def git_blob_sha1(path: Path) -> str:
    content = path.read_bytes()
    header = f"blob {len(content)}\0".encode()
    return hashlib.sha1(header + content).hexdigest()  # noqa: S324


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


def validate_metadata_source(
    artifact_root: Path, source: dict
) -> tuple[dict[str, dict], str]:
    metadata_path = checked_identity(
        artifact_root, source["metadata_evidence"], "original metadata evidence"
    )
    metadata = read_object(metadata_path)
    if (
        metadata.get("id") != source["repository"]
        or metadata.get("sha") != source["revision"]
    ):
        raise ValueError("metadata repository or revision identity mismatch")
    siblings = metadata.get("siblings")
    if not isinstance(siblings, list):
        raise ValueError("metadata siblings must be a list")
    remote: dict[str, dict] = {}
    for row in siblings:
        if not isinstance(row, dict) or not isinstance(row.get("rfilename"), str):
            raise ValueError("metadata contains an invalid sibling")
        relative = normalized_relative(row["rfilename"])
        if relative in remote:
            raise ValueError(f"metadata contains duplicate path: {relative}")
        remote[relative] = row
    executor: dict[str, dict] = {}
    for row in source["executor_inventory"]:
        relative = normalized_relative(row["path"])
        if relative in executor:
            raise ValueError(f"duplicate original executor path: {relative}")
        kind = row["identity_kind"]
        digest = row["digest"]
        if (kind == "GIT_BLOB_SHA1" and len(digest) != 40) or (
            kind == "LFS_SHA256" and len(digest) != 64
        ):
            raise ValueError(f"digest length does not match identity kind: {relative}")
        sibling = remote.get(relative)
        if sibling is None or sibling.get("size") != row["bytes"]:
            raise ValueError(f"metadata file identity mismatch: {relative}")
        lfs = sibling.get("lfs")
        if kind == "LFS_SHA256":
            if not isinstance(lfs, dict) or (
                lfs.get("sha256") != digest or lfs.get("size") != row["bytes"]
            ):
                raise ValueError(f"metadata LFS identity mismatch: {relative}")
        elif lfs is not None or sibling.get("blobId") != digest:
            raise ValueError(f"metadata Git blob identity mismatch: {relative}")
        executor[relative] = row
    excluded: set[str] = set()
    for row in source["excluded_paths"]:
        relative = normalized_relative(row["path"])
        if relative in excluded or relative in executor:
            raise ValueError(f"duplicate or overlapping original path: {relative}")
        if executor_sensitive(relative):
            alternate = row[
                "category"
            ] == "NON_EXECUTOR_ALTERNATE_FORMAT" and relative.startswith("original/")
            if not alternate:
                raise ValueError(
                    "executor-sensitive metadata path cannot be excluded: " + relative
                )
        excluded.add(relative)
    if set(remote) != set(executor) | excluded:
        raise ValueError(
            "original metadata inventory is not complete: "
            f"missing={sorted((set(executor) | excluded) - set(remote))} "
            f"unexpected={sorted(set(remote) - set(executor) - excluded)}"
        )
    return executor, source["metadata_evidence"]["sha256"]


def validate_metadata_amendment(amendment: dict, artifact_root: Path) -> dict:
    original = amendment["original_source"]
    replacement = amendment["replacement_source"]
    original_inventory, metadata_sha = validate_metadata_source(artifact_root, original)
    replacement_inventory = validate_source(artifact_root, replacement, "replacement")
    if set(original_inventory) != set(replacement_inventory):
        raise ValueError(
            "executor-visible path set differs: "
            f"missing={sorted(set(original_inventory) - set(replacement_inventory))} "
            f"unexpected={sorted(set(replacement_inventory) - set(original_inventory))}"
        )
    replacement_root = resolve_inside(artifact_root, replacement["root"])
    mismatches = []
    digest_rows = []
    for relative in sorted(original_inventory):
        before = original_inventory[relative]
        after = replacement_inventory[relative]
        path = resolve_inside(replacement_root, relative)
        if before["bytes"] != after["bytes"]:
            mismatches.append(relative)
            continue
        actual = (
            after["sha256"]
            if before["identity_kind"] == "LFS_SHA256"
            else git_blob_sha1(path)
        )
        if actual != before["digest"]:
            mismatches.append(relative)
        digest_rows.append(
            {
                "path": relative,
                "bytes": after["bytes"],
                "sha256": after["sha256"],
            }
        )
    if mismatches:
        raise ValueError(f"executor-visible content differs: {mismatches}")
    payload = json.dumps(
        digest_rows, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return {
        "status": "PASS_MODEL_SOURCE_METADATA_ATTESTED_CONTENT_EQUIVALENCE",
        "cycle_id": amendment["cycle_id"],
        "task_id": amendment["task_id"],
        "component": amendment["component"],
        "logical_model_id": amendment["logical_model_id"],
        "original_metadata_sha256": metadata_sha,
        "executor_files": len(original_inventory),
        "executor_payload_sha256": hashlib.sha256(payload).hexdigest(),
        "gpu_dispatch_authorized": False,
    }


def validate_amendment(path: Path, artifact_root: Path) -> dict:
    repo = repository_root()
    amendment = read_object(path)
    schema_name = SCHEMAS.get(amendment.get("schema_version"))
    if schema_name is None:
        raise ValueError("unsupported model source amendment schema version")
    errors = validate_json_file(path, repo / "schemas" / schema_name)
    if errors:
        raise ValueError("invalid model source amendment schema: " + "; ".join(errors))
    artifact_root = artifact_root.resolve()
    if amendment["schema_version"] == "community-model-source-amendment-v2":
        return validate_metadata_amendment(amendment, artifact_root)
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
