#!/usr/bin/env python3
"""Adversarial CPU tests for cohort-session and per-entry atomic claims."""

from __future__ import annotations

import copy
import ast
import json
import sqlite3
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event

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
import community_atomic_claim as atomic_claim  # noqa: E402


def relative_time(*, minutes: int) -> str:
    return (
        (datetime.now(timezone.utc) + timedelta(minutes=minutes))
        .isoformat()
        .replace("+00:00", "Z")
    )


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
    store: ClaimStore,
    *,
    token: str = "f" * 64,
    expires_at: str | None = None,
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
        claim_store_identity_sha256=store.identity_sha256,
        claim_store_epoch_sha256=store.store_epoch_sha256,
        formal_resource_id="shared-8x-sm120-32g",
        expires_at=expires_at or relative_time(minutes=60),
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
    return ClaimStore(root / name, store_epoch_sha256="9" * 64)


def create_session(
    store: ClaimStore, binding: SessionBinding, rows: list[dict]
) -> dict:
    state, receipt = store.create_or_resume_session(binding, rows, ready_gates())
    assert state == "CREATED"
    validate_receipt(receipt, "community_cohort_session_claim.schema.json")
    assert receipt["claim_state"] == "SESSION_CLAIMED"
    assert receipt["session_claim_id"] == digest(
        {key: value for key, value in receipt.items() if key != "session_claim_id"}
    )
    assert receipt["initial_order_index"] == 1
    return receipt


def test_concurrent_session_creation_consumes_token_once() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        rows = execution_schedule()
        store = new_store(Path(temporary))
        binding = session_binding(rows, store)

        def create(_: int) -> tuple[str, dict]:
            return store.create_or_resume_session(binding, rows, ready_gates())

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
        store = new_store(Path(temporary))
        binding = session_binding(rows, store)
        create_session(store, binding, rows)
        foreign = session_binding(rows, store, request_sha256="9" * 64)
        with pytest.raises(ClaimError, match="TOKEN_ALREADY_BOUND_TO_FOREIGN_SESSION"):
            store.create_or_resume_session(foreign, rows, ready_gates())


@pytest.mark.parametrize(
    "missing_gate",
    ["pre_gpu_ready", "execution_contract_ready", "semantic_approval_ready"],
)
def test_session_requires_p_and_e_and_a(missing_gate: str) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        rows = execution_schedule()
        store = new_store(Path(temporary))
        binding = session_binding(rows, store)
        gates = ready_gates()
        gates[missing_gate] = False
        with pytest.raises(ClaimError, match="P_AND_E_AND_A_REQUIRED"):
            store.create_or_resume_session(binding, rows, gates)


def test_execution_schedule_hash_and_argv_are_frozen() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        rows = execution_schedule()
        store = new_store(Path(temporary))
        binding = session_binding(rows, store)
        drifted = copy.deepcopy(rows)
        drifted[0]["resolved_argv"][0] = "python3"
        with pytest.raises(ClaimError, match="RESOLVED_ARGV_IDENTITY_MISMATCH"):
            store.create_or_resume_session(binding, drifted, ready_gates())


def test_concurrent_entry_claim_succeeds_once() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        rows = execution_schedule()
        store = new_store(Path(temporary))
        binding = session_binding(rows, store)
        create_session(store, binding, rows)

        def claim(_: int) -> str:
            try:
                store.claim_entry(binding, rows[0])
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
        store = new_store(Path(temporary))
        binding = session_binding(rows, store)
        create_session(store, binding, rows)
        with pytest.raises(ClaimError, match="FROZEN_ORDER_VIOLATION"):
            store.claim_entry(binding, rows[1])
        foreign = copy.deepcopy(rows[0])
        foreign["arm"] = "COMMUNITY_AUGMENTED"
        with pytest.raises(ClaimError, match="FOREIGN_SCHEDULE_ENTRY"):
            store.claim_entry(binding, foreign)


def test_expiry_is_rechecked_at_each_entry_claim() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        rows = execution_schedule()
        store = new_store(Path(temporary))
        binding = session_binding(rows, store, expires_at=relative_time(minutes=-1))
        with pytest.raises(ClaimError, match="APPROVAL_OR_SESSION_EXPIRED"):
            create_session(store, binding, rows)


