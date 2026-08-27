#!/usr/bin/env python3
"""Validate the semantic contract of a human-facing optimization report."""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path


EVIDENCE = {"生产匹配", "条件匹配", "仅供方向判断", "尚未测量"}
DECISIONS = {"保留", "否决", "待验证"}
SATURATION_REASONS = {
    "全卡并行不足",
    "单 CTA 数据量不足",
    "独立请求不足",
    "驻留数量受限",
    "请求放大",
    "地址效率不足",
    "cache 层级不匹配",
    "同步截断",
    "尾波不均衡",
    "与其他资源争用",
    "尚未建立",
}
EXPERIMENT_FIELDS = {
    "question": "问题",
    "held_constant": "保持不变",
    "only_change": "唯一改变",
    "result": "结果",
    "meaning": "含义",
    "boundary": "边界",
}
PUBLIC_INTERNAL_PATTERNS = (
    re.compile(r"\b[Mm]\d{2,}\b"),
    re.compile(r"\b[0-9a-fA-F]{40,64}\b"),
    re.compile(r"/(?:workspace|root|home|Users)/"),
)


def nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def public_strings(value: object, path: str = ""):
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "developer_appendix":
                continue
            yield from public_strings(item, f"{path}.{key}" if path else key)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from public_strings(item, f"{path}[{index}]")
    elif isinstance(value, str):
        yield path, value


def check_experiment(experiment: object, path: str, errors: list[str]) -> None:
    if not isinstance(experiment, dict):
        errors.append(f"{path}: experiment must be an object")
        return
    if not nonempty(experiment.get("name")):
        errors.append(f"{path}.name: missing human-readable name")
    for field, label in EXPERIMENT_FIELDS.items():
        if not nonempty(experiment.get(field)):
            errors.append(f"{path}.{field}: missing {label}")
    if experiment.get("evidence_status") not in EVIDENCE:
        errors.append(f"{path}.evidence_status: invalid evidence status")
    if experiment.get("decision") not in DECISIONS:
        errors.append(f"{path}.decision: invalid decision status")


