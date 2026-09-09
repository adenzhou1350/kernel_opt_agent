#!/usr/bin/env python3
"""Adversarial CPU tests for cohort-session and per-entry atomic claims."""

from __future__ import annotations

import copy
import ast
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from community_atomic_claim import (  # noqa: E402
    ClaimError,
    ClaimStore,
    SessionBinding,
    authorization_schedule,
    digest,
    validate_receipt,
)


CREATED_AT = "2026-09-09T00:00:00Z"
CLAIMED_AT = "2026-09-09T00:01:00Z"
DISPATCHED_AT = "2026-09-09T00:02:00Z"
TERMINAL_AT = "2026-09-09T00:03:00Z"
EXPIRES_AT = "2026-09-09T01:00:00Z"


def execution_schedule() -> list[dict]:
    rows = []
    for order_index, arm, argv_marker in (
        (1, "CONTROL", "control"),
        (2, "COMMUNITY_AUGMENTED", "candidate"),
    ):
        argv = ["python", "runner.py", "--arm", argv_marker]
        rows.append(
            {
                "order_index": order_index,
                "task_id": "task-a",
                "repeat_index": 1,
                "arm": arm,
                "schedule_key": str(order_index) * 64,
                "sealed_argv_sha256": chr(96 + order_index) * 64,
                "resolved_argv": argv,
                "resolved_argv_sha256": digest(argv),
                "formal_gpu_uuids": ["GPU-11111111-1111-1111-1111-111111111111"],
            }
        )
    return rows


def session_binding(
    rows: list[dict],
    *,
    token: str = "f" * 64,
    expires_at: str = EXPIRES_AT,
    request_sha256: str = "a" * 64,
) -> SessionBinding:
    return SessionBinding(
        request_id="request-1",
        cycle_id="cycle-1",
        suite_id="suite-1",
        authorization_request_sha256=request_sha256,
        semantic_approval_sha256="b" * 64,
        combined_authorization_sha256="c" * 64,
        single_use_token=token,
        authorization_schedule_sha256=digest(authorization_schedule(rows)),
        execution_schedule_sha256=digest(rows),
        dispatcher_sha256="d" * 64,
        formal_resource_id="shared-8x-sm120-32g",
        expires_at=expires_at,
        max_dispatches=len(rows),
    )


def ready_gates() -> dict[str, bool]:
    return {
        "pre_gpu_ready": True,
        "execution_contract_ready": True,
        "semantic_approval_ready": True,
    }


def process_identity(entry: dict, *, pid: int = 123) -> dict:
    return {
        "pid": pid,
        "hostname": "gpu-host-1",
        "boot_id": "11111111-2222-3333-4444-555555555555",
        "proc_start_ticks": 987654,
        "argv_sha256": entry["resolved_argv_sha256"],
        "executable_path": "/usr/bin/python3",
        "executable_sha256": "e" * 64,
        "gpu_uuids": entry["formal_gpu_uuids"],
    }


def new_store(root: Path, name: str = "claims.sqlite") -> ClaimStore:
    return ClaimStore(root / name)


def create_session(
    store: ClaimStore, binding: SessionBinding, rows: list[dict]
) -> dict:
    state, receipt = store.create_or_resume_session(
        binding, rows, ready_gates(), CREATED_AT
    )
    assert state == "CREATED"
    validate_receipt(receipt, "community_cohort_session_claim.schema.json")
    assert receipt["claim_state"] == "SESSION_CLAIMED"
    assert receipt["initial_order_index"] == 1
    return receipt


def test_concurrent_session_creation_consumes_token_once() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        rows = execution_schedule()
        binding = session_binding(rows)
        store = new_store(Path(temporary))

        def create(_: int) -> tuple[str, dict]:
            return store.create_or_resume_session(
                binding, rows, ready_gates(), CREATED_AT
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(create, range(2)))
        assert sorted(state for state, _ in outcomes) == [
            "CREATED",
            "EXISTING_IDENTICAL_SESSION",
        ]
        assert len({receipt["session_id"] for _, receipt in outcomes}) == 1


def test_token_cannot_rebind_to_foreign_request() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        rows = execution_schedule()
        binding = session_binding(rows)
        store = new_store(Path(temporary))
        create_session(store, binding, rows)
        foreign = session_binding(rows, request_sha256="9" * 64)
        with pytest.raises(ClaimError, match="TOKEN_ALREADY_BOUND_TO_FOREIGN_SESSION"):
            store.create_or_resume_session(foreign, rows, ready_gates(), CREATED_AT)


@pytest.mark.parametrize(
    "missing_gate",
    ["pre_gpu_ready", "execution_contract_ready", "semantic_approval_ready"],
)
def test_session_requires_p_and_e_and_a(missing_gate: str) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        rows = execution_schedule()
        binding = session_binding(rows)
        gates = ready_gates()
        gates[missing_gate] = False
        with pytest.raises(ClaimError, match="P_AND_E_AND_A_REQUIRED"):
            new_store(Path(temporary)).create_or_resume_session(
                binding, rows, gates, CREATED_AT
            )


