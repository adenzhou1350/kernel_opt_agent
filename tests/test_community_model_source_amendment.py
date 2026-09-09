#!/usr/bin/env python3
"""Exercise content-equivalent model-source amendment gates."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from community_knowledge import sha256_file  # noqa: E402
from community_model_source_amendment import validate_amendment  # noqa: E402


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def file_row(path: Path, root: Path) -> dict:
    return {
        "path": path.relative_to(root).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def git_blob_sha1(content: bytes) -> str:
    header = f"blob {len(content)}\0".encode()
    return hashlib.sha1(header + content).hexdigest()  # noqa: S324


def source(root: Path, provider: str, repository: str, revision: str) -> dict:
    executor = []
    for name in ("config.json", "model.safetensors", "tokenizer.json"):
        executor.append(file_row(root / name, root))
    excluded = [
        file_row(root / "README.md", root) | {"category": "DOCUMENTATION"},
        file_row(root / ".msc", root) | {"category": "PROVIDER_METADATA"},
    ]
    return {
        "provider": provider,
        "repository": repository,
        "revision": revision,
        "root": root.name,
        "executor_inventory": executor,
        "excluded_files": excluded,
    }


def fixture(root: Path) -> tuple[Path, dict]:
    original = root / "original"
    replacement = root / "replacement"
    original.mkdir()
    replacement.mkdir()
    payload = {
        "config.json": b'{"model_type":"llama"}\n',
        "model.safetensors": b"sealed model payload",
        "tokenizer.json": b'{"version":"1.0"}\n',
    }
    for name, content in payload.items():
        (original / name).write_bytes(content)
        (replacement / name).write_bytes(content)
    (original / "README.md").write_text("Hugging Face docs\n", encoding="utf-8")
    (replacement / "README.md").write_text("ModelScope docs\n", encoding="utf-8")
    (original / ".msc").write_text("hf metadata\n", encoding="utf-8")
    (replacement / ".msc").write_text("ms metadata\n", encoding="utf-8")
    value = {
        "schema_version": "community-model-source-amendment-v1",
        "generated_at": "2026-09-10T03:00:00Z",
        "cycle_id": "cycle-1",
        "task_id": "sglang-38565-tp-sampling-consistency",
        "component": "target",
        "logical_model_id": "meta-llama/Llama-3.1-8B-Instruct@frozen",
        "claim_boundary": (
            "MODEL_TRANSPORT_ONLY_EXECUTOR_PAYLOAD_CONTENT_IDENTICAL_"
            "NO_TASK_WORKLOAD_OR_MODEL_CHANGE"
        ),
        "execution_state": {
            "formal_entries_executed": 0,
            "hidden_oracle_exposed": False,
            "gpu_dispatch_authorized": False,
        },
        "original_source": source(
            original, "huggingface", "meta-llama/Llama-3.1-8B-Instruct", "frozen"
        ),
        "replacement_source": source(
            replacement,
            "modelscope",
            "AI-ModelScope/Llama-3.1-8B-Instruct",
            "master",
        ),
    }
    amendment = root / "amendment.json"
    write_json(amendment, value)
    return amendment, value


def refresh_source(value: dict, root: Path, side: str) -> None:
    previous = value[f"{side}_source"]
    source_root = root / previous["root"]
    value[f"{side}_source"] = source(
        source_root,
        previous["provider"],
        previous["repository"],
        previous["revision"],
    )


def test_accepts_exact_executor_payload_with_provider_metadata_drift(
    tmp_path: Path,
) -> None:
    amendment, _ = fixture(tmp_path)
    result = validate_amendment(amendment, tmp_path)
    assert result["status"] == "PASS_MODEL_SOURCE_CONTENT_EQUIVALENCE"
    assert result["executor_files"] == 3
    assert result["gpu_dispatch_authorized"] is False


def test_rejects_executor_content_mismatch(tmp_path: Path) -> None:
    amendment, value = fixture(tmp_path)
    (tmp_path / "replacement" / "config.json").write_text(
        '{"model_type":"other"}\n', encoding="utf-8"
    )
    refresh_source(value, tmp_path, "replacement")
    write_json(amendment, value)
    with pytest.raises(ValueError, match="executor-visible content differs"):
        validate_amendment(amendment, tmp_path)


def test_rejects_declared_hash_mismatch(tmp_path: Path) -> None:
    amendment, value = fixture(tmp_path)
    value["replacement_source"]["executor_inventory"][0]["sha256"] = "0" * 64
    write_json(amendment, value)
    with pytest.raises(ValueError, match="hash changed"):
        validate_amendment(amendment, tmp_path)


def test_rejects_missing_executor_path(tmp_path: Path) -> None:
    amendment, value = fixture(tmp_path)
    missing = value["replacement_source"]["executor_inventory"].pop()
    (tmp_path / "replacement" / missing["path"]).unlink()
    write_json(amendment, value)
    with pytest.raises(ValueError, match="executor-visible path set differs"):
        validate_amendment(amendment, tmp_path)


def test_rejects_undeclared_file(tmp_path: Path) -> None:
    amendment, _ = fixture(tmp_path)
    (tmp_path / "replacement" / "surprise.txt").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="inventory is not complete"):
        validate_amendment(amendment, tmp_path)


def test_rejects_executor_sensitive_exclusion(tmp_path: Path) -> None:
    amendment, value = fixture(tmp_path)
    row = value["replacement_source"]["executor_inventory"].pop(0)
    value["replacement_source"]["excluded_files"].append(
        row | {"category": "PROVIDER_METADATA"}
    )
    write_json(amendment, value)
    with pytest.raises(ValueError, match="executor-sensitive file cannot be excluded"):
        validate_amendment(amendment, tmp_path)


def test_rejects_duplicate_or_overlapping_path(tmp_path: Path) -> None:
    amendment, value = fixture(tmp_path)
    value["replacement_source"]["executor_inventory"].append(
        copy.deepcopy(value["replacement_source"]["executor_inventory"][0])
    )
    write_json(amendment, value)
    with pytest.raises(ValueError, match="duplicate replacement executor path"):
        validate_amendment(amendment, tmp_path)


def test_rejects_path_escape(tmp_path: Path) -> None:
    amendment, value = fixture(tmp_path)
    value["replacement_source"]["root"] = "../replacement"
    write_json(amendment, value)
    with pytest.raises(ValueError, match="invalid model source amendment schema"):
        validate_amendment(amendment, tmp_path)


def test_rejects_byte_count_mismatch(tmp_path: Path) -> None:
    amendment, value = fixture(tmp_path)
    value["replacement_source"]["executor_inventory"][0]["bytes"] += 1
    write_json(amendment, value)
    with pytest.raises(ValueError, match="byte count changed"):
        validate_amendment(amendment, tmp_path)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("formal_entries_executed", 1),
        ("hidden_oracle_exposed", True),
        ("gpu_dispatch_authorized", True),
    ],
)
def test_rejects_execution_or_oracle_state(
    tmp_path: Path, field: str, value: object
) -> None:
    amendment, payload = fixture(tmp_path)
    payload["execution_state"][field] = value
    write_json(amendment, payload)
    with pytest.raises(ValueError, match="invalid model source amendment schema"):
        validate_amendment(amendment, tmp_path)


def test_rejects_same_source_root(tmp_path: Path) -> None:
    amendment, value = fixture(tmp_path)
    value["replacement_source"] = copy.deepcopy(value["original_source"])
    write_json(amendment, value)
    with pytest.raises(ValueError, match="roots must be distinct"):
        validate_amendment(amendment, tmp_path)


def metadata_fixture(root: Path) -> tuple[Path, dict]:
    replacement = root / "modelscope"
    replacement.mkdir()
    payload = {
        "config.json": b'{"model_type":"llama"}\n',
        "model.safetensors": b"sealed lfs model payload",
        "tokenizer.json": b'{"version":"1.0"}\n',
    }
    for name, content in payload.items():
        (replacement / name).write_bytes(content)
    (replacement / "README.md").write_text("ModelScope docs\n", encoding="utf-8")
    (replacement / ".msc").write_text("provider metadata\n", encoding="utf-8")
    siblings = [
        {
            "rfilename": "config.json",
            "size": len(payload["config.json"]),
            "blobId": git_blob_sha1(payload["config.json"]),
            "lfs": None,
        },
        {
            "rfilename": "model.safetensors",
            "size": len(payload["model.safetensors"]),
            "blobId": "1" * 40,
            "lfs": {
                "sha256": hashlib.sha256(payload["model.safetensors"]).hexdigest(),
                "size": len(payload["model.safetensors"]),
            },
        },
        {
            "rfilename": "tokenizer.json",
            "size": len(payload["tokenizer.json"]),
            "blobId": git_blob_sha1(payload["tokenizer.json"]),
            "lfs": None,
        },
        {"rfilename": ".gitattributes", "size": 10, "blobId": "2" * 40},
        {"rfilename": "README.md", "size": 12, "blobId": "3" * 40},
        {
            "rfilename": "original/consolidated.00.pth",
            "size": 100,
            "blobId": "4" * 40,
            "lfs": {"sha256": "5" * 64, "size": 100},
        },
    ]
    metadata = root / "hf-api.json"
    write_json(
        metadata,
        {
            "id": "meta-llama/Llama-3.1-8B-Instruct",
            "sha": "frozen-revision",
            "siblings": siblings,
        },
    )
    executor = [
        {
            "path": "config.json",
            "bytes": len(payload["config.json"]),
            "identity_kind": "GIT_BLOB_SHA1",
            "digest": git_blob_sha1(payload["config.json"]),
        },
        {
            "path": "model.safetensors",
            "bytes": len(payload["model.safetensors"]),
            "identity_kind": "LFS_SHA256",
            "digest": hashlib.sha256(payload["model.safetensors"]).hexdigest(),
        },
        {
            "path": "tokenizer.json",
            "bytes": len(payload["tokenizer.json"]),
            "identity_kind": "GIT_BLOB_SHA1",
            "digest": git_blob_sha1(payload["tokenizer.json"]),
        },
    ]
    replacement_source = {
        "provider": "modelscope",
        "repository": "AI-ModelScope/Llama-3.1-8B-Instruct",
        "revision": "master",
        "root": replacement.name,
        "executor_inventory": [
            file_row(replacement / name, replacement) for name in payload
        ],
        "excluded_files": [
            file_row(replacement / "README.md", replacement)
            | {"category": "DOCUMENTATION"},
            file_row(replacement / ".msc", replacement)
            | {"category": "PROVIDER_METADATA"},
        ],
    }
    value = {
        "schema_version": "community-model-source-amendment-v2",
        "generated_at": "2026-09-10T04:00:00Z",
        "cycle_id": "cycle-1",
        "task_id": "sglang-38565-tp-sampling-consistency",
        "component": "target",
        "logical_model_id": "meta-llama/Llama-3.1-8B-Instruct@frozen-revision",
        "claim_boundary": (
            "MODEL_TRANSPORT_ONLY_METADATA_ATTESTED_EXECUTOR_PAYLOAD_IDENTICAL_"
            "NO_TASK_WORKLOAD_OR_MODEL_CHANGE"
        ),
        "execution_state": {
            "formal_entries_executed": 0,
            "hidden_oracle_exposed": False,
            "gpu_dispatch_authorized": False,
        },
        "original_source": {
            "provider": "huggingface",
            "repository": "meta-llama/Llama-3.1-8B-Instruct",
            "revision": "frozen-revision",
            "metadata_format": "HUGGINGFACE_MODEL_API_V1",
            "metadata_evidence": {
                "path": metadata.name,
                "sha256": sha256_file(metadata),
            },
            "executor_inventory": executor,
            "excluded_paths": [
                {"path": ".gitattributes", "category": "REPOSITORY_METADATA"},
                {"path": "README.md", "category": "DOCUMENTATION"},
                {
                    "path": "original/consolidated.00.pth",
                    "category": "NON_EXECUTOR_ALTERNATE_FORMAT",
                },
            ],
        },
        "replacement_source": replacement_source,
    }
    amendment = root / "metadata-amendment.json"
    write_json(amendment, value)
    return amendment, value


def refresh_metadata_evidence(value: dict, root: Path) -> None:
    path = root / value["original_source"]["metadata_evidence"]["path"]
    value["original_source"]["metadata_evidence"]["sha256"] = sha256_file(path)


def test_v2_accepts_exact_metadata_attested_executor_payload(tmp_path: Path) -> None:
    amendment, _ = metadata_fixture(tmp_path)
    result = validate_amendment(amendment, tmp_path)
    assert result["status"] == (
        "PASS_MODEL_SOURCE_METADATA_ATTESTED_CONTENT_EQUIVALENCE"
    )
    assert result["executor_files"] == 3
    assert result["gpu_dispatch_authorized"] is False


def test_v2_rejects_metadata_revision_drift(tmp_path: Path) -> None:
    amendment, value = metadata_fixture(tmp_path)
    metadata = tmp_path / "hf-api.json"
    payload = json.loads(metadata.read_text(encoding="utf-8"))
    payload["sha"] = "other-revision"
    write_json(metadata, payload)
    refresh_metadata_evidence(value, tmp_path)
    write_json(amendment, value)
    with pytest.raises(ValueError, match="repository or revision identity mismatch"):
        validate_amendment(amendment, tmp_path)


def test_v2_rejects_metadata_evidence_hash_drift(tmp_path: Path) -> None:
    amendment, _ = metadata_fixture(tmp_path)
    (tmp_path / "hf-api.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="metadata evidence hash changed"):
        validate_amendment(amendment, tmp_path)


def test_v2_rejects_lfs_identity_drift(tmp_path: Path) -> None:
    amendment, value = metadata_fixture(tmp_path)
    row = value["original_source"]["executor_inventory"][1]
    row["digest"] = "0" * 64
    write_json(amendment, value)
    with pytest.raises(ValueError, match="metadata LFS identity mismatch"):
        validate_amendment(amendment, tmp_path)


def test_v2_rejects_local_git_blob_drift(tmp_path: Path) -> None:
    amendment, value = metadata_fixture(tmp_path)
    path = tmp_path / "modelscope" / "config.json"
    path.write_text('{"model_type":"other"}\n', encoding="utf-8")
    replacement = value["replacement_source"]
    replacement["executor_inventory"] = [
        file_row(tmp_path / "modelscope" / row["path"], tmp_path / "modelscope")
        for row in replacement["executor_inventory"]
    ]
    write_json(amendment, value)
    with pytest.raises(ValueError, match="executor-visible content differs"):
        validate_amendment(amendment, tmp_path)


def test_v2_rejects_unclassified_remote_file(tmp_path: Path) -> None:
    amendment, value = metadata_fixture(tmp_path)
    metadata = tmp_path / "hf-api.json"
    payload = json.loads(metadata.read_text(encoding="utf-8"))
    payload["siblings"].append({"rfilename": "NOTICE", "size": 10, "blobId": "6" * 40})
    write_json(metadata, payload)
    refresh_metadata_evidence(value, tmp_path)
    write_json(amendment, value)
    with pytest.raises(ValueError, match="metadata inventory is not complete"):
        validate_amendment(amendment, tmp_path)


def test_v2_rejects_sensitive_exclusion_outside_original(tmp_path: Path) -> None:
    amendment, value = metadata_fixture(tmp_path)
    metadata = tmp_path / "hf-api.json"
    payload = json.loads(metadata.read_text(encoding="utf-8"))
    payload["siblings"].append(
        {
            "rfilename": "alternate.bin",
            "size": 10,
            "blobId": "7" * 40,
            "lfs": {"sha256": "8" * 64, "size": 10},
        }
    )
    write_json(metadata, payload)
    refresh_metadata_evidence(value, tmp_path)
    value["original_source"]["excluded_paths"].append(
        {"path": "alternate.bin", "category": "NON_EXECUTOR_ALTERNATE_FORMAT"}
    )
    write_json(amendment, value)
    with pytest.raises(
        ValueError, match="executor-sensitive metadata path cannot be excluded"
    ):
        validate_amendment(amendment, tmp_path)
