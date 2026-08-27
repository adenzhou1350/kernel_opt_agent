#!/usr/bin/env python3
"""Build the first evidence-closed production model for the Qwen3.5 GDN chain.

This script intentionally does not estimate physical service rates.  It records
mathematical work, schedule-derived logical traffic, production measurements,
and static final-binary evidence as four distinct evidence classes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path


B = 1
H = 16
D = 128
C = 64
BF16_BYTES = 2
FP32_BYTES = 4
SM_COUNT = 170
CASES = (256, 384, 404, 512, 640, 768, 1024)


def read(path: Path):
    return json.loads(path.read_text())


def write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def identity(path: Path) -> dict:
    return {"path": str(path.resolve()), "sha256": sha(path)}


def stage_from_kernel(name: str) -> str | None:
    lower = name.lower()
    if "s01" in lower:
        return "s01"
    if "s2_sm120" in lower or "s2stage" in lower:
        return "s2"
    if "s3_short" in lower or "s3_long" in lower:
        return "s3"
    if "fla_post" in lower or "gatedrms" in lower:
        return "post"
    return None


def trace_launches(trace: dict) -> dict:
    result = {}
    events = trace.get("traceEvents", trace if isinstance(trace, list) else [])
    for event in events:
        if event.get("cat") != "kernel":
            continue
        stage = stage_from_kernel(str(event.get("name", "")))
        if stage is None or stage in result:
            continue
        args = event.get("args", {})
        grid = list(args.get("grid", []))
        block = list(args.get("block", []))
        grid_x = int(grid[0]) if grid else None
        result[stage] = {
            "kernel_name": event.get("name"),
            "grid": grid,
            "block": block,
            "registers_per_thread": args.get("registers per thread"),
            "dynamic_shared_memory_bytes": args.get("shared memory"),
            "profiler_grid_cta_per_sm_ratio": args.get("blocks per SM"),
            "derived_maximum_one_wave_sm_coverage": (
                min(1.0, grid_x / SM_COUNT) if grid_x is not None else None
            ),
            "coverage_semantics": (
                "geometric upper bound from grid.x/170, not measured active-SM "
                "coverage and not resident blocks per SM"
            ),
        }
    required = {"s01", "s2", "s3", "post"}
    if set(result) != required:
        raise RuntimeError(f"trace launch coverage mismatch: {sorted(result)}")
    return result


def function_stage(name: str) -> str:
    stage = stage_from_kernel(name)
    return stage or "unmapped"


def class_counts(summary: dict) -> dict[str, int]:
    totals: dict[str, int] = {}
    for record in summary["functions"].values():
        for category, count in record["classes"].items():
            totals[category] = totals.get(category, 0) + int(count)
    return dict(sorted(totals.items()))


def math_and_traffic(S: int) -> dict:
    J = math.ceil(S / C)
    P = J * C
    R = S * H
    Rp = P * H
    E = S * H * D
    Ep = P * H * D
    HS = J * H * D * D
    tail = S - C * (J - 1)
    m16_tail = 16 * math.ceil(tail / 16)
    chunk_lengths = [C] * (J - 1) + [tail]

    s01_valid_flop = sum(H * D * (3 * t * t + t) for t in chunk_lengths)
    s01_schedule_flop = 6 * J * H * C * C * D
    s2_base = 16_777_216
    s2_valid_flop = int(s2_base * (4 * J - 6 + tail / 32))
    s2_m16_flop = int(s2_base * (4 * J - 6 + m16_tail / 32))
    s2_schedule_flop = s2_base * 4 * J
    local_pairs = sum(t * (t + 1) // 2 for t in chunk_lengths)
    s3_valid_flop = 2 * S * H * D * D + 4 * H * D * local_pairs
    s3_schedule_flop = 2 * P * H * D * D + 4 * H * D * J * C * C

    minimum_bytes = {
        "s01": 7 * BF16_BYTES * E + 2 * BF16_BYTES * R + FP32_BYTES * R + 2 * FP32_BYTES * H,
        "s2": 4 * BF16_BYTES * E + FP32_BYTES * R + BF16_BYTES * HS,
        "s3": 4 * BF16_BYTES * E + FP32_BYTES * R + BF16_BYTES * HS,
        "post": 3 * BF16_BYTES * E + BF16_BYTES * D,
    }
    current_bytes = {
        "s01": 4 * BF16_BYTES * E + 3 * BF16_BYTES * Ep + 2 * BF16_BYTES * R + FP32_BYTES * Rp + 2 * FP32_BYTES * H,
        "s2": 4 * BF16_BYTES * Ep + FP32_BYTES * Rp + BF16_BYTES * HS,
        "s3": 2 * BF16_BYTES * E + 2 * BF16_BYTES * Ep + FP32_BYTES * Rp + BF16_BYTES * HS,
        "post": 3 * BF16_BYTES * E + BF16_BYTES * D,
    }
    valid_tensor = s01_valid_flop + s2_valid_flop + s3_valid_flop
    schedule_tensor = s01_schedule_flop + s2_schedule_flop + s3_schedule_flop
    return {
        "dimensions": {"B": B, "H": H, "D": D, "C": C, "S": S, "J": J, "P": P, "tail": tail},
        "symbols": {"R": R, "Rp": Rp, "E": E, "Ep": Ep, "HS": HS},
        "tensor": {
            "s01_valid_dense_flop": s01_valid_flop,
            "s01_current_dense_schedule_flop": s01_schedule_flop,
            "s2_algorithm_exact_flop": s2_valid_flop,
            "s2_m16_feasible_flop": s2_m16_flop,
            "s2_current_schedule_flop": s2_schedule_flop,
            "s3_valid_dense_flop": s3_valid_flop,
            "s3_current_dense_schedule_flop": s3_schedule_flop,
            "total_valid_dense_flop": valid_tensor,
            "total_current_dense_schedule_flop": schedule_tensor,
            "total_schedule_minus_valid_dense_flop": schedule_tensor - valid_tensor,
        },
        "logical_bytes": {
            "legal_four_stage_minimum_by_stage": minimum_bytes,
            "legal_four_stage_minimum_total": sum(minimum_bytes.values()),
            "current_schedule_by_stage": current_bytes,
            "current_schedule_total": sum(current_bytes.values()),
            "current_minus_minimum": sum(current_bytes.values()) - sum(minimum_bytes.values()),
            "s3_post_fusion_eliminable_raw_o_store_read": 2 * BF16_BYTES * E,
        },
        "algorithmic_special_functions": {
            "qk_l2norm_rsqrt": 2 * R,
            "decay_exponential": R,
            "post_rms_rsqrt": R,
            "post_gate_sigmoid": E,
            "total_evaluations": E + 4 * R,
        },
        "reductions": {
            "qk_l2norm_rows": 2 * R,
            "post_rms_rows": R,
            "row_width": D,
        },
        "local_causal_pairs": local_pairs,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    run = args.run.resolve()
    models = run / "models"
    static_cases = run / "static/cases"
    baseline = read(models / "baseline.json")
    baseline_cases = {case["case_id"]: case for case in baseline["cases"]}
    manifest_path = static_cases / "manifest.json"
    manifest = read(manifest_path)
    manifest_cases = {case["case_id"]: case for case in manifest["cases"]}
    resource_discovery_path = models / "resource_discovery.json"
    resource_discovery = read(resource_discovery_path)
    discovery_identity = identity(resource_discovery_path)
    baseline_identity = identity(models / "baseline.json")
    manifest_identity = identity(manifest_path)

    if set(baseline_cases) != {f"s{s}" for s in CASES} or set(manifest_cases) != set(baseline_cases):
        raise RuntimeError("seven-case production coverage mismatch")
    if manifest.get("status") != "PASS" or any(c.get("launch_smoke") != "PASS" for c in manifest["cases"]):
        raise RuntimeError("case binary manifest is not PASS")

    coverage_cases = []
    reference_classes = None
    case_summaries = {}
    launches = {}
    stage_times = {}
    for S in CASES:
        case_id = f"s{S}"
        case_dir = static_cases / case_id
        summary_path = case_dir / "sass-summary.json"
        receipt_path = case_dir / "disassembly_receipt.json"
        summary = read(summary_path)
        if summary.get("status") != "PASS" or summary.get("coverage", {}).get("site_coverage_fraction") != 1.0:
            raise RuntimeError(f"{case_id}: SASS coverage is not exactly PASS/1.0")
        if summary.get("unclassified_mnemonics") or summary.get("ambiguous_mnemonics"):
            raise RuntimeError(f"{case_id}: unresolved SASS mnemonic")
        classes = set(class_counts(summary))
        if reference_classes is None:
            reference_classes = classes
        if classes != reference_classes:
            raise RuntimeError(f"{case_id}: material instruction-class set differs from reference")
        for key in ("cubin", "ptx"):
            item = manifest_cases[case_id][key]
            if sha(Path(item["path"])) != item["sha256"]:
                raise RuntimeError(f"{case_id}: stale {key} identity")
        if not receipt_path.is_file():
            raise RuntimeError(f"{case_id}: missing disassembly receipt")
        receipt = read(receipt_path)
        actual_sass_identity = identity(case_dir / "final.sass")
        if receipt.get("binary_identity", {}).get("sha256") != manifest_cases[case_id]["cubin"]["sha256"]:
            raise RuntimeError(f"{case_id}: disassembly receipt/binary mismatch")
        if receipt.get("sass_identity", {}).get("sha256") != actual_sass_identity["sha256"]:
            raise RuntimeError(f"{case_id}: disassembly receipt/SASS mismatch")
        if summary.get("input_sass_identity", {}).get("sha256") != actual_sass_identity["sha256"]:
            raise RuntimeError(f"{case_id}: SASS summary/input mismatch")
        case_summaries[case_id] = summary
        raw_path = run / f"baseline/raw/{case_id}.json"
        raw = read(raw_path)
        trace_path = run / f"baseline/raw/{case_id}_stage_trace.json"
        launches[case_id] = trace_launches(read(trace_path))
        stages = raw["stage_profile"]["stages"]
        s3_key = "s3_long" if stages.get("s3_long") else "s3_short"
        stage_times[case_id] = {
            "measurement_system": 0.006,
            "s01": stages["s01"]["median_us"],
            "s2": stages["s2"]["median_us"],
            "s3": stages[s3_key]["median_us"],
            "post": stages["post"]["median_us"],
        }
        coverage_cases.append({
            "case_id": case_id,
            "S": S,
            "J": manifest_cases[case_id]["J"],
            "P": manifest_cases[case_id]["P"],
            "binary_identity": manifest_cases[case_id]["cubin"],
            "sass_identity": actual_sass_identity,
            "source_manifest_sass_identity": manifest_cases[case_id]["sass"],
            "source_manifest_sass_identity_status": "SUPERSEDED_BY_REPRODUCIBLE_DISASSEMBLY_RECEIPT",
            "sass_summary_identity": identity(summary_path),
            "disassembly_receipt_identity": identity(receipt_path),
            "coverage": summary["coverage"],
            "instruction_classes": sorted(classes),
            "function_count": len(summary["functions"]),
        })

    coverage_receipt_path = models / "case_binary_resource_coverage.json"
    coverage_receipt = {
        "schema_version": "production-case-binary-resource-coverage-v1",
        "status": "PASS",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "contract": {
            "cases": list(map(lambda s: f"s{s}", CASES)),
            "site_coverage_fraction": 1.0,
            "unknown_or_ambiguous_mnemonics": 0,
            "same_material_instruction_class_set": True,
            "note": "same classes does not imply same dynamic counts or service behavior",
        },
        "manifest_identity": manifest_identity,
        "cases": coverage_cases,
    }
    write(coverage_receipt_path, coverage_receipt)
    coverage_identity = identity(coverage_receipt_path)

    derivation_path = models / "modeling_derivation.md"
    derivation_path.write_text(
        """# Qwen3.5 GDN 当前四阶段模型推导\n\n"
        "本文件只定义可由数学与当前切分直接推出的量；不把逻辑请求字节当作 L2 或 DRAM 实际流量。\n\n"
        "符号：`b=2`（BF16 字节），`f=4`（FP32 字节），`C=64`，"
        "`J=ceil(S/C)`，`P=64J`，`R=SH`，`Rp=PH`，`E=SHD`，`Ep=PHD`，`HS=JHD²`。\n\n"
        "当前四阶段的数学最小逻辑边界字节：\n\n"
        "- S01：`7bE + 2bR + fR + 2fH`。\n"
        "- S2：`4bE + fR + bHS`。\n"
        "- S3：`4bE + fR + bHS`。\n"
        "- post：`3bE + bD`。\n"
        "- 总计：`18bE + 2bR + 3fR + 2bHS + 2fH + bD`。\n\n"
        "当前 padded schedule 的逻辑请求字节：\n\n"
        "- S01：`4bE + 3bEp + 2bR + fRp + 2fH`。\n"
        "- S2：`4bEp + fRp + bHS`。\n"
        "- S3：`2bE + 2bEp + fRp + bHS`。\n"
        "- post：`3bE + bD`。\n\n"
        "S3 与 post 融合时，确定可以消去 raw_o 的一次写和一次读，即 `2bE=4E` 字节。"
        "这只是跨 kernel 逻辑 handoff 的消除量，不是 DRAM 节省量。\n\n"
        "稠密 Tensor 工作量按 1 次乘加等于 2 FLOP 计。S01 对每个有效 chunk 长度 t 的"
        "主稠密工作量为 `HD(3t²+t)`；S2 使用精确尾块公式；S3 包含 `q@h` 与 chunk 内"
        "因果 pair 工作。当前 schedule 的 padded FLOP 单独记录，不能冒充有效数学量。\n"
        """
    )
    derivation_identity = identity(derivation_path)

    # Mandatory work ledger.
    ledger_cases = []
    math_by_case = {}
    for S in CASES:
        case_id = f"s{S}"
        model = math_and_traffic(S)
        math_by_case[case_id] = model
        ledger_cases.append({
            "case_id": case_id,
            "valid_work": {
                "dimensions": model["dimensions"],
                "dense_tensor_flop": model["tensor"]["total_valid_dense_flop"],
                "dense_tensor_flop_by_stage": {
                    "s01": model["tensor"]["s01_valid_dense_flop"],
                    "s2": model["tensor"]["s2_algorithm_exact_flop"],
                    "s3": model["tensor"]["s3_valid_dense_flop"],
                    "post": 0,
                },
                "logical_four_stage_minimum_bytes": model["logical_bytes"],
                "algorithmic_special_functions": model["algorithmic_special_functions"],
                "reductions": model["reductions"],
            },
            "padded_or_redundant_work": {
                "padding_tokens": model["dimensions"]["P"] - S,
                "dense_tensor_schedule": model["tensor"],
                "current_logical_schedule": model["logical_bytes"],
                "s2_tail_rounding": {
                    "algorithm_exact_flop": model["tensor"]["s2_algorithm_exact_flop"],
                    "m16_feasible_flop": model["tensor"]["s2_m16_feasible_flop"],
                    "current_schedule_flop": model["tensor"]["s2_current_schedule_flop"],
                },
            },
            "assumptions": [
                "BF16=2 bytes, FP32=4 bytes, FMA=2 FLOP",
                "logical bytes count useful tensor boundary requests, not cache-line transactions or DRAM traffic",
                "initial_state=None and output_final_state=False",
            ],
            "evidence": [derivation_identity, manifest_identity, baseline_cases[case_id]["source_identity"]],
        })
    work_ledger = {
        "schema_version": "mandatory-work-ledger-v1",
        "workload_case": "production-prior-seven-prefill-shapes",
        "cases": ledger_cases,
        "valid_work": {
            "scope": "per-case records are authoritative",
            "bytes_by_boundary": {"status": "DERIVED_LOGICAL_NOT_PHYSICAL"},
            "tensor_operations": {"unit": "FLOP", "fma_convention": 2},
            "simt_operations": {"status": "DYNAMIC_COUNT_UNKNOWN"},
            "sfu_operations": {"status": "ALGORITHMIC_EVALUATIONS_ONLY"},
            "reductions": {"row_width": D},
            "synchronization_sites": 0,
            "handoffs": ["s01_to_s2", "s01_to_s3", "s2_to_s3", "s3_raw_to_post"],
        },
        "padded_or_redundant_work": {"scope": "per-case records are authoritative"},
        "assumptions": ["equal case weights because production frequency prior was not supplied"],
        "evidence": [derivation_identity, coverage_identity, baseline_identity],
    }
    write(models / "work_ledger.json", work_ledger)
    work_identity = identity(models / "work_ledger.json")

    # Operator and production schedule DAG.
    dag = {
        "schema_version": "operator-dag-v1",
        "nodes": [
            {"node_id": "inputs", "meaning": "Q/K/V/g/beta/A_log/dt_bias/post RMS weight"},
            {"node_id": "s01", "meaning": "Q/K L2 normalization, decay preparation, chunk-local lower-triangular transforms, packed K/W/U production", "resources": ["tensor_compute", "special_function", "shared_memory", "async_copy_engine"]},
            {"node_id": "s2", "meaning": "chunk-to-chunk recurrent state propagation", "resources": ["tensor_compute", "shared_memory", "synchronization"]},
            {"node_id": "s3", "meaning": "combine normalized Q, local causal contribution and propagated state into raw output", "resources": ["tensor_compute", "shared_memory", "async_copy_engine"]},
            {"node_id": "post", "meaning": "RMS reduction, reciprocal square root, sigmoid gate and BF16 output", "resources": ["simt_compute", "special_function", "warp_collective"]},
            {"node_id": "output", "meaning": "[B,S,H,D] BF16 output"},
        ],
        "mathematical_edges": [
            {"from": "inputs", "to": "s01", "payload": "Q/K/V/g/beta and decay weights"},
            {"from": "s01", "to": "s2", "payload": "packed per-chunk K/W/U and decay summaries"},
            {"from": "s01", "to": "s3", "payload": "normalized Q and chunk-local factors"},
            {"from": "s2", "to": "s3", "payload": "head-major recurrent state h"},
            {"from": "s3", "to": "post", "payload": "raw_o [B,S,H,D] BF16"},
            {"from": "inputs", "to": "post", "payload": "gate and RMS weight"},
            {"from": "post", "to": "output", "payload": "gated RMS-normalized output"},
        ],
        "schedule_only_edges": [
            {"from": "s01", "to": "s2", "reason": "P=ceil(S/64)*64 workspace padding"},
            {"from": "s01", "to": "s3", "reason": "global workspace handoff imposed by four-kernel schedule"},
            {"from": "s3", "to": "post", "reason": "raw_o materialization is removable by a legal fusion candidate", "eliminable_logical_bytes_formula": "2*b*E"},
        ],
        "resource_constraints": [
            {"resource_ids": request["resource_ids"], "request_id": request["request_id"], "status": "UNMEASURED"}
            for request in read(models / "experiment_queue.json")["requests"]
        ],
        "critical_paths": [
            {
                "case_id": case_id,
                "production_order": ["s01", "s2", "s3", "post"],
                "separate_cupti_stage_median_us": {k: v for k, v in stage_times[case_id].items() if k != "measurement_system"},
                "separate_cupti_kernel_sum_us": sum(v for k, v in stage_times[case_id].items() if k != "measurement_system"),
                "acceptance_gpu_graph_median_us": baseline_cases[case_id]["gpu_active"]["median_us"],
                "cross_method_difference_us": baseline_cases[case_id]["gpu_active"]["median_us"] - sum(v for k, v in stage_times[case_id].items() if k != "measurement_system"),
                "measurement_semantics": "stage values are a separate CUPTI diagnostic; graph median is the acceptance timing",
            }
            for case_id in baseline_cases
        ],
        "unproven_edges": [
            {"edge": "memory_request_to_L2_to_DRAM", "unknown": "cache hit/miss, transactions, amplification and latency", "request_id": "req-memory-hierarchy-service"},
            {"edge": "TMA_to_tensor_overlap", "unknown": "dependency latency and overlap fraction", "request_id": "req-sync-async-overlap"},
            {"edge": "tensor_to_epilogue", "unknown": "eligible issue window and SIMT/SFU tail", "request_id": "req-compute-service"},
        ],
    }
    write(models / "dag.json", dag)
    dag_identity = identity(models / "dag.json")

    # Schedule model: final-binary static facts and launch geometry, no dynamic inference.
    schedule_cases = []
    sass_control_flow = []
    for S in CASES:
        case_id = f"s{S}"
        summary = case_summaries[case_id]
        per_function = []
        for name, record in summary["functions"].items():
            per_function.append({
                "stage_id": function_stage(name),
                "kernel_name": name,
                "static_instruction_sites": record["instruction_count"],
                "static_class_counts": record["classes"],
            })
        sass_control_flow.append({
            "case_id": case_id,
            "static_branch_control_sites": class_counts(summary).get("branch_control", 0),
            "static_control_noop_sites": class_counts(summary).get("control_noop", 0),
            "dynamic_trip_counts": None,
            "status": "STATIC_ONLY",
        })
        schedule_cases.append({
            "case_id": case_id,
            "dimensions": math_by_case[case_id]["dimensions"],
            "binary_identity": manifest_cases[case_id]["cubin"],
            "sass_identity": identity(static_cases / case_id / "final.sass"),
            "sass_summary_identity": identity(static_cases / case_id / "sass-summary.json"),
            "disassembly_receipt_identity": identity(static_cases / case_id / "disassembly_receipt.json"),
            "static_instruction_sites": summary["coverage"]["total_static_sites"],
            "static_class_counts": class_counts(summary),
            "functions": per_function,
            "launches": launches[case_id],
            "production_timing": {
                "acceptance_graph_gpu_active_median_us": baseline_cases[case_id]["gpu_active"]["median_us"],
                "cpu_dispatch_median_us": baseline_cases[case_id]["cpu_dispatch"]["median_us"],
                "end_to_end_median_us": baseline_cases[case_id]["end_to_end"]["median_us"],
                "separate_cupti_stage_median_us": {k: v for k, v in stage_times[case_id].items() if k != "measurement_system"},
            },
        })
    schedule = {
        "schema_version": "resource-schedule-model-v1",
        "status": "INITIALIZED",
        "binary_identity": {
            "canonical_resource_discovery_binary": resource_discovery["binary_identity"],
            "production_case_manifest": manifest_identity,
            "abi_tag": manifest["cases"][0]["abi_tag"],
        },
        "sass_control_flow": sass_control_flow,
        "dynamic_instruction_method": {
            "status": "UNKNOWN",
            "reason": "static SASS sites do not provide dynamic execution counts, issue eligibility, replay or wait cycles",
            "required_requests": ["req-compute-service", "req-register-collective", "req-shared-request-service", "req-sync-async-overlap"],
        },
        "resource_mapping": [
            {
                "resource_id": node["resource_id"],
                "static_triggers_s404": node.get("triggers", []),
                "official_evidence": node.get("official_evidence", []),
                "service_status": "UNKNOWN",
            }
            for node in resource_discovery["resource_nodes"]
        ],
        "dependency_graph": {"nodes": [n["node_id"] for n in dag["nodes"]], "edges": dag["mathematical_edges"] + dag["schedule_only_edges"]},
        "workload_cases": schedule_cases,
        "coupled_resource_models": [
            {"request_id": request["request_id"], "resource_ids": request["resource_ids"], "status": "PENDING_EXPERIMENT"}
            for request in read(models / "experiment_queue.json")["requests"]
        ],
        "unknown_scheduler_or_cache_behavior": [
            "dynamic instruction counts and branch trip counts",
            "eligible issue window and per-pipeline issue efficiency",
            "shared-bank conflicts and request replays",
            "L1/L2/DRAM transaction counts and latency distributions",
            "TMA/compute overlap and scoreboard critical-path contribution",
            "actual active-SM distribution; grid.x/SM is only a geometric upper bound",
        ],
        "evidence": [coverage_identity, baseline_identity, work_identity, dag_identity, discovery_identity],
    }
    write(models / "schedule_model.json", schedule)
    schedule_identity = identity(models / "schedule_model.json")

    # Update the architecture model with all seven final-binary cases.
    architecture_path = models / "microarchitecture_model.json"
    architecture = read(architecture_path)
    architecture["status"] = "INITIALIZED"
    architecture["workload_mappings"] = [
        {
            "case_id": f"s{S}",
            "material_resource_ids": resource_discovery["required_resource_ids"],
            "status": "STATIC_FINAL_BINARY_MAPPED; NUMERIC_SERVICE_UNMEASURED",
            "binary_identity": manifest_cases[f"s{S}"]["cubin"],
            "sass_summary_identity": identity(static_cases / f"s{S}" / "sass-summary.json"),
        }
        for S in CASES
    ]
    architecture["service_curves"] = []
    architecture["latency_constraints"] = []
    architecture["evidence"] = list({item["path"]: item for item in architecture.get("evidence", []) + [coverage_identity, baseline_identity, schedule_identity]}.values())
    write(architecture_path, architecture)

    queue = read(models / "experiment_queue.json")
    resource_to_request = {}
    for request in queue["requests"]:
        for resource_id in request["resource_ids"]:
            resource_to_request.setdefault(resource_id, []).append(request["request_id"])
    resource_kind = {}
    prior = {}
    for case in read(models / "resource_balance.json")["cases"]:
        for row in case["resource_rows"]:
            resource_kind[row["resource_id"]] = row["resource_kind"]
    for rid in resource_discovery["required_resource_ids"]:
        kind = resource_kind[rid]
        prior[rid] = {
            "TENSOR_CORE": 0.95,
            "SIMT": 0.75,
            "SFU": 0.80,
            "TMA": 0.75,
            "REQUEST_SERVICE": 0.80,
            "SHARED_L1": 0.80,
            "L2": 0.70,
            "DEVICE_MEMORY": 0.70,
            "FRONT_END": 0.65,
            "SYNCHRONIZATION": 0.75,
        }[kind]

    balance_cases = []
    for S in CASES:
        case_id = f"s{S}"
        model = math_by_case[case_id]
        valid_flop = model["tensor"]["total_valid_dense_flop"]
        schedule_flop = model["tensor"]["total_current_dense_schedule_flop"]
        logical_min = model["logical_bytes"]["legal_four_stage_minimum_total"]
        logical_current = model["logical_bytes"]["current_schedule_total"]
        special = model["algorithmic_special_functions"]["total_evaluations"]
        rows = []
        for rid in resource_discovery["required_resource_ids"]:
            kind = resource_kind[rid]
            if rid == "tensor_compute":
                mandatory = {"value": valid_flop, "unit": "algorithmic_dense_FLOP", "status": "DERIVED"}
                actual = {"value": schedule_flop, "unit": "algorithmic_dense_FLOP", "status": "DERIVED_SCHEDULE_UPPER"}
            elif rid == "load_store_request":
                mandatory = {"value": logical_min, "unit": "logical_tensor_boundary_bytes", "status": "DERIVED"}
                actual = {"value": logical_current, "unit": "logical_tensor_boundary_bytes", "status": "DERIVED_SCHEDULE"}
            elif rid == "special_function":
                mandatory = {"value": special, "unit": "algorithmic_SFU_evaluations", "status": "DERIVED"}
                actual = {"value": special, "unit": "algorithmic_SFU_evaluations", "status": "ALGORITHMIC_NOT_DYNAMIC_INSTRUCTIONS"}
            else:
                mandatory = {"value": 0, "unit": "unresolved_dynamic_work_units", "status": "UNKNOWN"}
                actual = {"value": 0, "unit": "unresolved_dynamic_work_units", "status": "UNKNOWN"}
            row = {
                "resource_id": rid,
                "resource_kind": kind,
                "material": True,
                "mandatory_work": mandatory,
                "actual_work": actual,
                "production_point": {"status": "UNKNOWN", "value": None, "unit": "matched_microbenchmark_work_units"},
                "matched_saturation": {"status": "UNKNOWN", "value": None, "unit": "unknown", "conditions": []},
                "utilization": {
                    "status": "UNKNOWN", "value_percent": None, "numerator": None, "denominator": None,
                    "time_window": "acceptance graph GPU-active window; eligible resource window not yet measured",
                    "boundary": kind,
                },
                "critical_path": {
                    "status": "UNKNOWN", "contribution_us": None,
                    "coupling_model": "unmeasured causal prior used only for experiment ranking",
                    "probability": prior[rid],
                },
                "non_saturation_causes": ["NOT_ESTABLISHED"],
                "evidence": [work_identity, schedule_identity, baseline_identity],
                "unresolved_request_ids": resource_to_request[rid],
            }
            if kind == "TENSOR_CORE":
                row["compute_efficiency"] = {
                    "device_coverage": None,
                    "eligible_time_fraction": None,
                    "eligible_window_issue_efficiency": None,
                    "composition_status": "UNKNOWN",
                }
            rows.append(row)
        acceptance = baseline_cases[case_id]["gpu_active"]["median_us"]
        diagnostic_sum = sum(v for k, v in stage_times[case_id].items() if k != "measurement_system")
        balance_cases.append({
            "case_id": case_id,
            "resource_rows": rows,
            "device_coverage": {
                "status": "BOUNDED_GEOMETRIC_NOT_UTILIZATION",
                "per_stage_maximum_one_wave_fraction": {stage: data["derived_maximum_one_wave_sm_coverage"] for stage, data in launches[case_id].items()},
                "reason": "grid.x/170 only bounds how many SMs can receive at least one CTA in one wave",
            },
            "critical_path": {
                "status": "MEASURED_BASELINE",
                "total_us": acceptance,
                "stage_gpu_active_us": stage_times[case_id],
                "stage_timing_semantics": "CUPTI stage diagnostic is separate from graph acceptance timing",
            },
            "model_residual": {
                "status": "CROSS_METHOD_DIAGNOSTIC_NOT_MODEL_RESIDUAL",
                "value_us": acceptance - diagnostic_sum,
                "reason": "cannot be used as a schedule-model residual until component service curves exist",
            },
        })
    balance = {
        "schema_version": "resource-balance-ledger-v1",
        "status": "INITIALIZED",
        "cases": balance_cases,
        "cross_resource_coupling": [
            {"request_id": request["request_id"], "resource_ids": request["resource_ids"], "status": "UNKNOWN"}
            for request in queue["requests"]
        ],
        "unresolved_material_resources": [
            {"resource_id": rid, "request_id": request_id}
            for rid, request_ids in resource_to_request.items() for request_id in request_ids
        ],
        "evidence": [work_identity, dag_identity, schedule_identity, baseline_identity, coverage_identity],
    }
    write(models / "resource_balance.json", balance)

    # Ranker consumes cost categories after this script.
    cost_by_request = {
        "req-compute-service": "HIGH",
        "req-memory-hierarchy-service": "HIGH",
        "req-p0-measurement-system": "LOW",
        "req-register-collective": "MEDIUM",
        "req-shared-request-service": "MEDIUM",
        "req-sync-async-overlap": "MEDIUM",
    }
    for request in queue["requests"]:
        request["sensitivity"]["experiment_cost"] = cost_by_request[request["request_id"]]
    write(models / "experiment_queue.json", queue)

    frontier_cases = []
    for S in CASES:
        case_id = f"s{S}"
        model = math_by_case[case_id]
        frontier_cases.append({
            "case_id": case_id,
            "legal_minimum": {
                "status": "DERIVED_MATH_AND_LOGICAL_BOUNDARY_ONLY",
                "valid_math": "fixed by operator contract",
                "mandatory_compute": {"value": model["tensor"]["total_valid_dense_flop"], "unit": "dense_FLOP"},
                "mandatory_bytes_by_boundary": {
                    "logical_tensor_request": model["logical_bytes"]["legal_four_stage_minimum_total"],
                    "L2": None,
                    "device_memory": None,
                },
                "reason": "service-time lower bound remains unknown until matched P1/P2 microbenchmarks",
            },
            "current_schedule": {
                "schedule_id": "current-production-four-stage-exact-binary",
                "correctness": "PASS",
                "valid_compute": {"operations": model["tensor"]["total_valid_dense_flop"], "unit": "dense_FLOP", "status": "DERIVED"},
                "padded_compute": {"P": model["dimensions"]["P"], "S": S, "operations": model["tensor"]["total_current_dense_schedule_flop"], "unit": "dense_FLOP", "status": "DERIVED_SCHEDULE_UPPER"},
                "bytes_by_boundary": {
                    "request": model["logical_bytes"]["current_schedule_total"],
                    "L2": None,
                    "device_memory": None,
                    "status": "LOGICAL_REQUEST_DERIVED; PHYSICAL_BOUNDARIES_UNKNOWN",
                },
                "allocation": {"status": "MEASURED_PROFILER_LAUNCH_METADATA", "stages": launches[case_id]},
                "device_coverage": {
                    "status": "BOUNDED_GEOMETRIC_NOT_UTILIZATION",
                    "per_stage_fraction": {stage: data["derived_maximum_one_wave_sm_coverage"] for stage, data in launches[case_id].items()},
                },
                "synchronization": {"barriers": None, "waits": None, "status": "DYNAMIC_COUNTS_UNKNOWN"},
                "predicted_dag_us": None,
                "measured_us": baseline_cases[case_id]["gpu_active"]["median_us"],
                "uncertainty": {"status": "MEASUREMENT_P0_PASS_MODEL_UNCALIBRATED", "us": None},
                "decision": "CURRENT_BASELINE_NOT_LIMIT_CERTIFICATE",
            },
            "candidates": [],
            "pareto_frontier": [],
        })
    frontier = read(models / "tradeoff_frontier.json")
    frontier["status"] = "INITIALIZED"
    frontier["cases"] = frontier_cases
    frontier["global_decision"] = {
        "status": "PENDING_EXPERIMENT",
        "selected_schedule": None,
        "issued_by_role": "GLOBAL_SCHEDULER",
        "reason": "current baseline is correct, but resource service curves and causal limits remain unresolved",
    }
    frontier["evidence"] = [work_identity, dag_identity, schedule_identity, baseline_identity]
    write(models / "tradeoff_frontier.json", frontier)

    global_state_path = models / "global_schedule_state.json"
    global_state = read(global_state_path)
    global_state["status"] = "MODEL_READY"
    global_state["revision_history"].append({
        "revision": max(item["revision"] for item in global_state["revision_history"]) + 1,
        "reason": "Seven-case mathematical work, logical traffic, production DAG, final-binary SASS coverage and baseline launch/timing evidence are now closed; physical service/utilization remains explicitly unknown and assigned to experiments.",
    })
    write(global_state_path, global_state)

    print(json.dumps({
        "status": "PASS",
        "cases": len(CASES),
        "resources": len(resource_discovery["required_resource_ids"]),
        "coverage_receipt": str(coverage_receipt_path),
        "models": ["work_ledger", "dag", "schedule_model", "microarchitecture_model", "resource_balance", "tradeoff_frontier", "global_schedule_state"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
