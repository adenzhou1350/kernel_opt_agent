#!/usr/bin/env python3
"""Assemble one hash-bound community window from frozen discovery receipts."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from community_knowledge import atomic_json, now, read_object, sha256_file


REPOSITORIES = {
    "vllm-project/vllm": "vllm",
    "sgl-project/sglang": "sglang",
    "kvcache-ai/Mooncake": "mooncake",
}


def identity(path: Path) -> dict:
    path = path.resolve()
    return {"path": path.as_posix(), "sha256": sha256_file(path)}


def run(argv: list[str], timeout: float) -> dict:
    started = datetime.now().astimezone().isoformat()
    completed = subprocess.run(
        argv,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    result = {
        "argv": argv,
        "started_at": started,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }
    if completed.returncode:
        raise RuntimeError(json.dumps(result, sort_keys=True))
    return result


def validate_receipt_window(receipts: list[Path]) -> tuple[str, str]:
    if len(receipts) != len(REPOSITORIES):
        raise ValueError("exactly one receipt per registered repository is required")
    observed_repositories: set[str] = set()
    windows: set[tuple[str, str]] = set()
    for path in receipts:
        value = read_object(path.resolve())
        repository = value.get("repository")
        if repository not in REPOSITORIES:
            raise ValueError(f"unregistered receipt repository: {repository}")
        if repository in observed_repositories:
            raise ValueError(f"duplicate receipt repository: {repository}")
        observed_repositories.add(repository)
        window = value.get("window", {})
        since = window.get("since")
        until = window.get("until")
        if value.get("next_since") != until:
            raise ValueError(f"receipt next_since differs from until: {path}")
        windows.add((since, until))
    if observed_repositories != set(REPOSITORIES):
        raise ValueError("receipt repository coverage is incomplete")
    if len(windows) != 1:
        raise ValueError("receipts do not share one exact window")
    return next(iter(windows))


def output_paths(output_dir: Path, artifact_prefix: str, funnel_stamp: str) -> dict:
    return {
        "queue": output_dir / f"heldout-queue-{artifact_prefix}-v1.json",
        "screen": output_dir / f"preselection-screen-{artifact_prefix}-v1.json",
        "audit": output_dir / f"preselection-chain-audit-{artifact_prefix}-v1.json",
        "funnel": output_dir
        / f"discovery-funnel-cumulative-through-{funnel_stamp}-v1.json",
        "validation": output_dir / f"window-validation-{artifact_prefix}-v1.json",
        "manifest": output_dir / f"window-assembly-{artifact_prefix}-v1.json",
        "failure": output_dir / f"window-assembly-failure-{artifact_prefix}-v1.json",
    }


def assemble(args: argparse.Namespace) -> dict:
    source_root = args.source_root.resolve()
    corpus = args.corpus.resolve()
    output_dir = args.output_dir.resolve()
    receipts = [path.resolve() for path in args.receipt]
    paths = output_paths(output_dir, args.artifact_prefix, args.funnel_stamp)
    collisions = [str(path) for path in paths.values() if path.exists()]
    if collisions:
        raise FileExistsError(
            "refusing to overwrite artifacts: " + ", ".join(collisions)
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    since, until = validate_receipt_window(receipts)

    git_head = run(
        ["git", "-C", str(source_root), "rev-parse", "HEAD"],
        args.command_timeout,
    )["stdout"].strip()
    if git_head != args.expected_source_commit:
        raise ValueError(f"source commit differs: expected "
                         f"{args.expected_source_commit}, got {git_head}")
    frozen_paths = [
        "scripts/community_knowledge.py",
        "scripts/community_evaluation.py",
        "schemas/community_sync_receipt.schema.json",
        "schemas/community_heldout_preregistration.schema.json",
        "schemas/community_temporal_suite.schema.json",
        "knowledge/community",
    ]
    run(
        [
            "git",
            "-C",
            str(source_root),
            "diff",
            "--exit-code",
            args.expected_source_commit,
            "--",
            *frozen_paths,
        ],
        args.command_timeout,
    )

    checkpoint = read_object(args.checkpoint.resolve())
    prefix_count = len(checkpoint["input_identity"]["audit_prefix"])
    expected_count = prefix_count + 1
    commands: list[dict] = []
    python = sys.executable
    frozen_evaluation = source_root / "scripts/community_evaluation.py"

    queue_argv = [python, str(frozen_evaluation), "build-heldout-queue"]
    for receipt in receipts:
        queue_argv.extend(["--receipt", str(receipt)])
    queue_argv.extend(
        [
            "--graph",
            str(args.graph.resolve()),
            "--methods",
            str(args.methods.resolve()),
            "--routing-snapshot",
            str(args.routing_snapshot.resolve()),
            "--corpus",
            str(corpus),
            "--cutoff-at",
            args.cutoff_at,
            "--max-items",
            str(args.max_items),
            "--random-seed",
            str(args.random_seed),
            "--output",
            str(paths["queue"]),
        ]
    )
    commands.append(run(queue_argv, args.command_timeout))
    commands.append(
        run(
            [
                python,
                str(frozen_evaluation),
                "build-feasibility-screen",
                "--queue",
                str(paths["queue"]),
                "--policy",
                str(args.policy.resolve()),
                "--profile",
                str(args.profile.resolve()),
                "--corpus",
                str(corpus),
                "--output",
                str(paths["screen"]),
            ],
            args.command_timeout,
        )
    )
    commands.append(
        run(
            [
                python,
                str(frozen_evaluation),
                "audit-preselection-chain",
                "--anchor",
                str(args.anchor.resolve()),
                "--queue",
                str(paths["queue"]),
                "--screen",
                str(paths["screen"]),
                "--corpus",
                str(corpus),
                "--output",
                str(paths["audit"]),
            ],
            args.command_timeout,
        )
    )
    checkpoint_script = (
        Path(__file__).resolve().parent / "community_funnel_checkpoint.py"
    )
    commands.append(
        run(
            [
                python,
                str(checkpoint_script),
                "extend",
                "--checkpoint",
                str(args.checkpoint.resolve()),
                "--audit",
                str(paths["audit"]),
                "--corpus",
                str(corpus),
                "--source-root",
                str(source_root),
                "--output",
                str(paths["funnel"]),
            ],
            args.command_timeout,
        )
    )
    commands.append(
        run(
            [
                python,
                str(checkpoint_script),
                "validate-incremental",
                "--report",
                str(paths["funnel"]),
                "--checkpoint",
                str(args.checkpoint.resolve()),
                "--corpus",
                str(corpus),
                "--source-root",
                str(source_root),
            ],
            args.command_timeout,
        )
    )
    validation_script = (
        Path(__file__).resolve().parent / "community_window_validation.py"
    )
    commands.append(
        run(
            [
                python,
                str(validation_script),
                "--queue",
                str(paths["queue"]),
                "--screen",
                str(paths["screen"]),
                "--audit",
                str(paths["audit"]),
                "--funnel",
                str(paths["funnel"]),
                "--corpus",
                str(corpus),
                "--source-root",
                str(source_root),
                "--funnel-checkpoint",
                str(args.checkpoint.resolve()),
                "--output",
                str(paths["validation"]),
            ],
            args.command_timeout,
        )
    )
    funnel = read_object(paths["funnel"])
    observed_count = funnel["inventory"]["window_count"]
    if observed_count != expected_count:
        raise ValueError(f"successor window count differs: expected "
                         f"{expected_count}, got {observed_count}")
    queue = read_object(paths["queue"])
    manifest = {
        "schema_version": "community-window-assembly-v1",
        "generated_at": now(),
        "claim_boundary": "CPU_DISCOVERY_ASSEMBLY_NOT_GPU_OR_OPTIMIZATION_EVIDENCE",
        "window": {"since": since, "until": until},
        "configuration": {
            "cutoff_at": args.cutoff_at,
            "max_items": args.max_items,
            "random_seed": args.random_seed,
            "expected_source_commit": args.expected_source_commit,
            "command_timeout_seconds": args.command_timeout,
        },
        "input_identity": {
            "receipts": [identity(path) for path in sorted(receipts)],
            "checkpoint": identity(args.checkpoint),
            "anchor": identity(args.anchor),
            "graph": identity(args.graph),
            "methods": identity(args.methods),
            "routing_snapshot": identity(args.routing_snapshot),
            "policy": identity(args.policy),
            "profile": identity(args.profile),
        },
        "output_identity": {
            key: identity(paths[key])
            for key in ("queue", "screen", "audit", "funnel", "validation")
        },
        "inventory": {
            "prefix_window_count": prefix_count,
            "successor_window_count": observed_count,
            "selected_count": queue["inventory"]["selected_count"],
        },
        "command_count": len(commands),
        "status": "PASS",
    }
    atomic_json(paths["manifest"], manifest)
    return {
        "manifest": str(paths["manifest"]),
        **manifest["inventory"],
        "status": "PASS",
    }


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--receipt", type=Path, action="append", required=True)
    value.add_argument("--source-root", type=Path, required=True)
    value.add_argument("--expected-source-commit", required=True)
    value.add_argument("--corpus", type=Path, required=True)
    value.add_argument("--checkpoint", type=Path, required=True)
    value.add_argument("--anchor", type=Path, required=True)
    value.add_argument("--graph", type=Path, required=True)
    value.add_argument("--methods", type=Path, required=True)
    value.add_argument("--routing-snapshot", type=Path, required=True)
    value.add_argument("--policy", type=Path, required=True)
    value.add_argument("--profile", type=Path, required=True)
    value.add_argument("--cutoff-at", required=True)
    value.add_argument("--max-items", type=int, default=12)
    value.add_argument("--random-seed", type=int, required=True)
    value.add_argument("--artifact-prefix", required=True)
    value.add_argument("--funnel-stamp", required=True)
    value.add_argument("--output-dir", type=Path, required=True)
    value.add_argument("--command-timeout", type=float, default=120.0)
    return value


def main() -> int:
    args = parser().parse_args()
    paths = output_paths(
        args.output_dir.resolve(), args.artifact_prefix, args.funnel_stamp
    )
    try:
        result = assemble(args)
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        args.output_dir.resolve().mkdir(parents=True, exist_ok=True)
        if not paths["failure"].exists():
            atomic_json(
                paths["failure"],
                {
                    "schema_version": "community-window-assembly-failure-v1",
                    "generated_at": now(),
                    "claim_boundary": (
                        "FAIL_CLOSED_PARTIAL_ASSEMBLY_NOT_SELECTION_OR_"
                        "PERFORMANCE_EVIDENCE"
                    ),
                    "error": str(error),
                    "status": "FAIL_CLOSED",
                },
            )
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
