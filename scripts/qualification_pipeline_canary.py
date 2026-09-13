#!/usr/bin/env python3
"""Exercise a bounded producer-to-consumer pipeline before costly execution."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from schema_utils import validate_json_file


SCHEMA = "qualification_pipeline_canary.schema.json"
RESULT_SCHEMA = "qualification_pipeline_canary_result.schema.json"
CLAIM_BOUNDARY = (
    "DRY_RUN_COMPATIBILITY_ONLY_NOT_EXECUTION_AUTHORIZATION_OR_PERFORMANCE_EVIDENCE"
)


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def identity(path: Path, root: Path) -> dict:
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
    }


def resolve_inside(root: Path, relative: str, label: str) -> Path:
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise ValueError(f"{label} escapes artifact root: {relative}") from error
    return path


def render(value: str, root: Path) -> str:
    return value.replace("{artifact_root}", str(root)).replace(
        "{python}", sys.executable
    )


def write_once(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")


def validate_spec(spec_path: Path) -> dict:
    errors = validate_json_file(spec_path, repository_root() / "schemas" / SCHEMA)
    if errors:
        raise ValueError("invalid pipeline canary schema: " + "; ".join(errors))
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    stage_ids = [stage["id"] for stage in spec["stages"]]
    if len(stage_ids) != len(set(stage_ids)):
        raise ValueError("pipeline canary stage ids must be unique")
    if not 2 <= len(stage_ids) <= 16:
        raise ValueError("pipeline canary requires between 2 and 16 stages")
    input_paths = [item["path"] for item in spec.get("required_inputs", [])]
    if len(input_paths) != len(set(input_paths)):
        raise ValueError("pipeline canary repeats a required input path")
    for stage in spec["stages"]:
        output_paths = [item["path"] for item in stage["expected_outputs"]]
        if len(output_paths) != len(set(output_paths)):
            raise ValueError(
                f"pipeline canary stage {stage['id']} repeats an output path"
            )
    return spec


def validate_required_inputs(spec: dict, artifact_root: Path) -> None:
    """Validate every declared executable/data input before any stage starts."""
    for expected in spec.get("required_inputs", []):
        path = resolve_inside(artifact_root, expected["path"], "required input")
        if not path.is_file():
            raise FileNotFoundError(f"required input is missing: {expected['path']}")
        actual = sha256_file(path)
        if actual != expected["sha256"]:
            raise ValueError(
                f"required input hash mismatch: {expected['path']} "
                f"expected {expected['sha256']} got {actual}"
            )


def run_canary(spec_path: Path, artifact_root: Path, output_path: Path) -> dict:
    spec_path = spec_path.resolve(strict=True)
    artifact_root = artifact_root.resolve(strict=True)
    output_path = output_path.resolve()
    try:
        output_path.relative_to(artifact_root)
    except ValueError as error:
        raise ValueError("pipeline canary output escapes artifact root") from error
    if output_path.exists():
        raise FileExistsError(f"pipeline canary output already exists: {output_path}")

    spec = validate_spec(spec_path)
    if spec["claim_boundary"] != CLAIM_BOUNDARY:
        raise ValueError(
            "pipeline canary claim boundary differs from the tool contract"
        )
    validate_required_inputs(spec, artifact_root)

    receipt = {
        "schema_version": "qualification-pipeline-canary-result-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS",
        "claim_boundary": CLAIM_BOUNDARY,
        "spec": {
            "path": spec_path.as_posix(),
            "sha256": sha256_file(spec_path),
        },
        "artifact_root": artifact_root.as_posix(),
        "stages": [],
        "pipeline_compatible": True,
        "execution_authorized": False,
        "performance_claim_created": False,
    }

    for stage in spec["stages"]:
        cwd = resolve_inside(artifact_root, stage["cwd"], f"{stage['id']} cwd")
        if not cwd.is_dir():
            raise FileNotFoundError(f"{stage['id']} cwd is missing: {cwd}")
        outputs = []
        before = {}
        for expected in stage["expected_outputs"]:
            path = resolve_inside(
                artifact_root, expected["path"], f"{stage['id']} output"
            )
            before[expected["path"]] = sha256_file(path) if path.is_file() else None
            outputs.append((expected, path))

        argv = [render(value, artifact_root) for value in stage["argv"]]
        environment = os.environ.copy()
        environment.update(
            {
                key: render(value, artifact_root)
                for key, value in stage["environment"].items()
            }
        )
        started = time.monotonic()
        timed_out = False
        exit_code = None
        stdout = b""
        stderr = b""
        error = None
        try:
            completed = subprocess.run(
                argv,
                cwd=cwd,
                env=environment,
                capture_output=True,
                timeout=stage["timeout_seconds"],
                check=False,
            )
            exit_code = completed.returncode
            stdout = completed.stdout
            stderr = completed.stderr
            if exit_code != stage["expected_exit_code"]:
                error = (
                    f"exit code {exit_code} differs from expected "
                    f"{stage['expected_exit_code']}"
                )
        except subprocess.TimeoutExpired as timeout:
            timed_out = True
            stdout = timeout.stdout or b""
            stderr = timeout.stderr or b""
            error = f"timed out after {stage['timeout_seconds']} seconds"
        except OSError as launch_error:
            error = f"launch failed: {launch_error}"
        duration_ms = round((time.monotonic() - started) * 1000, 3)

        output_receipts = []
        if error is None:
            for expected, path in outputs:
                if not path.is_file():
                    error = f"required output is missing: {expected['path']}"
                    break
                current = sha256_file(path)
                prior = before[expected["path"]]
                if expected["freshness"] == "CREATED_OR_CHANGED" and current == prior:
                    error = (
                        "required output was not created or changed: "
                        f"{expected['path']}"
                    )
                    break
                output_receipts.append(
                    {
                        **identity(path, artifact_root),
                        "freshness": expected["freshness"],
                        "previous_sha256": prior,
                    }
                )

        receipt["stages"].append(
            {
                "id": stage["id"],
                "argv": argv,
                "cwd": cwd.relative_to(artifact_root).as_posix(),
                "exit_code": exit_code,
                "timed_out": timed_out,
                "duration_ms": duration_ms,
                "stdout_sha256": sha256_bytes(stdout),
                "stderr_sha256": sha256_bytes(stderr),
                "outputs": output_receipts,
                "status": "PASS" if error is None else "FAIL",
                "error": error,
            }
        )
        if error is not None:
            receipt["status"] = "FAIL"
            receipt["pipeline_compatible"] = False
            break

    write_once(output_path, receipt)
    result_errors = validate_json_file(
        output_path, repository_root() / "schemas" / RESULT_SCHEMA
    )
    if result_errors:
        raise ValueError(
            "pipeline canary produced an invalid result: " + "; ".join(result_errors)
        )
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True, type=Path)
    parser.add_argument("--artifact-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = run_canary(args.spec, args.artifact_root, args.output)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
