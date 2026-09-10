#!/usr/bin/env python3
"""Fail closed unless every deterministic output matches across arms and repeats."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

from schema_utils import validate_instance

OBSERVATIONS_SCHEMA = "deterministic-output-observations-v1"
RESULT_SCHEMA = "deterministic-output-parity-result-v1"


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_object(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return value


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def schema(name: str) -> dict:
    return read_object(repository_root() / "schemas" / name)


def bound_path(owner: Path, identity: dict, label: str) -> Path:
    relative = identity.get("path")
    if not isinstance(relative, str) or not relative:
        raise ValueError(f"{label} path is invalid")
    path = Path(relative)
    if path.is_absolute():
        raise ValueError(f"{label} path must be relative")
    resolved = (owner.parent / path).resolve()
    if not resolved.is_file():
        raise ValueError(f"{label} is missing")
    if digest(resolved) != identity.get("sha256"):
        raise ValueError(f"{label} SHA256 mismatch")
    return resolved


def validate_observations(document: dict, input_path: Path) -> None:
    errors = validate_instance(
        document,
        schema("deterministic_output_observations.schema.json"),
    )
    if errors:
        raise ValueError("invalid deterministic observations: " + "; ".join(errors))
    if document["baseline_arm"] == document["candidate_arm"]:
        raise ValueError("baseline_arm and candidate_arm must differ")
    bound_path(input_path, document["contract"], "deterministic output contract")


def mismatch(
    reason: str,
    key: tuple[str, int, str],
    *,
    expected: str | None,
    observed: str | None,
) -> dict:
    arm, repeat_index, case_id = key
    return {
        "reason": reason,
        "arm": arm,
        "repeat_index": repeat_index,
        "case_id": case_id,
        "expected_sha256": expected,
        "observed_sha256": observed,
    }


def analyze(document: dict, input_identity: dict, input_path: Path) -> dict:
    validate_observations(document, input_path)
    baseline = document["baseline_arm"]
    candidate = document["candidate_arm"]
    case_ids = document["case_ids"]
    repeat_count = document["repeat_count"]
    expected_keys = [
        (arm, repeat_index, case_id)
        for arm in (baseline, candidate)
        for repeat_index in range(repeat_count)
        for case_id in case_ids
    ]
    expected_set = set(expected_keys)
    first_by_key: dict[tuple[str, int, str], str] = {}
    mismatches = []
    for observation in document["observations"]:
        key = (
            observation["arm"],
            observation["repeat_index"],
            observation["case_id"],
        )
        observed = observation["output_sha256"]
        if key not in expected_set:
            mismatches.append(
                mismatch(
                    "UNEXPECTED",
                    key,
                    expected=None,
                    observed=observed,
                )
            )
        elif key in first_by_key:
            mismatches.append(
                mismatch(
                    "DUPLICATE",
                    key,
                    expected=first_by_key[key],
                    observed=observed,
                )
            )
        else:
            first_by_key[key] = observed

    for key in expected_keys:
        if key not in first_by_key:
            mismatches.append(mismatch("MISSING", key, expected=None, observed=None))

    for case_id in case_ids:
        reference = first_by_key.get((baseline, 0, case_id))
        if reference is None:
            continue
        for key in expected_keys:
            if key[2] != case_id or key not in first_by_key:
                continue
            observed = first_by_key[key]
            if observed != reference:
                mismatches.append(
                    mismatch(
                        "OUTPUT_MISMATCH",
                        key,
                        expected=reference,
                        observed=observed,
                    )
                )

    mismatches.sort(
        key=lambda item: (
            item["case_id"],
            item["arm"],
            item["repeat_index"],
            item["reason"],
        )
    )
    passed = not mismatches
    return {
        "schema_version": RESULT_SCHEMA,
        "input": input_identity,
        "contract": document["contract"],
        "baseline_arm": baseline,
        "candidate_arm": candidate,
        "case_ids": case_ids,
        "repeat_count": repeat_count,
        "expected_observation_count": len(expected_keys),
        "observed_observation_count": len(document["observations"]),
        "status": "PASS" if passed else "FAIL",
        "performance_evaluation_allowed": passed,
        "mismatch_count": len(mismatches),
        "mismatches": mismatches,
    }


def validate_parity_result(path: Path) -> dict:
    path = path.resolve()
    result = read_object(path)
    errors = validate_instance(
        result,
        schema("deterministic_output_parity_result.schema.json"),
    )
    if errors:
        raise ValueError("invalid deterministic parity result: " + "; ".join(errors))
    input_path = bound_path(path, result["input"], "deterministic parity input")
    expected = analyze(read_object(input_path), result["input"], input_path)
    if result != expected:
        raise ValueError("deterministic parity result is not reproducible")
    return result


def atomic_write(path: Path, value: dict) -> None:
    if path.exists():
        raise FileExistsError(f"output already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        temporary.write_bytes(canonical_json(value))
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = args.input.resolve()
    output_path = args.output.resolve()
    try:
        relative = os.path.relpath(input_path, output_path.parent).replace("\\", "/")
        if Path(relative).is_absolute():
            raise ValueError("input identity could not be made output-relative")
        identity = {"path": relative, "sha256": digest(input_path)}
        result = analyze(read_object(input_path), identity, input_path)
        result_errors = validate_instance(
            result,
            schema("deterministic_output_parity_result.schema.json"),
        )
        if result_errors:
            raise ValueError(
                "invalid generated parity result: " + "; ".join(result_errors)
            )
        atomic_write(output_path, result)
        print(
            json.dumps(
                {
                    "status": result["status"],
                    "performance_evaluation_allowed": result[
                        "performance_evaluation_allowed"
                    ],
                    "mismatch_count": result["mismatch_count"],
                },
                sort_keys=True,
            )
        )
        return 0 if result["status"] == "PASS" else 1
    except (FileNotFoundError, OSError, TypeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
