#!/usr/bin/env python3
"""Create one evidence-bound current-state attestation for an active work span."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from artifact_io import read_object, sha256_file
from community_work_cycle import parse_time, validate_ledger_object
from schema_utils import validate_instance


STATES = ("ACTIVE", "RESOLVED", "SUPERSEDED")
OWNERS = ("USER", "AGENT", "EXTERNAL", "MAINTAINER", "GPU", "NONE")


def root() -> Path:
    return Path(__file__).resolve().parents[1]


def timestamp(value: str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    return parse_time(value, "generated-at")


def identity(path: Path) -> dict[str, str]:
    resolved = path.resolve(strict=True)
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    return {"path": resolved.as_posix(), "sha256": sha256_file(resolved)}


def isoformat(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def build(args: argparse.Namespace) -> dict:
    ledger_path = args.ledger.resolve(strict=True)
    ledger = read_object(ledger_path)
    validate_ledger_object(ledger, ledger_path)
    matches = [
        span
        for span in ledger["spans"]
        if span["span_id"] == args.span_id and span["status"] == "ACTIVE"
    ]
    if len(matches) != 1:
        raise ValueError("span-id must select exactly one ACTIVE ledger span")
    span = matches[0]
    generated = timestamp(args.generated_at)
    if generated < parse_time(span["started_at"], "span.started_at"):
        raise ValueError("generated-at cannot predate the active ledger span")

    if args.state == "ACTIVE":
        if args.action_owner == "NONE":
            raise ValueError("ACTIVE attestation requires a non-NONE action owner")
        if args.valid_for_seconds is None or args.valid_for_seconds <= 0:
            raise ValueError("ACTIVE attestation requires positive --valid-for-seconds")
        valid_until = isoformat(generated + timedelta(seconds=args.valid_for_seconds))
    else:
        if args.action_owner != "NONE":
            raise ValueError("inactive attestation action owner must be NONE")
        if args.valid_for_seconds is not None:
            raise ValueError("inactive attestation cannot set --valid-for-seconds")
        valid_until = None

    if not args.evidence:
        raise ValueError("at least one --evidence file is required")
    record = {
        "schema_version": "community-action-attestation-v1",
        "claim_boundary": "CURRENT_ACTION_STATE_ONLY_NOT_LEDGER_MUTATION",
        "generated_at": isoformat(generated),
        "valid_until": valid_until,
        "ledger_identity": identity(ledger_path),
        "cycle_id": ledger["cycle_id"],
        "span_id": span["span_id"],
        "state": args.state,
        "action_owner": args.action_owner,
        "resource_id": span.get("resource_id"),
        "evidence": [identity(path) for path in args.evidence],
    }
    errors = validate_instance(
        record, read_object(root() / "schemas/community_action_attestation.schema.json")
    )
    if errors:
        raise ValueError("invalid action attestation: " + "; ".join(errors))
    return record


def write_once(path: Path, value: dict) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError as error:
        raise FileExistsError(
            f"refusing to replace existing action attestation: {path}"
        ) from error
    with os.fdopen(descriptor, "wb") as output:
        output.write(payload)
        output.flush()
        os.fsync(output.fileno())
    return hashlib.sha256(payload).hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--span-id", required=True)
    parser.add_argument("--state", choices=STATES, required=True)
    parser.add_argument("--action-owner", choices=OWNERS, default="NONE")
    parser.add_argument("--valid-for-seconds", type=int)
    parser.add_argument("--generated-at")
    parser.add_argument("--evidence", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output = args.output.resolve()
    record = build(args)
    digest = write_once(output, record)
    print(
        json.dumps(
            {
                "status": "PASS",
                "path": output.as_posix(),
                "sha256": digest,
                "cycle_id": record["cycle_id"],
                "span_id": record["span_id"],
                "state": record["state"],
                "claim_boundary": record["claim_boundary"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
