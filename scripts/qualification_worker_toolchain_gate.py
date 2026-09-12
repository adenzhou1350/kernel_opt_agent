#!/usr/bin/env python3
"""Reject stale or missing worker tools before reserving GPU resources."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from qualification_environment_worker import validate as validate_attestation
from schema_utils import validate_instance


SCHEMA_VERSION = "qualification-worker-toolchain-gate-v1"
CLAIM_BOUNDARY = (
    "FRESH_WORKER_TOOL_AVAILABILITY_ONLY_NOT_LEASE_EXECUTION_GPU_"
    "CORRECTNESS_OR_PERFORMANCE_AUTHORIZATION"
)
TOOL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9+_.-]*$")


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def read_object(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def parse_time(value: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError("attestation observed_at must be a timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("attestation observed_at is invalid") from error
    if parsed.tzinfo is None:
        raise ValueError("attestation observed_at must include a timezone")
    return parsed.astimezone(UTC)


def timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def identity(path: Path) -> dict:
    resolved = path.resolve(strict=True)
    if not resolved.is_file():
        raise ValueError(f"identity is not a regular file: {resolved}")
    return {"path": resolved.as_posix(), "sha256": sha256_file(resolved)}


def evaluate(
    *,
    attestation_path: Path,
    consumer_path: Path,
    worker_id: str,
    host_id: str,
    required_tools: list[str],
    max_age_seconds: int,
    observed_at: datetime | None = None,
) -> dict:
    if max_age_seconds < 1:
        raise ValueError("max_age_seconds must be positive")
    if not required_tools:
        raise ValueError("at least one required tool is required")
    if len(set(required_tools)) != len(required_tools):
        raise ValueError("required tool names must be unique")
    if any(TOOL_NAME.fullmatch(name) is None for name in required_tools):
        raise ValueError("required tool name is invalid")

    attestation_path = attestation_path.resolve(strict=True)
    consumer_path = consumer_path.resolve(strict=True)
    validate_attestation(attestation_path)
    attestation = read_object(attestation_path)
    if attestation["worker_id"] != worker_id:
        raise ValueError("worker_id differs from attestation")
    if attestation["host_id"] != host_id:
        raise ValueError("host_id differs from attestation")

    generated = (observed_at or datetime.now(UTC)).astimezone(UTC)
    attested = parse_time(attestation["observed_at"])
    raw_age = (generated - attested).total_seconds()
    blockers: list[str] = []
    if raw_age < 0:
        blockers.append("ATTESTATION_FROM_FUTURE")
    elif raw_age > max_age_seconds:
        blockers.append("ATTESTATION_STALE")

    toolchain = attestation["runtime"]["toolchain"]
    tools = []
    for name in required_tools:
        observed = toolchain.get(name)
        if observed is None:
            blockers.append(f"REQUIRED_TOOL_MISSING:{name}")
            tools.append({"name": name, "state": "MISSING", "identity": None})
        else:
            tools.append({"name": name, "state": "PRESENT", "identity": observed})

    result = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": timestamp(generated),
        "status": "BLOCKED_PRELEASE" if blockers else "READY_FOR_PRELEASE_BINDING",
        "claim_boundary": CLAIM_BOUNDARY,
        "worker_id": worker_id,
        "host_id": host_id,
        "attestation": identity(attestation_path),
        "consumer": identity(consumer_path),
        "attestation_observed_at": timestamp(attested),
        "max_age_seconds": max_age_seconds,
        "attestation_age_seconds": max(0.0, raw_age),
        "tools": tools,
        "blockers": blockers,
        "lease_authorized": False,
        "execution_authorized": False,
        "gpu_authorized": False,
    }
    errors = validate_instance(
        result,
        read_object(
            repository_root()
            / "schemas/qualification_worker_toolchain_gate.schema.json"
        ),
    )
    if errors:
        raise ValueError("invalid worker toolchain gate: " + "; ".join(errors))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attestation", required=True, type=Path)
    parser.add_argument("--consumer", required=True, type=Path)
    parser.add_argument("--worker-id", required=True)
    parser.add_argument("--host-id", required=True)
    parser.add_argument("--require-tool", action="append", required=True)
    parser.add_argument("--max-age-seconds", type=int, default=300)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = evaluate(
        attestation_path=args.attestation,
        consumer_path=args.consumer,
        worker_id=args.worker_id,
        host_id=args.host_id,
        required_tools=args.require_tool,
        max_age_seconds=args.max_age_seconds,
    )
    atomic_json(args.output.resolve(), result)
    print(args.output.resolve().as_posix())
    return 0 if result["status"] == "READY_FOR_PRELEASE_BINDING" else 2


if __name__ == "__main__":
    raise SystemExit(main())
