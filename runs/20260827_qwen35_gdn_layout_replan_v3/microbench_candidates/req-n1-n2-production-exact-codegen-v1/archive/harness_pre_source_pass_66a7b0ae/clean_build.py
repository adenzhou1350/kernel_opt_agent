#!/usr/bin/env python3
"""Compile C0 control plus N1/N2 short/long cubins with FakeTensor only."""

from __future__ import annotations

import argparse
import shutil
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

import cutlass
import cutlass.cute as cute
import torch
from cuda.bindings import driver as cuda_driver
from cutlass.cute.runtime import from_dlpack
from torch._subclasses.fake_tensor import FakeTensorMode

from common import (
    CANDIDATE_PACKAGE,
    CANDIDATES,
    EXPERIMENT_ROOT,
    PATHS,
    PRODUCTION_ROOT,
    dump,
    identity,
    require_run,
    verify_bound_sources,
    verify_experiment_source_seal,
)


H, D, BT = 16, 128, 64


def artifact_value(compiled, attribute: str):
    value = getattr(compiled, attribute, None)
    # CuTe exposes PTX/cubin through metadata accessors on some releases.  This
    # is not the compiled TVM-FFI/CUDA callable and cannot launch the kernel.
    if callable(value):
        value = value()
    if value is None:
        raise RuntimeError(f"compiled object lacks {attribute}")
    return value


def write_artifact(value, destination: Path) -> dict:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, (bytes, bytearray, memoryview)):
        destination.write_bytes(bytes(value))
    elif isinstance(value, str) and "\n" not in value and Path(value).is_file():
        shutil.copyfile(value, destination)
    elif isinstance(value, str):
        destination.write_text(value)
    else:
        raise RuntimeError(f"unsupported compiled artifact: {type(value)!r}")
    return identity(destination)


def fake_tensor(shape, dtype, *, stride=None):
    if stride is None:
        return torch.empty(shape, dtype=dtype, device="cuda")
    return torch.empty_strided(shape, stride, dtype=dtype, device="cuda")


