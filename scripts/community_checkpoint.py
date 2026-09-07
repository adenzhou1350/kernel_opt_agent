#!/usr/bin/env python3
"""Freeze and Git-anchor the exact knowledge/lifecycle universe used by a graph."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from community_knowledge import (
    atomic_json,
    event_manifest_path,
    event_paths,
    event_source_available_at,
    now,
    read_object,
    sha256_file,
    snapshot_source_available_at,
    validate_event,
)
from schema_utils import validate_instance, validate_json_file


CHECKPOINT_SCHEMA = "community-knowledge-checkpoint-v1"
ANCHOR_SCHEMA = "community-knowledge-checkpoint-anchor-v1"


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def file_identity(path: Path, base: Path | None = None) -> dict:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    value = path.relative_to(base.resolve()) if base is not None else path
    return {"path": value.as_posix(), "sha256": sha256_file(path)}


def resolve_in(base: Path, relative: str) -> Path:
    base = base.resolve()
    path = (base / relative).resolve()
    try:
        path.relative_to(base)
    except ValueError as error:
        raise ValueError(f"checkpoint path escapes corpus: {relative}") from error
    return path


def checkpoint_payload(
    corpus: Path, event_files: list[Path], manifests: list[Path]
) -> dict:
    corpus = corpus.resolve()
    events = []
    for path in sorted(event_files):
        validate_event(path, corpus)
        event = read_object(path)
        source_manifest = event_manifest_path(corpus, event)
        events.append(
            {
                "event_id": event["event_id"],
                "event": file_identity(path, corpus),
                "source_public_at": event_source_available_at(corpus, event),
                "source_manifest": file_identity(source_manifest, corpus),
            }
        )
    snapshots = []
    for path in sorted(manifests):
        manifest = read_object(path)
        snapshots.append(
            {
                "repository": manifest["source"]["repository"],
                "pr_number": manifest["source"]["number"],
                "snapshot_id": manifest["snapshot_id"],
                "source_available_at": snapshot_source_available_at(path),
                "manifest": file_identity(path, corpus),
            }
        )
    events.sort(key=lambda row: row["event_id"])
    snapshots.sort(
        key=lambda row: (
            row["repository"].lower(),
            row["pr_number"],
            row["snapshot_id"],
        )
    )
    event_ids = [row["event_id"] for row in events]
    snapshot_keys = [
        (row["repository"], row["pr_number"], row["snapshot_id"]) for row in snapshots
    ]
    if len(event_ids) != len(set(event_ids)):
        raise ValueError("knowledge checkpoint contains duplicate event ids")
    if len(snapshot_keys) != len(set(snapshot_keys)):
        raise ValueError("knowledge checkpoint contains duplicate lifecycle snapshots")
    return {"events": events, "lifecycle_snapshots": snapshots}


def payload_id(payload: dict) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_checkpoint(corpus: Path, root: Path | None = None) -> dict:
    root = (root or repository_root()).resolve()
    corpus = corpus.resolve()
    index = read_object(corpus / "index.json")
    manifests = [
        resolve_in(corpus, f"{entry['path']}/manifest.json")
        for entry in index["snapshots"]
    ]
    payload = checkpoint_payload(corpus, event_paths(corpus), manifests)
    checkpoint = {
        "schema_version": CHECKPOINT_SCHEMA,
        "checkpoint_id": payload_id(payload),
        "generated_at": now(),
        "claim_boundary": "KNOWLEDGE_UNIVERSE_IDENTITY_NOT_PERFORMANCE_EVIDENCE",
        "corpus_layout": "PATHS_RELATIVE_TO_RUNTIME_CORPUS_ROOT",
        **payload,
    }
    errors = validate_instance(
        checkpoint,
        read_object(root / "schemas/community_knowledge_checkpoint.schema.json"),
    )
    if errors:
        raise ValueError("invalid knowledge checkpoint: " + "; ".join(errors))
    return checkpoint


def validate_checkpoint(
    checkpoint_path: Path, corpus: Path, root: Path | None = None
) -> dict:
    root = (root or repository_root()).resolve()
    checkpoint_path = checkpoint_path.resolve()
    errors = validate_json_file(
        checkpoint_path, root / "schemas/community_knowledge_checkpoint.schema.json"
    )
    if errors:
        raise ValueError("invalid knowledge checkpoint: " + "; ".join(errors))
    observed = read_object(checkpoint_path)
    corpus = corpus.resolve()
    event_files = []
    for row in observed["events"]:
        path = resolve_in(corpus, row["event"]["path"])
        if not path.is_file() or sha256_file(path) != row["event"]["sha256"]:
            raise ValueError(f"checkpoint event changed: {row['event']['path']}")
        event_files.append(path)
    manifests = []
    for row in observed["lifecycle_snapshots"]:
        path = resolve_in(corpus, row["manifest"]["path"])
        if not path.is_file() or sha256_file(path) != row["manifest"]["sha256"]:
            raise ValueError(
                f"checkpoint lifecycle manifest changed: {row['manifest']['path']}"
            )
        manifests.append(path)
    expected_payload = checkpoint_payload(corpus, event_files, manifests)
    if observed["events"] != expected_payload["events"]:
        raise ValueError("checkpoint event metadata is stale or edited")
    if observed["lifecycle_snapshots"] != expected_payload["lifecycle_snapshots"]:
        raise ValueError("checkpoint lifecycle metadata is stale or edited")
    if observed["checkpoint_id"] != payload_id(expected_payload):
        raise ValueError("checkpoint id is stale or edited")
    return {
        "status": "PASS",
        "checkpoint_id": observed["checkpoint_id"],
        "event_count": len(observed["events"]),
        "lifecycle_snapshot_count": len(observed["lifecycle_snapshots"]),
    }


def git_bytes(repository: Path, *arguments: str) -> bytes:
    completed = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(f"git {' '.join(arguments)} failed: {detail}")
    return completed.stdout


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    operations = value.add_subparsers(dest="operation", required=True)
    build = operations.add_parser("build")
    build.add_argument("--corpus", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    validate = operations.add_parser("validate")
    validate.add_argument("--checkpoint", type=Path, required=True)
    validate.add_argument("--corpus", type=Path, required=True)
    anchor = operations.add_parser("anchor")
    anchor.add_argument("--checkpoint", type=Path, required=True)
    anchor.add_argument("--corpus", type=Path, required=True)
    anchor.add_argument("--git-commit", required=True)
    anchor.add_argument("--not-after", required=True)
    anchor.add_argument("--output", type=Path, required=True)
    anchor_validate = operations.add_parser("validate-anchor")
    anchor_validate.add_argument("--anchor", type=Path, required=True)
    anchor_validate.add_argument("--corpus", type=Path, required=True)
    return value


def main() -> int:
    args = parser().parse_args()
    if args.operation == "build":
        atomic_json(args.output, build_checkpoint(args.corpus))
        print(args.output.resolve())
    elif args.operation == "validate":
        print(validate_checkpoint(args.checkpoint, args.corpus))
    elif args.operation == "anchor":
        # The checkpoint is already content-validated before commit; anchoring
        # proves its exact bytes existed before the declared future cutoff.
        anchor = build_anchor(
            args.checkpoint, args.corpus, args.git_commit, args.not_after
        )
        atomic_json(args.output, anchor)
        print(args.output.resolve())
    else:
        print(validate_anchor(args.anchor, args.corpus))
    return 0


def build_anchor(
    checkpoint_path: Path,
    corpus: Path,
    git_commit: str,
    not_after: str,
    root: Path | None = None,
) -> dict:
    root = (root or repository_root()).resolve()
    checkpoint_path = checkpoint_path.resolve()
    validate_checkpoint(checkpoint_path, corpus, root)
    errors = validate_json_file(
        checkpoint_path, root / "schemas/community_knowledge_checkpoint.schema.json"
    )
    if errors:
        raise ValueError("invalid knowledge checkpoint: " + "; ".join(errors))
    try:
        relative = checkpoint_path.relative_to(root).as_posix()
    except ValueError as error:
        raise ValueError("checkpoint must be inside the Git repository") from error
    resolved = git_bytes(root, "rev-parse", f"{git_commit}^{{commit}}").decode().strip()
    if not re.fullmatch(r"[0-9a-f]{40}", resolved):
        raise ValueError("Git did not resolve a full commit identity")
    committed_bytes = git_bytes(root, "show", f"{resolved}:{relative}")
    if committed_bytes != checkpoint_path.read_bytes():
        raise ValueError("working checkpoint differs from anchored Git commit")
    committed_at = (
        git_bytes(root, "show", "-s", "--format=%cI", resolved).decode().strip()
    )
    if parse_time(committed_at) > parse_time(not_after):
        raise ValueError("knowledge checkpoint commit is later than not_after")
    anchor = {
        "schema_version": ANCHOR_SCHEMA,
        "generated_at": now(),
        "claim_boundary": "GIT_EXISTENCE_BEFORE_KNOWLEDGE_CUTOFF_ONLY",
        "checkpoint_identity": file_identity(checkpoint_path),
        "git_anchor": {
            "repository": root.as_posix(),
            "commit": resolved,
            "committed_at": committed_at,
            "checkpoint_path": relative,
        },
        "not_after": not_after,
        "status": "PASS",
    }
    errors = validate_instance(
        anchor,
        read_object(root / "schemas/community_knowledge_checkpoint_anchor.schema.json"),
    )
    if errors:
        raise ValueError("invalid knowledge checkpoint anchor: " + "; ".join(errors))
    return anchor


def validate_anchor(anchor_path: Path, corpus: Path, root: Path | None = None) -> dict:
    root = (root or repository_root()).resolve()
    anchor_path = anchor_path.resolve()
    errors = validate_json_file(
        anchor_path,
        root / "schemas/community_knowledge_checkpoint_anchor.schema.json",
    )
    if errors:
        raise ValueError("invalid knowledge checkpoint anchor: " + "; ".join(errors))
    observed = read_object(anchor_path)
    checkpoint = Path(observed["checkpoint_identity"]["path"])
    if (
        not checkpoint.is_file()
        or sha256_file(checkpoint) != observed["checkpoint_identity"]["sha256"]
    ):
        raise ValueError("knowledge checkpoint anchor input changed")
    expected = build_anchor(
        checkpoint,
        corpus,
        observed["git_anchor"]["commit"],
        observed["not_after"],
        root,
    )
    observed_stable = {
        key: value for key, value in observed.items() if key != "generated_at"
    }
    expected_stable = {
        key: value for key, value in expected.items() if key != "generated_at"
    }
    if observed_stable != expected_stable:
        raise ValueError("knowledge checkpoint anchor is stale or edited")
    return {
        "status": "PASS",
        "checkpoint_id": read_object(checkpoint)["checkpoint_id"],
        "commit": observed["git_anchor"]["commit"],
        "committed_at": observed["git_anchor"]["committed_at"],
        "not_after": observed["not_after"],
    }


if __name__ == "__main__":
    raise SystemExit(main())
