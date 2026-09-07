#!/usr/bin/env python3
"""Build temporal community graphs from one immutable Git-anchored checkpoint."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from community_checkpoint import git_bytes, resolve_in, validate_anchor
from community_knowledge import (
    REPOSITORY_PATTERN,
    atomic_json,
    graph_node,
    now,
    read_object,
    sha256_file,
    stable_identifier,
)
from schema_utils import validate_instance


GRAPH_SCHEMA = "community-optimization-graph-v2"


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def parse_time(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{label} must be ISO-8601") from error
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc)


def identity(path: Path) -> dict:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {"path": path.as_posix(), "sha256": sha256_file(path)}


def manifest_outcome(manifest: dict) -> str:
    pull_request = manifest["pull_request"]
    if pull_request["merged"]:
        return "MERGED"
    if pull_request["state"] == "open":
        return "OPEN"
    return "CLOSED_UNMERGED"


def git_method_universe(root: Path, commit: str) -> tuple[set[str], list[dict]]:
    names = git_bytes(
        root,
        "ls-tree",
        "-r",
        "--name-only",
        commit,
        "--",
        "knowledge/methods",
        "knowledge/primitives",
    ).decode("utf-8")
    paths = sorted(path for path in names.splitlines() if path.endswith(".json"))
    method_ids = set()
    identities = []
    for relative in paths:
        payload = git_bytes(root, "show", f"{commit}:{relative}")
        card = json.loads(payload.decode("utf-8"))
        method_ids.add(card["method_id"])
        identities.append(
            {
                "path": relative,
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    return method_ids, identities


def lifecycle_observation(
    corpus: Path,
    event: dict,
    lifecycle_rows: list[dict],
    source_cutoff: datetime,
) -> dict | None:
    """Resolve lifecycle using only manifests named by the frozen checkpoint."""
    source = event["source_snapshot"]
    candidates = []
    for row in lifecycle_rows:
        if (
            row["repository"] != source["repository"]
            or row["pr_number"] != source["pr_number"]
        ):
            continue
        available = parse_time(row["source_available_at"], "source_available_at")
        if available > source_cutoff:
            continue
        manifest = read_object(resolve_in(corpus, row["manifest"]["path"]))
        candidates.append((available, row["snapshot_id"], manifest, row))
    if not candidates:
        return None
    latest_time = max(item[0] for item in candidates)
    source_at_latest_time = next(
        (
            item
            for item in candidates
            if item[0] == latest_time and item[1] == source["snapshot_id"]
        ),
        None,
    )
    _, _, manifest, latest = source_at_latest_time or max(
        (item for item in candidates if item[0] == latest_time),
        key=lambda item: item[1],
    )
    current = latest["snapshot_id"] == source["snapshot_id"]
    return {
        "status": "CURRENT" if current else "REVIEW_REQUIRED",
        "event_snapshot_id": source["snapshot_id"],
        "event_outcome": event["lifecycle"]["outcome"],
        "latest_snapshot_id": latest["snapshot_id"],
        "latest_outcome": manifest_outcome(manifest),
        "latest_source_available_at": latest["source_available_at"],
    }


def validate_graph_structure(graph: dict, root: Path) -> None:
    schema = read_object(root / "schemas/community_optimization_graph_v2.schema.json")
    errors = validate_instance(graph, schema)
    v1 = read_object(root / "schemas/community_optimization_graph.schema.json")
    for field in (
        "nodes",
        "edges",
        "coverage_gaps",
        "composition_hypotheses",
        "lifecycle_review_queue",
    ):
        item_schema = v1["properties"][field]["items"]
        for index, item in enumerate(graph[field]):
            errors.extend(
                validate_instance(
                    item,
                    item_schema,
                    root=v1,
                    path=f"$.{field}[{index}]",
                )
            )
    if errors:
        raise ValueError("invalid checkpoint-backed graph: " + "; ".join(errors))


def build_graph(
    corpus: Path,
    checkpoint_anchor: Path,
    repositories: list[str],
    source_cutoff_at: str,
    knowledge_cutoff_at: str,
    root: Path | None = None,
) -> dict:
    root = (root or repository_root()).resolve()
    corpus = corpus.resolve()
    checkpoint_anchor = checkpoint_anchor.resolve()
    anchor_validation = validate_anchor(checkpoint_anchor, corpus, root)
    anchor = read_object(checkpoint_anchor)
    checkpoint_path = Path(anchor["checkpoint_identity"]["path"]).resolve()
    checkpoint = read_object(checkpoint_path)
    source_cutoff = parse_time(source_cutoff_at, "source_cutoff_at")
    knowledge_cutoff = parse_time(knowledge_cutoff_at, "knowledge_cutoff_at")
    if source_cutoff > knowledge_cutoff:
        raise ValueError("source cutoff exceeds graph knowledge cutoff")
    if parse_time(anchor["not_after"], "anchor.not_after") > knowledge_cutoff:
        raise ValueError("knowledge anchor not_after exceeds graph knowledge cutoff")
    repository_universe = sorted(set(repositories), key=str.lower)
    if not repository_universe or any(
        not REPOSITORY_PATTERN.fullmatch(item) for item in repository_universe
    ):
        raise ValueError("repository universe must contain owner/name values")

    all_event_ids = {row["event_id"] for row in checkpoint["events"]}
    selected: list[tuple[dict, str, dict]] = []
    excluded = []
    for row in checkpoint["events"]:
        available_at = row["source_public_at"]
        if parse_time(available_at, "source_public_at") > source_cutoff:
            excluded.append(
                {
                    "event_id": row["event_id"],
                    "reason": "SOURCE_AFTER_CUTOFF",
                    "source_public_at": available_at,
                }
            )
            continue
        event = read_object(resolve_in(corpus, row["event"]["path"]))
        observation = lifecycle_observation(
            corpus,
            event,
            checkpoint["lifecycle_snapshots"],
            source_cutoff,
        )
        if observation is None:
            excluded.append(
                {
                    "event_id": row["event_id"],
                    "reason": "NO_LIFECYCLE_SNAPSHOT_AT_SOURCE_CUTOFF",
                    "source_public_at": available_at,
                }
            )
            continue
        selected.append((event, available_at, observation))
    if not selected:
        raise ValueError("knowledge checkpoint has no usable events at source cutoff")

    nodes = sorted(
        (
            graph_node(event, available_at, observation)
            for event, available_at, observation in selected
        ),
        key=lambda item: item["event_id"],
    )
    known_events = {event["event_id"] for event, _, _ in selected}
    method_ids, method_identities = git_method_universe(
        root, anchor_validation["commit"]
    )
    current_event_ids = {
        event["event_id"]
        for event, _, observation in selected
        if observation["status"] == "CURRENT"
    }
    edges = []
    compositions: dict[str, dict] = {}
    for event, _, _ in selected:
        for relation in event["relations"]:
            target = relation["target"]
            if target in all_event_ids and target not in known_events:
                continue
            target_kind = "METHOD" if target in method_ids else "EVENT"
            present = (
                target in method_ids
                if target_kind == "METHOD"
                else target in known_events
            )
            edges.append(
                {
                    "source": event["event_id"],
                    "type": relation["type"],
                    "target": target,
                    "target_kind": target_kind,
                    "resolution": "PRESENT" if present else "MISSING",
                    "rationale": relation["rationale"],
                }
            )
            if (
                relation["type"] == "COMPLEMENTS"
                and present
                and target_kind == "EVENT"
                and event["event_id"] in current_event_ids
                and target in current_event_ids
            ):
                pair = sorted((event["event_id"], target))
                hypothesis_id = stable_identifier(
                    {"relation": "COMPLEMENTS", "events": pair}
                )
                compositions[hypothesis_id] = {
                    "hypothesis_id": hypothesis_id,
                    "events": pair,
                    "relation": "COMPLEMENTS",
                    "rationale": relation["rationale"],
                    "claim_boundary": "UNVALIDATED_COMPOSITION_HYPOTHESIS",
                }

    coverage: dict[tuple[str, str], dict[str, set[str]]] = {}
    for node in nodes:
        if (
            node["review_status"] == "DRAFT"
            or node["lifecycle_observation"]["status"] != "CURRENT"
        ):
            continue
        for family in node["rewrite_families"]:
            for subsystem in node["subsystems"]:
                bucket = coverage.setdefault(
                    (family, subsystem), {"repositories": set(), "events": set()}
                )
                bucket["repositories"].add(node["repository"])
                bucket["events"].add(node["event_id"])
    gaps = []
    for (family, subsystem), bucket in sorted(coverage.items()):
        observed = sorted(bucket["repositories"], key=str.lower)
        missing = sorted(set(repository_universe) - set(observed), key=str.lower)
        if not missing:
            continue
        gap_identity = {
            "rewrite_family": family,
            "subsystem": subsystem,
            "observed": observed,
            "missing": missing,
        }
        gaps.append(
            {
                "gap_id": stable_identifier(gap_identity),
                "rewrite_family": family,
                "subsystem": subsystem,
                "observed_repositories": observed,
                "missing_repositories": missing,
                "evidence_events": sorted(bucket["events"]),
                "claim_boundary": "CORPUS_COVERAGE_GAP_ONLY",
            }
        )

    graph = {
        "schema_version": GRAPH_SCHEMA,
        "generated_at": now(),
        "source_cutoff_at": source_cutoff_at,
        "knowledge_cutoff_at": knowledge_cutoff_at,
        "claim_boundary": "CHECKPOINT_BOUND_DISCOVERY_PRIOR_ONLY",
        "input_identity": {
            "checkpoint_anchor": identity(checkpoint_anchor),
            "checkpoint": identity(checkpoint_path),
            "checkpoint_id": checkpoint["checkpoint_id"],
            "git_commit": anchor_validation["commit"],
            "method_cards": method_identities,
        },
        "repository_universe": repository_universe,
        "excluded_events": sorted(excluded, key=lambda item: item["event_id"]),
        "nodes": nodes,
        "lifecycle_review_queue": [
            {
                "event_id": node["event_id"],
                "repository": node["repository"],
                "pr_number": node["pr_number"],
                **node["lifecycle_observation"],
            }
            for node in nodes
            if node["lifecycle_observation"]["status"] == "REVIEW_REQUIRED"
        ],
        "edges": sorted(
            edges, key=lambda item: (item["source"], item["type"], item["target"])
        ),
        "coverage_gaps": gaps,
        "composition_hypotheses": sorted(
            compositions.values(), key=lambda item: item["hypothesis_id"]
        ),
    }
    validate_graph_structure(graph, root)
    return graph


def validate_graph(graph_path: Path, corpus: Path, root: Path | None = None) -> dict:
    root = (root or repository_root()).resolve()
    graph = read_object(graph_path.resolve())
    validate_graph_structure(graph, root)
    anchor_path = Path(graph["input_identity"]["checkpoint_anchor"]["path"])
    if (
        sha256_file(anchor_path)
        != graph["input_identity"]["checkpoint_anchor"]["sha256"]
    ):
        raise ValueError("checkpoint anchor changed")
    expected = build_graph(
        corpus,
        anchor_path,
        graph["repository_universe"],
        graph["source_cutoff_at"],
        graph["knowledge_cutoff_at"],
        root,
    )
    observed_stable = {
        key: value for key, value in graph.items() if key != "generated_at"
    }
    expected_stable = {
        key: value for key, value in expected.items() if key != "generated_at"
    }
    if observed_stable != expected_stable:
        raise ValueError("checkpoint-backed graph is stale or was edited")
    return {
        "status": "PASS",
        "checkpoint_id": graph["input_identity"]["checkpoint_id"],
        "node_count": len(graph["nodes"]),
        "excluded_event_count": len(graph["excluded_events"]),
        "edge_count": len(graph["edges"]),
        "coverage_gap_count": len(graph["coverage_gaps"]),
        "composition_count": len(graph["composition_hypotheses"]),
        "lifecycle_review_count": len(graph["lifecycle_review_queue"]),
    }


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    operations = value.add_subparsers(dest="operation", required=True)
    build = operations.add_parser("build")
    build.add_argument("--corpus", type=Path, required=True)
    build.add_argument("--checkpoint-anchor", type=Path, required=True)
    build.add_argument("--repository", action="append", required=True)
    build.add_argument("--source-cutoff", required=True)
    build.add_argument("--knowledge-cutoff", required=True)
    build.add_argument("--output", type=Path, required=True)
    validate = operations.add_parser("validate")
    validate.add_argument("--graph", type=Path, required=True)
    validate.add_argument("--corpus", type=Path, required=True)
    return value


def main() -> int:
    args = parser().parse_args()
    if args.operation == "build":
        graph = build_graph(
            args.corpus,
            args.checkpoint_anchor,
            args.repository,
            args.source_cutoff,
            args.knowledge_cutoff,
        )
        atomic_json(args.output, graph)
        print(validate_graph(args.output, args.corpus))
    else:
        print(validate_graph(args.graph, args.corpus))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
