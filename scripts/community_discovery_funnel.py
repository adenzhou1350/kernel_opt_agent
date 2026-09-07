#!/usr/bin/env python3
"""Measure discovery yield and retain non-actionable routing feedback."""

from __future__ import annotations

import argparse
import copy
from collections import Counter, defaultdict
from pathlib import Path

from community_evaluation import validate_preselection_chain_audit
from community_knowledge import atomic_json, now, read_object, sha256_file
from schema_utils import validate_instance, validate_json_file


SCHEMA_VERSION_V1 = "community-discovery-funnel-v1"
SCHEMA_VERSION = "community-discovery-funnel-v2"


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def identity(path: Path) -> dict:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {"path": path.as_posix(), "sha256": sha256_file(path)}


def identity_path(value: dict) -> Path:
    return Path(value["path"]).resolve()


def ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def count_rows(counter: Counter) -> list[dict]:
    return [
        {"key": key, "count": count}
        for key, count in sorted(counter.items(), key=lambda item: item[0])
    ]


def schema_path(root: Path, version: str) -> Path:
    names = {
        SCHEMA_VERSION_V1: "community_discovery_funnel.schema.json",
        SCHEMA_VERSION: "community_discovery_funnel_v2.schema.json",
    }
    if version not in names:
        raise ValueError(f"unsupported discovery funnel: {version}")
    return root / "schemas" / names[version]


def build_funnel(
    audit_paths: list[Path], corpus: Path, root: Path | None = None
) -> dict:
    """Revalidate complete chains and summarize preselection routing yield."""
    root = (root or repository_root()).resolve()
    corpus = corpus.resolve()
    resolved = sorted({path.resolve() for path in audit_paths})
    if not resolved:
        raise ValueError("at least one preselection chain audit is required")

    repositories: Counter = Counter()
    exclusion_reasons: Counter = Counter()
    screen_statuses: Counter = Counter()
    screen_reasons: Counter = Counter()
    task_families: Counter = Counter()
    selected_items: list[dict] = []
    unique_candidates: set[tuple[str, int]] = set()
    total_search_matches = 0
    total_candidate_observations = 0
    receipt_count = 0

    for audit_path in resolved:
        validate_preselection_chain_audit(audit_path, corpus, root)
        audit = read_object(audit_path)
        queue_path = identity_path(audit["input_identity"]["queue"])
        screen_path = identity_path(audit["input_identity"]["feasibility_screen"])
        queue = read_object(queue_path)
        screen = read_object(screen_path)
        screen_by_key = {
            (row["repository"], int(row["pr_number"])): row for row in screen["items"]
        }
        for receipt_identity in queue["input_identity"]["receipts"]:
            receipt = read_object(identity_path(receipt_identity))
            receipt_count += 1
            repositories[receipt["repository"]] += 1
            total_search_matches += int(receipt["search_total_count"])
            total_candidate_observations += int(receipt["candidate_count"])
            unique_candidates.update(
                (receipt["repository"], int(candidate["pr_number"]))
                for candidate in receipt["candidates"]
            )
        for excluded in queue["excluded"]:
            exclusion_reasons[excluded["reason"]] += 1
        for candidate in queue["items"]:
            if candidate["selection"] != "SELECTED":
                continue
            key = (candidate["repository"], int(candidate["pr_number"]))
            screened = screen_by_key.get(key)
            if screened is None:
                raise ValueError(f"selected candidate is not screened: {key}")
            screen_statuses[screened["status"]] += 1
            screen_reasons[screened["reason"]] += 1
            task_families[screened["task_family"]] += 1
            selected_items.append(
                {
                    "repository": candidate["repository"],
                    "pr_number": candidate["pr_number"],
                    "title": candidate["title"],
                    "classifications": candidate["classifications"],
                    "discovery_score": candidate["discovery_score"],
                    "earliest_public_at": candidate["earliest_public_at"],
                    "screen_status": screened["status"],
                    "screen_reason": screened["reason"],
                    "task_family": screened["task_family"],
                    "matched_rule_id": screened["matched_rule_id"],
                    "source_audit": identity(audit_path),
                }
            )

    selected_items.sort(
        key=lambda row: (
            row["earliest_public_at"],
            row["repository"],
            row["pr_number"],
        )
    )
    grouped: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for item in selected_items:
        grouped[
            (
                item["matched_rule_id"],
                item["screen_reason"],
                item["task_family"],
            )
        ].append(item)
    shadow_recommendations = []
    for (rule_id, reason, family), rows in sorted(grouped.items()):
        distinct_rows = {(row["repository"], row["pr_number"]): row for row in rows}
        distinct_runnable = sum(
            any(
                row["screen_status"] == "ELIGIBLE"
                for row in rows
                if (row["repository"], row["pr_number"]) == candidate_key
            )
            for candidate_key in distinct_rows
        )
        if distinct_runnable:
            recommendation = "KEEP"
        elif len(distinct_rows) >= 2:
            recommendation = "CONSIDER_DISCOVERY_DEMOTION"
        else:
            recommendation = "COLLECT_MORE"
        shadow_recommendations.append(
            {
                "matched_rule_id": rule_id,
                "screen_reason": reason,
                "task_family": family,
                "observation_count": len(rows),
                "distinct_candidate_count": len(distinct_rows),
                "runnable_count": distinct_runnable,
                "recommendation": recommendation,
                "candidate_keys": [
                    f"{repository}#{pr_number}"
                    for repository, pr_number in sorted(distinct_rows)
                ],
            }
        )

    post_cutoff_selected = len(selected_items)
    runnable = int(screen_statuses["ELIGIBLE"])
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now(),
        "claim_boundary": "DESCRIPTIVE_DISCOVERY_YIELD_NOT_SELECTION_POLICY",
        "input_identity": {
            "audits": [identity(path) for path in resolved],
            "corpus_index": identity(corpus / "index.json"),
        },
        "inventory": {
            "window_count": len(resolved),
            "receipt_count": receipt_count,
            "search_match_observations": total_search_matches,
            "discovery_candidate_observations": total_candidate_observations,
            "unique_discovery_candidates": len(unique_candidates),
            "post_cutoff_selected": post_cutoff_selected,
            "runnable_selected": runnable,
            "infeasible_selected": int(screen_statuses["INFEASIBLE"]),
            "harness_blocked_selected": int(screen_statuses["HARNESS_BLOCKED"]),
        },
        "yield": {
            "search_to_discovery": ratio(
                total_candidate_observations, total_search_matches
            ),
            "discovery_to_post_cutoff": ratio(
                post_cutoff_selected, total_candidate_observations
            ),
            "discovery_to_runnable": ratio(runnable, total_candidate_observations),
            "post_cutoff_to_runnable": ratio(runnable, post_cutoff_selected),
        },
        "repository_receipt_counts": count_rows(repositories),
        "exclusion_reason_counts": count_rows(exclusion_reasons),
        "screen_status_counts": count_rows(screen_statuses),
        "screen_reason_counts": count_rows(screen_reasons),
        "task_family_counts": count_rows(task_families),
        "selected_items": selected_items,
        "shadow_recommendations": shadow_recommendations,
        "limitations": [
            "This report observes frozen selection chains and cannot change the current cohort.",
            "A demotion suggestion requires at least two distinct non-runnable PRs in the same rule/reason/family group; repeated updates never count as independent evidence.",
            "Discovery yield is scheduling evidence, not evidence of performance improvement.",
        ],
    }
    errors = validate_instance(
        report,
        read_object(schema_path(root, SCHEMA_VERSION)),
    )
    if errors:
        raise ValueError("invalid discovery funnel: " + "; ".join(errors))
    return report


