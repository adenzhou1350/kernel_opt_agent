#!/usr/bin/env python3
"""Audit checkpoint knowledge breadth without claiming optimization effectiveness."""

from __future__ import annotations

import argparse
import json
import subprocess
from collections import Counter
from pathlib import Path

from community_graph_v2 import validate_graph as validate_source_graph
from community_knowledge import atomic_json, now, read_object, sha256_file
from schema_utils import validate_instance, validate_json_file


SCHEMA_VERSION = "community-coverage-audit-v1"
NEGATIVE_OUTCOMES = {"CLOSED_UNMERGED", "REGRESSION_FOLLOWUP", "REVERTED"}


def root() -> Path:
    return Path(__file__).resolve().parents[1]


def identity(path: Path) -> dict:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {"path": path.as_posix(), "sha256": sha256_file(path)}


def validation_root_identity(path: Path) -> dict:
    path = path.resolve()
    if not path.is_dir():
        raise FileNotFoundError(path)
    commit = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout.strip()
    return {"path": path.as_posix(), "head_commit": commit}


def fraction(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def check(check_id: str, observed: float, requirement: float, passed: bool) -> dict:
    return {
        "check_id": check_id,
        "status": "PASS" if passed else "FAIL",
        "observed": observed,
        "requirement": requirement,
    }


def evaluate(graph: dict, policy: dict) -> tuple[dict, list[dict]]:
    nodes = graph["nodes"]
    edges = graph["edges"]
    repository_counts = Counter(item["repository"] for item in nodes)
    outcome_counts = Counter(item["outcome"] for item in nodes)
    relation_counts = Counter(item["type"] for item in edges)
    reviewed_count = sum(item["review_status"] == "REVIEWED" for item in nodes)
    negative_count = sum(item["outcome"] in NEGATIVE_OUTCOMES for item in nodes)
    unresolved_count = sum(item["resolution"] == "MISSING" for item in edges)
    event_repositories = {item["event_id"]: item["repository"] for item in nodes}
    cross_repository_compositions = sum(
        len(
            {
                event_repositories[event]
                for event in item["events"]
                if event in event_repositories
            }
        )
        > 1
        for item in graph["composition_hypotheses"]
    )
    node_count = len(nodes)
    edge_count = len(edges)
    reviewed_fraction = fraction(reviewed_count, node_count)
    unresolved_fraction = fraction(unresolved_count, edge_count)
    maximum_repository_fraction = fraction(
        max(repository_counts.values(), default=0), node_count
    )
    inventory = {
        "node_count": node_count,
        "repository_counts": dict(sorted(repository_counts.items())),
        "outcome_counts": dict(sorted(outcome_counts.items())),
        "reviewed_count": reviewed_count,
        "negative_event_count": negative_count,
        "edge_count": edge_count,
        "relation_type_counts": dict(sorted(relation_counts.items())),
        "unresolved_relation_count": unresolved_count,
        "coverage_gap_count": len(graph["coverage_gaps"]),
        "composition_count": len(graph["composition_hypotheses"]),
        "cross_repository_composition_count": cross_repository_compositions,
        "lifecycle_review_queue_count": len(graph["lifecycle_review_queue"]),
        "reviewed_fraction": reviewed_fraction,
        "unresolved_relation_fraction": unresolved_fraction,
        "maximum_single_repository_node_fraction": maximum_repository_fraction,
    }
    checks = []
    for outcome, minimum in sorted(policy["required_outcomes"].items()):
        observed = outcome_counts[outcome]
        checks.append(
            check(f"outcome:{outcome}", observed, minimum, observed >= minimum)
        )
    for repository, minimum in sorted(policy["required_repositories"].items()):
        observed = repository_counts[repository]
        checks.append(
            check(f"repository:{repository}", observed, minimum, observed >= minimum)
        )
    for relation in sorted(policy["required_relation_types"]):
        observed = relation_counts[relation]
        checks.append(check(f"relation:{relation}", observed, 1, observed >= 1))
    checks.extend(
        [
            check(
                "reviewed_fraction",
                reviewed_fraction,
                policy["minimum_reviewed_fraction"],
                reviewed_fraction >= policy["minimum_reviewed_fraction"],
            ),
            check(
                "negative_event_count",
                negative_count,
                policy["minimum_negative_event_count"],
                negative_count >= policy["minimum_negative_event_count"],
            ),
            check(
                "cross_repository_composition_count",
                cross_repository_compositions,
                policy["minimum_cross_repository_compositions"],
                cross_repository_compositions
                >= policy["minimum_cross_repository_compositions"],
            ),
            check(
                "unresolved_relation_fraction",
                unresolved_fraction,
                policy["maximum_unresolved_relation_fraction"],
                unresolved_fraction <= policy["maximum_unresolved_relation_fraction"],
            ),
            check(
                "maximum_single_repository_node_fraction",
                maximum_repository_fraction,
                policy["maximum_single_repository_node_fraction"],
                maximum_repository_fraction
                <= policy["maximum_single_repository_node_fraction"],
            ),
        ]
    )
    return inventory, checks


def build_audit(
    graph_path: Path,
    policy_path: Path,
    corpus: Path,
    project_root: Path | None = None,
    graph_validation_root: Path | None = None,
) -> dict:
    project_root = project_root or root()
    graph_validation_root = (graph_validation_root or project_root).resolve()
    graph_path = graph_path.resolve()
    policy_path = policy_path.resolve()
    validate_source_graph(graph_path, corpus.resolve(), graph_validation_root)
    policy_errors = validate_json_file(
        policy_path, project_root / "schemas/community_coverage_policy.schema.json"
    )
    if policy_errors:
        raise ValueError(
            "invalid community coverage policy: " + "; ".join(policy_errors)
        )
    graph = read_object(graph_path)
    policy = read_object(policy_path)
    inventory, checks = evaluate(graph, policy)
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now(),
        "claim_boundary": "CHECKPOINT_COVERAGE_NOT_METHOD_EFFECTIVENESS",
        "status": "PASS"
        if all(item["status"] == "PASS" for item in checks)
        else "FAIL",
        "input_identity": {
            "graph": identity(graph_path),
            "policy": identity(policy_path),
            "graph_validation_root": validation_root_identity(graph_validation_root),
        },
        "inventory": inventory,
        "checks": checks,
        "limitations": [
            "Breadth and lifecycle diversity do not prove that community knowledge improves optimization outcomes.",
            "Composition hypotheses remain discovery priors until a held-out task validates them.",
            "Coverage gaps identify missing repository-method intersections; they are not evidence that a transferable implementation exists.",
        ],
    }
    errors = validate_instance(
        report,
        read_object(project_root / "schemas/community_coverage_audit.schema.json"),
    )
    if errors:
        raise ValueError("invalid community coverage audit: " + "; ".join(errors))
    return report


