#!/usr/bin/env python3
"""Exercise the post-materialization feasibility and duplicate-PR gates."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from community_knowledge import atomic_json, sha256_file  # noqa: E402
from community_materialized_feasibility import (  # noqa: E402
    build_assessment,
    validate_assessment,
)


def identity(path: Path) -> dict:
    return {"path": path.resolve().as_posix(), "sha256": sha256_file(path)}


def write_inputs(base: Path) -> tuple[Path, Path, Path, Path, Path]:
    task = base / "task.json"
    screen = base / "screen.json"
    profile = base / "profile.json"
    resource_status = base / "resource-status.json"
    baseline = base / "baseline.py"
    baseline.write_text("def baseline():\n    return 1\n", encoding="utf-8")
    atomic_json(
        resource_status,
        {
            "schema_version": "community-materialized-resource-status-v1",
            "observed_at": "2026-09-07T05:00:00Z",
            "claim_boundary": "POINT_IN_TIME_READ_ONLY_OBSERVATION",
            "resources": [
                {
                    "resource_id": "single-sm120-32g",
                    "availability": "AVAILABLE",
                    "vendor": "NVIDIA",
                    "device_name": "NVIDIA GeForce RTX 5090",
                    "architecture": "sm120",
                    "memory_gib_per_gpu": 32,
                    "l2_cache_mib": 96,
                    "gpu_indices": [0],
                    "excluded_gpu_indices": [],
                    "active_compute_process_count": 0,
                }
            ],
            "actions": {
                "processes_stopped": 0,
                "gpu_benchmarks_started": 0,
                "compilations_started": 0,
            },
        },
    )
    atomic_json(
        task,
        {
            "schema_version": "community-heldout-task-v2",
            "task_id": "example.materialized-task",
            "information_policy": "SYMPTOM_CONTRACT_AND_BASELINE_ONLY",
            "objective": "Make the operator faster without changing results.",
            "operator": {
                "equation": "y = x",
                "input_shapes": ["x: [B, H]"],
                "input_dtype": "bfloat16",
                "output_dtype": "bfloat16",
                "layout": "contiguous",
                "numerical_contract": "exact",
                "aliasing": "inputs are read-only",
            },
            "workload": {
                "primary_mode": "decode",
                "shape_weights": {"B=1": 1.0},
                "integration": "example runtime",
                "latency_objective": "median GPU latency",
                "required_controls": ["randomized paired order"],
            },
            "hardware": {
                "device": "NVIDIA RTX 5090",
                "compute_capability": "sm120",
                "memory_gib": 31.0,
                "software": "CUDA test runtime",
                "allowed_programming_models": ["PyTorch CUDA"],
            },
            "baseline": {
                "implementation": "baseline.py",
                "observed_symptom": "redundant work",
                "candidate_bottlenecks": ["launch overhead"],
                "bottleneck_status": "STATIC_ONLY",
                "claim_boundary": "TASK_INPUT_NOT_RESULT",
            },
            "acceptance": {
                "correctness": ["exact output"],
                "performance": ["at least 1.02x"],
                "upstream": "reproducible patch",
            },
        },
    )
    atomic_json(
        screen,
        {
            "schema_version": "community-feasibility-screen-v1",
            "generated_at": "2026-09-07T05:00:00Z",
            "claim_boundary": "FEASIBILITY_ACCOUNTING_NOT_PERFORMANCE_EVIDENCE",
            "registration": "PRESELECTION",
            "input_identity": {
                "queue": identity(baseline),
                "policy": identity(baseline),
                "execution_profile": identity(baseline),
            },
            "inventory": {
                "selected_queue_count": 1,
                "eligible_count": 1,
                "infeasible_count": 0,
                "harness_blocked_count": 0,
            },
            "items": [
                {
                    "repository": "example/project",
                    "pr_number": 7,
                    "queue_priority_rank": 1,
                    "task_family": "GENERAL_GPU_RUNTIME",
                    "matched_rule_id": "default",
                    "requirements": {},
                    "status": "ELIGIBLE",
                    "reason": "DECLARED_RESOURCE_AND_HARNESS_READY",
                    "candidate_resource_ids": ["single-sm120-32g"],
                    "ready_resource_ids": ["single-sm120-32g"],
                    "harness_status": "READY",
                }
            ],
        },
    )
    atomic_json(
        profile,
        {
            "schema_version": "community-execution-profile-v1",
            "profile_id": "test-sm120",
            "observed_at": "2026-09-07T05:00:00Z",
            "claim_boundary": "DECLARED_AVAILABILITY_NOT_LIVE_PROOF",
            "resources": [
                {
                    "resource_id": "single-sm120-32g",
                    "availability": "AVAILABLE",
                    "vendor": "NVIDIA",
                    "architecture": "sm120",
                    "device_name": "NVIDIA GeForce RTX 5090",
                    "l2_cache_mib": 96,
                    "gpu_count": 1,
                    "memory_gib_per_gpu": 32,
                    "capabilities": ["CUDA", "PYTORCH"],
                    "constraints": [],
                }
            ],
            "harnesses": [],
        },
    )
    return task, screen, profile, resource_status, baseline


def manifest_object(
    task: Path,
    screen: Path,
    profile: Path,
    resource_status: Path,
    baseline: Path,
) -> dict:
    return {
        "schema_version": "community-materialization-manifest-v1",
        "generated_at": "2026-09-07T05:01:00Z",
        "claim_boundary": "DECLARED_POST_SELECTION_INPUTS_NOT_EXECUTION_AUTHORITY",
        "task": identity(task),
        "preselection_screen": identity(screen),
        "execution_profile": identity(profile),
        "resource_status": identity(resource_status),
        "candidate": {
            "repository": "example/project",
            "pr_number": 7,
            "purpose": "BLIND_REDISCOVERY",
            "existing_reference_pr": "https://github.com/example/project/pull/7",
        },
        "target_resource_ids": ["single-sm120-32g"],
        "artifacts": [
            {
                "role": "BASELINE_SOURCE",
                "required": True,
                "status": "READY",
                "reason": "EXACT_BASELINE_PRESENT",
                "evidence": [identity(baseline)],
            },
            {
                "role": "OPERATOR_HARNESS",
                "required": True,
                "status": "MISSING",
                "reason": "EXACT_HARNESS_NOT_MATERIALIZED",
                "evidence": [],
            },
            {
                "role": "LIVE_HARDWARE_STATUS",
                "required": True,
                "status": "READY",
                "reason": "READ_ONLY_STATUS_CAPTURED",
                "evidence": [identity(resource_status)],
            },
        ],
    }


def v2_manifest_object(
    task: Path,
    screen: Path,
    profile: Path,
    resource_status: Path,
    evidence: Path,
) -> dict:
    manifest = manifest_object(task, screen, profile, resource_status, evidence)
    manifest["schema_version"] = "community-materialization-manifest-v2"
    manifest["hardware_match"] = {
        "device_names_any": ["NVIDIA GeForce RTX 5090"],
        "minimum_l2_cache_mib": 96,
        "maximum_l2_cache_mib": 128,
        "required_capabilities_all": ["CUDA", "PYTORCH"],
        "maximum_resource_status_age_seconds": 300,
    }
    manifest["candidate"] = {
        "repository": "example/project",
        "pr_number": 7,
        "purpose": "NEW_UPSTREAM_WORK",
        "existing_reference_pr": None,
    }
    manifest["artifacts"] = [
        {
            "role": role,
            "required": True,
            "status": "READY",
            "reason": "HASH_BOUND_TEST_EVIDENCE",
            "evidence": [identity(evidence)],
        }
        for role in (
            "BASELINE_SOURCE",
            "OPERATOR_HARNESS",
            "WHOLE_MODEL_HARNESS",
            "MODEL_OR_WEIGHTS",
            "RUNTIME_OR_ENVIRONMENT",
            "LIVE_HARDWARE_STATUS",
        )
    ]
    return manifest


def v3_manifest_object(
    task: Path,
    screen: Path,
    profile: Path,
    resource_status: Path,
    evidence: Path,
) -> dict:
    live = json.loads(resource_status.read_text(encoding="utf-8"))
    live["schema_version"] = "community-materialized-resource-status-v2"
    resource = live["resources"][0]
    resource["devices"] = [
        {
            "gpu_index": 0,
            "memory_used_mib": 2,
            "memory_total_mib": 32607,
            "utilization_percent": 0,
            "pstate": "P8",
            "active_compute_process_count": 0,
        }
    ]
    atomic_json(resource_status, live)
    manifest = v2_manifest_object(task, screen, profile, resource_status, evidence)
    manifest["schema_version"] = "community-materialization-manifest-v3"
    manifest["resource_status"] = identity(resource_status)
    manifest["hardware_match"].update(
        {
            "minimum_ready_gpu_count": 1,
            "maximum_gpu_utilization_percent": 10,
            "maximum_used_memory_mib_per_gpu": 1024,
            "require_zero_active_compute_processes": True,
        }
    )
    live_artifact = next(
        item for item in manifest["artifacts"] if item["role"] == "LIVE_HARDWARE_STATUS"
    )
    live_artifact["evidence"] = [identity(resource_status)]
    return manifest


def v4_manifest_object(
    task: Path,
    screen: Path,
    profile: Path,
    resource_status: Path,
    evidence: Path,
) -> tuple[dict, Path]:
    manifest = v3_manifest_object(task, screen, profile, resource_status, evidence)
    runtime_receipt = resource_status.with_name("runtime-preflight.json")
    atomic_json(
        runtime_receipt,
        {
            "schema_version": "community-runtime-preflight-receipt-v1",
            "observed_at": "2026-09-07T05:00:30Z",
            "claim_boundary": "CPU_ONLY_IMPORT_AND_SOURCE_IDENTITY_NOT_GPU_EXECUTION",
            "status": "PASS",
            "resource_id": "single-sm120-32g",
            "environment": {
                "root": "/opt/isolated-runtime",
                "python_executable": "/opt/isolated-runtime/bin/python",
                "python_binary_resolved": "/usr/bin/python3.12",
                "python_executable_sha256": "a" * 64,
                "python_version": "3.12.11",
                "observed_sys_executable": "/opt/isolated-runtime/bin/python",
                "observed_sys_prefix": "/opt/isolated-runtime",
                "observed_sys_base_prefix": "/usr",
                "python_inside_environment_root": True,
                "python_prefix_matches_environment_root": True,
            },
            "pythonpath_roots": ["/work/sglang/python"],
            "forbidden_roots": ["/home/oem/h3-single-5090"],
            "source_checkout": {
                "path": "/work/sglang",
                "expected_commit": "b" * 40,
                "observed_commit": "b" * 40,
                "dirty": False,
            },
            "probes": [
                {
                    "module": "torch",
                    "status": "PASS",
                    "version": "2.9.1",
                    "origin": "/opt/isolated-runtime/lib/python3.12/site-packages/torch/__init__.py",
                    "origin_allowed": True,
                    "error_type": None,
                    "error_message": None,
                }
            ],
            "checks": {
                "all_imports_passed": True,
                "all_origins_allowed": True,
                "source_commit_matches": True,
                "source_checkout_clean": True,
                "python_inside_environment_root": True,
                "python_prefix_matches_environment_root": True,
                "environment_outside_forbidden_roots": True,
                "cuda_initialized_after_imports": False,
            },
            "actions": {
                "packages_installed_by_preflight": False,
                "compilation_requested_by_preflight": False,
                "gpu_benchmarks_started": 0,
            },
        },
    )
    manifest["schema_version"] = "community-materialization-manifest-v4"
    manifest["runtime_receipt"] = identity(runtime_receipt)
    manifest["runtime_receipt_maximum_age_seconds"] = 300
    runtime_artifact = next(
        item
        for item in manifest["artifacts"]
        if item["role"] == "RUNTIME_OR_ENVIRONMENT"
    )
    runtime_artifact["status"] = "READY"
    runtime_artifact["reason"] = "CPU_ONLY_IMPORT_PREFLIGHT_PASSED"
    runtime_artifact["evidence"] = [identity(runtime_receipt)]
    return manifest, runtime_receipt


def test_materialized_gate_blocks_missing_harness_and_duplicate_upstream() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        task, screen, profile, resource_status, baseline = write_inputs(base)
        manifest_path = base / "manifest.json"
        manifest = manifest_object(task, screen, profile, resource_status, baseline)
        atomic_json(manifest_path, manifest)
        blocked = build_assessment(manifest_path, ROOT)
        assert blocked["decision"] == "HARNESS_BLOCKED"
        assert blocked["matched_resource_ids"] == ["single-sm120-32g"]
        assert blocked["blockers"] == ["MISSING_OPERATOR_HARNESS"]
        assert not blocked["allowed_actions"]["request_supervisor_review"]

        harness = base / "harness.py"
        harness.write_text("def run():\n    return 1\n", encoding="utf-8")
        manifest["artifacts"][1] = {
            "role": "OPERATOR_HARNESS",
            "required": True,
            "status": "READY",
            "reason": "EXACT_HARNESS_PRESENT",
            "evidence": [identity(harness)],
        }
        manifest["candidate"]["purpose"] = "NEW_UPSTREAM_WORK"
        atomic_json(manifest_path, manifest)
        duplicate = build_assessment(manifest_path, ROOT)
        assert duplicate["decision"] == "UPSTREAM_DUPLICATE"
        assert duplicate["blockers"] == ["EXISTING_UPSTREAM_PR_TARGET"]
        assert not duplicate["allowed_actions"]["package_upstream_pr"]

        manifest["candidate"]["purpose"] = "BLIND_REDISCOVERY"
        atomic_json(manifest_path, manifest)
        eligible = build_assessment(manifest_path, ROOT)
        assert eligible["decision"] == "ELIGIBLE_FOR_SUPERVISOR_REVIEW"
        assert eligible["allowed_actions"]["request_supervisor_review"]
        assert not eligible["allowed_actions"]["dispatch_gpu"]
        assessment_path = base / "assessment.json"
        atomic_json(assessment_path, eligible)
        assert validate_assessment(assessment_path, ROOT)["status"] == "PASS"

        edited = json.loads(assessment_path.read_text(encoding="utf-8"))
        edited["allowed_actions"]["dispatch_gpu"] = True
        atomic_json(assessment_path, edited)
        try:
            validate_assessment(assessment_path, ROOT)
        except ValueError as error:
            assert "expected constant False" in str(error)
        else:
            raise AssertionError("edited dispatch authority passed validation")


def test_v2_requires_runtime_and_blocks_an_unverified_environment() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        task, screen, profile, resource_status, baseline = write_inputs(base)
        manifest_path = base / "manifest.json"
        manifest = v2_manifest_object(task, screen, profile, resource_status, baseline)
        runtime = next(
            item
            for item in manifest["artifacts"]
            if item["role"] == "RUNTIME_OR_ENVIRONMENT"
        )
        runtime["status"] = "UNVERIFIED"
        runtime["reason"] = "DRIVER_EXISTS_BUT_TARGET_RUNTIME_IS_NOT_INSTALLED"
        atomic_json(manifest_path, manifest)

        blocked = build_assessment(manifest_path, ROOT)
        assert blocked["schema_version"] == "community-materialized-feasibility-v2"
        assert blocked["decision"] == "HARNESS_BLOCKED"
        assert blocked["blockers"] == ["UNVERIFIED_RUNTIME_OR_ENVIRONMENT"]
        assert blocked["matched_resource_ids"] == ["single-sm120-32g"]
        assert blocked["resource_match_diagnostics"] == [
            {
                "resource_id": "single-sm120-32g",
                "matched": True,
                "reasons": [],
            }
        ]
        assert not blocked["allowed_actions"]["dispatch_gpu"]

        manifest["artifacts"] = [
            item
            for item in manifest["artifacts"]
            if item["role"] != "RUNTIME_OR_ENVIRONMENT"
        ]
        atomic_json(manifest_path, manifest)
        try:
            build_assessment(manifest_path, ROOT)
        except ValueError as error:
            assert "invalid materialization manifest" in str(error)
        else:
            raise AssertionError("v2 manifest omitted the runtime role")


def test_v2_rejects_coarse_sm_family_match_when_device_and_l2_do_not_match() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        task, screen, profile, resource_status, baseline = write_inputs(base)
        task_object = json.loads(task.read_text(encoding="utf-8"))
        task_object["hardware"]["device"] = "NVIDIA GB10"
        task_object["hardware"]["compute_capability"] = "sm121"
        atomic_json(task, task_object)

        manifest_path = base / "manifest.json"
        manifest = v2_manifest_object(task, screen, profile, resource_status, baseline)
        manifest["task"] = identity(task)
        manifest["hardware_match"] = {
            "device_names_any": ["NVIDIA GB10"],
            "minimum_l2_cache_mib": None,
            "maximum_l2_cache_mib": 24,
            "required_capabilities_all": ["CUDA"],
            "maximum_resource_status_age_seconds": 300,
        }
        atomic_json(manifest_path, manifest)

        blocked = build_assessment(manifest_path, ROOT)
        assert blocked["decision"] == "RESOURCE_BLOCKED"
        assert blocked["blockers"] == ["NO_MATERIALIZED_RESOURCE_MATCH"]
        assert blocked["matched_resource_ids"] == []
        assert blocked["resource_match_diagnostics"] == [
            {
                "resource_id": "single-sm120-32g",
                "matched": False,
                "reasons": [
                    "ARCHITECTURE_MISMATCH",
                    "DEVICE_NAME_MISMATCH",
                    "L2_CACHE_ABOVE_MAXIMUM",
                ],
            }
        ]
        assert not blocked["allowed_actions"]["dispatch_gpu"]


def test_v2_uses_live_device_identity_instead_of_trusting_the_profile() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        task, screen, profile, resource_status, baseline = write_inputs(base)
        live = json.loads(resource_status.read_text(encoding="utf-8"))
        live["resources"][0]["device_name"] = "NVIDIA RTX PRO 6000 Blackwell"
        live["resources"][0]["l2_cache_mib"] = 128
        atomic_json(resource_status, live)

        manifest_path = base / "manifest.json"
        manifest = v2_manifest_object(task, screen, profile, resource_status, baseline)
        atomic_json(manifest_path, manifest)

        blocked = build_assessment(manifest_path, ROOT)
        assert blocked["decision"] == "RESOURCE_BLOCKED"
        assert blocked["resource_match_diagnostics"] == [
            {
                "resource_id": "single-sm120-32g",
                "matched": False,
                "reasons": [
                    "DEVICE_NAME_MISMATCH",
                    "PROFILE_LIVE_DEVICE_MISMATCH",
                    "PROFILE_LIVE_L2_MISMATCH",
                ],
            }
        ]


def test_v2_rejects_a_stale_live_resource_receipt() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        task, screen, profile, resource_status, baseline = write_inputs(base)
        manifest_path = base / "manifest.json"
        manifest = v2_manifest_object(task, screen, profile, resource_status, baseline)
        manifest["generated_at"] = "2026-09-07T06:00:00Z"
        atomic_json(manifest_path, manifest)

        try:
            build_assessment(manifest_path, ROOT)
        except ValueError as error:
            assert "live resource status is too old" in str(error)
        else:
            raise AssertionError("v2 manifest accepted a stale live resource receipt")


def test_v3_requires_enough_idle_per_device_resources() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        task, screen, profile, resource_status, baseline = write_inputs(base)
        manifest = v3_manifest_object(task, screen, profile, resource_status, baseline)

        live = json.loads(resource_status.read_text(encoding="utf-8"))
        resource = live["resources"][0]
        resource["gpu_indices"] = list(range(8))
        resource["excluded_gpu_indices"] = [6]
        resource["devices"] = [
            {
                "gpu_index": index,
                "memory_used_mib": 15314 if index == 6 else 2,
                "memory_total_mib": 32607,
                "utilization_percent": 0 if index in {0, 6} else 100,
                "pstate": "P8" if index in {0, 6} else "P0",
                "active_compute_process_count": 0,
            }
            for index in range(8)
        ]
        atomic_json(resource_status, live)
        manifest["resource_status"] = identity(resource_status)
        live_artifact = next(
            item
            for item in manifest["artifacts"]
            if item["role"] == "LIVE_HARDWARE_STATUS"
        )
        live_artifact["evidence"] = [identity(resource_status)]
        manifest["hardware_match"]["minimum_ready_gpu_count"] = 8
        manifest_path = base / "manifest-v3.json"
        atomic_json(manifest_path, manifest)

        blocked = build_assessment(manifest_path, ROOT)
        assert blocked["schema_version"] == "community-materialized-feasibility-v3"
        assert blocked["decision"] == "RESOURCE_BLOCKED"
        assert blocked["resource_match_diagnostics"] == [
            {
                "resource_id": "single-sm120-32g",
                "matched": False,
                "reasons": [
                    "GPU_UTILIZATION_ABOVE_MAXIMUM",
                    "INSUFFICIENT_NON_EXCLUDED_GPU_COUNT",
                    "INSUFFICIENT_READY_GPU_COUNT",
                ],
                "eligible_gpu_indices": [0],
                "device_diagnostics": [
                    {
                        "gpu_index": index,
                        "eligible": index == 0,
                        "reasons": (
                            []
                            if index == 0
                            else [
                                "EXPLICITLY_EXCLUDED"
                                if index == 6
                                else "GPU_UTILIZATION_ABOVE_MAXIMUM"
                            ]
                        ),
                    }
                    for index in range(8)
                ],
            }
        ]

        manifest["hardware_match"]["minimum_ready_gpu_count"] = 1
        atomic_json(manifest_path, manifest)
        eligible = build_assessment(manifest_path, ROOT)
        assert eligible["matched_resource_ids"] == ["single-sm120-32g"]
        assert eligible["resource_match_diagnostics"][0]["reasons"] == []
        assert eligible["resource_match_diagnostics"][0]["eligible_gpu_indices"] == [0]


def test_v4_requires_a_bound_passing_runtime_preflight() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        task, screen, profile, resource_status, baseline = write_inputs(base)
        manifest, runtime_receipt = v4_manifest_object(
            task, screen, profile, resource_status, baseline
        )
        manifest_path = base / "manifest-v4.json"
        atomic_json(manifest_path, manifest)

        eligible = build_assessment(manifest_path, ROOT)
        assert eligible["schema_version"] == "community-materialized-feasibility-v4"
        assert eligible["decision"] == "ELIGIBLE_FOR_SUPERVISOR_REVIEW"
        assert eligible["inputs"]["runtime_receipt"] == identity(runtime_receipt)
        assert not eligible["allowed_actions"]["dispatch_gpu"]

        failed = json.loads(runtime_receipt.read_text(encoding="utf-8"))
        failed["status"] = "FAIL"
        failed["checks"]["all_imports_passed"] = False
        failed["probes"][0]["status"] = "FAIL"
        failed["probes"][0]["error_type"] = "ImportError"
        failed["probes"][0]["error_message"] = "missing dependency"
        atomic_json(runtime_receipt, failed)
        manifest["runtime_receipt"] = identity(runtime_receipt)
        runtime_artifact = next(
            item
            for item in manifest["artifacts"]
            if item["role"] == "RUNTIME_OR_ENVIRONMENT"
        )
        runtime_artifact["evidence"] = [identity(runtime_receipt)]
        atomic_json(manifest_path, manifest)
        try:
            build_assessment(manifest_path, ROOT)
        except ValueError as error:
            assert "runtime preflight receipt did not pass" in str(error)
        else:
            raise AssertionError("v4 manifest accepted a failing runtime preflight")


def test_v4_rejects_a_stale_runtime_preflight() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        task, screen, profile, resource_status, baseline = write_inputs(base)
        manifest, _ = v4_manifest_object(
            task, screen, profile, resource_status, baseline
        )
        manifest["runtime_receipt_maximum_age_seconds"] = 10
        manifest_path = base / "manifest-v4-stale-runtime.json"
        atomic_json(manifest_path, manifest)

        try:
            build_assessment(manifest_path, ROOT)
        except ValueError as error:
            assert "runtime preflight receipt is too old" in str(error)
        else:
            raise AssertionError("v4 manifest accepted a stale runtime preflight")
