#!/usr/bin/env python3
"""Tests for fail-closed cache-root preflight."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from environment_cache_preflight import evaluate  # noqa: E402


def write_request(tmp_path: Path, cache_root: Path, **updates: object) -> Path:
    specification = {
        "cache_id": "humming-jit",
        "path": str(cache_root),
        "environment_variable": "HUMMING_CACHE_DIR",
        "minimum_free_bytes": 1,
        "require_existing": True,
        "require_writable": True,
        "write_probe_authorized": True,
    }
    specification.update(updates)
    request = {
        "schema_version": "environment-cache-preflight-request-v1",
        "candidate_id": "candidate-a",
        "cache_roots": [specification],
    }
    path = tmp_path / "request.json"
    path.write_text(json.dumps(request), encoding="utf-8")
    return path


def test_matching_writable_cache_is_ready_and_probe_is_removed(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    request_path = write_request(tmp_path, cache)
    result = evaluate(
        json.loads(request_path.read_text(encoding="utf-8")),
        request_path,
        {"HUMMING_CACHE_DIR": str(cache)},
    )
    assert result["decision"] == "READY_FOR_CACHE_BOUND_COMMAND"
    assert result["blockers"] == []
    assert result["cache_roots"][0]["write_probe_passed"] is True
    assert list(cache.iterdir()) == []


def test_missing_or_drifted_environment_binding_fails_closed(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    request_path = write_request(tmp_path, cache, write_probe_authorized=False)
    request = json.loads(request_path.read_text(encoding="utf-8"))
    missing = evaluate(request, request_path, {})
    assert missing["decision"] == "BLOCKED_ENVIRONMENT_CACHE"
    assert missing["blockers"] == ["humming-jit:ENVIRONMENT_BINDING_MISMATCH"]

    drifted = evaluate(
        request,
        request_path,
        {"HUMMING_CACHE_DIR": str(tmp_path / "other")},
    )
    assert drifted["blockers"] == ["humming-jit:ENVIRONMENT_BINDING_MISMATCH"]


def test_space_file_and_missing_root_failures_are_distinct(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    request_path = write_request(
        tmp_path,
        cache,
        minimum_free_bytes=2**63,
        write_probe_authorized=False,
    )
    request = json.loads(request_path.read_text(encoding="utf-8"))
    result = evaluate(request, request_path, {"HUMMING_CACHE_DIR": str(cache)})
    assert result["blockers"] == ["humming-jit:INSUFFICIENT_FREE_SPACE"]

    file_root = tmp_path / "file"
    file_root.write_text("not a directory", encoding="utf-8")
    request_path = write_request(tmp_path, file_root, write_probe_authorized=False)
    request = json.loads(request_path.read_text(encoding="utf-8"))
    result = evaluate(request, request_path, {"HUMMING_CACHE_DIR": str(file_root)})
    assert "humming-jit:CACHE_ROOT_NOT_DIRECTORY" in result["blockers"]

    missing_root = tmp_path / "missing"
    request_path = write_request(tmp_path, missing_root, write_probe_authorized=False)
    request = json.loads(request_path.read_text(encoding="utf-8"))
    result = evaluate(request, request_path, {"HUMMING_CACHE_DIR": str(missing_root)})
    assert "humming-jit:CACHE_ROOT_MISSING" in result["blockers"]


def test_duplicate_id_path_and_unknown_field_are_rejected(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    request_path = write_request(tmp_path, cache, write_probe_authorized=False)
    request = json.loads(request_path.read_text(encoding="utf-8"))
    request["cache_roots"].append(dict(request["cache_roots"][0]))
    with pytest.raises(ValueError, match="cache_id values must be unique"):
        evaluate(request, request_path, {"HUMMING_CACHE_DIR": str(cache)})

    request = json.loads(request_path.read_text(encoding="utf-8"))
    request["hidden"] = True
    with pytest.raises(ValueError, match="additional property"):
        evaluate(request, request_path, {"HUMMING_CACHE_DIR": str(cache)})


def test_relative_cache_root_is_rejected(tmp_path: Path) -> None:
    request_path = write_request(
        tmp_path, Path("relative-cache"), write_probe_authorized=False
    )
    request = json.loads(request_path.read_text(encoding="utf-8"))
    with pytest.raises(ValueError, match="path must be absolute"):
        evaluate(request, request_path, {"HUMMING_CACHE_DIR": "relative-cache"})


def test_missing_root_below_file_and_public_cli_fail_closed(tmp_path: Path) -> None:
    parent_file = tmp_path / "not-a-directory"
    parent_file.write_text("file", encoding="utf-8")
    cache = parent_file / "cache"
    request_path = write_request(
        tmp_path,
        cache,
        require_existing=False,
        write_probe_authorized=False,
    )
    request = json.loads(request_path.read_text(encoding="utf-8"))
    result = evaluate(request, request_path, {"HUMMING_CACHE_DIR": str(cache)})
    assert "humming-jit:CACHE_PARENT_NOT_DIRECTORY" in result["blockers"]

    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "kernel_opt.py"),
            "environment-cache-preflight",
            "--request",
            str(request_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 2
    assert json.loads(completed.stdout)["decision"] == "BLOCKED_ENVIRONMENT_CACHE"
