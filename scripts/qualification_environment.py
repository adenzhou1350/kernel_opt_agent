#!/usr/bin/env python3
"""Decide whether a materialized qualification environment can be reused."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from schema_utils import validate_instance


CLOSURE_VERSION = "qualification-environment-closure-v1"
REQUEST_VERSION = "qualification-environment-request-v1"
RESULT_VERSION = "qualification-environment-reuse-v1"


def root() -> Path:
    return Path(__file__).resolve().parents[1]


def read_object(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


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
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
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


def validate(value: dict, schema_name: str, label: str) -> None:
    schema = read_object(root() / "schemas" / schema_name)
    errors = validate_instance(value, schema)
    if errors:
        raise ValueError(f"invalid {label}: " + "; ".join(errors))


def validate_semantics(closure: dict, request: dict) -> None:
    validate(
        closure,
        "qualification_environment_closure.schema.json",
        "environment closure",
    )
    validate(
        request,
        "qualification_environment_request.schema.json",
        "environment request",
    )
    extension = closure["execution"]["native_extension"]
    if extension["required"]:
        if not extension["artifact_sha256"] or not extension["source_tree_sha"]:
            raise ValueError(
                "a required materialized native extension needs artifact and source identities"
            )
    elif extension["artifact_sha256"] or extension["source_tree_sha"]:
        raise ValueError(
            "a closure without a native extension cannot claim extension identities"
        )


def mismatch(path: str, expected: object, observed: object) -> dict:
    return {"field": path, "expected": expected, "observed": observed}


def evaluate(closure: dict, request: dict) -> dict:
    validate_semantics(closure, request)
    hard_mismatches: list[dict] = []
    closure_platform = closure["platform"]
    request_platform = request["platform"]
    for field in ("os", "architecture", "gpu_visible"):
        if closure_platform[field] != request_platform[field]:
            hard_mismatches.append(
                mismatch(
                    f"platform.{field}",
                    request_platform[field],
                    closure_platform[field],
                )
            )
    missing_features = sorted(
        set(request_platform["required_cpu_features"])
        - set(closure_platform["available_cpu_features"])
    )
    if missing_features:
        hard_mismatches.append(
            mismatch("platform.required_cpu_features", missing_features, [])
        )

    closure_execution = closure["execution"]
    request_execution = request["execution"]
    for field in (
        "workflow_sha256",
        "test_contract_sha256",
        "dependency_lock_sha256",
        "toolchain_lock_sha256",
    ):
        if closure_execution[field] != request_execution[field]:
            hard_mismatches.append(
                mismatch(
                    f"execution.{field}",
                    request_execution[field],
                    closure_execution[field],
                )
            )
    expected_image = request_execution["image_digest"]
    if closure_execution["image_digest"] != expected_image:
        hard_mismatches.append(
            mismatch(
                "execution.image_digest",
                expected_image,
                closure_execution["image_digest"],
            )
        )
    if not closure["materialized"]:
        hard_mismatches.append(mismatch("materialized", True, False))

    source = request["candidate_source"]
    import_reusable = closure["source_binding"] == source
    extension = closure_execution["native_extension"]
    extension_required = request_execution["native_extension_required"]
    extension_reusable = not extension_required or (
        extension["required"]
        and extension["artifact_sha256"] is not None
        and extension["source_tree_sha"] == source["tree_sha"]
    )

    if hard_mismatches:
        decision = "MATERIALIZE_NEW_CLOSURE"
        next_action = "BUILD_OR_FETCH_MATCHING_ENVIRONMENT"
    elif extension_required and not extension_reusable:
        if request["allow_native_rebuild"]:
            decision = "REUSE_DEPENDENCIES_REBUILD_EXTENSION"
            next_action = "REBUILD_NATIVE_EXTENSION_THEN_VERIFY_IMPORTED_SOURCE"
        else:
            decision = "MATERIALIZE_NEW_CLOSURE"
            next_action = "USE_SOURCE_MATCHED_PREBUILT_CLOSURE"
    elif not import_reusable:
        decision = "REUSE_DEPENDENCIES_REBIND_SOURCE"
        next_action = "MOUNT_AND_HASH_VERIFY_CANDIDATE_SOURCE"
    else:
        decision = "REUSE_FULL_CLOSURE"
        next_action = "RUN_SEALED_TEST_BODY"

    return {
        "schema_version": RESULT_VERSION,
        "generated_at": now(),
        "candidate_id": request["candidate_id"],
        "closure_id": closure["closure_id"],
        "decision": decision,
        "next_action": next_action,
        "dependency_closure_reusable": not hard_mismatches,
        "native_extension_reusable": extension_reusable and not hard_mismatches,
        "import_binding_reusable": import_reusable and not hard_mismatches,
        "hard_mismatches": hard_mismatches,
        "claim_boundary": (
            "ADVISORY_ENVIRONMENT_REUSE_ROUTING_ONLY_NOT_EXECUTION_AUTHORIZATION_"
            "CORRECTNESS_OR_PERFORMANCE_EVIDENCE"
        ),
    }


def closure_template() -> dict:
    zero = "0" * 64
    tree = "0" * 40
    return {
        "schema_version": CLOSURE_VERSION,
        "closure_id": "replace-me",
        "materialized": False,
        "platform": {
            "os": "linux",
            "architecture": "x86_64",
            "available_cpu_features": [],
            "gpu_visible": False,
        },
        "execution": {
            "workflow_sha256": zero,
            "test_contract_sha256": zero,
            "image_digest": None,
            "dependency_lock_sha256": zero,
            "toolchain_lock_sha256": zero,
            "native_extension": {
                "required": False,
                "artifact_sha256": None,
                "source_tree_sha": None,
            },
        },
        "source_binding": {"tree_sha": tree, "module_sha256": zero},
    }


def request_template() -> dict:
    zero = "0" * 64
    tree = "0" * 40
    return {
        "schema_version": REQUEST_VERSION,
        "candidate_id": "replace-me",
        "platform": {
            "os": "linux",
            "architecture": "x86_64",
            "required_cpu_features": [],
            "gpu_visible": False,
        },
        "execution": {
            "workflow_sha256": zero,
            "test_contract_sha256": zero,
            "image_digest": None,
            "dependency_lock_sha256": zero,
            "toolchain_lock_sha256": zero,
            "native_extension_required": False,
        },
        "candidate_source": {"tree_sha": tree, "module_sha256": zero},
        "allow_native_rebuild": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--print-closure-template", action="store_true")
    mode.add_argument("--print-request-template", action="store_true")
    mode.add_argument("--closure", type=Path)
    parser.add_argument("--request", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    if args.print_closure_template or args.print_request_template:
        if args.request or args.output:
            parser.error("template output does not accept --request or --output")
        template = (
            closure_template() if args.print_closure_template else request_template()
        )
        print(json.dumps(template, indent=2, sort_keys=True))
        return 0
    if args.request is None:
        parser.error("--closure requires --request")

    closure_path = args.closure.resolve()
    request_path = args.request.resolve()
    result = evaluate(read_object(closure_path), read_object(request_path))
    result["closure_identity"] = {
        "path": closure_path.as_posix(),
        "sha256": sha256_file(closure_path),
    }
    result["request_identity"] = {
        "path": request_path.as_posix(),
        "sha256": sha256_file(request_path),
    }
    if args.output:
        atomic_json(args.output.resolve(), result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