def test_expiry_is_rechecked_with_trusted_clock_before_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        rows = execution_schedule()
        store = new_store(Path(temporary))
        current = datetime(2030, 1, 1, tzinfo=timezone.utc)
        monkeypatch.setattr(atomic_claim, "trusted_utc_now", lambda: current)
        binding = session_binding(rows, store, expires_at="2030-01-01T00:02:00Z")
        create_session(store, binding, rows)
        store.claim_entry(binding, rows[0])
        current = datetime(2030, 1, 1, 0, 2, tzinfo=timezone.utc)
        with pytest.raises(ClaimError, match="SESSION_EXPIRED_BEFORE_DISPATCH"):
            store.record_dispatch(binding, 1, process_identity(rows[0]))


def test_claim_store_identity_prevents_cross_database_token_replay() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        rows = execution_schedule()
        root = Path(temporary)
        primary = new_store(root, "primary.sqlite")
        foreign = new_store(root, "foreign.sqlite")
        binding = session_binding(rows, primary)
        create_session(primary, binding, rows)
        with pytest.raises(ClaimError, match="CLAIM_STORE_IDENTITY_MISMATCH"):
            foreign.create_or_resume_session(binding, rows, ready_gates())


@pytest.mark.parametrize("mutation", ["schedule", "next_order"])
def test_each_transition_revalidates_stored_session_invariants(mutation: str) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        rows = execution_schedule()
        store = new_store(Path(temporary))
        binding = session_binding(rows, store)
        create_session(store, binding, rows)
        with closing(sqlite3.connect(store.path)) as database:
            if mutation == "schedule":
                changed = copy.deepcopy(rows)
                changed[0]["task_id"] = "foreign-task"
                database.execute(
                    "UPDATE sessions SET schedule_json=? WHERE session_id=?",
                    (json.dumps(changed), binding.session_id),
                )
            else:
                database.execute(
                    "UPDATE sessions SET next_order_index=2 WHERE session_id=?",
                    (binding.session_id,),
                )
            database.commit()
        expected = (
            "AUTHORIZATION_SCHEDULE_IDENTITY_MISMATCH"
            if mutation == "schedule"
            else "STORED_NEXT_ORDER_DIFFERS_FROM_SUCCESS_PREFIX"
        )
        with pytest.raises(ClaimError, match=expected):
            store.claim_entry(binding, rows[0])


def test_stored_claim_and_terminal_ids_are_recomputed_on_read() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        rows = execution_schedule()
        store = new_store(Path(temporary))
        binding = session_binding(rows, store)
        create_session(store, binding, rows)
        store.claim_entry(binding, rows[0])
        with closing(sqlite3.connect(store.path)) as database:
            claim = json.loads(
                database.execute(
                    "SELECT claim_receipt_json FROM entry_claims "
                    "WHERE session_id=? AND order_index=1",
                    (binding.session_id,),
                ).fetchone()[0]
            )
            claim["task_id"] = "forged-task"
            database.execute(
                "UPDATE entry_claims SET claim_receipt_json=? "
                "WHERE session_id=? AND order_index=1",
                (json.dumps(claim), binding.session_id),
            )
            database.commit()
        with pytest.raises(
            ClaimError, match="STORED_RECEIPT_IDENTITY_MISMATCH:entry_claim_id"
        ):
            store.record_dispatch(binding, 1, process_identity(rows[0]))

        # Rebuild a clean store to exercise the terminal lineage check separately.
        second = new_store(Path(temporary), "terminal.sqlite")
        second_binding = session_binding(rows, second, token="8" * 64)
        create_session(second, second_binding, rows)
        second.claim_entry(second_binding, rows[0])
        second.record_dispatch(second_binding, 1, process_identity(rows[0]))
        terminal = second.record_terminal(second_binding, 1, "CORRECTNESS_FAIL")
        with closing(sqlite3.connect(second.path)) as database:
            forged = dict(terminal)
            forged["schedule_key"] = "9" * 64
            database.execute(
                "UPDATE entry_claims SET terminal_receipt_json=? "
                "WHERE session_id=? AND order_index=1",
                (json.dumps(forged), second_binding.session_id),
            )
            database.commit()
        with pytest.raises(
            ClaimError, match="STORED_RECEIPT_IDENTITY_MISMATCH:terminal_receipt_id"
        ):
            second.validate_final_coverage(second_binding, [forged])