def validate_audit(path: Path, corpus: Path, project_root: Path | None = None) -> dict:
    project_root = project_root or root()
    path = path.resolve()
    errors = validate_json_file(
        path, project_root / "schemas/community_coverage_audit.schema.json"
    )
    if errors:
        raise ValueError("invalid community coverage audit: " + "; ".join(errors))
    report = read_object(path)
    for label in ("graph", "policy"):
        item = report["input_identity"][label]
        source = Path(item["path"])
        if not source.is_file() or sha256_file(source) != item["sha256"]:
            raise ValueError(f"community coverage {label} identity changed")
    expected = build_audit(
        Path(report["input_identity"]["graph"]["path"]),
        Path(report["input_identity"]["policy"]["path"]),
        corpus,
        project_root,
        Path(report["input_identity"]["graph_validation_root"]["path"]),
    )
    observed_copy = {
        key: value for key, value in report.items() if key != "generated_at"
    }
    expected_copy = {
        key: value for key, value in expected.items() if key != "generated_at"
    }
    if observed_copy != expected_copy:
        raise ValueError("community coverage audit is stale or was edited")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    build = commands.add_parser("build")
    build.add_argument("--graph", type=Path, required=True)
    build.add_argument("--policy", type=Path, required=True)
    build.add_argument("--corpus", type=Path, required=True)
    build.add_argument("--graph-validation-root", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("--audit", type=Path, required=True)
    validate.add_argument("--corpus", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.operation == "build":
        result = build_audit(
            args.graph,
            args.policy,
            args.corpus,
            graph_validation_root=args.graph_validation_root,
        )
        atomic_json(args.output.resolve(), result)
        coverage_status = result["status"]
    else:
        report = validate_audit(args.audit, args.corpus)
        result = {"status": "PASS", "coverage_status": report["status"]}
        coverage_status = report["status"]
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if coverage_status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
