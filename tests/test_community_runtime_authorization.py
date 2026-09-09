from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import community_runtime_authorization as runtime_module  # noqa: E402
from community_claim_contracts import digest  # noqa: E402
from community_runtime_authorization import validate_authorization  # noqa: E402


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def identity(path: Path, root: Path) -> dict[str, str]:
    return {"path": path.relative_to(root).as_posix(), "sha256": sha256_file(path)}


def with_self_id(value: dict, field: str) -> dict:
    result = dict(value)
    result[field] = digest(value)
    return result


def validator_binding() -> dict[str, str]:
    paths = {
        "authorization_schema_sha256": ROOT
        / "schemas"
        / "community_runtime_bound_execution_authorization.schema.json",
        "profile_schema_sha256": ROOT
        / "schemas"
        / "community_task_execution_profile.schema.json",
        "validator_sha256": ROOT / "scripts" / "community_runtime_authorization.py",
        "base_authorization_schema_sha256": ROOT
        / "schemas"
        / "community_combined_execution_authorization_v2.schema.json",
        "base_validator_sha256": ROOT
        / "scripts"
        / "community_execution_authorization_v2.py",
        "dispatcher_sha256": ROOT / "scripts" / "community_atomic_dispatcher.py",
    }
    return {
        "repository_commit": "1" * 40,
        **{key: sha256_file(path) for key, path in paths.items()},
    }


def build_bundle(root: Path, *, ready: bool = True) -> tuple[Path, dict]:
    request_path = root / "request.json"
    base_path = root / "base.json"
    runtime_lock_path = root / "runtime-lock.json"
    work = root / "work"
    work.mkdir()
    write_json(request_path, {"request": "bound"})
    write_json(base_path, {"base": "bound"})
    write_json(runtime_lock_path, {"runtime": "bound"})
    executable = Path(sys.executable).resolve()
    environment = {
        "PATH": str(executable.parent) + os.pathsep + os.environ.get("PATH", ""),
        "HOME": str(root),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "CUDA_VISIBLE_DEVICES": "0",
        "NVIDIA_VISIBLE_DEVICES": "void",
        "XDG_CACHE_HOME": str(root / "cache"),
    }
    profile = with_self_id(
        {
            "schema_version": "community-task-execution-profile-v1",
            "generated_at": "2026-09-10T00:00:00Z",
            "claim_boundary": "EXACT_TASK_RUNTIME_IDENTITY_NOT_EXECUTION_AUTHORIZATION",
            "task_id": "stable-task-a",
            "formal_gpu_uuids": ["GPU-11111111-1111-1111-1111-111111111111"],
            "runtime_lock": identity(runtime_lock_path, root),
            "working_directory": str(work.resolve()),
            "sealed_argv0": "python3",
            "command_executable": {
                "path": str(executable),
                "sha256": sha256_file(executable),
            },
            "process_executable": {
                "path": str(executable),
                "sha256": sha256_file(executable),
            },
            "environment": environment,
            "environment_sha256": digest(environment),
            "hidden_oracle_exposed": False,
        },
        "execution_profile_id",
    )
    profile_path = root / "profile.json"
    write_json(profile_path, profile)
    entry = {
        "order_index": 1,
        "task_id": "task-a",
        "repeat_index": 1,
        "arm": "CONTROL",
        "schedule_key": "2" * 64,
        "sealed_argv_sha256": "3" * 64,
        "resolved_argv": ["python3", "runner.py", "--timeout-seconds", "10"],
        "resolved_argv_sha256": digest(
            ["python3", "runner.py", "--timeout-seconds", "10"]
        ),
        "formal_gpu_uuids": ["GPU-11111111-1111-1111-1111-111111111111"],
    }
    base_authorization = {
        "combined_authorization_id": "4" * 64,
        "authorization_request": identity(request_path, root),
        "cycle_id": "cycle-1",
        "suite_id": "suite-1",
        "formal_resource_id": "resource-1",
        "gate_decisions": {
            "pre_gpu_ready": ready,
            "execution_contract_ready": ready,
            "semantic_approval_ready": ready,
            "claim_store_deployment_ready": ready,
        },
    }
    base_bundle = {
        "authorization": base_authorization,
        "request": {
            "request_id": "request-1",
            "cycle_id": "cycle-1",
            "tasks": {
                "task-a": {
                    "task_id": "stable-task-a",
                    "formal_gpu_uuids": entry["formal_gpu_uuids"],
                }
            },
        },
        "approval": {},
        "deployment": {},
        "suite": {},
        "execution_schedule": [entry],
        "authorization_schedule_sha256": "5" * 64,
        "execution_schedule_sha256": digest([entry]),
        "ready_for_atomic_claim": ready,
        "gpu_dispatch_authorized": False,
    }
    runtime_row = runtime_module.runtime_entry(entry, profile)
    authorization = with_self_id(
        {
            "schema_version": "community-combined-execution-authorization-v3",
            "generated_at": "2026-09-10T00:00:00Z",
            "claim_boundary": (
                "P_AND_E_AND_A_AND_STORE_AND_RUNTIME_RECOMPUTED_READY_FOR_ATOMIC_CLAIM_NOT_DISPATCH"
            ),
            "validator_binding": validator_binding(),
            "base_combined_authorization": identity(base_path, root),
            "authorization_request": identity(request_path, root),
            "cycle_id": "cycle-1",
            "suite_id": "suite-1",
            "formal_resource_id": "resource-1",
            "task_execution_profiles": {"task-a": identity(profile_path, root)},
            "execution_schedule": [entry],
            "runtime_schedule": [runtime_row],
            "gate_decisions": {
                **base_authorization["gate_decisions"],
                "runtime_profiles_ready": True,
            },
            "state": "READY_FOR_ATOMIC_CLAIM" if ready else "ATOMIC_CLAIM_BLOCKED",
            "ready_for_atomic_claim": ready,
            "gpu_dispatch_authorized": False,
            "remaining_blockers": [] if ready else ["base authorization blocked"],
            "hidden_oracle_exposed": False,
        },
        "combined_authorization_id",
    )
    authorization_path = root / "runtime-authorization.json"
    write_json(authorization_path, authorization)
    return authorization_path, {
        "authorization": authorization,
        "profile": profile,
        "profile_path": profile_path,
        "base_bundle": base_bundle,
    }


