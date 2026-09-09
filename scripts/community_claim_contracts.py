#!/usr/bin/env python3
"""Pure contracts for atomic community cohort claims.

This module owns canonical identities and validation only. It deliberately has
no persistence, process-launch, framework, remote-host, or GPU surface.
"""

from __future__ import annotations

import hashlib
import json
import re
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
    claim_store_epoch_sha256: str
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
            "claim_store_epoch_sha256",
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
