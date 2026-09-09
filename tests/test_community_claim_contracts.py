#!/usr/bin/env python3
"""Focused tests for the pure cohort-claim contract layer."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from community_claim_contracts import (  # noqa: E402
    ClaimError,
    SessionBinding,
    authorization_schedule,
    digest,
    validate_execution_schedule,
)


def schedule() -> list[dict]:
    argv = ["python", "runner.py", "--arm", "control"]
    return [
        {
            "order_index": 1,
            "task_id": "task-a",
            "repeat_index": 1,
            "arm": "CONTROL",
            "schedule_key": "1" * 64,
            "sealed_argv_sha256": "a" * 64,
            "resolved_argv": argv,
            "resolved_argv_sha256": digest(argv),
            "formal_gpu_uuids": ["GPU-11111111-1111-1111-1111-111111111111"],
        }
    ]


def binding(rows: list[dict]) -> SessionBinding:
    return SessionBinding(
        request_id="request-1",
        cycle_id="cycle-1",
        suite_id="suite-1",
        authorization_request_sha256="a" * 64,
        semantic_approval_sha256="b" * 64,
        combined_authorization_sha256="c" * 64,
        single_use_token="d" * 64,
        authorization_schedule_sha256=digest(authorization_schedule(rows)),
        execution_schedule_sha256=digest(rows),
        dispatcher_sha256="e" * 64,
        claim_store_identity_sha256="f" * 64,
        claim_store_epoch_sha256="9" * 64,
        formal_resource_id="shared-8x-sm120-32g",
        expires_at="2030-01-01T00:00:00Z",
        max_dispatches=1,
    )


def test_contract_module_has_no_persistence_or_launch_surface() -> None:
    source = (ROOT / "scripts" / "community_claim_contracts.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    imported_roots = {
        alias.name.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert imported_roots.isdisjoint(
        {"sqlite3", "subprocess", "multiprocessing", "torch"}
    )


def test_contract_accepts_exact_schedule_and_rejects_argv_drift() -> None:
    rows = schedule()
    frozen = binding(rows)
    validate_execution_schedule(rows, frozen)
    rows[0]["resolved_argv"][0] = "python3"
    with pytest.raises(ClaimError, match="RESOLVED_ARGV_IDENTITY_MISMATCH"):
        validate_execution_schedule(rows, frozen)
