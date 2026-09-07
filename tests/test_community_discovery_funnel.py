#!/usr/bin/env python3
"""Exercise evidence-bound prospective discovery funnel accounting."""

from __future__ import annotations

import json
import sys
import tempfile
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from community_discovery_funnel import (  # noqa: E402
    build_funnel,
    count_rows,
    ratio,
    validate_funnel,
)
from community_knowledge import atomic_json  # noqa: E402
from schema_utils import validate_instance  # noqa: E402


def test_small_funnel_helpers_are_deterministic() -> None:
    assert ratio(1, 4) == 0.25
    assert ratio(0, 0) is None
    assert count_rows(Counter({"z": 1, "a": 2})) == [
        {"key": "a", "count": 2},
        {"key": "z", "count": 1},
    ]


def available_audits() -> list[Path]:
    base = (
        ROOT.parent / "community-validation/prospective-heldout-outcome-v3-2026-09-07"
    )
    return [
        path
        for path in (
            base / "preselection-chain-audit-postcutoff-033016-v1.json",
            base / "preselection-chain-audit-postcutoff-035615-v1.json",
        )
        if path.is_file()
    ]


def test_funnel_build_validate_and_tamper_guard() -> None:
    audits = available_audits()
    if len(audits) != 2:
        return
    corpus = ROOT.parent / "community-optimization-corpus"
    report = build_funnel(audits, corpus)
    assert report["inventory"]["window_count"] == 2
    assert report["inventory"]["post_cutoff_selected"] == 1
    assert report["inventory"]["runnable_selected"] == 0
    assert report["inventory"]["harness_blocked_selected"] == 1
    assert report["yield"]["discovery_to_runnable"] == 0
    assert report["shadow_recommendations"][0]["recommendation"] == ("COLLECT_MORE")
    assert report["shadow_recommendations"][0]["distinct_candidate_count"] == 1
    schema = json.loads(
        (ROOT / "schemas/community_discovery_funnel_v2.schema.json").read_text(
            encoding="utf-8"
        )
    )
    assert not validate_instance(report, schema)
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "funnel.json"
        atomic_json(path, report)
        assert validate_funnel(path, corpus)["status"] == "PASS"
        edited = json.loads(path.read_text(encoding="utf-8"))
        edited["inventory"]["runnable_selected"] = 1
        atomic_json(path, edited)
        try:
            validate_funnel(path, corpus)
        except ValueError as error:
            assert "stale or was edited" in str(error)
        else:
            raise AssertionError("edited funnel must fail validation")
    committed_v1 = (
        ROOT.parent
        / "community-validation/prospective-heldout-outcome-v3-2026-09-07"
        / "discovery-funnel-through-035615-v1.json"
    )
    if committed_v1.is_file():
        assert validate_funnel(committed_v1, corpus)["status"] == "PASS"


def test_repeated_pr_updates_do_not_become_independent_evidence() -> None:
    audits = available_audits()
    base = (
        ROOT.parent / "community-validation/prospective-heldout-outcome-v3-2026-09-07"
    )
    third = base / "preselection-chain-audit-postcutoff-040852-v1.json"
    if len(audits) != 2 or not third.is_file():
        return
    corpus = ROOT.parent / "community-optimization-corpus"
    report = build_funnel([*audits, third], corpus)
    docs = next(
        row
        for row in report["shadow_recommendations"]
        if row["matched_rule_id"] == "documentation-only"
    )
    assert docs["observation_count"] == 2
    assert docs["distinct_candidate_count"] == 1
    assert docs["candidate_keys"] == ["sgl-project/sglang#38261"]
    assert docs["recommendation"] == "COLLECT_MORE"
