#!/usr/bin/env python3
"""Discover explicit delivery-ready artifacts without authorizing publication."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

READY_PREFIX = "READY_TO_CREATE_"
READY_SUFFIX = "_PENDING_ACTION_CONFIRMATION"
SHA256_LENGTH = 64


def validate_manifest(manifest: Any) -> list[str]:
    """Validate the inbox fields needed for exact candidate registration."""
    if not isinstance(manifest, dict):
        return ["manifest must be an object"]
    version = manifest.get("schema_version")
    allowed_keys = {"schema_version", "observed_at", "candidates"}
    errors = [
        f"unexpected manifest field: {key}"
        for key in sorted(set(manifest) - allowed_keys)
    ]
    version_prefix = "upstream-delivery-inbox-v"
    version_suffix = (
        version.removeprefix(version_prefix)
        if isinstance(version, str) and version.startswith(version_prefix)
        else ""
    )
    if not version_suffix.isdigit() or int(version_suffix) < 1:
        errors.append("unsupported delivery inbox schema_version")
    try:
        parse_timestamp(manifest.get("observed_at"))
    except (TypeError, ValueError) as error:
        errors.append(str(error).replace("recorded_at", "observed_at"))
    candidates = manifest.get("candidates")
    if not isinstance(candidates, list):
        return [*errors, "candidates must be an array"]
    seen: set[str] = set()
    for index, candidate in enumerate(candidates):
        prefix = f"candidates[{index}]"
        if not isinstance(candidate, dict):
            errors.append(f"{prefix} must be an object")
            continue
        required = {"candidate_id", "lane_id", "review_state"}
        for key in sorted(required - set(candidate)):
            errors.append(f"{prefix} missing {key}")
        candidate_id = candidate.get("candidate_id")
        if not isinstance(candidate_id, str) or not candidate_id:
            errors.append(f"{prefix}.candidate_id must be a non-empty string")
        elif candidate_id in seen:
            errors.append(f"duplicate candidate_id: {candidate_id}")
        else:
            seen.add(candidate_id)
        if not isinstance(candidate.get("lane_id"), str) or not candidate.get(
            "lane_id"
        ):
            errors.append(f"{prefix}.lane_id must be a non-empty string")
        for binding_name in ("review_state", "review_handoff"):
            binding = candidate.get(binding_name)
            if binding_name == "review_handoff" and binding is None:
                continue
            if not isinstance(binding, dict) or set(binding) != {"path", "sha256"}:
                errors.append(
                    f"{prefix}.{binding_name} must contain only path and sha256"
                )
                continue
            if not isinstance(binding["path"], str) or not binding["path"]:
                errors.append(
                    f"{prefix}.{binding_name}.path must be a non-empty string"
                )
            digest = binding["sha256"]
            if not (
                isinstance(digest, str)
                and len(digest) == SHA256_LENGTH
                and all(character in "0123456789abcdef" for character in digest)
            ):
                errors.append(
                    f"{prefix}.{binding_name}.sha256 must be lowercase SHA-256"
                )
    return errors


def parse_timestamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise TypeError("recorded_at must be an RFC3339 string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("recorded_at timezone is required")
    return parsed


def is_readiness_filename(path: Path) -> bool:
    normalized = path.name.lower().replace("_", "-")
    return normalized.endswith(".json") and "upstream-delivery-readiness" in normalized


def paths_within(root: Path, max_depth: int, max_files: int) -> list[Path]:
    if not root.is_dir():
        raise ValueError(f"scan root is not a directory: {root}")
    paths: list[Path] = []
    root_depth = len(root.parts)
    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        directory_path = Path(directory)
        depth = len(directory_path.parts) - root_depth
        if depth >= max_depth:
            dirnames[:] = []
        else:
            dirnames[:] = sorted(
                name for name in dirnames if not (directory_path / name).is_symlink()
            )
        for filename in sorted(filenames):
            path = directory_path / filename
            if not is_readiness_filename(path):
                continue
            paths.append(path.resolve())
            if len(paths) > max_files:
                raise ValueError(f"scan exceeded max-files={max_files}")
    return sorted(set(paths))


def registered_candidate_ids(manifest_path: Path | None) -> set[str]:
    if manifest_path is None:
        return set()
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as error:
        raise ValueError(f"cannot read delivery inbox manifest: {error}") from error
    errors = validate_manifest(manifest)
    if errors:
        raise ValueError("invalid delivery inbox manifest: " + "; ".join(errors))
    return {item["candidate_id"] for item in manifest["candidates"]}


def readiness_item(
    path: Path, max_file_bytes: int
) -> tuple[dict[str, Any] | None, str]:
    try:
        raw = path.read_bytes()
    except OSError as error:
        return None, f"{path}: {error}"
    if len(raw) > max_file_bytes:
        return None, f"{path}: exceeds max-file-bytes={max_file_bytes}"
    try:
        value = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as error:
        return None, f"{path}: invalid JSON: {error}"
    if not isinstance(value, dict):
        return None, ""
    status = value.get("status")
    if not (
        isinstance(status, str)
        and status.startswith(READY_PREFIX)
        and status.endswith(READY_SUFFIX)
    ):
        return None, ""
    candidate_id = value.get("candidate") or value.get("candidate_id")
    source = value.get("source")
    pull_request = value.get("pull_request")
    if not (
        isinstance(candidate_id, str)
        and candidate_id
        and isinstance(source, dict)
        and isinstance(pull_request, dict)
    ):
        return None, f"{path}: ready signal lacks candidate/source/pull_request"
    branch = source.get("branch")
    commit = (
        source.get("commit") or source.get("candidate_commit") or source.get("head")
    )
    repository = pull_request.get("repository")
    base = pull_request.get("base")
    if repository is None and isinstance(base, str) and ":" in base:
        repository = base.split(":", 1)[0]
    if not all(isinstance(item, str) and item for item in (branch, commit, repository)):
        return None, f"{path}: ready signal lacks repository/branch/commit identity"
    timestamp_warning = ""
    recorded_value = value.get("recorded_at")
    try:
        recorded_at = parse_timestamp(recorded_value)
        recorded_at_normalized = recorded_at.isoformat()
        recorded_epoch = recorded_at.timestamp()
        timestamp_quality = "RFC3339_TIMEZONE_BOUND"
    except (TypeError, ValueError) as error:
        modified_at = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
        recorded_at_normalized = None
        recorded_epoch = modified_at.timestamp()
        timestamp_quality = "FILE_MTIME_FALLBACK"
        timestamp_warning = (
            f"{path}: {error}; retained as discovery-only with file-mtime ordering"
        )
    return (
        {
            "candidate_id": candidate_id,
            "repository": repository,
            "branch": branch,
            "commit": commit,
            "status": status,
            "recorded_at": recorded_value,
            "recorded_at_normalized": recorded_at_normalized,
            "timestamp_quality": timestamp_quality,
            "artifact": {
                "path": path.as_posix(),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "modified_at": datetime.fromtimestamp(
                    path.stat().st_mtime, timezone.utc
                ).isoformat(),
            },
            "_recorded_epoch": recorded_epoch,
        },
        timestamp_warning,
    )


def discover(
    roots: list[Path],
    manifest_path: Path | None = None,
    *,
    max_depth: int = 1,
    max_files: int = 10_000,
    max_file_bytes: int = 2 * 1024 * 1024,
) -> dict[str, Any]:
    if max_depth < 0 or max_files < 1 or max_file_bytes < 1:
        raise ValueError(
            "scan limits must be positive and max-depth must be non-negative"
        )
    registered = registered_candidate_ids(manifest_path)
    paths: set[Path] = set()
    for root in roots:
        paths.update(paths_within(root.resolve(), max_depth, max_files))
        if len(paths) > max_files:
            raise ValueError(f"scan exceeded max-files={max_files}")
    newest: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for path in sorted(paths):
        item, error = readiness_item(path, max_file_bytes)
        if error:
            errors.append(error)
        if item is None:
            continue
        previous = newest.get(item["candidate_id"])
        current_key = (item["_recorded_epoch"], item["artifact"]["path"])
        previous_key = (
            (previous["_recorded_epoch"], previous["artifact"]["path"])
            if previous is not None
            else None
        )
        if previous_key is None or current_key > previous_key:
            newest[item["candidate_id"]] = item

    items: list[dict[str, Any]] = []
    by_source: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for item in newest.values():
        item = dict(item)
        item.pop("_recorded_epoch")
        item["registered_in_delivery_inbox"] = item["candidate_id"] in registered
        items.append(item)
        by_source[(item["repository"], item["branch"], item["commit"])].append(
            item["candidate_id"]
        )
    items.sort(
        key=lambda item: (
            item["recorded_at_normalized"] or item["artifact"]["modified_at"],
            item["candidate_id"],
        ),
        reverse=True,
    )
    aliases = [
        {
            "repository": identity[0],
            "branch": identity[1],
            "commit": identity[2],
            "candidate_ids": sorted(candidate_ids),
        }
        for identity, candidate_ids in sorted(by_source.items())
        if len(candidate_ids) > 1
    ]
    return {
        "schema_version": "upstream-readiness-discovery-v1",
        "scanned_file_count": len(paths),
        "ready_signal_count": len(items),
        "registered_count": sum(item["registered_in_delivery_inbox"] for item in items),
        "unregistered_count": sum(
            not item["registered_in_delivery_inbox"] for item in items
        ),
        "source_alias_count": len(aliases),
        "source_aliases": aliases,
        "items": items,
        "errors": errors,
        "claim_boundary": (
            "EXPLICIT_READINESS_SIGNAL_DISCOVERY_ONLY_NOT_REVIEW_STATE_VALIDATION_"
            "PR_AUTHORIZATION_OR_EXTERNAL_ACTION"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("roots", type=Path, nargs="+")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--max-depth", type=int, default=1)
    parser.add_argument("--max-files", type=int, default=10_000)
    parser.add_argument("--max-file-bytes", type=int, default=2 * 1024 * 1024)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = discover(
            args.roots,
            args.manifest,
            max_depth=args.max_depth,
            max_files=args.max_files,
            max_file_bytes=args.max_file_bytes,
        )
    except ValueError as error:
        print(json.dumps({"status": "FAIL", "errors": [str(error)]}, indent=2))
        return 1
    output = {"status": "PASS", "errors": [], "discovery": result}
    rendered = json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
