#!/usr/bin/env python3
"""Detect environment-plan churn before it consumes another repair cycle."""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from artifact_io import atomic_json, now, sha256_file
from schema_utils import validate_instance


SCHEMA_VERSION = "qualification-churn-report-v1"
PLAN_MARKER = "materialization_plan"
TERMINAL_MARKERS = (
    "materialization_receipt",
    "materialization_terminal",
    "terminal_observation",
    "worker_materialization_terminal",
)
VERSION_RE = re.compile(r"^(?P<family>.+?)[_-]v(?P<version>[0-9]+)$", re.I)


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def versioned_name(path: Path) -> tuple[str, int] | None:
    match = VERSION_RE.fullmatch(path.stem)
    if match is None:
        return None
    return match.group("family"), int(match.group("version"))


def terminal_status(value: dict[str, Any]) -> str | None:
    candidates = [value.get("status"), value.get("state")]
    execution = value.get("execution")
    if isinstance(execution, dict):
        candidates.extend((execution.get("status"), execution.get("state")))
    for candidate in candidates:
        if isinstance(candidate, str) and "TERMINAL" in candidate.upper():
            return candidate.upper()
    return None


def boolean_signal(value: Any, names: set[str]) -> bool:
    if isinstance(value, dict):
        return any(
            (key in names and child is True) or boolean_signal(child, names)
            for key, child in value.items()
        )
    if isinstance(value, list):
        return any(boolean_signal(child, names) for child in value)
    return False


