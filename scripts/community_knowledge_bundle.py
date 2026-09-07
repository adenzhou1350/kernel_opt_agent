#!/usr/bin/env python3
"""Build and validate one portable, cutoff-aligned community knowledge bundle."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from community_checkpoint import validate_anchor
from community_coverage_audit import (
    build_audit,
    validate_audit,
    validate_method_snapshot,
)
from community_graph_v2 import validate_graph
from community_knowledge import atomic_json, now, read_object, sha256_file
from schema_utils import validate_json_file


SCHEMA_VERSION = "future-community-knowledge-bundle-receipt-v2"
VALIDATION_SCHEMA_VERSION = "community-knowledge-bundle-validation-v1"
INVENTORY_BINDINGS = {
    "events": "node_count",
    "relations": "edge_count",
    "composition_hypotheses": "composition_count",
    "cross_repository_compositions": "cross_repository_composition_count",
    "callable_community_provenance_method_cards": (
        "method_provenance_callable_card_count"
    ),
    "rejected_community_provenance_method_cards": (
        "method_provenance_rejected_card_count"
    ),
    "reusable_method_connected_events": "reusable_method_connected_event_count",
    "connected_negative_events": "connected_negative_event_count",
}
VALIDATOR_PATHS = (
    "scripts/community_knowledge_bundle.py",
    "scripts/community_coverage_audit.py",
    "scripts/community_evaluation.py",
    "scripts/community_graph_v2.py",
    "scripts/community_checkpoint.py",
    "schemas/community_knowledge_bundle_receipt.schema.json",
    "schemas/community_knowledge_bundle_validation.schema.json",
    "schemas/community_coverage_audit.schema.json",
    "schemas/community_optimization_graph_v2.schema.json",
    "schemas/community_knowledge_checkpoint_anchor.schema.json",
    "schemas/optimization_method_snapshot.schema.json",
    "schemas/optimization_method.schema.json",
)


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def relative_identity(path: Path) -> dict:
    return {"path": path.name, "sha256": sha256_file(path)}


def resolve_inside(base: Path, value: str, label: str) -> Path:
    path = (base / value).resolve()
    try:
        path.relative_to(base.resolve())
    except ValueError as error:
        raise ValueError(f"{label} path escapes bundle root: {value}") from error
    return path


def bound_path(base: Path, value: dict, label: str) -> Path:
    path = resolve_inside(base, value["path"], label)
    if not path.is_file():
        raise FileNotFoundError(f"{label} is missing: {path}")
    if sha256_file(path) != value["sha256"]:
        raise ValueError(f"{label} hash changed")
    return path


def git_head(root: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout.strip()


def require_clean_validator(root: Path) -> str:
    commit = git_head(root)
    result = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain=v1", "--", *VALIDATOR_PATHS],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.stdout.strip():
        raise ValueError(
            "bundle validator differs from HEAD; commit validator changes before building"
        )
    return commit


def copy_unique(source: Path, directory: Path, used_names: set[str]) -> Path:
    source = source.resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    if source.name in used_names:
        raise ValueError(f"bundle input basenames collide: {source.name}")
    used_names.add(source.name)
    destination = directory / source.name
    shutil.copyfile(source, destination)
    return destination


def inventory_from_audit(audit: dict) -> dict:
    inventory = {
        target: audit["inventory"][source]
        for target, source in INVENTORY_BINDINGS.items()
    }
    inventory["coverage_status"] = audit["status"]
    return inventory


def validation_receipt(
    graph: Path,
    methods: Path,
    anchor: Path,
    policy: Path,
    audit: Path,
    knowledge_commit: str,
    validator_commit: str,
) -> dict:
    return {
        "schema_version": VALIDATION_SCHEMA_VERSION,
        "generated_at": now(),
        "status": "PASS",
        "claim_boundary": "PORTABILITY_AND_CONSISTENCY_NOT_PERFORMANCE_EVIDENCE",
        "knowledge_commit": knowledge_commit,
        "validator_commit": validator_commit,
        "inputs": {
            "graph": relative_identity(graph),
            "methods": relative_identity(methods),
            "checkpoint_anchor": relative_identity(anchor),
            "policy": relative_identity(policy),
            "coverage_audit": relative_identity(audit),
        },
        "checks": [
            "all bound files are inside the bundle root and hash-correct",
            "graph, method snapshot and checkpoint anchor share one cutoff",
            "coverage audit is PASS and reproducible at validator_commit",
            "knowledge_commit is distinct from validator_commit when validators evolve",
        ],
    }


def validate_bundle(
    bundle_path: Path,
    corpus: Path,
    graph_validation_root: Path,
    project_root: Path | None = None,
) -> dict:
    project_root = (project_root or repository_root()).resolve()
    bundle_path = bundle_path.resolve()
    base = bundle_path.parent
    errors = validate_json_file(
        bundle_path,
        project_root / "schemas/community_knowledge_bundle_receipt.schema.json",
    )
    if errors:
        raise ValueError("invalid knowledge bundle: " + "; ".join(errors))
    bundle = read_object(bundle_path)
    paths = {
        label: bound_path(base, value, f"bundle {label}")
        for label, value in bundle["inputs"].items()
    }
    graph = read_object(paths["graph"])
    methods = read_object(paths["methods"])
    audit = read_object(paths["coverage_audit"])
    receipt = read_object(paths["validation_receipt"])
    audit_errors = validate_json_file(
        paths["coverage_audit"],
        project_root / "schemas/community_coverage_audit.schema.json",
    )
    if audit_errors:
        raise ValueError("invalid knowledge bundle coverage audit: " + "; ".join(audit_errors))
    if bundle["schema_version"] == SCHEMA_VERSION:
        receipt_errors = validate_json_file(
            paths["validation_receipt"],
            project_root / "schemas/community_knowledge_bundle_validation.schema.json",
        )
        if receipt_errors:
            raise ValueError(
                "invalid knowledge bundle validation receipt: "
                + "; ".join(receipt_errors)
            )
    validate_graph(paths["graph"], corpus.resolve(), graph_validation_root.resolve())
    validate_anchor(
        paths["checkpoint_anchor"], corpus.resolve(), graph_validation_root.resolve()
    )
    validate_method_snapshot(paths["methods"], graph, project_root)
    if graph["source_cutoff_at"] != graph["knowledge_cutoff_at"]:
        raise ValueError("knowledge bundle graph cutoffs differ")
    if methods["cutoff_at"] != graph["source_cutoff_at"]:
        raise ValueError("knowledge bundle method cutoff differs from graph")
    if (
        bundle["cutoffs"]["source_cutoff_at"] != graph["source_cutoff_at"]
        or bundle["cutoffs"]["knowledge_cutoff_at"] != graph["knowledge_cutoff_at"]
    ):
        raise ValueError("knowledge bundle receipt cutoff differs from graph")
    if audit["status"] != "PASS":
        raise ValueError("knowledge bundle coverage audit is not PASS")
    audit_labels = ("graph", "methods", "policy")
    if bundle["schema_version"] != SCHEMA_VERSION:
        audit_labels = ("graph", "methods")
    for label in audit_labels:
        audit_path = bound_path(
            paths["coverage_audit"].parent,
            audit["input_identity"][label],
            f"coverage audit {label}",
        )
        if audit_path != paths[label].resolve():
            raise ValueError(f"coverage audit binds a different {label}")
    if inventory_from_audit(audit) != bundle["inventory"]:
        raise ValueError("knowledge bundle inventory differs from coverage audit")
    knowledge_commit = bundle["repository"].get(
        "knowledge_commit", bundle["repository"].get("commit")
    )
    validator_commit = bundle["repository"].get(
        "validator_commit", bundle["repository"].get("commit")
    )
    if knowledge_commit != graph["input_identity"]["git_commit"]:
        raise ValueError("knowledge bundle knowledge commit differs from graph")
    if validator_commit != audit["input_identity"]["graph_validation_root"]["head_commit"]:
        raise ValueError("knowledge bundle validator commit differs from audit")
    if receipt.get("status") != "PASS":
        raise ValueError("knowledge bundle validation receipt is not PASS")
    if bundle["schema_version"] == SCHEMA_VERSION and (
        receipt.get("knowledge_commit") != knowledge_commit
        or receipt.get("validator_commit") != validator_commit
    ):
        raise ValueError("knowledge bundle validation receipt commit differs")
    receipt_labels = (
        ("graph", "methods", "checkpoint_anchor", "policy", "coverage_audit")
        if bundle["schema_version"] == SCHEMA_VERSION
        else ()
    )
    for label in receipt_labels:
        receipt_path = bound_path(
            paths["validation_receipt"].parent,
            receipt["inputs"][label],
            f"validation receipt {label}",
        )
        if receipt_path != paths[label].resolve():
            raise ValueError(f"validation receipt binds a different {label}")
    mode = "HASH_AND_SCHEMA_REPLAY"
    if git_head(graph_validation_root.resolve()) == validator_commit:
        validate_audit(paths["coverage_audit"], corpus.resolve(), project_root)
        mode = "FULL_RECOMPUTATION"
    return {
        "status": "PASS",
        "validation_mode": mode,
        "bundle": bundle_path.as_posix(),
        "knowledge_commit": knowledge_commit,
        "validator_commit": validator_commit,
        "inventory": bundle["inventory"],
    }


def build_bundle(
    graph: Path,
    methods: Path,
    checkpoint_anchor: Path,
    policy: Path,
    corpus: Path,
    graph_validation_root: Path,
    branch: str,
    fork_url: str,
    output_dir: Path,
    project_root: Path | None = None,
) -> dict:
    project_root = (project_root or repository_root()).resolve()
    output_dir = output_dir.resolve()
    if output_dir.exists():
        raise FileExistsError(f"refusing to overwrite bundle directory: {output_dir}")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=output_dir.parent)
    )
    try:
        validator_commit = require_clean_validator(graph_validation_root.resolve())
        used_names: set[str] = set()
        local_graph = copy_unique(graph, temporary, used_names)
        local_methods = copy_unique(methods, temporary, used_names)
        local_anchor = copy_unique(checkpoint_anchor, temporary, used_names)
        local_policy = copy_unique(policy, temporary, used_names)
        graph_value = read_object(local_graph)
        knowledge_commit = graph_value["input_identity"]["git_commit"]
        audit_value = build_audit(
            local_graph,
            local_policy,
            corpus.resolve(),
            project_root,
            graph_validation_root.resolve(),
            local_methods,
        )
        if audit_value["status"] != "PASS":
            raise ValueError("coverage policy failed; refusing to build READY bundle")
        for label in ("graph", "methods", "policy"):
            audit_value["input_identity"][label]["path"] = Path(
                audit_value["input_identity"][label]["path"]
            ).name
        audit_path = temporary / "coverage-audit.json"
        atomic_json(audit_path, audit_value)
        receipt_path = temporary / "bundle-validation.json"
        atomic_json(
            receipt_path,
            validation_receipt(
                local_graph,
                local_methods,
                local_anchor,
                local_policy,
                audit_path,
                knowledge_commit,
                validator_commit,
            ),
        )
        bundle_path = temporary / "knowledge-bundle.json"
        atomic_json(
            bundle_path,
            {
                "schema_version": SCHEMA_VERSION,
                "generated_at": now(),
                "status": "READY_FOR_FUTURE_SUITE_BINDING",
                "claim_boundary": (
                    "CUTOFF_SAFE_KNOWLEDGE_INPUT_NOT_PERFORMANCE_EVIDENCE"
                ),
                "repository": {
                    "branch": branch,
                    "knowledge_commit": knowledge_commit,
                    "validator_commit": validator_commit,
                    "fork_url": fork_url,
                },
                "cutoffs": {
                    "source_cutoff_at": graph_value["source_cutoff_at"],
                    "knowledge_cutoff_at": graph_value["knowledge_cutoff_at"],
                    "event_universe": (
                        f"{len(graph_value['nodes'])} events from "
                        f"{len(graph_value['repository_universe'])} repositories"
                    ),
                },
                "inputs": {
                    "checkpoint_anchor": relative_identity(local_anchor),
                    "graph": relative_identity(local_graph),
                    "methods": relative_identity(local_methods),
                    "policy": relative_identity(local_policy),
                    "coverage_audit": relative_identity(audit_path),
                    "validation_receipt": relative_identity(receipt_path),
                },
                "inventory": inventory_from_audit(audit_value),
                "suite_binding_rule": (
                    "Bind this graph, method snapshot and checkpoint anchor together; "
                    "all cutoffs must equal the future temporal-suite cutoff."
                ),
                "limitations": [
                    "This bundle proves portable identity, cutoff alignment and coverage breadth, not optimization effectiveness.",
                    "Community relations and compositions remain discovery priors until a held-out outcome-aware A/B validates them.",
                ],
            },
        )
        validate_bundle(
            bundle_path, corpus.resolve(), graph_validation_root.resolve(), project_root
        )
        os.replace(temporary, output_dir)
        return validate_bundle(
            output_dir / bundle_path.name,
            corpus.resolve(),
            graph_validation_root.resolve(),
            project_root,
        )
    except Exception:
        shutil.rmtree(temporary)
        raise


def failure_receipt(args: argparse.Namespace, error: Exception) -> dict:
    inputs = {}
    for label in ("graph", "methods", "checkpoint_anchor", "policy"):
        value = getattr(args, label, None)
        if value is not None:
            path = Path(value).resolve()
            inputs[label] = {
                "path": path.as_posix(),
                "sha256": sha256_file(path) if path.is_file() else None,
            }
    return {
        "schema_version": "community-knowledge-bundle-failure-v1",
        "generated_at": now(),
        "status": "FAIL_CLOSED",
        "error_type": type(error).__name__,
        "error": str(error),
        "inputs": inputs,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    build = commands.add_parser("build")
    build.add_argument("--graph", type=Path, required=True)
    build.add_argument("--methods", type=Path, required=True)
    build.add_argument("--checkpoint-anchor", type=Path, required=True)
    build.add_argument("--policy", type=Path, required=True)
    build.add_argument("--corpus", type=Path, required=True)
    build.add_argument("--graph-validation-root", type=Path, required=True)
    build.add_argument("--branch", required=True)
    build.add_argument("--fork-url", required=True)
    build.add_argument("--output-dir", type=Path, required=True)
    build.add_argument("--failure-output", type=Path)
    validate = commands.add_parser("validate")
    validate.add_argument("--bundle", type=Path, required=True)
    validate.add_argument("--corpus", type=Path, required=True)
    validate.add_argument("--graph-validation-root", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.operation == "build":
            result = build_bundle(
                args.graph,
                args.methods,
                args.checkpoint_anchor,
                args.policy,
                args.corpus,
                args.graph_validation_root,
                args.branch,
                args.fork_url,
                args.output_dir,
            )
        else:
            result = validate_bundle(
                args.bundle, args.corpus, args.graph_validation_root
            )
    except Exception as error:
        if args.operation == "build":
            output = args.failure_output or Path(f"{args.output_dir}.failure.json")
            atomic_json(output.resolve(), failure_receipt(args, error))
        print(json.dumps({"status": "FAIL_CLOSED", "error": str(error)}, indent=2))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
