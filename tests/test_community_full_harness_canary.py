#!/usr/bin/env python3
"""Exercise the full-harness dry-run admission gate."""

from __future__ import annotations

import copy
import json
import sys
import tempfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from community_full_harness_canary import validate_canary  # noqa: E402
from community_knowledge import sha256_file  # noqa: E402


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def identity(path: Path, base: Path) -> dict:
    return {"path": path.relative_to(base).as_posix(), "sha256": sha256_file(path)}


def build_fixture(base: Path) -> tuple[Path, dict]:
    task_id = "stable-task"
    binding_paths = {}
    for name in ("harness_manifest", "workload", "runner", "sealed_argv"):
        path = base / f"{name}.json"
        write_json(path, {"task_id": task_id, "name": name})
        binding_paths[name] = path
    output_schema = base / "output-schema.json"
    write_json(
        output_schema,
        {
            "type": "object",
            "required": [
                "task_id",
                "arm",
                "mode",
                "request_count",
                "rank_terminal_digests",
                "contract_checks",
            ],
            "properties": {
                "task_id": {"const": task_id},
                "arm": {"enum": ["CONTROL", "COMMUNITY_AUGMENTED"]},
                "mode": {"const": "FRAMEWORK_EXECUTION"},
                "request_count": {"const": 2},
                "rank_terminal_digests": {
                    "type": "array",
                    "minItems": 2,
                    "maxItems": 2,
                    "items": {"type": "string"},
                },
                "contract_checks": {
                    "type": "object",
                    "required": ["requests", "ranks"],
                    "properties": {
                        "requests": {"const": True},
                        "ranks": {"const": True},
                    },
                },
            },
        },
    )
    binding_paths["output_schema"] = output_schema
    digest = "a" * 64
    runs = []
    for arm in ("CONTROL", "COMMUNITY_AUGMENTED"):
        result = base / arm.lower() / "result.json"
        write_json(
            result,
            {
                "task_id": task_id,
                "arm": arm,
                "mode": "FRAMEWORK_EXECUTION",
                "request_count": 2,
                "rank_terminal_digests": [digest, digest],
                "contract_checks": {"requests": True, "ranks": True},
            },
        )
        sidecars = []
        for rank in (0, 1):
            sidecar = base / arm.lower() / f"rank-{rank}.json"
            write_json(
                sidecar,
                {
                    "rank": rank,
                    "request_count_observed": 2,
                    "committed_token_digests_by_request": {"0": "x", "1": "y"},
                    "accepted_lengths_by_request": {"0": [1], "1": [1]},
                    "terminal_state_digest": digest,
                },
            )
            sidecars.append(identity(sidecar, base))
        runs.append(
            {
                "arm": arm,
                "process_exit_code": 0,
                "result": identity(result, base),
                "required_rank_count": 2,
                "rank_sidecars": sidecars,
                "request_count": 2,
                "output_schema_valid": True,
                "all_contract_checks_passed": True,
            }
        )
    canary = {
        "schema_version": "community-full-harness-canary-v1",
        "generated_at": "2026-09-10T00:00:00Z",
        "cycle_id": "cycle-1",
        "task_id": task_id,
        "claim_boundary": "FULL_HARNESS_DRY_RUN_NOT_FORMAL_CLAIM_OR_PERFORMANCE_EVIDENCE",
        "execution_bindings": {
            name: identity(path, base) for name, path in binding_paths.items()
        },
        "runs": runs,
        "formal_claim_created": False,
        "formal_observation_created": False,
        "hidden_oracle_exposed": False,
    }
    path = base / "canary.json"
    write_json(path, canary)
    return path, canary


def test_full_harness_canary_recomputes_results_and_rank_consistency() -> None:
    with tempfile.TemporaryDirectory() as temp:
        base = Path(temp)
        path, canary = build_fixture(base)
        result = validate_canary(path, base, expected_cycle_id="cycle-1")
        assert result["full_harness_canary_ready"] is True
        assert result["validated_artifacts"] == 11

        failed_check = copy.deepcopy(canary)
        result_path = base / failed_check["runs"][0]["result"]["path"]
        payload = json.loads(result_path.read_text(encoding="utf-8"))
        payload["contract_checks"]["ranks"] = False
        write_json(result_path, payload)
        failed_check["runs"][0]["result"]["sha256"] = sha256_file(result_path)
        write_json(path, failed_check)
        with pytest.raises(ValueError, match="violates output schema"):
            validate_canary(path, base)


def test_full_harness_canary_rejects_one_arm_and_rank_drift() -> None:
    with tempfile.TemporaryDirectory() as temp:
        base = Path(temp)
        path, canary = build_fixture(base)

        duplicate_arm = copy.deepcopy(canary)
        duplicate_arm["runs"][1]["arm"] = "CONTROL"
        write_json(path, duplicate_arm)
        with pytest.raises(ValueError, match="exactly one run for each arm"):
            validate_canary(path, base)

        path, canary = build_fixture(base)
        sidecar_identity = canary["runs"][0]["rank_sidecars"][1]
        sidecar_path = base / sidecar_identity["path"]
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        sidecar["accepted_lengths_by_request"]["1"] = [2]
        write_json(sidecar_path, sidecar)
        sidecar_identity["sha256"] = sha256_file(sidecar_path)
        write_json(path, canary)
        with pytest.raises(ValueError, match="rank accepted lengths differ"):
            validate_canary(path, base)
