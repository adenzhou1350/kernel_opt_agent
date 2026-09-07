"""Exercise CPU-only runtime preflight receipts and fail-closed validation."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from community_knowledge import atomic_json  # noqa: E402
from community_runtime_preflight import run_preflight, validate_receipt  # noqa: E402


def head_commit(checkout: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def arguments(
    output: Path,
    *,
    forbidden_roots: list[Path] | None = None,
) -> Namespace:
    return Namespace(
        python=Path(sys.executable),
        environment_root=Path(sys.prefix),
        resource_id="test-cpu-preflight",
        source_checkout=ROOT,
        expected_source_commit=head_commit(ROOT),
        pythonpath_root=[ROOT / "scripts"],
        forbidden_root=forbidden_roots or [],
        require_import=["json", "community_materialized_feasibility"],
        timeout_seconds=30,
        output=output,
    )


def test_runtime_preflight_runs_imports_without_initializing_cuda() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        receipt_path = base / "runtime.json"
        with patch(
            "community_runtime_preflight.git_output",
            side_effect=[head_commit(ROOT), ""],
        ):
            receipt = run_preflight(arguments(receipt_path))
        assert receipt["status"] == "PASS"
        assert receipt["checks"]["all_imports_passed"]
        assert receipt["checks"]["source_checkout_clean"]
        assert receipt["checks"]["python_prefix_matches_environment_root"]
        assert receipt["checks"]["cuda_initialized_after_imports"] is None
        assert not receipt["actions"]["compilation_requested_by_preflight"]
        assert receipt["actions"]["gpu_benchmarks_started"] == 0
        atomic_json(receipt_path, receipt)
        assert validate_receipt(receipt_path, ROOT)["status"] == "PASS"


def test_runtime_preflight_rejects_reserved_environment_and_status_tampering() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        receipt_path = base / "runtime.json"
        with patch(
            "community_runtime_preflight.git_output",
            side_effect=[head_commit(ROOT), ""],
        ):
            receipt = run_preflight(
                arguments(receipt_path, forbidden_roots=[Path(sys.prefix)])
            )
        assert receipt["status"] == "FAIL"
        assert not receipt["checks"]["environment_outside_forbidden_roots"]
        atomic_json(receipt_path, receipt)
        assert validate_receipt(receipt_path, ROOT)["status"] == "FAIL"

        edited = json.loads(receipt_path.read_text(encoding="utf-8"))
        edited["status"] = "PASS"
        atomic_json(receipt_path, edited)
        try:
            validate_receipt(receipt_path, ROOT)
        except ValueError as error:
            assert "status is inconsistent" in str(error)
        else:
            raise AssertionError("tampered runtime preflight status passed validation")


def test_runtime_preflight_rejects_dirty_source_identity() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        receipt_path = base / "runtime.json"
        with patch(
            "community_runtime_preflight.git_output",
            side_effect=[head_commit(ROOT), "?? dirty.json"],
        ):
            receipt = run_preflight(arguments(receipt_path))
        assert receipt["source_checkout"]["dirty"] is True
        assert receipt["checks"]["source_checkout_clean"] is False
        assert receipt["status"] == "FAIL"
        atomic_json(receipt_path, receipt)
        assert validate_receipt(receipt_path, ROOT)["status"] == "FAIL"

        edited = json.loads(receipt_path.read_text(encoding="utf-8"))
        edited["checks"]["source_checkout_clean"] = True
        atomic_json(receipt_path, edited)
        try:
            validate_receipt(receipt_path, ROOT)
        except ValueError as error:
            assert "source cleanliness is inconsistent" in str(error)
        else:
            raise AssertionError("dirty source passed a clean runtime receipt")
