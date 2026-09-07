#!/usr/bin/env python3
"""Fail closed between metadata selection and expensive task execution."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.dont_write_bytecode = True

from community_knowledge import (  # noqa: E402
    atomic_json,
    now,
    read_object,
    sha256_file,
)
from schema_utils import validate_instance, validate_json_file  # noqa: E402


MANIFEST_SCHEMA_V1 = "community-materialization-manifest-v1"
MANIFEST_SCHEMA_V2 = "community-materialization-manifest-v2"
MANIFEST_SCHEMA_V3 = "community-materialization-manifest-v3"
MANIFEST_SCHEMAS = {MANIFEST_SCHEMA_V1, MANIFEST_SCHEMA_V2, MANIFEST_SCHEMA_V3}
ASSESSMENT_SCHEMA_V1 = "community-materialized-feasibility-v1"
ASSESSMENT_SCHEMA_V2 = "community-materialized-feasibility-v2"
ASSESSMENT_SCHEMA_V3 = "community-materialized-feasibility-v3"
READY_AVAILABILITY = {"AVAILABLE", "SHARED_NO_DISRUPTION"}
V2_REQUIRED_ROLES = {
    "BASELINE_SOURCE",
    "OPERATOR_HARNESS",
    "WHOLE_MODEL_HARNESS",
    "MODEL_OR_WEIGHTS",
    "RUNTIME_OR_ENVIRONMENT",
    "LIVE_HARDWARE_STATUS",
}


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


def parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def validate_manifest(path: Path, root: Path | None = None) -> dict:
    root = root or repository_root()
    path = path.resolve()
    errors = validate_json_file(
        path, root / "schemas/community_materialization_manifest.schema.json"
    )
    if errors:
        raise ValueError("invalid materialization manifest: " + "; ".join(errors))
    manifest = read_object(path)
    if manifest["schema_version"] not in MANIFEST_SCHEMAS:
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
    if manifest["schema_version"] in {MANIFEST_SCHEMA_V2, MANIFEST_SCHEMA_V3}:
        roles = {item["role"] for item in manifest["artifacts"] if item["required"]}
        missing_roles = sorted(V2_REQUIRED_ROLES - roles)
        if missing_roles:
            raise ValueError(
                "v2 materialization manifest is missing required roles: "
                + ", ".join(missing_roles)
            )
        hardware_match = manifest["hardware_match"]
        minimum_l2 = hardware_match["minimum_l2_cache_mib"]
        maximum_l2 = hardware_match["maximum_l2_cache_mib"]
        if (
            minimum_l2 is not None
            and maximum_l2 is not None
            and minimum_l2 > maximum_l2
        ):
            raise ValueError("minimum L2 cache requirement exceeds maximum")
        resource_status_path = Path(manifest["resource_status"]["path"])
        errors = validate_json_file(
            resource_status_path,
            root / "schemas/community_materialized_resource_status.schema.json",
        )
        if errors:
            raise ValueError(
                "invalid materialized live resource status: " + "; ".join(errors)
            )
        resource_status = read_object(resource_status_path)
        if (
            manifest["schema_version"] == MANIFEST_SCHEMA_V3
            and resource_status["schema_version"]
            != "community-materialized-resource-status-v2"
        ):
            raise ValueError("v3 manifest requires per-device resource status v2")
        resource_ids = [item["resource_id"] for item in resource_status["resources"]]
        if len(resource_ids) != len(set(resource_ids)):
            raise ValueError("duplicate live resource status id")
        if manifest["schema_version"] == MANIFEST_SCHEMA_V3:
            for resource in resource_status["resources"]:
                device_indices = [item["gpu_index"] for item in resource["devices"]]
                if len(device_indices) != len(set(device_indices)):
                    raise ValueError("duplicate per-device GPU index")
                if set(device_indices) != set(resource["gpu_indices"]):
                    raise ValueError(
                        "per-device GPU indices do not match resource indices"
                    )
                if not set(resource["excluded_gpu_indices"]).issubset(
                    set(device_indices)
                ):
                    raise ValueError(
                        "excluded GPU index is absent from per-device status"
                    )
                process_count = sum(
                    item["active_compute_process_count"] for item in resource["devices"]
                )
                if process_count != resource["active_compute_process_count"]:
                    raise ValueError(
                        "aggregate active compute process count does not match devices"
                    )
        status_age = parse_timestamp(manifest["generated_at"]) - parse_timestamp(
            resource_status["observed_at"]
        )
        maximum_age = hardware_match["maximum_resource_status_age_seconds"]
        if status_age.total_seconds() < 0:
            raise ValueError("live resource status postdates the manifest")
        if status_age.total_seconds() > maximum_age:
            raise ValueError("live resource status is too old for the manifest")
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
    manifest: dict,
    task: dict,
    screen_item: dict,
    profile: dict,
    live_status: dict | None,
) -> tuple[list[str], list[dict]]:
    requested = set(manifest["target_resource_ids"])
    preselected = set(screen_item["ready_resource_ids"])
    target_architecture = task["hardware"]["compute_capability"].lower()
    target_memory = float(task["hardware"]["memory_gib"])
    hardware_match = manifest.get("hardware_match")
    resources = {item["resource_id"]: item for item in profile["resources"]}
    if len(resources) != len(profile["resources"]):
        raise ValueError("duplicate execution profile resource id")
    live_resources = (
        {item["resource_id"]: item for item in live_status["resources"]}
        if live_status is not None
        else {}
    )
    matched = []
    diagnostics = []
    for resource_id in sorted(requested):
        reasons = []
        diagnostic_details = {}
        resource = resources.get(resource_id)
        if resource is None:
            diagnostics.append(
                {
                    "resource_id": resource_id,
                    "matched": False,
                    "reasons": ["PROFILE_RESOURCE_MISSING"],
                }
            )
            continue
        if resource_id not in preselected:
            reasons.append("NOT_READY_AT_PRESELECTION")
        if resource["availability"] not in READY_AVAILABILITY:
            reasons.append("RESOURCE_NOT_AVAILABLE")
        if resource["vendor"] != "NVIDIA":
            reasons.append("VENDOR_MISMATCH")
        if resource["architecture"].lower() != target_architecture:
            reasons.append("ARCHITECTURE_MISMATCH")
        if float(resource["memory_gib_per_gpu"]) < target_memory:
            reasons.append("INSUFFICIENT_MEMORY")
        if hardware_match is not None:
            live_resource = live_resources.get(resource_id)
            if live_resource is None:
                reasons.append("LIVE_RESOURCE_MISSING")
                diagnostics.append(
                    {
                        "resource_id": resource_id,
                        "matched": False,
                        "reasons": sorted(set(reasons)),
                    }
                )
                continue
            if live_resource["availability"] not in READY_AVAILABILITY:
                reasons.append("LIVE_RESOURCE_NOT_AVAILABLE")
            if live_resource["vendor"] != resource["vendor"]:
                reasons.append("PROFILE_LIVE_VENDOR_MISMATCH")
            if live_resource["architecture"].lower() != target_architecture:
                reasons.append("ARCHITECTURE_MISMATCH")
            if (
                live_resource["architecture"].lower()
                != resource["architecture"].lower()
            ):
                reasons.append("PROFILE_LIVE_ARCHITECTURE_MISMATCH")
            if float(live_resource["memory_gib_per_gpu"]) < target_memory:
                reasons.append("INSUFFICIENT_LIVE_MEMORY")
            allowed_names = {
                item.casefold() for item in hardware_match["device_names_any"]
            }
            resource_name = live_resource["device_name"]
            if resource_name.casefold() not in allowed_names:
                reasons.append("DEVICE_NAME_MISMATCH")
            profile_name = resource.get("device_name")
            if (
                profile_name is not None
                and profile_name.casefold() != resource_name.casefold()
            ):
                reasons.append("PROFILE_LIVE_DEVICE_MISMATCH")
            required_capabilities = set(hardware_match["required_capabilities_all"])
            if not required_capabilities.issubset(set(resource["capabilities"])):
                reasons.append("CAPABILITY_MISMATCH")
            minimum_l2 = hardware_match["minimum_l2_cache_mib"]
            maximum_l2 = hardware_match["maximum_l2_cache_mib"]
            if minimum_l2 is not None or maximum_l2 is not None:
                l2_cache = live_resource["l2_cache_mib"]
                if l2_cache is None:
                    reasons.append("L2_CACHE_NOT_DECLARED")
                else:
                    if minimum_l2 is not None and float(l2_cache) < float(minimum_l2):
                        reasons.append("L2_CACHE_BELOW_MINIMUM")
                    if maximum_l2 is not None and float(l2_cache) > float(maximum_l2):
                        reasons.append("L2_CACHE_ABOVE_MAXIMUM")
            profile_l2 = resource.get("l2_cache_mib")
            if (
                profile_l2 is not None
                and live_resource["l2_cache_mib"] is not None
                and float(profile_l2) != float(live_resource["l2_cache_mib"])
            ):
                reasons.append("PROFILE_LIVE_L2_MISMATCH")
            if manifest["schema_version"] == MANIFEST_SCHEMA_V3:
                excluded = set(live_resource["excluded_gpu_indices"])
                candidates = [
                    item
                    for item in live_resource["devices"]
                    if item["gpu_index"] not in excluded
                ]
                required_gpu_count = hardware_match["minimum_ready_gpu_count"]
                if len(candidates) < required_gpu_count:
                    reasons.append("INSUFFICIENT_NON_EXCLUDED_GPU_COUNT")
                utilization_limit = hardware_match["maximum_gpu_utilization_percent"]
                memory_limit = hardware_match["maximum_used_memory_mib_per_gpu"]
                require_idle = hardware_match["require_zero_active_compute_processes"]
                ready_devices = []
                device_failure_reasons = set()
                device_diagnostics = []
                for device in live_resource["devices"]:
                    device_reasons = []
                    if device["gpu_index"] in excluded:
                        device_reasons.append("EXPLICITLY_EXCLUDED")
                        device_diagnostics.append(
                            {
                                "gpu_index": device["gpu_index"],
                                "eligible": False,
                                "reasons": device_reasons,
                            }
                        )
                        continue
                    device_ready = True
                    if device["utilization_percent"] > utilization_limit:
                        device_failure_reasons.add("GPU_UTILIZATION_ABOVE_MAXIMUM")
                        device_reasons.append("GPU_UTILIZATION_ABOVE_MAXIMUM")
                        device_ready = False
                    if (
                        memory_limit is not None
                        and device["memory_used_mib"] > memory_limit
                    ):
                        device_failure_reasons.add("GPU_MEMORY_USE_ABOVE_MAXIMUM")
                        device_reasons.append("GPU_MEMORY_USE_ABOVE_MAXIMUM")
                        device_ready = False
                    if require_idle and device["active_compute_process_count"] != 0:
                        device_failure_reasons.add("GPU_HAS_ACTIVE_COMPUTE_PROCESS")
                        device_reasons.append("GPU_HAS_ACTIVE_COMPUTE_PROCESS")
                        device_ready = False
                    if device_ready:
                        ready_devices.append(device)
                    device_diagnostics.append(
                        {
                            "gpu_index": device["gpu_index"],
                            "eligible": device_ready,
                            "reasons": sorted(device_reasons),
                        }
                    )
                if len(ready_devices) < required_gpu_count:
                    reasons.extend(sorted(device_failure_reasons))
                    reasons.append("INSUFFICIENT_READY_GPU_COUNT")
                diagnostic_details = {
                    "eligible_gpu_indices": sorted(
                        item["gpu_index"] for item in ready_devices
                    ),
                    "device_diagnostics": sorted(
                        device_diagnostics, key=lambda item: item["gpu_index"]
                    ),
                }
        reasons = sorted(set(reasons))
        is_match = not reasons
        diagnostics.append(
            {
                "resource_id": resource_id,
                "matched": is_match,
                "reasons": reasons,
                **diagnostic_details,
            }
        )
        if is_match:
            matched.append(resource_id)
    return sorted(matched), diagnostics


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
    live_status = (
        read_object(Path(manifest["resource_status"]["path"]))
        if manifest["schema_version"] in {MANIFEST_SCHEMA_V2, MANIFEST_SCHEMA_V3}
        else None
    )
    matched, resource_diagnostics = matching_resources(
        manifest, task, screen_item, profile, live_status
    )

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
        "schema_version": {
            MANIFEST_SCHEMA_V1: ASSESSMENT_SCHEMA_V1,
            MANIFEST_SCHEMA_V2: ASSESSMENT_SCHEMA_V2,
            MANIFEST_SCHEMA_V3: ASSESSMENT_SCHEMA_V3,
        }[manifest["schema_version"]],
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
    if manifest["schema_version"] in {MANIFEST_SCHEMA_V2, MANIFEST_SCHEMA_V3}:
        result["resource_match_diagnostics"] = resource_diagnostics
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
