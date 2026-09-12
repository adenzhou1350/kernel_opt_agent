from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from qualification_churn import build_report  # noqa: E402


def write(path: Path, value: dict) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def plan(root: Path, version: int) -> tuple[Path, str]:
    path = root / "experiments" / f"environment_materialization_plan_v{version}.json"
    return path, write(path, {"version": version})


def receipt(
    root: Path,
    version: int,
    plan_path: Path,
    plan_sha: str,
    *,
    status: str,
    workload: bool = False,
) -> None:
    write(
        root / "raw" / f"materialization_receipt_v{version}.json",
        {
            "status": status,
            "plan": {"path": plan_path.as_posix(), "sha256": plan_sha},
            "gpu_used": False,
            "workload_started": workload,
        },
    )


def test_stops_failed_repair_scope(tmp_path: Path) -> None:
    for version in range(1, 4):
        path, digest = plan(tmp_path, version)
        receipt(
            tmp_path,
            version,
            path,
            digest,
            status="FAILED_TERMINAL",
        )
    report = build_report(tmp_path)
    family = report["families"][0]
    assert family["decision"] == "STOP_REPAIR_SCOPE"
    assert family["failed_terminal_plan_count"] == 3
    assert family["unexecuted_plan_count"] == 0


def test_advances_after_environment_success_instead_of_minting_more_plans(
    tmp_path: Path,
) -> None:
    paths = [plan(tmp_path, version) for version in range(1, 6)]
    for version, (path, digest) in enumerate(paths[:4], start=1):
        receipt(
            tmp_path,
            version,
            path,
            digest,
            status="SUCCEEDED_TERMINAL" if version == 4 else "FAILED_TERMINAL",
        )
    report = build_report(tmp_path)
    family = report["families"][0]
    assert family["decision"] == "ADVANCE_FROM_ENVIRONMENT"
    assert family["succeeded_terminal_plan_count"] == 1
    assert family["workload_started_plan_count"] == 0


def test_collapses_unexecuted_revisions(tmp_path: Path) -> None:
    plan(tmp_path, 1)
    plan(tmp_path, 2)
    report = build_report(tmp_path)
    assert report["families"][0]["decision"] == "COLLAPSE_UNEXECUTED_REVISIONS"


def test_workload_progress_wins_over_churn_warning(tmp_path: Path) -> None:
    path, digest = plan(tmp_path, 1)
    receipt(
        tmp_path,
        1,
        path,
        digest,
        status="SUCCEEDED_TERMINAL",
        workload=True,
    )
    assert build_report(tmp_path)["families"][0]["decision"] == "WORKLOAD_REACHED"


def test_terminal_plan_hash_drift_fails_closed(tmp_path: Path) -> None:
    path, _digest = plan(tmp_path, 1)
    receipt(
        tmp_path,
        1,
        path,
        "0" * 64,
        status="FAILED_TERMINAL",
    )
    with pytest.raises(ValueError, match="binds changed plan"):
        build_report(tmp_path)