def test_dispatch_binds_strong_process_argv_and_gpu_identity() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        rows = execution_schedule()
        store = new_store(Path(temporary))
        binding = session_binding(rows, store)
        create_session(store, binding, rows)
        claim = store.claim_entry(binding, rows[0])
        validate_receipt(claim, "community_schedule_entry_claim.schema.json")

        wrong_argv = process_identity(rows[0])
        wrong_argv["argv_sha256"] = "9" * 64
        with pytest.raises(ClaimError, match="PROCESS_ARGV_DIFFERS_FROM_ENTRY_CLAIM"):
            store.record_dispatch(binding, 1, wrong_argv)

        wrong_gpu = process_identity(rows[0])
        wrong_gpu["gpu_uuids"] = ["GPU-foreign"]
        with pytest.raises(
            ClaimError, match="PROCESS_GPU_UUIDS_DIFFER_FROM_ENTRY_CLAIM"
        ):
            store.record_dispatch(binding, 1, wrong_gpu)

        dispatch = store.record_dispatch(binding, 1, process_identity(rows[0]))
        validate_receipt(dispatch, "community_entry_dispatch_receipt_v2.schema.json")
        assert dispatch["entry_claim_id"] == claim["entry_claim_id"]


def test_sequential_entries_advance_transactionally_and_complete() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        rows = execution_schedule()
        store = new_store(Path(temporary))
        binding = session_binding(rows, store)
        create_session(store, binding, rows)
        terminal_receipts = []
        for index, entry in enumerate(rows, start=1):
            store.claim_entry(binding, entry)
            store.record_dispatch(
                binding,
                index,
                process_identity(entry, pid=122 + index),
            )
            terminal = store.record_terminal(binding, index, "SUCCESS")
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
        store = new_store(Path(temporary))
        binding = session_binding(rows, store)
        create_session(store, binding, rows)
        store.claim_entry(binding, rows[0])
        if after_dispatch:
            store.record_dispatch(binding, 1, process_identity(rows[0]))
        assert store.recovery_state(binding, 1) == (
            "AMBIGUOUS_CONSUMED_NO_AUTOMATIC_RETRY"
        )
        terminal = store.record_ambiguous(binding, 1, outcome)
        assert terminal["automatic_retry_allowed"] is False
        assert store.snapshot(binding)["state"] == "ABORTED"
        with pytest.raises(ClaimError, match="SESSION_NOT_ACTIVE"):
            store.claim_entry(binding, rows[0])
        assert store.validate_final_coverage(binding, [terminal])["state"] == (
            "ABORTED"
        )


def test_dispatched_entry_cannot_be_relabelled_as_prelaunch_ambiguity() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        rows = execution_schedule()
        store = new_store(Path(temporary))
        binding = session_binding(rows, store)
        create_session(store, binding, rows)
        store.claim_entry(binding, rows[0])
        store.record_dispatch(binding, 1, process_identity(rows[0]))
        with pytest.raises(ClaimError, match="ENTRY_NOT_IN_TERMINABLE_STATE"):
            store.record_ambiguous(binding, 1, "AMBIGUOUS_PRELAUNCH")


def test_correctness_failure_is_preserved_as_terminal_evidence() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        rows = execution_schedule()
        store = new_store(Path(temporary))
        binding = session_binding(rows, store)
        create_session(store, binding, rows)
        store.claim_entry(binding, rows[0])
        store.record_dispatch(binding, 1, process_identity(rows[0]))
        terminal = store.record_terminal(binding, 1, "CORRECTNESS_FAIL")
        assert terminal["outcome"] == "CORRECTNESS_FAIL"
        coverage = store.validate_final_coverage(binding, [terminal])
        assert coverage["state"] == "ABORTED"
        assert coverage["complete"] is False


def test_final_coverage_rejects_missing_reordered_and_mixed_receipts() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        rows = execution_schedule()
        store = new_store(Path(temporary))
        binding = session_binding(rows, store)
        create_session(store, binding, rows)
        terminals = []
        for index, entry in enumerate(rows, start=1):
            store.claim_entry(binding, entry)
            store.record_dispatch(
                binding,
                index,
                process_identity(entry, pid=200 + index),
            )
            terminals.append(store.record_terminal(binding, index, "SUCCESS"))
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
        store = new_store(Path(temporary))
        binding = session_binding(rows, store)
        receipt = create_session(store, binding, rows)
        receipt["unbound_override"] = True
        with pytest.raises(ClaimError, match="additional property is forbidden"):
            validate_receipt(receipt, "community_cohort_session_claim.schema.json")


