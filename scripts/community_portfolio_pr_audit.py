#!/usr/bin/env python3
"""Compare selected work-cycle PR milestones with an explicit stage snapshot."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from artifact_io import atomic_json, now, read_object, sha256_file
from community_portfolio import resolve_identity
from community_work_cycle import parse_time, validate_ledger
from schema_utils import validate_instance


SCHEMA_VERSION = "community-portfolio-pr-stage-audit-v1"
HISTORY_VERSION = "github-pr-stage-history-v1"
STAGE_RANK = {"NONE": 0, "DRAFT": 1, "READY": 2, "MERGED": 3}
PULL_REQUEST_URL = re.compile(r"^https://github\.com/[^/]+/[^/]+/pull/[0-9]+$")


def root() -> Path:
    return Path(__file__).resolve().parents[1]


def parse_binding(value: str) -> tuple[str, str]:
    cycle_id, separator, url = value.partition("=")
    if not separator or not cycle_id or PULL_REQUEST_URL.fullmatch(url) is None:
        raise argparse.ArgumentTypeError(
            "binding must be CYCLE_ID=https://github.com/OWNER/REPO/pull/N"
        )
    return cycle_id, url


def ledger_stage(ledger: dict) -> str:
    kinds = {item["kind"] for item in ledger["milestones"]}
    if ledger["outcome"]["merged"] or "PR_MERGED" in kinds:
        return "MERGED"
    if "PR_READY_FOR_REVIEW" in kinds:
        return "READY"
    if "PR_DRAFT_OPENED" in kinds:
        return "DRAFT"
    return "NONE"


def compare_stage(cycle_id: str, url: str, ledger: dict, observed: dict) -> dict:
    current = observed["current_stage"]
    recorded = ledger_stage(ledger)
    if current == "CLOSED":
        status = "EXTERNAL_CLOSED_UNREPRESENTED"
        suggested_stage = None
    elif STAGE_RANK[current] > STAGE_RANK[recorded]:
        status = "LEDGER_LAGS_EXTERNAL"
        suggested_stage = current
    elif STAGE_RANK[current] < STAGE_RANK[recorded]:
        status = "EXTERNAL_SNAPSHOT_LAGS_LEDGER"
        suggested_stage = None
    else:
        status = "ALIGNED"
        suggested_stage = None
    return {
        "cycle_id": cycle_id,
        "pull_request_url": url,
        "ledger_stage": recorded,
        "observed_stage": current,
        "observed_stage_since": observed["current_stage_since"],
        "status": status,
        "suggested_stage": suggested_stage,
    }


def validate_history(history: dict) -> None:
    if set(history) != {"schema_version", "entries"}:
        raise ValueError("PR stage history has unexpected fields")
    if history["schema_version"] != HISTORY_VERSION:
        raise ValueError("unsupported PR stage history")
    if not isinstance(history["entries"], dict):
        raise ValueError("PR stage history entries must be an object")
    for url, entry in history["entries"].items():
        if PULL_REQUEST_URL.fullmatch(url) is None:
            raise ValueError("invalid PR stage history URL")
        if entry.get("current_stage") not in {*STAGE_RANK, "CLOSED"} - {"NONE"}:
            raise ValueError(f"invalid PR stage for {url}")
        parse_time(entry.get("current_stage_since"), "current_stage_since")
        if entry.get("last_observation_stale") is not False:
            raise ValueError(f"PR stage history is stale for {url}")


def audit(
    manifest_path: Path,
    history_path: Path,
    raw_bindings: list[tuple[str, str]],
) -> dict:
    manifest_path = manifest_path.resolve(strict=True)
    history_path = history_path.resolve(strict=True)
    manifest = read_object(manifest_path)
    errors = validate_instance(
        manifest,
        read_object(root() / "schemas/community_portfolio_manifest.schema.json"),
    )
    if errors:
        raise ValueError("invalid portfolio manifest: " + "; ".join(errors))
    history = read_object(history_path)
    validate_history(history)

    selected: dict[str, dict] = {}
    for lane in manifest["lanes"]:
        for index, identity in enumerate(lane["work_cycle_ledgers"]):
            path = resolve_identity(
                manifest_path.parent,
                identity,
                f"{lane['lane_id']} ledger {index}",
            )
            ledger = validate_ledger(path)
            cycle_id = ledger["cycle_id"]
            if cycle_id in selected:
                raise ValueError("duplicate selected cycle_id")
            selected[cycle_id] = ledger

    bindings: dict[str, str] = {}
    for cycle_id, url in raw_bindings:
        if cycle_id not in selected:
            raise ValueError(f"binding selects unknown cycle: {cycle_id}")
        if cycle_id in bindings or url in bindings.values():
            raise ValueError("duplicate PR stage binding")
        recorded_url = selected[cycle_id]["outcome"]["pull_request_url"]
        if recorded_url is not None and recorded_url != url:
            raise ValueError("binding conflicts with ledger pull_request_url")
        bindings[cycle_id] = url

    rows = []
    for cycle_id, ledger in selected.items():
        url = bindings.get(cycle_id) or ledger["outcome"]["pull_request_url"]
        if url is None:
            continue
        observed = history["entries"].get(url)
        if observed is None:
            rows.append(
                {
                    "cycle_id": cycle_id,
                    "pull_request_url": url,
                    "ledger_stage": ledger_stage(ledger),
                    "observed_stage": None,
                    "observed_stage_since": None,
                    "status": "HISTORY_MISSING",
                    "suggested_stage": None,
                }
            )
            continue
        rows.append(compare_stage(cycle_id, url, ledger, observed))

    actionable = sum(row["status"] == "LEDGER_LAGS_EXTERNAL" for row in rows)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now(),
        "claim_boundary": "READ_ONLY_EXPLICIT_PR_STAGE_RECONCILIATION_NOT_LEDGER_MUTATION",
        "manifest_identity": {
            "path": manifest_path.as_posix(),
            "sha256": sha256_file(manifest_path),
        },
        "stage_history_identity": {
            "path": history_path.as_posix(),
            "sha256": sha256_file(history_path),
        },
        "binding_count": len(bindings),
        "selected_pr_count": len(rows),
        "actionable_drift_count": actionable,
        "status": "DRIFT" if actionable else "PASS",
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--stage-history", type=Path, required=True)
    parser.add_argument("--bind", action="append", type=parse_binding, default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.manifest, args.stage_history, args.bind)
    errors = validate_instance(
        result,
        read_object(root() / "schemas/community_portfolio_pr_stage_audit.schema.json"),
    )
    if errors:
        raise ValueError("invalid PR stage audit: " + "; ".join(errors))
    atomic_json(args.output.resolve(), result)
    print(args.output.resolve().as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
