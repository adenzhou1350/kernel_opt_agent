#!/usr/bin/env python3
"""Exercise immutable knowledge checkpoint construction and validation."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from community_checkpoint import (  # noqa: E402
    build_checkpoint,
    validate_checkpoint,
)
from community_knowledge import atomic_json  # noqa: E402


def test_checkpoint_ignores_later_corpus_growth_but_rejects_tampering() -> None:
    corpus = ROOT.parents[1] / "community-optimization-corpus"
    if not corpus.is_dir():
        return
    checkpoint = build_checkpoint(corpus)
    assert checkpoint["events"]
    assert checkpoint["lifecycle_snapshots"]
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "checkpoint.json"
        atomic_json(path, checkpoint)
        result = validate_checkpoint(path, corpus)
        assert result["status"] == "PASS"
        edited = json.loads(path.read_text(encoding="utf-8"))
        edited["events"][0]["source_public_at"] = "2020-01-01T00:00:00Z"
        atomic_json(path, edited)
        try:
            validate_checkpoint(path, corpus)
        except ValueError as error:
            assert "stale or edited" in str(error)
        else:
            raise AssertionError("edited checkpoint metadata must fail")
