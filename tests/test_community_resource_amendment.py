#!/usr/bin/env python3
"""Exercise resource-only cohort amendment integrity gates."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from community_knowledge import sha256_file  # noqa: E402
from community_resource_amendment import validate_amendment  # noqa: E402


@pytest.fixture(autouse=True)
def canonical_readiness_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "community_resource_amendment.validate_readiness",
        lambda _path, _root: {
            "state": "PRE_GPU_GATE_BLOCKED",
            "eligible_to_execute_arms": False,
        },
    )


def write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def identity(path: Path, root: Path) -> dict:
    return {"path": path.relative_to(root).as_posix(), "sha256": sha256_file(path)}


def fixture(root: Path) -> tuple[Path, dict]:
    readiness = root / "readiness.json"
    feasibility = root / "feasibility.json"
    write(
        readiness,
        {
            "cycle_id": "cycle-1",
            "state": "PRE_GPU_GATE_BLOCKED",
            "eligible_to_execute_arms": False,
            "task_freezes": {"task-a": {}, "task-b": {}},
        },
    )
    write(
        feasibility,
        {
            "cycle_id": "cycle-1",
            "decision": (
                "RESOURCE_CAPACITY_COMPATIBLE_MIGRATION_NOT_YET_EXECUTION_READY"
            ),
        },
    )
    closure = []
    for label in (
        "temporal-suite",
        "environment",
        "task-packet:task-a",
        "server-contract:task-a",
        "sealed-argv:task-a",
        "task-packet:task-b",
        "server-contract:task-b",
        "sealed-argv:task-b",
    ):
        filename = label.replace(":", "-")
        original = root / f"{filename}-old.json"
        effective = root / f"{filename}-new.json"
        common = {"task": label, "schedule": ["CONTROL", "COMMUNITY_AUGMENTED"], "metric": "TTFT"}
        write(
            original,
            common
            | {
                "resource_id": "old-sm120",
                "endpoint": "old:22",
                "gpu_uuids": ["GPU-old-a", "GPU-old-b"],
            },
        )
        write(
            effective,
            common
            | {
                "resource_id": "new-sm120",
                "endpoint": "new:22",
                "gpu_uuids": ["GPU-new-a", "GPU-new-b"],
            },
        )
        closure.append(
            {
                "label": label,
                "original": identity(original, root),
                "effective": identity(effective, root),
            }
        )
    value = {
        "schema_version": "community-resource-amendment-v1",
        "generated_at": "2026-09-09T14:00:00Z",
        "cycle_id": "cycle-1",
        "claim_boundary": "RESOURCE_ONLY_NO_TASK_ARM_SCHEDULE_METRIC_OR_ORACLE_CHANGE",
        "original_readiness": identity(readiness, root),
        "feasibility_audit": identity(feasibility, root),
        "execution_state": {
            "formal_entries_executed": 0,
            "hidden_oracle_exposed": False,
            "gpu_dispatch_authorized": False,
        },
        "old_resource": {
            "resource_id": "old-sm120",
            "endpoint": "old:22",
            "gpu_uuids": ["GPU-old-a", "GPU-old-b"],
        },
        "new_resource": {
            "resource_id": "new-sm120",
            "endpoint": "new:22",
            "gpu_uuids": ["GPU-new-a", "GPU-new-b"],
        },
        "allowed_resource_pointers": ["/resource_id", "/endpoint", "/gpu_uuids"],
        "closure": closure,
    }
    amendment = root / "amendment.json"
    write(amendment, value)
    return amendment, value


def rewrite_effective(root: Path, value: dict, label: str, mutate) -> None:
    item = next(row for row in value["closure"] if row["label"] == label)
    path = root / item["effective"]["path"]
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutate(payload)
    write(path, payload)
    item["effective"] = identity(path, root)


def test_valid_resource_only_amendment(tmp_path: Path) -> None:
    amendment, _ = fixture(tmp_path)
    result = validate_amendment(amendment, tmp_path)
    assert result["status"] == "PASS_RESOURCE_ONLY_AMENDMENT"
    assert result["closure_items"] == 8
    assert result["gpu_dispatch_authorized"] is False


def test_rejects_non_resource_drift(tmp_path: Path) -> None:
    amendment, value = fixture(tmp_path)
    rewrite_effective(
        tmp_path,
        value,
        "task-packet:task-a",
        lambda row: row.__setitem__("metric", "TPOT"),
    )
    write(amendment, value)
    with pytest.raises(ValueError, match="non-resource drift"):
        validate_amendment(amendment, tmp_path)


def test_rejects_stale_old_identity(tmp_path: Path) -> None:
    amendment, value = fixture(tmp_path)
    rewrite_effective(
        tmp_path,
        value,
        "task-packet:task-a",
        lambda row: row.__setitem__("endpoint", "old:22"),
    )
    write(amendment, value)
    with pytest.raises(ValueError, match="retains old resource"):
        validate_amendment(amendment, tmp_path)


def test_rejects_missing_new_identity(tmp_path: Path) -> None:
    amendment, value = fixture(tmp_path)
    for item in value["closure"]:
        path = tmp_path / item["effective"]["path"]
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["gpu_uuids"] = ["GPU-new-a"]
        write(path, payload)
        item["effective"] = identity(path, tmp_path)
    write(amendment, value)
    with pytest.raises(ValueError, match="every new resource"):
        validate_amendment(amendment, tmp_path)


def test_rejects_reused_gpu_identity(tmp_path: Path) -> None:
    amendment, value = fixture(tmp_path)
    value["new_resource"]["gpu_uuids"][0] = "GPU-old-a"
    write(amendment, value)
    with pytest.raises(ValueError, match="must be distinct"):
        validate_amendment(amendment, tmp_path)


def test_rejects_changed_identity_hash(tmp_path: Path) -> None:
    amendment, value = fixture(tmp_path)
    value["closure"][0]["effective"]["sha256"] = "0" * 64
    write(amendment, value)
    with pytest.raises(ValueError, match="hash changed"):
        validate_amendment(amendment, tmp_path)


def test_rejects_incomplete_effective_closure(tmp_path: Path) -> None:
    amendment, value = fixture(tmp_path)
    value["closure"] = value["closure"][:-1]
    write(amendment, value)
    with pytest.raises(ValueError, match="complete task resource closure"):
        validate_amendment(amendment, tmp_path)
