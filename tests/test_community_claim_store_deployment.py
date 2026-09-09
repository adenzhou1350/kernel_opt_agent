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

import community_claim_store_deployment as deployment_module  # noqa: E402
from community_claim_store_deployment import validate_deployment  # noqa: E402
from community_claim_contracts import digest  # noqa: E402


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def identity(path: Path, root: Path) -> dict[str, str]:
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": sha256_file(path),
    }


def with_self_id(value: dict, field: str) -> dict:
    result = dict(value)
    result[field] = digest(value)
    return result


def validator_binding() -> dict[str, str]:
    paths = {
        "epoch_schema_sha256": ROOT
        / "schemas"
        / "community_claim_store_epoch.schema.json",
        "deployment_schema_sha256": ROOT
        / "schemas"
        / "community_claim_store_deployment.schema.json",
        "validator_sha256": ROOT / "scripts" / "community_claim_store_deployment.py",
        "claim_contracts_sha256": ROOT / "scripts" / "community_claim_contracts.py",
        "atomic_claim_sha256": ROOT / "scripts" / "community_atomic_claim.py",
    }
    return {
        "repository_commit": "1" * 40,
        **{key: sha256_file(path) for key, path in paths.items()},
    }


def build_bundle(root: Path) -> tuple[Path, dict, dict]:
    epoch = with_self_id(
        {
            "schema_version": "community-claim-store-epoch-v1",
            "issued_at": "2030-01-01T00:00:00Z",
            "claim_boundary": (
                "EXTERNAL_NO_ROLLBACK_EPOCH_NOT_EXECUTION_AUTHORIZATION"
            ),
            "issuer_id": "trusted-controller",
            "store_name": "meta-cycle-v8",
            "epoch_sequence": 1,
            "epoch_nonce_sha256": "2" * 64,
            "previous_epoch_receipt": None,
            "hidden_oracle_exposed": False,
        },
        "epoch_receipt_id",
    )
    epoch_path = root / "epoch.json"
    write_json(epoch_path, epoch)
    dispatcher_path = root / "dispatcher.py"
    dispatcher_path.write_text("print('sealed dispatcher')\n", encoding="utf-8")
    database_path = str((root / "claims.sqlite").resolve())
    store_identity = digest(
        {
            "schema_version": "community-claim-store-identity-v1",
            "canonical_database_path": os.path.normcase(database_path),
            "external_no_rollback_epoch_sha256": epoch["epoch_receipt_id"],
        }
    )
    deployment = with_self_id(
        {
            "schema_version": "community-claim-store-deployment-v1",
            "generated_at": "2030-01-01T00:00:01Z",
            "claim_boundary": (
                "TRUSTED_STORE_DEPLOYMENT_NOT_TOKEN_CONSUMPTION_OR_PROCESS_LAUNCH"
            ),
            "validator_binding": validator_binding(),
            "formal_resource_id": "shared-8x-sm120-32g",
            "host_identity": {"hostname": "formal-host", "boot_id": "boot-1"},
            "canonical_database_path": database_path,
            "store_epoch_receipt": identity(epoch_path, root),
            "claim_store_epoch_sha256": epoch["epoch_receipt_id"],
            "dispatcher_executable": identity(dispatcher_path, root),
            "claim_store_identity_sha256": store_identity,
            "hidden_oracle_exposed": False,
        },
        "deployment_id",
    )
    deployment_path = root / "deployment.json"
    write_json(deployment_path, deployment)
    return deployment_path, deployment, epoch


@pytest.fixture(autouse=True)
def bind_uncommitted_validator(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(deployment_module, "require_commit", lambda commit: None)

    def current_blob(commit: str, relative: str) -> str:
        return sha256_file(ROOT / relative)

    monkeypatch.setattr(deployment_module, "git_blob_sha256", current_blob)


def test_deployment_binds_store_epoch_dispatcher_and_host() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        path, deployment, _ = build_bundle(root)
        result = validate_deployment(path, root, require_live_host=False)
        assert result["ready_for_atomic_claim"] is True
        assert result["gpu_dispatch_authorized"] is False
        assert (
            result["claim_store_identity_sha256"]
            == deployment["claim_store_identity_sha256"]
        )


def test_deployment_rejects_live_host_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        path, _, _ = build_bundle(root)
        monkeypatch.setattr(
            deployment_module,
            "live_host_identity",
            lambda: {"hostname": "foreign-host", "boot_id": "boot-9"},
        )
        with pytest.raises(ValueError, match="differs from the live host"):
            validate_deployment(path, root)


def test_deployment_rejects_noncanonical_database_path() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        path, deployment, _ = build_bundle(root)
        deployment["canonical_database_path"] = str(
            root / "nested" / ".." / "claims.sqlite"
        )
        unsigned = {
            key: value for key, value in deployment.items() if key != "deployment_id"
        }
        deployment["deployment_id"] = digest(unsigned)
        write_json(path, deployment)
        with pytest.raises(ValueError, match="not canonical absolute"):
            validate_deployment(path, root, require_live_host=False)


def test_deployment_rejects_epoch_or_store_identity_substitution() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        path, deployment, _ = build_bundle(root)
        deployment["claim_store_epoch_sha256"] = "9" * 64
        deployment["claim_store_identity_sha256"] = "8" * 64
        unsigned = {
            key: value for key, value in deployment.items() if key != "deployment_id"
        }
        deployment["deployment_id"] = digest(unsigned)
        write_json(path, deployment)
        with pytest.raises(ValueError, match="deployment epoch differs"):
            validate_deployment(path, root, require_live_host=False)


def test_later_epoch_requires_valid_predecessor_chain() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        path, deployment, epoch = build_bundle(root)
        epoch["epoch_sequence"] = 2
        epoch["previous_epoch_receipt"] = None
        unsigned_epoch = {
            key: value for key, value in epoch.items() if key != "epoch_receipt_id"
        }
        epoch["epoch_receipt_id"] = digest(unsigned_epoch)
        epoch_path = root / "epoch.json"
        write_json(epoch_path, epoch)
        deployment["store_epoch_receipt"] = identity(epoch_path, root)
        deployment["claim_store_epoch_sha256"] = epoch["epoch_receipt_id"]
        unsigned = {
            key: value for key, value in deployment.items() if key != "deployment_id"
        }
        deployment["deployment_id"] = digest(unsigned)
        write_json(path, deployment)
        with pytest.raises(ValueError, match="requires its predecessor"):
            validate_deployment(path, root, require_live_host=False)


def test_deployment_rejects_unbound_payload_and_validator_drift() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        path, deployment, _ = build_bundle(root)
        unbound = copy.deepcopy(deployment)
        unbound["launch_now"] = True
        write_json(path, unbound)
        with pytest.raises(ValueError, match="invalid claim-store deployment"):
            validate_deployment(path, root, require_live_host=False)

        deployment["validator_binding"]["atomic_claim_sha256"] = "0" * 64
        unsigned = {
            key: value for key, value in deployment.items() if key != "deployment_id"
        }
        deployment["deployment_id"] = digest(unsigned)
        write_json(path, deployment)
        with pytest.raises(ValueError, match="declared commit binding changed"):
            validate_deployment(path, root, require_live_host=False)
