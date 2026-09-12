#!/usr/bin/env python3
"""Register validated prospective work-cycle ledgers in a portfolio manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from copy import deepcopy
from pathlib import Path

from artifact_io import read_object, sha256_file
from community_lane_topology import LANE_IDS
from community_portfolio import build_report
from community_work_cycle import parse_time, validate_ledger
from schema_utils import validate_instance


SCHEMA_VERSION = "community-portfolio-manifest-v1"
CLAIM_BOUNDARY = "EXPLICIT_LEDGER_SELECTION_NOT_CAUSAL_COMPARISON"


def root() -> Path:
    return Path(__file__).resolve().parents[1]


def identity(path: Path) -> dict[str, str]:
    resolved = path.resolve(strict=True)
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    return {"path": resolved.as_posix(), "sha256": sha256_file(resolved)}


def parse_registration(value: str) -> tuple[str, Path]:
    lane_id, separator, raw_path = value.partition("=")
    if not separator or not raw_path:
        raise argparse.ArgumentTypeError("registration must be LANE_ID=/path/to/ledger")
    if lane_id not in LANE_IDS:
        raise argparse.ArgumentTypeError(f"unknown lane id: {lane_id}")
    return lane_id, Path(raw_path)


def existing_accounting_start(manifest_path: Path, manifest: dict) -> object:
    starts = []
    for lane in manifest["lanes"]:
        for item in lane["work_cycle_ledgers"]:
            raw = Path(item["path"])
            path = raw if raw.is_absolute() else manifest_path.parent / raw
            ledger = validate_ledger(path)
            if ledger["observation_mode"] == "PROSPECTIVE_EXACT":
                starts.append(parse_time(ledger["started_at"], "started_at"))
    if not starts:
        raise ValueError("portfolio has no prospective accounting boundary")
    return min(starts)


def build(
    manifest_path: Path, registrations: list[tuple[str, Path]]
) -> tuple[dict, list[dict]]:
    manifest_path = manifest_path.resolve(strict=True)
    build_report(manifest_path)
    manifest = read_object(manifest_path)
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported portfolio manifest")
    if manifest.get("claim_boundary") != CLAIM_BOUNDARY:
        raise ValueError("unexpected portfolio claim boundary")
    if not registrations:
        raise ValueError("at least one --register is required")

    boundary = existing_accounting_start(manifest_path, manifest)
    output = deepcopy(manifest)
    lane_by_id = {lane["lane_id"]: lane for lane in output["lanes"]}
    known_hashes = {
        item["sha256"]
        for lane in output["lanes"]
        for item in lane["work_cycle_ledgers"]
    }
    known_cycles: set[tuple[str, str]] = set()
    for lane in output["lanes"]:
        for item in lane["work_cycle_ledgers"]:
            raw = Path(item["path"])
            path = raw if raw.is_absolute() else manifest_path.parent / raw
            ledger = validate_ledger(path)
            known_cycles.add((ledger["cycle_id"], ledger["task_id"]))

    additions = []
    for lane_id, raw_path in registrations:
        path = raw_path.resolve(strict=True)
        ledger = validate_ledger(path)
        if ledger["observation_mode"] != "PROSPECTIVE_EXACT":
            raise ValueError("registered ledger must use PROSPECTIVE_EXACT")
        if parse_time(ledger["started_at"], "started_at") < boundary:
            raise ValueError("registered ledger predates portfolio accounting boundary")
        item = identity(path)
        if item["sha256"] in known_hashes:
            raise ValueError("registered ledger is already selected")
        cycle_key = (ledger["cycle_id"], ledger["task_id"])
        if cycle_key in known_cycles:
            raise ValueError("registered cycle/task is already selected")
        lane_by_id[lane_id]["work_cycle_ledgers"].append(item)
        known_hashes.add(item["sha256"])
        known_cycles.add(cycle_key)
        additions.append(
            {
                "lane_id": lane_id,
                "cycle_id": ledger["cycle_id"],
                "task_id": ledger["task_id"],
                "ledger_identity": item,
            }
        )

    errors = validate_instance(
        output, read_object(root() / "schemas/community_portfolio_manifest.schema.json")
    )
    if errors:
        raise ValueError("invalid superseding portfolio manifest: " + "; ".join(errors))
    return output, additions


def write_once(path: Path, value: dict) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError as error:
        raise FileExistsError(
            f"refusing to replace existing manifest: {path}"
        ) from error
    with os.fdopen(descriptor, "wb") as output:
        output.write(payload)
        output.flush()
        os.fsync(output.fileno())
    return hashlib.sha256(payload).hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument(
        "--register",
        type=parse_registration,
        action="append",
        default=[],
        metavar="LANE_ID=LEDGER",
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_path = args.output.resolve()
    manifest, additions = build(args.manifest, args.register)
    digest = write_once(output_path, manifest)
    build_report(output_path)
    print(
        json.dumps(
            {
                "status": "PASS",
                "path": output_path.as_posix(),
                "sha256": digest,
                "registered_count": len(additions),
                "registered": additions,
                "claim_boundary": CLAIM_BOUNDARY,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
