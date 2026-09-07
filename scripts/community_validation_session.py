#!/usr/bin/env python3
"""Run-scoped, content-addressed memoization for community validators.

The cache is deliberately process-local.  A successful semantic validation may
be reused only while the validated artifact and every file identity reachable
from it still have the same SHA-256.  No cache state is serialized, so an
independent invocation remains a full validation boundary.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class ValidationEntry:
    result: dict
    closure: tuple[tuple[str, str], ...]


class ValidationSession:
    """Memoize successful validations without weakening identity checks."""

    def __init__(
        self,
        repository_root: Path,
        *,
        identity_roots: tuple[Path, ...] = (),
    ) -> None:
        self.repository_root = repository_root.resolve()
        self.identity_roots = tuple(path.resolve() for path in identity_roots)
        self._entries: dict[tuple[str, str, str, tuple[str, ...]], ValidationEntry] = {}
        self.hits = 0
        self.misses = 0

    def _key(
        self, validator: str, artifact: Path, context: tuple[Path, ...]
    ) -> tuple[str, str, str, tuple[str, ...]]:
        artifact = artifact.resolve()
        return (
            validator,
            artifact.as_posix(),
            sha256_file(artifact),
            tuple(path.resolve().as_posix() for path in context),
        )

    def get(
        self, validator: str, artifact: Path, *, context: tuple[Path, ...] = ()
    ) -> dict | None:
        key = self._key(validator, artifact, context)
        entry = self._entries.get(key)
        if entry is None:
            self.misses += 1
            return None
        for raw_path, expected_sha256 in entry.closure:
            path = Path(raw_path)
            if not path.is_file() or sha256_file(path) != expected_sha256:
                self.misses += 1
                self._entries.pop(key, None)
                return None
        self.hits += 1
        return copy.deepcopy(entry.result)

    def put(
        self,
        validator: str,
        artifact: Path,
        result: dict,
        *,
        context: tuple[Path, ...] = (),
    ) -> dict:
        artifact = artifact.resolve()
        closure = self._identity_closure((artifact, *context))
        key = self._key(validator, artifact, context)
        self._entries[key] = ValidationEntry(
            result=copy.deepcopy(result),
            closure=tuple(sorted(closure.items())),
        )
        return result

    def _identity_closure(self, roots: tuple[Path, ...]) -> dict[str, str]:
        pending = [path.resolve() for path in roots]
        closure: dict[str, str] = {}
        while pending:
            path = pending.pop()
            key = path.as_posix()
            if key in closure:
                continue
            if not path.is_file():
                raise FileNotFoundError(path)
            observed_sha256 = sha256_file(path)
            closure[key] = observed_sha256
            if path.suffix.lower() != ".json":
                continue
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            for identity in self._walk_identities(value):
                resolved = self._resolve_identity_path(
                    identity["path"], identity["sha256"], path.parent
                )
                if resolved is None:
                    raise ValueError(
                        "validation-cache identity path cannot be resolved with its SHA-256: "
                        f"{identity['path']}"
                    )
                pending.append(resolved)
        return closure

    def _resolve_identity_path(
        self, raw_path: str, expected_sha256: str, parent: Path
    ) -> Path | None:
        value = Path(raw_path)
        candidates = (
            (value.resolve(),)
            if value.is_absolute()
            else (
                (parent / value).resolve(),
                (self.repository_root / value).resolve(),
                *((root / value).resolve() for root in self.identity_roots),
            )
        )
        seen: set[Path] = set()
        for path in candidates:
            if path in seen:
                continue
            seen.add(path)
            if path.is_file() and sha256_file(path) == expected_sha256:
                return path
        return None

    @staticmethod
    def _walk_identities(value):
        if isinstance(value, dict):
            if (
                isinstance(value.get("path"), str)
                and isinstance(value.get("sha256"), str)
                and len(value["sha256"]) == 64
            ):
                yield value
            for child in value.values():
                yield from ValidationSession._walk_identities(child)
        elif isinstance(value, list):
            for child in value:
                yield from ValidationSession._walk_identities(child)

    def statistics(self) -> dict:
        return {
            "scope": "PROCESS_LOCAL_CONTENT_ADDRESSED",
            "entries": len(self._entries),
            "hits": self.hits,
            "misses": self.misses,
        }
