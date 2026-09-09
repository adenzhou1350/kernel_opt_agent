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
    packet_paths = {
        "task-a": "task-packet-task-a.json",
        "task-b": "task-packet-task-b.json",
    }
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
        original = root / "original" / f"{filename}.json"
        effective = root / "effective" / f"{filename}.json"
        original.parent.mkdir(exist_ok=True)
        effective.parent.mkdir(exist_ok=True)
        common = {
            "task": label,
            "schedule": ["CONTROL", "COMMUNITY_AUGMENTED"],
            "metric": "TTFT",
        }
        if label == "temporal-suite":
            common["tasks"] = [
                {"task_id": task_id, "packet": {"path": path, "sha256": "pending"}}
                for task_id, path in packet_paths.items()
            ]
            common["protocol"] = {
                "environment_identity": {
                    "path": "environment.json",
                    "sha256": "pending",
                }
            }
        if label == "environment":
            common = {
                "resources": {
                    task_id: {
                        "resource_id": "old-sm120",
                        "gpu_uuids": ["GPU-old-a", "GPU-old-b"],
                    }
                    for task_id in packet_paths
                }
            }
        if label.startswith("sealed-argv:"):
            write(original, common)
            effective.write_bytes(original.read_bytes())
        elif label == "environment":
            write(original, common)
            replaced = copy.deepcopy(common)
            for resource in replaced["resources"].values():
                resource["resource_id"] = "new-sm120"
                resource["gpu_uuids"] = ["GPU-new-a", "GPU-new-b"]
                resource["endpoint"] = "new:22"
            write(effective, replaced)
        else:
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
    packet_hashes = {
        item["label"].split(":", 1)[1]: item["effective"]["sha256"]
        for item in closure
        if item["label"].startswith("task-packet:")
    }
    suite_item = next(item for item in closure if item["label"] == "temporal-suite")
    environment_item = next(item for item in closure if item["label"] == "environment")
    for side in ("original", "effective"):
        suite_path = root / suite_item[side]["path"]
        suite = json.loads(suite_path.read_text(encoding="utf-8"))
        suite["protocol"]["environment_identity"] = {
            "path": Path(environment_item[side]["path"]).name,
            "sha256": environment_item[side]["sha256"],
        }
        for task in suite["tasks"]:
            if side == "effective":
                task["packet"]["sha256"] = packet_hashes[task["task_id"]]
            else:
                old_item = next(
                    item
                    for item in closure
                    if item["label"] == f"task-packet:{task['task_id']}"
                )
                task["packet"]["path"] = Path(old_item["original"]["path"]).name
                task["packet"]["sha256"] = old_item["original"]["sha256"]
        write(suite_path, suite)
        suite_item[side] = identity(suite_path, root)
    value = {
        "schema_version": "community-resource-amendment-v1",
        "generated_at": "2026-09-09T14:00:00Z",
        "cycle_id": "cycle-1",
        "claim_boundary": "RESOURCE_ONLY_NO_TASK_ARM_SCHEDULE_METRIC_OR_ORACLE_CHANGE",
        "original_artifact_root": "original",
        "effective_artifact_root": "effective",
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
        "allowed_resource_pointers": [
            "/resource_id",
            "/endpoint",
            "/gpu_uuids",
            "/protocol/environment_identity/sha256",
            "/resources",
            "/tasks/0/packet/sha256",
            "/tasks/1/packet/sha256",
        ],
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
    with pytest.raises(ValueError, match="deterministic resource substitution"):
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
    with pytest.raises(ValueError, match="deterministic resource substitution"):
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


def test_rejects_root_allowlist_bypass(tmp_path: Path) -> None:
    amendment, value = fixture(tmp_path)
    value["allowed_resource_pointers"] = ["/"]
    write(amendment, value)
    with pytest.raises(ValueError, match="non-resource pointers"):
        validate_amendment(amendment, tmp_path)


def test_rejects_hidden_payload_inside_resource_field(tmp_path: Path) -> None:
    amendment, value = fixture(tmp_path)
    rewrite_effective(
        tmp_path,
        value,
        "task-packet:task-a",
        lambda row: row.__setitem__("resource_id", "new-sm120 hidden-oracle=leak"),
    )
    write(amendment, value)
    with pytest.raises(ValueError, match="deterministic resource substitution"):
        validate_amendment(amendment, tmp_path)


def test_rejects_suite_packet_hash_not_bound_to_effective_packet(
    tmp_path: Path,
) -> None:
    amendment, value = fixture(tmp_path)
    rewrite_effective(
        tmp_path,
        value,
        "temporal-suite",
        lambda row: row["tasks"][0]["packet"].__setitem__("sha256", "0" * 64),
    )
    write(amendment, value)
    with pytest.raises(ValueError, match="deterministic resource substitution"):
        validate_amendment(amendment, tmp_path)


def test_rejects_suite_environment_hash_not_bound_to_effective_environment(
    tmp_path: Path,
) -> None:
    amendment, value = fixture(tmp_path)
    rewrite_effective(
        tmp_path,
        value,
        "temporal-suite",
        lambda row: row["protocol"]["environment_identity"].__setitem__(
            "sha256", "0" * 64
        ),
    )
    write(amendment, value)
    with pytest.raises(ValueError, match="deterministic resource substitution"):
        validate_amendment(amendment, tmp_path)
