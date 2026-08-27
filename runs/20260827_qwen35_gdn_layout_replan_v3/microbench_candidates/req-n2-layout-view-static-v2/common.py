"""Immutable paths, hashing and atomic JSON helpers for the N2 static gate."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


REQUEST_ID = "req-n2-layout-view-static-v2"
PRODUCTION_ROOT = Path("/workspace/dance/qwen35/flashinfer/flashinfer/gdn_kernels/delta_rule_dsl")
PRODUCTION_SOURCES = {
    "short": PRODUCTION_ROOT / "qwen35_fla_s3_short_raw_sm120.py",
    "long": PRODUCTION_ROOT / "qwen35_fla_s3_long_raw_sm120.py",
}
EXPECTED_PRODUCTION_HASHES = {
    "short": "2b61b0da46b13802fcc75620fe7f87fe50d4de6660259327ee08696b0b83929f",
    "long": "2b647e3971a36929a2239c1ade1b4afec33894e0cb6ec638d6b0b046871e149f",
}
CUTLASS_CUTE_ROOT = Path(
    "/workspace/dance/qwen35/.venv-cu13/lib/python3.12/site-packages/"
    "nvidia_cutlass_dsl/dsl_packages/cutlass/cute"
)
CUTLASS_PACKAGE_ROOT = CUTLASS_CUTE_ROOT.parent
CUTLASS_DSL_ROOT = CUTLASS_PACKAGE_ROOT.parent
CUTLASS_LAYOUT_SOURCES = {
    "atom": CUTLASS_CUTE_ROOT / "atom.py",
    "core": CUTLASS_CUTE_ROOT / "core.py",
    "tensor": CUTLASS_CUTE_ROOT / "tensor.py",
}
EXPECTED_CUTLASS_LAYOUT_HASHES = {
    "atom": "41a61c0dcc44eb1f852db9e6cf1a42d6098f66e42c7059015d1d04879d3de848",
    "core": "035c764686c4e5a94c1f2432b55ba2e6cc572a27db4d857278ccd785a6f7f6f3",
    "tensor": "c0707b064be449f726ffb895a6a745ffa9ea7cc814da3b97f86ce8c1597b6a27",
}
STATIC_TOOLCHAIN_SOURCES = {
    "warp_mma": CUTLASS_CUTE_ROOT / "nvgpu/warp/mma.py",
    "ast_preprocessor": CUTLASS_PACKAGE_ROOT / "base_dsl/ast_preprocessor.py",
    "ast_helpers": CUTLASS_PACKAGE_ROOT / "base_dsl/ast_helpers.py",
    "cutlass_ir": CUTLASS_PACKAGE_ROOT / "_mlir/_mlir_libs/_cutlass_ir.cu13.cpython-312-x86_64-linux-gnu.so",
    "ptxas": Path("/usr/local/cuda/bin/ptxas"),
    "cuobjdump": Path("/usr/local/cuda/bin/cuobjdump"),
}
EXPECTED_STATIC_TOOLCHAIN_HASHES = {
    "warp_mma": "afd7a67d9ecc87494929f1099d2e2da42371034ca55a8db5a7052e25c0d7c773",
    "ast_preprocessor": "97c9acb67af2bf2fb01d73c39556e906954ede8251a42b73315d0330d3c554c8",
    "ast_helpers": "5b357a0084b72b6c9cc6391921e8a5d08e743652f2b60d649a88bf50957abcfc",
    "cutlass_ir": "e20f9ddef63b8e4257fc26d87b80d15f81cb62104d84e7a6a7d079d913559a75",
    "ptxas": "7fdd01a4cf50e30746da98989c9272a907f491e6fd7fecfda14642e4375f88fb",
    "cuobjdump": "8690c347b8b4ce8ce0491a2fd10de9c99e02ec3600d1c7e101cf27719500a6ad",
}
LEGACY_NEGATIVE_SOURCE = Path(
    "/workspace/dance/qwen35/kernel_opt_agent/runs/"
    "20260827_qwen35_gdn_layout_replan_v3/traces/"
    "static_admissibility_revision_02/legacy_attempt2_short_source.py"
)
EXPECTED_LEGACY_NEGATIVE_HASH = (
    "089272013fc3e1f009d371b639ac50e72805b6a47136ccb5879fff3330f716f6"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def identity(path: Path) -> dict:
    return {"path": str(path.resolve()), "sha256": sha256(path)}


def dump(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def load(path: Path) -> dict:
    return json.loads(path.read_text())


def experiment_dir(run: Path) -> Path:
    return run / "experiments" / REQUEST_ID


def candidate_dir(run: Path) -> Path:
    return run / "microbench_candidates" / REQUEST_ID


def verify_production_sources() -> dict[str, dict]:
    bindings = {}
    for name, path in PRODUCTION_SOURCES.items():
        observed = sha256(path)
        expected = EXPECTED_PRODUCTION_HASHES[name]
        if observed != expected:
            raise RuntimeError(f"INFRA_FAILURE: production {name} identity changed: expected={expected}, observed={observed}")
        bindings[name] = identity(path)
    return bindings


def verify_cutlass_layout_sources() -> dict[str, dict]:
    bindings = {}
    for name, path in CUTLASS_LAYOUT_SOURCES.items():
        observed = sha256(path)
        expected = EXPECTED_CUTLASS_LAYOUT_HASHES[name]
        if observed != expected:
            raise RuntimeError(
                f"INFRA_FAILURE: CUTLASS CuTe {name} identity changed: "
                f"expected={expected}, observed={observed}"
            )
        bindings[name] = identity(path)
    return bindings


def verify_static_toolchain_sources() -> dict[str, dict]:
    bindings = {}
    for name, path in STATIC_TOOLCHAIN_SOURCES.items():
        observed = sha256(path)
        expected = EXPECTED_STATIC_TOOLCHAIN_HASHES[name]
        if observed != expected:
            raise RuntimeError(
                f"INFRA_FAILURE: static toolchain {name} identity changed: "
                f"expected={expected}, observed={observed}"
            )
        bindings[name] = identity(path)
    return bindings


def verify_legacy_negative_source() -> dict:
    observed = sha256(LEGACY_NEGATIVE_SOURCE)
    if observed != EXPECTED_LEGACY_NEGATIVE_HASH:
        raise RuntimeError(
            "INFRA_FAILURE: immutable legacy attempt-2 source changed: "
            f"expected={EXPECTED_LEGACY_NEGATIVE_HASH}, observed={observed}"
        )
    return identity(LEGACY_NEGATIVE_SOURCE)


__all__ = [
    "REQUEST_ID", "PRODUCTION_SOURCES", "EXPECTED_PRODUCTION_HASHES",
    "CUTLASS_LAYOUT_SOURCES", "EXPECTED_CUTLASS_LAYOUT_HASHES",
    "STATIC_TOOLCHAIN_SOURCES", "EXPECTED_STATIC_TOOLCHAIN_HASHES",
    "LEGACY_NEGATIVE_SOURCE", "EXPECTED_LEGACY_NEGATIVE_HASH",
    "candidate_dir", "dump", "experiment_dir", "identity", "load", "sha256",
    "verify_cutlass_layout_sources", "verify_production_sources",
    "verify_static_toolchain_sources", "verify_legacy_negative_source",
]
