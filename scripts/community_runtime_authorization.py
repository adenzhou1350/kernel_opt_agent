#!/usr/bin/env python3
"""Bind one validated combined authorization to exact task runtimes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path

from community_claim_contracts import digest
from community_execution_authorization_v2 import (
    same_identity,
    validate_authorization as validate_base_authorization,
    validate_identity,
)
from community_resource_amendment import validate_amendment
from schema_utils import validate_json_file


AUTHORIZATION_SCHEMA = "community_runtime_bound_execution_authorization.schema.json"
PROFILE_SCHEMA = "community_task_execution_profile.schema.json"
TREATMENT_SCHEMA = "community_arm_treatment_manifest.schema.json"
BASE_SCHEMA = "community_combined_execution_authorization_v2.schema.json"
VALIDATOR_PATH = "scripts/community_runtime_authorization.py"
BASE_VALIDATOR_PATH = "scripts/community_execution_authorization_v2.py"
DISPATCHER_PATH = "scripts/community_atomic_dispatcher.py"
RESOURCE_AMENDMENT_SCHEMA = "community_resource_amendment.schema.json"
RESOURCE_AMENDMENT_VALIDATOR_PATH = "scripts/community_resource_amendment.py"


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def sha256_file(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


def read_object(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected one JSON object: {path}")
    return value


def validate_schema(path: Path, schema: str, label: str) -> dict:
    errors = validate_json_file(path, repository_root() / "schemas" / schema)
    if errors:
        raise ValueError(f"invalid {label}: " + "; ".join(errors))
    return read_object(path)


def require_self_id(value: dict, field: str, label: str) -> None:
    unsigned = {key: item for key, item in value.items() if key != field}
    if value[field] != digest(unsigned):
        raise ValueError(f"{label} self identity changed")


def require_commit(commit: str) -> None:
    result = subprocess.run(
        ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
        cwd=repository_root(),
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise ValueError("runtime authorization commit is unavailable")


def git_blob_sha256(commit: str, relative_path: str) -> str:
    result = subprocess.run(
        ["git", "show", f"{commit}:{relative_path}"],
        cwd=repository_root(),
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise ValueError(f"runtime authorization blob is unavailable: {relative_path}")
    return hashlib.sha256(result.stdout).hexdigest()


def validate_validator_binding(binding: dict, *, resource_closure_required: bool) -> None:
    require_commit(binding["repository_commit"])
    paths = {
        "authorization_schema_sha256": f"schemas/{AUTHORIZATION_SCHEMA}",
        "profile_schema_sha256": f"schemas/{PROFILE_SCHEMA}",
        "treatment_schema_sha256": f"schemas/{TREATMENT_SCHEMA}",
        "validator_sha256": VALIDATOR_PATH,
        "base_authorization_schema_sha256": f"schemas/{BASE_SCHEMA}",
        "base_validator_sha256": BASE_VALIDATOR_PATH,
        "dispatcher_sha256": DISPATCHER_PATH,
    }
    if resource_closure_required:
        paths.update(
            {
                "resource_amendment_schema_sha256": (
                    f"schemas/{RESOURCE_AMENDMENT_SCHEMA}"
                ),
                "resource_amendment_validator_sha256": (
                    RESOURCE_AMENDMENT_VALIDATOR_PATH
                ),
            }
        )
    root = repository_root()
    for field, relative in paths.items():
        expected = git_blob_sha256(binding["repository_commit"], relative)
        if binding[field] != expected:
            raise ValueError(f"declared commit binding changed: {field}")
        if binding[field] != sha256_file(root / relative):
            raise ValueError(f"worktree binding changed: {field}")


def resource_execution_closure(request: dict, artifact_root: Path) -> dict | None:
    """Return the effective resource overlay required by the pre-GPU gate.

    A resource amendment is intentionally stored as a sparse overlay.  Runtime
    profiles may point at a materialized execution view below that overlay, but
    every amended logical path must resolve there with the effective bytes.
    """
    pre_identity = request.get("pre_gpu_gate")
    if not isinstance(pre_identity, dict):
        return None
    pre_path = validate_identity(artifact_root, pre_identity, "pre-GPU readiness")
    readiness = read_object(pre_path)
    candidates: list[tuple[Path, dict]] = []
    for label, identity in readiness.get("supplemental_audits", {}).items():
        if "resource_amendment" not in label:
            continue
        receipt_path = validate_identity(
            pre_path.parent, identity, f"resource amendment receipt {label}"
        )
        receipt = read_object(receipt_path)
        amendment_identity = receipt.get("amendment")
        if not isinstance(amendment_identity, dict):
            raise ValueError("resource amendment receipt has no amendment identity")
        amendment_path = validate_identity(
            receipt_path.parent, amendment_identity, "resource amendment"
        )
        candidates.append(
            (amendment_path, validate_amendment(amendment_path, artifact_root))
        )
    if not candidates:
        return None
    if len(candidates) != 1:
        raise ValueError("pre-GPU readiness must bind one effective resource amendment")
    amendment_path, _validation = candidates[0]
    amendment = read_object(amendment_path)
    effective_root = (artifact_root / amendment["effective_artifact_root"]).resolve()
    require_inside(effective_root, artifact_root, "effective resource root")
    if not effective_root.is_dir():
        raise ValueError("effective resource root is unavailable")
    logical_files: dict[str, str] = {}
    effective_relative = Path(amendment["effective_artifact_root"])
    for item in amendment["closure"]:
        effective = item["effective"]
        try:
            logical = Path(effective["path"]).relative_to(effective_relative)
        except ValueError as error:
            raise ValueError(
                f"effective closure path is outside resource overlay: {item['label']}"
            ) from error
        logical_files[logical.as_posix()] = effective["sha256"]
    return {
        "effective_root": effective_root,
        "logical_files": logical_files,
    }


def validate_materialized_resource_view(
    working_directory: Path, closure: dict | None, task_key: str
) -> None:
    if closure is None:
        return
    effective_root = closure["effective_root"]
    require_inside(
        working_directory, effective_root, f"{task_key} effective working directory"
    )
    for relative, expected_hash in closure["logical_files"].items():
        materialized = (working_directory / relative).resolve()
        require_inside(
            materialized, working_directory, f"{task_key} materialized resource file"
        )
        if not materialized.is_file() or sha256_file(materialized) != expected_hash:
            raise ValueError(
                f"{task_key} materialized resource closure changed: {relative}"
            )


def require_absolute(path_text: str, label: str) -> Path:
    path = Path(path_text)
    if not path.is_absolute():
        raise ValueError(f"{label} must be absolute")
    return path


def require_inside(path: Path, root: Path, label: str) -> None:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as error:
        raise ValueError(f"{label} escapes artifact root") from error


def validate_profile(
    profile_path: Path,
    artifact_root: Path,
    task: dict,
    task_key: str,
    arm: str,
    resource_closure: dict | None = None,
) -> dict:
    profile = validate_schema(profile_path, PROFILE_SCHEMA, f"{task_key} profile")
    require_self_id(profile, "execution_profile_id", f"{task_key} profile")
    if profile["task_id"] != task["task_id"]:
        raise ValueError(f"{task_key} profile binds a different stable task id")
    if profile["arm"] != arm:
        raise ValueError(f"{task_key} profile binds a different arm")
    treatment_path = validate_identity(
        artifact_root,
        profile["treatment_manifest"],
        f"{task_key} {arm} treatment manifest",
    )
    treatment = validate_schema(
        treatment_path, TREATMENT_SCHEMA, f"{task_key} {arm} treatment manifest"
    )
    require_self_id(treatment, "treatment_id", f"{task_key} {arm} treatment")
    if treatment["task_id"] != task["task_id"] or treatment["arm"] != arm:
        raise ValueError(f"{task_key} treatment binds a different task or arm")
    expected_realization = "BASELINE" if arm == "CONTROL" else "CHALLENGER"
    if treatment["realization"] != expected_realization:
        raise ValueError(f"{task_key} treatment realization differs from arm")
    if profile["treatment_id"] != treatment["treatment_id"]:
        raise ValueError(f"{task_key} profile treatment identity changed")
    if profile["implementation_identity"] != treatment["implementation_identity"]:
        raise ValueError(f"{task_key} profile implementation identity changed")
    source_root = require_absolute(
        treatment["source_root"], f"{task_key} {arm} source root"
    )
    if not source_root.is_dir():
        raise ValueError(f"{task_key} {arm} source root is unavailable")
    source_files = treatment["source_files"]
    if digest(source_files) != treatment["source_files_sha256"]:
        raise ValueError(f"{task_key} {arm} source file set digest changed")
    if treatment["implementation_identity"] != treatment["source_files_sha256"]:
        raise ValueError(f"{task_key} {arm} implementation is not source-derived")
    for index, source_identity in enumerate(source_files):
        source_path = validate_identity(
            source_root,
            source_identity,
            f"{task_key} {arm} source file {index}",
        )
        if not source_path.is_file():
            raise ValueError(f"{task_key} {arm} source file is unavailable")
    if profile["formal_gpu_uuids"] != task["formal_gpu_uuids"]:
        raise ValueError(f"{task_key} profile binds different formal GPU UUIDs")
    validate_identity(
        artifact_root, profile["runtime_lock"], f"{task_key} runtime lock"
    )
    if digest(profile["environment"]) != profile["environment_sha256"]:
        raise ValueError(f"{task_key} profile environment digest changed")
    for name, value in profile["environment"].items():
        if "\0" in name or "\0" in value:
            raise ValueError(f"{task_key} profile environment contains NUL")
    marker = treatment["runtime_marker"]
    if marker["value"] != treatment["implementation_identity"]:
        raise ValueError(f"{task_key} treatment runtime marker changed")
    if profile["environment"].get(marker["name"]) != marker["value"]:
        raise ValueError(f"{task_key} profile does not realize treatment marker")

    working_directory = require_absolute(
        profile["working_directory"], f"{task_key} working directory"
    )
    require_inside(working_directory, artifact_root, f"{task_key} working directory")
    if not working_directory.is_dir():
        raise ValueError(f"{task_key} working directory is unavailable")
    validate_materialized_resource_view(
        working_directory, resource_closure, task_key
    )

    command = require_absolute(
        profile["command_executable"]["path"], f"{task_key} command executable"
    )
    process = require_absolute(
        profile["process_executable"]["path"], f"{task_key} process executable"
    )
    if (
        not command.is_file()
        or sha256_file(command) != profile["command_executable"]["sha256"]
    ):
        raise ValueError(f"{task_key} command executable identity changed")
    if (
        not process.is_file()
        or sha256_file(process) != profile["process_executable"]["sha256"]
    ):
        raise ValueError(f"{task_key} process executable identity changed")
    if command.resolve(strict=True) != process.resolve(strict=True):
        raise ValueError(f"{task_key} command and process executables differ")
    command_parent = os.path.normcase(str(command.parent.resolve()))
    path_entries = [
        os.path.normcase(str(Path(item).resolve()))
        for item in profile["environment"]["PATH"].split(os.pathsep)
        if item
    ]
    if not path_entries or path_entries[0] != command_parent:
        raise ValueError(f"{task_key} command directory must lead sealed PATH")
    return profile


def runtime_entry(entry: dict, profile: dict) -> dict:
    if entry["resolved_argv"][0] != profile["sealed_argv0"]:
        raise ValueError("sealed argv0 differs from task execution profile")
    launch_argv = list(entry["resolved_argv"])
    return {
        "order_index": entry["order_index"],
        "task_id": entry["task_id"],
        "arm": entry["arm"],
        "execution_profile_id": profile["execution_profile_id"],
        "treatment_id": profile["treatment_id"],
        "implementation_identity": profile["implementation_identity"],
        "launch_argv": launch_argv,
        "launch_argv_sha256": digest(launch_argv),
        "working_directory": profile["working_directory"],
        "command_executable": profile["command_executable"],
        "process_executable": profile["process_executable"],
        "environment": profile["environment"],
        "environment_sha256": profile["environment_sha256"],
    }


def validate_authorization(
    authorization_path: Path,
    artifact_root: Path,
    *,
    require_live_store_host: bool = True,
) -> dict:
    artifact_root = artifact_root.resolve()
    authorization = validate_schema(
        authorization_path, AUTHORIZATION_SCHEMA, "runtime-bound authorization"
    )
    require_self_id(
        authorization, "combined_authorization_id", "runtime-bound authorization"
    )
    resource_closure_required = (
        authorization["schema_version"] == "community-combined-execution-authorization-v5"
    )
    validate_validator_binding(
        authorization["validator_binding"],
        resource_closure_required=resource_closure_required,
    )
    base_path = validate_identity(
        artifact_root,
        authorization["base_combined_authorization"],
        "base combined authorization",
    )
    base = validate_base_authorization(
        base_path, artifact_root, require_live_store_host=require_live_store_host
    )
    base_authorization = base["authorization"]
    if not same_identity(
        authorization["authorization_request"],
        base_authorization["authorization_request"],
    ):
        raise ValueError("runtime authorization binds a different request")
    for field in ("cycle_id", "suite_id", "formal_resource_id"):
        if authorization[field] != base_authorization[field]:
            raise ValueError(f"runtime authorization {field} differs from base")
    if authorization["execution_schedule"] != base["execution_schedule"]:
        raise ValueError("runtime authorization execution schedule differs from base")

    request = base["request"]
    resource_closure = resource_execution_closure(request, artifact_root)
    if resource_closure is not None and not resource_closure_required:
        raise ValueError(
            "resource-amended execution requires runtime authorization v5"
        )
    if set(authorization["task_arm_execution_profiles"]) != set(request["tasks"]):
        raise ValueError("runtime profile task set differs from request")
    profiles: dict[tuple[str, str], dict] = {}
    for task_key, task in request["tasks"].items():
        arm_profiles = authorization["task_arm_execution_profiles"][task_key]
        for arm in ("CONTROL", "COMMUNITY_AUGMENTED"):
            profile_path = validate_identity(
                artifact_root,
                arm_profiles[arm],
                f"{task_key} {arm} execution profile",
            )
            profiles[(task_key, arm)] = validate_profile(
                profile_path,
                artifact_root,
                task,
                task_key,
                arm,
                resource_closure,
            )
        control = profiles[(task_key, "CONTROL")]
        challenger = profiles[(task_key, "COMMUNITY_AUGMENTED")]
        if control["treatment_id"] == challenger["treatment_id"]:
            raise ValueError(f"{task_key} arms bind the same treatment identity")
        if control["implementation_identity"] == challenger["implementation_identity"]:
            raise ValueError(f"{task_key} arms bind the same implementation identity")
    expected_runtime_schedule = [
        runtime_entry(entry, profiles[(entry["task_id"], entry["arm"])])
        for entry in base["execution_schedule"]
    ]
    if authorization["runtime_schedule"] != expected_runtime_schedule:
        raise ValueError("runtime schedule differs from exact task profiles")

    expected_gates = {
        **base_authorization["gate_decisions"],
        "runtime_profiles_ready": True,
    }
    if authorization["gate_decisions"] != expected_gates:
        raise ValueError("runtime gate decisions differ from canonical validation")
    ready = base["ready_for_atomic_claim"]
    if authorization["ready_for_atomic_claim"] is not ready:
        raise ValueError(
            "runtime ready state differs from base P AND E AND A AND store"
        )
    if ready:
        if (
            authorization["state"] != "READY_FOR_ATOMIC_CLAIM"
            or authorization["remaining_blockers"]
        ):
            raise ValueError("ready runtime authorization must have no blockers")
    elif (
        authorization["state"] != "ATOMIC_CLAIM_BLOCKED"
        or not authorization["remaining_blockers"]
    ):
        raise ValueError("blocked runtime authorization requires blockers")

    effective_authorization = dict(authorization)
    effective_authorization["authorization_request"] = base_authorization[
        "authorization_request"
    ]
    return {
        **base,
        "authorization": effective_authorization,
        "base_authorization": base_authorization,
        "execution_schedule": base["execution_schedule"],
        "runtime_schedule": expected_runtime_schedule,
        "execution_profiles": profiles,
        "ready_for_atomic_claim": ready,
        "gpu_dispatch_authorized": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("authorization", type=Path)
    parser.add_argument("--artifact-root", required=True, type=Path)
    parser.add_argument("--offline-store-host-check", action="store_true")
    args = parser.parse_args()
    result = validate_authorization(
        args.authorization,
        args.artifact_root,
        require_live_store_host=not args.offline_store_host_check,
    )
    print(
        json.dumps(
            {
                "status": "PASS",
                "ready_for_atomic_claim": result["ready_for_atomic_claim"],
                "gpu_dispatch_authorized": result["gpu_dispatch_authorized"],
                "runtime_schedule_sha256": digest(result["runtime_schedule"]),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
