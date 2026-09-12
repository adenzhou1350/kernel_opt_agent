#!/usr/bin/env python3
"""Focused tests for create-once work-cycle action attestations."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/kernel_opt.py"
sys.path.insert(0, str(ROOT / "scripts"))

from community_portfolio import load_action_attestations  # noqa: E402


def write_json(path: Path, value: dict) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def ledger(tmp_path: Path, *, active: bool = True) -> tuple[Path, Path]:
    evidence = write_json(tmp_path / "evidence.json", {"status": "RUNNING"})
    value = {
        "schema_version": "community-work-cycle-v1",
        "cycle_id": "candidate-cycle",
        "task_id": "task-id",
        "started_at": "2026-09-12T00:00:00Z",
        "observation_mode": "PROSPECTIVE_EXACT",
        "claim_boundary": "WORK_CYCLE_TIMING_NOT_PERFORMANCE_CAUSALITY",
        "minimum_material_speedup": 1.02,
        "spans": [
            {
                "span_id": "qualification",
                "phase": "CORRECTNESS_VALIDATION",
                "actor": "AGENT",
                "resource_id": "LOCAL_CPU_TEST",
                "started_at": "2026-09-12T00:01:00Z",
                "ended_at": None if active else "2026-09-12T00:02:00Z",
                "status": "ACTIVE" if active else "COMPLETE",
                "evidence": []
                if active
                else [
                    {
                        "path": evidence.name,
                        "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest(),
                    }
                ],
            }
        ],
        "milestones": [],
        "outcome": {
            "correctness": "NOT_RUN",
            "best_speedup": None,
            "best_whole_model_speedup": None,
            "upstream_ready": False,
            "pull_request_url": None,
            "merged": False,
        },
    }
    return write_json(tmp_path / "ledger.json", value), evidence


def command(
    ledger_path: Path,
    evidence: Path,
    output: Path,
    *,
    state: str = "ACTIVE",
    owner: str = "AGENT",
) -> list[str]:
    arguments = [
        sys.executable,
        str(SCRIPT),
        "community-action-attest",
        "--ledger",
        str(ledger_path),
        "--span-id",
        "qualification",
        "--state",
        state,
        "--action-owner",
        owner,
        "--generated-at",
        "2026-09-12T00:03:00Z",
        "--evidence",
        str(evidence),
        "--output",
        str(output),
    ]
    if state == "ACTIVE":
        arguments.extend(("--valid-for-seconds", "600"))
    return arguments


def test_active_attestation_derives_identity_and_is_create_once(tmp_path: Path) -> None:
    ledger_path, evidence = ledger(tmp_path)
    output = tmp_path / "active.json"
    completed = subprocess.run(
        command(ledger_path, evidence, output), capture_output=True, text=True
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    record = json.loads(output.read_text(encoding="utf-8"))
    assert result["status"] == "PASS"
    assert record["cycle_id"] == "candidate-cycle"
    assert record["span_id"] == "qualification"
    assert record["resource_id"] == "LOCAL_CPU_TEST"
    assert record["action_owner"] == "AGENT"
    assert record["valid_until"] == "2026-09-12T00:13:00Z"
    attestations, identities = load_action_attestations(
        [output], [(ledger_path, json.loads(ledger_path.read_text(encoding="utf-8")))]
    )
    assert len(attestations) == 1
    assert identities[0]["path"] == output.as_posix()
    duplicate = subprocess.run(
        command(ledger_path, evidence, output), capture_output=True, text=True
    )
    assert duplicate.returncode != 0
    assert "refusing to replace" in duplicate.stderr


def test_resolved_attestation_has_no_owner_or_validity(tmp_path: Path) -> None:
    ledger_path, evidence = ledger(tmp_path)
    output = tmp_path / "resolved.json"
    completed = subprocess.run(
        command(ledger_path, evidence, output, state="RESOLVED", owner="NONE"),
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    record = json.loads(output.read_text(encoding="utf-8"))
    assert record["state"] == "RESOLVED"
    assert record["action_owner"] == "NONE"
    assert record["valid_until"] is None

    invalid = command(ledger_path, evidence, tmp_path / "invalid.json")
    invalid[invalid.index("AGENT")] = "NONE"
    rejected = subprocess.run(invalid, capture_output=True, text=True)
    assert rejected.returncode != 0
    assert "non-NONE action owner" in rejected.stderr


def test_closed_span_and_missing_evidence_fail_without_output(tmp_path: Path) -> None:
    ledger_path, evidence = ledger(tmp_path, active=False)
    output = tmp_path / "closed.json"
    rejected = subprocess.run(
        command(ledger_path, evidence, output), capture_output=True, text=True
    )
    assert rejected.returncode != 0
    assert "exactly one ACTIVE" in rejected.stderr
    assert not output.exists()

    ledger_path, evidence = ledger(tmp_path)
    evidence.unlink()
    missing = subprocess.run(
        command(ledger_path, evidence, output), capture_output=True, text=True
    )
    assert missing.returncode != 0
    assert not output.exists()

