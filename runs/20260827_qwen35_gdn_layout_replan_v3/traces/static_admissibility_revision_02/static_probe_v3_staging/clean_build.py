#!/usr/bin/env python3
"""Build two PASS-only static proof artifacts without invoking a kernel."""

from __future__ import annotations

import argparse
import json
import shutil
import traceback
from datetime import datetime, timezone
from pathlib import Path

import cutlass.cute as cute
import torch
from cutlass.cute.runtime import from_dlpack
from torch._subclasses.fake_tensor import FakeTensorMode

from common import (
    PRODUCTION_SOURCES,
    candidate_dir,
    dump,
    experiment_dir,
    identity,
    verify_cutlass_layout_sources,
    verify_production_sources,
)
from layout_proof import (
    BT,
    D,
    N2LongStaticLayoutProof,
    N2ShortStaticLayoutProof,
    oracle_witness_rows,
    production_ast_binding,
    proof_ast_binding,
    validate_ast_triplet,
)


def dump_compiled_artifact(compiled, attribute: str, destination: Path) -> dict:
    value = getattr(compiled, attribute, None)
    if callable(value):
        value = value()
    if value is None:
        raise RuntimeError(f"INFRA_FAILURE: compiled proof does not expose {attribute}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, (bytes, bytearray, memoryview)):
        destination.write_bytes(bytes(value))
    elif isinstance(value, str) and "\n" not in value and Path(value).is_file():
        shutil.copyfile(value, destination)
    elif isinstance(value, str):
        destination.write_text(value)
    else:
        raise RuntimeError(f"INFRA_FAILURE: unsupported artifact type: {type(value)!r}")
    return identity(destination)


def compile_only(proof, build: Path, stem: str) -> dict:
    options = (cute.GPUArch("sm_120a"), cute.KeepPTX(True), cute.KeepCUBIN(True))
    try:
        with FakeTensorMode():
            fake_sink = torch.empty((D, BT), dtype=torch.float32, device="cuda")
            compiled = cute.compile[options](proof, from_dlpack(fake_sink))
        return {
            "ptx": dump_compiled_artifact(compiled, "__ptx__", build / f"{stem}.ptx"),
            "cubin": dump_compiled_artifact(compiled, "__cubin__", build / f"{stem}.cubin"),
        }
    except Exception as error:
        dump(build / f"{stem}_infrastructure_failure.json", {
            "schema_version": "static-proof-infrastructure-failure-v2",
            "status": "INFRA_FAILURE",
            "exception_type": type(error).__name__,
            "exception": str(error),
            "traceback": traceback.format_exc(),
            "candidate_disposition": "NONE",
        })
        raise RuntimeError(f"INFRA_FAILURE: CuTe compile/codegen failed for {stem}") from error


def write_witness(path: Path, rows: list[dict]) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    temporary.replace(path)
    return identity(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    run = args.run.resolve()
    source_root = candidate_dir(run)
    experiment = experiment_dir(run)
    build = experiment / "build"
    static = experiment / "static"
    build.mkdir(parents=True, exist_ok=True)

    production_bindings = verify_production_sources()
    cutlass_bindings = verify_cutlass_layout_sources()
    production_ast = {
        name: production_ast_binding(name, path)
        for name, path in PRODUCTION_SOURCES.items()
    }
    proof_ast = proof_ast_binding(source_root / "layout_proof.py")
    ast_triplet = validate_ast_triplet(
        production_ast["short"], production_ast["long"], proof_ast
    )
    ast_report_path = static / "production_proof_ast_binding.json"
    dump(ast_report_path, {
        "schema_version": "production-proof-o1-ast-binding-v2",
        "status": "PASS",
        "production_source_identities": production_bindings,
        "cutlass_layout_source_identities": cutlass_bindings,
        "production_bindings": production_ast,
        "proof_binding": proof_ast,
        "triplet_check": ast_triplet,
    })

    rows, oracle_summary = oracle_witness_rows()
    witness_path = static / "layout_oracle.jsonl"
    witness_identity = write_witness(witness_path, rows)
    mapping_report_path = static / "mapping_report.json"
    dump(mapping_report_path, {
        "schema_version": "n2-independent-oracle-report-v3",
        "status": "EXPECTED_ORACLE_READY",
        "summary": oracle_summary,
        "witness_identity": witness_identity,
        "expected_record_count": D * BT,
        "proof_domain": {"threads": 256, "tiles_per_thread": 4, "slots_per_tile": 8},
        "oracle_role": "independent PTX mapping; actual CuTe mappings are compiler-resolved assertions",
        "actual_cute_evidence": {
            "o1": "tv_layout_C_tiled plus partition_C(identity(D,BT))",
            "scorev": "tv_layout_C_tiled plus partition_C(local_tile(identity,DxN16))",
            "backing": "output.layout plus logical_divide plus slice_and_offset plus crd2idx",
            "negative": "exact attempt-2 one-warp fragment plus cute.append layout",
        },
        "physical_register_number_claim": "NOT_MADE; only CuTe logical iterator offsets are tested",
    })

    # A partial compile cannot create a consumable manifest.  Any failure is
    # INVALID/BLOCKED and leaves N2 undisposed; binary_pass=0 is impossible.
    artifacts = {
        "short": compile_only(
            N2ShortStaticLayoutProof(), build, "n2_layout_admit_short_static"
        ),
        "long": compile_only(
            N2LongStaticLayoutProof(), build, "n2_layout_admit_long_static"
        ),
    }

    manifest_path = build / "manifest.json"
    dump(manifest_path, {
        "schema_version": "n2-static-layout-build-v3",
        "status": "PASS",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "predicate_outcome": "PASS",
        "binary_pass": 1,
        "target": {"architecture": "sm_120a", "device_launch_required": False},
        "compile_action": "cute.compile with FakeTensor only",
        "compiled_callable_invocations": 0,
        "cuda_kernel_launches": 0,
        "gpu_performance_samples": 0,
        "artifacts": artifacts,
        "ast_report_identity": identity(ast_report_path),
        "mapping_report_identity": identity(mapping_report_path),
        "proof_sources": [
            identity(source_root / "layout_proof.py"),
            identity(source_root / "clean_build.py"),
        ],
        "production_sources": production_bindings,
        "cutlass_layout_sources": cutlass_bindings,
        "failure_semantics": "ANY_FAILURE_IS_INVALID_WITHOUT_N2_DISPOSITION",
        "candidate_disposition_scope": "STATIC_LAYOUT_ONLY",
    })
    print("PASS: static admission build completed; CUDA launches=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
