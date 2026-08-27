#!/usr/bin/env python3
"""Compile the CuTe layout proof for sm_120a without invoking it."""

from __future__ import annotations

import argparse
import shutil
from datetime import datetime, timezone
from pathlib import Path

import cutlass
import cutlass.cute as cute

from common import candidate_dir, dump, identity, production_sources
from layout_proof import N2AccumulatorLayoutProof


def dump_compiled_artifact(compiled, attribute: str, destination: Path) -> dict:
    value = getattr(compiled, attribute, None)
    if callable(value):
        value = value()
    if value is None:
        raise RuntimeError(f"compiled proof does not expose {attribute}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, (bytes, bytearray, memoryview)):
        destination.write_bytes(bytes(value))
    elif isinstance(value, str) and "\n" not in value and Path(value).is_file():
        shutil.copyfile(value, destination)
    elif isinstance(value, str):
        destination.write_text(value)
    else:
        raise RuntimeError(f"unsupported compiled artifact type: {type(value)!r}")
    return identity(destination)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    run = args.run.resolve()
    source_root = candidate_dir(run)
    build = run / "experiments/req-n2-static-layout-admissibility/build"
    build.mkdir(parents=True, exist_ok=True)

    proof = N2AccumulatorLayoutProof()
    options = (
        cute.GPUArch("sm_120a"),
        cute.KeepPTX(True),
        cute.KeepCUBIN(True),
    )
    compiled = cute.compile[options](proof)
    # Deliberately do not call `compiled()`: no CUDA kernel is launched.
    ptx = dump_compiled_artifact(compiled, "__ptx__", build / "layout_proof.ptx")
    cubin = dump_compiled_artifact(compiled, "__cubin__", build / "layout_proof.cubin")

    manifest = {
        "schema_version": "n2-static-layout-build-v1",
        "status": "PASS",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "target": {"architecture": "sm_120a", "device_launch_required": False},
        "cutlass_version": getattr(cutlass, "__version__", "unknown"),
        "compile_action": "cute.compile only",
        "compiled_callable_invocations": 0,
        "cuda_kernel_launches": 0,
        "artifacts": {"ptx": ptx, "cubin": cubin},
        "proof_sources": [
            identity(source_root / "layout_proof.py"),
            identity(source_root / "clean_build.py"),
        ],
        "production_sources": {
            name: identity(path) for name, path in production_sources().items()
        },
    }
    dump(build / "manifest.json", manifest)
    print("PASS: CuTe compiler/type proof built; compiled callable invocations=0; CUDA launches=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
