"""Hash-bound helpers for the zero-launch N1/N2 production codegen gate."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path


REQUEST_ID = "req-n1-n2-production-exact-codegen-v1"
RUN_ID = "20260827_qwen35_gdn_layout_replan_v3"
RUN_ROOT = Path("/workspace/dance/qwen35/kernel_opt_agent/runs") / RUN_ID
CANDIDATE_ROOT = RUN_ROOT / "microbench_candidates" / REQUEST_ID
CANDIDATE_PACKAGE = CANDIDATE_ROOT / "candidate_pkg"
REFERENCE_ROOT = CANDIDATE_ROOT / "reference"
EXPERIMENT_ROOT = RUN_ROOT / "experiments" / REQUEST_ID
PRODUCTION_ROOT = Path(
    "/workspace/dance/qwen35/flashinfer/flashinfer/gdn_kernels/delta_rule_dsl"
)
PYTHON = Path("/workspace/dance/qwen35/.venv-cu13/bin/python")

CANDIDATES = {
    "N1": "C1",
    "N2": "C2",
}
PATHS = {
    "short_s404": {
        "sequence": 404,
        "padded_sequence": 448,
        "chunks": 7,
        "block_threads": 512,
        "active_threads": 256,
        "register_cap": 126,
        "shared_cap": 73984,
        "s3_token": "qwen35_fla_s3_short_raw_sm120",
    },
    "long_s1024": {
        "sequence": 1024,
        "padded_sequence": 1024,
        "chunks": 16,
        "block_threads": 256,
        "active_threads": 256,
        "register_cap": 128,
        "shared_cap": 49408,
        "s3_token": "qwen35_fla_s3_long_raw_sm120",
    },
}

# Candidate identities are owned by the global scheduler's uploaded package.
EXPECTED_CANDIDATE_HASHES = {
    "CANDIDATE_CONTRACT.md": "48eb55ca489a5cf17f5dc87049fd576ddc1bf41488e564e53db515aa107d063e",
    "__init__.py": "84c93fdacd14107e29dcf666cf166793076fe74fb55d24e8012419d3e6cf6ed4",
    "qwen35_fla_pipeline_sm120.py": "7da4d941ffd8218d2a4b6ea15cc4856afcc41d510fb0338038b283ce2e5a1529",
    "qwen35_fla_s3_raw_sm120.py": "76808b2ead0ea439f119d0ce6c547f3edb0091eb688aa4eeabe3d92a2134ce6d",
    "qwen35_fla_s3_short_raw_sm120.py": "a02b4c5d3aef6c4b7db4e3dba20583b819481a452eac1b68e70916ca2a255d21",
    "qwen35_fla_s3_long_raw_sm120.py": "f51db951d48595b158f2a4898a53666ee1e8848a5f9baa22b49697d1d98da21a",
}

EXPECTED_PRODUCTION_HASHES = {
    "qwen35_fla_s3_short_raw_sm120.py": "2b61b0da46b13802fcc75620fe7f87fe50d4de6660259327ee08696b0b83929f",
    "qwen35_fla_s3_long_raw_sm120.py": "2b647e3971a36929a2239c1ade1b4afec33894e0cb6ec638d6b0b046871e149f",
    "qwen35_fla_s01_sm120.py": "a17bbba422c8ee4af41c0da86b1e68f1b9db75892c4004789bc23fc2446b8df8",
    "qwen35_fla_s2_sm120.py": "00dedb81955371f5b34eb39d5f2bd0ae8d95d7f63bf13fc4635e032f8f5d9f24",
    "qwen35_fla_post_sm120.py": "54ab667c78cdbdd082c95a6159bcfee3fce8194c32439fc4b53a7c0afd7cb818",
    "custom_compile_cache.py": "218c53d6b7afd00dda369ac1fd90d5a7cb65ea4fb9bdc7f8bafc06535d86bca8",
    "varlen_helper.py": "ced3aeeee187f9d96d4d3ed5d28b0e088dc23d75b214d8a6b129c877160f3be1",
}
EXPECTED_REFERENCE_HASHES = {
    "qwen35_fla_s3_short_raw_sm120.py": "2b61b0da46b13802fcc75620fe7f87fe50d4de6660259327ee08696b0b83929f",
    "qwen35_fla_s3_long_raw_sm120.py": "2b647e3971a36929a2239c1ade1b4afec33894e0cb6ec638d6b0b046871e149f",
}

# These modules are deliberately imported through their production-qualified
# names.  The package must not obtain them through candidate_pkg.__path__ or an
# unsealed shadow module.
ABSOLUTE_HELPER_ORIGINS = {
    "flashinfer.gdn_kernels.delta_rule_dsl.custom_compile_cache": {
        "path": PRODUCTION_ROOT / "custom_compile_cache.py",
        "sha256": EXPECTED_PRODUCTION_HASHES["custom_compile_cache.py"],
    },
    "flashinfer.gdn_kernels.delta_rule_dsl.varlen_helper": {
        "path": PRODUCTION_ROOT / "varlen_helper.py",
        "sha256": EXPECTED_PRODUCTION_HASHES["varlen_helper.py"],
    },
}

RUNTIME_CANDIDATE_ORIGINS = {
    "candidate_pkg": CANDIDATE_PACKAGE / "__init__.py",
    "candidate_pkg.qwen35_fla_pipeline_sm120": (
        CANDIDATE_PACKAGE / "qwen35_fla_pipeline_sm120.py"
    ),
    "candidate_pkg.qwen35_fla_s3_raw_sm120": (
        CANDIDATE_PACKAGE / "qwen35_fla_s3_raw_sm120.py"
    ),
    "candidate_pkg.qwen35_fla_s3_short_raw_sm120": (
        CANDIDATE_PACKAGE / "qwen35_fla_s3_short_raw_sm120.py"
    ),
    "candidate_pkg.qwen35_fla_s3_long_raw_sm120": (
        CANDIDATE_PACKAGE / "qwen35_fla_s3_long_raw_sm120.py"
    ),
}

CUTLASS_ROOT = Path(
    "/workspace/dance/qwen35/.venv-cu13/lib/python3.12/site-packages/"
    "nvidia_cutlass_dsl/dsl_packages/cutlass"
)
TOOLCHAIN_IDENTITIES = {
    CUTLASS_ROOT / "cute/atom.py": "41a61c0dcc44eb1f852db9e6cf1a42d6098f66e42c7059015d1d04879d3de848",
    CUTLASS_ROOT / "cute/core.py": "035c764686c4e5a94c1f2432b55ba2e6cc572a27db4d857278ccd785a6f7f6f3",
    CUTLASS_ROOT / "cute/tensor.py": "c0707b064be449f726ffb895a6a745ffa9ea7cc814da3b97f86ce8c1597b6a27",
    CUTLASS_ROOT / "cute/nvgpu/warp/mma.py": "afd7a67d9ecc87494929f1099d2e2da42371034ca55a8db5a7052e25c0d7c773",
    CUTLASS_ROOT / "base_dsl/ast_preprocessor.py": "97c9acb67af2bf2fb01d73c39556e906954ede8251a42b73315d0330d3c554c8",
    CUTLASS_ROOT / "base_dsl/ast_helpers.py": "5b357a0084b72b6c9cc6391921e8a5d08e743652f2b60d649a88bf50957abcfc",
    CUTLASS_ROOT / "_mlir/_mlir_libs/_cutlass_ir.cu13.cpython-312-x86_64-linux-gnu.so": "e20f9ddef63b8e4257fc26d87b80d15f81cb62104d84e7a6a7d079d913559a75",
    Path("/usr/local/cuda/bin/ptxas"): "7fdd01a4cf50e30746da98989c9272a907f491e6fd7fecfda14642e4375f88fb",
    Path("/usr/local/cuda/bin/cuobjdump"): "8690c347b8b4ce8ce0491a2fd10de9c99e02ec3600d1c7e101cf27719500a6ad",
}


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
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    os.replace(temporary, path)


def load(path: Path) -> dict:
    return json.loads(path.read_text())


def verify_hashes(root: Path, expected: dict[str, str], label: str) -> list[dict]:
    result = []
    for relative, digest in expected.items():
        path = root / relative
        observed = sha256(path)
        if observed != digest:
            raise RuntimeError(
                f"INVALID_INFRA: {label} identity mismatch: {path}; "
                f"expected={digest}, observed={observed}"
            )
        result.append(identity(path))
    return result


def verify_bound_sources() -> dict:
    candidates = verify_hashes(
        CANDIDATE_PACKAGE, EXPECTED_CANDIDATE_HASHES, "candidate"
    )
    production = verify_hashes(
        PRODUCTION_ROOT, EXPECTED_PRODUCTION_HASHES, "production"
    )
    reference = verify_hashes(
        REFERENCE_ROOT, EXPECTED_REFERENCE_HASHES, "run-local reference"
    )
    toolchain = []
    for path, expected in TOOLCHAIN_IDENTITIES.items():
        observed = sha256(path)
        if observed != expected:
            raise RuntimeError(
                f"INVALID_INFRA: toolchain identity mismatch: {path}; "
                f"expected={expected}, observed={observed}"
            )
        toolchain.append(identity(path))
    return {
        "candidate": candidates,
        "reference": reference,
        "production": production,
        "absolute_helper_origins": {
            name: identity(binding["path"])
            for name, binding in ABSOLUTE_HELPER_ORIGINS.items()
        },
        "toolchain": toolchain,
    }


def verify_loaded_module_origins(path_name: str) -> dict[str, dict]:
    """Fail closed if Python resolved a candidate/helper through another file."""

    import sys

    if path_name not in PATHS:
        raise RuntimeError(f"INVALID_INFRA: unknown production path: {path_name}")
    # The dispatcher imports both short and long modules.  Bind all five
    # candidate Python origins on every configuration, not only the selected
    # path, so a shadowed inactive module cannot enter the source seal.
    required = dict(RUNTIME_CANDIDATE_ORIGINS)
    required.update({
        name: binding["path"] for name, binding in ABSOLUTE_HELPER_ORIGINS.items()
    })
    origins = {}
    for module_name, expected_path in required.items():
        module = sys.modules.get(module_name)
        if module is None:
            raise RuntimeError(
                f"INVALID_INFRA: required module was not loaded: {module_name}"
            )
        raw_origin = getattr(module, "__file__", None)
        if not raw_origin:
            raise RuntimeError(
                f"INVALID_INFRA: loaded module lacks __file__: {module_name}"
            )
        observed_path = Path(raw_origin).resolve()
        expected_path = expected_path.resolve()
        if observed_path != expected_path:
            raise RuntimeError(
                f"INVALID_INFRA: runtime module origin mismatch: {module_name}; "
                f"expected={expected_path}, observed={observed_path}"
            )
        observed = identity(observed_path)
        if module_name in ABSOLUTE_HELPER_ORIGINS:
            expected_hash = ABSOLUTE_HELPER_ORIGINS[module_name]["sha256"]
        else:
            expected_hash = EXPECTED_CANDIDATE_HASHES[observed_path.name]
        if observed["sha256"] != expected_hash:
            raise RuntimeError(
                f"INVALID_INFRA: runtime module hash mismatch: {module_name}"
            )
        origins[module_name] = observed
    return origins


def assert_same_source_snapshot(before: dict, after: dict) -> None:
    if before != after:
        raise RuntimeError(
            "INVALID_INFRA: source/toolchain identity changed during compile "
            "(TOCTOU)"
        )


def verify_experiment_source_seal(run: Path) -> dict:
    experiment_path = run / "experiments" / REQUEST_ID / "experiment.json"
    experiment = load(experiment_path)
    if experiment.get("status") != "MATERIALIZED":
        raise RuntimeError("INVALID_INFRA: experiment is not MATERIALIZED")
    sealed = {}
    for bound in experiment.get("source", {}).get("identities", []):
        path = Path(bound["path"])
        if not path.is_absolute():
            path = run / path
        path = path.resolve()
        observed = sha256(path)
        if observed != bound.get("sha256"):
            raise RuntimeError(
                f"INVALID_INFRA: experiment source seal mismatch: {path}"
            )
        sealed[path] = bound.get("sha256")

    required = {
        (CANDIDATE_PACKAGE / relative).resolve(): digest
        for relative, digest in EXPECTED_CANDIDATE_HASHES.items()
    }
    required.update({
        binding["path"].resolve(): binding["sha256"]
        for binding in ABSOLUTE_HELPER_ORIGINS.values()
    })
    missing = [
        str(path) for path, digest in required.items()
        if sealed.get(path) != digest
    ]
    if missing:
        raise RuntimeError(
            "INVALID_INFRA: experiment source seal omits candidate/helper "
            f"origins: {missing}"
        )
    return identity(experiment_path)


def require_run(value: Path) -> Path:
    run = value.resolve()
    if run != RUN_ROOT:
        raise RuntimeError(f"INVALID_INFRA: unexpected run path: {run}")
    return run


def gate(path: Path) -> dict:
    payload = load(path)
    if payload.get("status") not in {"PASS", "VALID"}:
        raise RuntimeError(f"INVALID_INFRA: upstream gate not consumable: {path}")
    return {"identity": identity(path), "payload": payload}


__all__ = [
    "ABSOLUTE_HELPER_ORIGINS", "CANDIDATES", "CANDIDATE_PACKAGE",
    "CANDIDATE_ROOT", "EXPERIMENT_ROOT",
    "EXPECTED_CANDIDATE_HASHES", "EXPECTED_PRODUCTION_HASHES",
    "EXPECTED_REFERENCE_HASHES", "PATHS", "PRODUCTION_ROOT", "PYTHON",
    "REFERENCE_ROOT", "REQUEST_ID", "RUN_ROOT", "RUNTIME_CANDIDATE_ORIGINS",
    "TOOLCHAIN_IDENTITIES", "assert_same_source_snapshot", "dump", "gate",
    "identity", "load", "require_run", "sha256", "verify_bound_sources",
    "verify_experiment_source_seal", "verify_loaded_module_origins",
]
