#!/usr/bin/env python3
"""Separate newly selected PRs from prior-window repeat observations."""

from __future__ import annotations

import argparse
from pathlib import Path

from community_funnel_checkpoint import validate_checkpoint_fast
from community_knowledge import atomic_json, now, read_object, sha256_file
from schema_utils import validate_instance, validate_json_file


SCHEMA_VERSION = "community-task-novelty-guard-v1"
CLAIM_BOUNDARY = (
    "PREDECESSOR_KEY_NOVELTY_ONLY_NOT_TASK_FEASIBILITY_OR_PERFORMANCE_EVIDENCE"
)


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def identity(path: Path) -> dict:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {"path": path.as_posix(), "sha256": sha256_file(path)}


def identity_path(value: dict) -> Path:
    return Path(value["path"]).resolve()


def stable(value: dict) -> dict:
    return {key: item for key, item in value.items() if key != "generated_at"}


def candidate_key(item: dict) -> str:
    return f"{item['repository']}#{int(item['pr_number'])}"


def derive_task_novelty(checkpoint: dict, queue: dict) -> dict:
    prior_keys = set(checkpoint["state"]["unique_candidate_keys"])
    selected = [item for item in queue["items"] if item["selection"] == "SELECTED"]
    if len(selected) != int(queue["inventory"]["selected_count"]):
        raise ValueError("queue selected inventory differs from selected items")

    observed: set[str] = set()
    new_keys: list[str] = []
    repeated_keys: list[str] = []
    for item in selected:
        key = candidate_key(item)
        if key in observed:
            raise ValueError(f"duplicate selected candidate: {key}")
        observed.add(key)
        if key in prior_keys:
            repeated_keys.append(key)
        else:
            new_keys.append(key)

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now(),
        "status": "PASS",
        "claim_boundary": CLAIM_BOUNDARY,
        "policy": {
            "novelty_identity": "REPOSITORY_AND_PR_NUMBER",
            "prior_universe": "PREDECESSOR_CHECKPOINT_UNIQUE_CANDIDATE_KEYS",
            "new_selected_disposition": "ELIGIBLE_FOR_POSTSELECTION",
            "repeated_selected_disposition": "RECORD_ONLY_NOT_A_NEW_TASK",
            "materialization_gate": "ONLY_NEW_SELECTED_KEYS",
        },
        "inventory": {
            "selected_observation_count": len(selected),
            "new_selected_count": len(new_keys),
            "repeated_selected_count": len(repeated_keys),
        },
        "new_selected_keys": new_keys,
        "repeated_selected_keys": repeated_keys,
    }


def build_guard(
    checkpoint_path: Path,
    queue_path: Path,
    corpus: Path,
    source_root: Path,
    root: Path | None = None,
) -> dict:
    root = (root or repository_root()).resolve()
    checkpoint_path = checkpoint_path.resolve()
    queue_path = queue_path.resolve()
    corpus = corpus.resolve()
    source_root = source_root.resolve()
    validate_checkpoint_fast(checkpoint_path, corpus, root, source_root)
    # The queue was created by the frozen cohort implementation.  Its graph
    # anchor and schemas therefore resolve against that source root, while the
    # novelty guard itself is validated against the current runner root.
    from community_evaluation import validate_heldout_queue

    validate_heldout_queue(queue_path, corpus, source_root)
    report = derive_task_novelty(
        read_object(checkpoint_path), read_object(queue_path)
    )
    report["input_identity"] = {
        "predecessor_checkpoint": identity(checkpoint_path),
        "queue": identity(queue_path),
    }
    errors = validate_instance(
        report, read_object(root / "schemas/community_task_novelty.schema.json")
    )
    if errors:
        raise ValueError("invalid task novelty guard: " + "; ".join(errors))
    return report


def validate_guard(
    guard_path: Path,
    corpus: Path,
    source_root: Path,
    root: Path | None = None,
) -> dict:
    root = (root or repository_root()).resolve()
    guard_path = guard_path.resolve()
    errors = validate_json_file(
        guard_path, root / "schemas/community_task_novelty.schema.json"
    )
    if errors:
        raise ValueError("invalid task novelty guard: " + "; ".join(errors))
    guard = read_object(guard_path)
    inputs = guard["input_identity"]
    for label, value in inputs.items():
        path = identity_path(value)
        if not path.is_file() or sha256_file(path) != value["sha256"]:
            raise ValueError(f"task novelty {label} changed: {path}")
    expected = build_guard(
        identity_path(inputs["predecessor_checkpoint"]),
        identity_path(inputs["queue"]),
        corpus,
        source_root,
        root,
    )
    if stable(guard) != stable(expected):
        raise ValueError("task novelty guard is stale or was edited")
    return {"status": "PASS", **guard["inventory"]}


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    operations = value.add_subparsers(dest="operation", required=True)
    for name in ("build", "validate"):
        command = operations.add_parser(name)
        if name == "build":
            command.add_argument("--checkpoint", type=Path, required=True)
            command.add_argument("--queue", type=Path, required=True)
        else:
            command.add_argument("--guard", type=Path, required=True)
        command.add_argument("--corpus", type=Path, required=True)
        command.add_argument("--source-root", type=Path, required=True)
        if name == "build":
            command.add_argument("--output", type=Path, required=True)
    return value


def main() -> int:
    args = parser().parse_args()
    try:
        if args.operation == "build":
            if args.output.resolve().exists():
                raise FileExistsError(f"refusing to overwrite {args.output.resolve()}")
            report = build_guard(
                args.checkpoint, args.queue, args.corpus, args.source_root
            )
            atomic_json(args.output.resolve(), report)
            result = {"guard": str(args.output.resolve()), **report["inventory"], "status": "PASS"}
        else:
            result = validate_guard(
                args.guard, args.corpus, args.source_root
            )
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}")
        return 1
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
