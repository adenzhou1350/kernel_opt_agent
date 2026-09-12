#!/usr/bin/env python3
"""Decide whether a Git commit change requires source-tree requalification."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from schema_utils import validate_instance


VERSION = "source-tree-supersession-v1"


def root() -> Path:
    return Path(__file__).resolve().parents[1]


def git(repo: Path, *args: str, required: bool = True) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    if result.returncode:
        if required:
            detail = result.stderr.strip() or result.stdout.strip()
            raise ValueError(f"git {' '.join(args)} failed: {detail}")
        return None
    return result.stdout.strip()


def resolve(repo: Path, requested_ref: str) -> dict[str, str]:
    if not requested_ref or requested_ref.startswith("-"):
        raise ValueError("Git refs must be non-empty and must not begin with '-'")
    commit = git(repo, "rev-parse", "--verify", f"{requested_ref}^{{commit}}")
    tree = git(repo, "rev-parse", "--verify", f"{commit}^{{tree}}")
    return {"requested_ref": requested_ref, "commit": commit, "tree": tree}


def public_remote_url(value: str | None) -> str | None:
    """Remove HTTP credentials before persisting a remote identity."""
    if not value or "://" not in value:
        return value
    parsed = urlsplit(value)
    if "@" not in parsed.netloc:
        return value
    host = parsed.netloc.rsplit("@", 1)[1]
    return urlunsplit((parsed.scheme, host, parsed.path, parsed.query, parsed.fragment))


def evaluate(repo: Path, validated_ref: str, replacement_ref: str) -> dict:
    repo = repo.resolve()
    if not (repo / ".git").exists() and not git(
        repo, "rev-parse", "--git-dir", required=False
    ):
        raise ValueError(f"not a Git repository: {repo}")
    dirty = git(repo, "status", "--porcelain", "--untracked-files=all")
    if dirty:
        raise ValueError("source supersession requires a clean worktree")
    validated = resolve(repo, validated_ref)
    replacement = resolve(repo, replacement_ref)
    same_tree = validated["tree"] == replacement["tree"]
    changed_paths = []
    if not same_tree:
        output = git(
            repo,
            "diff",
            "--name-only",
            "--no-renames",
            validated["commit"],
            replacement["commit"],
            "--",
        )
        changed_paths = sorted(filter(None, output.splitlines()))
    origin_url = public_remote_url(
        git(repo, "remote", "get-url", "origin", required=False)
    )
    receipt = {
        "schema_version": VERSION,
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "repository": {"path": repo.as_posix(), "origin_url": origin_url},
        "worktree_clean": True,
        "validated_source": validated,
        "replacement_source": replacement,
        "changed_paths": changed_paths,
        "decision": (
            "SOURCE_TREE_EQUIVALENT_REBIND_NON_SOURCE_IDENTITIES"
            if same_tree
            else "SOURCE_TREE_CHANGED_REQUALIFICATION_REQUIRED"
        ),
        "source_requalification_required": not same_tree,
        "non_source_identity_action": "MUST_REBIND_OR_REVALIDATE",
        "claim_boundary": (
            "GIT_TREE_EQUIVALENCE_ONLY_NOT_BUILD_RUNTIME_WORKLOAD_HARDWARE_OR_"
            "PERFORMANCE_EQUIVALENCE"
        ),
    }
    schema = json.loads(
        (root() / "schemas/source_tree_supersession.schema.json").read_text(
            encoding="utf-8"
        )
    )
    errors = validate_instance(receipt, schema)
    if errors:
        raise ValueError("invalid source supersession receipt: " + "; ".join(errors))
    return receipt


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--validated-ref", required=True)
    parser.add_argument("--replacement-ref", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    receipt = evaluate(args.repo, args.validated_ref, args.replacement_ref)
    if args.output:
        atomic_json(args.output.resolve(), receipt)
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
