#!/usr/bin/env python3
"""Exercise the bounded producer-to-consumer compatibility canary."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from qualification_pipeline_canary import run_canary  # noqa: E402


CLAIM_BOUNDARY = (
    "DRY_RUN_COMPATIBILITY_ONLY_NOT_EXECUTION_AUTHORIZATION_OR_PERFORMANCE_EVIDENCE"
)


def write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8", newline="\n")


def write_json(path: Path, value: dict) -> None:
    write(path, json.dumps(value, indent=2) + "\n")


def spec(producer: str, consumer: str) -> dict:
    return {
        "schema_version": "qualification-pipeline-canary-v1",
        "claim_boundary": CLAIM_BOUNDARY,
        "stages": [
            {
                "id": "producer",
                "argv": ["{python}", producer, "{artifact_root}/result.json"],
                "cwd": ".",
                "environment": {"CUDA_VISIBLE_DEVICES": "-1"},
                "timeout_seconds": 5,
                "expected_exit_code": 0,
                "expected_outputs": [
                    {"path": "result.json", "freshness": "CREATED_OR_CHANGED"}
                ],
            },
            {
                "id": "consumer",
                "argv": [
                    "{python}",
                    consumer,
                    "{artifact_root}/result.json",
                    "{artifact_root}/decision.json",
                ],
                "cwd": ".",
                "environment": {"CUDA_VISIBLE_DEVICES": "-1"},
                "timeout_seconds": 5,
                "expected_exit_code": 0,
                "expected_outputs": [
                    {"path": "decision.json", "freshness": "CREATED_OR_CHANGED"}
                ],
            },
        ],
    }


def make_scripts(root: Path, producer_field: str = "git_tree") -> tuple[str, str]:
    producer = root / "producer.py"
    consumer = root / "consumer.py"
    write(
        producer,
        "import json, pathlib, sys\n"
        "pathlib.Path(sys.argv[1]).write_text("
        f"json.dumps({{{producer_field!r}: 'abc'}}))\n",
    )
    write(
        consumer,
        "import json, pathlib, sys\n"
        "value = json.loads(pathlib.Path(sys.argv[1]).read_text())\n"
        "assert value['git_tree'] == 'abc'\n"
        "pathlib.Path(sys.argv[2]).write_text(json.dumps({'accepted': True}))\n",
    )
    return producer.name, consumer.name


def test_canary_runs_the_complete_compatible_chain() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        producer, consumer = make_scripts(root)
        spec_path = root / "spec.json"
        output = root / "receipt.json"
        write_json(spec_path, spec(producer, consumer))

        result = run_canary(spec_path, root, output)

        assert result["status"] == "PASS"
        assert result["pipeline_compatible"] is True
        assert [stage["status"] for stage in result["stages"]] == ["PASS", "PASS"]
        assert result["execution_authorized"] is False
        assert output.is_file()


def test_canary_catches_producer_consumer_field_mismatch_before_gpu() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        producer, consumer = make_scripts(root, producer_field="tree")
        spec_path = root / "spec.json"
        output = root / "receipt.json"
        write_json(spec_path, spec(producer, consumer))

        result = run_canary(spec_path, root, output)

        assert result["status"] == "FAIL"
        assert result["pipeline_compatible"] is False
        assert result["stages"][0]["status"] == "PASS"
        assert result["stages"][1]["status"] == "FAIL"
        assert "exit code" in result["stages"][1]["error"]


def test_canary_accepts_expected_negative_exit_with_terminal_artifact() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        producer, _ = make_scripts(root)
        rejector = root / "rejector.py"
        write(
            rejector,
            "import json, pathlib, sys\n"
            "pathlib.Path(sys.argv[1]).write_text("
            "json.dumps({'status': 'FAIL', 'reason': 'correctness'}))\n"
            "raise SystemExit(2)\n",
        )
        value = spec(producer, rejector.name)
        value["stages"][1]["argv"] = [
            "{python}",
            rejector.name,
            "{artifact_root}/decision.json",
        ]
        value["stages"][1]["expected_exit_code"] = 2
        spec_path = root / "spec.json"
        output = root / "receipt.json"
        write_json(spec_path, value)

        result = run_canary(spec_path, root, output)

        assert result["status"] == "PASS"
        assert result["pipeline_compatible"] is True
        assert result["stages"][1]["exit_code"] == 2
        assert result["stages"][1]["outputs"][0]["path"] == "decision.json"


def test_canary_rejects_expected_negative_exit_without_terminal_artifact() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        producer, _ = make_scripts(root)
        crashing_rejector = root / "crashing_rejector.py"
        write(
            crashing_rejector,
            "raise SystemExit(2)\n",
        )
        value = spec(producer, crashing_rejector.name)
        value["stages"][1]["argv"] = ["{python}", crashing_rejector.name]
        value["stages"][1]["expected_exit_code"] = 2
        spec_path = root / "spec.json"
        output = root / "receipt.json"
        write_json(spec_path, value)

        result = run_canary(spec_path, root, output)

        assert result["status"] == "FAIL"
        assert result["pipeline_compatible"] is False
        assert result["stages"][1]["exit_code"] == 2
        assert result["stages"][1]["status"] == "FAIL"
        assert result["stages"][1]["error"] == (
            "required output is missing: decision.json"
        )


def test_canary_rejects_paths_outside_the_artifact_root() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        producer, consumer = make_scripts(root)
        value = spec(producer, consumer)
        value["stages"][0]["expected_outputs"][0]["path"] = "../escaped.json"
        spec_path = root / "spec.json"
        write_json(spec_path, value)

        with pytest.raises(ValueError, match="escapes artifact root"):
            run_canary(spec_path, root, root / "receipt.json")


def test_canary_rejects_duplicate_stage_outputs() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        producer, consumer = make_scripts(root)
        value = spec(producer, consumer)
        value["stages"][0]["expected_outputs"].append(
            {"path": "result.json", "freshness": "PRESENT"}
        )
        spec_path = root / "spec.json"
        write_json(spec_path, value)

        with pytest.raises(ValueError, match="repeats an output path"):
            run_canary(spec_path, root, root / "receipt.json")


def test_canary_rejects_an_unchanged_required_output() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        noop = root / "noop.py"
        write(noop, "pass\n")
        write(root / "result.json", "unchanged\n")
        value = spec(noop.name, noop.name)
        value["stages"][0]["argv"] = ["{python}", noop.name]
        spec_path = root / "spec.json"
        write_json(spec_path, value)

        result = run_canary(spec_path, root, root / "receipt.json")

        assert result["status"] == "FAIL"
        assert "not created or changed" in result["stages"][0]["error"]


def test_canary_times_out_without_running_later_stages() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        slow = root / "slow.py"
        consumer = root / "consumer.py"
        write(slow, "import time\ntime.sleep(5)\n")
        write(consumer, "raise AssertionError('must not run')\n")
        value = spec(slow.name, consumer.name)
        value["stages"][0]["timeout_seconds"] = 1
        spec_path = root / "spec.json"
        write_json(spec_path, value)

        result = run_canary(spec_path, root, root / "receipt.json")

        assert result["status"] == "FAIL"
        assert result["stages"][0]["timed_out"] is True
        assert len(result["stages"]) == 1


def test_public_cli_runs_the_pipeline_and_writes_the_receipt() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        producer, consumer = make_scripts(root)
        spec_path = root / "spec.json"
        output = root / "receipt.json"
        write_json(spec_path, spec(producer, consumer))

        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "kernel_opt.py"),
                "qualification-pipeline-canary",
                "--spec",
                str(spec_path),
                "--artifact-root",
                str(root),
                "--output",
                str(output),
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        assert completed.returncode == 0, completed.stderr
        assert json.loads(completed.stdout)["pipeline_compatible"] is True
        assert json.loads(output.read_text(encoding="utf-8"))["status"] == "PASS"