def check_status(record: dict, path: str, errors: list[str]) -> None:
    if record.get("evidence_status") not in EVIDENCE:
        errors.append(f"{path}.evidence_status: invalid evidence status")
    if record.get("decision") not in DECISIONS:
        errors.append(f"{path}.decision: invalid decision status")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    try:
        report = json.loads(args.report.read_text())
    except Exception as error:
        print(json.dumps({"status": "FAIL", "errors": [str(error)]}, ensure_ascii=False, indent=2))
        return 1

    errors: list[str] = []
    required = {
        "schema_version", "title", "workload", "hardware", "measurement",
        "overview", "stages", "edges", "missing_evidence", "developer_appendix",
    }
    missing = sorted(required - set(report))
    if missing:
        errors.append(f"root: missing keys {missing}")
    if report.get("schema_version") != "human-review-report-v1":
        errors.append("schema_version must be human-review-report-v1")

    stages = report.get("stages", [])
    if not isinstance(stages, list) or not stages:
        errors.append("stages must be a non-empty list")
        stages = []
    observed_sum = 0.0
    for index, stage in enumerate(stages):
        path = f"stages[{index}]"
        if not isinstance(stage, dict):
            errors.append(f"{path}: stage must be an object")
            continue
        check_status(stage, path, errors)
        for field in ("key", "name", "main_limit", "direct_evidence", "boundary"):
            if not nonempty(stage.get(field)):
                errors.append(f"{path}.{field}: missing text")
        observed = stage.get("observed_us")
        if not isinstance(observed, (int, float)) or observed < 0 or not math.isfinite(observed):
            errors.append(f"{path}.observed_us: invalid non-negative finite time")
        else:
            observed_sum += observed
        for field in ("capacity", "dag_nodes", "schedule_lanes", "experiments", "resource_workpoints"):
            if not isinstance(stage.get(field), list):
                errors.append(f"{path}.{field}: must be a list")
        if not isinstance(stage.get("model_closure"), dict):
            errors.append(f"{path}.model_closure: must be an object")
        for exp_index, experiment in enumerate(stage.get("experiments", [])):
            check_experiment(experiment, f"{path}.experiments[{exp_index}]", errors)
        for wp_index, workpoint in enumerate(stage.get("resource_workpoints", [])):
            wp_path = f"{path}.resource_workpoints[{wp_index}]"
            if not isinstance(workpoint, dict):
                errors.append(f"{wp_path}: must be an object")
                continue
            for field in (
                "name", "resource_kind", "mandatory_work", "production_partition",
                "first_service", "steady_service", "production_point",
                "matched_saturation_point", "critical_path_contribution",
                "conclusion", "boundary",
            ):
                if not nonempty(workpoint.get(field)):
                    errors.append(f"{wp_path}.{field}: missing text")
            if workpoint.get("evidence_status") not in EVIDENCE:
                errors.append(f"{wp_path}.evidence_status: invalid evidence status")
            reasons = workpoint.get("saturation_reasons")
            if not isinstance(reasons, list) or not reasons:
                errors.append(f"{wp_path}.saturation_reasons: must be a non-empty list")
            elif invalid := sorted(set(reasons) - SATURATION_REASONS):
                errors.append(f"{wp_path}.saturation_reasons: invalid values {invalid}")
            curve = workpoint.get("curve")
            if curve is not None:
                if not isinstance(curve, dict) or not nonempty(curve.get("unit")):
                    errors.append(f"{wp_path}.curve: one graph must declare exactly one unit")
                elif not isinstance(curve.get("points"), list):
                    errors.append(f"{wp_path}.curve.points: must be a list")

    overview = report.get("overview", {})
    if isinstance(overview, dict):
        total = overview.get("total_observed_us")
        if isinstance(total, (int, float)) and stages and abs(total - observed_sum) > 0.002:
            errors.append(
                f"overview.total_observed_us={total} does not equal stage sum={observed_sum:.6f}"
            )
        if overview.get("theoretical_bound_status") not in {"理论下界已建立", "理论下界尚未建立"}:
            errors.append("overview.theoretical_bound_status: invalid phrase")
    else:
        errors.append("overview must be an object")

    for index, edge in enumerate(report.get("edges", [])):
        path = f"edges[{index}]"
        if not isinstance(edge, dict):
            errors.append(f"{path}: edge must be an object")
            continue
        check_status(edge, path, errors)
        check_experiment(edge.get("experiment"), f"{path}.experiment", errors)
        for field in (
            "name", "from_stage", "to_stage", "payload", "ownership",
            "unique_bytes", "request_bytes", "amplification", "boundary",
        ):
            if not nonempty(edge.get(field)):
                errors.append(f"{path}.{field}: missing text")

    missing_items = report.get("missing_evidence", [])
    if not isinstance(missing_items, list):
        errors.append("missing_evidence must be a list")
    else:
        for index, item in enumerate(missing_items):
            path = f"missing_evidence[{index}]"
            if not isinstance(item, dict):
                errors.append(f"{path}: must be an object")
                continue
            for field in ("stage_or_edge", "blocked_claim", "next_experiment"):
                if not nonempty(item.get(field)):
                    errors.append(f"{path}.{field}: missing text")
            if item.get("priority") not in {"P0", "P1", "P2", "P3"}:
                errors.append(f"{path}.priority: invalid priority")

    for path, value in public_strings(report):
        for pattern in PUBLIC_INTERNAL_PATTERNS:
            if pattern.search(value):
                errors.append(f"{path}: internal identifier/path leaked into human-facing text")
                break
        if "SM 利用率" in value or "显存带宽" in value:
            errors.append(f"{path}: forbidden ambiguous resource term")

    result = {
        "status": "PASS" if not errors else "FAIL",
        "report": str(args.report),
        "stage_count": len(stages),
        "errors": errors,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
