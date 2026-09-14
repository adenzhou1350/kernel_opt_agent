#!/usr/bin/env python3
"""Tests for the cache-confined command wrapper."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from qualification_environment_worker import CACHE_ENVIRONMENT_KEYS  # noqa: E402
from run_with_cache_environment import (  # noqa: E402
    contract,
    isolated_environment,
    main,
    prepare_directories,
)


def test_isolated_environment_replaces_implicit_home_caches() -> None:
    inherited = {
        "HOME": "/root",
        "XDG_CACHE_HOME": "/root/.cache",
        "FLASHINFER_WORKSPACE_BASE": "/root",
        "CUDA_VISIBLE_DEVICES": "GPU-example",
    }

    child, cache = isolated_environment(
        "/workspace/kernel-opt/tasks/run-v1",
        inherited=inherited,
    )

    assert set(cache) == set(CACHE_ENVIRONMENT_KEYS)
    assert child["HOME"] == "/root"
    assert child["CUDA_VISIBLE_DEVICES"] == "GPU-example"
    assert child["XDG_CACHE_HOME"].startswith("/workspace/kernel-opt/tasks/run-v1/")
    assert child["FLASHINFER_WORKSPACE_BASE"].startswith(
        "/workspace/kernel-opt/tasks/run-v1/"
    )
    assert all(not value.startswith("/root") for value in cache.values())


def test_prepare_directories_creates_only_closure_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closure = "/workspace/kernel-opt/tasks/run-v1"
    _, cache = isolated_environment(
        closure,
        inherited={},
    )
    created: list[str] = []
    monkeypatch.setattr(
        Path,
        "mkdir",
        lambda self, **kwargs: created.append(self.as_posix()),
    )

    prepare_directories(closure, cache)

    assert created == list(cache.values())


def test_prepare_directories_rejects_escape(tmp_path: Path) -> None:
    closure = tmp_path / "task"
    with pytest.raises(ValueError, match="escapes closure"):
        prepare_directories(
            closure.as_posix(),
            {"XDG_CACHE_HOME": (tmp_path / "outside").as_posix()},
        )


def test_print_environment_is_machine_readable(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    closure = "/workspace/kernel-opt/tasks/run-v1"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_with_cache_environment.py",
            "--closure-root",
            closure,
            "--print-environment",
        ],
    )

    assert main() == 0
    result = json.loads(capsys.readouterr().out)
    _, cache = isolated_environment(closure, inherited={})
    assert result == contract(closure, cache)


def test_wrapper_requires_command_without_print_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_with_cache_environment.py", "--closure-root", "/workspace/task"],
    )
    with pytest.raises(SystemExit, match="2"):
        main()