def legacy_v1_view(report: dict) -> dict:
    """Reproduce the committed v1 surface for immutable artifact validation."""
    legacy = copy.deepcopy(report)
    legacy["schema_version"] = SCHEMA_VERSION_V1
    for recommendation in legacy["shadow_recommendations"]:
        rows = [
            row
            for row in legacy["selected_items"]
            if row["matched_rule_id"] == recommendation["matched_rule_id"]
            and row["screen_reason"] == recommendation["screen_reason"]
            and row["task_family"] == recommendation["task_family"]
        ]
        runnable = sum(row["screen_status"] == "ELIGIBLE" for row in rows)
        recommendation["runnable_count"] = runnable
        recommendation["recommendation"] = (
            "KEEP"
            if runnable
            else "CONSIDER_DISCOVERY_DEMOTION"
            if len(rows) >= 2
            else "COLLECT_MORE"
        )
        recommendation["candidate_keys"] = [
            f"{row['repository']}#{row['pr_number']}" for row in rows
        ]
        recommendation.pop("distinct_candidate_count")
    legacy["limitations"][1] = (
        "A demotion suggestion requires at least two non-runnable observations in the same rule/reason/family group."
    )
    return legacy


def validate_funnel(report_path: Path, corpus: Path, root: Path | None = None) -> dict:
    root = (root or repository_root()).resolve()
    report_path = report_path.resolve()
    observed = read_object(report_path)
    version = observed.get("schema_version")
    errors = validate_json_file(report_path, schema_path(root, version))
    if errors:
        raise ValueError("invalid discovery funnel: " + "; ".join(errors))
    corpus_index = corpus.resolve() / "index.json"
    corpus_identity = observed["input_identity"]["corpus_index"]
    if identity_path(corpus_identity) != corpus_index:
        raise ValueError("discovery funnel corpus index path changed")
    if sha256_file(corpus_index) != corpus_identity["sha256"]:
        raise ValueError("discovery funnel corpus index changed")
    audit_paths = []
    for audit_identity in observed["input_identity"]["audits"]:
        audit_path = identity_path(audit_identity)
        if (
            not audit_path.is_file()
            or sha256_file(audit_path) != audit_identity["sha256"]
        ):
            raise ValueError(f"discovery funnel audit changed: {audit_path}")
        audit_paths.append(audit_path)
    expected = build_funnel(audit_paths, corpus, root)
    if version == SCHEMA_VERSION_V1:
        expected = legacy_v1_view(expected)
    observed_stable = {
        key: value for key, value in observed.items() if key != "generated_at"
    }
    expected_stable = {
        key: value for key, value in expected.items() if key != "generated_at"
    }
    if observed_stable != expected_stable:
        raise ValueError("discovery funnel is stale or was edited")
    return {"status": "PASS", **observed["inventory"], **observed["yield"]}


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    operations = value.add_subparsers(dest="operation", required=True)
    build = operations.add_parser("build")
    build.add_argument("--audit", action="append", type=Path, required=True)
    build.add_argument("--corpus", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    validate = operations.add_parser("validate")
    validate.add_argument("--report", type=Path, required=True)
    validate.add_argument("--corpus", type=Path, required=True)
    return value


def main() -> int:
    args = parser().parse_args()
    if args.operation == "build":
        report = build_funnel(args.audit, args.corpus)
        atomic_json(args.output, report)
        print(args.output.resolve())
    else:
        print(validate_funnel(args.report, args.corpus))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
