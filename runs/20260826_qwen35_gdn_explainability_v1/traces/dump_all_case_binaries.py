#!/usr/bin/env python3
"""Compile, launch, and archive every exact workload-case production composite."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import cutlass.cute as cute
import torch
from cutlass.base_dsl.compiler import DumpDir

from flashinfer.gdn_kernels.delta_rule_dsl.qwen35_fla_pipeline_sm120 import prepare_qwen35_fla_cute_pipeline_sm120
from flashinfer.gdn_kernels.delta_rule_dsl import custom_compile_cache


ROOT = Path("/workspace/dance/qwen35")
RUN = ROOT / "kernel_opt_agent/runs/20260826_qwen35_gdn_explainability_v1"
SOURCE_DIR = ROOT / "flashinfer/flashinfer/gdn_kernels/delta_rule_dsl"
OUT = RUN / "static/cases"
SHAPES = (256, 384, 404, 512, 640, 768, 1024)
H, D = 16, 128
EXPECTED = {
    "qwen35_fla_pipeline_sm120.py": "1ba9ed3d607171e2e900c91cf9c4d3ea91d3c3542f80cad4354b91eda507888d",
    "qwen35_fla_s01_sm120.py": "a17bbba422c8ee4af41c0da86b1e68f1b9db75892c4004789bc23fc2446b8df8",
    "qwen35_fla_s2_sm120.py": "00dedb81955371f5b34eb39d5f2bd0ae8d95d7f63bf13fc4635e032f8f5d9f24",
    "qwen35_fla_s3_raw_sm120.py": "fb0eb2a9bf4a72c6804eaf09c7fc3c9a74ff6eaf961c15ef4b3bd0dcb43e157b",
    "qwen35_fla_s3_short_raw_sm120.py": "2b61b0da46b13802fcc75620fe7f87fe50d4de6660259327ee08696b0b83929f",
    "qwen35_fla_s3_long_raw_sm120.py": "2b647e3971a36929a2239c1ade1b4afec33894e0cb6ec638d6b0b046871e149f",
    "qwen35_fla_post_sm120.py": "54ab667c78cdbdd082c95a6159bcfee3fce8194c32439fc4b53a7c0afd7cb818",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(value, path: Path) -> None:
    if callable(value):
        value = value()
    if isinstance(value, (bytes, bytearray, memoryview)):
        path.write_bytes(bytes(value))
    elif isinstance(value, str) and "\n" not in value and Path(value).is_file():
        shutil.copyfile(value, path)
    elif isinstance(value, str):
        path.write_text(value)
    else:
        raise TypeError(f"unsupported artifact {type(value)!r}")


def main() -> None:
    observed = {name: sha(SOURCE_DIR / name) for name in EXPECTED}
    if observed != EXPECTED:
        raise RuntimeError(f"production source identity changed: {observed}")
    torch.cuda.set_device(6)
    device = torch.device("cuda:6")
    OUT.mkdir(parents=True, exist_ok=True)
    active_dump = [OUT]

    def persistent_options(options, _temporary_dir):
        return tuple(options) + (cute.KeepPTX(True), cute.KeepCUBIN(True), cute.KeepSASS(True), DumpDir(str(active_dump[0])))

    custom_compile_cache._ptx_check_compile_options = persistent_options
    nvdisasm = Path("/usr/local/cuda/bin/nvdisasm")
    cases = []
    for sequence in SHAPES:
        case_dir = OUT / f"s{sequence}"
        case_dir.mkdir(parents=True, exist_ok=True)
        active_dump[0] = case_dir / "compiler_dump"
        active_dump[0].mkdir(parents=True, exist_ok=True)
        generator = torch.Generator(device=device).manual_seed(20260826 + sequence)
        physical = torch.randn((sequence, 3 * H * D), device=device, dtype=torch.bfloat16, generator=generator)
        mixed = torch.as_strided(physical, size=(1, 3 * H * D, sequence), stride=(sequence * 3 * H * D, 1, 3 * H * D))
        zba = torch.randn((sequence, H * (D + 2)), device=device, dtype=torch.bfloat16, generator=generator)
        a_log = -3.0 + 0.1 * torch.randn(H, device=device, dtype=torch.float32, generator=generator)
        dt_bias = -0.5 + 0.1 * torch.randn(H, device=device, dtype=torch.float32, generator=generator)
        norm = torch.randn(D, device=device, dtype=torch.bfloat16, generator=generator)
        cu = torch.tensor([0, sequence], device=device, dtype=torch.int64)
        output = torch.empty((sequence, H, D), device=device, dtype=torch.bfloat16)
        plan = prepare_qwen35_fla_cute_pipeline_sm120(mixed, zba, a_log, dt_bias, norm, cu, output=output)
        plan.run_fused_gated_rms(output, mixed, zba, a_log, dt_bias, norm)
        torch.cuda.synchronize(device)
        if not bool(torch.isfinite(output).all().item()):
            raise RuntimeError(f"S={sequence}: non-finite smoke output")
        cubin, ptx, sass = case_dir / "composite.cubin", case_dir / "composite.ptx", case_dir / "final.sass"
        dump(getattr(plan.compiled, "__cubin__", None), cubin)
        dump(getattr(plan.compiled, "__ptx__", None), ptx)
        result = subprocess.run([str(nvdisasm), "--print-code", "--print-line-info", str(cubin)], check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        sass.write_text(result.stdout)
        record = {
            "case_id": f"s{sequence}", "S": sequence, "P": ((sequence + 63) // 64) * 64,
            "J": (sequence + 63) // 64, "abi_tag": plan.stage_abi_tag,
            "cubin": {"path": str(cubin), "sha256": sha(cubin), "bytes": cubin.stat().st_size},
            "ptx": {"path": str(ptx), "sha256": sha(ptx), "bytes": ptx.stat().st_size},
            "sass": {"path": str(sass), "sha256": sha(sass), "bytes": sass.stat().st_size},
            "launch_smoke": "PASS",
        }
        cases.append(record)
        print(json.dumps({"event": "CASE_BINARY_READY", **record}, sort_keys=True), flush=True)
        del plan, output, mixed, physical, zba, a_log, dt_bias, norm, cu
        torch.cuda.empty_cache()
    manifest = {
        "schema_version": "qwen35-production-case-binary-set-v1", "status": "PASS",
        "created_at": datetime.now(timezone.utc).isoformat(), "source_sha256": observed,
        "device": {"index": 6, "name": torch.cuda.get_device_name(device), "capability": list(torch.cuda.get_device_capability(device))},
        "tool": {"path": str(nvdisasm), "sha256": sha(nvdisasm)}, "cases": cases,
    }
    write_path = OUT / "manifest.json"
    write_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"event": "BINARY_SET_READY", "manifest": str(write_path), "sha256": sha(write_path)}, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
