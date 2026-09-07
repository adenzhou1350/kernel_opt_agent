"""Exercise checkpoint coverage policy and recomputation guards."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from community_coverage_audit import (  # noqa: E402
    build_audit,
    evaluate,
    main,
    validate_audit,
)
from community_knowledge import atomic_json  # noqa: E402


def graph() -> dict:
    outcomes = ["MERGED", "OPEN", "CLOSED_UNMERGED", "REGRESSION_FOLLOWUP", "REVERTED"]
    repositories = [
        "vllm-project/vllm",
        "sgl-project/sglang",
        "kvcache-ai/Mooncake",
        "vllm-project/vllm",
        "sgl-project/sglang",
    ]
    relation_types = [
        "COMPLEMENTS",
        "CONFLICTS",
        "PORTED_FROM",
        "REGRESSION_OF",
        "REQUIRES",
        "REVERTED_BY",
        "SUPERSEDED_BY",
    ]
    nodes = [
        {
            "event_id": f"event-{index}",
            "repository": repository,
            "outcome": outcome,
            "review_status": "REVIEWED",
            "source_available_at": "2026-01-01T00:00:00Z",
        }
        for index, (repository, outcome) in enumerate(zip(repositories, outcomes))
    ]
    return {
        "source_cutoff_at": "2026-01-02T00:00:00Z",
        "nodes": nodes,
        "edges": [
            {
                "source": f"event-{index % len(nodes)}",
                "target": (
                    "method-a" if index == 0 else f"event-{(index + 1) % len(nodes)}"
                ),
                "target_kind": "METHOD" if index == 0 else "EVENT",
                "type": relation,
                "resolution": "PRESENT",
            }
            for index, relation in enumerate(relation_types)
        ],
        "coverage_gaps": [],
        "composition_hypotheses": [
            {"events": ["event-0", "event-1"]},
            {"events": ["event-1", "event-2"]},
        ],
        "lifecycle_review_queue": [],
    }


def policy() -> dict:
    return {
        "schema_version": "community-coverage-policy-v1",
        "policy_id": "test-policy",
        "required_outcomes": {
            outcome: 1
            for outcome in (
                "MERGED",
                "OPEN",
                "CLOSED_UNMERGED",
                "REGRESSION_FOLLOWUP",
                "REVERTED",
            )
        },
        "required_repositories": {
            "vllm-project/vllm": 1,
            "sgl-project/sglang": 1,
            "kvcache-ai/Mooncake": 1,
        },
        "required_relation_types": [
            "COMPLEMENTS",
            "CONFLICTS",
            "PORTED_FROM",
            "REGRESSION_OF",
            "REQUIRES",
            "REVERTED_BY",
            "SUPERSEDED_BY",
        ],
        "minimum_reviewed_fraction": 1.0,
        "minimum_negative_event_count": 3,
        "minimum_cross_repository_compositions": 2,
        "maximum_unresolved_relation_fraction": 0.5,
        "maximum_single_repository_node_fraction": 0.7,
    }


def test_coverage_audit_requires_lifecycle_and_cross_repository_breadth() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        graph_path = base / "graph.json"
        policy_path = base / "policy.json"
        audit_path = base / "audit.json"
        atomic_json(graph_path, graph())
        atomic_json(policy_path, policy())
        with patch("community_coverage_audit.validate_source_graph"):
            report = build_audit(graph_path, policy_path, base, ROOT, ROOT)
        assert report["status"] == "PASS"
        assert report["inventory"]["negative_event_count"] == 3
        assert report["inventory"]["cross_repository_composition_count"] == 2
        assert report["schema_version"] == "community-coverage-audit-v1"
        assert "reusable_method_connected_event_count" not in report["inventory"]
        atomic_json(audit_path, report)
        with patch("community_coverage_audit.validate_source_graph"):
            assert validate_audit(audit_path, base, ROOT)["status"] == "PASS"

        reduced = graph()
        reduced["nodes"] = [
            item for item in reduced["nodes"] if item["outcome"] != "REVERTED"
        ]
        atomic_json(graph_path, reduced)
        with patch("community_coverage_audit.validate_source_graph"):
            failed = build_audit(graph_path, policy_path, base, ROOT, ROOT)
        assert failed["status"] == "FAIL"
        assert (
            next(
                item
                for item in failed["checks"]
                if item["check_id"] == "outcome:REVERTED"
            )["status"]
            == "FAIL"
        )


def test_coverage_audit_rejects_tampering() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        graph_path = base / "graph.json"
        policy_path = base / "policy.json"
        audit_path = base / "audit.json"
        atomic_json(graph_path, graph())
        atomic_json(policy_path, policy())
        with patch("community_coverage_audit.validate_source_graph"):
            report = build_audit(graph_path, policy_path, base, ROOT, ROOT)
        report["inventory"]["node_count"] = 999
        atomic_json(audit_path, report)
        with patch("community_coverage_audit.validate_source_graph"):
            try:
                validate_audit(audit_path, base, ROOT)
            except ValueError as error:
                assert "stale or was edited" in str(error)
            else:
                raise AssertionError("edited coverage audit passed validation")


def test_coverage_failure_returns_nonzero_and_keeps_artifact() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        graph_path = base / "graph.json"
        policy_path = base / "policy.json"
        audit_path = base / "audit.json"
        reduced = graph()
        reduced["composition_hypotheses"] = []
        atomic_json(graph_path, reduced)
        atomic_json(policy_path, policy())
        argv = [
            "community_coverage_audit.py",
            "build",
            "--graph",
            str(graph_path),
            "--policy",
            str(policy_path),
            "--corpus",
            str(base),
            "--graph-validation-root",
            str(ROOT),
            "--output",
            str(audit_path),
        ]
        with (
            patch("community_coverage_audit.validate_source_graph"),
            patch.object(sys, "argv", argv),
        ):
            assert main() == 2
        assert audit_path.is_file()
        assert json.loads(audit_path.read_text(encoding="utf-8"))["status"] == "FAIL"


def test_method_aware_inventory_separates_graph_and_provenance_links() -> None:
    methods = {
        "cards": [
            {
                "method_id": "method-from-negative-event",
                "source": {"available_at": "2026-01-02T00:00:00Z"},
                "community_provenance": {"source_event_ids": ["event-2"]},
            }
        ]
    }
    inventory, _ = evaluate(graph(), policy(), methods)
    assert inventory["graph_method_relation_count"] == 1
    assert inventory["graph_method_linked_event_count"] == 1
    assert inventory["method_provenance_link_count"] == 1
    assert inventory["method_provenance_event_count"] == 1
    assert inventory["method_provenance_card_count"] == 1
    assert inventory["method_provenance_callable_card_count"] == 1
    assert inventory["method_provenance_rejected_card_count"] == 0
    assert inventory["reusable_method_connected_event_count"] == 2
    assert inventory["reusable_method_connected_event_fraction"] == 0.4
    assert inventory["connected_negative_event_count"] == 3
    assert inventory["cross_repository_event_relation_count"] == 6


def test_method_provenance_after_card_time_is_not_callable() -> None:
    value = graph()
    value["nodes"][2]["source_available_at"] = "2026-01-03T00:00:00Z"
    methods = {
        "cards": [
            {
                "method_id": "premature-method",
                "source": {"available_at": "2026-01-02T00:00:00Z"},
                "community_provenance": {"source_event_ids": ["event-2"]},
            }
        ]
    }
    inventory, _ = evaluate(value, policy(), methods)
    assert inventory["method_provenance_callable_card_count"] == 0
    assert inventory["method_provenance_rejected_card_count"] == 1
    assert inventory["method_provenance_rejection_counts"] == {
        "SOURCE_EVENT_AVAILABLE_AFTER_METHOD": 1
    }
