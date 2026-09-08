#!/usr/bin/env python3
"""Validate a final, evidence-bound cross-framework policy decision."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path
from statistics import median

from community_evaluation import validate_preselection_anchor
from community_knowledge import read_object, sha256_file
from community_work_cycle_observation import validate_observation
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


def validate_pair_chain(summary_path: Path, summary: dict, root: Path) -> dict[int, dict]:
    repeats: set[int] = set()
    pair_evidence: dict[int, dict] = {}
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
        assessments = {}
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
            assessments[arm] = {
                "path": assessment_path,
                "identity": pair[key],
                "assessment": assessment,
            }
        fidelity = pair["treatment_fidelity"]
        realized = fidelity["community_event_prior_realized"] or fidelity["method_prior_realized"]
        if fidelity["any_prior_realized"] != realized:
            raise ValueError("pair treatment fidelity flags are internally inconsistent")
        expected_interpretation = (
            "TREATMENT_REALIZED" if realized else "ASSIGNMENT_WITHOUT_REALIZED_PRIOR"
        )
        if fidelity["causal_interpretation"] != expected_interpretation:
            raise ValueError("pair causal interpretation conflicts with treatment fidelity")
        pair_evidence[repeat_index] = {
            "treatment_realized": realized,
            "assessments": assessments,
        }
    expected = set(range(1, summary["repeat_count"] + 1))
    if repeats != expected:
        raise ValueError(f"pair repeat indices must be exactly 1..{summary['repeat_count']}")
    if len(summary["pair_reports"]) != summary["repeat_count"]:
        raise ValueError("repeat summary pair count does not match repeat_count")
    return pair_evidence


def validate_observations(
    framework: dict,
    expected_repeats: int,
    evidence_root: Path,
    pair_evidence: dict[int, dict],
    protocol: dict,
    protocol_commit: str,
    root: Path,
) -> tuple[dict[str, list[dict]], bool]:
    expected_indices = set(range(1, expected_repeats + 1))
    all_prospective = True
    seen_paths: set[Path] = set()
    bundles: dict[str, list[dict]] = {"control": [], "community_augmented": []}
    arm_contracts = {
        "control": ("CONTROL", protocol["arms"]["champion"]),
        "community_augmented": (
            "COMMUNITY_AUGMENTED",
            protocol["arms"]["challenger"],
        ),
    }
    for arm, (protocol_arm, arm_contract) in arm_contracts.items():
        rows = framework["observations"][arm]
        indices = [row["repeat_index"] for row in rows]
        if (
            len(rows) != expected_repeats
            or set(indices) != expected_indices
            or len(indices) != len(set(indices))
        ):
            raise ValueError(
                f"{framework['repository']} {arm} observations must cover "
                f"exactly 1..{expected_repeats}"
            )
        for row in rows:
            observation_path = validate_identity(
                evidence_root,
                row["observation"],
                f"{framework['repository']} {arm} repeat {row['repeat_index']} observation",
            )
            if observation_path in seen_paths:
                raise ValueError("one observation cannot represent multiple arms or repeats")
            seen_paths.add(observation_path)
            bundle = validate_observation(observation_path, root)
            observation = bundle["observation"]
            repeat_index = row["repeat_index"]
            if (
                observation["repository"] != framework["repository"]
                or observation["suite_id"] != framework["suite_id"]
                or observation["task_id"] != framework["task_id"]
                or observation["repeat_index"] != repeat_index
                or observation["arm"] != protocol_arm
                or observation["search_policy"]["policy_id"]
                != arm_contract["policy_id"]
                or observation["search_policy"]["protocol_commit"] != protocol_commit
            ):
                raise ValueError("observation does not match framework, arm, or frozen policy")
            paired_assessment = pair_evidence[repeat_index]["assessments"][protocol_arm]
            if (
                bundle["assessment_path"] != paired_assessment["path"]
                or observation["assessment_identity"]["sha256"]
                != paired_assessment["identity"]["sha256"]
            ):
                raise ValueError("observation assessment does not match paired report")
            community_source = any(
                source["kind"] in {"COMMUNITY_EVENT", "METHOD", "HYBRID"}
                for source in observation["candidate_sources"]
            )
            if arm == "community_augmented" and community_source != pair_evidence[
                repeat_index
            ]["treatment_realized"]:
                raise ValueError("candidate sources conflict with pair treatment realization")
            ledger = bundle["ledger"]
            all_prospective = all_prospective and ledger["observation_mode"] == "PROSPECTIVE_EXACT"
            bundles[arm].append(bundle)
    for arm in bundles:
        bundles[arm].sort(key=lambda item: item["observation"]["repeat_index"])
    return bundles, all_prospective


def numeric_verdict(
    control: list[float | None],
    community: list[float | None],
    *,
    higher_is_better: bool,
) -> str:
    if any(value is None for value in (*control, *community)):
        return "INCONCLUSIVE"
    control_median = float(median(control))  # type: ignore[arg-type]
    community_median = float(median(community))  # type: ignore[arg-type]
    if abs(control_median - community_median) <= 1e-12 * max(
        1.0, abs(control_median), abs(community_median)
    ):
        return "NO_CHANGE"
    community_better = community_median > control_median
    if not higher_is_better:
        community_better = community_median < control_median
    return "BETTER" if community_better else "WORSE"


def non_regression_verdict(
    control: float | None, community: float | None, *, higher_is_better: bool
) -> str:
    if control is None or community is None:
        return "INCONCLUSIVE"
    tolerance = 1e-12 * max(1.0, abs(control), abs(community))
    if higher_is_better:
        return "NO_REGRESSION" if community + tolerance >= control else "REGRESSED"
    return "NO_REGRESSION" if community <= control + tolerance else "REGRESSED"


def derive_verdicts(bundles: dict[str, list[dict]]) -> tuple[dict, dict]:
    control = bundles["control"]
    community = bundles["community_augmented"]

    def assessment_values(rows: list[dict], field: str) -> list[float | None]:
        return [row["assessment"]["metrics"][field] for row in rows]

    def survivor_value(rows: list[dict]) -> float | None:
        gpu_seconds = sum(row["gpu_seconds"] for row in rows)
        if gpu_seconds <= 0:
            return None
        survivors = sum(
            int(
                any(
                    milestone["kind"] == "FIRST_QUALIFIED_RESULT"
                    for milestone in row["ledger"]["milestones"]
                )
                or row["ledger"]["outcome"]["upstream_ready"]
                or row["ledger"]["outcome"]["merged"]
            )
            for row in rows
        )
        return survivors / (gpu_seconds / 3600.0)

    gpu_values = [survivor_value(control), survivor_value(community)]
    upstream_rates = [
        sum(
            int(
                row["ledger"]["outcome"]["upstream_ready"]
                or row["ledger"]["outcome"]["merged"]
            )
            for row in rows
        )
        / len(rows)
        for rows in (control, community)
    ]
    metric_verdicts = {
        "TIME_TO_FIRST_CORRECT": numeric_verdict(
            assessment_values(control, "time_to_first_correct_seconds"),
            assessment_values(community, "time_to_first_correct_seconds"),
            higher_is_better=False,
        ),
        "TIME_TO_FIRST_IMPROVEMENT": numeric_verdict(
            assessment_values(control, "time_to_first_improvement_seconds"),
            assessment_values(community, "time_to_first_improvement_seconds"),
            higher_is_better=False,
        ),
        "VALIDATION_VALUE_PER_GPU_HOUR": numeric_verdict(
            [gpu_values[0]], [gpu_values[1]], higher_is_better=True
        ),
        "UPSTREAM_READY_OR_MERGE_RATE": numeric_verdict(
            [upstream_rates[0]], [upstream_rates[1]], higher_is_better=True
        ),
    }

    correctness_rates: list[float | None] = []
    for rows in (control, community):
        outcomes = [row["ledger"]["outcome"]["correctness"] for row in rows]
        correctness_rates.append(
            None
            if any(value == "NOT_RUN" for value in outcomes)
            else sum(value == "PASS" for value in outcomes) / len(outcomes)
        )
    regression_rates: list[float | None] = []
    for rows in (control, community):
        count = sum(row["observation"]["regression"]["test_count"] for row in rows)
        failures = sum(
            row["observation"]["regression"]["failure_count"] for row in rows
        )
        regression_rates.append(None if count == 0 else failures / count)
    workload_statuses = [
        [row["observation"]["real_workload"]["status"] for row in rows]
        for rows in (control, community)
    ]
    workload_pass_rates = [
        sum(status == "PASS" for status in statuses) / len(statuses)
        for statuses in workload_statuses
    ]
    if any("NOT_RUN" in statuses for statuses in workload_statuses):
        whole_model_verdict = "INCONCLUSIVE"
    elif workload_pass_rates[1] < workload_pass_rates[0]:
        whole_model_verdict = "REGRESSED"
    elif workload_pass_rates[1] > workload_pass_rates[0]:
        whole_model_verdict = "NO_REGRESSION"
    elif workload_pass_rates[0] < 1.0:
        whole_model_verdict = "INCONCLUSIVE"
    else:
        whole_model_medians = [
            float(
                median(
                    row["observation"]["real_workload"]["speedup"] for row in rows
                )
            )
            for rows in (control, community)
        ]
        whole_model_verdict = non_regression_verdict(
            whole_model_medians[0], whole_model_medians[1], higher_is_better=True
        )
    validation_costs = [
        sum(row["validation_seconds"] for row in rows)
        for rows in (control, community)
    ]
    non_regression_verdicts = {
        "CORRECTNESS": non_regression_verdict(
            correctness_rates[0], correctness_rates[1], higher_is_better=True
        ),
        "REGRESSION_RATE": non_regression_verdict(
            regression_rates[0], regression_rates[1], higher_is_better=False
        ),
        "WHOLE_MODEL_SPEEDUP": whole_model_verdict,
        "VALIDATION_COST": non_regression_verdict(
            validation_costs[0], validation_costs[1], higher_is_better=False
        ),
    }
    return metric_verdicts, non_regression_verdicts


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
        pair_evidence = validate_pair_chain(summary_path, summary, root)
        bundles, all_prospective = validate_observations(
            framework,
            expected_repeats,
            evidence_root,
            pair_evidence,
            protocol,
            report["protocol_commit"],
            root,
        )
        calculated_metrics, calculated_non_regressions = derive_verdicts(bundles)
        if framework["metric_verdicts"] != calculated_metrics:
            raise ValueError("metric verdicts do not match recomputed observations")
        if framework["non_regression_verdicts"] != calculated_non_regressions:
            raise ValueError(
                "non-regression verdicts do not match recomputed observations"
            )
        treatment_realized = sum(
            row["treatment_realized"] for row in pair_evidence.values()
        )

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
            and all(
                bundle["ledger"]["outcome"]["correctness"] == "PASS"
                and bundle["observation"]["real_workload"]["status"] == "PASS"
                for rows in bundles.values()
                for bundle in rows
            )
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
