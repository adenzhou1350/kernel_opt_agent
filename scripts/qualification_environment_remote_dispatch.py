#!/usr/bin/env python3
"""Transport one approved CPU-only materialization to an attested worker."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import subprocess
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Callable

from qualification_environment_materialization import (
    identity,
    parse_time,
    read_object,
    sha256_file,
    validate_approval,
    validate_identity,
)
from schema_utils import validate_instance


PLAN_SCHEMA = "qualification_environment_remote_transport_plan.schema.json"
AUTHORIZATION_SCHEMA = (
    "qualification_environment_remote_transport_authorization.schema.json"
)
RECEIPT_SCHEMA = "qualification_environment_remote_transport_receipt.schema.json"
WORKER_CLAIM_SCHEMA = "qualification_environment_materialization_claim.schema.json"
WORKER_RECEIPT_SCHEMA = (
    "qualification_environment_materialization_dispatch_receipt_v2.schema.json"
)
AUTHORIZATION_VERSION = "qualification-environment-remote-transport-authorization-v1"
APPROVAL_VERSION = "qualification-environment-materialization-approval-v2"
PLAN_VERSION = "qualification-environment-remote-transport-plan-v1"
CLAIM_BOUNDARY = (
    "REMOTE_TRANSPORT_ONLY_REQUIRES_SEPARATE_WORKER_TERMINAL_AND_ENVIRONMENT_VALIDATION"
)
RECEIPT_BOUNDARY = (
    "REMOTE_PROCESS_TRANSPORT_EVIDENCE_ONLY_NOT_ENVIRONMENT_CORRECTNESS_"
    "PERFORMANCE_GPU_WORKLOAD_OR_BROKER_AUTHORIZATION"
)
RUNTIME_FILES = (
    "scripts/qualification_environment_materialization_dispatch.py",
    "scripts/qualification_environment_materialization.py",
    "scripts/schema_utils.py",
    "schemas/qualification_environment_materialization_approval_v2.schema.json",
    "schemas/qualification_environment_materialization_claim.schema.json",
    "schemas/qualification_environment_materialization_dispatch_receipt_v2.schema.json",
    "schemas/qualification_environment_request.schema.json",
    "schemas/resource_broker_job.schema.json",
)


class RemoteDispatchError(RuntimeError):
    """A remote transport invariant failed after validation or claim."""


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def self_identified(value: dict, field: str) -> dict:
    result = dict(value)
    result[field] = canonical_sha256(value)
    return result


def worker_runtime_sha256() -> str:
    return canonical_sha256(
        {
            relative: sha256_file(repository_root() / relative)
            for relative in RUNTIME_FILES
        }
    )


def validate_generated(value: dict, schema_name: str, label: str) -> None:
    schema = read_object(repository_root() / "schemas" / schema_name)
    errors = validate_instance(value, schema)
    if errors:
        raise ValueError(f"invalid {label}: " + "; ".join(errors))


def validate_json(path: Path, schema_name: str, label: str) -> dict:
    value = read_object(path)
    validate_generated(value, schema_name, label)
    return value


def atomic_publish_json(path: Path, value: dict) -> None:
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
        os.link(temporary_name, path)
    finally:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass


def external_path(value: dict, label: str) -> Path:
    path = Path(value["path"]).resolve(strict=True)
    if not path.is_file() or sha256_file(path) != value["sha256"]:
        raise ValueError(f"{label} identity differs")
    return path


def posix_join(root: str, relative: str) -> str:
    root_path = PurePosixPath(root)
    if not root_path.is_absolute() or ".." in root_path.parts:
        raise ValueError(f"remote artifact root is unsafe: {root}")
    relative_path = PurePosixPath(relative)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise ValueError(f"remote relative path is unsafe: {relative}")
    joined = root_path / relative_path
    return joined.as_posix()


def required_task_paths(plan: dict, artifact_root: Path) -> set[str]:
    required: set[str] = set()

    def visit(value: object) -> None:
        if isinstance(value, dict):
            if set(value) == {"path", "sha256"} and isinstance(value.get("path"), str):
                try:
                    path = (artifact_root / value["path"]).resolve()
                    path.relative_to(artifact_root)
                except (ValueError, OSError):
                    pass
                else:
                    if path.is_file():
                        required.add(path.relative_to(artifact_root).as_posix())
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(plan)
    for step in plan.get("materialization_steps", []):
        for token in step.get("argv") or []:
            if not isinstance(token, str) or not token.startswith("/"):
                continue
            remote_root = plan.get("paths", {}).get("artifact_root")
            if not isinstance(remote_root, str):
                continue
            try:
                relative = PurePosixPath(token).relative_to(PurePosixPath(remote_root))
            except ValueError:
                continue
            local_path = (artifact_root / Path(*relative.parts)).resolve()
            if local_path.is_file():
                required.add(local_path.relative_to(artifact_root).as_posix())
    return required


def validate_transport_bundle(
    *,
    artifact_root: Path,
    approval_path: Path,
    transport_plan_path: Path,
    now: datetime,
) -> tuple[dict, dict]:
    artifact_root = artifact_root.resolve(strict=True)
    approval_path = approval_path.resolve(strict=True)
    transport_plan_path = transport_plan_path.resolve(strict=True)
    approval = read_object(approval_path)
    if approval.get("schema_version") != APPROVAL_VERSION:
        raise ValueError("remote transport requires a dispatcher-bound v2 approval")
    approval_result = validate_approval(approval_path, artifact_root, now=now)
    if not approval_result["dispatcher_bound"] or not approval_result["single_use"]:
        raise ValueError("materialization approval is not dispatcher-bound single-use")
    plan = validate_json(transport_plan_path, PLAN_SCHEMA, "remote transport plan")
    if plan["schema_version"] != PLAN_VERSION:
        raise ValueError("unsupported remote transport plan version")

    materialization_plan_path = validate_identity(
        artifact_root, approval["materialization_plan"], "materialization plan"
    )
    materialization_plan = read_object(materialization_plan_path)
    runtime_worker = materialization_plan.get("runtime_worker")
    if not isinstance(runtime_worker, dict):
        raise ValueError("remote transport requires an attested worker plan")
    worker = plan["worker"]
    if runtime_worker.get("worker_id") != worker["worker_id"]:
        raise ValueError("transport worker differs from materialization plan")
    if runtime_worker.get("host_id") != worker["host_id"]:
        raise ValueError("transport host differs from materialization plan")
    planned_root = materialization_plan.get("paths", {}).get("artifact_root")
    if planned_root != plan["remote_artifact_root"]:
        raise ValueError("transport artifact root differs from materialization plan")
    posix_join(plan["remote_artifact_root"], ".")
    python_path = PurePosixPath(worker["python"])
    if not python_path.is_absolute() or ".." in python_path.parts:
        raise ValueError("worker Python path is unsafe")

    task_files = {item["path"]: item for item in plan["task_files"]}
    if len(task_files) != len(plan["task_files"]):
        raise ValueError("remote transport task file paths must be unique")
    for label, approved_identity in (
        ("materialization plan", approval["materialization_plan"]),
        ("environment request", approval["environment_request"]),
        ("resource job", approval["resource_job"]),
    ):
        if task_files.get(approved_identity["path"]) != approved_identity:
            raise ValueError(f"remote transport omits approved {label}")
    required = required_task_paths(materialization_plan, artifact_root)
    missing = sorted(required - set(task_files))
    if missing:
        raise ValueError(
            "remote transport omits bound task files: " + ", ".join(missing)
        )
    for item in plan["task_files"]:
        validate_identity(artifact_root, item, "remote transport task file")

    for label in ("ssh", "scp", "known_hosts", "identity_file"):
        external_path(plan["controller"][label], f"controller {label}")
    dispatcher = repository_root() / RUNTIME_FILES[0]
    if approval["dispatcher_sha256"] != sha256_file(dispatcher):
        raise ValueError("materialization approval binds another worker dispatcher")
    if now + timedelta(seconds=plan["budget"]["total_wall_seconds"]) >= parse_time(
        approval["expires_at"]
    ):
        raise ValueError("materialization approval expires before remote deadline")
    return approval, plan


def issue_authorization(
    *,
    artifact_root: Path,
    approval_path: Path,
    transport_plan_path: Path,
    supervisor_id: str,
    authorization_id: str,
    issued_at: datetime,
    expires_at: datetime,
) -> dict:
    _, plan = validate_transport_bundle(
        artifact_root=artifact_root,
        approval_path=approval_path,
        transport_plan_path=transport_plan_path,
        now=issued_at,
    )
    if expires_at <= issued_at:
        raise ValueError("remote transport authorization expiry must follow issuance")
    if (
        issued_at + timedelta(seconds=plan["budget"]["total_wall_seconds"])
        >= expires_at
    ):
        raise ValueError("remote transport authorization expires before deadline")
    result = {
        "schema_version": AUTHORIZATION_VERSION,
        "authorization_id": authorization_id,
        "issued_at": timestamp(issued_at),
        "expires_at": timestamp(expires_at),
        "issued_by": {"role": "GLOBAL_SUPERVISOR", "supervisor_id": supervisor_id},
        "action": "REMOTE_CPU_ONLY_ENVIRONMENT_MATERIALIZATION_TRANSPORT",
        "materialization_approval": identity(approval_path, artifact_root),
        "transport_plan": identity(transport_plan_path, artifact_root),
        "remote_dispatcher_sha256": sha256_file(Path(__file__).resolve()),
        "worker_runtime_sha256": worker_runtime_sha256(),
        "constraints": {
            "gpu": False,
            "workload": False,
            "broker": False,
            "service_mutation": False,
            "retry_after_claim": False,
        },
        "decision": "APPROVED",
        "single_use": True,
        "claim_boundary": CLAIM_BOUNDARY,
    }
    validate_generated(result, AUTHORIZATION_SCHEMA, "remote authorization")
    return result


def openssh_options(plan: dict, *, scp: bool) -> list[str]:
    controller = plan["controller"]
    worker = plan["worker"]
    return [
        "-F",
        os.devnull,
        "-o",
        "BatchMode=yes",
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "IdentityAgent=none",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        f"UserKnownHostsFile={controller['known_hosts']['path']}",
        "-o",
        f"GlobalKnownHostsFile={os.devnull}",
        "-o",
        "ForwardAgent=no",
        "-o",
        "ClearAllForwardings=yes",
        "-o",
        "PermitLocalCommand=no",
        "-o",
        "ProxyCommand=none",
        "-o",
        "ProxyJump=none",
        "-o",
        f"ConnectTimeout={plan['budget']['connect_timeout_seconds']}",
        "-i",
        controller["identity_file"]["path"],
        "-P" if scp else "-p",
        str(worker["port"]),
    ]


def command_record(stage: str, completed: subprocess.CompletedProcess[bytes]) -> dict:
    return {
        "stage": stage,
        "exit_code": completed.returncode,
        "stdout_sha256": hashlib.sha256(completed.stdout).hexdigest(),
        "stderr_sha256": hashlib.sha256(completed.stderr).hexdigest(),
    }


def run_checked(
    runner: Callable[..., subprocess.CompletedProcess[bytes]],
    argv: list[str],
    *,
    timeout: int,
) -> subprocess.CompletedProcess[bytes]:
    completed = runner(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=timeout,
    )
    if completed.returncode:
        raise RemoteDispatchError(f"command exited {completed.returncode}")
    return completed


def remote_shell(
    plan: dict,
    target: str,
    command: str,
    runner: Callable[..., subprocess.CompletedProcess[bytes]],
    *,
    timeout: int,
) -> subprocess.CompletedProcess[bytes]:
    return run_checked(
        runner,
        [
            plan["controller"]["ssh"]["path"],
            *openssh_options(plan, scp=False),
            target,
            command,
        ],
        timeout=timeout,
    )


def stage_file(
    *,
    plan: dict,
    target: str,
    source: Path,
    destination: str,
    expected_sha256: str,
    nonce: str,
    runner: Callable[..., subprocess.CompletedProcess[bytes]],
) -> list[dict]:
    transfer_timeout = plan["budget"]["transfer_timeout_seconds"]
    remote_root = plan["remote_artifact_root"]
    quoted_destination = shlex.quote(destination)
    canonical_checks = " && ".join(
        (
            f'test "$(realpath -m {shlex.quote(remote_root)})" = {shlex.quote(remote_root)}',
            f'test "$(realpath -m {quoted_destination})" = {quoted_destination}',
        )
    )
    inspect = remote_shell(
        plan,
        target,
        f"{canonical_checks} && if test -e {quoted_destination}; "
        f"then test -f {quoted_destination} && test ! -L {quoted_destination} "
        f"&& sha256sum {quoted_destination}; else printf 'ABSENT\\n'; fi",
        runner,
        timeout=transfer_timeout,
    )
    records = [command_record("REMOTE_IDENTITY_PREFLIGHT", inspect)]
    text = inspect.stdout.decode("utf-8", errors="strict").strip()
    if text != "ABSENT":
        if text.split(maxsplit=1)[0] != expected_sha256:
            raise RemoteDispatchError(
                f"remote destination identity differs: {destination}"
            )
        return records

    parent = str(PurePosixPath(destination).parent)
    temporary = f"{destination}.{nonce}.tmp"
    mkdir = remote_shell(
        plan,
        target,
        f"mkdir -p {shlex.quote(parent)}",
        runner,
        timeout=transfer_timeout,
    )
    records.append(command_record("REMOTE_PARENT_CREATE", mkdir))
    upload = run_checked(
        runner,
        [
            plan["controller"]["scp"]["path"],
            *openssh_options(plan, scp=True),
            str(source),
            f"{target}:{temporary}",
        ],
        timeout=transfer_timeout,
    )
    records.append(command_record("UPLOAD", upload))
    publish = remote_shell(
        plan,
        target,
        " && ".join(
            (
                canonical_checks,
                f"test \"$(sha256sum {shlex.quote(temporary)} | cut -d' ' -f1)\" = {expected_sha256}",
                f"ln {shlex.quote(temporary)} {quoted_destination}",
                f"rm {shlex.quote(temporary)}",
            )
        ),
        runner,
        timeout=transfer_timeout,
    )
    records.append(command_record("REMOTE_ATOMIC_PUBLISH", publish))
    return records


def preclaim_remote_readiness(
    *,
    plan: dict,
    target: str,
    runner: Callable[..., subprocess.CompletedProcess[bytes]],
) -> None:
    remote_root = shlex.quote(plan["remote_artifact_root"])
    python = shlex.quote(plan["worker"]["python"])
    command = (
        "command -v realpath sha256sum cut mkdir ln rm >/dev/null "
        f"&& test -x {python} "
        f'&& test "$(realpath -m {remote_root})" = {remote_root}'
    )
    remote_shell(
        plan,
        target,
        command,
        runner,
        timeout=plan["budget"]["connect_timeout_seconds"],
    )


def dispatch(
    *,
    artifact_root: Path,
    authorization_path: Path,
    expected_authorization_sha256: str,
    now: datetime | None = None,
    runner: Callable[..., subprocess.CompletedProcess[bytes]] = subprocess.run,
) -> dict:
    artifact_root = artifact_root.resolve(strict=True)
    authorization_path = authorization_path.resolve(strict=True)
    authorization_identity = identity(authorization_path, artifact_root)
    if authorization_identity["sha256"] != expected_authorization_sha256:
        raise ValueError("remote authorization hash differs from controller input")
    authorization = validate_json(
        authorization_path, AUTHORIZATION_SCHEMA, "remote transport authorization"
    )
    if authorization["schema_version"] != AUTHORIZATION_VERSION:
        raise ValueError("unsupported remote transport authorization")
    current_sha256 = sha256_file(Path(__file__).resolve())
    if authorization["remote_dispatcher_sha256"] != current_sha256:
        raise ValueError("remote authorization binds another controller dispatcher")
    if authorization["worker_runtime_sha256"] != worker_runtime_sha256():
        raise ValueError("remote authorization binds another worker runtime")
    claimed_at = (now or datetime.now(UTC)).astimezone(UTC)
    if not (
        parse_time(authorization["issued_at"])
        <= claimed_at
        < parse_time(authorization["expires_at"])
    ):
        raise ValueError("remote transport authorization is not currently valid")
    approval_path = validate_identity(
        artifact_root,
        authorization["materialization_approval"],
        "materialization approval",
    )
    transport_plan_path = validate_identity(
        artifact_root, authorization["transport_plan"], "remote transport plan"
    )
    approval, plan = validate_transport_bundle(
        artifact_root=artifact_root,
        approval_path=approval_path,
        transport_plan_path=transport_plan_path,
        now=claimed_at,
    )
    deadline = claimed_at + timedelta(seconds=plan["budget"]["total_wall_seconds"])
    if deadline >= parse_time(authorization["expires_at"]):
        raise ValueError("remote transport authorization expires before deadline")

    worker = plan["worker"]
    target = f"{worker['user']}@{worker['address']}"
    # Connectivity and the small worker-side transport tool set are read-only
    # prerequisites.  Probe them before consuming the single-use claim so an
    # offline worker does not force another versioned authorization.
    preclaim_remote_readiness(plan=plan, target=target, runner=runner)

    claims = artifact_root / ".kernel-opt" / "remote-materialization-claims"
    claim_path = claims / f"{expected_authorization_sha256}.claim.json"
    receipt_path = claims / f"{expected_authorization_sha256}.receipt.json"
    if receipt_path.exists():
        raise FileExistsError("remote transport authorization already has a receipt")
    claim = self_identified(
        {
            "schema_version": "qualification-environment-remote-transport-claim-v1",
            "claimed_at": timestamp(claimed_at),
            "authorization": authorization_identity,
            "transport_plan": identity(transport_plan_path, artifact_root),
            "remote_dispatcher_sha256": current_sha256,
            "single_use": True,
            "claim_boundary": CLAIM_BOUNDARY,
        },
        "claim_id",
    )
    atomic_publish_json(claim_path, claim)

    started = time.monotonic()
    commands: list[dict] = []
    worker_launched = False
    worker_terminal: dict | None = None
    error_text: str | None = None
    remote_root = plan["remote_artifact_root"]
    nonce = expected_authorization_sha256[:16]
    try:
        transfers: list[tuple[Path, str, str]] = []
        for item in plan["task_files"]:
            source = validate_identity(artifact_root, item, "remote task file")
            transfers.append(
                (source, posix_join(remote_root, item["path"]), item["sha256"])
            )
        transfers.append(
            (
                approval_path,
                posix_join(
                    remote_root, authorization["materialization_approval"]["path"]
                ),
                authorization["materialization_approval"]["sha256"],
            )
        )
        runtime_root = posix_join(
            remote_root, f".kernel-opt/runtime/{authorization['worker_runtime_sha256']}"
        )
        for relative in RUNTIME_FILES:
            source = repository_root() / relative
            transfers.append(
                (source, posix_join(runtime_root, relative), sha256_file(source))
            )
        destinations: dict[str, str] = {}
        for source, destination, expected_sha256 in transfers:
            prior = destinations.get(destination)
            if prior is not None and prior != expected_sha256:
                raise ValueError(f"two source identities target {destination}")
            if prior is not None:
                continue
            destinations[destination] = expected_sha256
            commands.extend(
                stage_file(
                    plan=plan,
                    target=target,
                    source=source,
                    destination=destination,
                    expected_sha256=expected_sha256,
                    nonce=nonce,
                    runner=runner,
                )
            )

        runtime_dispatcher = posix_join(
            runtime_root,
            "scripts/qualification_environment_materialization_dispatch.py",
        )
        remote_approval = posix_join(
            remote_root, authorization["materialization_approval"]["path"]
        )
        remote_argv = [
            worker["python"],
            runtime_dispatcher,
            "--artifact-root",
            remote_root,
            "--approval",
            remote_approval,
            "--approval-sha256",
            authorization["materialization_approval"]["sha256"],
        ]
        worker_launched = True
        remaining = max(1, int((deadline - datetime.now(UTC)).total_seconds()))
        executed = runner(
            [
                plan["controller"]["ssh"]["path"],
                *openssh_options(plan, scp=False),
                target,
                shlex.join(remote_argv),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=remaining,
        )
        commands.append(command_record("WORKER_DISPATCH", executed))
        remote_receipt_relative = (
            ".kernel-opt/materialization-claims/"
            f"{authorization['materialization_approval']['sha256']}.receipt.json"
        )
        remote_claim_relative = (
            ".kernel-opt/materialization-claims/"
            f"{authorization['materialization_approval']['sha256']}.claim.json"
        )
        retrieved_root = claims / expected_authorization_sha256
        retrieved_root.mkdir(parents=True, exist_ok=False)
        retrieved_receipt = retrieved_root / "worker-receipt.json"
        retrieved_claim = retrieved_root / "worker-claim.json"
        for remote_relative, local, stage in (
            (remote_claim_relative, retrieved_claim, "RETRIEVE_WORKER_CLAIM"),
            (remote_receipt_relative, retrieved_receipt, "RETRIEVE_WORKER_RECEIPT"),
        ):
            retrieved = run_checked(
                runner,
                [
                    plan["controller"]["scp"]["path"],
                    *openssh_options(plan, scp=True),
                    f"{target}:{posix_join(remote_root, remote_relative)}",
                    str(local),
                ],
                timeout=plan["budget"]["transfer_timeout_seconds"],
            )
            commands.append(command_record(stage, retrieved))
        worker_claim = validate_json(
            retrieved_claim, WORKER_CLAIM_SCHEMA, "worker materialization claim"
        )
        expected_remote_approval = {
            "path": authorization["materialization_approval"]["path"],
            "sha256": authorization["materialization_approval"]["sha256"],
        }
        if worker_claim["approval"] != expected_remote_approval:
            raise RemoteDispatchError("worker claim binds another approval")
        worker_terminal = validate_json(
            retrieved_receipt, WORKER_RECEIPT_SCHEMA, "worker terminal receipt"
        )
        expected_claim = {
            "path": remote_claim_relative,
            "sha256": sha256_file(retrieved_claim),
        }
        if worker_terminal["claim"] != expected_claim:
            raise RemoteDispatchError("worker terminal receipt binds another claim")
    except BaseException as error:
        error_text = f"{type(error).__name__}: {error}"

    state = (
        "WORKER_TERMINAL_RETRIEVED"
        if worker_terminal is not None
        else (
            "AMBIGUOUS_POSTLAUNCH_CONSUMED"
            if worker_launched
            else "FAILED_PRELAUNCH_CONSUMED"
        )
    )
    worker_receipt_identity = None
    if worker_terminal is not None:
        local = claims / expected_authorization_sha256 / "worker-receipt.json"
        worker_receipt_identity = identity(local, artifact_root)
    completed_at = datetime.now(UTC)
    receipt = self_identified(
        {
            "schema_version": "qualification-environment-remote-transport-receipt-v1",
            "started_at": timestamp(claimed_at),
            "completed_at": timestamp(completed_at),
            "duration_seconds": max(0.0, time.monotonic() - started),
            "authorization": authorization_identity,
            "transport_plan": identity(transport_plan_path, artifact_root),
            "worker_runtime_sha256": authorization["worker_runtime_sha256"],
            "worker": {
                "worker_id": worker["worker_id"],
                "host_id": worker["host_id"],
                "address": worker["address"],
                "port": worker["port"],
            },
            "state": state,
            "worker_terminal_receipt": worker_receipt_identity,
            "commands": commands,
            "error": error_text,
            "gpu_authorized": False,
            "workload_authorized": False,
            "broker_mutated": False,
            "retry_authorized": False,
            "claim_boundary": RECEIPT_BOUNDARY,
        },
        "receipt_id",
    )
    validate_generated(receipt, RECEIPT_SCHEMA, "remote transport receipt")
    atomic_publish_json(receipt_path, receipt)
    return {**receipt, "receipt_path": receipt_path.as_posix()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--issue", action="store_true")
    mode.add_argument("--authorization", type=Path)
    parser.add_argument("--artifact-root", required=True, type=Path)
    parser.add_argument("--approval", type=Path)
    parser.add_argument("--transport-plan", type=Path)
    parser.add_argument("--supervisor-id")
    parser.add_argument("--authorization-id")
    parser.add_argument("--ttl-seconds", type=int, default=3600)
    parser.add_argument("--authorization-sha256")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    artifact_root = args.artifact_root.resolve()
    if args.issue:
        required = {
            "--approval": args.approval,
            "--transport-plan": args.transport_plan,
            "--supervisor-id": args.supervisor_id,
            "--authorization-id": args.authorization_id,
            "--output": args.output,
        }
        missing = [label for label, value in required.items() if value is None]
        if missing:
            parser.error("--issue requires " + ", ".join(missing))
        issued_at = datetime.now(UTC)
        authorization = issue_authorization(
            artifact_root=artifact_root,
            approval_path=args.approval.resolve(),
            transport_plan_path=args.transport_plan.resolve(),
            supervisor_id=args.supervisor_id,
            authorization_id=args.authorization_id,
            issued_at=issued_at,
            expires_at=issued_at + timedelta(seconds=args.ttl_seconds),
        )
        atomic_publish_json(args.output.resolve(), authorization)
        result = {
            "status": "PASS",
            "authorization": identity(args.output.resolve(), artifact_root),
            "gpu_authorized": False,
            "workload_authorized": False,
        }
    else:
        if args.authorization_sha256 is None:
            parser.error("dispatch requires --authorization-sha256")
        result = dispatch(
            artifact_root=artifact_root,
            authorization_path=args.authorization.resolve(),
            expected_authorization_sha256=args.authorization_sha256,
        )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("state") == "WORKER_TERMINAL_RETRIEVED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
