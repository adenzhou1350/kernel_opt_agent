#!/usr/bin/env python3
"""Queue qualification jobs and atomically reserve compatible GPU gangs.

This is a non-launching control plane. A reservation never authorizes a
process, GPU work, correctness claim, or performance claim; the worker must
still pass the task-specific dispatcher and authorization gates.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from qualification_environment import evaluate as evaluate_environment
from qualification_environment import validate as validate_environment_object
from schema_utils import validate_instance


LEASE_VERSION = "resource-broker-lease-v1"
TERMINAL_VERSION = "resource-broker-terminal-v1"
WITHDRAWAL_VERSION = "resource-broker-withdrawal-v1"
ENVIRONMENT_DECISION_RANK = {
    "REUSE_FULL_CLOSURE": 0,
    "REUSE_DEPENDENCIES_REBIND_SOURCE": 1,
}


def root() -> Path:
    return Path(__file__).resolve().parents[1]


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def timestamp(value: datetime | None = None) -> str:
    value = value or datetime.now(UTC)
    if value.tzinfo is None:
        raise ValueError("trusted broker timestamps require a timezone")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("broker timestamp requires a timezone")
    return parsed.astimezone(UTC)


def read_object(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected an object: {path}")
    return value


def validate(value: dict, schema_name: str, label: str) -> None:
    schema = read_object(root() / "schemas" / schema_name)
    errors = validate_instance(value, schema)
    if errors:
        raise ValueError(f"invalid {label}: " + "; ".join(errors))


def validate_job(job: dict) -> None:
    validate(job, "resource_broker_job.schema.json", "broker job")
    required_gpu_uuids = job["resource"].get("required_gpu_uuids")
    if (
        required_gpu_uuids is not None
        and len(required_gpu_uuids) != job["resource"]["gpu_count"]
    ):
        raise ValueError("required_gpu_uuids must contain exactly gpu_count identities")
    validate_environment_object(
        job["environment_request"],
        "qualification_environment_request.schema.json",
        "environment request",
    )


def validate_inventory(inventory: dict) -> None:
    validate(inventory, "resource_broker_inventory.schema.json", "broker inventory")
    host_ids: set[str] = set()
    gpu_uuids: set[str] = set()
    for host in inventory["hosts"]:
        if host["host_id"] in host_ids:
            raise ValueError("duplicate host_id in inventory")
        host_ids.add(host["host_id"])
        closure_ids: set[str] = set()
        for closure in host["environment_closures"]:
            validate_environment_object(
                closure,
                "qualification_environment_closure.schema.json",
                "environment closure",
            )
            extension = closure["execution"]["native_extension"]
            if extension["required"] and (
                not extension["artifact_sha256"] or not extension["source_tree_sha"]
            ):
                raise ValueError("materialized extension identity is incomplete")
            if not extension["required"] and (
                extension["artifact_sha256"] or extension["source_tree_sha"]
            ):
                raise ValueError("unused extension identity must be empty")
            if closure["closure_id"] in closure_ids:
                raise ValueError("duplicate closure_id on host")
            closure_ids.add(closure["closure_id"])
        for gpu in host["gpus"]:
            if gpu["uuid"] in gpu_uuids:
                raise ValueError("GPU UUID appears on more than one host")
            gpu_uuids.add(gpu["uuid"])


def environment_decision(host: dict, request: dict) -> dict | None:
    decisions = [
        evaluate_environment(closure, request)
        for closure in host["environment_closures"]
    ]
    decisions = [
        item for item in decisions if item["decision"] in ENVIRONMENT_DECISION_RANK
    ]
    if not decisions:
        return None
    return min(
        decisions,
        key=lambda item: (
            ENVIRONMENT_DECISION_RANK[item["decision"]],
            item["closure_id"],
        ),
    )


class ResourceBroker:
    """Durable queue with transactionally exclusive GPU allocation."""

    def __init__(self, database: Path) -> None:
        self.database = database.resolve()
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(
            self.database, isolation_level=None, timeout=30
        )
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(
            """
            PRAGMA journal_mode=WAL;
            PRAGMA foreign_keys=ON;
            CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY,
                request_sha256 TEXT NOT NULL,
                request_json TEXT NOT NULL,
                state TEXT NOT NULL,
                priority_score INTEGER NOT NULL,
                submitted_at TEXT NOT NULL,
                terminal_json TEXT
            );
            CREATE TABLE IF NOT EXISTS leases (
                lease_id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL UNIQUE REFERENCES jobs(job_id),
                host_id TEXT NOT NULL,
                worker_id TEXT NOT NULL,
                exclusive_host INTEGER NOT NULL,
                state TEXT NOT NULL,
                acquired_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                lease_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS allocations (
                gpu_uuid TEXT PRIMARY KEY,
                host_id TEXT NOT NULL,
                lease_id TEXT NOT NULL REFERENCES leases(lease_id)
            );
            CREATE TABLE IF NOT EXISTS exclusive_hosts (
                host_id TEXT PRIMARY KEY,
                lease_id TEXT NOT NULL REFERENCES leases(lease_id)
            );
            """
        )

    def close(self) -> None:
        self.connection.close()

    def submit(self, job: dict, *, now: datetime | None = None) -> dict:
        validate_job(job)
        if job["origin"]["thread_id"] != job["callback"]["thread_id"]:
            raise ValueError("callback must return to the originating task")
        gate = job["dispatch_gate"]
        if (gate["state"] == "READY") != (gate["identity_sha256"] is not None):
            raise ValueError("a READY dispatch gate requires one bound identity")
        state = "QUEUED" if gate["state"] == "READY" else "BLOCKED_AUTHORIZATION"
        submitted_at = timestamp(now)
        request_sha256 = digest(job)
        try:
            self.connection.execute(
                "INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?, NULL)",
                (
                    job["job_id"],
                    request_sha256,
                    canonical_json(job),
                    state,
                    job["priority_score"],
                    submitted_at,
                ),
            )
        except sqlite3.IntegrityError as error:
            row = self.connection.execute(
                "SELECT request_sha256 FROM jobs WHERE job_id = ?",
                (job["job_id"],),
            ).fetchone()
            if row and row["request_sha256"] == request_sha256:
                return self.job(job["job_id"])
            raise ValueError("job_id already names a different request") from error
        return self.job(job["job_id"])

    def bind_dispatch_gate(self, job: dict) -> dict:
        """Atomically bind a READY gate to an otherwise immutable blocked job.

        The broker does not validate the supervisor's authorization semantics;
        it only prevents a later gate identity from changing the frozen job.
        """
        validate_job(job)
        if job["origin"]["thread_id"] != job["callback"]["thread_id"]:
            raise ValueError("callback must return to the originating task")
        gate = job["dispatch_gate"]
        if gate["state"] != "READY" or gate["identity_sha256"] is None:
            raise ValueError("dispatch-gate binding requires one READY identity")

        request_sha256 = digest(job)
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            row = self.connection.execute(
                "SELECT request_sha256, request_json, state FROM jobs WHERE job_id = ?",
                (job["job_id"],),
            ).fetchone()
            if row is None:
                raise ValueError("unknown job_id")
            if row["state"] == "QUEUED" and row["request_sha256"] == request_sha256:
                self.connection.execute("COMMIT")
                return self.job(job["job_id"])
            if row["state"] != "BLOCKED_AUTHORIZATION":
                raise ValueError("only a blocked authorization job can bind a gate")

            blocked = json.loads(row["request_json"])
            blocked_gate = blocked["dispatch_gate"]
            if blocked_gate != {"state": "BLOCKED", "identity_sha256": None}:
                raise ValueError("stored blocked dispatch gate is not canonical")
            blocked_body = {
                key: value for key, value in blocked.items() if key != "dispatch_gate"
            }
            ready_body = {
                key: value for key, value in job.items() if key != "dispatch_gate"
            }
            if ready_body != blocked_body:
                raise ValueError(
                    "dispatch-gate binding cannot change the frozen job request"
                )

            self.connection.execute(
                "UPDATE jobs SET request_sha256 = ?, request_json = ?, "
                "state = 'QUEUED' WHERE job_id = ?",
                (request_sha256, canonical_json(job), job["job_id"]),
            )
            self.connection.execute("COMMIT")
            return self.job(job["job_id"])
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise

    def job(self, job_id: str) -> dict:
        row = self.connection.execute(
            "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
        if row is None:
            raise ValueError("unknown job_id")
        return {
            "job_id": row["job_id"],
            "request_sha256": row["request_sha256"],
            "state": row["state"],
            "priority_score": row["priority_score"],
            "submitted_at": row["submitted_at"],
            "terminal": (
                json.loads(row["terminal_json"]) if row["terminal_json"] else None
            ),
        }

    def withdraw(
        self,
        job_id: str,
        reason_identity: dict,
        *,
        now: datetime | None = None,
    ) -> dict:
        """Withdraw an unleased job without deleting its audit history."""
        if (
            set(reason_identity) != {"path", "sha256"}
            or not isinstance(reason_identity["path"], str)
            or not reason_identity["path"]
        ):
            raise ValueError("withdrawal reason identity must contain path and sha256")
        reason_sha256 = reason_identity["sha256"]
        if (
            not isinstance(reason_sha256, str)
            or len(reason_sha256) != 64
            or any(character not in "0123456789abcdef" for character in reason_sha256)
        ):
            raise ValueError("withdrawal reason sha256 must be a full digest")
        now = now or datetime.now(UTC)
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            row = self.connection.execute(
                "SELECT state FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            if row is None:
                raise ValueError("unknown job_id")
            if row["state"] not in {"BLOCKED_AUTHORIZATION", "QUEUED"}:
                raise ValueError(
                    "only an unleased blocked or queued job can be withdrawn"
                )
            lease = self.connection.execute(
                "SELECT 1 FROM leases WHERE job_id = ?", (job_id,)
            ).fetchone()
            if lease is not None:
                raise ValueError("a job with lease history cannot be withdrawn")
            terminal = {
                "schema_version": WITHDRAWAL_VERSION,
                "job_id": job_id,
                "outcome": "WITHDRAWN",
                "completed_at": timestamp(now),
                "reason_identity": reason_identity,
                "claim_boundary": (
                    "UNLEASED_QUEUE_WITHDRAWAL_ONLY_NOT_RESULT_OR_EXECUTION_EVIDENCE"
                ),
            }
            self.connection.execute(
                "UPDATE jobs SET state = 'WITHDRAWN', terminal_json = ? "
                "WHERE job_id = ?",
                (canonical_json(terminal), job_id),
            )
            self.connection.execute("COMMIT")
            return terminal
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise

    def _mark_stale(self, now: datetime) -> None:
        rows = self.connection.execute(
            "SELECT lease_id, job_id, expires_at FROM leases WHERE state = 'ACTIVE'"
        ).fetchall()
        for row in rows:
            if parse_timestamp(row["expires_at"]) <= now:
                self.connection.execute(
                    "UPDATE leases SET state = 'STALE' WHERE lease_id = ?",
                    (row["lease_id"],),
                )
                self.connection.execute(
                    "UPDATE jobs SET state = "
                    "'STALE_REQUIRES_RECONCILIATION' WHERE job_id = ?",
                    (row["job_id"],),
                )

    def _occupied(self) -> tuple[set[str], set[str], set[str]]:
        gpu_uuids = {
            row[0]
            for row in self.connection.execute("SELECT gpu_uuid FROM allocations")
        }
        hosts = {
            row[0]
            for row in self.connection.execute(
                "SELECT DISTINCT host_id FROM allocations"
            )
        }
        exclusive = {
            row[0]
            for row in self.connection.execute("SELECT host_id FROM exclusive_hosts")
        }
        return gpu_uuids, hosts, exclusive

    @staticmethod
    def _host_static_resource_match(job: dict, host: dict) -> bool:
        resource = job["resource"]
        required_gpu_uuids = set(resource.get("required_gpu_uuids", []))
        compatible_gpu_uuids = {
            gpu["uuid"]
            for gpu in host["gpus"]
            if gpu["memory_gib"] >= resource["min_memory_gib"]
        }
        return (
            host["architecture"] in resource["architectures"]
            and set(resource["required_capabilities"]).issubset(host["capabilities"])
            and required_gpu_uuids.issubset(compatible_gpu_uuids)
            and len(compatible_gpu_uuids) >= resource["gpu_count"]
        )

    @staticmethod
    def _host_match(
        job: dict,
        host: dict,
        occupied: set[str],
        occupied_hosts: set[str],
        exclusive_hosts: set[str],
    ) -> dict | None:
        resource = job["resource"]
        if host[
            "state"
        ] != "AVAILABLE" or not ResourceBroker._host_static_resource_match(job, host):
            return None
        if host["host_id"] in exclusive_hosts:
            return None
        if resource["exclusive_host"] and host["host_id"] in occupied_hosts:
            return None
        decision = environment_decision(host, job["environment_request"])
        if decision is None:
            return None
        free = sorted(
            gpu["uuid"]
            for gpu in host["gpus"]
            if gpu["state"] == "FREE"
            and gpu["memory_gib"] >= resource["min_memory_gib"]
            and gpu["uuid"] not in occupied
        )
        required_gpu_uuids = resource.get("required_gpu_uuids")
        if required_gpu_uuids is not None:
            required = sorted(required_gpu_uuids)
            if not set(required).issubset(free):
                return None
            free = required
        if len(free) < resource["gpu_count"]:
            return None
        return {
            "host": host,
            "gpu_uuids": free[: resource["gpu_count"]],
            "environment": decision,
        }

    def acquire(
        self,
        inventory: dict,
        *,
        ttl_seconds: int = 900,
        now: datetime | None = None,
        job_id: str | None = None,
    ) -> dict | None:
        validate_inventory(inventory)
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        now = now or datetime.now(UTC)
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            self._mark_stale(now)
            occupied, occupied_hosts, exclusive_hosts = self._occupied()
            if job_id is not None and (not isinstance(job_id, str) or not job_id):
                raise ValueError("job_id must be a non-empty string when provided")
            if job_id is None:
                rows = self.connection.execute(
                    "SELECT * FROM jobs WHERE state = 'QUEUED' "
                    "ORDER BY priority_score DESC, submitted_at ASC, job_id ASC"
                ).fetchall()
            else:
                rows = self.connection.execute(
                    "SELECT * FROM jobs WHERE state = 'QUEUED' AND job_id = ?",
                    (job_id,),
                ).fetchall()
            for row in rows:
                job = json.loads(row["request_json"])
                matches = []
                for host in inventory["hosts"]:
                    match = self._host_match(
                        job,
                        host,
                        occupied,
                        occupied_hosts,
                        exclusive_hosts,
                    )
                    if match:
                        matches.append(match)
                if not matches:
                    continue
                match = min(
                    matches,
                    key=lambda item: (
                        ENVIRONMENT_DECISION_RANK[item["environment"]["decision"]],
                        item["host"]["host_id"],
                    ),
                )
                acquired_at = timestamp(now)
                expires_at = timestamp(now + timedelta(seconds=ttl_seconds))
                lease_id = uuid.uuid4().hex
                selected_closure = next(
                    closure
                    for closure in match["host"]["environment_closures"]
                    if closure["closure_id"] == match["environment"]["closure_id"]
                )
                lease = {
                    "schema_version": LEASE_VERSION,
                    "lease_id": lease_id,
                    "job_id": job["job_id"],
                    "request_sha256": row["request_sha256"],
                    "origin": job["origin"],
                    "callback": job["callback"],
                    "host_id": match["host"]["host_id"],
                    "worker_id": match["host"]["worker_id"],
                    "gpu_uuids": match["gpu_uuids"],
                    "exclusive_host": job["resource"]["exclusive_host"],
                    "environment": {
                        "closure_id": match["environment"]["closure_id"],
                        "decision": match["environment"]["decision"],
                        "closure_sha256": digest(selected_closure),
                        "request_sha256": digest(job["environment_request"]),
                    },
                    "dispatch_gate_identity_sha256": job["dispatch_gate"][
                        "identity_sha256"
                    ],
                    "budget": job["budget"],
                    "state": "ACTIVE_RESOURCE_RESERVATION",
                    "acquired_at": acquired_at,
                    "expires_at": expires_at,
                    "claim_boundary": (
                        "RESOURCE_RESERVATION_ONLY_NOT_PROCESS_OR_GPU_"
                        "EXECUTION_AUTHORIZATION"
                    ),
                }
                self.connection.execute(
                    "INSERT INTO leases VALUES (?, ?, ?, ?, ?, 'ACTIVE', ?, ?, ?)",
                    (
                        lease_id,
                        job["job_id"],
                        match["host"]["host_id"],
                        match["host"]["worker_id"],
                        int(job["resource"]["exclusive_host"]),
                        acquired_at,
                        expires_at,
                        canonical_json(lease),
                    ),
                )
                self.connection.executemany(
                    "INSERT INTO allocations VALUES (?, ?, ?)",
                    [
                        (gpu, match["host"]["host_id"], lease_id)
                        for gpu in match["gpu_uuids"]
                    ],
                )
                if job["resource"]["exclusive_host"]:
                    self.connection.execute(
                        "INSERT INTO exclusive_hosts VALUES (?, ?)",
                        (match["host"]["host_id"], lease_id),
                    )
                self.connection.execute(
                    "UPDATE jobs SET state = 'LEASED' WHERE job_id = ?",
                    (job["job_id"],),
                )
                self.connection.execute("COMMIT")
                return lease
            self.connection.execute("COMMIT")
            return None
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise

    def heartbeat(
        self,
        lease_id: str,
        *,
        ttl_seconds: int = 900,
        now: datetime | None = None,
    ) -> dict:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        now = now or datetime.now(UTC)
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            self._mark_stale(now)
            row = self.connection.execute(
                "SELECT * FROM leases WHERE lease_id = ?", (lease_id,)
            ).fetchone()
            if row is None or row["state"] != "ACTIVE":
                raise ValueError("only an active lease can heartbeat")
            expires_at = timestamp(now + timedelta(seconds=ttl_seconds))
            lease = json.loads(row["lease_json"])
            lease["expires_at"] = expires_at
            self.connection.execute(
                "UPDATE leases SET expires_at = ?, lease_json = ? WHERE lease_id = ?",
                (expires_at, canonical_json(lease), lease_id),
            )
            self.connection.execute("COMMIT")
            return lease
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise

    def complete(
        self,
        lease_id: str,
        outcome: str,
        result_identity: dict,
        *,
        now: datetime | None = None,
    ) -> dict:
        if outcome not in {"SUCCEEDED", "FAILED", "ABANDONED"}:
            raise ValueError("invalid terminal outcome")
        if (
            set(result_identity) != {"path", "sha256"}
            or not isinstance(result_identity["path"], str)
            or not result_identity["path"]
        ):
            raise ValueError("result identity must contain only path and sha256")
        result_sha256 = result_identity["sha256"]
        if (
            not isinstance(result_sha256, str)
            or len(result_sha256) != 64
            or any(character not in "0123456789abcdef" for character in result_sha256)
        ):
            raise ValueError("result sha256 must be a full digest")
        now = now or datetime.now(UTC)
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            self._mark_stale(now)
            row = self.connection.execute(
                "SELECT * FROM leases WHERE lease_id = ?", (lease_id,)
            ).fetchone()
            if row is None or row["state"] not in {"ACTIVE", "STALE"}:
                raise ValueError("lease is not terminalizable")
            lease = json.loads(row["lease_json"])
            terminal = {
                "schema_version": TERMINAL_VERSION,
                "lease_id": lease_id,
                "job_id": row["job_id"],
                "outcome": outcome,
                "completed_at": timestamp(now),
                "result_identity": result_identity,
                "callback": lease["callback"],
                "claim_boundary": (
                    "RESOURCE_RELEASE_AND_RESULT_ROUTING_ONLY_"
                    "RESULT_CONTENT_NOT_VALIDATED"
                ),
            }
            self.connection.execute(
                "DELETE FROM allocations WHERE lease_id = ?", (lease_id,)
            )
            self.connection.execute(
                "DELETE FROM exclusive_hosts WHERE lease_id = ?", (lease_id,)
            )
            self.connection.execute(
                "UPDATE leases SET state = 'RELEASED' WHERE lease_id = ?",
                (lease_id,),
            )
            self.connection.execute(
                "UPDATE jobs SET state = ?, terminal_json = ? WHERE job_id = ?",
                (outcome, canonical_json(terminal), row["job_id"]),
            )
            self.connection.execute("COMMIT")
            return terminal
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise

    def plan(self, inventory: dict, *, now: datetime | None = None) -> dict:
        """Explain queue readiness without reserving a GPU or launching work."""
        validate_inventory(inventory)
        now = now or datetime.now(UTC)
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            self._mark_stale(now)
            occupied, occupied_hosts, exclusive_hosts = self._occupied()
            rows = self.connection.execute(
                "SELECT * FROM jobs ORDER BY priority_score DESC, "
                "submitted_at ASC, job_id ASC"
            ).fetchall()
            jobs = []
            for row in rows:
                job = json.loads(row["request_json"])
                item = {
                    "job_id": row["job_id"],
                    "lane_id": job["origin"]["lane_id"],
                    "candidate_id": job["origin"]["candidate_id"],
                    "priority_score": row["priority_score"],
                    "broker_state": row["state"],
                    "gpu_count": job["resource"]["gpu_count"],
                }
                if row["state"] != "QUEUED":
                    item["plan_state"] = row["state"]
                    item["compatible_host_ids"] = []
                    jobs.append(item)
                    continue

                hardware_hosts = [
                    host
                    for host in inventory["hosts"]
                    if self._host_static_resource_match(job, host)
                ]
                environment_hosts = [
                    host
                    for host in hardware_hosts
                    if environment_decision(host, job["environment_request"])
                    is not None
                ]
                ready_hosts = [
                    host
                    for host in environment_hosts
                    if self._host_match(
                        job,
                        host,
                        occupied,
                        occupied_hosts,
                        exclusive_hosts,
                    )
                    is not None
                ]
                if ready_hosts:
                    plan_state = "READY_FOR_RESOURCE_RESERVATION"
                    compatible_hosts = ready_hosts
                elif environment_hosts:
                    plan_state = "WAITING_FOR_GPU"
                    compatible_hosts = environment_hosts
                elif hardware_hosts:
                    plan_state = "ENVIRONMENT_PREPARATION_REQUIRED"
                    compatible_hosts = hardware_hosts
                else:
                    plan_state = "NO_COMPATIBLE_RESOURCE"
                    compatible_hosts = []
                item["plan_state"] = plan_state
                item["compatible_host_ids"] = sorted(
                    host["host_id"] for host in compatible_hosts
                )
                jobs.append(item)
            self.connection.execute("COMMIT")
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise
        return {
            "schema_version": "resource-broker-plan-v1",
            "generated_at": timestamp(now),
            "inventory_id": inventory["inventory_id"],
            "jobs": jobs,
            "claim_boundary": (
                "SCHEDULING_EXPLANATION_ONLY_NOT_A_RESERVATION_OR_EXECUTION_AUTHORIZATION"
            ),
        }

    def snapshot(self, *, now: datetime | None = None) -> dict:
        now = now or datetime.now(UTC)
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            self._mark_stale(now)
            jobs = [
                dict(row)
                for row in self.connection.execute(
                    "SELECT job_id, request_sha256, state, priority_score, "
                    "submitted_at FROM jobs ORDER BY priority_score DESC, "
                    "submitted_at ASC, job_id ASC"
                )
            ]
            leases = [
                dict(row)
                for row in self.connection.execute(
                    "SELECT lease_id, job_id, host_id, worker_id, state, "
                    "acquired_at, expires_at FROM leases "
                    "ORDER BY acquired_at, lease_id"
                )
            ]
            allocations = [
                dict(row)
                for row in self.connection.execute(
                    "SELECT gpu_uuid, host_id, lease_id FROM allocations "
                    "ORDER BY host_id, gpu_uuid"
                )
            ]
            self.connection.execute("COMMIT")
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise
        return {
            "schema_version": "resource-broker-snapshot-v1",
            "generated_at": timestamp(now),
            "jobs": jobs,
            "leases": leases,
            "allocations": allocations,
            "claim_boundary": (
                "CONTROL_PLANE_STATE_ONLY_NOT_LIVE_MACHINE_OR_PROCESS_ATTESTATION"
            ),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path)
    commands = parser.add_subparsers(dest="action", required=True)
    submit = commands.add_parser("submit")
    submit.add_argument("--job", required=True, type=Path)
    bind_gate = commands.add_parser("bind-gate")
    bind_gate.add_argument("--job", required=True, type=Path)
    acquire = commands.add_parser("acquire")
    acquire.add_argument("--inventory", required=True, type=Path)
    acquire.add_argument("--ttl-seconds", type=int, default=900)
    acquire.add_argument(
        "--job-id",
        help="atomically acquire only this queued job; omit for normal scheduling",
    )
    heartbeat = commands.add_parser("heartbeat")
    heartbeat.add_argument("--lease-id", required=True)
    heartbeat.add_argument("--ttl-seconds", type=int, default=900)
    complete = commands.add_parser("complete")
    complete.add_argument("--lease-id", required=True)
    complete.add_argument(
        "--outcome", choices=("SUCCEEDED", "FAILED", "ABANDONED"), required=True
    )
    complete.add_argument("--result-path", required=True)
    complete.add_argument("--result-sha256", required=True)
    withdraw = commands.add_parser("withdraw")
    withdraw.add_argument("--job-id", required=True)
    withdraw.add_argument("--reason-path", required=True)
    withdraw.add_argument("--reason-sha256", required=True)
    plan = commands.add_parser("plan")
    plan.add_argument("--inventory", required=True, type=Path)
    commands.add_parser("snapshot")
    args = parser.parse_args()
    broker = ResourceBroker(args.database)
    try:
        if args.action == "submit":
            result = broker.submit(read_object(args.job))
        elif args.action == "bind-gate":
            result = broker.bind_dispatch_gate(read_object(args.job))
        elif args.action == "acquire":
            result = broker.acquire(
                read_object(args.inventory),
                ttl_seconds=args.ttl_seconds,
                job_id=args.job_id,
            )
        elif args.action == "heartbeat":
            result = broker.heartbeat(args.lease_id, ttl_seconds=args.ttl_seconds)
        elif args.action == "complete":
            result = broker.complete(
                args.lease_id,
                args.outcome,
                {"path": args.result_path, "sha256": args.result_sha256},
            )
        elif args.action == "withdraw":
            result = broker.withdraw(
                args.job_id,
                {"path": args.reason_path, "sha256": args.reason_sha256},
            )
        elif args.action == "plan":
            result = broker.plan(read_object(args.inventory))
        else:
            result = broker.snapshot()
    finally:
        broker.close()
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
