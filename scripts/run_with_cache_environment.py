#!/usr/bin/env python3
"""Exec a command with all known writable caches confined to one closure."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path, PurePosixPath

from qualification_environment_worker import cpu_only_cache_environment


CLAIM_BOUNDARY = (
    "CACHE_ENVIRONMENT_ISOLATION_ONLY_NOT_COMMAND_BUILD_GPU_WORKLOAD_OR_"
    "PERFORMANCE_AUTHORIZATION"
)


def isolated_environment(
    closure_root: str,
    *,
    storage_root: str = "/workspace",
    inherited: dict[str, str] | None = None,
) -> tuple[dict[str, str], dict[str, str]]:
    """Return the child environment and its exact cache-only projection."""
    cache_environment = cpu_only_cache_environment(closure_root, storage_root)
    child_environment = dict(os.environ if inherited is None else inherited)
    child_environment.update(cache_environment)
    return child_environment, cache_environment


def prepare_directories(closure_root: str, cache_environment: dict[str, str]) -> None:
    """Create only the closure and cache directories named by the projection."""
    closure = PurePosixPath(closure_root)
    for value in cache_environment.values():
        path = PurePosixPath(value)
        try:
            path.relative_to(closure)
        except ValueError as error:
            raise ValueError(f"cache path escapes closure: {value}") from error
        Path(value).mkdir(parents=True, exist_ok=True)


def contract(closure_root: str, cache_environment: dict[str, str]) -> dict:
    return {
        "status": "PASS",
        "closure_root": closure_root,
        "environment": cache_environment,
        "claim_boundary": CLAIM_BOUNDARY,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--closure-root", required=True)
    parser.add_argument("--storage-root", default="/workspace")
    parser.add_argument("--print-environment", action="store_true")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()

    command = list(args.command)
    if command[:1] == ["--"]:
        command = command[1:]
    if args.print_environment and command:
        parser.error("--print-environment does not accept a command")
    if not args.print_environment and not command:
        parser.error("a command is required after --")

    child_environment, cache_environment = isolated_environment(
        args.closure_root,
        storage_root=args.storage_root,
    )
    if args.print_environment:
        print(
            json.dumps(
                contract(args.closure_root, cache_environment),
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    prepare_directories(args.closure_root, cache_environment)
    os.execvpe(command[0], command, child_environment)
    return 127


if __name__ == "__main__":
    raise SystemExit(main())
