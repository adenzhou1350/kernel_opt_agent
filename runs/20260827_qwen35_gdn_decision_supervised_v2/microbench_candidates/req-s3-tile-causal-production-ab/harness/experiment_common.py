"""Shared, run-local utilities for the sealed S3 C0/C1 experiment."""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import torch


H, D = 16, 128
SCREENING_SEQUENCES = (404, 768)
CANDIDATES = ("C0", "C1")
EXPECTED_PYTHONPATH_PREFIX = (
    "/workspace/dance/qwen35/new/harrix/python",
    "/workspace/dance/qwen35/flashinfer",
)
PRODUCTION_PACKAGE = Path(
    "/workspace/dance/qwen35/flashinfer/flashinfer/gdn_kernels/delta_rule_dsl"
)
PRODUCTION_HASHES = {
    "qwen35_fla_pipeline_sm120.py": "1ba9ed3d607171e2e900c91cf9c4d3ea91d3c3542f80cad4354b91eda507888d",
    "qwen35_fla_s01_sm120.py": "a17bbba422c8ee4af41c0da86b1e68f1b9db75892c4004789bc23fc2446b8df8",
    "qwen35_fla_s2_sm120.py": "00dedb81955371f5b34eb39d5f2bd0ae8d95d7f63bf13fc4635e032f8f5d9f24",
    "qwen35_fla_s3_raw_sm120.py": "fb0eb2a9bf4a72c6804eaf09c7fc3c9a74ff6eaf961c15ef4b3bd0dcb43e157b",
    "qwen35_fla_s3_short_raw_sm120.py": "2b61b0da46b13802fcc75620fe7f87fe50d4de6660259327ee08696b0b83929f",
    "qwen35_fla_s3_long_raw_sm120.py": "2b647e3971a36929a2239c1ade1b4afec33894e0cb6ec638d6b0b046871e149f",
    "qwen35_fla_post_sm120.py": "54ab667c78cdbdd082c95a6159bcfee3fce8194c32439fc4b53a7c0afd7cb818",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def identity(path: Path) -> dict:
    return {"path": str(path.resolve()), "sha256": sha256(path)}


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def load_run(run: Path) -> tuple[dict, dict, dict]:
    return tuple(
        json.loads((run / name).read_text())
        for name in ("hardware.json", "workload.json", "operator.json")
    )


def verify_p0(run: Path) -> dict:
    path = run / "experiments/p0-reused/p0_receipt.json"
    data = json.loads(path.read_text())
    if data.get("status") != "PASS":
        raise RuntimeError("P0 receipt is not PASS")
    required = (
        "clock_stability",
        "cold_warm_separation",
        "competing_load",
        "graph_direct_equivalence",
        "independent_process_replication",
        "live_sink",
        "timer_bracket",
        "zero_work",
    )
    failed = [name for name in required if data["controls"][name]["status"] != "PASS"]
    if failed:
        raise RuntimeError(f"P0 controls failed: {failed}")
    return {"identity": identity(path), "controls": data["controls"]}


def verify_runtime_identity(run: Path) -> dict:
    declared = tuple(filter(None, os.environ.get("PYTHONPATH", "").split(":")))
    if declared[:2] != EXPECTED_PYTHONPATH_PREFIX:
        raise RuntimeError(
            f"PYTHONPATH must start with {EXPECTED_PYTHONPATH_PREFIX}, got {declared[:2]}"
        )
    candidate_root = run / "microbench_candidates/req-s3-tile-causal-production-ab"
    if str(candidate_root) not in sys.path:
        sys.path.insert(0, str(candidate_root))

    production_observed = {
        name: sha256(PRODUCTION_PACKAGE / name) for name in PRODUCTION_HASHES
    }
    if production_observed != PRODUCTION_HASHES:
        raise RuntimeError(f"frozen production source changed: {production_observed}")

    module_names = (
        "harrix",
        "flashinfer",
        "flashinfer.gdn_kernels.delta_rule_dsl.qwen35_fla_s01_sm120",
        "flashinfer.gdn_kernels.delta_rule_dsl.qwen35_fla_s2_sm120",
        "flashinfer.gdn_kernels.delta_rule_dsl.qwen35_fla_post_sm120",
    )
    specs = {}
    for name in module_names:
        spec = importlib.util.find_spec(name)
        origin = None if spec is None else spec.origin
        specs[name] = origin
        if origin is None:
            raise RuntimeError(f"runtime module has no origin: {name}")
    if not str(specs["harrix"]).startswith(EXPECTED_PYTHONPATH_PREFIX[0]):
        raise RuntimeError(f"old Harrix resolved: {specs['harrix']}")
    if not str(specs["flashinfer"]).startswith(EXPECTED_PYTHONPATH_PREFIX[1]):
        raise RuntimeError(f"wrong FlashInfer resolved: {specs['flashinfer']}")
    for name in module_names[2:]:
        if not str(specs[name]).startswith(str(PRODUCTION_PACKAGE)):
            raise RuntimeError(f"unchanged stage did not resolve to production: {name}={specs[name]}")

    candidate = importlib.import_module("candidate_pkg")
    candidate_modules = {
        name: importlib.import_module(f"candidate_pkg.{name}").__file__
        for name in (
            "qwen35_fla_pipeline_sm120",
            "qwen35_fla_s3_raw_sm120",
            "qwen35_fla_s3_short_raw_sm120",
            "qwen35_fla_s3_long_raw_sm120",
        )
    }
    if any(not str(path).startswith(str(candidate_root / "candidate_pkg")) for path in candidate_modules.values()):
        raise RuntimeError(f"candidate override escaped run-local package: {candidate_modules}")
    return {
        "pythonpath": list(declared),
        "module_origins": specs,
        "candidate_module_origins": candidate_modules,
        "candidate_package": candidate.__file__,
        "production_source_sha256": production_observed,
    }


def target_device(run: Path) -> tuple[int, str]:
    hardware = json.loads((run / "hardware.json").read_text())
    index = int(hardware["target"]["device_index"])
    uuid = hardware["target"]["uuid"]
    torch.cuda.set_device(index)
    if torch.cuda.get_device_capability(index) != (12, 0):
        raise RuntimeError("screening requires the frozen SM120 target")
    return index, uuid


def smi(index: int) -> dict:
    fields = "uuid,name,clocks.current.sm,utilization.gpu,temperature.gpu,power.draw"
    values = subprocess.run(
        [
            "/usr/bin/nvidia-smi",
            "-i",
            str(index),
            f"--query-gpu={fields}",
            "--format=csv,noheader,nounits",
        ],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout.strip().split(", ")
    return {
        "uuid": values[0],
        "name": values[1],
        "clock_mhz": float(values[2]),
        "utilization_percent": float(values[3]),
        "temperature_c": float(values[4]),
        "power_w": float(values[5]),
    }


def make_inputs(sequence: int, device: torch.device, *, seed: int, extreme: bool = False):
    generator = torch.Generator(device=device).manual_seed(seed)
    dtype = torch.bfloat16
    token_major = torch.randn(
        (1, sequence, 3 * H * D), device=device, dtype=dtype, generator=generator
    )
    zba = torch.randn(
        (sequence, H * (D + 2)), device=device, dtype=dtype, generator=generator
    )
    a_log = -3.0 + 0.1 * torch.randn(
        H, device=device, dtype=torch.float32, generator=generator
    )
    dt_bias = -0.5 + 0.1 * torch.randn(
        H, device=device, dtype=torch.float32, generator=generator
    )
    norm = torch.randn(D, device=device, dtype=dtype, generator=generator)
    if extreme:
        token_major[:, ::2].mul_(8.0)
        zba[::2].mul_(8.0)
        a_log.clamp_(-6.0, 1.0)
        dt_bias.clamp_(-8.0, 8.0)
        norm.mul_(4.0)
    mixed = token_major.transpose(1, 2)
    cu = torch.tensor([0, sequence], device=device, dtype=torch.int64)
    return mixed, zba, a_log, dt_bias, norm, cu


def make_plan(inputs, output: torch.Tensor, candidate_id: str):
    if candidate_id not in CANDIDATES:
        raise ValueError(candidate_id)
    from candidate_pkg import prepare_qwen35_fla_cute_pipeline_sm120

    mixed, zba, a_log, dt_bias, norm, cu = inputs
    plan = prepare_qwen35_fla_cute_pipeline_sm120(
        mixed,
        zba,
        a_log,
        dt_bias,
        norm,
        cu,
        output=output,
        candidate_id=candidate_id,
    )
    suffix = f"s3tileab_{candidate_id.lower()}"
    if not plan.stage_abi_tag.endswith(suffix):
        raise RuntimeError(f"ABI/cache key did not bind candidate: {plan.stage_abi_tag}")
    return plan


def launch(plan, inputs, output):
    mixed, zba, a_log, dt_bias, norm, _ = inputs
    return plan.run_fused_gated_rms(output, mixed, zba, a_log, dt_bias, norm)


def plans_for_sequence(sequence: int, device: torch.device, *, seed: int, extreme: bool = False):
    inputs = make_inputs(sequence, device, seed=seed, extreme=extreme)
    entries = {}
    for candidate_id in CANDIDATES:
        output = torch.empty((sequence, H, D), device=device, dtype=torch.bfloat16)
        plan = make_plan(inputs, output, candidate_id)
        entries[candidate_id] = {"plan": plan, "output": output}
    return inputs, entries


def run_receipt(run: Path, relative: str, *, expected_status: str = "PASS") -> dict:
    path = run / relative
    data = json.loads(path.read_text())
    if data.get("status") != expected_status:
        raise RuntimeError(f"gate is not {expected_status}: {path}")
    return {"identity": identity(path), "payload": data}


def assert_idle(snapshot: dict, *, maximum_percent: float = 2.0) -> None:
    if snapshot["utilization_percent"] > maximum_percent:
        raise RuntimeError(
            f"GPU is not idle: {snapshot['utilization_percent']}% > {maximum_percent}%"
        )


def snapshot_boundaries(plan, output) -> dict[str, torch.Tensor]:
    return {name: tensor.clone() for name, tensor in boundary_tensors(plan, output).items()}


def dump_compiled(compiled, stem: str, output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    result = {}
    for attribute, suffix in (("__ptx__", "ptx"), ("__cubin__", "cubin")):
        value = getattr(compiled, attribute, None)
        if callable(value):
            value = value()
        if value is None:
            raise RuntimeError(f"compiled object does not expose {attribute}")
        destination = output_dir / f"{stem}.{suffix}"
        if isinstance(value, (bytes, bytearray, memoryview)):
            destination.write_bytes(bytes(value))
        elif isinstance(value, str) and "\n" not in value and Path(value).is_file():
            shutil.copyfile(value, destination)
        elif isinstance(value, str):
            destination.write_text(value)
        else:
            raise RuntimeError(f"unsupported {attribute} value {type(value)!r}")
        result[suffix] = identity(destination)
    return result


def boundary_tensors(plan, output):
    return {
        "qhat": plan.qhat,
        "kpack": plan.kpack,
        "wpack": plan.wpack,
        "upack": plan.upack,
        "cumulative": plan.cumulative,
        "vnew": plan.vnew,
        "h_state": plan.h_state,
        "raw_o": plan.raw_o,
        "output": output,
    }


def compare_boundaries(lhs, rhs) -> dict:
    checks = {}
    for name in lhs:
        a, b = lhs[name], rhs[name]
        af, bf = a.float(), b.float()
        finite_masks = torch.equal(torch.isfinite(af), torch.isfinite(bf))
        nan_masks = torch.equal(torch.isnan(af), torch.isnan(bf))
        inf_masks = torch.equal(torch.isinf(af), torch.isinf(bf))
        bitwise = torch.equal(a, b)
        checks[name] = {
            "bitwise_equal": bool(bitwise),
            "finite_mask_equal": bool(finite_masks),
            "nan_mask_equal": bool(nan_masks),
            "inf_mask_equal": bool(inf_masks),
            "mismatch_count": int((a != b).sum().item()),
            "max_abs": float((af - bf).abs().nan_to_num().max().item()),
        }
    passed = all(
        item["bitwise_equal"]
        and item["finite_mask_equal"]
        and item["nan_mask_equal"]
        and item["inf_mask_equal"]
        for item in checks.values()
    )
    return {"status": "PASS" if passed else "FAIL", "checks": checks}