def compile_configuration(candidate_id: str, path_name: str, build: Path) -> dict:
    config = PATHS[path_name]
    sequence = config["sequence"]
    padded = config["padded_sequence"]
    chunks = config["chunks"]

    sys.path.insert(0, str(CANDIDATE_PACKAGE.parent))
    sys.path.insert(1, str(PRODUCTION_ROOT.parents[2]))
    from candidate_pkg.qwen35_fla_pipeline_sm120 import (  # noqa: PLC0415
        Qwen35FLACompositeSm120,
        _build_production_stage_bundle,
    )
    from candidate_pkg.varlen_helper import integer_dtype_to_cutlass  # noqa: PLC0415

    cu_dtype = integer_dtype_to_cutlass(torch.int64)
    stages = _build_production_stage_bundle(
        sequence,
        cutlass.BFloat16,
        cu_dtype,
        candidate_id=candidate_id,
    )
    composite = Qwen35FLACompositeSm120(
        cutlass.BFloat16,
        cu_dtype,
        sequence=sequence,
        stages=stages,
    )

    with FakeTensorMode():
        output = fake_tensor((sequence, H, D), torch.bfloat16)
        mixed = fake_tensor(
            (1, 3 * H * D, sequence),
            torch.bfloat16,
            stride=(sequence * 3 * H * D, 1, 3 * H * D),
        )
        zba = fake_tensor((sequence, H * (D + 2)), torch.bfloat16)
        a_log = fake_tensor((H,), torch.float32)
        dt_bias = fake_tensor((H,), torch.float32)
        norm = fake_tensor((D,), torch.bfloat16)
        qhat = fake_tensor((sequence, H, D), torch.bfloat16)
        packed = [
            fake_tensor((chunks, H, D * BT), torch.bfloat16)
            for _ in range(3)
        ]
        cumulative = fake_tensor((H, padded), torch.float32)
        vnew = fake_tensor((padded, H, D), torch.bfloat16)
        h_state = fake_tensor((H * 8, chunks, 2, 64, 16), torch.bfloat16)
        raw_o = fake_tensor((sequence, H, D), torch.bfloat16)
        m_debug = fake_tensor((chunks, H, BT, BT), torch.bfloat16)
        inverse_debug = fake_tensor((chunks, H, BT, BT), torch.float16)
        beta_debug = fake_tensor((padded, H), torch.float32)
        s2_debug = fake_tensor((2, 64, 16, H * 8), torch.float32)
        cu = fake_tensor((2,), torch.int64)

        def wrap(tensor, align):
            return from_dlpack(
                tensor, assumed_align=align, enable_tvm_ffi=True
            ).mark_layout_dynamic()

        arguments = (
            wrap(output, 16),
            wrap(mixed, 16),
            wrap(zba, 16),
            wrap(a_log, 16),
            wrap(dt_bias, 16),
            wrap(norm, 16),
            wrap(qhat, 16),
            *(wrap(tensor, 16) for tensor in packed),
            wrap(cumulative, 16),
            wrap(vnew, 16),
            wrap(h_state, 16),
            wrap(raw_o, 16),
            wrap(m_debug, 16),
            wrap(inverse_debug, 16),
            wrap(beta_debug, 16),
            wrap(s2_debug, 16),
            wrap(cu, 8),
            cutlass.Float32(D**-0.5),
            cutlass.Float32(1.0e-6),
            cuda_driver.CUstream(0),
        )
        options = (
            cute.EnableTVMFFI(True),
            cute.GPUArch("sm_120a"),
            cute.KeepPTX(True),
            cute.KeepCUBIN(True),
        )
        compiled = cute.compile[options](composite, *arguments)

    stem = f"{candidate_id.lower()}_{path_name}"
    output_dir = build / stem
    ptx = write_artifact(
        artifact_value(compiled, "__ptx__"), output_dir / f"{stem}.ptx"
    )
    cubin = write_artifact(
        artifact_value(compiled, "__cubin__"), output_dir / f"{stem}.cubin"
    )
    return {
        "status": "PASS_CODEGEN",
        "candidate_id": candidate_id,
        "production_path": path_name,
        "sequence": sequence,
        "block_threads": config["block_threads"],
        "active_threads": config["active_threads"],
        "abi_tag": stages.abi_tag,
        "ptx": ptx,
        "cubin": cubin,
        "compiled_callable_invocations": 0,
        "cuda_kernel_launches": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    run = require_run(args.run)
    build = EXPERIMENT_ROOT / "build"
    if build.exists() and any(build.iterdir()):
        raise RuntimeError("INVALID_INFRA: clean build directory is not empty")
    build.mkdir(parents=True, exist_ok=True)

    try:
        experiment_identity = verify_experiment_source_seal(run)
        bound_sources = verify_bound_sources()
    except Exception as error:
        dump(build / "invalid_infrastructure.json", {
            "schema_version": "qwen35-n1-n2-codegen-infra-v1",
            "status": "INVALID",
            "stage": "identity_preflight",
            "error": str(error),
            "traceback": traceback.format_exc(),
            "candidate_disposition": "NONE",
        })
        raise

    configurations = []
    control_failed = False
    for path_name in PATHS:
        try:
            configurations.append(
                compile_configuration("C0", path_name, build)
            )
        except Exception as error:
            control_failed = True
            configurations.append({
                "status": "INVALID_CONTROL",
                "candidate_id": "C0",
                "production_path": path_name,
                "error": str(error),
                "traceback": traceback.format_exc(),
                "candidate_disposition": "NONE",
            })

    if control_failed:
        dump(build / "manifest.json", {
            "schema_version": "qwen35-n1-n2-codegen-build-v1",
            "status": "INVALID",
            "reason": "C0 production control did not compile",
            "experiment_identity": experiment_identity,
            "bound_sources": bound_sources,
            "configurations": configurations,
            "compiled_callable_invocations": 0,
            "cuda_kernel_launches": 0,
            "performance_samples": 0,
        })
        raise RuntimeError("INVALID_INFRA: C0 production compile control failed")

    for model_id, candidate_id in CANDIDATES.items():
        for path_name in PATHS:
            try:
                entry = compile_configuration(candidate_id, path_name, build)
                entry["model_candidate_id"] = model_id
            except Exception as error:
                entry = {
                    "status": "FAIL_CODEGEN",
                    "candidate_id": candidate_id,
                    "model_candidate_id": model_id,
                    "production_path": path_name,
                    "error": str(error),
                    "traceback": traceback.format_exc(),
                    "classification": (
                        "VALID_CANDIDATE_FAIL_BECAUSE_C0_CONTROL_PASSED"
                    ),
                }
            configurations.append(entry)

    for path_name in PATHS:
        passed = {
            entry["candidate_id"]: entry
            for entry in configurations
            if entry.get("production_path") == path_name
            and entry.get("status") == "PASS_CODEGEN"
        }
        hashes = [entry["cubin"]["sha256"] for entry in passed.values()]
        if len(hashes) != len(set(hashes)):
            for candidate_id in ("C1", "C2"):
                if candidate_id in passed:
                    passed[candidate_id]["status"] = "FAIL_NON_DISTINCT_BINARY"
                    passed[candidate_id]["classification"] = (
                        "VALID_CANDIDATE_FAIL"
                    )

    manifest = {
        "schema_version": "qwen35-n1-n2-codegen-build-v1",
        "status": "PASS",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "experiment_identity": experiment_identity,
        "bound_sources": bound_sources,
        "target": {"architecture": "sm_120a", "device_required": False},
        "compile_action": "cute.compile with FakeTensor only",
        "configurations": configurations,
        "compiled_callable_invocations": 0,
        "cuda_kernel_launches": 0,
        "gpu_timers": 0,
        "performance_samples": 0,
        "failure_semantics": {
            "candidate_compile_failure_after_C0_pass": "FAIL",
            "identity_toolchain_or_C0_failure": "INVALID",
        },
    }
    dump(build / "manifest.json", manifest)
    print("PASS: compile/codegen lifecycle complete; CUDA launches=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
