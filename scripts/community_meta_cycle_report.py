#!/usr/bin/env python3
"""Validate a final, evidence-bound cross-framework policy decision."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path

from community_evaluation import validate_preselection_anchor
from community_knowledge import read_object, sha256_file
from community_work_cycle import validate_ledger
from schema_utils import validate_instance, validate_json_file


REPORT_SCHEMA = "community-meta-cycle-report-v1"
PAIR_SCHEMA = "community-ab-report-v1"
REPEAT_SCHEMA = "community-ab-repeat-summary-v1"
ASSESSMENT_SCHEMA = "community-trial-assessment-v1"


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp must include a timezone: {value}")
    return parsed


def resolve_inside(base: Path, relative: str) -> Path:
    base = base.resolve()
    path = (base / relative).resolve()
    try:
        path.relative_to(base)
    except ValueError as error:
        raise ValueError(f"identity path escapes its artifact root: {relative}") from error
    return path


def validate_identity(base: Path, identity: dict, label: str) -> Path:
    path = resolve_inside(base, identity["path"])
    if not path.is_file():
        raise FileNotFoundError(f"{label} is missing: {path}")
    if sha256_file(path) != identity["sha256"]:
        raise ValueError(f"{label} hash changed: {identity['path']}")
    return path


def validate_schema(path: Path, schema_name: str, label: str, root: Path) -> dict:
    errors = validate_json_file(path, root / "schemas" / schema_name)
    if errors:
        raise ValueError(f"invalid {label}: " + "; ".join(errors))
    return read_object(path)


def git_blob(root: Path, commit: str, relative: str) -> bytes:
    process = subprocess.run(
        ["git", "show", f"{commit}:{relative}"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if process.returncode != 0:
        detail = process.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(f"cannot read frozen protocol from git: {detail}")
    return process.stdout


def validate_descendant_commit(root: Path, ancestor: str, descendant: str) -> None:
    resolved = subprocess.run(
        ["git", "rev-parse", f"{descendant}^{{commit}}"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if resolved.returncode != 0 or resolved.stdout.strip() != descendant:
        raise ValueError("shared_default_commit is not an available Git commit")
    ancestry = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if ancestry.returncode != 0 or ancestor == descendant:
        raise ValueError("shared_default_commit must descend from the frozen protocol commit")


def validate_pair_chain(summary_path: Path, summary: dict, root: Path) -> int:
    repeats: set[int] = set()
    treatment_realized = 0
    for index, identity in enumerate(summary["pair_reports"]):
        pair_path = validate_identity(summary_path.parent, identity, f"pair report {index + 1}")
        pair = validate_schema(
            pair_path, "community_ab_report.schema.json", "paired report", root
        )
        if pair["schema_version"] != PAIR_SCHEMA:
            raise ValueError("unsupported paired report schema")
        if (
            pair["suite_id"] != summary["suite_id"]
            or pair["task_id"] != summary["task_id"]
        ):
            raise ValueError("pair report suite/task does not match repeat summary")
        repeat_index = pair["repeat_index"]
        if repeat_index in repeats:
            raise ValueError("duplicate repeat index in pair reports")
        repeats.add(repeat_index)
        for arm, key in (
            ("CONTROL", "control_assessment"),
            ("COMMUNITY_AUGMENTED", "community_assessment"),
        ):
            assessment_path = validate_identity(
                pair_path.parent, pair[key], f"{arm} assessment"
            )
            assessment = validate_schema(
                assessment_path,
                "community_trial_assessment.schema.json",
                "trial assessment",
                root,
            )
            if assessment["schema_version"] != ASSESSMENT_SCHEMA:
                raise ValueError("unsupported trial assessment schema")
            if (
                assessment["arm"] != arm
                or assessment["suite_id"] != summary["suite_id"]
                or assessment["task_id"] != summary["task_id"]
                or assessment["repeat_index"] != repeat_index
            ):
                raise ValueError("paired assessment identity does not match report")
        fidelity = pair["treatment_fidelity"]
        realized = fidelity["community_event_prior_realized"] or fidelity["method_prior_realized"]
        if fidelity["any_prior_realized"] != realized:
            raise ValueError("pair treatment fidelity flags are internally inconsistent")
        expected_interpretation = (
            "TREATMENT_REALIZED" if realized else "ASSIGNMENT_WITHOUT_REALIZED_PRIOR"
        )
        if fidelity["causal_interpretation"] != expected_interpretation:
            raise ValueError("pair causal interpretation conflicts with treatment fidelity")
        treatment_realized += int(realized)
    expected = set(range(1, summary["repeat_count"] + 1))
    if repeats != expected:
        raise ValueError(f"pair repeat indices must be exactly 1..{summary['repeat_count']}")
    if len(summary["pair_reports"]) != summary["repeat_count"]:
        raise ValueError("repeat summary pair count does not match repeat_count")
    return treatment_realized


def validate_work_cycles(
    framework: dict, expected_repeats: int, evidence_root: Path
) -> bool:
    expected_indices = set(range(1, expected_repeats + 1))
    all_prospective = True
    seen_paths: set[Path] = set()
    for arm in ("control", "community_augmented"):
        rows = framework["work_cycles"][arm]
        indices = [row["repeat_index"] for row in rows]
        if (
            len(rows) != expected_repeats
            or set(indices) != expected_indices
            or len(indices) != len(set(indices))
        ):
            raise ValueError(
                f"{framework['repository']} {arm} work cycles must cover "
                f"exactly 1..{expected_repeats}"
            )
        for row in rows:
            ledger_path = validate_identity(
                evidence_root,
                row["identity"],
                f"{framework['repository']} {arm} repeat {row['repeat_index']} ledger",
            )
            if ledger_path in seen_paths:
                raise ValueError("one work-cycle ledger cannot represent multiple arms or repeats")
            seen_paths.add(ledger_path)
            ledger = validate_ledger(ledger_path, allow_active=False)
            if ledger["task_id"] != framework["task_id"]:
                raise ValueError("work-cycle task_id does not match framework result")
            all_prospective = all_prospective and ledger["observation_mode"] == "PROSPECTIVE_EXACT"
    return all_prospective


def validate_report(
    report_path: Path, evidence_root: Path, root: Path | None = None
) -> dict:
    root = (root or repository_root()).resolve()
    report_path = report_path.resolve()
    evidence_root = evidence_root.resolve()
    report = validate_schema(
        report_path,
        "community_meta_cycle_report.schema.json",
        "meta-cycle report",
        root,
    )
    if report["schema_version"] != REPORT_SCHEMA:
        raise ValueError("unsupported meta-cycle report schema")

    resolve_inside(root, report["protocol_identity"]["path"])
    protocol_bytes = git_blob(root, report["protocol_commit"], report["protocol_identity"]["path"])
    if (
        hashlib.sha256(protocol_bytes).hexdigest()
        != report["protocol_identity"]["sha256"]
    ):
        raise ValueError("protocol identity does not match the frozen git commit")
    try:
        protocol = json.loads(protocol_bytes)
    except json.JSONDecodeError as error:
        raise ValueError("frozen cycle protocol is not valid JSON") from error
    protocol_errors = validate_instance(
        protocol, read_object(root / "schemas/community_meta_cycle.schema.json")
    )
    if protocol_errors:
        raise ValueError("invalid frozen cycle protocol: " + "; ".join(protocol_errors))
    if protocol["cycle_id"] != report["cycle_id"]:
        raise ValueError("report cycle_id does not match protocol")
    preregistration_identity = protocol["discovery_preregistration_identity"]
    preregistration_bytes = git_blob(
        root, report["protocol_commit"], preregistration_identity["path"]
    )
    if (
        hashlib.sha256(preregistration_bytes).hexdigest()
        != preregistration_identity["sha256"]
    ):
        raise ValueError("held-out preregistration does not match the frozen protocol")
    try:
        preregistration = json.loads(preregistration_bytes)
    except json.JSONDecodeError as error:
        raise ValueError("frozen held-out preregistration is not valid JSON") from error
    preregistration_errors = validate_instance(
        preregistration,
        read_object(root / "schemas/community_heldout_preregistration.schema.json"),
    )
    if preregistration_errors:
        raise ValueError(
            "invalid frozen held-out preregistration: " + "; ".join(preregistration_errors)
        )
    frozen_evaluation = preregistration["evaluation"]
    expected_improvements = set(protocol["decision_gate"]["improve_any"])
    expected_non_regressions = set(protocol["decision_gate"]["must_not_regress"])

    expected_repositories = set(protocol["selection"]["repositories"])
    frameworks = report["framework_results"]
    repositories = [item["repository"] for item in frameworks]
    if len(repositories) != len(set(repositories)) or set(repositories) != expected_repositories:
        raise ValueError("framework results must match the protocol repository set exactly")
    expected_repeats = protocol["selection"]["repeats"]
    qualified: list[str] = []
    every_non_regression_gate_met = True
    every_improvement_gate_met = True

    for framework in frameworks:
        suite_path = validate_identity(
            evidence_root,
            framework["suite_identity"],
            f"{framework['repository']} evaluation suite",
        )
        suite = validate_schema(
            suite_path,
            "community_temporal_suite.schema.json",
            "temporal evaluation suite",
            root,
        )
        if "preselection_anchor" not in suite:
            raise ValueError("formal Cycle 1 suite must bind its preselection anchor")
        anchor_path = validate_identity(
            suite_path.parent, suite["preselection_anchor"], "suite preselection anchor"
        )
        anchor_result = validate_preselection_anchor(anchor_path, root)
        matching_tasks = [
            task for task in suite["tasks"] if task["task_id"] == framework["task_id"]
        ]
        suite_protocol = suite["protocol"]
        frozen_suite_fields = {
            "arms": frozen_evaluation["arms"],
            "repeats": frozen_evaluation["repeats"],
            "randomized_order": frozen_evaluation["randomized_order"],
            "network_policy": frozen_evaluation["network_policy"],
            "model_identity": frozen_evaluation["model_identity"],
            "task_packet_contract": frozen_evaluation["task_packet_contract"],
            "budgets": frozen_evaluation["budgets"],
            "minimum_material_speedup": frozen_evaluation["minimum_material_speedup"],
            "metrics": frozen_evaluation["metrics"],
        }
        if (
            suite["suite_id"] != framework["suite_id"]
            or suite["cutoff_at"] != protocol["cutoff_at"]
            or anchor_result["commit"] != report["protocol_commit"]
            or anchor_result["cutoff_at"] != protocol["cutoff_at"]
            or suite_protocol["random_seed"] != preregistration["selection"]["random_seed"]
            or any(
                suite_protocol.get(key) != value
                for key, value in frozen_suite_fields.items()
            )
            or len(matching_tasks) != 1
            or matching_tasks[0]["repository"] != framework["repository"]
            or parse_time(matching_tasks[0]["available_at"]) <= parse_time(protocol["cutoff_at"])
        ):
            raise ValueError("evaluation suite does not bind the declared protocol repository/task")
        summary_path = validate_identity(
            evidence_root,
            framework["repeat_summary"],
            f"{framework['repository']} repeat summary",
        )
        summary = validate_schema(
            summary_path,
            "community_ab_repeat_summary.schema.json",
            "repeat summary",
            root,
        )
        if summary["schema_version"] != REPEAT_SCHEMA:
            raise ValueError("unsupported repeat summary schema")
        if (
            summary["suite_id"] != framework["suite_id"]
            or summary["task_id"] != framework["task_id"]
            or summary["repeat_count"] != expected_repeats
        ):
            raise ValueError(
                "framework suite/task/repeat count does not match repeat summary "
                "and protocol"
            )
        treatment_realized = validate_pair_chain(summary_path, summary, root)
        all_prospective = validate_work_cycles(framework, expected_repeats, evidence_root)

        improvements = sorted(
            key for key, value in framework["metric_verdicts"].items() if value == "BETTER"
        )
        if set(framework["metric_verdicts"]) != expected_improvements:
            raise ValueError("metric verdicts do not match the frozen improvement gate")
        regressions = sorted(
            key
            for key, value in framework["non_regression_verdicts"].items()
            if value == "REGRESSED"
        )
        if set(framework["non_regression_verdicts"]) != expected_non_regressions:
            raise ValueError("non-regression verdicts do not match the frozen gate")
        non_regression_gate = all(
            value == "NO_REGRESSION"
            for value in framework["non_regression_verdicts"].values()
        )
        qualification = framework["qualification"]
        if sorted(qualification["improvement_metrics"]) != improvements:
            raise ValueError("declared improvement_metrics do not match metric verdicts")
        if sorted(qualification["regression_metrics"]) != regressions:
            raise ValueError("declared regression_metrics do not match regression verdicts")
        if qualification["treatment_realized_repeats"] != treatment_realized:
            raise ValueError("declared treatment realization count does not match pair reports")
        calculated_qualified = (
            bool(improvements)
            and non_regression_gate
            and all_prospective
            and treatment_realized == expected_repeats
        )
        if qualification["qualified_for_cross_framework_claim"] != calculated_qualified:
            raise ValueError("framework qualification does not match evidence gates")
        if calculated_qualified:
            qualified.append(framework["repository"])
        every_improvement_gate_met = every_improvement_gate_met and bool(improvements)
        every_non_regression_gate_met = every_non_regression_gate_met and non_regression_gate

    gate = report["aggregate_gate"]
    compared = sorted(expected_repositories)
    qualified = sorted(qualified)
    minimum_frameworks = protocol["decision_gate"]["minimum_frameworks"]
    promotion_eligible = (
        len(qualified) >= minimum_frameworks
        and every_improvement_gate_met
        and every_non_regression_gate_met
    )
    expected_gate = {
        "compared_frameworks": compared,
        "qualified_frameworks": qualified,
        "improve_any_met": every_improvement_gate_met,
        "must_not_regress_met": every_non_regression_gate_met,
        "promotion_eligible": promotion_eligible,
    }
    if gate != expected_gate:
        raise ValueError("aggregate_gate does not match recomputed framework gates")

    decision = report["decision"]
    if decision["outcome"] == "PROMOTE_DEFAULT":
        if not promotion_eligible:
            raise ValueError("PROMOTE_DEFAULT requires a passing cross-framework gate")
        if decision["shared_default_commit"] is None:
            raise ValueError("PROMOTE_DEFAULT requires shared_default_commit")
        validate_descendant_commit(
            root, report["protocol_commit"], decision["shared_default_commit"]
        )
    elif decision["shared_default_commit"] is not None:
        raise ValueError("shared_default_commit is reserved for PROMOTE_DEFAULT")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate", help="validate one final policy decision")
    validate.add_argument("--report", required=True, type=Path)
    validate.add_argument("--evidence-root", required=True, type=Path)
    args = parser.parse_args()
    if args.command == "validate":
        report = validate_report(args.report, args.evidence_root)
        print(json.dumps({"status": "PASS", "cycle_id": report["cycle_id"]}, indent=2))
        return 0
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