def test_execution_schedule_hash_and_argv_are_frozen() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        rows = execution_schedule()
        binding = session_binding(rows)
        drifted = copy.deepcopy(rows)
        drifted[0]["resolved_argv"][0] = "python3"
        with pytest.raises(ClaimError, match="RESOLVED_ARGV_IDENTITY_MISMATCH"):
            new_store(Path(temporary)).create_or_resume_session(
                binding, drifted, ready_gates(), CREATED_AT
            )


def test_concurrent_entry_claim_succeeds_once() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        rows = execution_schedule()
        binding = session_binding(rows)
        store = new_store(Path(temporary))
        create_session(store, binding, rows)

        def claim(_: int) -> str:
            try:
                store.claim_entry(binding, rows[0], CLAIMED_AT)
            except ClaimError as error:
                return str(error)
            return "CLAIMED"

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = sorted(pool.map(claim, range(2)))
        assert outcomes == ["CLAIMED", "ENTRY_ALREADY_CONSUMED"]
        assert store.recovery_state(binding, 1) == (
            "AMBIGUOUS_CONSUMED_NO_AUTOMATIC_RETRY"
        )


def test_entry_claim_enforces_frozen_order_and_exact_fields() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        rows = execution_schedule()
        binding = session_binding(rows)
        store = new_store(Path(temporary))
        create_session(store, binding, rows)
        with pytest.raises(ClaimError, match="FROZEN_ORDER_VIOLATION"):
            store.claim_entry(binding, rows[1], CLAIMED_AT)
        foreign = copy.deepcopy(rows[0])
        foreign["arm"] = "COMMUNITY_AUGMENTED"
        with pytest.raises(ClaimError, match="FOREIGN_SCHEDULE_ENTRY"):
            store.claim_entry(binding, foreign, CLAIMED_AT)


def test_expiry_is_rechecked_at_each_entry_claim() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        rows = execution_schedule()
        binding = session_binding(rows, expires_at="2026-09-09T00:02:00Z")
        store = new_store(Path(temporary))
        create_session(store, binding, rows)
        with pytest.raises(ClaimError, match="SESSION_EXPIRED_AT_ENTRY_CLAIM"):
            store.claim_entry(binding, rows[0], "2026-09-09T00:02:00Z")


def test_dispatch_binds_strong_process_argv_and_gpu_identity() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        rows = execution_schedule()
        binding = session_binding(rows)
        store = new_store(Path(temporary))
        create_session(store, binding, rows)
        claim = store.claim_entry(binding, rows[0], CLAIMED_AT)
        validate_receipt(claim, "community_schedule_entry_claim.schema.json")

        wrong_argv = process_identity(rows[0])
        wrong_argv["argv_sha256"] = "9" * 64
        with pytest.raises(ClaimError, match="PROCESS_ARGV_DIFFERS_FROM_ENTRY_CLAIM"):
            store.record_dispatch(binding, 1, wrong_argv, DISPATCHED_AT)

        wrong_gpu = process_identity(rows[0])
        wrong_gpu["gpu_uuids"] = ["GPU-foreign"]
        with pytest.raises(
            ClaimError, match="PROCESS_GPU_UUIDS_DIFFER_FROM_ENTRY_CLAIM"
        ):
            store.record_dispatch(binding, 1, wrong_gpu, DISPATCHED_AT)

        dispatch = store.record_dispatch(
            binding, 1, process_identity(rows[0]), DISPATCHED_AT
        )
        validate_receipt(dispatch, "community_entry_dispatch_receipt_v2.schema.json")
        assert dispatch["entry_claim_id"] == claim["entry_claim_id"]


def test_sequential_entries_advance_transactionally_and_complete() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        rows = execution_schedule()
        binding = session_binding(rows)
        store = new_store(Path(temporary))
        create_session(store, binding, rows)
        terminal_receipts = []
        for index, entry in enumerate(rows, start=1):
            store.claim_entry(binding, entry, CLAIMED_AT)
            store.record_dispatch(
                binding,
                index,
                process_identity(entry, pid=122 + index),
                DISPATCHED_AT,
            )
            terminal = store.record_terminal(binding, index, "SUCCESS", TERMINAL_AT)
            validate_receipt(terminal, "community_entry_terminal_receipt.schema.json")
            terminal_receipts.append(terminal)
        snapshot = store.snapshot(binding)
        assert snapshot["state"] == "COMPLETE"
        assert snapshot["next_order_index"] == 3
        coverage = store.validate_final_coverage(binding, terminal_receipts)
        assert coverage == {
            "session_id": binding.session_id,
            "state": "COMPLETE",
            "terminal_receipt_count": 2,
            "expected_schedule_count": 2,
            "complete": True,
        }


