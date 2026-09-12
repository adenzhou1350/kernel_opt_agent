#!/usr/bin/env python3
"""Cross-platform repository audit path tests."""

from __future__ import annotations

import sys
from pathlib import Path, PurePosixPath, PureWindowsPath


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from audit_repository import relative_posix  # noqa: E402
from evidence_utils import validate_hardware_evidence  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]


def test_relative_posix_normalizes_windows_catalog_paths() -> None:
    assert (
        relative_posix(
            PureWindowsPath(r"C:\repo\microbench\nvidia\demo_probe"),
            PureWindowsPath(r"C:\repo\microbench"),
        )
        == "nvidia/demo_probe"
    )


def test_relative_posix_preserves_posix_catalog_paths() -> None:
    assert (
        relative_posix(
            PurePosixPath("/repo/microbench/nvidia/demo_probe"),
            PurePosixPath("/repo/microbench"),
        )
        == "nvidia/demo_probe"
    )


def test_trusted_hardware_policy_identity_is_portable() -> None:
    assert (
        validate_hardware_evidence(ROOT / "tests/fixtures/hardware_evidence.json") == []
    )
