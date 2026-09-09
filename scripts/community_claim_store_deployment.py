#!/usr/bin/env python3
"""Validate one host-bound atomic claim-store deployment."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import subprocess
from pathlib import Path

from community_claim_contracts import digest, parse_timestamp
from community_knowledge import read_object, sha256_file
from schema_utils import validate_json_file

EPOCH_SCHEMA = "community_claim_store_epoch.schema.json"
DEPLOYMENT_SCHEMA = "community_claim_store_deployment.schema.json"
VALIDATOR_PATH = "scripts/community_claim_store_deployment.py"
CLAIM_CONTRACTS_PATH = "scripts/community_claim_contracts.py"
ATOMIC_CLAIM_PATH = "scripts/community_atomic_claim.py"


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def resolve_inside(base: Path, relative: str) -> Path:
    base = base.resolve()
    path = (base / relative).resolve()
    try:
        path.relative_to(base)
    except ValueError as error:
        raise ValueError(f"identity path escapes artifact root: {relative}") from error
    return path


def validate_identity(base: Path, identity: dict, label: str) -> Path:
    path = resolve_inside(base, identity["path"])
    if not path.is_file():
        raise FileNotFoundError(f"{label} is missing: {path}")
    if sha256_file(path) != identity["sha256"]:
        raise ValueError(f"{label} hash changed: {identity['path']}")
    return path


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
        raise ValueError("claim-store deployment validator commit is unavailable")


def git_blob_sha256(commit: str, relative_path: str) -> str:
    result = subprocess.run(
        ["git", "show", f"{commit}:{relative_path}"],
        cwd=repository_root(),
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise ValueError(f"claim-store deployment blob is unavailable: {relative_path}")
    return hashlib.sha256(result.stdout).hexdigest()


def validate_validator_binding(binding: dict) -> None:
    require_commit(binding["repository_commit"])
    paths = {
        "epoch_schema_sha256": f"schemas/{EPOCH_SCHEMA}",
        "deployment_schema_sha256": f"schemas/{DEPLOYMENT_SCHEMA}",
        "validator_sha256": VALIDATOR_PATH,
        "claim_contracts_sha256": CLAIM_CONTRACTS_PATH,
        "atomic_claim_sha256": ATOMIC_CLAIM_PATH,
    }
    root = repository_root()
    for field, relative in paths.items():
        if binding[field] != git_blob_sha256(binding["repository_commit"], relative):
            raise ValueError(f"declared commit binding changed: {field}")
        if binding[field] != sha256_file(root / relative):
            raise ValueError(f"worktree binding changed: {field}")


def live_host_identity() -> dict[str, str]:
    boot_path = Path("/proc/sys/kernel/random/boot_id")
    if not boot_path.is_file():
        raise ValueError("live boot identity is unavailable on this host")
    return {
        "hostname": socket.gethostname(),
        "boot_id": boot_path.read_text(encoding="utf-8").strip(),
    }


def validate_epoch(path: Path, artifact_root: Path) -> dict:
    epoch = validate_schema(path, EPOCH_SCHEMA, "claim-store epoch")
    require_self_id(epoch, "epoch_receipt_id", "claim-store epoch")
    parse_timestamp(epoch["issued_at"])
    previous = epoch["previous_epoch_receipt"]
    if epoch["epoch_sequence"] == 1 and previous is not None:
        raise ValueError("first claim-store epoch cannot have a predecessor")
    if epoch["epoch_sequence"] > 1:
        if previous is None:
            raise ValueError("later claim-store epoch requires its predecessor")
        previous_path = validate_identity(
            artifact_root, previous, "previous claim-store epoch"
        )
        prior = validate_schema(
            previous_path, EPOCH_SCHEMA, "previous claim-store epoch"
        )
        require_self_id(prior, "epoch_receipt_id", "previous claim-store epoch")
        if (
            prior["issuer_id"] != epoch["issuer_id"]
            or prior["store_name"] != epoch["store_name"]
            or prior["epoch_sequence"] + 1 != epoch["epoch_sequence"]
        ):
            raise ValueError("claim-store epoch predecessor chain changed")
    return epoch


def validate_deployment(
    deployment_path: Path, artifact_root: Path, *, require_live_host: bool = True
) -> dict:
    artifact_root = artifact_root.resolve()
    deployment = validate_schema(
        deployment_path, DEPLOYMENT_SCHEMA, "claim-store deployment"
    )
    require_self_id(deployment, "deployment_id", "claim-store deployment")
    validate_validator_binding(deployment["validator_binding"])
    epoch_path = validate_identity(
        artifact_root, deployment["store_epoch_receipt"], "claim-store epoch"
    )
    epoch = validate_epoch(epoch_path, artifact_root)
    if deployment["claim_store_epoch_sha256"] != epoch["epoch_receipt_id"]:
        raise ValueError("deployment epoch differs from the external epoch receipt")
    dispatcher_path = validate_identity(
        artifact_root, deployment["dispatcher_executable"], "dispatcher executable"
    )
    if dispatcher_path == deployment_path.resolve():
        raise ValueError("dispatcher executable cannot be the deployment receipt")
    canonical_database_path = str(Path(deployment["canonical_database_path"]).resolve())
    if canonical_database_path != deployment["canonical_database_path"]:
        raise ValueError("claim-store database path is not canonical absolute form")
    expected_store_identity = digest(
        {
            "schema_version": "community-claim-store-identity-v1",
            "canonical_database_path": os.path.normcase(canonical_database_path),
            "external_no_rollback_epoch_sha256": epoch["epoch_receipt_id"],
        }
    )
    if deployment["claim_store_identity_sha256"] != expected_store_identity:
        raise ValueError("claim-store identity differs from path and external epoch")
    if require_live_host and deployment["host_identity"] != live_host_identity():
        raise ValueError("claim-store deployment differs from the live host")
    return {
        "deployment": deployment,
        "epoch": epoch,
        "dispatcher_path": dispatcher_path,
        "claim_store_identity_sha256": expected_store_identity,
        "ready_for_atomic_claim": True,
        "gpu_dispatch_authorized": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("deployment", type=Path)
    parser.add_argument("--artifact-root", required=True, type=Path)
    parser.add_argument("--offline-host-check", action="store_true")
    args = parser.parse_args()
    result = validate_deployment(
        args.deployment,
        args.artifact_root,
        require_live_host=not args.offline_host_check,
    )
    print(
        json.dumps(
            {
                "status": "PASS",
                "ready_for_atomic_claim": result["ready_for_atomic_claim"],
                "gpu_dispatch_authorized": result["gpu_dispatch_authorized"],
                "claim_store_identity_sha256": result["claim_store_identity_sha256"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