@pytest.mark.parametrize(
    ("after_dispatch", "outcome"),
    [
        (False, "AMBIGUOUS_PRELAUNCH"),
        (True, "AMBIGUOUS_LAUNCH"),
    ],
)
def test_crash_windows_are_consumed_and_never_auto_retry(
    after_dispatch: bool, outcome: str
) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        rows = execution_schedule()
        binding = session_binding(rows)
        store = new_store(Path(temporary))
        create_session(store, binding, rows)
        store.claim_entry(binding, rows[0], CLAIMED_AT)
        if after_dispatch:
            store.record_dispatch(binding, 1, process_identity(rows[0]), DISPATCHED_AT)
        assert store.recovery_state(binding, 1) == (
            "AMBIGUOUS_CONSUMED_NO_AUTOMATIC_RETRY"
        )
        terminal = store.record_ambiguous(binding, 1, outcome, TERMINAL_AT)
        assert terminal["automatic_retry_allowed"] is False
        assert store.snapshot(binding)["state"] == "ABORTED"
        with pytest.raises(ClaimError, match="SESSION_NOT_ACTIVE"):
            store.claim_entry(binding, rows[0], TERMINAL_AT)
        assert store.validate_final_coverage(binding, [terminal])["state"] == (
            "ABORTED"
        )


def test_dispatched_entry_cannot_be_relabelled_as_prelaunch_ambiguity() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        rows = execution_schedule()
        binding = session_binding(rows)
        store = new_store(Path(temporary))
        create_session(store, binding, rows)
        store.claim_entry(binding, rows[0], CLAIMED_AT)
        store.record_dispatch(binding, 1, process_identity(rows[0]), DISPATCHED_AT)
        with pytest.raises(ClaimError, match="ENTRY_NOT_IN_TERMINABLE_STATE"):
            store.record_ambiguous(binding, 1, "AMBIGUOUS_PRELAUNCH", TERMINAL_AT)


def test_correctness_failure_is_preserved_as_terminal_evidence() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        rows = execution_schedule()
        binding = session_binding(rows)
        store = new_store(Path(temporary))
        create_session(store, binding, rows)
        store.claim_entry(binding, rows[0], CLAIMED_AT)
        store.record_dispatch(binding, 1, process_identity(rows[0]), DISPATCHED_AT)
        terminal = store.record_terminal(binding, 1, "CORRECTNESS_FAIL", TERMINAL_AT)
        assert terminal["outcome"] == "CORRECTNESS_FAIL"
        coverage = store.validate_final_coverage(binding, [terminal])
        assert coverage["state"] == "ABORTED"
        assert coverage["complete"] is False


def test_final_coverage_rejects_missing_reordered_and_mixed_receipts() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        rows = execution_schedule()
        binding = session_binding(rows)
        store = new_store(Path(temporary))
        create_session(store, binding, rows)
        terminals = []
        for index, entry in enumerate(rows, start=1):
            store.claim_entry(binding, entry, CLAIMED_AT)
            store.record_dispatch(
                binding,
                index,
                process_identity(entry, pid=200 + index),
                DISPATCHED_AT,
            )
            terminals.append(
                store.record_terminal(binding, index, "SUCCESS", TERMINAL_AT)
            )
        with pytest.raises(
            ClaimError, match="INCOMPLETE_REORDERED_OR_FOREIGN_RECEIPTS"
        ):
            store.validate_final_coverage(binding, terminals[:1])
        with pytest.raises(
            ClaimError, match="INCOMPLETE_REORDERED_OR_FOREIGN_RECEIPTS"
        ):
            store.validate_final_coverage(binding, list(reversed(terminals)))
        mixed = copy.deepcopy(terminals)
        mixed[1]["session_id"] = "9" * 64
        with pytest.raises(ClaimError, match="MIXED_SESSION_RECEIPTS"):
            store.validate_final_coverage(binding, mixed)


def test_claim_core_has_no_process_or_gpu_launch_surface() -> None:
    source = (ROOT / "scripts" / "community_atomic_claim.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    imported_roots = {
        alias.name.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported_roots.update(
        node.module.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    )
    assert imported_roots.isdisjoint({"subprocess", "multiprocessing", "torch"})
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"Popen", "run", "system", "spawn"}
        for node in ast.walk(tree)
    )


def test_strict_receipt_schemas_reject_unbound_fields() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        rows = execution_schedule()
        binding = session_binding(rows)
        receipt = create_session(new_store(Path(temporary)), binding, rows)
        receipt["unbound_override"] = True
        with pytest.raises(ClaimError, match="additional property is forbidden"):
            validate_receipt(receipt, "community_cohort_session_claim.schema.json")
