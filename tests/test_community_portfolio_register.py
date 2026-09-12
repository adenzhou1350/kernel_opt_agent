#!/usr/bin/env python3
"""Focused tests for explicit prospective portfolio registration."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from artifact_io import sha256_file  # noqa: E402
from community_portfolio_register import build, write_once  # noqa: E402


LANES = (
    ("VLLM_OPTIMIZATION", "01a043a4-2c53-7603-b44f-2c76d5c7ad0b"),
    ("VLLM_A800_ADAPTATION", "01a0812c-2e88-7e40-bf5c-94ddfdbf8463"),
    ("MOONCAKE_OPTIMIZATION", "01a0824c-1440-7a73-b539-9f1f29976c1e"),
    ("SGLANG_OPTIMIZATION", "01a08251-190c-7b33-8977-face2c8875ce"),
)


def dump(path: Path, value: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return path


def ledger(path: Path, cycle: str, task: str, started: str) -> Path:
    evidence = dump(path.parent / f"{cycle}-evidence.json", {"cycle": cycle})
    return dump(
        path,
        {
            "schema_version": "community-work-cycle-v1",
            "cycle_id": cycle,
            "task_id": task,
            "started_at": started,
            "observation_mode": "PROSPECTIVE_EXACT",
            "claim_boundary": "WORK_CYCLE_TIMING_NOT_PERFORMANCE_CAUSALITY",
            "minimum_material_speedup": 1.02,
            "spans": [],
            "milestones": [
                {
                    "kind": "FIRST_CANDIDATE_PROPOSED",
                    "at": started,
                    "evidence": [
                        {"path": evidence.as_posix(), "sha256": sha256_file(evidence)}
                    ],
                }
            ],
            "outcome": {
                "correctness": "NOT_RUN",
                "best_speedup": None,
                "best_whole_model_speedup": None,
                "upstream_ready": False,
                "pull_request_url": None,
                "merged": False,
            },
        },
    )


def manifest(tmp_path: Path) -> Path:
    lanes = []
    for index, (lane_id, thread_id) in enumerate(LANES):
        item = ledger(
            tmp_path / f"base-{index}.json",
            f"base-{index}",
            f"task-{index}",
            "2026-09-12T01:30:00Z",
        )
        lanes.append(
            {
                "lane_id": lane_id,
                "thread_id": thread_id,
                "work_cycle_ledgers": [
                    {"path": item.as_posix(), "sha256": sha256_file(item)}
                ],
            }
        )
    topology = ROOT / "knowledge/community/lane_topology.v3.json"
    return dump(
        tmp_path / "manifest.json",
        {
            "schema_version": "community-portfolio-manifest-v1",
            "claim_boundary": "EXPLICIT_LEDGER_SELECTION_NOT_CAUSAL_COMPARISON",
            "lane_topology_identity": {
                "path": topology.as_posix(),
                "sha256": sha256_file(topology),
            },
            "lanes": lanes,
        },
    )


def test_registers_valid_ledger_in_explicit_lane(tmp_path: Path) -> None:
    base = manifest(tmp_path)
    candidate = ledger(
        tmp_path / "candidate.json",
        "candidate",
        "candidate-task",
        "2026-09-12T02:00:00Z",
    )
    value, additions = build(base, [("SGLANG_OPTIMIZATION", candidate)])
    selected = next(
        row for row in value["lanes"] if row["lane_id"] == "SGLANG_OPTIMIZATION"
    )
    assert len(selected["work_cycle_ledgers"]) == 2
    assert additions[0]["cycle_id"] == "candidate"


def test_rejects_ledger_before_accounting_boundary(tmp_path: Path) -> None:
    base = manifest(tmp_path)
    candidate = ledger(tmp_path / "old.json", "old", "old-task", "2026-09-12T01:00:00Z")
    with pytest.raises(ValueError, match="predates portfolio accounting boundary"):
        build(base, [("VLLM_OPTIMIZATION", candidate)])


def test_rejects_duplicate_cycle_task(tmp_path: Path) -> None:
    base = manifest(tmp_path)
    candidate = ledger(
        tmp_path / "duplicate.json", "base-0", "task-0", "2026-09-12T03:00:00Z"
    )
    with pytest.raises(ValueError, match="cycle/task is already selected"):
        build(base, [("VLLM_OPTIMIZATION", candidate)])


def test_rejects_legacy_ledger(tmp_path: Path) -> None:
    base = manifest(tmp_path)
    candidate = ledger(
        tmp_path / "legacy.json", "legacy", "legacy-task", "2026-09-12T03:00:00Z"
    )
    value = json.loads(candidate.read_text(encoding="utf-8"))
    value["observation_mode"] = "LEGACY_MILESTONE_BOUNDS"
    dump(candidate, value)
    with pytest.raises(ValueError, match="must use PROSPECTIVE_EXACT"):
        build(base, [("VLLM_OPTIMIZATION", candidate)])


def test_output_is_create_once(tmp_path: Path) -> None:
    output = tmp_path / "next.json"
    write_once(output, {"ok": True})
    with pytest.raises(FileExistsError, match="refusing to replace"):
        write_once(output, {"ok": False})


def test_refreshes_changed_selected_ledger_at_same_lane_and_path(
    tmp_path: Path,
) -> None:
    base = manifest(tmp_path)
    old_manifest = json.loads(base.read_text(encoding="utf-8"))
    lane = next(
        row for row in old_manifest["lanes"] if row["lane_id"] == "VLLM_OPTIMIZATION"
    )
    selected = Path(lane["work_cycle_ledgers"][0]["path"])
    previous_hash = lane["work_cycle_ledgers"][0]["sha256"]
    current = json.loads(selected.read_text(encoding="utf-8"))
    current["outcome"]["pull_request_url"] = (
        "https://github.com/vllm-project/vllm/pull/1"
    )
    dump(selected, current)

    value, changes = build(base, [], [("VLLM_OPTIMIZATION", selected)])

    refreshed_lane = next(
        row for row in value["lanes"] if row["lane_id"] == "VLLM_OPTIMIZATION"
    )
    assert refreshed_lane["work_cycle_ledgers"][0]["sha256"] == sha256_file(selected)
    assert refreshed_lane["work_cycle_ledgers"][0]["sha256"] != previous_hash
    assert changes[0]["operation"] == "REFRESH"
    assert changes[0]["previous_ledger_identity"]["sha256"] == previous_hash


def test_refresh_rejects_path_selected_in_another_lane(tmp_path: Path) -> None:
    base = manifest(tmp_path)
    value = json.loads(base.read_text(encoding="utf-8"))
    selected = Path(value["lanes"][0]["work_cycle_ledgers"][0]["path"])
    current = json.loads(selected.read_text(encoding="utf-8"))
    current["outcome"]["pull_request_url"] = "https://github.com/example/repo/pull/1"
    dump(selected, current)

    with pytest.raises(ValueError, match="declared lane"):
        build(base, [], [("SGLANG_OPTIMIZATION", selected)])


def test_refresh_rejects_unchanged_identity(tmp_path: Path) -> None:
    base = manifest(tmp_path)
    value = json.loads(base.read_text(encoding="utf-8"))
    selected = Path(value["lanes"][0]["work_cycle_ledgers"][0]["path"])
    with pytest.raises(ValueError, match="did not change"):
        build(base, [], [("VLLM_OPTIMIZATION", selected)])


def test_rejects_combined_register_and_refresh(tmp_path: Path) -> None:
    base = manifest(tmp_path)
    value = json.loads(base.read_text(encoding="utf-8"))
    selected = Path(value["lanes"][0]["work_cycle_ledgers"][0]["path"])
    candidate = ledger(
        tmp_path / "candidate.json",
        "candidate",
        "candidate-task",
        "2026-09-12T02:00:00Z",
    )
    with pytest.raises(ValueError, match="cannot be combined"):
        build(
            base,
            [("SGLANG_OPTIMIZATION", candidate)],
            [("VLLM_OPTIMIZATION", selected)],
        )
