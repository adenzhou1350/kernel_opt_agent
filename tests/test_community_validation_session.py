#!/usr/bin/env python3
"""Exercise content-addressed, process-local community validation reuse."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from community_validation_session import ValidationSession  # noqa: E402
from community_window_validation import validate_window  # noqa: E402


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")


def test_cache_hit_rechecks_transitive_identity_closure() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        leaf = root / "leaf.json"
        child = root / "child.json"
        parent = root / "parent.json"
        write(leaf, {"value": 1})
        write(child, {"input": {"path": leaf.as_posix(), "sha256": digest(leaf)}})
        write(parent, {"input": {"path": child.as_posix(), "sha256": digest(child)}})

        session = ValidationSession(root)
        result = {"status": "PASS"}
        session.put("example", parent, result)
        assert session.get("example", parent) == result
        assert session.statistics()["hits"] == 1

        write(leaf, {"value": 2})
        assert session.get("example", parent) is None
        assert session.statistics()["misses"] == 1


def test_cache_is_not_shared_between_sessions() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        artifact = root / "artifact.json"
        write(artifact, {"value": 1})
        first = ValidationSession(root)
        first.put("example", artifact, {"status": "PASS"})
        assert first.get("example", artifact) is not None
        second = ValidationSession(root)
        assert second.get("example", artifact) is None


def test_explicit_identity_root_resolves_corpus_relative_paths() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        source = root / "source"
        corpus = root / "corpus"
        source.mkdir()
        (corpus / "events").mkdir(parents=True)
        event = corpus / "events" / "event.json"
        artifact = source / "artifact.json"
        (source / "events").mkdir()
        write(source / "events" / "event.json", {"value": "wrong root"})
        write(event, {"value": 1})
        write(
            artifact,
            {"input": {"path": "events/event.json", "sha256": digest(event)}},
        )
        session = ValidationSession(source, identity_roots=(corpus,))
        session.put("example", artifact, {"status": "PASS"})
        assert session.get("example", artifact) is not None


def test_window_validator_preserves_fail_closed_receipt() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        corpus = base / "corpus"
        corpus.mkdir()
        write(corpus / "index.json", {"events": []})
        paths = [base / f"input-{index}.json" for index in range(4)]
        for path in paths:
            write(path, {"invalid": True})
        report = validate_window(
            *paths,
            corpus,
            ROOT,
            implementation_root=ROOT,
        )
        assert report["status"] == "FAIL"
        assert report["stages"] == []
        assert report["error"].startswith("ValueError: invalid held-out queue")


def main() -> None:
    test_cache_hit_rechecks_transitive_identity_closure()
    test_cache_is_not_shared_between_sessions()
    test_explicit_identity_root_resolves_corpus_relative_paths()
    test_window_validator_preserves_fail_closed_receipt()
    print("community validation session tests passed")


if __name__ == "__main__":
    main()
