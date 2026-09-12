#!/usr/bin/env python3
"""Tests for the exact runtime import-closure preflight."""

from __future__ import annotations

import hashlib
import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

evaluate = importlib.import_module("runtime_import_preflight").evaluate


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_package(
    tmp_path: Path, *, eager_backend: bool = False, stdout_noise: bool = False
) -> tuple[Path, Path]:
    package = tmp_path / "sample_model"
    package.mkdir()
    (package / "quant_config.py").write_text(
        "class QuantConfig:\n    pass\n", encoding="utf-8"
    )
    (package / "backend.py").write_text("LOADED = True\n", encoding="utf-8")
    eager = "from . import backend\n" if eager_backend else ""
    entrypoint = package / "__init__.py"
    entrypoint.write_text(
        ("print('framework import notice')\n" if stdout_noise else "")
        + eager
        + "from .quant_config import QuantConfig\n",
        encoding="utf-8",
    )
    return package, entrypoint


def write_request(
    tmp_path: Path,
    module_file: Path,
    *,
    expected_hash: str | None = None,
    forbidden: list[str] | None = None,
    module: str = "sample_model",
    attribute: str | None = "QuantConfig",
) -> Path:
    request = {
        "schema_version": "runtime-import-preflight-request-v1",
        "candidate_id": "candidate-a",
        "interpreter": {"path": sys.executable, "sha256": digest(Path(sys.executable))},
        "working_directory": str(tmp_path),
        "python_paths": [str(tmp_path)],
        "environment_overrides": {
            "CUDA_VISIBLE_DEVICES": "",
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
        },
        "timeout_seconds": 10,
        "imports": [
            {
                "import_id": "quant-config-only",
                "module": module,
                "attribute": attribute,
                "expected_module_file": {
                    "path": str(module_file),
                    "sha256": expected_hash or digest(module_file),
                },
                "expected_attribute_module": (
                    "sample_model.quant_config" if attribute is not None else None
                ),
                "forbidden_loaded_module_prefixes": forbidden or [],
            }
        ],
    }
    path = tmp_path / "request.json"
    path.write_text(json.dumps(request), encoding="utf-8")
    return path


def run_evaluate(request_path: Path) -> dict:
    return evaluate(
        json.loads(request_path.read_text(encoding="utf-8")),
        request_path,
        {},
    )


def test_exact_lazy_import_closure_passes(tmp_path: Path) -> None:
    _, entrypoint = make_package(tmp_path, stdout_noise=True)
    result = run_evaluate(
        write_request(
            tmp_path,
            entrypoint,
            forbidden=["sample_model.backend"],
        )
    )
    assert result["decision"] == "READY_FOR_NEXT_PREFLIGHT"
    assert result["blockers"] == []
    observation = result["imports"][0]
    assert observation["status"] == "PASS"
    assert observation["module_file"] == entrypoint.resolve().as_posix()
    assert observation["attribute_module"] == "sample_model.quant_config"
    assert observation["forbidden_loaded_modules"] == []


def test_eager_optional_backend_import_fails_closed(tmp_path: Path) -> None:
    _, entrypoint = make_package(tmp_path, eager_backend=True)
    result = run_evaluate(
        write_request(
            tmp_path,
            entrypoint,
            forbidden=["sample_model.backend"],
        )
    )
    assert result["decision"] == "BLOCKED_RUNTIME_IMPORT"
    assert result["blockers"] == ["quant-config-only:FORBIDDEN_TRANSITIVE_IMPORT"]
    assert result["imports"][0]["forbidden_loaded_modules"] == ["sample_model.backend"]


@pytest.mark.parametrize(
    ("expected_path", "expected_hash", "expected_blocker"),
    [
        ("other.py", None, "MODULE_FILE_MISMATCH"),
        (None, "0" * 64, "MODULE_SHA256_MISMATCH"),
    ],
)
def test_module_path_and_bytes_are_both_bound(
    tmp_path: Path,
    expected_path: str | None,
    expected_hash: str | None,
    expected_blocker: str,
) -> None:
    _, entrypoint = make_package(tmp_path)
    target = entrypoint
    if expected_path is not None:
        target = tmp_path / expected_path
        target.write_text(entrypoint.read_text(encoding="utf-8"), encoding="utf-8")
    request = write_request(
        tmp_path,
        target,
        expected_hash=expected_hash or digest(target),
    )
    result = run_evaluate(request)
    assert result["decision"] == "BLOCKED_RUNTIME_IMPORT"
    assert expected_blocker in result["imports"][0]["blockers"]


def test_missing_generated_module_and_public_cli_fail_closed(tmp_path: Path) -> None:
    _, entrypoint = make_package(tmp_path)
    request = write_request(
        tmp_path,
        entrypoint,
        module="sample_model.generated_interface",
        attribute=None,
    )
    result = run_evaluate(request)
    assert result["decision"] == "BLOCKED_RUNTIME_IMPORT"
    assert result["imports"][0]["blockers"] == ["IMPORT_FAILED"]
    assert result["imports"][0]["error_type"] == "ModuleNotFoundError"

    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "kernel_opt.py"),
            "runtime-import-preflight",
            "--request",
            str(request),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 2
    assert json.loads(completed.stdout)["decision"] == "BLOCKED_RUNTIME_IMPORT"


def test_interpreter_drift_and_unknown_fields_fail_closed(tmp_path: Path) -> None:
    _, entrypoint = make_package(tmp_path)
    request_path = write_request(tmp_path, entrypoint)
    request = json.loads(request_path.read_text(encoding="utf-8"))
    request["interpreter"]["sha256"] = "0" * 64
    request_path.write_text(json.dumps(request), encoding="utf-8")
    result = run_evaluate(request_path)
    assert result["decision"] == "BLOCKED_RUNTIME_IMPORT"
    assert result["blockers"] == ["INTERPRETER_SHA256_MISMATCH"]
    assert result["imports"] == []

    request["hidden"] = True
    request_path.write_text(json.dumps(request), encoding="utf-8")
    with pytest.raises(ValueError, match="additional property"):
        run_evaluate(request_path)
