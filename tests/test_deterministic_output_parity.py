from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
KERNEL_OPT = ROOT / "scripts/kernel_opt.py"
COMPARE = ROOT / "scripts/compare_paired.py"


def output_digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def observations() -> dict:
    rows = []
    for arm in ("control", "candidate"):
        for repeat_index in range(2):
            for case_id in ("short", "long"):
                rows.append(
                    {
                        "arm": arm,
                        "repeat_index": repeat_index,
                        "case_id": case_id,
                        "output_sha256": output_digest(case_id),
                    }
                )
    return {
        "schema_version": "deterministic-output-observations-v1",
        "contract": {"path": "contract.json", "sha256": output_digest("contract")},
        "baseline_arm": "control",
        "candidate_arm": "candidate",
        "case_ids": ["short", "long"],
        "repeat_count": 2,
        "observations": rows,
    }


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def run_parity(
    tmp_path: Path, document: dict
) -> tuple[subprocess.CompletedProcess, Path]:
    (tmp_path / "contract.json").write_text("contract", encoding="utf-8")
    input_path = tmp_path / "observations.json"
    result_path = tmp_path / "parity.json"
    write_json(input_path, document)
    completed = subprocess.run(
        [
            sys.executable,
            str(KERNEL_OPT),
            "output-parity",
            "--input",
            str(input_path),
            "--output",
            str(result_path),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    return completed, result_path


def test_pass_result_unlocks_paired_performance(tmp_path: Path) -> None:
    completed, result_path = run_parity(tmp_path, observations())
    assert completed.returncode == 0, completed.stderr
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["status"] == "PASS"
    assert result["performance_evaluation_allowed"] is True
    assert result["mismatches"] == []

    samples = tmp_path / "paired.csv"
    samples.write_text(
        "pair,candidate,duration_us\n"
        "1,control,10\n1,candidate,9\n"
        "2,candidate,8\n2,control,10\n"
        "3,control,11\n3,candidate,9\n",
        encoding="utf-8",
    )
    comparison = tmp_path / "comparison.json"
    compared = subprocess.run(
        [
            sys.executable,
            str(COMPARE),
            "--input",
            str(samples),
            "--baseline",
            "control",
            "--candidate",
            "candidate",
            "--parity-result",
            str(result_path),
            "--bootstrap",
            "200",
            "--output",
            str(comparison),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert compared.returncode == 0, compared.stderr
    compared_result = json.loads(comparison.read_text(encoding="utf-8"))
    assert compared_result["decision"] == "ACCEPT"
    assert compared_result["correctness"] == "PASS"
    assert (
        compared_result["deterministic_output_parity"]["sha256"]
        == hashlib.sha256(result_path.read_bytes()).hexdigest()
    )


def test_output_mismatch_blocks_performance_before_csv_read(tmp_path: Path) -> None:
    document = observations()
    document["observations"][-1]["output_sha256"] = output_digest("wrong")
    completed, result_path = run_parity(tmp_path, document)
    assert completed.returncode == 1
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["status"] == "FAIL"
    assert result["performance_evaluation_allowed"] is False
    assert {item["reason"] for item in result["mismatches"]} == {"OUTPUT_MISMATCH"}

    comparison = tmp_path / "must-not-exist.json"
    compared = subprocess.run(
        [
            sys.executable,
            str(COMPARE),
            "--input",
            str(tmp_path / "missing-timing.csv"),
            "--baseline",
            "control",
            "--candidate",
            "candidate",
            "--parity-result",
            str(result_path),
            "--output",
            str(comparison),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert compared.returncode != 0
    assert "performance comparison is forbidden" in compared.stderr
    assert not comparison.exists()


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ("missing", "MISSING"),
        ("duplicate", "DUPLICATE"),
        ("unexpected", "UNEXPECTED"),
    ],
)
def test_coverage_failures_are_explicit(
    tmp_path: Path, mutation: str, reason: str
) -> None:
    document = observations()
    if mutation == "missing":
        document["observations"].pop()
    elif mutation == "duplicate":
        document["observations"].append(copy.deepcopy(document["observations"][0]))
    else:
        document["observations"][0]["repeat_index"] = 2
    completed, result_path = run_parity(tmp_path, document)
    assert completed.returncode == 1
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert reason in {item["reason"] for item in result["mismatches"]}


def test_tampered_result_is_not_accepted(tmp_path: Path) -> None:
    completed, result_path = run_parity(tmp_path, observations())
    assert completed.returncode == 0
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["performance_evaluation_allowed"] = False
    write_json(result_path, result)

    sys.path.insert(0, str(ROOT / "scripts"))
    from deterministic_output_parity import validate_parity_result

    with pytest.raises(ValueError, match="not reproducible"):
        validate_parity_result(result_path)


def test_contract_identity_is_verified_before_comparison(tmp_path: Path) -> None:
    completed, result_path = run_parity(tmp_path, observations())
    assert completed.returncode == 0
    (tmp_path / "contract.json").write_text("changed", encoding="utf-8")

    compared = subprocess.run(
        [
            sys.executable,
            str(COMPARE),
            "--input",
            str(tmp_path / "missing-timing.csv"),
            "--baseline",
            "control",
            "--candidate",
            "candidate",
            "--parity-result",
            str(result_path),
            "--output",
            str(tmp_path / "comparison.json"),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert compared.returncode != 0
    assert "contract SHA256 mismatch" in compared.stderr