@pytest.fixture(autouse=True)
def canonical_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runtime_module, "require_commit", lambda commit: None)
    monkeypatch.setattr(
        runtime_module,
        "git_blob_sha256",
        lambda commit, relative: sha256_file(ROOT / relative),
    )

    def base(path: Path, root: Path, *, require_live_store_host: bool) -> dict:
        del path, require_live_store_host
        return CURRENT_BASE[root]

    monkeypatch.setattr(runtime_module, "validate_base_authorization", base)


CURRENT_BASE: dict[Path, dict] = {}


@pytest.mark.parametrize("ready", [True, False])
def test_runtime_authorization_binds_exact_environment_and_executable(
    ready: bool,
) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary).resolve()
        path, bundle = build_bundle(root, ready=ready)
        CURRENT_BASE[root] = bundle["base_bundle"]
        result = validate_authorization(path, root, require_live_store_host=False)
        assert result["ready_for_atomic_claim"] is ready
        assert (
            result["authorization"]["combined_authorization_id"]
            != result["base_authorization"]["combined_authorization_id"]
        )
        assert result["runtime_schedule"][0]["environment_sha256"] == digest(
            bundle["profile"]["environment"]
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("environment", "environment digest changed"),
        ("task", "different stable task id"),
        ("gpu", "different formal GPU UUIDs"),
        ("executable", "command executable identity changed"),
    ],
)
def test_runtime_authorization_rejects_profile_drift(
    mutation: str, message: str
) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary).resolve()
        path, bundle = build_bundle(root)
        CURRENT_BASE[root] = bundle["base_bundle"]
        profile = copy.deepcopy(bundle["profile"])
        if mutation == "environment":
            profile["environment"]["PATH"] += os.pathsep + str(root / "foreign")
        elif mutation == "task":
            profile["task_id"] = "foreign-task"
        elif mutation == "gpu":
            profile["formal_gpu_uuids"] = ["GPU-22222222-2222-2222-2222-222222222222"]
        else:
            profile["command_executable"]["sha256"] = "0" * 64
        profile = with_self_id(
            {
                key: value
                for key, value in profile.items()
                if key != "execution_profile_id"
            },
            "execution_profile_id",
        )
        write_json(bundle["profile_path"], profile)
        authorization = bundle["authorization"]
        authorization["task_execution_profiles"]["task-a"] = identity(
            bundle["profile_path"], root
        )
        authorization = with_self_id(
            {
                key: value
                for key, value in authorization.items()
                if key != "combined_authorization_id"
            },
            "combined_authorization_id",
        )
        write_json(path, authorization)
        with pytest.raises(ValueError, match=message):
            validate_authorization(path, root, require_live_store_host=False)


def test_runtime_authorization_rejects_schedule_profile_substitution() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary).resolve()
        path, bundle = build_bundle(root)
        CURRENT_BASE[root] = bundle["base_bundle"]
        authorization = bundle["authorization"]
        authorization["runtime_schedule"][0]["working_directory"] = str(
            root / "foreign"
        )
        authorization = with_self_id(
            {
                key: value
                for key, value in authorization.items()
                if key != "combined_authorization_id"
            },
            "combined_authorization_id",
        )
        write_json(path, authorization)
        with pytest.raises(ValueError, match="runtime schedule differs"):
            validate_authorization(path, root, require_live_store_host=False)
