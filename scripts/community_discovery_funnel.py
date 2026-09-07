#!/usr/bin/env python3
"""Measure discovery yield and retain non-actionable routing feedback."""

from __future__ import annotations

import argparse
import copy
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from community_evaluation import validate_preselection_chain_audit
from community_knowledge import atomic_json, now, read_object, sha256_file
from community_validation_session import ValidationSession
from schema_utils import validate_instance, validate_json_file


SCHEMA_VERSION_V1 = "community-discovery-funnel-v1"
SCHEMA_VERSION = "community-discovery-funnel-v2"
ROUTING_SNAPSHOT_SCHEMA = "community-discovery-routing-snapshot-v1"


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


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def resource_satisfies(resource: dict, requirements: dict) -> bool:
    vendors = set(requirements["vendors_any"])
    return (
        (not vendors or resource["vendor"] in vendors)
        and set(requirements["capabilities_all"]) <= set(resource["capabilities"])
        and resource["gpu_count"] >= requirements["minimum_gpu_count"]
        and resource["memory_gib_per_gpu"]
        >= requirements["minimum_memory_gib_per_gpu"]
    )


def derive_routing_rules(funnel: dict, policy: dict, profile: dict) -> list[dict]:
    """Promote only repeated, context-matched, reversible non-runnable evidence."""
    policy_rules = {rule["rule_id"]: rule for rule in policy["rules"]}
    routed = []
    for recommendation in funnel["shadow_recommendations"]:
        if (
            recommendation["recommendation"]
            != "CONSIDER_DISCOVERY_DEMOTION"
            or recommendation["screen_reason"]
            != "NO_DECLARED_RESOURCE_SATISFIES_REQUIREMENTS"
            or recommendation["distinct_candidate_count"] < 2
            or recommendation["runnable_count"] != 0
        ):
            continue
        rule = policy_rules.get(recommendation["matched_rule_id"])
        if rule is None or rule["task_family"] != recommendation["task_family"]:
            continue
        if any(
            resource_satisfies(resource, rule["requirements"])
            for resource in profile["resources"]
        ):
            continue
        routed.append(
            {
                "rule_id": rule["rule_id"],
                "task_family": rule["task_family"],
                "screen_reason": recommendation["screen_reason"],
                "match": copy.deepcopy(rule["match"]),
                "distinct_candidate_count": recommendation[
                    "distinct_candidate_count"
                ],
                "runnable_count": 0,
                "evidence_candidate_keys": sorted(
                    recommendation["candidate_keys"]
                ),
                "action": "DEFER_AFTER_CONTEXT_MATCHED_RUNNABLE_CANDIDATES",
                "reversal": (
                    "CANCEL_WHEN_ANY_RUNNABLE_COUNTEREXAMPLE_APPEARS_IN_SAME_CONTEXT"
                ),
            }
        )
    return sorted(routed, key=lambda row: row["rule_id"])


def schema_path(root: Path, version: str) -> Path:
    names = {
        SCHEMA_VERSION_V1: "community_discovery_funnel.schema.json",
        SCHEMA_VERSION: "community_discovery_funnel_v2.schema.json",
    }
    if version not in names:
        raise ValueError(f"unsupported discovery funnel: {version}")
    return root / "schemas" / names[version]


