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

from community_checkpoint import build_anchor  # noqa: E402
from community_graph_v2 import (  # noqa: E402
    build_graph,
    parse_time,
    resolve_relation_observations,
    validate_graph,
)
from community_knowledge import atomic_json  # noqa: E402
from schema_utils import validate_instance  # noqa: E402


CORPUS = ROOT.parents[1] / "community-optimization-corpus"
CHECKPOINT = (
    ROOT
    / "knowledge/community/checkpoints/community-knowledge-2026-09-07-0427z.v1.json"
)
CHECKPOINT_COMMIT = "f3db80246a30081047652098b5ace5f612125fdb"
REPOSITORIES = [
    "vllm-project/vllm",
    "sgl-project/sglang",
    "kvcache-ai/Mooncake",
]


def stable(graph: dict) -> dict:
    return {key: value for key, value in graph.items() if key != "generated_at"}


def materialize_anchor(corpus: Path, output: Path) -> Path:
    anchor_path = output / "checkpoint-anchor.json"
    atomic_json(
        anchor_path,
        build_anchor(
            CHECKPOINT,
            corpus,
            CHECKPOINT_COMMIT,
            "2026-09-07T05:00:00Z",
            ROOT,
        ),
    )
    return anchor_path


def test_graph_is_stable_when_uncheckpointed_corpus_grows() -> None:
    if not CORPUS.is_dir() or not CHECKPOINT.is_file():
        return
    with tempfile.TemporaryDirectory() as temporary:
        temporary_path = Path(temporary)
        corpus = temporary_path / "corpus"
        shutil.copytree(CORPUS, corpus)
        anchor = materialize_anchor(corpus, temporary_path)
        first = build_graph(
            corpus,
            anchor,
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
            anchor,
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
    if not CORPUS.is_dir() or not CHECKPOINT.is_file():
        return
    with tempfile.TemporaryDirectory() as temporary:
        anchor = materialize_anchor(CORPUS, Path(temporary))
        try:
            build_graph(
                CORPUS,
                anchor,
                REPOSITORIES,
                "2026-09-07T04:59:59Z",
                "2026-09-07T04:59:59Z",
                ROOT,
            )
        except ValueError as error:
            assert "knowledge anchor not_after" in str(error)
        else:
            raise AssertionError("graph accepted knowledge before its anchor boundary")


def test_temporal_suite_v2_requires_the_complete_knowledge_chain() -> None:
    schema = json.loads(
        (ROOT / "schemas" / "community_temporal_suite.schema.json").read_text(
            encoding="utf-8"
        )
    )
    v2_errors = validate_instance(
        {"schema_version": "community-temporal-suite-v2"}, schema
    )
    assert any("knowledge_checkpoint_anchor" in error for error in v2_errors)
    assert any("preselection_anchor" in error for error in v2_errors)
    assert any("training_prior_outcomes" in error for error in v2_errors)
    assert any("training_prior_routing" in error for error in v2_errors)

    v1_errors = validate_instance(
        {"schema_version": "community-temporal-suite-v1"}, schema
    )
    assert not any("knowledge_checkpoint_anchor" in error for error in v1_errors)

    v3_errors = validate_instance(
        {"schema_version": "community-temporal-suite-v3"}, schema
    )
    assert any("knowledge_checkpoint_anchor" in error for error in v3_errors)
    assert any("task_novelty_guard" in error for error in v3_errors)
    assert any("task_selection_manifest" in error for error in v3_errors)


def test_relation_observation_is_temporal_claim_bound_and_context_guarded() -> None:
    first = {
        "event_id": "repo-a.pr-1.first",
        "claims": [{"claim_id": "first-claim"}],
    }
    second = {
        "event_id": "repo-b.pr-2.second",
        "claims": [{"claim_id": "second-claim"}],
    }
    checkpoint_events = {
        first["event_id"]: (first, "2026-09-01T00:00:00Z"),
        second["event_id"]: (second, "2026-09-02T00:00:00Z"),
    }
    observation = {
        "observation_id": "cross-project.v1",
        "available_at": "2026-09-03T00:00:00Z",
        "source": first["event_id"],
        "relation": "COMPLEMENTS",
        "target": second["event_id"],
        "rationale": "The methods remove different sequential stages.",
        "required_context": ["Both stages occur in one weighted workload."],
        "falsification_recipe": ["Measure isolated and combined arms."],
        "evidence": [
            {"event_id": first["event_id"], "claim_ids": ["first-claim"]},
            {"event_id": second["event_id"], "claim_ids": ["second-claim"]},
        ],
    }
    known = set(checkpoint_events)
    edges, compositions = resolve_relation_observations(
        [observation],
        checkpoint_events,
        known,
        known,
        parse_time("2026-09-05T00:00:00Z", "cutoff"),
        parse_time("2026-09-04T00:00:00Z", "commit"),
    )
    assert len(edges) == 1
    assert len(compositions) == 1
    composition = next(iter(compositions.values()))
    assert composition["available_at"] == "2026-09-04T00:00:00+00:00"
    assert composition["required_context"] == observation["required_context"]

    edges, compositions = resolve_relation_observations(
        [observation],
        checkpoint_events,
        known,
        known,
        parse_time("2026-09-03T12:00:00Z", "cutoff"),
        parse_time("2026-09-04T00:00:00Z", "commit"),
    )
    assert edges == []
    assert compositions == {}

    invalid = dict(observation)
    invalid["evidence"] = [dict(row) for row in observation["evidence"]]
    invalid["evidence"][0]["claim_ids"] = ["unknown"]
    try:
        resolve_relation_observations(
            [invalid],
            checkpoint_events,
            known,
            known,
            parse_time("2026-09-05T00:00:00Z", "cutoff"),
            parse_time("2026-09-04T00:00:00Z", "commit"),
        )
    except ValueError as error:
        assert "unknown claims" in str(error)
    else:
        raise AssertionError("relation observation accepted an unknown claim")