def plan_identities(value: Any) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if (
                key == "plan"
                and isinstance(child, dict)
                and isinstance(child.get("path"), str)
                and isinstance(child.get("sha256"), str)
            ):
                found.append({"path": child["path"], "sha256": child["sha256"]})
            found.extend(plan_identities(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(plan_identities(child))
    return found


def classify_family(
    *,
    plan_count: int,
    failed_count: int,
    succeeded_count: int,
    workload_started_count: int,
    unexecuted_count: int,
    max_plan_versions: int,
    max_failed_attempts: int,
    max_unexecuted_revisions: int,
) -> str:
    if workload_started_count:
        return "WORKLOAD_REACHED"
    if succeeded_count and plan_count > max_plan_versions:
        return "ADVANCE_FROM_ENVIRONMENT"
    if failed_count >= max_failed_attempts and not succeeded_count:
        return "STOP_REPAIR_SCOPE"
    if unexecuted_count >= max_unexecuted_revisions:
        return "COLLAPSE_UNEXECUTED_REVISIONS"
    return "CONTINUE_BOUNDED"


def build_report(
    run_root: Path,
    *,
    max_plan_versions: int = 3,
    max_failed_attempts: int = 3,
    max_unexecuted_revisions: int = 2,
) -> dict[str, Any]:
    run_root = run_root.resolve()
    if not run_root.is_dir():
        raise FileNotFoundError(run_root)
    if min(max_plan_versions, max_failed_attempts, max_unexecuted_revisions) < 1:
        raise ValueError("churn thresholds must be positive")

    plans: dict[str, list[dict[str, Any]]] = defaultdict(list)
    plans_by_name: dict[str, dict[str, Any]] = {}
    for path in sorted(run_root.rglob("*.json")):
        parsed = versioned_name(path)
        if parsed is None or PLAN_MARKER not in parsed[0].lower():
            continue
        family, version = parsed
        row = {
            "version": version,
            "path": path.relative_to(run_root).as_posix(),
            "sha256": sha256_file(path),
            "terminal_statuses": [],
            "workload_started": False,
            "gpu_used": False,
        }
        if path.name in plans_by_name:
            raise ValueError(f"duplicate versioned plan basename: {path.name}")
        plans[family].append(row)
        plans_by_name[path.name] = row

    orphan_terminal_artifacts: list[str] = []
    terminal_artifact_count = 0
    for path in sorted(run_root.rglob("*.json")):
        if not any(marker in path.stem.lower() for marker in TERMINAL_MARKERS):
            continue
        value = read_object(path)
        status = terminal_status(value)
        if status is None:
            continue
        identities = plan_identities(value)
        linked = False
        for identity in identities:
            plan = plans_by_name.get(Path(identity["path"]).name)
            if plan is None:
                continue
            if plan["sha256"] != identity["sha256"]:
                raise ValueError(
                    f"terminal artifact binds changed plan: {path.relative_to(run_root)}"
                )
            if status not in plan["terminal_statuses"]:
                plan["terminal_statuses"].append(status)
            plan["workload_started"] = plan["workload_started"] or boolean_signal(
                value, {"workload_started", "workload_used", "workload_executed"}
            )
            plan["gpu_used"] = plan["gpu_used"] or boolean_signal(value, {"gpu_used"})
            linked = True
        if linked:
            terminal_artifact_count += 1
        else:
            orphan_terminal_artifacts.append(path.relative_to(run_root).as_posix())

    families = []
    for family, rows in sorted(plans.items()):
        rows.sort(key=lambda row: row["version"])
        versions = [row["version"] for row in rows]
        if len(versions) != len(set(versions)):
            raise ValueError(f"duplicate plan version in family: {family}")
        terminal_rows = [row for row in rows if row["terminal_statuses"]]
        failed = [
            row
            for row in terminal_rows
            if any("FAIL" in status for status in row["terminal_statuses"])
        ]
        succeeded = [
            row
            for row in terminal_rows
            if any(
                token in status
                for status in row["terminal_statuses"]
                for token in ("SUCCEEDED", "SUCCESS", "PASS")
            )
        ]
        workload = [row for row in rows if row["workload_started"]]
        unexecuted_count = len(rows) - len(terminal_rows)
        decision = classify_family(
            plan_count=len(rows),
            failed_count=len(failed),
            succeeded_count=len(succeeded),
            workload_started_count=len(workload),
            unexecuted_count=unexecuted_count,
            max_plan_versions=max_plan_versions,
            max_failed_attempts=max_failed_attempts,
            max_unexecuted_revisions=max_unexecuted_revisions,
        )
        families.append(
            {
                "family_id": family,
                "plan_version_count": len(rows),
                "terminal_plan_count": len(terminal_rows),
                "failed_terminal_plan_count": len(failed),
                "succeeded_terminal_plan_count": len(succeeded),
                "unexecuted_plan_count": unexecuted_count,
                "workload_started_plan_count": len(workload),
                "decision": decision,
                "plans": rows,
            }
        )

    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now(),
        "run_root": run_root.as_posix(),
        "policy": {
            "max_plan_versions": max_plan_versions,
            "max_failed_attempts": max_failed_attempts,
            "max_unexecuted_revisions": max_unexecuted_revisions,
        },
        "summary": {
            "family_count": len(families),
            "plan_version_count": sum(row["plan_version_count"] for row in families),
            "terminal_plan_count": sum(row["terminal_plan_count"] for row in families),
            "unexecuted_plan_count": sum(
                row["unexecuted_plan_count"] for row in families
            ),
            "workload_started_plan_count": sum(
                row["workload_started_plan_count"] for row in families
            ),
            "terminal_artifact_count": terminal_artifact_count,
            "action_required_family_count": sum(
                row["decision"]
                in {
                    "ADVANCE_FROM_ENVIRONMENT",
                    "STOP_REPAIR_SCOPE",
                    "COLLAPSE_UNEXECUTED_REVISIONS",
                }
                for row in families
            ),
        },
        "families": families,
        "orphan_terminal_artifacts": orphan_terminal_artifacts,
        "claim_boundary": (
            "PLAN_AND_TERMINAL_ARTIFACT_CHURN_ONLY_NOT_EXECUTION_CORRECTNESS_"
            "PERFORMANCE_OR_AUTHORIZATION"
        ),
    }
    errors = validate_instance(
        report,
        read_object(
            repository_root() / "schemas/qualification_churn_report.schema.json"
        ),
    )
    if errors:
        raise ValueError("invalid qualification churn report: " + "; ".join(errors))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--max-plan-versions", type=int, default=3)
    parser.add_argument("--max-failed-attempts", type=int, default=3)
    parser.add_argument("--max-unexecuted-revisions", type=int, default=2)
    args = parser.parse_args()
    report = build_report(
        args.run,
        max_plan_versions=args.max_plan_versions,
        max_failed_attempts=args.max_failed_attempts,
        max_unexecuted_revisions=args.max_unexecuted_revisions,
    )
    if args.output:
        atomic_json(args.output.resolve(), report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
