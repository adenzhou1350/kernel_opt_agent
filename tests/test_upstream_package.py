#!/usr/bin/env python3
"""Exercise fail-closed upstream package generation."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"


def write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, str):
        path.write_text(value, encoding="utf-8")
    else:
        path.write_text(
            json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(repository: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *args],
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def run_cli(*args: str, expected: int = 0) -> subprocess.CompletedProcess:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/kernel_opt.py"),
            "upstream-package",
            *args,
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == expected, (args, result.stdout, result.stderr)
    return result


def main() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        workspace = Path(temporary)
        repository = workspace / "repository"
        repository.mkdir()
        git(repository, "init")
        git(repository, "config", "user.name", "Test")
        git(repository, "config", "user.email", "test@example.com")
        source = repository / "kernel.py"
        write(source, "value = 1\n")
        git(repository, "add", "kernel.py")
        git(repository, "commit", "-m", "base")
        base = git(repository, "rev-parse", "HEAD")
        write(source, "value = 2\n")
        git(repository, "add", "kernel.py")
        git(repository, "commit", "-m", "candidate")
        candidate = git(repository, "rev-parse", "HEAD")

        evidence = workspace / "evidence"
        write(evidence / "correctness.json", {"status": "PASS"})
        write(evidence / "operator.json", {"baseline_us": 2.0, "candidate_us": 1.0})
        write(evidence / "model.json", {"baseline": 100.0, "candidate": 102.0})
        write(evidence / "reproduce.txt", "python benchmark.py\n")
        write(evidence / "checks.txt", "ruff PASS\n")
        write(evidence / "sm120.json", {"status": "PASS", "speedup": 1.01})

        def receipt(role: str, receipt_name: str, *artifact_names: str) -> dict:
            write(
                evidence / receipt_name,
                {
                    "schema_version": "upstream-evidence-receipt-v1",
                    "role": role,
                    "status": "PASS",
                    "candidate_commit": candidate,
                    "summary": f"{role} passed.",
                    "artifacts": [
                        {"path": name, "sha256": digest(evidence / name)}
                        for name in artifact_names
                    ],
                },
            )
            return {
                "role": role,
                "path": receipt_name,
                "sha256": digest(evidence / receipt_name),
            }

        correctness_receipt = receipt(
            "CORRECTNESS", "correctness-receipt.json", "correctness.json"
        )
        operator_receipt = receipt(
            "OPERATOR_PERFORMANCE", "operator-receipt.json", "operator.json"
        )
        model_receipt = receipt(
            "WHOLE_MODEL_PERFORMANCE", "model-receipt.json", "model.json"
        )
        reproduction_receipt = receipt(
            "REPRODUCTION", "reproduction-receipt.json", "reproduce.txt"
        )
        checks_receipt = receipt("UPSTREAM_CHECKS", "checks-receipt.json", "checks.txt")

        spec = {
            "schema_version": "upstream-candidate-spec-v1",
            "package_id": "candidate-v1",
            "repository": {
                "slug": "example/project",
                "title": "Remove redundant work",
                "base_branch": "main",
                "base_commit": base,
                "candidate_branch": "perf/remove-work",
                "candidate_commit": candidate,
            },
            "motivation": "The old path performs redundant work.",
            "modifications": [
                "Remove the redundant operation.",
                "Add a regression test.",
            ],
            "accuracy_summary": "The output contract is preserved.",
            "tests": [
                {
                    "command": "python test.py",
                    "status": "PASS",
                    "evidence_path": "correctness-receipt.json",
                },
                {
                    "command": "ruff check",
                    "status": "PASS",
                    "evidence_path": "checks-receipt.json",
                },
            ],
            "benchmark_claims": [
                {
                    "scope": "OPERATOR",
                    "workload": "shape A",
                    "metric": "latency",
                    "direction": "LOWER_IS_BETTER",
                    "baseline": 2.0,
                    "candidate": 1.0,
                    "unit": "us",
                    "speedup": 2.0,
                    "evidence_path": "operator-receipt.json",
                },
                {
                    "scope": "WHOLE_MODEL",
                    "workload": "model A",
                    "metric": "throughput",
                    "direction": "HIGHER_IS_BETTER",
                    "baseline": 100.0,
                    "candidate": 102.0,
                    "unit": "tok/s",
                    "speedup": 1.02,
                    "evidence_path": "model-receipt.json",
                },
            ],
            "evidence": [
                correctness_receipt,
                operator_receipt,
                model_receipt,
                reproduction_receipt,
                checks_receipt,
            ],
            "boundaries": ["Validated on one architecture."],
            "gates": [
                {
                    "name": "correctness",
                    "status": "PASS",
                    "rationale": "Exact checks passed.",
                },
                {
                    "name": "source_review",
                    "status": "PASS",
                    "rationale": "The diff is minimal.",
                },
                {
                    "name": "whole_model_performance",
                    "status": "PASS",
                    "rationale": "Model A improved.",
                },
                {
                    "name": "upstream_checks",
                    "status": "PASS",
                    "rationale": "Local checks passed.",
                },
                {
                    "name": "cross_hardware",
                    "status": "PENDING",
                    "rationale": "Second device pending.",
                },
            ],
        }
        spec_path = workspace / "spec.json"
        write(spec_path, spec)
        draft_output = workspace / "draft-package"
        result = run_cli(
            "build",
            "--spec",
            str(spec_path),
            "--evidence-root",
            str(evidence),
            "--repository",
            str(repository),
            "--output",
            str(draft_output),
        )
        package_result = json.loads(result.stdout)
        assert package_result["status"] == "DRAFT_PENDING_QUALIFICATION"
        manifest = json.loads(
            (draft_output / "manifest.json").read_text(encoding="utf-8")
        )
        assert manifest["pending_gates"] == ["cross_hardware"]
        assert "upstream-ready" in manifest["claims_forbidden"]
        assert (
            digest(draft_output / "changes.patch")
            == manifest["source"]["patch"]["sha256"]
        )
        assert "Validated on one architecture" in (draft_output / "PR.md").read_text(
            encoding="utf-8"
        )
        run_cli(
            "build",
            "--spec",
            str(spec_path),
            "--evidence-root",
            str(evidence),
            "--repository",
            str(repository),
            "--output",
            str(draft_output),
            expected=1,
        )

        spec["evidence"].append(
            receipt("CROSS_HARDWARE", "sm120-receipt.json", "sm120.json")
        )
        for gate in spec["gates"]:
            if gate["name"] == "cross_hardware":
                gate["status"] = "PASS"
                gate["rationale"] = "SM120 replication passed."
        write(spec_path, spec)
        ready_output = workspace / "ready-package"
        ready = run_cli(
            "build",
            "--spec",
            str(spec_path),
            "--evidence-root",
            str(evidence),
            "--repository",
            str(repository),
            "--output",
            str(ready_output),
        )
        assert json.loads(ready.stdout)["status"] == "UPSTREAM_READY"

        write(evidence / "model.json", {"tampered": True})
        run_cli(
            "build",
            "--spec",
            str(spec_path),
            "--evidence-root",
            str(evidence),
            "--repository",
            str(repository),
            "--output",
            str(workspace / "stale-package"),
            expected=1,
        )

        spec["evidence"][2] = receipt(
            "WHOLE_MODEL_PERFORMANCE", "model-receipt-v2.json", "model.json"
        )
        spec["benchmark_claims"][1]["evidence_path"] = "model-receipt-v2.json"
        spec["benchmark_claims"][1]["speedup"] = 9.0
        write(spec_path, spec)
        run_cli(
            "build",
            "--spec",
            str(spec_path),
            "--evidence-root",
            str(evidence),
            "--repository",
            str(repository),
            "--output",
            str(workspace / "false-claim-package"),
            expected=1,
        )
    print("upstream package test: PASS")


if __name__ == "__main__":
    main()
