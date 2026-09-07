#!/usr/bin/env python3
"""Freeze newly observed pre-cutoff PR metadata for a future cohort review."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from community_funnel_checkpoint import validate_checkpoint_fast
from community_knowledge import atomic_json, now, read_object, sha256_file
from schema_utils import validate_instance, validate_json_file


SCHEMA_VERSION = "community-deferred-training-intake-v1"
CLAIM_BOUNDARY = (
    "METADATA_ONLY_NEXT_COHORT_REVIEW_QUEUE_NOT_CURRENT_COHORT_TRAINING_OR_"
    "PERFORMANCE_EVIDENCE"
)
REPOSITORIES = {
    "vllm-project/vllm",
    "sgl-project/sglang",
    "kvcache-ai/Mooncake",
}


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def identity(path: Path) -> dict:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {"path": path.as_posix(), "sha256": sha256_file(path)}


def identity_path(value: dict) -> Path:
    return Path(value["path"]).resolve()


def verify_identity(value: dict, label: str) -> Path:
    path = identity_path(value)
    if not path.is_file() or sha256_file(path) != value["sha256"]:
        raise ValueError(f"{label} changed: {path}")
    return path


def parse_time(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"invalid {label}: {value}") from error
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must include a timezone")
    return parsed


def candidate_key(repository: str, pr_number: int) -> str:
    return f"{repository}#{pr_number}"


def stable(value: dict) -> dict:
    return {key: item for key, item in value.items() if key != "generated_at"}


def validate_receipts(
    receipt_paths: list[Path], root: Path
) -> tuple[list[tuple[Path, dict]], str, str]:
    if len(receipt_paths) != len(REPOSITORIES):
        raise ValueError("exactly one receipt per registered repository is required")
    schema = root / "schemas/community_sync_receipt.schema.json"
    rows: list[tuple[Path, dict]] = []
    repositories: set[str] = set()
    windows: set[tuple[str, str]] = set()
    for original_path in receipt_paths:
        path = original_path.resolve()
        errors = validate_json_file(path, schema)
        if errors:
            raise ValueError(f"invalid discovery receipt {path}: " + "; ".join(errors))
        receipt = read_object(path)
        if receipt["schema_version"] != "community-sync-receipt-v2":
            raise ValueError("deferred intake requires receipt v2 earliest_public_at")
        repository = receipt["repository"]
        if repository not in REPOSITORIES:
            raise ValueError(f"unregistered receipt repository: {repository}")
        if repository in repositories:
            raise ValueError(f"duplicate receipt repository: {repository}")
        if receipt["coverage_truncated"]:
            raise ValueError(f"truncated discovery receipt cannot seed intake: {path}")
        repositories.add(repository)
        window = receipt["window"]
        windows.add((window["since"], window["until"]))
        if receipt["next_since"] != window["until"]:
            raise ValueError(f"receipt next_since differs from until: {path}")
        rows.append((path, receipt))
    if repositories != REPOSITORIES:
        raise ValueError("receipt repository coverage is incomplete")
    if len(windows) != 1:
        raise ValueError("receipts do not share one exact window")
    since, until = next(iter(windows))
    return sorted(rows, key=lambda row: row[1]["repository"]), since, until


def derive_deferred_intake(
    predecessor: dict,
    successor: dict,
    receipt_rows: list[tuple[Path, dict]],
    cutoff_at: str,
) -> dict:
    predecessor_keys = set(predecessor["state"]["unique_candidate_keys"])
    successor_keys = set(successor["state"]["unique_candidate_keys"])
    removed = sorted(predecessor_keys - successor_keys)
    if removed:
        raise ValueError("successor checkpoint removed candidate keys: " + ", ".join(removed))

    predecessor_audits = predecessor["input_identity"]["audit_prefix"]
    successor_audits = successor["input_identity"]["audit_prefix"]
    if (
        len(successor_audits) != len(predecessor_audits) + 1
        or successor_audits[: len(predecessor_audits)] != predecessor_audits
    ):
        raise ValueError("successor checkpoint is not an exact one-window extension")
    if predecessor["input_identity"]["corpus_index"] != successor["input_identity"][
        "corpus_index"
    ]:
        raise ValueError("checkpoint corpus identities differ")
    if predecessor["input_identity"]["source_root"] != successor["input_identity"][
        "source_root"
    ]:
        raise ValueError("checkpoint source roots differ")

    cutoff = parse_time(cutoff_at, "cutoff_at")
    windows = {
        (receipt["window"]["since"], receipt["window"]["until"])
        for _, receipt in receipt_rows
    }
    if len(windows) != 1:
        raise ValueError("receipts do not share one exact window")
    since, until = next(iter(windows))
    receipt_candidates: dict[str, tuple[str, dict]] = {}
    for _, receipt in receipt_rows:
        repository = receipt["repository"]
        for candidate in receipt["candidates"]:
            key = candidate_key(repository, int(candidate["pr_number"]))
            if key in receipt_candidates:
                raise ValueError(f"duplicate receipt candidate: {key}")
            receipt_candidates[key] = (repository, candidate)

    new_keys = successor_keys - predecessor_keys
    missing = sorted(new_keys - set(receipt_candidates))
    unexpected = sorted(set(receipt_candidates) - successor_keys)
    if missing:
        raise ValueError("new checkpoint candidates missing from receipts: " + ", ".join(missing))
    if unexpected:
        raise ValueError("receipt candidates missing from successor checkpoint: " + ", ".join(unexpected))

    items = []
    withheld_post_cutoff_keys = []
    for key in sorted(new_keys):
        repository, candidate = receipt_candidates[key]
        public_at = parse_time(candidate["earliest_public_at"], f"{key}.earliest_public_at")
        if public_at >= cutoff:
            withheld_post_cutoff_keys.append(key)
            continue
        items.append(
            {
                "repository": repository,
                "pr_number": int(candidate["pr_number"]),
                "title": candidate["title"],
                "created_at": candidate["created_at"],
                "earliest_public_at": candidate["earliest_public_at"],
                "updated_at": candidate["updated_at"],
                "classifications": sorted(candidate["classifications"]),
                "selection_score": int(candidate["selection_score"]),
                "disposition": "NEXT_COHORT_REVIEW",
                "hypothesis_status": "UNREAD",
            }
        )

    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now(),
        "status": "PASS",
        "claim_boundary": CLAIM_BOUNDARY,
        "source_window": {
            "since": since,
            "until": until,
            "current_cohort_cutoff_at": cutoff_at,
        },
        "policy": {
            "current_cohort_route": "RECORD_ONLY_DO_NOT_ROUTE",
            "diff_review": "FORBIDDEN_UNTIL_NEXT_COHORT_RULES_AND_CUTOFF_ARE_FROZEN",
            "hypothesis_strength": "UNREAD_METADATA_ONLY",
            "promotion_requirements": [
                "capture immutable PR and review snapshots",
                "classify lifecycle and review outcomes",
                "extract applicability and counterexample boundaries",
                "validate event schema and relation graph",
                "route only in a future preregistered cohort",
            ],
        },
        "inventory": {
            "previous_unique_candidates": len(predecessor_keys),
            "current_unique_candidates": len(successor_keys),
            "new_unique_candidates": len(new_keys),
            "deferred_pre_cutoff_count": len(items),
            "withheld_post_cutoff_count": len(withheld_post_cutoff_keys),
            "receipt_candidate_count": len(receipt_candidates),
            "reobserved_candidate_count": len(set(receipt_candidates) & predecessor_keys),
        },
        "items": items,
        "withheld_post_cutoff_keys": sorted(withheld_post_cutoff_keys),
    }
    return report


def build_deferred_intake(
    predecessor_path: Path,
    successor_path: Path,
    receipt_paths: list[Path],
    cutoff_at: str,
    corpus: Path,
    source_root: Path,
    root: Path | None = None,
) -> dict:
    root = (root or repository_root()).resolve()
    predecessor_path = predecessor_path.resolve()
    successor_path = successor_path.resolve()
    corpus = corpus.resolve()
    source_root = source_root.resolve()
    validate_checkpoint_fast(predecessor_path, corpus, root, source_root)
    validate_checkpoint_fast(successor_path, corpus, root, source_root)
    rows, _, _ = validate_receipts(receipt_paths, root)

    successor = read_object(successor_path)
    suffix_audit_identity = successor["input_identity"]["audit_prefix"][-1]
    audit_path = verify_identity(suffix_audit_identity, "successor suffix audit")
    audit = read_object(audit_path)
    queue_path = verify_identity(audit["input_identity"]["queue"], "suffix queue")
    queue = read_object(queue_path)
    supplied = sorted(
        (identity(path) for path, _ in rows), key=lambda value: value["path"]
    )
    bound = sorted(queue["input_identity"]["receipts"], key=lambda value: value["path"])
    if supplied != bound:
        raise ValueError("receipts differ from successor suffix queue")

    report = derive_deferred_intake(
        read_object(predecessor_path), successor, rows, cutoff_at
    )
    report["input_identity"] = {
        "predecessor_checkpoint": identity(predecessor_path),
        "successor_checkpoint": identity(successor_path),
        "receipts": supplied,
    }
    errors = validate_instance(
        report, read_object(root / "schemas/community_deferred_intake.schema.json")
    )
    if errors:
        raise ValueError("invalid deferred intake: " + "; ".join(errors))
    return report


def validate_deferred_intake(
    intake_path: Path,
    corpus: Path,
    source_root: Path,
    root: Path | None = None,
) -> dict:
    root = (root or repository_root()).resolve()
    intake_path = intake_path.resolve()
    errors = validate_json_file(
        intake_path, root / "schemas/community_deferred_intake.schema.json"
    )
    if errors:
        raise ValueError("invalid deferred intake: " + "; ".join(errors))
    observed = read_object(intake_path)
    inputs = observed["input_identity"]
    predecessor = verify_identity(inputs["predecessor_checkpoint"], "predecessor checkpoint")
    successor = verify_identity(inputs["successor_checkpoint"], "successor checkpoint")
    receipts = [verify_identity(value, "discovery receipt") for value in inputs["receipts"]]
    expected = build_deferred_intake(
        predecessor,
        successor,
        receipts,
        observed["source_window"]["current_cohort_cutoff_at"],
        corpus,
        source_root,
        root,
    )
    if stable(observed) != stable(expected):
        raise ValueError("deferred intake is stale or was edited")
    return {
        "status": "PASS",
        "new_unique_candidates": observed["inventory"]["new_unique_candidates"],
        "deferred_pre_cutoff_count": observed["inventory"]["deferred_pre_cutoff_count"],
        "withheld_post_cutoff_count": observed["inventory"]["withheld_post_cutoff_count"],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    build.add_argument("--predecessor-checkpoint", type=Path, required=True)
    build.add_argument("--successor-checkpoint", type=Path, required=True)
    build.add_argument("--receipt", type=Path, action="append", required=True)
    build.add_argument("--cutoff-at", required=True)
    build.add_argument("--corpus", type=Path, required=True)
    build.add_argument("--source-root", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("--intake", type=Path, required=True)
    validate.add_argument("--corpus", type=Path, required=True)
    validate.add_argument("--source-root", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "build":
        output = args.output.resolve()
        if output.exists():
            raise FileExistsError(f"refusing to overwrite deferred intake: {output}")
        report = build_deferred_intake(
            args.predecessor_checkpoint,
            args.successor_checkpoint,
            args.receipt,
            args.cutoff_at,
            args.corpus,
            args.source_root,
        )
        atomic_json(output, report)
        print(output)
        return 0
    result = validate_deferred_intake(
        args.intake, args.corpus, args.source_root
    )
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
