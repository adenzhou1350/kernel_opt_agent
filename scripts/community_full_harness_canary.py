#!/usr/bin/env python3
"""Validate a complete two-arm harness dry-run before formal dispatch."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from community_knowledge import read_object, sha256_file
from schema_utils import validate_json_file


SCHEMA = "community_full_harness_canary.schema.json"
ARMS = {"CONTROL", "COMMUNITY_AUGMENTED"}


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def resolve_inside(base: Path, relative: str) -> Path:
    base = base.resolve()
    path = (base / relative).resolve()
    try:
        path.relative_to(base)
    except ValueError as error:
        raise ValueError(
            f"identity path escapes the artifact root: {relative}"
        ) from error
    return path


def validate_identity(base: Path, value: dict, label: str) -> Path:
    path = resolve_inside(base, value["path"])
    if not path.is_file():
        raise FileNotFoundError(f"{label} is missing: {path}")
    if sha256_file(path) != value["sha256"]:
        raise ValueError(f"{label} hash changed: {value['path']}")
    return path


def same_identity(left: dict, right: dict) -> bool:
    return left.get("path") == right.get("path") and left.get("sha256") == right.get(
        "sha256"
    )


def validate_canary(
    canary_path: Path,
    artifact_root: Path,
    *,
    expected_task: dict | None = None,
    expected_cycle_id: str | None = None,
) -> dict:
    errors = validate_json_file(canary_path, repository_root() / "schemas" / SCHEMA)
    if errors:
        raise ValueError("invalid full-harness canary schema: " + "; ".join(errors))
    canary = read_object(canary_path)
    artifact_root = artifact_root.resolve()
    if expected_cycle_id is not None and canary["cycle_id"] != expected_cycle_id:
        raise ValueError("full-harness canary cycle differs from readiness gate")

    bindings = canary["execution_bindings"]
    if expected_task is not None:
        if canary["task_id"] != expected_task["task_id"]:
            raise ValueError(
                "full-harness canary task identity differs from readiness gate"
            )
        for field in (
            "harness_manifest",
            "workload",
            "runner",
            "sealed_argv",
            "output_schema",
        ):
            expected = expected_task[field]
            if expected is None or not same_identity(bindings[field], expected):
                raise ValueError(
                    f"full-harness canary {field} differs from readiness gate"
                )

    for field, identity in bindings.items():
        validate_identity(artifact_root, identity, f"canary {field.replace('_', ' ')}")
    output_schema = validate_identity(
        artifact_root, bindings["output_schema"], "canary output schema"
    )

    runs = canary["runs"]
    if {run["arm"] for run in runs} != ARMS:
        raise ValueError("full-harness canary requires exactly one run for each arm")
    validated_artifacts = len(bindings)
    for run in runs:
        arm = run["arm"]
        result_path = validate_identity(
            artifact_root, run["result"], f"{arm} full-harness result"
        )
        validated_artifacts += 1
        result_errors = validate_json_file(result_path, output_schema)
        if result_errors:
            raise ValueError(
                f"{arm} full-harness result violates output schema: "
                + "; ".join(result_errors)
            )
        result = read_object(result_path)
        if result.get("task_id") != canary["task_id"]:
            raise ValueError(f"{arm} result task identity differs")
        if result.get("arm") != arm:
            raise ValueError(f"{arm} result arm differs")
        if result.get("mode") != "FRAMEWORK_EXECUTION":
            raise ValueError(f"{arm} canary is not a framework execution")
        if result.get("request_count") != run["request_count"]:
            raise ValueError(f"{arm} request count differs")
        checks = result.get("contract_checks")
        if (
            not isinstance(checks, dict)
            or not checks
            or not all(value is True for value in checks.values())
        ):
            raise ValueError(f"{arm} did not pass every output contract check")

        sidecar_paths = [
            validate_identity(artifact_root, identity, f"{arm} rank sidecar {index}")
            for index, identity in enumerate(run["rank_sidecars"])
        ]
        validated_artifacts += len(sidecar_paths)
        if len(sidecar_paths) != run["required_rank_count"]:
            raise ValueError(f"{arm} rank sidecar count differs")
        if run["required_rank_count"]:
            sidecars = [read_object(path) for path in sidecar_paths]
            ranks = {sidecar.get("rank") for sidecar in sidecars}
            if ranks != set(range(run["required_rank_count"])):
                raise ValueError(f"{arm} rank sidecar identities are incomplete")
            for sidecar in sidecars:
                if sidecar.get("request_count_observed") != run["request_count"]:
                    raise ValueError(f"{arm} rank sidecar request count differs")
            first = sidecars[0]
            for sidecar in sidecars[1:]:
                if sidecar.get("committed_token_digests_by_request") != first.get(
                    "committed_token_digests_by_request"
                ):
                    raise ValueError(f"{arm} rank token digests differ")
                if sidecar.get("accepted_lengths_by_request") != first.get(
                    "accepted_lengths_by_request"
                ):
                    raise ValueError(f"{arm} rank accepted lengths differ")
                if sidecar.get("terminal_state_digest") != first.get(
                    "terminal_state_digest"
                ):
                    raise ValueError(f"{arm} rank terminal digests differ")
            expected_digests = [
                first["terminal_state_digest"]
                for _ in range(run["required_rank_count"])
            ]
            if result.get("rank_terminal_digests") != expected_digests:
                raise ValueError(f"{arm} result does not bind rank terminal digests")

    return {
        "status": "PASS",
        "cycle_id": canary["cycle_id"],
        "task_id": canary["task_id"],
        "arms": sorted(ARMS),
        "validated_artifacts": validated_artifacts,
        "full_harness_canary_ready": True,
        "formal_claim_created": False,
        "formal_observation_created": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--canary", required=True, type=Path)
    parser.add_argument("--artifact-root", required=True, type=Path)
    args = parser.parse_args()
    result = validate_canary(args.canary, args.artifact_root)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
