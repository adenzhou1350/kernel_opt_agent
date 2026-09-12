#!/usr/bin/env python3
"""Seal and verify candidate source identity directly from immutable Git objects."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "candidate-source-seal-v1"
TOP_LEVEL_KEYS = {
    "schema_version",
    "repository_id",
    "base",
    "candidate",
    "patch",
    "changed_paths",
    "source_identity_sha256",
    "claim_boundary",
}


class SourceIdentityError(ValueError):
    """Raised when source identity cannot be sealed or verified."""


def _git(repository: Path, *args: str, input_bytes: bytes | None = None) -> bytes:
    process = subprocess.run(
        ["git", "-C", os.fspath(repository), *args],
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if process.returncode:
        detail = process.stderr.decode("utf-8", errors="replace").strip()
        raise SourceIdentityError(f"git {' '.join(args)} failed: {detail}")
    return process.stdout


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _resolve_commit(repository: Path, revision: str) -> str:
    return _git(repository, "rev-parse", "--verify", f"{revision}^{{commit}}").decode("ascii").strip()


def _resolve_tree(repository: Path, commit: str) -> str:
    return _git(repository, "rev-parse", "--verify", f"{commit}^{{tree}}").decode("ascii").strip()


def _require_clean(repository: Path) -> None:
    status = _git(repository, "status", "--porcelain=v1", "--untracked-files=all")
    if status:
        raise SourceIdentityError("candidate repository worktree is not clean")


def _require_ancestor(repository: Path, base: str, candidate: str) -> None:
    process = subprocess.run(
        ["git", "-C", os.fspath(repository), "merge-base", "--is-ancestor", base, candidate],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if process.returncode == 1:
        raise SourceIdentityError("base commit is not an ancestor of candidate commit")
    if process.returncode:
        detail = process.stderr.decode("utf-8", errors="replace").strip()
        raise SourceIdentityError(f"git merge-base --is-ancestor failed: {detail}")


def _changed_paths(repository: Path, base: str, candidate: str) -> list[dict[str, str]]:
    raw = _git(repository, "diff", "--name-status", "-z", "--no-renames", base, candidate, "--")
    fields = raw.split(b"\0")
    if fields and fields[-1] == b"":
        fields.pop()
    if len(fields) % 2:
        raise SourceIdentityError("unexpected git diff --name-status output")
    changes = []
    for index in range(0, len(fields), 2):
        status = fields[index].decode("ascii")
        try:
            path = fields[index + 1].decode("utf-8")
        except UnicodeDecodeError as error:
            raise SourceIdentityError("non-UTF-8 Git paths are not supported") from error
        if status not in {"A", "D", "M", "T", "U", "X", "B"}:
            raise SourceIdentityError(f"unexpected Git change status: {status}")
        changes.append({"status": status, "path": path})
    return changes


def _object_identity(repository: Path, commit: str, path: str) -> dict[str, Any] | None:
    raw = _git(repository, "ls-tree", "-z", commit, "--", f":(literal){path}")
    if not raw:
        return None
    records = [item for item in raw.split(b"\0") if item]
    if len(records) != 1:
        raise SourceIdentityError(f"expected one Git object for path: {path}")
    header, raw_path = records[0].split(b"\t", 1)
    if raw_path.decode("utf-8") != path:
        raise SourceIdentityError(f"Git path mismatch while sealing: {path}")
    mode, object_type, object_sha1 = header.decode("ascii").split()
    result = {
        "mode": mode,
        "type": object_type,
        "git_sha1": object_sha1,
    }
    if object_type == "blob":
        payload = _git(repository, "cat-file", "blob", object_sha1)
        result.update({"sha256": _sha256(payload), "bytes": len(payload)})
    else:
        # A gitlink points at a commit in another object database. The
        # superproject commit/tree and gitlink SHA still seal that identity.
        result.update({"sha256": None, "bytes": None})
    return result


def derive_identity(repository: Path, repository_id: str, base_revision: str, candidate_revision: str) -> dict[str, Any]:
    repository = repository.resolve()
    if not repository_id.strip():
        raise SourceIdentityError("repository_id must not be empty")
    base = _resolve_commit(repository, base_revision)
    candidate = _resolve_commit(repository, candidate_revision)
    _require_ancestor(repository, base, candidate)

    diff = _git(repository, "diff", "--binary", "--full-index", "--no-ext-diff", "--no-renames", base, candidate, "--")
    if not diff:
        raise SourceIdentityError("candidate has no committed diff from base")
    patch_id_output = _git(repository, "patch-id", "--stable", input_bytes=diff).decode("ascii").strip().split()
    if len(patch_id_output) != 2:
        raise SourceIdentityError("Git could not derive a stable patch-id")

    changed_paths = []
    for change in _changed_paths(repository, base, candidate):
        changed_paths.append(
            {
                **change,
                "base_object": _object_identity(repository, base, change["path"]),
                "candidate_object": _object_identity(repository, candidate, change["path"]),
            }
        )

    identity: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "repository_id": repository_id,
        "base": {"commit": base, "tree": _resolve_tree(repository, base)},
        "candidate": {"commit": candidate, "tree": _resolve_tree(repository, candidate)},
        "patch": {
            "stable_patch_id": patch_id_output[0],
            "diff_sha256": _sha256(diff),
            "diff_bytes": len(diff),
        },
        "changed_paths": changed_paths,
        "claim_boundary": {
            "source": "IMMUTABLE_GIT_OBJECTS",
            "worktree_bytes_used": False,
            "runtime_correctness_or_performance": "NOT_CLAIMED",
        },
    }
    identity["source_identity_sha256"] = _sha256(_canonical_bytes(identity))
    return identity


def seal(repository: Path, repository_id: str, base: str, candidate: str, output: Path) -> dict[str, Any]:
    _require_clean(repository.resolve())
    identity = derive_identity(repository, repository_id, base, candidate)
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(identity, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    try:
        with output.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
    except FileExistsError as error:
        raise SourceIdentityError(f"refusing to overwrite existing receipt: {output}") from error
    return identity


def verify(repository: Path, receipt_path: Path) -> dict[str, Any]:
    try:
        recorded = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SourceIdentityError(f"could not read receipt: {error}") from error
    if not isinstance(recorded, dict) or set(recorded) != TOP_LEVEL_KEYS:
        raise SourceIdentityError("receipt top-level keys do not match candidate-source-seal-v1")
    if recorded.get("schema_version") != SCHEMA_VERSION:
        raise SourceIdentityError(f"unsupported schema_version: {recorded.get('schema_version')}")
    try:
        expected = derive_identity(
            repository,
            recorded["repository_id"],
            recorded["base"]["commit"],
            recorded["candidate"]["commit"],
        )
    except (KeyError, TypeError) as error:
        raise SourceIdentityError("receipt source identity fields are malformed") from error
    if recorded != expected:
        raise SourceIdentityError("receipt does not match identities re-derived from Git objects")
    return expected


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="operation", required=True)
    seal_parser = subparsers.add_parser("seal", help="create a source identity receipt")
    seal_parser.add_argument("--repository", type=Path, required=True)
    seal_parser.add_argument("--repository-id", required=True)
    seal_parser.add_argument("--base", required=True)
    seal_parser.add_argument("--candidate", required=True)
    seal_parser.add_argument("--output", type=Path, required=True)
    verify_parser = subparsers.add_parser("verify", help="re-derive and verify a source identity receipt")
    verify_parser.add_argument("--repository", type=Path, required=True)
    verify_parser.add_argument("--receipt", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.operation == "seal":
            result = seal(args.repository, args.repository_id, args.base, args.candidate, args.output)
        else:
            result = verify(args.repository, args.receipt)
    except SourceIdentityError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 2
    print(json.dumps({"status": "PASS", "source_identity_sha256": result["source_identity_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
