#!/usr/bin/env python3
"""Exercise checkpoint-backed graph temporal and corpus-growth guards."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from community_graph_v2 import build_graph, validate_graph  # noqa: E402
from community_knowledge import atomic_json  # noqa: E402


CORPUS = ROOT.parents[1] / "community-optimization-corpus"
ANCHOR = (
    ROOT.parents[1]
    / "community-validation"
    / "knowledge-checkpoint-anchor-2026-09-07-0500z.v1.json"
)
REPOSITORIES = [
    "vllm-project/vllm",
    "sgl-project/sglang",
    "kvcache-ai/Mooncake",
]


def stable(graph: dict) -> dict:
    return {key: value for key, value in graph.items() if key != "generated_at"}


def test_graph_is_stable_when_uncheckpointed_corpus_grows() -> None:
    if not CORPUS.is_dir() or not ANCHOR.is_file():
        return
    with tempfile.TemporaryDirectory() as temporary:
        corpus = Path(temporary) / "corpus"
        shutil.copytree(CORPUS, corpus)
        first = build_graph(
            corpus,
            ANCHOR,
            REPOSITORIES,
            "2026-09-07T05:00:00Z",
            "2026-09-07T05:00:00Z",
            ROOT,
        )
        # Simulate a later sync. Neither a changed global index nor a new event
        # outside the checkpoint may affect the already frozen graph universe.
        index_path = corpus / "index.json"
        index = json.loads(index_path.read_text(encoding="utf-8"))
        index["generated_at"] = "2026-09-08T00:00:00Z"
        atomic_json(index_path, index)
        atomic_json(
            corpus / "events" / "uncheckpointed-later-event.json",
            {"schema_version": "not-part-of-this-checkpoint"},
        )
        second = build_graph(
            corpus,
            ANCHOR,
            REPOSITORIES,
            "2026-09-07T05:00:00Z",
            "2026-09-07T05:00:00Z",
            ROOT,
        )
        assert stable(first) == stable(second)
        graph_path = Path(temporary) / "graph.json"
        atomic_json(graph_path, first)
        assert validate_graph(graph_path, corpus, ROOT)["status"] == "PASS"


def test_graph_rejects_cutoff_before_checkpoint_anchor() -> None:
    if not CORPUS.is_dir() or not ANCHOR.is_file():
        return
    try:
        build_graph(
            CORPUS,
            ANCHOR,
            REPOSITORIES,
            "2026-09-07T04:59:59Z",
            "2026-09-07T04:59:59Z",
            ROOT,
        )
    except ValueError as error:
        assert "knowledge anchor not_after" in str(error)
    else:
        raise AssertionError("graph accepted knowledge before its anchor boundary")
