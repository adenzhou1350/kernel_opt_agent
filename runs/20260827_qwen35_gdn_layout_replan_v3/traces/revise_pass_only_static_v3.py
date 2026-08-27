#!/usr/bin/env python3
"""Archive vetoed sealed revision and issue a PASS-only static admission revision."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path("/workspace/dance/qwen35/kernel_opt_agent")
RUN = ROOT / "runs/20260827_qwen35_gdn_layout_replan_v3"
REQUEST = "req-n2-layout-view-static-v2"
ARCHIVE = RUN / "traces/preapproval_veto_revision_02"
REVISION = RUN / "traces/static_admissibility_revision_02"
STAGING = REVISION / "static_probe_v3_staging"
CANDIDATE_DIR = RUN / "microbench_candidates" / REQUEST
EXPERIMENT_PATH = RUN / "experiments" / REQUEST / "experiment.json"
CONTRACT_PATH = RUN / "models/admissibility_contracts/n2_zero_copy_layout_v1.json"
OLD_EXPERIMENT_SHA = "60e9e254f5d2a97ada618bc4718f56479101d5970cfbb0667e030705173fa380"
PRODUCTION = {
    "short": Path("/workspace/dance/qwen35/flashinfer/flashinfer/gdn_kernels/delta_rule_dsl/qwen35_fla_s3_short_raw_sm120.py"),
    "long": Path("/workspace/dance/qwen35/flashinfer/flashinfer/gdn_kernels/delta_rule_dsl/qwen35_fla_s3_long_raw_sm120.py"),
}
CUTLASS_ROOT = Path(
    "/workspace/dance/qwen35/.venv-cu13/lib/python3.12/site-packages/"
    "nvidia_cutlass_dsl/dsl_packages/cutlass/cute"
)
CUTLASS_SOURCES = {name: CUTLASS_ROOT / f"{name}.py" for name in ("atom", "core", "tensor")}
LEGACY_SOURCE = Path(
    "/workspace/dance/qwen35/kernel_opt_agent/runs/"
    "20260827_qwen35_gdn_decision_supervised_v2/microbench_candidates/"
    "req-s3-tile-causal-production-ab/candidate_pkg/qwen35_fla_s3_short_raw_sm120.py"
)
SOURCE_NAMES = (
    "analyze.py", "clean_build.py", "common.py", "correctness.py",
    "layout_proof.py", "measure.py", "static_audit.py", "warmup.py",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def identity(path: Path) -> dict:
    return {"path": str(path), "sha256": sha256(path)}


def read(path: Path) -> dict:
    return json.loads(path.read_text())


def write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def archive_file(relative: str) -> None:
    source = RUN / relative
    if source.is_file():
        target = ARCHIVE / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def main() -> None:
    if ARCHIVE.exists():
        raise FileExistsError(f"refusing to overwrite revision archive: {ARCHIVE}")
    if REVISION.exists() and any(REVISION.iterdir()):
        allowed = {"static_probe_v3_staging"}
        observed = {item.name for item in REVISION.iterdir()}
        if observed - allowed:
            raise FileExistsError(f"revision trace already contains non-staging data: {observed}")
    if sha256(EXPERIMENT_PATH) != OLD_EXPERIMENT_SHA:
        raise RuntimeError("sealed experiment identity differs from the unanimously vetoed revision")
    if not STAGING.is_dir() or {item.name for item in STAGING.iterdir()} != set(SOURCE_NAMES):
        raise RuntimeError("revision staging must contain exactly eight reviewed source files")

    ARCHIVE.mkdir(parents=True)
    for relative in (
        "models/optimization_plan.json",
        "models/architecture_candidates/n2.json",
        "models/admissibility_contracts/n2_zero_copy_layout_v1.json",
        "models/admissibility_status.json",
        "models/production_constructor_bindings.json",
        "models/experiment_queue.json",
        f"experiments/{REQUEST}/experiment.json",
        f"experiments/{REQUEST}/catalog_query_receipt.json",
        "traces/static_admissibility_experiment_seal_v2.json",
        "traces/experiment_ranking_receipt.json",
    ):
        archive_file(relative)
    shutil.copytree(CANDIDATE_DIR, ARCHIVE / "microbench_candidates" / REQUEST)

    now = datetime.now(timezone.utc).isoformat()
    review_path = ARCHIVE / "review_receipt.json"
    write(review_path, {
        "schema_version": "preapproval-veto-receipt-v1",
        "reviewed_at": now,
        "request_id": REQUEST,
        "sealed_experiment_sha256": OLD_EXPERIMENT_SHA,
        "disposition": "ONE_ALLOWED_REVISION_REQUIRED_NO_CANDIDATE_DISPOSITION",
        "execution_observed": {
            "supervisor_approval": False,
            "dispatch": False,
            "compilation": False,
            "cuda_kernel_launch": False,
            "gpu_performance_samples": 0,
        },
        "independent_reviews": [
            {
                "role": "GLOBAL_SUPERVISOR",
                "decision": "VETO",
                "reason": "active plan, mutable evidence, candidate scope and deferred implementation gates were not closed",
            },
            {
                "role": "MICROARCHITECTURE_ANALYST",
                "decision": "VETO",
                "reason": "hand-written mapping self-compared, backing offsets were assumed, and negative control was artificial",
            },
            {
                "role": "EXPERIMENT_AGENT",
                "decision": "VETO",
                "reason": "real CuTe predicate failure was misclassified as infrastructure while contract authorized VALID reject",
            },
        ],
        "required_revision": "PASS-only admission with actual CuTe TV/partition/offset evidence and immutable status snapshot",
    })

    # Preserve and freeze the exact legacy expression used by the failed attempt.
    legacy_copy = REVISION / "legacy_attempt2_short_source.py"
    legacy_copy.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(LEGACY_SOURCE, legacy_copy)

    initial_status_path = REVISION / "admissibility_status_initial.json"
    initial_status = {
        "schema_version": "candidate-admissibility-status-v1",
        "candidate_id": "N2",
        "status": "STATIC_ADMISSIBILITY_PENDING",
        "performance_top_two_frozen": False,
        "survivor_set_not_yet_changed": ["N0", "N1", "N2"],
    }
    write(initial_status_path, initial_status)
    write(RUN / "models/admissibility_status.json", initial_status)

    for name in SOURCE_NAMES:
        shutil.copy2(STAGING / name, CANDIDATE_DIR / name)

    candidate_path = RUN / "models/architecture_candidates/n2.json"
    candidate = read(candidate_path)
    candidate.update({
        "static_hard_gate": {
            "scope": "SAME_BACKING_LOGICAL_LAYOUT_VIEW_ONLY",
            "pass": (
                "For hash-bound short and long O1 fragments, four pairwise-disjoint N16 tensors "
                "reuse the exact O1 backing iterator, cover all 128x64 logical elements once, "
                "and have the registered scoreV C/D fragment layout."
            ),
            "invalid": (
                "Any source identity, AST binding, oracle, import, tool, compiler, type or "
                "compiler-time assertion failure leaves N2 undisposed."
            ),
        },
        "static_pass_status": "LAYOUT_VIEW_FEASIBLE_PENDING_IMPLEMENTATION",
        "deferred_implementation_gates": [
            "per-element K accumulation order",
            "BF16 boundaries and numerical correctness",
            "actual implementation introduces no copy/permutation/shared/global transport",
            "production SASS removes the intended dynamic tile work",
            "register, spill, stack, shared-memory and occupancy/resource caps",
            "measured latency and performance ranking",
        ],
        "explicit_non_claims": [
            "no latency or speedup",
            "no performance Top2",
            "no physical-register-number claim",
            "no numerical or K-order conclusion",
            "no final implementation or production acceptance",
        ],
        "removed_flop_claim_condition": (
            "Static PASS only permits implementation work; removed-FLOP accounting has zero latency "
            "decision weight until implementation correctness, production SASS and measurement gates pass."
        ),
        "status": "STATIC_ADMISSIBILITY_PENDING",
    })
    write(candidate_path, candidate)

    binding_path = RUN / "models/production_constructor_bindings.json"
    write(binding_path, {
        "schema_version": "production-constructor-binding-v2",
        "status": "SOURCE_TOOLCHAIN_AND_PROOF_HASH_BOUND_AST_TRIPLET_PENDING_EXECUTION",
        "production_bindings": [
            {
                "production_path": name,
                "source_identity": identity(path),
                "active_thread_domain": "tidx<256 of block512" if name == "short" else "tidx<256 of block256",
            }
            for name, path in PRODUCTION.items()
        ],
        "proof_source_identity": identity(CANDIDATE_DIR / "layout_proof.py"),
        "cutlass_layout_implementation_identities": [identity(path) for path in CUTLASS_SOURCES.values()],
        "legacy_negative_source_identity": identity(legacy_copy),
        "required_normalized_ast_fields": [
            "D", "BT", "active_threads", "acc_dtype", "MMA op", "atom shape",
            "thread layout", "permutation_mnk", "get_slice(tidx)",
            "make_fragment_C(partition_shape_C((D,BT)))",
        ],
        "required_equality": "layout_signature_sha256(short)==layout_signature_sha256(long)==layout_signature_sha256(proof)",
        "regex_only_binding_forbidden": True,
    })

    contract = {
        "schema_version": "candidate-admissibility-contract-v1",
        "subdecision_id": "admit-n2-zero-copy-layout-v1",
        "status": "READY_FOR_SUPERVISOR",
        "lifecycle": "PASS_ONLY_INVALID",
        "issued_by": {"role": "GLOBAL_SCHEDULER", "owner_id": "global-scheduler-linear-v3"},
        "analysis_owner": {"role": "MICROARCHITECTURE_ANALYST", "analyst_id": "microarchitecture-analyst-linear-v3"},
        "run_id": RUN.name,
        "phase": "MODELING",
        "candidate_binding": {"candidate_id": "N2", "artifact_identity": identity(candidate_path)},
        "predicate": {
            "quantity_id": "n2_layout_view_feasible",
            "unit": "binary_pass",
            "domain": {"lower": 0, "upper": 1},
            "equation": "x=1 only if G1..G6 pass for short and long; any failure is INVALID and produces no x",
            "pass_condition": "x == 1",
            "fail_condition": "not authorized; no VALID x=0 outcome in revision_02",
            "statistical_precision": "NOT_APPLICABLE_DETERMINISTIC",
        },
        "gates": [
            {
                "gate_id": "G1_EXACT_PATH_IDENTITY",
                "requirement": "hash-bind production, proof and CUTLASS layout sources; exact O1 def-use AST signature is equal for short, long and proof with registered active-thread domains",
            },
            {
                "gate_id": "G2_SAME_ITERATOR",
                "requirement": "derive four N16 views from output.iterator via logical_divide and slice_and_offset; every view offset joins exactly one original output.layout offset",
            },
            {
                "gate_id": "G3_BIJECTIVE_MAPPING",
                "requirement": "actual O1/scoreV tv_layout_C_tiled and partition_C are checked against an independent 8192-row PTX oracle with full owner and coordinate coverage",
            },
            {
                "gate_id": "G4_SCOREV_FRAGMENT_COMPATIBILITY",
                "requirement": "short block512-active256 and long block256-active256 separately type-compile each same-backing N16 view as scoreV cute.gemm C/D",
            },
            {
                "gate_id": "G5_NEGATIVE_CONTROL",
                "requirement": "the exact prior one-warp fragment plus cute.append layout is instantiated and is unequal to the production O1 layout; its owner map exposes warp replication",
            },
            {
                "gate_id": "G6_ZERO_DYNAMIC_EXECUTION",
                "requirement": "compiled callable invocations=0, CUDA kernel launches=0, CUDA timing samples=0",
            },
        ],
        "explicit_non_claims": [
            "no latency value", "no speedup value", "no performance Top2 ordering",
            "no numerical correctness conclusion", "no K-loop accumulation-order proof",
            "no physical-register continuity", "no production SASS/resource or actual transport conclusion",
            "no production candidate acceptance or candidate rejection",
        ],
        "observations": {
            "short": {"count": 1, "unit": "binary_pass"},
            "long": {"count": 1, "unit": "binary_pass"},
            "aggregate": "logical_and(short,long)",
            "duplicated_samples_forbidden": True,
        },
        "host_budget": {
            "max_configurations": 2,
            "max_samples_per_configuration": 1,
            "max_process_launches": 6,
            "max_wall_clock_minutes": 15,
            "max_revisions": 1,
        },
        "device_budget": {"cuda_kernel_launches": 0, "gpu_performance_samples": 0},
        "outcomes": [
            {
                "condition": "all G1..G6 pass for separately compiled short and long proofs",
                "outcome": "ADMIT_N2_LAYOUT_VIEW_PENDING_IMPLEMENTATION",
            },
            {
                "condition": "any stale identity, AST/oracle mismatch, import/tool/compiler/type/assertion or lifecycle failure",
                "outcome": "INVALID_HALT_WITHOUT_N2_DISPOSITION",
            },
        ],
        "allowed_model_updates": [
            "PASS only: admissibility_status=LAYOUT_VIEW_FEASIBLE_PENDING_IMPLEMENTATION",
            "PASS only: survivor set remains [N0,N1,N2]",
            "PASS only: trigger fresh implementation/performance-bound rebuild",
            "INVALID: canonical status and survivor set remain unchanged and request blocks",
        ],
        "forbidden_model_updates": [
            "candidate rejection", "latency interval", "objective value", "performance Top2",
            "ranking score", "numerical or K-order conclusion", "production resources or transport",
            "production source mutation", "global candidate acceptance",
        ],
        "evidence": [identity(review_path), identity(binding_path), identity(initial_status_path)],
    }
    write(CONTRACT_PATH, contract)

    plan_path = RUN / "models/optimization_plan.json"
    plan = read(plan_path)
    plan.update({
        "acceptance_rule": (
            "This static request can only admit N2 logical same-backing N16 layout-view feasibility "
            "or block INVALID; it cannot reject a candidate or update performance."
        ),
        "experiment_queue": [REQUEST],
        "open_uncertainties": [{
            "admissibility_contract": identity(CONTRACT_PATH),
            "quantity_id": "n2_layout_view_feasible",
            "unit": "binary_pass",
            "performance_ranking": False,
        }],
        "correctness_gates": [
            "this static gate proves logical layout/type admissibility only",
            "all semantic and numerical gates are deferred to implementation",
        ],
        "evidence_gates": [
            "hash-bound production/proof O1 AST triplet equality",
            "actual CuTe O1/scoreV TV and partition_C mapping against independent oracle",
            "actual logical_divide/slice_and_offset same-backing joins",
            "four disjoint N16 views and 8192-coordinate full union",
            "exact legacy one-warp append negative control",
            "zero callable invocation, zero CUDA launch and zero timing sample",
        ],
        "deferred_implementation_gates": [
            "per-element K accumulation order",
            "BF16 boundaries and numerical correctness",
            "actual implementation no-copy/no-permutation/no shared or global transport",
            "production SASS tile-work removal",
            "register, spill, stack, shared memory and occupancy/resources",
            "measured latency, objective interval and Top2 ranking",
        ],
        "stop_criteria": [
            "PASS only advances N2 to LAYOUT_VIEW_FEASIBLE_PENDING_IMPLEMENTATION.",
            "Any identity/oracle/type/compiler/assert/tool failure is INVALID and leaves N2 pending.",
            "No VALID rejection exists in revision_02.",
            "No result may update latency, objective or performance Top2.",
            "No CUDA launch or production-source mutation is authorized.",
        ],
    })
    plan.setdefault("revision_history", []).append({
        "revision": 2,
        "at": now,
        "reason": "scope static decision to PASS-only same-backing logical layout-view admission and defer implementation semantics/resources",
    })
    write(plan_path, plan)

    queue_path = RUN / "models/experiment_queue.json"
    queue = read(queue_path)
    request = next(item for item in queue["requests"] if item["request_id"] == REQUEST)
    request.update({
        "status": "PROPOSED",
        "admissibility_contract": identity(CONTRACT_PATH),
        "candidate_decision": "PASS-only N2 logical layout-view admission; any failure is INVALID without disposition",
        "controls": [
            "Zero dynamic execution: no compiled callable invocation, CUDA launch, event or timer.",
            "Actual O1 and scoreV CuTe TV/partition mappings must agree with an independent PTX oracle.",
            "Actual fragment slice offsets must join the original O1 backing offsets one-to-one.",
            "Exact prior one-warp fragment plus cute.append layout is the negative control.",
            "Typed scoreV C/D compilation is not production SASS/resource evidence.",
        ],
        "measurement_contract": {
            "primary": "deterministic PASS-only static admission predicate",
            "timer": "none_compiler_typecheck",
            "unit": "binary_pass",
            "configurations": ["short", "long"],
            "samples_per_configuration": 1,
            "gpu_launches": 0,
            "performance_samples": 0,
            "classification": {
                "predicate_pass": "VALID binary_pass=1",
                "any_failure": "INVALID/BLOCKED without candidate disposition or result",
                "predicate_reject": "NOT_AUTHORIZED_IN_REVISION_02",
            },
        },
        "expected_sass": [
            "static proof artifact only; no production instruction/resource claim is permitted"
        ],
        "result_binding": {
            "status": "PENDING",
            "target": "models/admissibility_status.json::status",
            "pass_value": "LAYOUT_VIEW_FEASIBLE_PENDING_IMPLEMENTATION",
            "failure_value": "NO_UPDATE_BLOCKED",
        },
        "attempt_history": [{
            "revision": 1,
            "experiment_identity": identity(ARCHIVE / f"experiments/{REQUEST}/experiment.json"),
            "disposition": "PREAPPROVAL_VETO_NO_EXECUTION",
        }],
    })
    request.pop("materialized_experiment", None)
    queue["ranking_policy"] = {
        "issued_by_role": "GLOBAL_SCHEDULER",
        "formula": "NO_PERFORMANCE_RANKING_SINGLE_STATIC_GATE",
        "benefit_bound": "NOT_APPLICABLE_STATIC_ADMISSIBILITY",
        "performance_ranking": False,
        "ranked_at": now,
    }
    write(queue_path, queue)

    experiment = read(EXPERIMENT_PATH)
    experiment.update({
        "status": "PLANNED",
        "admissibility_contract_identity": identity(CONTRACT_PATH),
        "controls": request["controls"],
        "measurement_contract": request["measurement_contract"],
        "expected_sass": request["expected_sass"],
        "question": request["causal_question"],
    })
    experiment.pop("sealed_at", None)
    experiment.pop("commands", None)
    experiment.pop("source", None)
    experiment.pop("evidence", None)
    experiment["model_update_contract"].update({
        "decision_changed": request["candidate_decision"],
        "summary_fields": [
            "static_admissibility", "n2_disposition", "latency_model_update_authorized",
            "performance_top_two_update_authorized", "cuda_kernel_launches",
            "gpu_performance_samples",
        ],
    })
    write(EXPERIMENT_PATH, experiment)

    receipt_path = REVISION / "revision_receipt.json"
    write(receipt_path, {
        "schema_version": "static-admissibility-revision-receipt-v3",
        "created_at": now,
        "request_id": REQUEST,
        "revision": 2,
        "prior_sealed_experiment_sha256": OLD_EXPERIMENT_SHA,
        "review_identity": identity(review_path),
        "candidate_identity": identity(candidate_path),
        "contract_identity": identity(CONTRACT_PATH),
        "plan_identity": identity(plan_path),
        "queue_identity": identity(queue_path),
        "experiment_scaffold_identity": identity(EXPERIMENT_PATH),
        "initial_status_identity": identity(initial_status_path),
        "production_binding_identity": identity(binding_path),
        "source_identities": [identity(CANDIDATE_DIR / name) for name in SOURCE_NAMES],
        "lifecycle": "PASS_ONLY_INVALID",
        "compilation": False,
        "cuda_kernel_launches": 0,
        "gpu_performance_samples": 0,
    })
    print(json.dumps({"status": "PASS", "receipt": str(receipt_path)}, sort_keys=True))


if __name__ == "__main__":
    main()
