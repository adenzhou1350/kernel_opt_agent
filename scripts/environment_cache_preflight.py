#!/usr/bin/env python3
"""Fail closed before cache-bound downloads, JIT compilation, or builds."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from schema_utils import validate_instance


REQUEST_SCHEMA = "environment_cache_preflight_request.schema.json"
RESULT_SCHEMA = "environment_cache_preflight_result.schema.json"
REQUEST_VERSION = "environment-cache-preflight-request-v1"
RESULT_VERSION = "environment-cache-preflight-result-v1"
CLAIM_BOUNDARY = (
    "CACHE_PATH_BINDING_SPACE_AND_WRITEABILITY_PREFLIGHT_ONLY_NOT_BUILD_DOWNLOAD_"
    "EXECUTION_CORRECTNESS_OR_PERFORMANCE_AUTHORIZATION"
)


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


def validate(value: dict, schema_name: str, label: str) -> None:
    schema = read_object(root() / "schemas" / schema_name)
    errors = validate_instance(value, schema)
    if errors:
        raise ValueError(f"invalid {label}: " + "; ".join(errors))


def nearest_existing(path: Path) -> Path | None:
    candidate = path
    while not candidate.exists():
        parent = candidate.parent
        if parent == candidate:
            return None
        candidate = parent
    return candidate


def equivalent_path(left: str, right: Path) -> bool:
    try:
        return Path(left).expanduser().resolve(strict=False) == right
    except (OSError, RuntimeError):
        return False


def probe_root(specification: dict, environment: dict[str, str]) -> dict:
    requested_path = Path(specification["path"]).expanduser()
    if not requested_path.is_absolute():
        raise ValueError(
            f"cache root {specification['cache_id']} path must be absolute"
        )
    resolved = requested_path.resolve(strict=False)
    environment_variable = specification["environment_variable"]
    environment_binding_matches: bool | None = None
    blockers: list[str] = []
    if environment_variable is not None:
        observed = environment.get(environment_variable)
        environment_binding_matches = observed is not None and equivalent_path(
            observed, resolved
        )
        if not environment_binding_matches:
            blockers.append(f"{specification['cache_id']}:ENVIRONMENT_BINDING_MISMATCH")

    exists = resolved.exists()
    is_directory = exists and resolved.is_dir()
    if specification["require_existing"] and not exists:
        blockers.append(f"{specification['cache_id']}:CACHE_ROOT_MISSING")
    if exists and not is_directory:
        blockers.append(f"{specification['cache_id']}:CACHE_ROOT_NOT_DIRECTORY")

    filesystem_path = resolved if exists else nearest_existing(resolved)
    if filesystem_path is not None and not filesystem_path.is_dir():
        blockers.append(f"{specification['cache_id']}:CACHE_PARENT_NOT_DIRECTORY")
        filesystem_path = None
    writable = bool(filesystem_path and os.access(filesystem_path, os.W_OK))
    if specification["require_writable"] and not writable:
        blockers.append(f"{specification['cache_id']}:CACHE_ROOT_NOT_WRITABLE")

    free_bytes: int | None = None
    if filesystem_path is None:
        blockers.append(f"{specification['cache_id']}:FILESYSTEM_UNRESOLVED")
    else:
        try:
            free_bytes = shutil.disk_usage(filesystem_path).free
        except OSError:
            blockers.append(f"{specification['cache_id']}:DISK_USAGE_UNAVAILABLE")
    if free_bytes is not None and free_bytes < specification["minimum_free_bytes"]:
        blockers.append(f"{specification['cache_id']}:INSUFFICIENT_FREE_SPACE")

    write_probe_performed = False
    write_probe_passed: bool | None = None
    if specification["write_probe_authorized"]:
        write_probe_performed = True
        write_probe_passed = False
        if is_directory:
            try:
                descriptor, temporary = tempfile.mkstemp(
                    dir=resolved, prefix=".kernel-opt-cache-probe-"
                )
                try:
                    os.write(descriptor, b"cache-preflight-v1\n")
                    os.fsync(descriptor)
                    write_probe_passed = True
                finally:
                    os.close(descriptor)
                    os.unlink(temporary)
            except OSError:
                write_probe_passed = False
        if not write_probe_passed:
            blockers.append(f"{specification['cache_id']}:WRITE_PROBE_FAILED")

    blockers = sorted(set(blockers))
    return {
        "cache_id": specification["cache_id"],
        "path": resolved.as_posix(),
        "environment_variable": environment_variable,
        "environment_binding_matches": environment_binding_matches,
        "exists": exists,
        "is_directory": is_directory,
        "writable": writable,
        "write_probe_performed": write_probe_performed,
        "write_probe_passed": write_probe_passed,
        "free_bytes": free_bytes,
        "minimum_free_bytes": specification["minimum_free_bytes"],
        "ready": not blockers,
        "blockers": blockers,
    }


def evaluate(request: dict, request_path: Path, environment: dict[str, str]) -> dict:
    validate(request, REQUEST_SCHEMA, "cache preflight request")
    cache_ids = [item["cache_id"] for item in request["cache_roots"]]
    if len(cache_ids) != len(set(cache_ids)):
        raise ValueError("cache root cache_id values must be unique")
    resolved_paths = [
        Path(item["path"]).expanduser().resolve(strict=False)
        for item in request["cache_roots"]
    ]
    if len(resolved_paths) != len(set(resolved_paths)):
        raise ValueError("cache root paths must be unique")

    results = [probe_root(item, environment) for item in request["cache_roots"]]
    blockers = sorted({blocker for item in results for blocker in item["blockers"]})
    output = {
        "schema_version": RESULT_VERSION,
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "candidate_id": request["candidate_id"],
        "request_identity": {
            "path": request_path.resolve().as_posix(),
            "sha256": sha256_file(request_path),
        },
        "decision": (
            "BLOCKED_ENVIRONMENT_CACHE" if blockers else "READY_FOR_CACHE_BOUND_COMMAND"
        ),
        "cache_roots": results,
        "blockers": blockers,
        "claim_boundary": CLAIM_BOUNDARY,
    }
    validate(output, RESULT_SCHEMA, "cache preflight result")
    return output


def request_template() -> dict:
    return {
        "schema_version": REQUEST_VERSION,
        "candidate_id": "replace-me",
        "cache_roots": [
            {
                "cache_id": "compiler-cache",
                "path": "/absolute/cache/path",
                "environment_variable": "FRAMEWORK_CACHE_DIR",
                "minimum_free_bytes": 10737418240,
                "require_existing": True,
                "require_writable": True,
                "write_probe_authorized": False,
            }
        ],
    }


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--print-template", action="store_true")
    parser.add_argument("--request", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.print_template:
        if args.request or args.output:
            parser.error("--print-template does not accept --request or --output")
        print(json.dumps(request_template(), indent=2, sort_keys=True))
        return 0
    if args.request is None:
        parser.error("--request is required")
    request_path = args.request.resolve()
    result = evaluate(read_object(request_path), request_path, dict(os.environ))
    if args.output:
        atomic_json(args.output.resolve(), result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["decision"] == "READY_FOR_CACHE_BOUND_COMMAND" else 2


if __name__ == "__main__":
    raise SystemExit(main())
