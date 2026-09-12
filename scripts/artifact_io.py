#!/usr/bin/env python3
"""Small, dependency-free helpers for hash-bound JSON artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_tracked_text(repository: Path, path: Path, revision: str = "HEAD") -> str:
    """Hash committed text bytes while accepting Git's CRLF checkout filter only."""
    repository = repository.resolve()
    path = path.resolve()
    try:
        relative = path.relative_to(repository).as_posix()
    except ValueError as error:
        raise ValueError("tracked text path must stay inside the repository") from error
    completed = subprocess.run(
        ["git", "-C", str(repository), "show", f"{revision}:{relative}"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        detail = completed.stderr.decode(errors="replace").strip()
        raise ValueError(f"cannot read tracked text from Git: {detail}")
    committed = completed.stdout
    worktree = path.read_bytes()
    if worktree != committed and worktree.replace(b"\r\n", b"\n") != committed:
        raise ValueError("tracked text worktree content changed")
    return hashlib.sha256(committed).hexdigest()


def read_object(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(
        prefix=path.name, suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(canonical_json(value))
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
