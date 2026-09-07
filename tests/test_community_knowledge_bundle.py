from __future__ import annotations

import json
import sys
from copy import deepcopy
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from community_evaluation import validate_knowledge_bundle_binding  # noqa: E402
from community_knowledge import atomic_json, sha256_file  # noqa: E402


CUTOFF = "2026-09-07T22:00:00+00:00"
COMMIT = "1" * 40


def identity(path: Path) -> dict:
    return {"path": path.as_posix(), "sha256": sha256_file(path)}


def coverage_inventory() -> dict:
    return {
        "node_count": 2,
        "repository_counts": {"one/project": 1, "two/project": 1},
        "outcome_counts": {"MERGED": 2},
        "reviewed_count": 2,
        "negative_event_count": 1,
        "edge_count": 1,
        "relation_type_counts": {"COMPLEMENTS": 1},
        "unresolved_relation_count": 0,
        "coverage_gap_count": 0,
        "composition_count": 1,
        "cross_repository_composition_count": 1,
        "graph_method_relation_count": 1,
        "graph_method_linked_event_count": 1,
        "graph_method_linked_event_fraction": 0.5,
        "method_provenance_link_count": 2,
        "method_provenance_event_count": 2,
        "method_provenance_card_count": 1,
        "method_provenance_callable_card_count": 1,
        "method_provenance_rejected_card_count": 0,
        "method_provenance_rejection_counts": {},
        "reusable_method_connected_event_count": 2,
        "reusable_method_connected_event_fraction": 1.0,
        "connected_negative_event_count": 1,
        "connected_negative_event_fraction": 1.0,
        "cross_repository_event_relation_count": 1,
        "lifecycle_review_queue_count": 0,
        "reviewed_fraction": 1.0,
        "unresolved_relation_fraction": 0.0,
        "maximum_single_repository_node_fraction": 0.5,
    }


def build_fixture(tmp_path: Path) -> tuple[dict, dict, dict[str, Path]]:
    graph_path = tmp_path / "graph.json"
    methods_path = tmp_path / "methods.json"
    anchor_path = tmp_path / "anchor.json"
    policy_path = tmp_path / "policy.json"
    validation_path = tmp_path / "validation.json"
    audit_path = tmp_path / "audit.json"
    bundle_path = tmp_path / "bundle.json"
    suite_path = tmp_path / "suite.json"

    graph = {
        "source_cutoff_at": CUTOFF,
        "knowledge_cutoff_at": CUTOFF,
        "input_identity": {
            "git_commit": COMMIT,
            "relation_observations": [{"path": "relation.json", "sha256": "2" * 64}],
        },
    }
    atomic_json(graph_path, graph)
    atomic_json(methods_path, {"cutoff_at": CUTOFF})
    atomic_json(anchor_path, {"not_after": CUTOFF})
    atomic_json(policy_path, {"policy": "fixture"})
    atomic_json(validation_path, {"status": "PASS"})
    inventory = coverage_inventory()
    audit = {
        "schema_version": "community-coverage-audit-v2",
        "generated_at": CUTOFF,
        "claim_boundary": "CHECKPOINT_COVERAGE_NOT_METHOD_EFFECTIVENESS",
        "status": "PASS",
        "input_identity": {
            "graph": identity(graph_path),
            "methods": identity(methods_path),
            "policy": identity(policy_path),
            "graph_validation_root": {
                "path": tmp_path.as_posix(),
                "head_commit": COMMIT,
            },
        },
        "inventory": inventory,
        "checks": [
            {
                "check_id": "cross_repository_composition_count",
                "status": "PASS",
                "observed": 1,
                "requirement": 1,
            }
        ],
        "limitations": ["Fixture coverage is not performance evidence."],
    }
    atomic_json(audit_path, audit)
    bundle = {
        "schema_version": "future-community-knowledge-bundle-receipt-v1",
        "generated_at": CUTOFF,
        "status": "READY_FOR_FUTURE_SUITE_BINDING",
        "claim_boundary": "CUTOFF_SAFE_KNOWLEDGE_INPUT_NOT_PERFORMANCE_EVIDENCE",
        "repository": {
            "branch": "fixture",
            "commit": COMMIT,
            "fork_url": "https://example.invalid/fixture",
        },
        "cutoffs": {
            "source_cutoff_at": CUTOFF,
            "knowledge_cutoff_at": CUTOFF,
            "event_universe": "two fixture events",
        },
        "inputs": {
            "checkpoint_anchor": identity(anchor_path),
            "graph": identity(graph_path),
            "methods": identity(methods_path),
            "coverage_audit": identity(audit_path),
            "validation_receipt": identity(validation_path),
        },
        "inventory": {
            "events": inventory["node_count"],
            "relations": inventory["edge_count"],
            "composition_hypotheses": inventory["composition_count"],
            "cross_repository_compositions": inventory[
                "cross_repository_composition_count"
            ],
            "callable_community_provenance_method_cards": inventory[
                "method_provenance_callable_card_count"
            ],
            "rejected_community_provenance_method_cards": inventory[
                "method_provenance_rejected_card_count"
            ],
            "reusable_method_connected_events": inventory[
                "reusable_method_connected_event_count"
            ],
            "connected_negative_events": inventory[
                "connected_negative_event_count"
            ],
            "coverage_status": "PASS",
        },
        "suite_binding_rule": "Bind graph and methods together.",
        "limitations": ["Fixture bundle is not performance evidence."],
    }
    atomic_json(bundle_path, bundle)
    suite = {
        "schema_version": "community-temporal-suite-v3",
        "knowledge_bundle": identity(bundle_path),
    }
    return suite, graph, {
        "suite": suite_path,
        "graph": graph_path,
        "methods": methods_path,
        "anchor": anchor_path,
        "bundle": bundle_path,
    }


def validate_fixture(suite: dict, graph: dict, paths: dict[str, Path]) -> Path | None:
    return validate_knowledge_bundle_binding(
        suite,
        paths["suite"].parent,
        graph,
        paths["graph"],
        paths["methods"],
        paths["anchor"],
        datetime.fromisoformat(CUTOFF),
        ROOT,
    )


def test_bundle_binds_graph_methods_anchor_audit_and_cutoff(tmp_path: Path) -> None:
    suite, graph, paths = build_fixture(tmp_path)
    assert validate_fixture(suite, graph, paths) == paths["bundle"]

    missing = deepcopy(suite)
    missing.pop("knowledge_bundle")
    try:
        validate_fixture(missing, graph, paths)
    except ValueError as error:
        assert "requires a knowledge bundle" in str(error)
    else:
        raise AssertionError("relation-aware graph accepted without a bundle")

    late_bundle = json.loads(paths["bundle"].read_text(encoding="utf-8"))
    late_bundle["cutoffs"]["knowledge_cutoff_at"] = "2026-09-07T23:00:00+00:00"
    atomic_json(paths["bundle"], late_bundle)
    suite["knowledge_bundle"] = identity(paths["bundle"])
    try:
        validate_fixture(suite, graph, paths)
    except ValueError as error:
        assert "cutoff differs" in str(error)
    else:
        raise AssertionError("later-cutoff bundle accepted by an earlier suite")


def test_legacy_v3_graph_without_relations_remains_replayable(tmp_path: Path) -> None:
    suite, graph, paths = build_fixture(tmp_path)
    suite.pop("knowledge_bundle")
    graph["input_identity"].pop("relation_observations")
    assert validate_fixture(suite, graph, paths) is None