def build_funnel(
    audit_paths: list[Path],
    corpus: Path,
    root: Path | None = None,
    validation_session: ValidationSession | None = None,
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
        validate_preselection_chain_audit(
            audit_path, corpus, root, validation_session=validation_session
        )
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


def validate_funnel(
    report_path: Path,
    corpus: Path,
    root: Path | None = None,
    validation_session: ValidationSession | None = None,
) -> dict:
    root = (root or repository_root()).resolve()
    report_path = report_path.resolve()
    corpus = corpus.resolve()
    if validation_session is not None:
        cached = validation_session.get(
            "discovery-funnel-v2",
            report_path,
            context=(corpus / "index.json",),
        )
        if cached is not None:
            return cached
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
    expected = build_funnel(
        audit_paths,
        corpus,
        root,
        validation_session=validation_session,
    )
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
    result = {"status": "PASS", **observed["inventory"], **observed["yield"]}
    if validation_session is not None:
        validation_session.put(
            "discovery-funnel-v2",
            report_path,
            result,
            context=(corpus / "index.json",),
        )
    return result


def build_routing_snapshot(
    funnel_path: Path,
    policy_path: Path,
    profile_path: Path,
    corpus: Path,
    root: Path | None = None,
) -> dict:
    root = (root or repository_root()).resolve()
    funnel_path = funnel_path.resolve()
    policy_path = policy_path.resolve()
    profile_path = profile_path.resolve()
    funnel = read_object(funnel_path)
    source_roots: set[Path] = set()
    for audit_identity in funnel["input_identity"]["audits"]:
        audit = read_object(identity_path(audit_identity))
        anchor = read_object(identity_path(audit["input_identity"]["anchor"]))
        source_roots.add(Path(anchor["git_anchor"]["repository"]).resolve())
    if len(source_roots) != 1:
        raise ValueError("discovery funnel audits do not share one source repository")
    validate_funnel(funnel_path, corpus, source_roots.pop())
    for path, schema_name, label in (
        (policy_path, "community_feasibility_policy.schema.json", "policy"),
        (profile_path, "community_execution_profile.schema.json", "profile"),
    ):
        errors = validate_json_file(path, root / "schemas" / schema_name)
        if errors:
            raise ValueError(f"invalid discovery routing {label}: " + "; ".join(errors))
    policy = read_object(policy_path)
    profile = read_object(profile_path)
    rules = derive_routing_rules(funnel, policy, profile)
    if not rules:
        raise ValueError("no context-valid discovery demotion has enough evidence")
    available_at = max(
        (funnel["generated_at"], policy["declared_at"], profile["observed_at"]),
        key=parse_time,
    )
    snapshot = {
        "schema_version": ROUTING_SNAPSHOT_SCHEMA,
        "generated_at": now(),
        "available_at": available_at,
        "claim_boundary": (
            "NEXT_COHORT_CONTEXT_ROUTING_NOT_CURRENT_COHORT_SELECTION_OR_PERFORMANCE_EVIDENCE"
        ),
        "input_identity": {
            "source_funnel": {
                "schema_version": funnel["schema_version"],
                "generated_at": funnel["generated_at"],
                "sha256": sha256_file(funnel_path),
            },
            "feasibility_policy": {
                "policy_id": policy["policy_id"],
                "declared_at": policy["declared_at"],
                "sha256": sha256_file(policy_path),
            },
            "execution_profile": {
                "profile_id": profile["profile_id"],
                "observed_at": profile["observed_at"],
                "sha256": sha256_file(profile_path),
            },
        },
        "profile_id": profile["profile_id"],
        "minimum_distinct_candidates": 2,
        "rules": rules,
        "limitations": [
            "A snapshot may be consumed only when available_at is no later than the next cohort cutoff.",
            "Rules are bound to one exact feasibility policy and execution profile; they never transfer across hardware contexts by name alone.",
            "Demotion changes ordering only and never removes a candidate or proves a performance outcome.",
            "Any runnable counterexample in the same rule/reason/family context cancels the rule when the next snapshot is rebuilt.",
        ],
    }
    errors = validate_instance(
        snapshot,
        read_object(root / "schemas/community_discovery_routing_snapshot.schema.json"),
    )
    if errors:
        raise ValueError("invalid discovery routing snapshot: " + "; ".join(errors))
    return snapshot


def validate_routing_snapshot(
    snapshot_path: Path,
    root: Path | None = None,
) -> dict:
    root = (root or repository_root()).resolve()
    snapshot_path = snapshot_path.resolve()
    errors = validate_json_file(
        snapshot_path,
        root / "schemas/community_discovery_routing_snapshot.schema.json",
    )
    if errors:
        raise ValueError("invalid discovery routing snapshot: " + "; ".join(errors))
    observed = read_object(snapshot_path)
    inputs = observed["input_identity"]
    expected_available_at = max(
        (
            inputs["source_funnel"]["generated_at"],
            inputs["feasibility_policy"]["declared_at"],
            inputs["execution_profile"]["observed_at"],
        ),
        key=parse_time,
    )
    if observed["available_at"] != expected_available_at:
        raise ValueError("discovery routing available_at differs from its inputs")
    if observed["profile_id"] != inputs["execution_profile"]["profile_id"]:
        raise ValueError("discovery routing profile id differs from its input")
    for rule in observed["rules"]:
        if rule["distinct_candidate_count"] != len(rule["evidence_candidate_keys"]):
            raise ValueError("discovery routing evidence count is inconsistent")
    return {
        "status": "PASS",
        "profile_id": observed["profile_id"],
        "rule_count": len(observed["rules"]),
        "available_at": observed["available_at"],
    }


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
    routing = operations.add_parser("build-routing")
    routing.add_argument("--funnel", type=Path, required=True)
    routing.add_argument("--policy", type=Path, required=True)
    routing.add_argument("--profile", type=Path, required=True)
    routing.add_argument("--corpus", type=Path, required=True)
    routing.add_argument("--output", type=Path, required=True)
    routing_validate = operations.add_parser("validate-routing")
    routing_validate.add_argument("--snapshot", type=Path, required=True)
    return value


def main() -> int:
    args = parser().parse_args()
    if args.operation == "build":
        report = build_funnel(args.audit, args.corpus)
        atomic_json(args.output, report)
        print(args.output.resolve())
    elif args.operation == "validate":
        print(validate_funnel(args.report, args.corpus))
    elif args.operation == "build-routing":
        snapshot = build_routing_snapshot(
            args.funnel,
            args.policy,
            args.profile,
            args.corpus,
        )
        atomic_json(args.output, snapshot)
        print(args.output.resolve())
    else:
        print(validate_routing_snapshot(args.snapshot))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
