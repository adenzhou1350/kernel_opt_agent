#!/usr/bin/env python3
"""Compile, launch, and archive the exact current S=404 production composite."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import cutlass.cute as cute
import torch
from cutlass.base_dsl.compiler import DumpDir

from flashinfer.gdn_kernels.delta_rule_dsl.qwen35_fla_pipeline_sm120 import (
    prepare_qwen35_fla_cute_pipeline_sm120,
)
from flashinfer.gdn_kernels.delta_rule_dsl import custom_compile_cache


ROOT = Path("/workspace/dance/qwen35")
SOURCE_DIR = ROOT / "flashinfer/flashinfer/gdn_kernels/delta_rule_dsl"
EXPECTED = {
    "qwen35_fla_pipeline_sm120.py": "1ba9ed3d607171e2e900c91cf9c4d3ea91d3c3542f80cad4354b91eda507888d",
    "qwen35_fla_s01_sm120.py": "a17bbba422c8ee4af41c0da86b1e68f1b9db75892c4004789bc23fc2446b8df8",
    "qwen35_fla_s2_sm120.py": "00dedb81955371f5b34eb39d5f2bd0ae8d95d7f63bf13fc4635e032f8f5d9f24",
    "qwen35_fla_s3_raw_sm120.py": "fb0eb2a9bf4a72c6804eaf09c7fc3c9a74ff6eaf961c15ef4b3bd0dcb43e157b",
    "qwen35_fla_s3_short_raw_sm120.py": "2b61b0da46b13802fcc75620fe7f87fe50d4de6660259327ee08696b0b83929f",
    "qwen35_fla_s3_long_raw_sm120.py": "2b647e3971a36929a2239c1ade1b4afec33894e0cb6ec638d6b0b046871e149f",
    "qwen35_fla_post_sm120.py": "54ab667c78cdbdd082c95a6159bcfee3fce8194c32439fc4b53a7c0afd7cb818",
}
OUT = ROOT / "kernel_opt_agent/runs/20260826_qwen35_gdn_explainability_v1/static"
DUMP = OUT / "cute_compiler_dump"
S, H, D = 404, 16, 128
CHANNELS = 3 * H * D


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump_artifact(value, destination: Path) -> None:
    if callable(value):
        value = value()
    if isinstance(value, (bytes, bytearray, memoryview)):
        destination.write_bytes(bytes(value))
    elif isinstance(value, str) and "\n" not in value and Path(value).is_file():
        shutil.copyfile(value, destination)
    elif isinstance(value, str):
        destination.write_text(value)
    else:
        raise TypeError(f"unsupported compiled artifact type: {type(value)!r}")


def main() -> None:
    observed = {name: sha256(SOURCE_DIR / name) for name in EXPECTED}
    if observed != EXPECTED:
        raise RuntimeError(f"production source identity changed: {observed}")

    torch.manual_seed(20260826)
    torch.cuda.set_device(6)
    device = torch.device("cuda:6")

    # The production helper already forces KeepPTX for its SM12x legality
    # check, but uses a temporary dump directory and does not retain CUBIN.
    # Replace only that artifact-output option builder: generated code and all
    # semantic compile options remain identical, while the exact loaded cubin
    # and PTX survive under this run for disassembly and hash binding.
    DUMP.mkdir(parents=True, exist_ok=True)

    def persistent_artifact_options(options, _temporary_dir):
        return tuple(options) + (
            cute.KeepPTX(True),
            cute.KeepCUBIN(True),
            cute.KeepSASS(True),
            DumpDir(str(DUMP)),
        )

    custom_compile_cache._ptx_check_compile_options = persistent_artifact_options
    physical_qkv = torch.randn((S, CHANNELS), device=device, dtype=torch.bfloat16)
    mixed = torch.as_strided(
        physical_qkv,
        size=(1, CHANNELS, S),
        stride=(S * CHANNELS, 1, CHANNELS),
    )
    zba = torch.randn((S, H * (D + 2)), device=device, dtype=torch.bfloat16) * 0.125
    a_log = torch.zeros((H,), device=device, dtype=torch.float32)
    dt_bias = torch.zeros((H,), device=device, dtype=torch.float32)
    norm_weight = torch.ones((D,), device=device, dtype=torch.bfloat16)
    cu_seqlens = torch.tensor([0, S], device=device, dtype=torch.int64)
    output = torch.empty((S, H, D), device=device, dtype=torch.bfloat16)

    plan = prepare_qwen35_fla_cute_pipeline_sm120(
        mixed,
        zba,
        a_log,
        dt_bias,
        norm_weight,
        cu_seqlens,
        output=output,
    )
    plan.run_fused_gated_rms(output, mixed, zba, a_log, dt_bias, norm_weight)
    torch.cuda.synchronize(device)
    if not bool(torch.isfinite(output).all()):
        raise RuntimeError("current production S=404 smoke output is not finite")

    OUT.mkdir(parents=True, exist_ok=True)
    cubin = OUT / "current_s404_composite.cubin"
    ptx = OUT / "current_s404_composite.ptx"
    dump_artifact(getattr(plan.compiled, "__cubin__", None), cubin)
    dump_artifact(getattr(plan.compiled, "__ptx__", None), ptx)
    manifest = {
        "schema_version": "qwen35-current-s404-binary-dump-v1",
        "device": {
            "index": 6,
            "name": torch.cuda.get_device_name(device),
            "capability": list(torch.cuda.get_device_capability(device)),
        },
        "workload": {"B": 1, "H": H, "D": D, "S": S, "C": 64, "P": 448, "J": 7},
        "source_sha256": observed,
        "abi_tag": plan.stage_abi_tag,
        "artifacts": {
            "cubin": {"path": str(cubin), "sha256": sha256(cubin), "bytes": cubin.stat().st_size},
            "ptx": {"path": str(ptx), "sha256": sha256(ptx), "bytes": ptx.stat().st_size},
        },
        "launch_smoke": {"status": "PASS", "finite_output": True},
    }
    manifest_path = OUT / "current_s404_binary_dump.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps(manifest, sort_keys=True))


if __name__ == "__main__":
    main()
