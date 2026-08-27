#!/usr/bin/env python3
"""Build PASS or controlled-REJECT marker artifacts without invoking a kernel."""

from __future__ import annotations

import argparse
import shutil
import traceback
from datetime import datetime, timezone
from pathlib import Path

import cutlass.cute as cute
import torch
from cutlass.cute.runtime import from_dlpack
from torch._subclasses.fake_tensor import FakeTensorMode

from common import PRODUCTION_SOURCES, candidate_dir, dump, experiment_dir, identity, verify_production_sources
from layout_proof import D, BT, N2LiveCodegenProof, StaticRejectMarker, ast_binding, exhaustive_mapping_rows, validate_ast_pair


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
        raise RuntimeError(f"INFRA_FAILURE: unsupported compiled artifact type: {type(value)!r}")
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
            "schema_version": "static-proof-infrastructure-failure-v1",
            "status": "INFRA_FAILURE", "exception_type": type(error).__name__,
            "exception": str(error), "traceback": traceback.format_exc(),
            "candidate_disposition": "NONE",
        })
        raise RuntimeError(f"INFRA_FAILURE: CuTe compile/codegen failed for {stem}") from error


def write_witness(path: Path, rows: list[dict]) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w") as handle:
        for row in rows:
            import json
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
    bindings = verify_production_sources()

    ast_bindings = {name: ast_binding(name, path) for name, path in PRODUCTION_SOURCES.items()}
    ast_pair = validate_ast_pair(ast_bindings["short"], ast_bindings["long"])
    ast_report_path = static / "production_ast_binding.json"
    dump(ast_report_path, {
        "schema_version": "production-o1-ast-binding-v1", "status": "PASS",
        "source_identities": bindings, "bindings": ast_bindings, "pair_check": ast_pair,
    })

    predicate_outcome = "PASS"
    predicate_id = None
    rows: list[dict] = []
    try:
        rows, mapping_summary = exhaustive_mapping_rows()
    except AssertionError as error:
        if not str(error).startswith("PREDICATE_REJECT:"):
            raise
        predicate_outcome = "REJECT"
        predicate_id = str(error).split(":", 1)[1].strip()
        mapping_summary = {"status": "PREDICATE_REJECT", "predicate_id": predicate_id}
    witness_path = static / "layout_witness.jsonl"
    witness_identity = write_witness(witness_path, rows)
    mapping_report_path = static / "mapping_report.json"
    dump(mapping_report_path, {
        "schema_version": "n2-exhaustive-mapping-report-v2",
        "predicate_outcome": predicate_outcome, "predicate_id": predicate_id,
        "summary": mapping_summary, "witness_identity": witness_identity,
        "expected_record_count": D * BT,
        "proof_domain": {"threads": 256, "tiles_per_thread": 4, "slots_per_tile": 8},
        "physical_register_number_claim": "NOT_MADE; absolute_fragment_offset is the logical backing-fragment offset",
    })

    if predicate_outcome == "PASS":
        artifacts = {
            "short": compile_only(N2LiveCodegenProof(512), build, "n2_layout_admit_short_live"),
            "long": compile_only(N2LiveCodegenProof(256), build, "n2_layout_admit_long_live"),
        }
    else:
        artifacts = {"reject_marker": compile_only(StaticRejectMarker(), build, "n2_layout_reject_marker")}

    manifest_path = build / "manifest.json"
    dump(manifest_path, {
        "schema_version": "n2-static-layout-build-v2", "status": "PASS",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "predicate_outcome": predicate_outcome, "binary_pass": 1 if predicate_outcome == "PASS" else 0,
        "predicate_id": predicate_id,
        "target": {"architecture": "sm_120a", "device_launch_required": False},
        "compile_action": "cute.compile with FakeTensor only",
        "compiled_callable_invocations": 0, "cuda_kernel_launches": 0, "gpu_performance_samples": 0,
        "artifacts": artifacts,
        "ast_report_identity": identity(ast_report_path),
        "mapping_report_identity": identity(mapping_report_path),
        "proof_sources": [identity(source_root / "layout_proof.py"), identity(source_root / "clean_build.py")],
        "production_sources": bindings,
        "candidate_disposition_scope": "STATIC_LAYOUT_ONLY",
    })
    print(f"PASS: controlled static build completed; predicate_outcome={predicate_outcome}; CUDA launches=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
