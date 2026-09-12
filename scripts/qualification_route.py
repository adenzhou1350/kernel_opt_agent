#!/usr/bin/env python3
"""Classify qualification failures without blaming candidates for broken environments."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from schema_utils import validate_instance


REQUEST_VERSION = "qualification-attempt-v1"
RESULT_VERSION = "qualification-route-v1"


def root() -> Path:
    return Path(__file__).resolve().parents[1]


def read_object(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def request_template() -> dict:
    return {
        "schema_version": REQUEST_VERSION,
        "candidate_id": "replace-me",
        "execution_route": "OFFICIAL_WORKFLOW",
        "workflow_requires_native_build": False,
        "native_build_authorized": False,
        "failure_stage": "NOT_STARTED",
        "environment_failure": "NONE",
        "tests_collected": 0,
        "tests_executed": 0,
        "candidate_assertion_failures": 0,
        "exact_source_import_verified": False,
        "technical_repair_attempts": 0,
        "technical_repair_budget": 1,
    }


def validate_semantics(attempt: dict) -> None:
    schema = read_object(root() / "schemas/qualification_attempt.schema.json")
    errors = validate_instance(attempt, schema)
    if errors:
        raise ValueError("invalid qualification attempt: " + "; ".join(errors))
    if attempt["tests_executed"] > attempt["tests_collected"]:
        raise ValueError("tests_executed exceeds tests_collected")
    if attempt["candidate_assertion_failures"] > attempt["tests_executed"]:
        raise ValueError("candidate assertion failures exceed executed tests")
    if attempt["technical_repair_attempts"] > attempt["technical_repair_budget"]:
        raise ValueError("technical repair attempts exceed the frozen budget")
    if (
        attempt["failure_stage"] == "COMPLETE"
        and attempt["environment_failure"] != "NONE"
    ):
        raise ValueError("a completed attempt cannot retain an environment failure")
    if (
        attempt["candidate_assertion_failures"]
        and attempt["environment_failure"] != "NONE"
    ):
        raise ValueError(
            "candidate assertion failures and environment failure are mutually exclusive"
        )
    if (
        attempt["execution_route"] == "OFFICIAL_WORKFLOW"
        and attempt["workflow_requires_native_build"]
        and not attempt["native_build_authorized"]
        and attempt["tests_executed"]
    ):
        raise ValueError("tests executed under an unauthorized intrinsic native build")


def environment_action(failure: str, budget_exhausted: bool) -> str:
    if budget_exhausted:
        return "STOP_BOUNDED_ENVIRONMENT_REPAIR"
    if failure == "IMPORT_SOURCE_MISMATCH":
        return "USE_IMPORT_BOUND_CLOSURE"
    if failure == "IMAGE_UNAVAILABLE":
        return "MATERIALIZE_PINNED_PREBUILT_CLOSURE"
    if failure in {"DEPENDENCY_MISSING", "TOOLCHAIN_TIMEOUT", "ISA_INCOMPATIBLE"}:
        return "USE_CACHED_OR_PREBUILT_CLOSURE"
    return "REPAIR_ENVIRONMENT_WITHIN_BUDGET"


def evaluate(attempt: dict) -> dict:
    validate_semantics(attempt)
    reasons: list[str] = []
    workflow_build_blocked = (
        attempt["execution_route"] == "OFFICIAL_WORKFLOW"
        and attempt["workflow_requires_native_build"]
        and not attempt["native_build_authorized"]
    )

    if workflow_build_blocked:
        classification = "EXECUTION_CONTRACT_BLOCKED"
        action = "AUTHORIZE_INTRINSIC_BUILD_OR_USE_PREBUILT_CLOSURE"
        reasons.append("the official workflow intrinsically builds native code")
    elif attempt["environment_failure"] != "NONE":
        classification = "ENVIRONMENT_BLOCKED"
        budget_exhausted = (
            attempt["technical_repair_attempts"] >= attempt["technical_repair_budget"]
        )
        action = environment_action(attempt["environment_failure"], budget_exhausted)
        reasons.append(
            f"qualification stopped at {attempt['failure_stage']} because of "
            f"{attempt['environment_failure']}"
        )
    elif attempt["candidate_assertion_failures"]:
        if not attempt["exact_source_import_verified"]:
            raise ValueError(
                "candidate failures require exact imported-source verification"
            )
        classification = "CANDIDATE_FAILED"
        action = "REJECT_OR_REVISE_CANDIDATE_CORRECTNESS"
        reasons.append("an exact-source candidate assertion failed")
    elif attempt["tests_executed"] == 0:
        classification = "INCOMPLETE"
        action = "RUN_SEALED_TEST_BODY"
        reasons.append("no candidate test body executed")
    elif not attempt["exact_source_import_verified"]:
        classification = "EVIDENCE_INVALID"
        action = "BIND_ACTUAL_IMPORTED_SOURCE"
        reasons.append("executed tests were not bound to the imported candidate source")
    elif attempt["tests_executed"] < attempt["tests_collected"]:
        classification = "INCOMPLETE"
        action = "CONTINUE_SEALED_TESTS"
        reasons.append("only part of the collected test body executed")
    elif attempt["failure_stage"] != "COMPLETE":
        classification = "INCOMPLETE"
        action = "COMPLETE_REMAINING_QUALIFICATION_STAGE"
        reasons.append("test bodies passed but the sealed qualification is incomplete")
    else:
        classification = "QUALIFICATION_PASS"
        action = "ACCEPT_THIS_QUALIFICATION_GATE"
        reasons.append(
            "all collected exact-source tests completed without candidate failure"
        )

    return {
        "schema_version": RESULT_VERSION,
        "generated_at": now(),
        "candidate_id": attempt["candidate_id"],
        "classification": classification,
        "recommended_action": action,
        "candidate_disposition": (
            "REJECT_OR_REVISE" if classification == "CANDIDATE_FAILED" else "RETAIN"
        ),
        "test_body_executed": attempt["tests_executed"] > 0,
        "reasons": reasons,
        "claim_boundary": (
            "FAILURE_ROUTING_ONLY_NOT_CORRECTNESS_PERFORMANCE_OR_UPSTREAM_PROOF"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--attempt", type=Path)
    source.add_argument("--print-template", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    if args.print_template:
        if args.output:
            parser.error("--output requires --attempt")
        print(json.dumps(request_template(), indent=2, sort_keys=True))
        return 0

    attempt_path = args.attempt.resolve()
    result = evaluate(read_object(attempt_path))
    result["attempt_identity"] = {
        "path": attempt_path.as_posix(),
        "sha256": sha256_file(attempt_path),
    }
    if args.output:
        atomic_json(args.output.resolve(), result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
