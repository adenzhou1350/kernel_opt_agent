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
from community_lane_topology import LANE_IDS, validate_topology
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


def resolve_selected_path(manifest_path: Path, item: dict) -> Path:
    raw = Path(item["path"])
    return (raw if raw.is_absolute() else manifest_path.parent / raw).resolve()


def validate_manifest_structure(manifest_path: Path, manifest: dict) -> None:
    errors = validate_instance(
        manifest,
        read_object(root() / "schemas/community_portfolio_manifest.schema.json"),
    )
    if errors:
        raise ValueError("invalid portfolio manifest: " + "; ".join(errors))
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported portfolio manifest")
    if manifest.get("claim_boundary") != CLAIM_BOUNDARY:
        raise ValueError("unexpected portfolio claim boundary")

    topology = manifest["lane_topology_identity"]
    topology_path = resolve_selected_path(manifest_path, topology)
    if not topology_path.is_file() or sha256_file(topology_path) != topology["sha256"]:
        raise ValueError("lane topology identity changed")
    validate_topology(topology_path)
    lane_ids = [lane["lane_id"] for lane in manifest["lanes"]]
    if len(lane_ids) != len(set(lane_ids)) or set(lane_ids) != LANE_IDS:
        raise ValueError("manifest must contain each autonomous lane exactly once")


def validate_selected_ledgers(manifest_path: Path, manifest: dict) -> None:
    seen_hashes: set[str] = set()
    seen_cycles: set[tuple[str, str]] = set()
    for lane in manifest["lanes"]:
        for item in lane["work_cycle_ledgers"]:
            path = resolve_selected_path(manifest_path, item)
            if not path.is_file() or sha256_file(path) != item["sha256"]:
                raise ValueError(f"selected ledger identity changed: {item['path']}")
            if item["sha256"] in seen_hashes:
                raise ValueError("one ledger identity cannot be counted more than once")
            ledger = validate_ledger(path)
            cycle_key = (ledger["cycle_id"], ledger["task_id"])
            if cycle_key in seen_cycles:
                raise ValueError("duplicate cycle/task selection")
            seen_hashes.add(item["sha256"])
            seen_cycles.add(cycle_key)


def build(
    manifest_path: Path,
    registrations: list[tuple[str, Path]],
    refreshes: list[tuple[str, Path]] | None = None,
) -> tuple[dict, list[dict]]:
    manifest_path = manifest_path.resolve(strict=True)
    manifest = read_object(manifest_path)
    refreshes = refreshes or []
    if registrations and refreshes:
        raise ValueError("--register and --refresh cannot be combined")
    if not registrations and not refreshes:
        raise ValueError("at least one --register or --refresh is required")

    validate_manifest_structure(manifest_path, manifest)
    if refreshes:
        output = deepcopy(manifest)
        lane_by_id = {lane["lane_id"]: lane for lane in output["lanes"]}
        changes = []
        seen_targets: set[tuple[str, str]] = set()
        for lane_id, raw_path in refreshes:
            path = raw_path.resolve(strict=True)
            target = (lane_id, path.as_posix())
            if target in seen_targets:
                raise ValueError("duplicate refresh target")
            seen_targets.add(target)
            matches = [
                (index, item)
                for index, item in enumerate(lane_by_id[lane_id]["work_cycle_ledgers"])
                if resolve_selected_path(manifest_path, item) == path
            ]
            if len(matches) != 1:
                raise ValueError(
                    "refreshed ledger must already be selected once in the declared lane"
                )
            index, previous = matches[0]
            ledger = validate_ledger(path)
            if ledger["observation_mode"] != "PROSPECTIVE_EXACT":
                raise ValueError("refreshed ledger must use PROSPECTIVE_EXACT")
            current = identity(path)
            if current["sha256"] == previous["sha256"]:
                raise ValueError("refreshed ledger identity did not change")
            lane_by_id[lane_id]["work_cycle_ledgers"][index] = current
            changes.append(
                {
                    "operation": "REFRESH",
                    "lane_id": lane_id,
                    "cycle_id": ledger["cycle_id"],
                    "task_id": ledger["task_id"],
                    "previous_ledger_identity": previous,
                    "ledger_identity": current,
                }
            )
        validate_selected_ledgers(manifest_path, output)
        return output, changes

    # Registration requires the old selection to remain fully reproducible.
    build_report(manifest_path)

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
                "operation": "REGISTER",
                "lane_id": lane_id,
                "cycle_id": ledger["cycle_id"],
                "task_id": ledger["task_id"],
                "ledger_identity": item,
            }
        )

    validate_selected_ledgers(manifest_path, output)
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
    parser.add_argument(
        "--refresh",
        type=parse_registration,
        action="append",
        default=[],
        metavar="LANE_ID=LEDGER",
        help=(
            "replace the hash for an already-selected ledger at the exact same "
            "lane and path after its evidence-closed state advances"
        ),
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_path = args.output.resolve()
    manifest, changes = build(args.manifest, args.register, args.refresh)
    digest = write_once(output_path, manifest)
    # Validate the exact bytes written, not just the in-memory proposal.
    build_report(output_path)
    registered = [item for item in changes if item["operation"] == "REGISTER"]
    refreshed = [item for item in changes if item["operation"] == "REFRESH"]
    print(
        json.dumps(
            {
                "status": "PASS",
                "path": output_path.as_posix(),
                "sha256": digest,
                "registered_count": len(registered),
                "registered": registered,
                "refreshed_count": len(refreshed),
                "refreshed": refreshed,
                "change_count": len(changes),
                "changes": changes,
                "claim_boundary": CLAIM_BOUNDARY,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