@pytest.mark.parametrize(
    ("transition", "expected_error"),
    [
        ("create", "APPROVAL_OR_SESSION_EXPIRED"),
        ("claim", "SESSION_EXPIRED_AT_ENTRY_CLAIM"),
        ("dispatch", "SESSION_EXPIRED_BEFORE_DISPATCH"),
    ],
)
def test_expiry_clock_is_sampled_after_acquiring_write_lock(
    monkeypatch: pytest.MonkeyPatch, transition: str, expected_error: str
) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        rows = execution_schedule()
        store = new_store(Path(temporary))
        binding = session_binding(rows, store)
        if transition != "create":
            create_session(store, binding, rows)
        if transition == "dispatch":
            store.claim_entry(binding, rows[0])

        clock_called = Event()
        expired = atomic_claim.parse_timestamp(binding.expires_at) + timedelta(seconds=1)

        def expired_clock() -> datetime:
            clock_called.set()
            return expired

        monkeypatch.setattr(atomic_claim, "trusted_utc_now", expired_clock)
        blocker = sqlite3.connect(store.path, timeout=5, isolation_level=None)
        blocker.execute("BEGIN IMMEDIATE")
        try:
            if transition == "create":
                operation = lambda: store.create_or_resume_session(  # noqa: E731
                    binding, rows, ready_gates()
                )
            elif transition == "claim":
                operation = lambda: store.claim_entry(binding, rows[0])  # noqa: E731
            else:
                operation = lambda: store.record_dispatch(  # noqa: E731
                    binding, 1, process_identity(rows[0])
                )
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(operation)
                assert clock_called.wait(0.1) is False
                blocker.execute("COMMIT")
                with pytest.raises(ClaimError, match=expected_error):
                    future.result(timeout=5)
        finally:
            if blocker.in_transaction:
                blocker.execute("ROLLBACK")
            blocker.close()


def test_store_epoch_is_persistent_and_changes_store_identity() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        path = root / "claims.sqlite"
        first = ClaimStore(path, store_epoch_sha256="1" * 64)
        assert ClaimStore(path, store_epoch_sha256="1" * 64).identity_sha256 == (
            first.identity_sha256
        )
        with pytest.raises(
            ClaimError, match="CLAIM_STORE_EPOCH_OR_IDENTITY_MISMATCH"
        ):
            ClaimStore(path, store_epoch_sha256="2" * 64)

        archived = root / "claims.sqlite.archived"
        path.replace(archived)
        replacement = ClaimStore(path, store_epoch_sha256="2" * 64)
        assert replacement.identity_sha256 != first.identity_sha256
        rows = execution_schedule()
        old_binding = session_binding(rows, first)
        with pytest.raises(ClaimError, match="CLAIM_STORE_IDENTITY_MISMATCH"):
            replacement.create_or_resume_session(old_binding, rows, ready_gates())


def test_store_metadata_is_revalidated_on_each_transition() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        rows = execution_schedule()
        store = new_store(Path(temporary))
        binding = session_binding(rows, store)
        create_session(store, binding, rows)
        with closing(sqlite3.connect(store.path)) as database:
            database.execute(
                "UPDATE claim_store_metadata SET store_identity_sha256=? "
                "WHERE singleton=1",
                ("0" * 64,),
            )
            database.commit()
        with pytest.raises(ClaimError, match="CLAIM_STORE_METADATA_MISMATCH"):
            store.claim_entry(binding, rows[0])


def test_session_receipt_self_identity_detects_timestamp_tamper() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        rows = execution_schedule()
        store = new_store(Path(temporary))
        binding = session_binding(rows, store)
        create_session(store, binding, rows)
        with closing(sqlite3.connect(store.path)) as database:
            receipt = json.loads(
                database.execute(
                    "SELECT receipt_json FROM sessions WHERE session_id=?",
                    (binding.session_id,),
                ).fetchone()[0]
            )
            receipt["generated_at"] = "2026-01-01T00:00:00Z"
            database.execute(
                "UPDATE sessions SET receipt_json=? WHERE session_id=?",
                (json.dumps(receipt), binding.session_id),
            )
            database.commit()
        with pytest.raises(
            ClaimError,
            match="STORED_RECEIPT_IDENTITY_MISMATCH:session_claim_id",
        ):
            store.snapshot(binding)


def test_cli_uses_validated_store_snapshot() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        rows = execution_schedule()
        store = new_store(Path(temporary))
        binding = session_binding(rows, store)
        create_session(store, binding, rows)
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "community_atomic_claim.py"),
                str(store.path),
                binding.session_id,
                "--store-epoch-sha256",
                store.store_epoch_sha256,
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["state"] == "ACTIVE"
