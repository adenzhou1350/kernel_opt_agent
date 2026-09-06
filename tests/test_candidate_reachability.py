#!/usr/bin/env python3
"""Dependency-free tests for candidate path/source/cache reachability guards."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from candidate_discovery import validate_smoke_result

SCRIPT = (
    ROOT
    / "runs"
    / "20260902_qwen35_08b_e2e_sm89_v1"
    / "tools"
    / "benchmark_vllm_offline.py"
)
SPEC = importlib.util.spec_from_file_location("benchmark_vllm_offline", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def main() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        source = root / "candidate.py"
        source.write_bytes(b"candidate-v1\n")
        digest = hashlib.sha256(source.read_bytes()).hexdigest()

        observed = MODULE.expected_source_hashes([f"{source}={digest}"])
        assert observed[str(source.resolve())] == digest

        try:
            MODULE.expected_source_hashes([f"{source}={'0' * 64}"])
        except RuntimeError as exc:
            assert "candidate source mismatch" in str(exc)
        else:
            raise AssertionError("mismatched source hash was accepted")

        empty_cache = root / "empty-cache"
        assert MODULE.require_empty_vllm_cache_root(str(empty_cache)).endswith(
            "empty-cache"
        )
        empty_cache.mkdir()
        (empty_cache / "stale-artifact").write_text("stale", encoding="utf-8")
        try:
            MODULE.require_empty_vllm_cache_root(str(empty_cache))
        except RuntimeError as exc:
            assert "may be stale" in str(exc)
        else:
            raise AssertionError("non-empty compile cache was accepted")

        run = root / "run"
        candidate_source = run / "candidates" / "c1" / "kernel.py"
        candidate_source.parent.mkdir(parents=True)
        candidate_source.write_text("candidate = True\n", encoding="utf-8")
        candidate_digest = hashlib.sha256(candidate_source.read_bytes()).hexdigest()
        timing_path = run / "models" / "phase-timing.json"
        timing_path.parent.mkdir(parents=True)
        timing_path.write_text(
            json.dumps({
                "setup_seconds": 30.0,
                "compile_seconds": 20.0,
                "warmup_seconds": 2.0,
                "steady_state_seconds": 0.5,
                "steady_state_samples": 3,
            }),
            encoding="utf-8",
        )
        timing_digest = hashlib.sha256(timing_path.read_bytes()).hexdigest()
        fixed_seconds = 52.0
        fixed_share = fixed_seconds / 52.5
        steady_per_request = 0.5 / 3
        legacy_seconds = 6 * (fixed_seconds + steady_per_request)
        selected_seconds = 2 * (fixed_seconds + 3 * steady_per_request)
        plan_path = run / "models" / "candidate-execution" / "c1.json"
        plan_path.parent.mkdir(parents=True)
        plan_path.write_text(
            json.dumps({
                "schema_version": "candidate-execution-plan-v1",
                "candidate_id": "c1",
                "created_at": "2026-09-07T00:00:00+00:00",
                "inputs": {
                    "phase_timing": {
                        "path": "models/phase-timing.json",
                        "sha256": timing_digest,
                    },
                    "shared_switching_receipt": None,
                },
                "workload": {
                    "arm_count": 2,
                    "requests_per_arm": 3,
                    "total_requests": 6,
                },
                "phase_timing": {
                    "setup_seconds": 30.0,
                    "compile_seconds": 20.0,
                    "warmup_seconds": 2.0,
                    "steady_state_seconds": 0.5,
                    "steady_state_samples": 3,
                    "fixed_seconds": fixed_seconds,
                    "fixed_share": fixed_share,
                },
                "policy": {"fixed_share_threshold": 0.5},
                "selection": {
                    "process_model": "PERSISTENT_PER_ARM",
                    "session_scope": "SINGLE_TREATMENT",
                    "persistent_session_eligible": True,
                    "switching_preserves_treatment_identity": False,
                    "requires_persistent_session_protocol": True,
                    "reason": "fixed cost dominates but shared switching is unproven",
                },
                "estimates": {
                    "legacy_cold_per_request_seconds": legacy_seconds,
                    "selected_seconds": selected_seconds,
                    "selected_session_count": 2,
                    "estimated_experiment_speedup": legacy_seconds / selected_seconds,
                },
                "claim_scope": "EXECUTION_ROUTING_ONLY_NOT_CANDIDATE_PERFORMANCE",
            }),
            encoding="utf-8",
        )
        plan_digest = hashlib.sha256(plan_path.read_bytes()).hexdigest()
        item = {
            "candidate_id": "c1",
            "execution_plan": {
                "path": "models/candidate-execution/c1.json",
                "sha256": plan_digest,
            },
        }
        def write_session_receipt(label: str) -> dict:
            stdout = run / f"{label}.stdout.ndjson"
            stderr = run / f"{label}.stderr.txt"
            stdout.write_text("ready\nresult\n", encoding="utf-8")
            stderr.write_text("", encoding="utf-8")
            treatment = hashlib.sha256(label.encode()).hexdigest()
            receipt = {
                "schema_version": "persistent-session-receipt-v1",
                "status": "PASS",
                "failure": None,
                "session_scope": "SINGLE_TREATMENT",
                "switching_supported": False,
                "process_launches": 1,
                "engine_init_count": 1,
                "session_identity": hashlib.sha256(b"fixture-worker").hexdigest(),
                "request_count": 3,
                "requests": [
                    {
                        "treatment_identity": treatment,
                        "output_digest": hashlib.sha256(
                            f"{label}-{index}".encode()
                        ).hexdigest(),
                    }
                    for index in range(3)
                ],
                "stdout": {
                    "path": stdout.relative_to(run).as_posix(),
                    "sha256": hashlib.sha256(stdout.read_bytes()).hexdigest(),
                },
                "stderr": {
                    "path": stderr.relative_to(run).as_posix(),
                    "sha256": hashlib.sha256(stderr.read_bytes()).hexdigest(),
                },
            }
            path = run / f"{label}.receipt.json"
            path.write_text(json.dumps(receipt), encoding="utf-8")
            return {
                "path": path.relative_to(run).as_posix(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }

        session_receipts = [
            write_session_receipt("baseline"),
            write_session_receipt("candidate"),
        ]
        smoke_path = run / "smoke.json"
        smoke = {
            "schema_version": "candidate-smoke-result-v6",
            "status": "PASS",
            "candidate_id": "c1",
            "objective": {
                "direction": "minimize",
                "baseline": 10.0,
                "candidate": 8.0,
                "unit": "us",
                "measurement_window": "STEADY_STATE_ONLY",
            },
            "cases": [
                {"case_id": "anchor", "role": "ANCHOR"},
                {"case_id": "edge", "role": "EDGE"},
            ],
            "correctness": {
                "status": "PASS",
                "contract": "EXACT_IDENTITY",
                "oracle": "frozen test output",
                "case_results": [
                    {
                        "case_id": case_id,
                        "role": role,
                        "status": "PASS",
                        "baseline_digest": candidate_digest,
                        "candidate_digest": candidate_digest,
                        "evidence": [{
                            "path": "candidates/c1/kernel.py",
                            "sha256": candidate_digest,
                        }],
                    }
                    for case_id, role in (("anchor", "ANCHOR"), ("edge", "EDGE"))
                ],
            },
            "reachability": {
                "status": "PASS",
                "expected_path": "candidate-kernel",
                "observed_path": "fallback-kernel",
                "compile_cache_policy": "SOURCE_HASHED",
                "execution_proof": {
                    "kind": "KERNEL_INSTANCE_COUNT",
                    "scope": "candidate kernel inside compiled decode graph",
                    "observed_count": 1,
                    "minimum_count": 1,
                    "evidence_index": 0,
                },
                "evidence": [
                    {
                        "path": "candidates/c1/kernel.py",
                        "sha256": hashlib.sha256(
                            candidate_source.read_bytes()
                        ).hexdigest(),
                    },
                    {
                        "path": "models/candidate-execution/c1.json",
                        "sha256": plan_digest,
                    },
                    *session_receipts,
                ],
            },
            "runtime_contract": {
                "production_execution_mode": "COMPILED",
                "observed_execution_mode": "COMPILED",
                "treatment_materialization": "SOURCE_FILE",
                "compile_cache_key_includes_treatment": True,
                "requires_logical_extent": True,
                "logical_extent_source": "EXPLICIT_RUNTIME_METADATA",
                "treatment_identity_evidence_index": 0,
            },
            "timing_accounting": {
                "setup_seconds": 30.0,
                "compile_seconds": 20.0,
                "warmup_seconds": 2.0,
                "steady_state_seconds": 0.5,
                "steady_state_samples": 3,
                "objective_window": "STEADY_STATE_ONLY",
                "process_model": "PERSISTENT_PER_ARM",
                "persistent_session_eligible": True,
                "switching_preserves_treatment_identity": False,
                "execution_plan_evidence_index": 1,
                "persistent_session_receipt_evidence_indices": [2, 3],
            },
        }
        smoke_path.write_text(json.dumps(smoke), encoding="utf-8")
        try:
            validate_smoke_result(run, smoke_path, item)
        except ValueError as exc:
            assert "execution path was not reached" in str(exc)
        else:
            raise AssertionError("unreachable candidate passed the smoke gate")

        smoke["reachability"]["observed_path"] = "candidate-kernel"
        smoke["reachability"]["execution_proof"]["observed_count"] = 0
        smoke_path.write_text(json.dumps(smoke), encoding="utf-8")
        try:
            validate_smoke_result(run, smoke_path, item)
        except ValueError as exc:
            assert "execution count" in str(exc)
        else:
            raise AssertionError("zero runtime kernel count passed reachability")

        smoke["reachability"]["execution_proof"].update(
            {"kind": "DIRECT_SENTINEL", "observed_count": 1}
        )
        smoke_path.write_text(json.dumps(smoke), encoding="utf-8")
        try:
            validate_smoke_result(run, smoke_path, item)
        except ValueError as exc:
            assert "compiled candidates" in str(exc)
        else:
            raise AssertionError("compiled candidate accepted a host-only sentinel")

        smoke["reachability"]["execution_proof"]["kind"] = (
            "INSTRUMENTED_CALL_COUNT"
        )
        smoke["runtime_contract"]["treatment_materialization"] = (
            "RUNTIME_MONKEYPATCH"
        )
        smoke_path.write_text(json.dumps(smoke), encoding="utf-8")
        try:
            validate_smoke_result(run, smoke_path, item)
        except ValueError as exc:
            assert "runtime monkeypatch" in str(exc)
        else:
            raise AssertionError("compiled candidate accepted a runtime monkeypatch")

        smoke["runtime_contract"]["treatment_materialization"] = "SOURCE_FILE"
        smoke["runtime_contract"]["observed_execution_mode"] = "EAGER"
        smoke_path.write_text(json.dumps(smoke), encoding="utf-8")
        try:
            validate_smoke_result(run, smoke_path, item)
        except ValueError as exc:
            assert "does not match production" in str(exc)
        else:
            raise AssertionError("mismatched runtime mode passed reachability")

        smoke["runtime_contract"]["observed_execution_mode"] = "COMPILED"
        smoke["runtime_contract"]["compile_cache_key_includes_treatment"] = False
        smoke_path.write_text(json.dumps(smoke), encoding="utf-8")
        try:
            validate_smoke_result(run, smoke_path, item)
        except ValueError as exc:
            assert "cache key" in str(exc)
        else:
            raise AssertionError("unbound compiled treatment cache passed")

        smoke["runtime_contract"]["compile_cache_key_includes_treatment"] = True
        smoke["runtime_contract"]["logical_extent_source"] = (
            "PHYSICAL_TENSOR_SHAPE"
        )
        smoke_path.write_text(json.dumps(smoke), encoding="utf-8")
        try:
            validate_smoke_result(run, smoke_path, item)
        except ValueError as exc:
            assert "logical extents" in str(exc)
        else:
            raise AssertionError("compiled logical extent accepted physical shape")

        smoke["runtime_contract"]["logical_extent_source"] = (
            "EXPLICIT_RUNTIME_METADATA"
        )
        smoke["timing_accounting"]["process_model"] = (
            "PERSISTENT_SHARED_ENGINE"
        )
        smoke_path.write_text(json.dumps(smoke), encoding="utf-8")
        try:
            validate_smoke_result(run, smoke_path, item)
        except ValueError as exc:
            assert "differs from the sealed execution plan" in str(exc)
        else:
            raise AssertionError("unsafe shared persistent engine passed")

        smoke["timing_accounting"]["process_model"] = "PERSISTENT_PER_ARM"
        smoke["objective"]["measurement_window"] = "END_TO_END_WITH_SETUP"
        smoke_path.write_text(json.dumps(smoke), encoding="utf-8")
        try:
            validate_smoke_result(run, smoke_path, item)
        except ValueError as exc:
            assert "measurement windows differ" in str(exc)
        else:
            raise AssertionError("cold-start objective attribution passed")

        smoke["objective"]["measurement_window"] = "STEADY_STATE_ONLY"

        smoke["reachability"]["compile_cache_policy"] = "NOT_COMPILED"
        smoke["correctness"]["case_results"][0]["candidate_digest"] = "0" * 64
        smoke_path.write_text(json.dumps(smoke), encoding="utf-8")
        try:
            validate_smoke_result(run, smoke_path, item)
        except ValueError as exc:
            assert "EXACT_IDENTITY" in str(exc)
        else:
            raise AssertionError("mismatching exact output passed the correctness gate")

    print("candidate reachability test: PASS")


if __name__ == "__main__":
    main()
