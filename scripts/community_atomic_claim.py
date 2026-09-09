#!/usr/bin/env python3
"""Atomically claim a cohort session and its frozen schedule entries.

This module is deliberately a pure authorization state machine. It never starts a
process, imports a framework, connects to a remote host, or touches a GPU.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from schema_utils import validate_instance


class ClaimError(RuntimeError):
    """A fail-closed authorization or state-transition error."""


SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
GPU_UUID_PATTERN = re.compile(r"^GPU-[0-9A-Za-z-]+$")
GATE_KEYS = {
    "pre_gpu_ready",
    "execution_contract_ready",
    "semantic_approval_ready",
}
ENTRY_KEYS = {
    "order_index",
    "task_id",
    "repeat_index",
    "arm",
    "schedule_key",
    "sealed_argv_sha256",
    "resolved_argv",
    "resolved_argv_sha256",
    "formal_gpu_uuids",
}
PROCESS_IDENTITY_KEYS = {
    "pid",
    "hostname",
    "boot_id",
    "proc_start_ticks",
    "argv_sha256",
    "executable_path",
    "executable_sha256",
    "gpu_uuids",
}
TERMINAL_OUTCOMES = {
    "SUCCESS",
    "CORRECTNESS_FAIL",
    "TIMEOUT",
    "PROCESS_FAIL",
}
AMBIGUOUS_OUTCOMES = {"AMBIGUOUS_PRELAUNCH", "AMBIGUOUS_LAUNCH"}


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ClaimError("INVALID_TIMESTAMP") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ClaimError("TIMESTAMP_REQUIRES_TIMEZONE")
    return parsed


def trusted_utc_now() -> datetime:
    """Return the process clock used for state-transition decisions."""

    return datetime.now(timezone.utc)


def timestamp_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def require_sha256(value: str, label: str) -> None:
    if not isinstance(value, str) or SHA256_PATTERN.fullmatch(value) is None:
        raise ClaimError(f"INVALID_SHA256:{label}")


def authorization_schedule(rows: list[dict]) -> list[dict]:
    fields = ("order_index", "task_id", "repeat_index", "arm", "schedule_key")
    return [{key: row[key] for key in fields} for row in rows]


@dataclass(frozen=True)
class SessionBinding:
    request_id: str
    cycle_id: str
    suite_id: str
    authorization_request_sha256: str
    semantic_approval_sha256: str
    combined_authorization_sha256: str
    single_use_token: str
    authorization_schedule_sha256: str
    execution_schedule_sha256: str
    dispatcher_sha256: str
    claim_store_identity_sha256: str
    formal_resource_id: str
    expires_at: str
    max_dispatches: int

    def validate(self) -> None:
        for field in (
            "authorization_request_sha256",
            "semantic_approval_sha256",
            "combined_authorization_sha256",
            "single_use_token",
            "authorization_schedule_sha256",
            "execution_schedule_sha256",
            "dispatcher_sha256",
            "claim_store_identity_sha256",
        ):
            require_sha256(getattr(self, field), field)
        if not all((self.request_id, self.cycle_id, self.suite_id)):
            raise ClaimError("INCOMPLETE_COHORT_IDENTITY")
        if not self.formal_resource_id:
            raise ClaimError("FORMAL_RESOURCE_ID_REQUIRED")
        if self.max_dispatches < 1:
            raise ClaimError("INVALID_DISPATCH_BUDGET")
        parse_timestamp(self.expires_at)

    @property
    def session_id(self) -> str:
        return digest(asdict(self))


def schema_path(name: str) -> Path:
    return Path(__file__).resolve().parents[1] / "schemas" / name


def validate_receipt(receipt: dict, schema_name: str) -> None:
    schema = json.loads(schema_path(schema_name).read_text(encoding="utf-8"))
    errors = validate_instance(receipt, schema)
    if errors:
        raise ClaimError("INVALID_RECEIPT:" + "; ".join(errors))


def with_id(receipt: dict, field: str) -> dict:
    result = dict(receipt)
    result[field] = digest(receipt)
    return result


def validate_execution_schedule(rows: list[dict], binding: SessionBinding) -> None:
    if not rows or len(rows) != binding.max_dispatches:
        raise ClaimError("SCHEDULE_LENGTH_DIFFERS_FROM_BUDGET")
    if [row.get("order_index") for row in rows] != list(range(1, len(rows) + 1)):
        raise ClaimError("NONCONTIGUOUS_SCHEDULE")
    schedule_keys: set[str] = set()
    for row in rows:
        if set(row) != ENTRY_KEYS:
            raise ClaimError("INVALID_EXECUTION_ENTRY_FIELDS")
        if not isinstance(row["task_id"], str) or not row["task_id"]:
            raise ClaimError("INVALID_TASK_ID")
        if not isinstance(row["repeat_index"], int) or row["repeat_index"] < 1:
            raise ClaimError("INVALID_REPEAT_INDEX")
        if row["arm"] not in {"CONTROL", "COMMUNITY_AUGMENTED"}:
            raise ClaimError("INVALID_ARM")
        require_sha256(row["schedule_key"], "schedule_key")
        require_sha256(row["sealed_argv_sha256"], "sealed_argv_sha256")
        require_sha256(row["resolved_argv_sha256"], "resolved_argv_sha256")
        if row["schedule_key"] in schedule_keys:
            raise ClaimError("DUPLICATE_SCHEDULE_KEY")
        schedule_keys.add(row["schedule_key"])
        argv = row["resolved_argv"]
        if (
            not isinstance(argv, list)
            or not argv
            or not all(isinstance(item, str) and item for item in argv)
        ):
            raise ClaimError("INVALID_RESOLVED_ARGV")
        if digest(argv) != row["resolved_argv_sha256"]:
            raise ClaimError("RESOLVED_ARGV_IDENTITY_MISMATCH")
        gpu_uuids = row["formal_gpu_uuids"]
        if not isinstance(gpu_uuids, list) or not gpu_uuids:
            raise ClaimError("FORMAL_GPU_UUIDS_REQUIRED")
        if len(gpu_uuids) != len(set(gpu_uuids)) or any(
            not isinstance(item, str) or GPU_UUID_PATTERN.fullmatch(item) is None
            for item in gpu_uuids
        ):
            raise ClaimError("INVALID_FORMAL_GPU_UUIDS")
    if digest(authorization_schedule(rows)) != binding.authorization_schedule_sha256:
        raise ClaimError("AUTHORIZATION_SCHEDULE_IDENTITY_MISMATCH")
    if digest(rows) != binding.execution_schedule_sha256:
        raise ClaimError("EXECUTION_SCHEDULE_IDENTITY_MISMATCH")


class ClaimStore:
    """SQLite-backed state store with transactional session and entry claims."""

    def __init__(self, path: Path):
        self.path = path.resolve()
        self.identity_sha256 = digest(
            {
                "schema_version": "community-claim-store-identity-v1",
                "canonical_database_path": os.path.normcase(str(self.path)),
            }
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as database:
            database.executescript(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA synchronous=FULL;
                CREATE TABLE IF NOT EXISTS sessions (
                  session_id TEXT PRIMARY KEY,
                  token TEXT NOT NULL UNIQUE,
                  binding_json TEXT NOT NULL,
                  schedule_json TEXT NOT NULL,
                  receipt_json TEXT NOT NULL,
                  max_dispatches INTEGER NOT NULL,
                  next_order_index INTEGER NOT NULL,
                  state TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS entry_claims (
                  session_id TEXT NOT NULL,
                  order_index INTEGER NOT NULL,
                  schedule_key TEXT NOT NULL,
                  entry_json TEXT NOT NULL,
                  claim_receipt_json TEXT NOT NULL,
                  state TEXT NOT NULL,
                  process_identity_json TEXT,
                  dispatch_receipt_json TEXT,
                  terminal_receipt_json TEXT,
                  PRIMARY KEY(session_id, order_index),
                  UNIQUE(session_id, schedule_key),
                  FOREIGN KEY(session_id) REFERENCES sessions(session_id)
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        database = sqlite3.connect(self.path, timeout=5.0, isolation_level=None)
        database.execute("PRAGMA busy_timeout=5000")
        database.execute("PRAGMA foreign_keys=ON")
        return database

    @staticmethod
    def _binding_json(binding: SessionBinding) -> str:
        return canonical_json(asdict(binding))

    @staticmethod
    def _require_binding(stored: str, binding: SessionBinding) -> None:
        if stored != ClaimStore._binding_json(binding):
            raise ClaimError("SESSION_BINDING_MISMATCH")

    def _require_store_binding(self, binding: SessionBinding) -> None:
        if binding.claim_store_identity_sha256 != self.identity_sha256:
            raise ClaimError("CLAIM_STORE_IDENTITY_MISMATCH")

    @staticmethod
    def _require_self_id(receipt: dict, field: str) -> None:
        expected = receipt.get(field)
        unsigned = {key: value for key, value in receipt.items() if key != field}
        if expected != digest(unsigned):
            raise ClaimError(f"STORED_RECEIPT_IDENTITY_MISMATCH:{field}")

    def _validated_session(
        self, database: sqlite3.Connection, binding: SessionBinding
    ) -> tuple[list[dict], int, int, str]:
        self._require_store_binding(binding)
        session = database.execute(
            "SELECT binding_json,schedule_json,receipt_json,max_dispatches,"
            "next_order_index,state FROM sessions WHERE session_id=?",
            (binding.session_id,),
        ).fetchone()
        if session is None:
            raise ClaimError("FOREIGN_OR_MISSING_SESSION")
        binding_json, schedule_json, receipt_json, maximum, next_order, state = session
        self._require_binding(binding_json, binding)
        schedule = json.loads(schedule_json)
        validate_execution_schedule(schedule, binding)
        if maximum != binding.max_dispatches:
            raise ClaimError("STORED_DISPATCH_BUDGET_MISMATCH")
        if not isinstance(next_order, int) or not 1 <= next_order <= maximum + 1:
            raise ClaimError("STORED_NEXT_ORDER_INDEX_INVALID")
        if state not in {"ACTIVE", "COMPLETE", "ABORTED"}:
            raise ClaimError("STORED_SESSION_STATE_INVALID")
        session_receipt = json.loads(receipt_json)
        validate_receipt(session_receipt, "community_cohort_session_claim.schema.json")
        if (
            session_receipt["session_id"] != binding.session_id
            or session_receipt["claim_store_identity_sha256"] != self.identity_sha256
        ):
            raise ClaimError("STORED_SESSION_RECEIPT_IDENTITY_MISMATCH")
        expected_receipt_fields = {
            "request_id": binding.request_id,
            "cycle_id": binding.cycle_id,
            "suite_id": binding.suite_id,
            "authorization_request_sha256": binding.authorization_request_sha256,
            "semantic_approval_sha256": binding.semantic_approval_sha256,
            "combined_authorization_sha256": binding.combined_authorization_sha256,
            "single_use_token": binding.single_use_token,
            "authorization_schedule_sha256": binding.authorization_schedule_sha256,
            "execution_schedule_sha256": binding.execution_schedule_sha256,
            "formal_resource_id": binding.formal_resource_id,
            "dispatcher_sha256": binding.dispatcher_sha256,
            "claim_store_identity_sha256": binding.claim_store_identity_sha256,
            "expires_at": binding.expires_at,
            "max_dispatches": binding.max_dispatches,
        }
        if any(
            session_receipt.get(key) != value
            for key, value in expected_receipt_fields.items()
        ):
            raise ClaimError("STORED_SESSION_RECEIPT_BINDING_MISMATCH")
        self._validate_entry_state_invariants(
            database, binding, schedule, maximum, next_order, state
        )
        return schedule, maximum, next_order, state

    def _validate_entry_state_invariants(
        self,
        database: sqlite3.Connection,
        binding: SessionBinding,
        schedule: list[dict],
        maximum: int,
        next_order: int,
        session_state: str,
    ) -> None:
        rows = database.execute(
            "SELECT order_index,entry_json,claim_receipt_json,state,"
            "dispatch_receipt_json,terminal_receipt_json FROM entry_claims "
            "WHERE session_id=? ORDER BY order_index",
            (binding.session_id,),
        ).fetchall()
        if [row[0] for row in rows] != list(range(1, len(rows) + 1)):
            raise ClaimError("STORED_ENTRY_ORDER_GAP")
        decoded: list[tuple[str, dict | None]] = []
        for (
            order_index,
            entry_json,
            claim_json,
            state,
            dispatch_json,
            terminal_json,
        ) in rows:
            entry = json.loads(entry_json)
            if entry != schedule[order_index - 1]:
                raise ClaimError("STORED_ENTRY_DIFFERS_FROM_FROZEN_SCHEDULE")
            claim = json.loads(claim_json)
            self._require_self_id(claim, "entry_claim_id")
            validate_receipt(claim, "community_schedule_entry_claim.schema.json")
            if (
                claim["session_id"] != binding.session_id
                or claim["order_index"] != order_index
                or any(
                    claim[key] != entry[key]
                    for key in (
                        "task_id",
                        "repeat_index",
                        "arm",
                        "schedule_key",
                        "sealed_argv_sha256",
                        "resolved_argv",
                        "resolved_argv_sha256",
                        "formal_gpu_uuids",
                    )
                )
            ):
                raise ClaimError("STORED_ENTRY_CLAIM_LINEAGE_MISMATCH")
            dispatch = json.loads(dispatch_json) if dispatch_json else None
            terminal = json.loads(terminal_json) if terminal_json else None
            if dispatch is not None:
                self._require_self_id(dispatch, "dispatch_receipt_id")
                validate_receipt(
                    dispatch, "community_entry_dispatch_receipt_v2.schema.json"
                )
                if (
                    dispatch["session_id"] != binding.session_id
                    or dispatch["entry_claim_id"] != claim["entry_claim_id"]
                    or dispatch["order_index"] != order_index
                ):
                    raise ClaimError("STORED_DISPATCH_RECEIPT_LINEAGE_MISMATCH")
            if terminal is not None:
                self._require_self_id(terminal, "terminal_receipt_id")
                validate_receipt(
                    terminal, "community_entry_terminal_receipt.schema.json"
                )
                if (
                    terminal["session_id"] != binding.session_id
                    or terminal["entry_claim_id"] != claim["entry_claim_id"]
                    or terminal["order_index"] != order_index
                    or terminal["dispatch_receipt_id"]
                    != (dispatch["dispatch_receipt_id"] if dispatch else None)
                ):
                    raise ClaimError("STORED_TERMINAL_RECEIPT_LINEAGE_MISMATCH")
            if state == "CLAIMED_PRELAUNCH":
                if dispatch is not None or terminal is not None:
                    raise ClaimError("PRELAUNCH_ENTRY_HAS_LATER_RECEIPT")
            elif state == "DISPATCHED":
                if dispatch is None or terminal is not None:
                    raise ClaimError("DISPATCHED_ENTRY_RECEIPT_STATE_MISMATCH")
            elif state == "TERMINAL":
                if terminal is None:
                    raise ClaimError("TERMINAL_ENTRY_LACKS_RECEIPT")
            else:
                raise ClaimError("STORED_ENTRY_STATE_INVALID")
            decoded.append((state, terminal))

        successful_prefix = 0
        for entry_state, terminal in decoded:
            if entry_state == "TERMINAL" and terminal["outcome"] == "SUCCESS":
                successful_prefix += 1
            else:
                break
        if session_state == "ACTIVE":
            if next_order != successful_prefix + 1:
                raise ClaimError("STORED_NEXT_ORDER_DIFFERS_FROM_SUCCESS_PREFIX")
            if len(rows) not in {successful_prefix, successful_prefix + 1}:
                raise ClaimError("ACTIVE_SESSION_ENTRY_COUNT_INVALID")
            if len(rows) == successful_prefix + 1 and rows[-1][3] == "TERMINAL":
                raise ClaimError("ACTIVE_SESSION_HAS_UNAPPLIED_TERMINAL_ENTRY")
        elif session_state == "COMPLETE":
            if next_order != maximum + 1 or successful_prefix != maximum:
                raise ClaimError("COMPLETE_SESSION_INVARIANT_MISMATCH")
        else:
            if len(rows) != next_order or not rows:
                raise ClaimError("ABORTED_SESSION_ENTRY_COUNT_INVALID")
            last_terminal = decoded[-1][1]
            if (
                decoded[-1][0] != "TERMINAL"
                or last_terminal is None
                or last_terminal["outcome"] == "SUCCESS"
            ):
                raise ClaimError("ABORTED_SESSION_LACKS_FAILURE_OR_AMBIGUITY")

    def create_or_resume_session(
        self,
        binding: SessionBinding,
        schedule: list[dict],
        gates: dict[str, bool],
    ) -> tuple[str, dict]:
        binding.validate()
        self._require_store_binding(binding)
        if set(gates) != GATE_KEYS or not all(gates.values()):
            raise ClaimError("P_AND_E_AND_A_REQUIRED")
        current_time = trusted_utc_now()
        generated_at = timestamp_text(current_time)
        if current_time >= parse_timestamp(binding.expires_at):
            raise ClaimError("APPROVAL_OR_SESSION_EXPIRED")
        validate_execution_schedule(schedule, binding)
        binding_json = self._binding_json(binding)
        schedule_json = canonical_json(schedule)
        receipt = {
            "schema_version": "community-cohort-session-claim-v1",
            "generated_at": generated_at,
            "claim_boundary": (
                "COHORT_TOKEN_CONSUMED_SESSION_CREATED_NO_PROCESS_LAUNCHED"
            ),
            "session_id": binding.session_id,
            "claim_state": "SESSION_CLAIMED",
            "request_id": binding.request_id,
            "cycle_id": binding.cycle_id,
            "suite_id": binding.suite_id,
            "authorization_request_sha256": binding.authorization_request_sha256,
            "semantic_approval_sha256": binding.semantic_approval_sha256,
            "combined_authorization_sha256": binding.combined_authorization_sha256,
            "single_use_token": binding.single_use_token,
            "authorization_schedule_sha256": binding.authorization_schedule_sha256,
            "execution_schedule_sha256": binding.execution_schedule_sha256,
            "formal_resource_id": binding.formal_resource_id,
            "dispatcher_sha256": binding.dispatcher_sha256,
            "claim_store_identity_sha256": self.identity_sha256,
            "expires_at": binding.expires_at,
            "max_dispatches": binding.max_dispatches,
            "initial_order_index": 1,
            "hidden_oracle_exposed": False,
        }
        validate_receipt(receipt, "community_cohort_session_claim.schema.json")
        with closing(self._connect()) as database:
            database.execute("BEGIN IMMEDIATE")
            existing = database.execute(
                "SELECT session_id,binding_json,schedule_json,receipt_json "
                "FROM sessions WHERE token=?",
                (binding.single_use_token,),
            ).fetchone()
            if existing is not None:
                expected = (binding.session_id, binding_json, schedule_json)
                if existing[:3] != expected:
                    database.execute("ROLLBACK")
                    raise ClaimError("TOKEN_ALREADY_BOUND_TO_FOREIGN_SESSION")
                self._validated_session(database, binding)
                database.execute("COMMIT")
                return "EXISTING_IDENTICAL_SESSION", json.loads(existing[3])
            database.execute(
                "INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?)",
                (
                    binding.session_id,
                    binding.single_use_token,
                    binding_json,
                    schedule_json,
                    canonical_json(receipt),
                    binding.max_dispatches,
                    1,
                    "ACTIVE",
                ),
            )
            database.execute("COMMIT")
        return "CREATED", receipt

    def claim_entry(
        self,
        binding: SessionBinding,
        entry: dict,
    ) -> dict:
        current_time = trusted_utc_now()
        claimed_at = timestamp_text(current_time)
        if current_time >= parse_timestamp(binding.expires_at):
            raise ClaimError("SESSION_EXPIRED_AT_ENTRY_CLAIM")
        with closing(self._connect()) as database:
            database.execute("BEGIN IMMEDIATE")
            schedule, maximum, next_order, state = self._validated_session(
                database, binding
            )
            if state != "ACTIVE":
                database.execute("ROLLBACK")
                raise ClaimError("SESSION_NOT_ACTIVE")
            matches = [
                row
                for row in schedule
                if row["order_index"] == entry.get("order_index")
            ]
            if len(matches) != 1 or matches[0] != entry:
                database.execute("ROLLBACK")
                raise ClaimError("FOREIGN_SCHEDULE_ENTRY")
            if entry["order_index"] != next_order:
                database.execute("ROLLBACK")
                raise ClaimError("FROZEN_ORDER_VIOLATION")
            existing = database.execute(
                "SELECT 1 FROM entry_claims WHERE session_id=? "
                "AND (order_index=? OR schedule_key=?)",
                (binding.session_id, entry["order_index"], entry["schedule_key"]),
            ).fetchone()
            if existing is not None:
                database.execute("ROLLBACK")
                raise ClaimError("ENTRY_ALREADY_CONSUMED")
            used = database.execute(
                "SELECT COUNT(*) FROM entry_claims WHERE session_id=?",
                (binding.session_id,),
            ).fetchone()[0]
            if used >= maximum:
                database.execute("ROLLBACK")
                raise ClaimError("DISPATCH_BUDGET_EXHAUSTED")
            receipt = with_id(
                {
                    "schema_version": "community-schedule-entry-claim-v1",
                    "claimed_at": claimed_at,
                    "claim_boundary": ("ENTRY_CONSUMED_PRELAUNCH_NO_AUTOMATIC_RETRY"),
                    "session_id": binding.session_id,
                    "state": "CLAIMED_PRELAUNCH",
                    "order_index": entry["order_index"],
                    "task_id": entry["task_id"],
                    "repeat_index": entry["repeat_index"],
                    "arm": entry["arm"],
                    "schedule_key": entry["schedule_key"],
                    "sealed_argv_sha256": entry["sealed_argv_sha256"],
                    "resolved_argv": entry["resolved_argv"],
                    "resolved_argv_sha256": entry["resolved_argv_sha256"],
                    "formal_gpu_uuids": entry["formal_gpu_uuids"],
                    "launch_attempt_consumed": True,
                },
                "entry_claim_id",
            )
            validate_receipt(receipt, "community_schedule_entry_claim.schema.json")
            try:
                database.execute(
                    "INSERT INTO entry_claims VALUES (?,?,?,?,?,?,NULL,NULL,NULL)",
                    (
                        binding.session_id,
                        entry["order_index"],
                        entry["schedule_key"],
                        canonical_json(entry),
                        canonical_json(receipt),
                        "CLAIMED_PRELAUNCH",
                    ),
                )
            except sqlite3.IntegrityError as error:
                database.execute("ROLLBACK")
                raise ClaimError("ENTRY_ALREADY_CONSUMED") from error
            database.execute("COMMIT")
        return receipt

    @staticmethod
    def _validate_process_identity(process: dict, entry: dict) -> None:
        if set(process) != PROCESS_IDENTITY_KEYS:
            raise ClaimError("INCOMPLETE_PROCESS_IDENTITY")
        if not isinstance(process["pid"], int) or process["pid"] < 1:
            raise ClaimError("INVALID_PROCESS_PID")
        if (
            not isinstance(process["proc_start_ticks"], int)
            or process["proc_start_ticks"] < 0
        ):
            raise ClaimError("INVALID_PROCESS_START_TICKS")
        if not all(
            isinstance(process[key], str) and process[key]
            for key in ("hostname", "boot_id", "executable_path")
        ):
            raise ClaimError("INCOMPLETE_PROCESS_IDENTITY")
        require_sha256(process["argv_sha256"], "process.argv_sha256")
        require_sha256(process["executable_sha256"], "process.executable_sha256")
        if process["argv_sha256"] != entry["resolved_argv_sha256"]:
            raise ClaimError("PROCESS_ARGV_DIFFERS_FROM_ENTRY_CLAIM")
        if process["gpu_uuids"] != entry["formal_gpu_uuids"]:
            raise ClaimError("PROCESS_GPU_UUIDS_DIFFER_FROM_ENTRY_CLAIM")

    def record_dispatch(
        self,
        binding: SessionBinding,
        order_index: int,
        process_identity: dict,
    ) -> dict:
        current_time = trusted_utc_now()
        dispatched_at = timestamp_text(current_time)
        if current_time >= parse_timestamp(binding.expires_at):
            raise ClaimError("SESSION_EXPIRED_BEFORE_DISPATCH")
        with closing(self._connect()) as database:
            database.execute("BEGIN IMMEDIATE")
            _, _, next_order, session_state = self._validated_session(database, binding)
            if session_state != "ACTIVE" or order_index != next_order:
                database.execute("ROLLBACK")
                raise ClaimError("SESSION_ENTRY_NOT_DISPATCHABLE")
            row = database.execute(
                "SELECT entry_json,claim_receipt_json,state FROM entry_claims "
                "WHERE session_id=? AND order_index=?",
                (binding.session_id, order_index),
            ).fetchone()
            if row is None or row[2] != "CLAIMED_PRELAUNCH":
                database.execute("ROLLBACK")
                raise ClaimError("ENTRY_NOT_IN_PRELAUNCH_STATE")
            entry = json.loads(row[0])
            claim = json.loads(row[1])
            self._require_self_id(claim, "entry_claim_id")
            validate_receipt(claim, "community_schedule_entry_claim.schema.json")
            if parse_timestamp(dispatched_at) < parse_timestamp(claim["claimed_at"]):
                database.execute("ROLLBACK")
                raise ClaimError("DISPATCH_PREDATES_ENTRY_CLAIM")
            self._validate_process_identity(process_identity, entry)
            receipt = with_id(
                {
                    "schema_version": "community-entry-dispatch-receipt-v2",
                    "dispatched_at": dispatched_at,
                    "claim_boundary": (
                        "PROCESS_IDENTITY_RECORDED_AFTER_ATOMIC_ENTRY_CLAIM"
                    ),
                    "session_id": binding.session_id,
                    "entry_claim_id": claim["entry_claim_id"],
                    "order_index": order_index,
                    "schedule_key": entry["schedule_key"],
                    "state": "DISPATCHED",
                    "formal_resource_id": binding.formal_resource_id,
                    "resolved_argv_sha256": entry["resolved_argv_sha256"],
                    "formal_gpu_uuids": entry["formal_gpu_uuids"],
                    "process_identity": process_identity,
                    "launch_attempt_consumed": True,
                },
                "dispatch_receipt_id",
            )
            validate_receipt(receipt, "community_entry_dispatch_receipt_v2.schema.json")
            changed = database.execute(
                "UPDATE entry_claims SET state='DISPATCHED',process_identity_json=?,"
                "dispatch_receipt_json=? WHERE session_id=? AND order_index=? "
                "AND state='CLAIMED_PRELAUNCH'",
                (
                    canonical_json(process_identity),
                    canonical_json(receipt),
                    binding.session_id,
                    order_index,
                ),
            ).rowcount
            if changed != 1:
                database.execute("ROLLBACK")
                raise ClaimError("ENTRY_NOT_IN_PRELAUNCH_STATE")
            database.execute("COMMIT")
        return receipt

    def record_terminal(
        self,
        binding: SessionBinding,
        order_index: int,
        outcome: str,
    ) -> dict:
        if outcome not in TERMINAL_OUTCOMES:
            raise ClaimError("INVALID_TERMINAL_OUTCOME")
        return self._terminal_transition(binding, order_index, outcome, {"DISPATCHED"})

    def record_ambiguous(
        self,
        binding: SessionBinding,
        order_index: int,
        outcome: str,
    ) -> dict:
        if outcome not in AMBIGUOUS_OUTCOMES:
            raise ClaimError("INVALID_AMBIGUOUS_OUTCOME")
        allowed_states = (
            {"CLAIMED_PRELAUNCH"}
            if outcome == "AMBIGUOUS_PRELAUNCH"
            else {"CLAIMED_PRELAUNCH", "DISPATCHED"}
        )
        return self._terminal_transition(
            binding,
            order_index,
            outcome,
            allowed_states,
        )

    def _terminal_transition(
        self,
        binding: SessionBinding,
        order_index: int,
        outcome: str,
        allowed_states: set[str],
    ) -> dict:
        recorded_at = timestamp_text(trusted_utc_now())
        with closing(self._connect()) as database:
            database.execute("BEGIN IMMEDIATE")
            _, maximum, next_order, session_state = self._validated_session(
                database, binding
            )
            if session_state != "ACTIVE" or order_index != next_order:
                database.execute("ROLLBACK")
                raise ClaimError("SESSION_ENTRY_NOT_TERMINABLE")
            row = database.execute(
                "SELECT claim_receipt_json,state,dispatch_receipt_json "
                "FROM entry_claims WHERE session_id=? AND order_index=?",
                (binding.session_id, order_index),
            ).fetchone()
            if row is None or row[1] not in allowed_states:
                database.execute("ROLLBACK")
                raise ClaimError("ENTRY_NOT_IN_TERMINABLE_STATE")
            claim = json.loads(row[0])
            dispatch = json.loads(row[2]) if row[2] else None
            self._require_self_id(claim, "entry_claim_id")
            validate_receipt(claim, "community_schedule_entry_claim.schema.json")
            if dispatch is not None:
                self._require_self_id(dispatch, "dispatch_receipt_id")
                validate_receipt(
                    dispatch, "community_entry_dispatch_receipt_v2.schema.json"
                )
            lower_bound = dispatch["dispatched_at"] if dispatch else claim["claimed_at"]
            if parse_timestamp(recorded_at) < parse_timestamp(lower_bound):
                database.execute("ROLLBACK")
                raise ClaimError("TERMINAL_RECEIPT_PREDATES_ENTRY_STATE")
            receipt = with_id(
                {
                    "schema_version": "community-entry-terminal-receipt-v1",
                    "recorded_at": recorded_at,
                    "claim_boundary": (
                        "TERMINAL_ENTRY_EVIDENCE_PRESERVES_FAILURE_AND_AMBIGUITY"
                    ),
                    "session_id": binding.session_id,
                    "entry_claim_id": claim["entry_claim_id"],
                    "order_index": order_index,
                    "schedule_key": claim["schedule_key"],
                    "state": "TERMINAL",
                    "outcome": outcome,
                    "dispatch_receipt_id": (
                        dispatch["dispatch_receipt_id"] if dispatch else None
                    ),
                    "launch_attempt_consumed": True,
                    "automatic_retry_allowed": False,
                },
                "terminal_receipt_id",
            )
            validate_receipt(receipt, "community_entry_terminal_receipt.schema.json")
            database.execute(
                "UPDATE entry_claims SET state='TERMINAL',terminal_receipt_json=? "
                "WHERE session_id=? AND order_index=?",
                (canonical_json(receipt), binding.session_id, order_index),
            )
            if outcome == "SUCCESS":
                new_next = next_order + 1
                new_state = "COMPLETE" if new_next > maximum else "ACTIVE"
                database.execute(
                    "UPDATE sessions SET next_order_index=?,state=? WHERE session_id=?",
                    (new_next, new_state, binding.session_id),
                )
            else:
                database.execute(
                    "UPDATE sessions SET state='ABORTED' WHERE session_id=?",
                    (binding.session_id,),
                )
            database.execute("COMMIT")
        return receipt

    def recovery_state(self, binding: SessionBinding, order_index: int) -> str:
        with closing(self._connect()) as database:
            self._validated_session(database, binding)
            row = database.execute(
                "SELECT state FROM entry_claims WHERE session_id=? AND order_index=?",
                (binding.session_id, order_index),
            ).fetchone()
        if row is None:
            return "UNCLAIMED_RESUMABLE"
        if row[0] in {"CLAIMED_PRELAUNCH", "DISPATCHED"}:
            return "AMBIGUOUS_CONSUMED_NO_AUTOMATIC_RETRY"
        return row[0]

    def validate_final_coverage(
        self, binding: SessionBinding, terminal_receipts: list[dict]
    ) -> dict:
        with closing(self._connect()) as database:
            schedule, _, next_order, state = self._validated_session(database, binding)
            stored_rows = database.execute(
                "SELECT order_index,terminal_receipt_json FROM entry_claims "
                "WHERE session_id=? ORDER BY order_index",
                (binding.session_id,),
            ).fetchall()
        if state not in {"COMPLETE", "ABORTED"}:
            raise ClaimError("SESSION_NOT_TERMINAL")
        if any(
            row.get("session_id") != binding.session_id for row in terminal_receipts
        ):
            raise ClaimError("MIXED_SESSION_RECEIPTS")
        if any(value is None for _, value in stored_rows):
            raise ClaimError("MISSING_TERMINAL_RECEIPT")
        stored = [json.loads(value) for _, value in stored_rows]
        for receipt in stored:
            self._require_self_id(receipt, "terminal_receipt_id")
            validate_receipt(receipt, "community_entry_terminal_receipt.schema.json")
        if terminal_receipts != stored:
            raise ClaimError("INCOMPLETE_REORDERED_OR_FOREIGN_RECEIPTS")
        expected_count = len(schedule) if state == "COMPLETE" else next_order
        if len(stored) != expected_count:
            raise ClaimError("TERMINAL_COVERAGE_DIFFERS_FROM_SESSION_STATE")
        if [row["order_index"] for row in stored] != list(range(1, expected_count + 1)):
            raise ClaimError("TERMINAL_RECEIPT_ORDER_GAP")
        if state == "COMPLETE" and any(row["outcome"] != "SUCCESS" for row in stored):
            raise ClaimError("COMPLETE_SESSION_HAS_NON_SUCCESS_OUTCOME")
        if state == "ABORTED" and stored[-1]["outcome"] == "SUCCESS":
            raise ClaimError("ABORTED_SESSION_LACKS_FAILURE_OR_AMBIGUITY")
        return {
            "session_id": binding.session_id,
            "state": state,
            "terminal_receipt_count": len(stored),
            "expected_schedule_count": len(schedule),
            "complete": state == "COMPLETE",
        }

    def snapshot(self, binding: SessionBinding) -> dict:
        with closing(self._connect()) as database:
            _, maximum, next_order, state = self._validated_session(database, binding)
            claims = database.execute(
                "SELECT order_index,state FROM entry_claims WHERE session_id=? "
                "ORDER BY order_index",
                (binding.session_id,),
            ).fetchall()
        return {
            "session_id": binding.session_id,
            "max_dispatches": maximum,
            "next_order_index": next_order,
            "state": state,
            "entries": [
                {"order_index": order_index, "state": state}
                for order_index, state in claims
            ],
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    parser.add_argument("session-id")
    args = parser.parse_args()
    require_sha256(args.session_id, "session_id")
    with closing(sqlite3.connect(args.database)) as database:
        row = database.execute(
            "SELECT max_dispatches,next_order_index,state FROM sessions "
            "WHERE session_id=?",
            (args.session_id,),
        ).fetchone()
    if row is None:
        raise ClaimError("FOREIGN_OR_MISSING_SESSION")
    print(
        json.dumps(
            {
                "session_id": args.session_id,
                "max_dispatches": row[0],
                "next_order_index": row[1],
                "state": row[2],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
