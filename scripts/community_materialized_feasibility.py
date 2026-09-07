#!/usr/bin/env python3
"""Fail closed between metadata selection and expensive task execution."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True

from community_knowledge import (  # noqa: E402
    atomic_json,
    now,
    read_object,
    sha256_file,
)
from schema_utils import validate_instance, validate_json_file  # noqa: E402


MANIFEST_SCHEMA = "community-materialization-manifest-v1"
ASSESSMENT_SCHEMA = "community-materialized-feasibility-v1"
READY_AVAILABILITY = {"AVAILABLE", "SHARED_NO_DISRUPTION"}


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def absolute_identity(path: Path) -> dict:
    resolved = path.resolve()
    return {"path": resolved.as_posix(), "sha256": sha256_file(resolved)}


def validate_identity(identity: dict, label: str) -> Path:
    path = Path(identity["path"])
    if not path.is_file():
        raise ValueError(f"{label} is missing: {path}")
    if sha256_file(path) != identity["sha256"]:
        raise ValueError(f"{label} changed: {path}")
    return path


def validate_manifest(path: Path, root: Path | None = None) -> dict:
    root = root or repository_root()
    path = path.resolve()
    errors = validate_json_file(
        path, root / "schemas/community_materialization_manifest.schema.json"
    )
    if errors:
        raise ValueError("invalid materialization manifest: " + "; ".join(errors))
    manifest = read_object(path)
    if manifest["schema_version"] != MANIFEST_SCHEMA:
        raise ValueError("unsupported materialization manifest")
    for label in ("task", "preselection_screen", "execution_profile"):
        validate_identity(manifest[label], f"manifest {label}")
    if manifest["resource_status"] is not None:
        validate_identity(manifest["resource_status"], "manifest resource status")
    seen_roles = set()
    for artifact in manifest["artifacts"]:
        role = artifact["role"]
        if role in seen_roles:
            raise ValueError(f"duplicate materialization artifact role: {role}")
        seen_roles.add(role)
        for identity in artifact["evidence"]:
            validate_identity(identity, f"materialization artifact {role}")
    return manifest


def load_validated_inputs(manifest: dict, root: Path) -> tuple[dict, dict, dict]:
    task_path = Path(manifest["task"]["path"])
    screen_path = Path(manifest["preselection_screen"]["path"])
    profile_path = Path(manifest["execution_profile"]["path"])
    checks = (
        (task_path, "community_heldout_task.schema.json", "task"),
        (screen_path, "community_feasibility_screen.schema.json", "screen"),
        (profile_path, "community_execution_profile.schema.json", "profile"),
    )
    for path, schema, label in checks:
        errors = validate_json_file(path, root / "schemas" / schema)
        if errors:
            raise ValueError(f"invalid materialized {label}: " + "; ".join(errors))
    return read_object(task_path), read_object(screen_path), read_object(profile_path)


def matching_resources(
    manifest: dict, task: dict, screen_item: dict, profile: dict
) -> list[str]:
    requested = set(manifest["target_resource_ids"])
    preselected = set(screen_item["ready_resource_ids"])
    target_architecture = task["hardware"]["compute_capability"].lower()
    target_memory = float(task["hardware"]["memory_gib"])
    matched = []
    for resource in profile["resources"]:
        resource_id = resource["resource_id"]
        if resource_id not in requested or resource_id not in preselected:
            continue
        if resource["availability"] not in READY_AVAILABILITY:
            continue
        if resource["vendor"] != "NVIDIA":
            continue
        if resource["architecture"].lower() != target_architecture:
            continue
        if float(resource["memory_gib_per_gpu"]) < target_memory:
            continue
        matched.append(resource_id)
    return sorted(matched)


def build_assessment(manifest_path: Path, root: Path | None = None) -> dict:
    root = root or repository_root()
    manifest_path = manifest_path.resolve()
    manifest = validate_manifest(manifest_path, root)
    task, screen, profile = load_validated_inputs(manifest, root)
    candidate = manifest["candidate"]
    screen_items = [
        item
        for item in screen["items"]
        if item["repository"] == candidate["repository"]
        and int(item["pr_number"]) == int(candidate["pr_number"])
    ]
    if len(screen_items) != 1:
        raise ValueError("materialized candidate does not resolve to one screen item")
    screen_item = screen_items[0]
    matched = matching_resources(manifest, task, screen_item, profile)

    required = [item for item in manifest["artifacts"] if item["required"]]
    missing = [item for item in required if item["status"] == "MISSING"]
    unverified = [item for item in required if item["status"] == "UNVERIFIED"]
    ready = [item for item in required if item["status"] == "READY"]
    blockers = []
    if screen_item["status"] != "ELIGIBLE":
        blockers.append(f"PRESELECTION_{screen_item['status']}")
    if not matched:
        blockers.append("NO_MATERIALIZED_RESOURCE_MATCH")
    blockers.extend(f"MISSING_{item['role']}" for item in missing)
    blockers.extend(f"UNVERIFIED_{item['role']}" for item in unverified)
    if manifest["resource_status"] is None:
        blockers.append("MISSING_LIVE_RESOURCE_STATUS")
    if (
        candidate["purpose"] == "NEW_UPSTREAM_WORK"
        and candidate["existing_reference_pr"] is not None
    ):
        blockers.append("EXISTING_UPSTREAM_PR_TARGET")
    blockers = sorted(set(blockers))

    if screen_item["status"] != "ELIGIBLE":
        decision = "PRESELECTION_BLOCKED"
    elif not matched or "MISSING_LIVE_RESOURCE_STATUS" in blockers:
        decision = "RESOURCE_BLOCKED"
    elif missing or unverified:
        decision = "HARNESS_BLOCKED"
    elif "EXISTING_UPSTREAM_PR_TARGET" in blockers:
        decision = "UPSTREAM_DUPLICATE"
    else:
        decision = "ELIGIBLE_FOR_SUPERVISOR_REVIEW"

    result = {
        "schema_version": ASSESSMENT_SCHEMA,
        "generated_at": now(),
        "claim_boundary": (
            "POST_MATERIALIZATION_GATE_NOT_PERFORMANCE_EVIDENCE_OR_DISPATCH_APPROVAL"
        ),
        "registration": "POST_MATERIALIZATION",
        "inputs": {
            "manifest": absolute_identity(manifest_path),
            "task": manifest["task"],
            "preselection_screen": manifest["preselection_screen"],
            "execution_profile": manifest["execution_profile"],
            "resource_status": manifest["resource_status"],
        },
        "candidate": {
            **candidate,
            "task_id": task["task_id"],
        },
        "matched_resource_ids": matched,
        "artifact_inventory": {
            "required_count": len(required),
            "ready_required_count": len(ready),
            "missing_required_count": len(missing),
            "unverified_required_count": len(unverified),
        },
        "decision": decision,
        "blockers": blockers,
        "allowed_actions": {
            "read_only_research": True,
            "prepare_missing_artifacts": decision
            in {
                "HARNESS_BLOCKED",
                "RESOURCE_BLOCKED",
            },
            "request_supervisor_review": decision == "ELIGIBLE_FOR_SUPERVISOR_REVIEW",
            "dispatch_gpu": False,
            "package_upstream_pr": (
                decision == "ELIGIBLE_FOR_SUPERVISOR_REVIEW"
                and candidate["purpose"] == "NEW_UPSTREAM_WORK"
                and candidate["existing_reference_pr"] is None
            ),
        },
    }
    errors = validate_instance(
        result,
        read_object(root / "schemas/community_materialized_feasibility.schema.json"),
    )
    if errors:
        raise ValueError("invalid materialized feasibility: " + "; ".join(errors))
    return result


def validate_assessment(path: Path, root: Path | None = None) -> dict:
    root = root or repository_root()
    path = path.resolve()
    errors = validate_json_file(
        path, root / "schemas/community_materialized_feasibility.schema.json"
    )
    if errors:
        raise ValueError("invalid materialized feasibility: " + "; ".join(errors))
    observed = read_object(path)
    manifest_path = Path(observed["inputs"]["manifest"]["path"])
    expected = build_assessment(manifest_path, root)
    observed_stable = {
        key: value for key, value in observed.items() if key != "generated_at"
    }
    expected_stable = {
        key: value for key, value in expected.items() if key != "generated_at"
    }
    if observed_stable != expected_stable:
        raise ValueError("materialized feasibility is stale or was edited")
    return {
        "status": "PASS",
        "decision": observed["decision"],
        **observed["artifact_inventory"],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    build = commands.add_parser("build")
    build.add_argument("--manifest", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("--assessment", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.operation == "build":
        result = build_assessment(args.manifest)
        atomic_json(args.output.resolve(), result)
        output = {"status": "PASS", "assessment": str(args.output.resolve()), **result}
    else:
        output = validate_assessment(args.assessment)
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
