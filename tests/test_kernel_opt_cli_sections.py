#!/usr/bin/env python3
"""Keep the public CLI command groups complete and non-overlapping."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "kernel_opt.py"


def command_group_keys() -> list[str]:
    tree = ast.parse(CLI.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.AnnAssign):
            continue
        if not isinstance(node.target, ast.Name):
            continue
        if node.target.id != "COMMAND_GROUPS" or not isinstance(node.value, ast.Dict):
            continue
        return [
            key.value
            for key in node.value.keys
            if isinstance(key, ast.Constant) and isinstance(key.value, str)
        ]
    raise AssertionError("COMMAND_GROUPS dictionary was not found")


def main() -> int:
    groups = command_group_keys()
    assert len(groups) == len(set(groups)), f"duplicate CLI command groups: {groups}"

    result = subprocess.run(
        [sys.executable, str(CLI), "--help"],
        capture_output=True,
        check=True,
        text=True,
    )
    for command in (
        "upstream-review-state",
        "upstream-review-handoff",
        "upstream-delivery-inbox",
        "upstream-draft-freshness",
        "upstream-author-accountability",
        "upstream-author-review-packet",
        "upstream-draft-progress",
        "upstream-readiness-discover",
    ):
        assert command in result.stdout, command
    print("kernel_opt CLI section test: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
