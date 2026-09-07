#!/usr/bin/env python3
"""Exercise evidence-bound prospective discovery funnel accounting."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from community_discovery_funnel import (  # noqa: E402
    build_funnel,
    count_rows,
    derive_routing_rules,
    ratio,
    validate_funnel,
)
from community_evaluation import validate_preselection_chain_audit  # noqa: E402
from community_funnel_checkpoint import (  # noqa: E402
    build_checkpoint,
    extend_funnel,
    validate_checkpoint,
    validate_incremental_funnel,
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


def test_anchored_chain_survives_later_corpus_index_growth() -> None:
    base = (
        ROOT.parent / "community-validation/prospective-heldout-outcome-v4-2026-09-07"
    )
    audit = base / "preselection-chain-audit-postcutoff-051533-v1.json"
    source_corpus = ROOT.parent / "community-optimization-corpus"
    if not audit.is_file() or not source_corpus.is_dir():
        return
    with tempfile.TemporaryDirectory() as temporary:
        corpus = Path(temporary) / "corpus"
        shutil.copytree(source_corpus, corpus)
        index_path = corpus / "index.json"
        index = json.loads(index_path.read_text(encoding="utf-8"))
        index["generated_at"] = "2026-09-08T00:00:00Z"
        atomic_json(index_path, index)
        assert validate_preselection_chain_audit(audit, corpus, ROOT)["status"] == (
            "PASS"
        )


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


def test_hash_bound_checkpoint_replays_only_new_funnel_suffix() -> None:
    base = (
        ROOT.parent / "community-validation/prospective-heldout-outcome-v4-2026-09-07"
    )
    prior = base / "discovery-funnel-cumulative-through-20260907-134704Z-v1.json"
    current = base / "discovery-funnel-cumulative-through-20260907-143943Z-v1.json"
    new_audit = base / "preselection-chain-audit-134704-20260907-143943Z-v1.json"
    corpus = ROOT.parent / "community-optimization-corpus"
    if not all(path.exists() for path in (prior, current, new_audit, corpus)):
        return
    with tempfile.TemporaryDirectory() as temporary:
        checkpoint_path = Path(temporary) / "checkpoint.json"
        checkpoint = build_checkpoint(prior, corpus)
        atomic_json(checkpoint_path, checkpoint)
        assert validate_checkpoint(checkpoint_path, corpus)["status"] == "PASS"
        incremental = extend_funnel(checkpoint_path, [new_audit], corpus)
        observed = json.loads(current.read_text(encoding="utf-8"))
        incremental.pop("generated_at")
        observed.pop("generated_at")
        assert incremental == observed
        assert (
            validate_incremental_funnel(current, checkpoint_path, corpus)["status"]
            == "PASS"
        )

        edited = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        edited["input_identity"]["source_funnel"]["sha256"] = "0" * 64
        atomic_json(checkpoint_path, edited)
        try:
            validate_checkpoint(checkpoint_path, corpus)
        except ValueError as error:
            assert "source funnel changed" in str(error)
        else:
            raise AssertionError("edited checkpoint must fail validation")


def test_context_bound_routing_requires_distinct_nonrunnable_evidence() -> None:
    recommendation = {
        "matched_rule_id": "amd-only",
        "screen_reason": "NO_DECLARED_RESOURCE_SATISFIES_REQUIREMENTS",
        "task_family": "AMD_RUNTIME",
        "observation_count": 2,
        "distinct_candidate_count": 2,
        "runnable_count": 0,
        "recommendation": "CONSIDER_DISCOVERY_DEMOTION",
        "candidate_keys": ["example/project#7", "example/project#8"],
    }
    funnel = {"shadow_recommendations": [recommendation]}
    policy = {
        "rules": [
            {
                "rule_id": "amd-only",
                "match": {"title_regex": "\\b(rocm|amd)\\b"},
                "task_family": "AMD_RUNTIME",
                "requirements": {
                    "vendors_any": ["AMD"],
                    "capabilities_all": ["ROCM"],
                    "minimum_gpu_count": 1,
                    "minimum_memory_gib_per_gpu": 1,
                },
            }
        ]
    }
    nvidia_profile = {
        "resources": [
            {
                "vendor": "NVIDIA",
                "capabilities": ["CUDA"],
                "gpu_count": 1,
                "memory_gib_per_gpu": 32,
            }
        ]
    }
    rules = derive_routing_rules(funnel, policy, nvidia_profile)
    assert len(rules) == 1
    assert rules[0]["action"] == ("DEFER_AFTER_CONTEXT_MATCHED_RUNNABLE_CANDIDATES")
    assert rules[0]["evidence_candidate_keys"] == [
        "example/project#7",
        "example/project#8",
    ]

    amd_profile = {
        "resources": [
            {
                "vendor": "AMD",
                "capabilities": ["ROCM"],
                "gpu_count": 1,
                "memory_gib_per_gpu": 32,
            }
        ]
    }
    assert derive_routing_rules(funnel, policy, amd_profile) == []
    recommendation["runnable_count"] = 1
    recommendation["recommendation"] = "KEEP"
    assert derive_routing_rules(funnel, policy, nvidia_profile) == []
