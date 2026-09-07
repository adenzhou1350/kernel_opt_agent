#!/usr/bin/env python3
"""Build and consume hash-bound prefixes for fast discovery-funnel validation."""

from __future__ import annotations

import argparse
import copy
from collections import Counter, defaultdict
from pathlib import Path

from community_discovery_funnel import (
    count_rows,
    identity,
    identity_path,
    ratio,
    validate_funnel,
)
from community_evaluation import validate_preselection_chain_audit
from community_knowledge import atomic_json, now, read_object, sha256_file
from community_validation_session import ValidationSession
from schema_utils import validate_instance, validate_json_file

SCHEMA_VERSION = "community-funnel-checkpoint-v1"
CLAIM_BOUNDARY = "FAST_PREFIX_VALIDATION_NOT_RELEASE_EVIDENCE"


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def schema_path(root: Path) -> Path:
    return root / "schemas/community_funnel_checkpoint.schema.json"


def _candidate_key(repository: str, pr_number: int) -> str:
    return f"{repository}#{pr_number}"


def _counter(rows: list[dict]) -> Counter:
    return Counter({row["key"]: int(row["count"]) for row in rows})


def _shadow_recommendations(selected_items: list[dict]) -> list[dict]:
    grouped: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for item in selected_items:
        grouped[
            (item["matched_rule_id"], item["screen_reason"], item["task_family"])
        ].append(item)
    output = []
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
        output.append(
            {
                "matched_rule_id": rule_id,
                "screen_reason": reason,
                "task_family": family,
                "observation_count": len(rows),
                "distinct_candidate_count": len(distinct_rows),
                "runnable_count": distinct_runnable,
                "recommendation": (
                    "KEEP"
                    if distinct_runnable
                    else "CONSIDER_DISCOVERY_DEMOTION"
                    if len(distinct_rows) >= 2
                    else "COLLECT_MORE"
                ),
                "candidate_keys": [
                    _candidate_key(repository, pr_number)
                    for repository, pr_number in sorted(distinct_rows)
                ],
            }
        )
    return output


def build_checkpoint(
    funnel_path: Path,
    corpus: Path,
    root: Path | None = None,
    source_root: Path | None = None,
) -> dict:
    """Pay for one full replay and freeze the semantically validated prefix."""
    root = (root or repository_root()).resolve()
    source_root = (source_root or root).resolve()
    funnel_path = funnel_path.resolve()
    corpus = corpus.resolve()
    validate_funnel(funnel_path, corpus, source_root)
    funnel = read_object(funnel_path)
    if funnel["schema_version"] != "community-discovery-funnel-v2":
        raise ValueError("only discovery funnel v2 can seed an incremental checkpoint")
    unique_candidates = set()
    for audit_identity in funnel["input_identity"]["audits"]:
        audit = read_object(identity_path(audit_identity))
        queue = read_object(identity_path(audit["input_identity"]["queue"]))
        for receipt_identity in queue["input_identity"]["receipts"]:
            receipt = read_object(identity_path(receipt_identity))
            unique_candidates.update(
                _candidate_key(receipt["repository"], int(candidate["pr_number"]))
                for candidate in receipt["candidates"]
            )
    closure_session = ValidationSession(source_root, identity_roots=(corpus,))
    prefix_closure = closure_session.identity_closure(
        (funnel_path, corpus / "index.json")
    )
    checkpoint = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now(),
        "claim_boundary": CLAIM_BOUNDARY,
        "input_identity": {
            "source_funnel": identity(funnel_path),
            "corpus_index": identity(corpus / "index.json"),
            "audit_prefix": copy.deepcopy(funnel["input_identity"]["audits"]),
            "source_root": source_root.as_posix(),
        },
        "state": {
            "unique_candidate_keys": sorted(unique_candidates),
            "prefix_identity_closure": [
                {"path": path, "sha256": digest}
                for path, digest in sorted(prefix_closure.items())
            ],
        },
        "limitations": [
            (
                "The checkpoint is valid only for fast scheduling after its source "
                "funnel has passed one full replay."
            ),
            (
                "Every release claim still requires an independent full "
                "no-checkpoint validation."
            ),
            (
                "The exact checkpoint identity must be frozen before observing "
                "the next window."
            ),
        ],
    }
    errors = validate_instance(checkpoint, read_object(schema_path(root)))
    if errors:
        raise ValueError("invalid funnel checkpoint: " + "; ".join(errors))
    return checkpoint


def validate_checkpoint(
    checkpoint_path: Path,
    corpus: Path,
    root: Path | None = None,
    source_root: Path | None = None,
) -> dict:
    root = (root or repository_root()).resolve()
    checkpoint_path = checkpoint_path.resolve()
    corpus = corpus.resolve()
    errors = validate_json_file(checkpoint_path, schema_path(root))
    if errors:
        raise ValueError("invalid funnel checkpoint: " + "; ".join(errors))
    checkpoint = read_object(checkpoint_path)
    inputs = checkpoint["input_identity"]
    recorded_source_root = Path(inputs["source_root"]).resolve()
    if source_root is not None and source_root.resolve() != recorded_source_root:
        raise ValueError("funnel checkpoint source root differs from request")
    corpus_index = corpus / "index.json"
    if (
        identity_path(inputs["corpus_index"]) != corpus_index
        or sha256_file(corpus_index) != inputs["corpus_index"]["sha256"]
    ):
        raise ValueError("funnel checkpoint corpus index changed")
    funnel_path = identity_path(inputs["source_funnel"])
    if (
        not funnel_path.is_file()
        or sha256_file(funnel_path) != inputs["source_funnel"]["sha256"]
    ):
        raise ValueError("funnel checkpoint source funnel changed")
    funnel = read_object(funnel_path)
    if funnel.get("schema_version") != "community-discovery-funnel-v2":
        raise ValueError("funnel checkpoint source is not v2")
    if funnel["input_identity"]["corpus_index"] != inputs["corpus_index"]:
        raise ValueError("funnel checkpoint corpus binding differs from source")
    if funnel["input_identity"]["audits"] != inputs["audit_prefix"]:
        raise ValueError("funnel checkpoint audit prefix differs from source")
    if (
        len(checkpoint["state"]["unique_candidate_keys"])
        != funnel["inventory"]["unique_discovery_candidates"]
    ):
        raise ValueError("funnel checkpoint unique-candidate count differs from source")
    closure_session = ValidationSession(
        recorded_source_root,
        identity_roots=(corpus,),
    )
    observed_closure = [
        {"path": path, "sha256": digest}
        for path, digest in sorted(
            closure_session.identity_closure((funnel_path, corpus_index)).items()
        )
    ]
    if observed_closure != checkpoint["state"]["prefix_identity_closure"]:
        raise ValueError("funnel checkpoint prefix identity closure changed")
    return {
        "status": "PASS",
        "validation_mode": "FULL_IDENTITY_CLOSURE_REPLAY",
        "prefix_window_count": len(inputs["audit_prefix"]),
        "unique_discovery_candidates": len(
            checkpoint["state"]["unique_candidate_keys"]
        ),
    }


def validate_checkpoint_fast(
    checkpoint_path: Path,
    corpus: Path,
    root: Path | None = None,
    source_root: Path | None = None,
) -> dict:
    """Verify a previously constructed checkpoint without rebuilding its graph."""
    root = (root or repository_root()).resolve()
    checkpoint_path = checkpoint_path.resolve()
    corpus = corpus.resolve()
    errors = validate_json_file(checkpoint_path, schema_path(root))
    if errors:
        raise ValueError("invalid funnel checkpoint: " + "; ".join(errors))
    checkpoint = read_object(checkpoint_path)
    inputs = checkpoint["input_identity"]
    recorded_source_root = Path(inputs["source_root"]).resolve()
    if source_root is not None and source_root.resolve() != recorded_source_root:
        raise ValueError("funnel checkpoint source root differs from request")
    corpus_index = corpus / "index.json"
    funnel_path = identity_path(inputs["source_funnel"])
    for label, value, expected_path in (
        ("corpus index", inputs["corpus_index"], corpus_index),
        ("source funnel", inputs["source_funnel"], funnel_path),
    ):
        if (
            identity_path(value) != expected_path
            or not expected_path.is_file()
            or sha256_file(expected_path) != value["sha256"]
        ):
            raise ValueError(f"funnel checkpoint {label} changed")
    funnel = read_object(funnel_path)
    if funnel.get("schema_version") != "community-discovery-funnel-v2":
        raise ValueError("funnel checkpoint source is not v2")
    if funnel["input_identity"]["corpus_index"] != inputs["corpus_index"]:
        raise ValueError("funnel checkpoint corpus binding differs from source")
    if funnel["input_identity"]["audits"] != inputs["audit_prefix"]:
        raise ValueError("funnel checkpoint audit prefix differs from source")
    if (
        len(checkpoint["state"]["unique_candidate_keys"])
        != funnel["inventory"]["unique_discovery_candidates"]
    ):
        raise ValueError("funnel checkpoint unique-candidate count differs from source")

    closure = {
        Path(row["path"]).resolve(): row["sha256"]
        for row in checkpoint["state"]["prefix_identity_closure"]
    }
    required = [inputs["source_funnel"], inputs["corpus_index"], *inputs["audit_prefix"]]
    for value in required:
        path = identity_path(value)
        if closure.get(path) != value["sha256"]:
            raise ValueError("funnel checkpoint closure omits a required identity")
    for path, digest in closure.items():
        if not path.is_file() or sha256_file(path) != digest:
            raise ValueError(f"funnel checkpoint closure identity changed: {path}")

    provenance = checkpoint.get("extension_provenance")
    if provenance is not None:
        predecessor_path = identity_path(provenance["predecessor_checkpoint"])
        if (
            not predecessor_path.is_file()
            or sha256_file(predecessor_path)
            != provenance["predecessor_checkpoint"]["sha256"]
        ):
            raise ValueError("incremental checkpoint predecessor changed")
        predecessor = read_object(predecessor_path)
        prefix_length = len(predecessor["input_identity"]["audit_prefix"])
        if inputs["audit_prefix"][:prefix_length] != predecessor["input_identity"][
            "audit_prefix"
        ]:
            raise ValueError("incremental checkpoint does not extend predecessor")
        if inputs["audit_prefix"][prefix_length:] != provenance["suffix_audits"]:
            raise ValueError("incremental checkpoint suffix provenance differs")
    return {
        "status": "PASS",
        "validation_mode": "HASH_LIST_AND_REQUIRED_MEMBERSHIP",
        "prefix_window_count": len(inputs["audit_prefix"]),
        "unique_discovery_candidates": len(
            checkpoint["state"]["unique_candidate_keys"]
        ),
    }


def extend_funnel(
    checkpoint_path: Path,
    audit_paths: list[Path],
    corpus: Path,
    root: Path | None = None,
    source_root: Path | None = None,
    validation_session: ValidationSession | None = None,
    fast_checkpoint_validation: bool = True,
) -> dict:
    """Extend a validated prefix by revalidating only the unseen audit suffix."""
    root = (root or repository_root()).resolve()
    source_root = (source_root or root).resolve()
    corpus = corpus.resolve()
    checkpoint_path = checkpoint_path.resolve()
    checkpoint_validator = (
        validate_checkpoint_fast if fast_checkpoint_validation else validate_checkpoint
    )
    checkpoint_validator(checkpoint_path, corpus, root, source_root)
    checkpoint = read_object(checkpoint_path)
    source = read_object(identity_path(checkpoint["input_identity"]["source_funnel"]))
    prefix_identities = copy.deepcopy(checkpoint["input_identity"]["audit_prefix"])
    prefix_paths = {identity_path(value) for value in prefix_identities}
    suffix = sorted({path.resolve() for path in audit_paths})
    if not suffix:
        raise ValueError("at least one new audit is required")
    if prefix_paths.intersection(suffix):
        raise ValueError("new audit already exists in checkpoint prefix")

    repositories = _counter(source["repository_receipt_counts"])
    exclusion_reasons = _counter(source["exclusion_reason_counts"])
    screen_statuses = _counter(source["screen_status_counts"])
    screen_reasons = _counter(source["screen_reason_counts"])
    task_families = _counter(source["task_family_counts"])
    selected_items = copy.deepcopy(source["selected_items"])
    unique_candidates = set(checkpoint["state"]["unique_candidate_keys"])
    total_search_matches = int(source["inventory"]["search_match_observations"])
    total_candidate_observations = int(
        source["inventory"]["discovery_candidate_observations"]
    )
    receipt_count = int(source["inventory"]["receipt_count"])

    for audit_path in suffix:
        validate_preselection_chain_audit(
            audit_path,
            corpus,
            source_root,
            validation_session=validation_session,
        )
        audit = read_object(audit_path)
        queue = read_object(identity_path(audit["input_identity"]["queue"]))
        screen = read_object(
            identity_path(audit["input_identity"]["feasibility_screen"])
        )
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
                _candidate_key(receipt["repository"], int(candidate["pr_number"]))
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
        key=lambda row: (row["earliest_public_at"], row["repository"], row["pr_number"])
    )
    post_cutoff_selected = len(selected_items)
    runnable = int(screen_statuses["ELIGIBLE"])
    report = {
        "schema_version": "community-discovery-funnel-v2",
        "generated_at": now(),
        "claim_boundary": "DESCRIPTIVE_DISCOVERY_YIELD_NOT_SELECTION_POLICY",
        "input_identity": {
            "audits": [*prefix_identities, *(identity(path) for path in suffix)],
            "corpus_index": identity(corpus / "index.json"),
        },
        "inventory": {
            "window_count": len(prefix_identities) + len(suffix),
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
        "shadow_recommendations": _shadow_recommendations(selected_items),
        "limitations": copy.deepcopy(source["limitations"]),
    }
    errors = validate_instance(
        report, read_object(root / "schemas/community_discovery_funnel_v2.schema.json")
    )
    if errors:
        raise ValueError("invalid incremental discovery funnel: " + "; ".join(errors))
    return report


def validate_incremental_funnel(
    report_path: Path,
    checkpoint_path: Path,
    corpus: Path,
    source_root: Path | None = None,
    implementation_root: Path | None = None,
    validation_session: ValidationSession | None = None,
    fast_checkpoint_validation: bool = True,
) -> dict:
    implementation_root = (implementation_root or repository_root()).resolve()
    source_root = (source_root or implementation_root).resolve()
    report_path = report_path.resolve()
    observed = read_object(report_path)
    errors = validate_json_file(
        report_path,
        source_root / "schemas/community_discovery_funnel_v2.schema.json",
    )
    if errors:
        raise ValueError("invalid discovery funnel: " + "; ".join(errors))
    checkpoint_validator = (
        validate_checkpoint_fast if fast_checkpoint_validation else validate_checkpoint
    )
    checkpoint_validator(
        checkpoint_path,
        corpus,
        implementation_root,
        source_root,
    )
    checkpoint = read_object(checkpoint_path.resolve())
    prefix = checkpoint["input_identity"]["audit_prefix"]
    observed_audits = observed["input_identity"]["audits"]
    if observed_audits[: len(prefix)] != prefix:
        raise ValueError("discovery funnel does not extend checkpoint prefix")
    suffix = [identity_path(value) for value in observed_audits[len(prefix) :]]
    expected = extend_funnel(
        checkpoint_path,
        suffix,
        corpus,
        implementation_root,
        source_root,
        validation_session,
        fast_checkpoint_validation,
    )
    observed_stable = {
        key: value for key, value in observed.items() if key != "generated_at"
    }
    expected_stable = {
        key: value for key, value in expected.items() if key != "generated_at"
    }
    if observed_stable != expected_stable:
        raise ValueError("incremental discovery funnel is stale or was edited")
    return {
        "status": "PASS",
        "validation_mode": "HASH_BOUND_PREFIX_PLUS_NEW_SUFFIX",
        **observed["inventory"],
        **observed["yield"],
    }


def advance_checkpoint(
    report_path: Path,
    checkpoint_path: Path,
    corpus: Path,
    root: Path | None = None,
    source_root: Path | None = None,
) -> dict:
    """Create the next checkpoint from a proven prefix plus its new audit suffix."""
    root = (root or repository_root()).resolve()
    source_root = (source_root or root).resolve()
    report_path = report_path.resolve()
    checkpoint_path = checkpoint_path.resolve()
    corpus = corpus.resolve()
    validate_incremental_funnel(
        report_path,
        checkpoint_path,
        corpus,
        source_root,
        root,
        fast_checkpoint_validation=True,
    )
    predecessor = read_object(checkpoint_path)
    report = read_object(report_path)
    prefix = predecessor["input_identity"]["audit_prefix"]
    suffix_identities = report["input_identity"]["audits"][len(prefix) :]
    suffix_paths = [identity_path(value) for value in suffix_identities]

    closure = {
        Path(row["path"]).resolve().as_posix(): row["sha256"]
        for row in predecessor["state"]["prefix_identity_closure"]
    }
    old_funnel = identity_path(predecessor["input_identity"]["source_funnel"])
    closure.pop(old_funnel.resolve().as_posix(), None)
    closure[report_path.as_posix()] = sha256_file(report_path)
    closure_session = ValidationSession(source_root, identity_roots=(corpus,))
    closure.update(closure_session.identity_closure(tuple(suffix_paths)))

    unique_candidates = set(predecessor["state"]["unique_candidate_keys"])
    for audit_path in suffix_paths:
        audit = read_object(audit_path)
        queue = read_object(identity_path(audit["input_identity"]["queue"]))
        for receipt_identity in queue["input_identity"]["receipts"]:
            receipt = read_object(identity_path(receipt_identity))
            unique_candidates.update(
                _candidate_key(receipt["repository"], int(candidate["pr_number"]))
                for candidate in receipt["candidates"]
            )
    checkpoint = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now(),
        "claim_boundary": CLAIM_BOUNDARY,
        "input_identity": {
            "source_funnel": identity(report_path),
            "corpus_index": identity(corpus / "index.json"),
            "audit_prefix": copy.deepcopy(report["input_identity"]["audits"]),
            "source_root": source_root.as_posix(),
        },
        "state": {
            "unique_candidate_keys": sorted(unique_candidates),
            "prefix_identity_closure": [
                {"path": path, "sha256": digest}
                for path, digest in sorted(closure.items())
            ],
        },
        "extension_provenance": {
            "predecessor_checkpoint": identity(checkpoint_path),
            "suffix_audits": copy.deepcopy(suffix_identities),
        },
        "limitations": copy.deepcopy(predecessor["limitations"]),
    }
    errors = validate_instance(checkpoint, read_object(schema_path(root)))
    if errors:
        raise ValueError("invalid incremental funnel checkpoint: " + "; ".join(errors))
    if len(unique_candidates) != report["inventory"]["unique_discovery_candidates"]:
        raise ValueError("incremental checkpoint unique-candidate state differs")
    return checkpoint


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    operations = value.add_subparsers(dest="operation", required=True)
    build = operations.add_parser("build")
    build.add_argument("--funnel", type=Path, required=True)
    build.add_argument("--corpus", type=Path, required=True)
    build.add_argument("--source-root", type=Path)
    build.add_argument("--output", type=Path, required=True)
    validate = operations.add_parser("validate")
    validate.add_argument("--checkpoint", type=Path, required=True)
    validate.add_argument("--corpus", type=Path, required=True)
    validate_fast = operations.add_parser("validate-fast")
    validate_fast.add_argument("--checkpoint", type=Path, required=True)
    validate_fast.add_argument("--corpus", type=Path, required=True)
    validate_fast.add_argument("--source-root", type=Path)
    extend = operations.add_parser("extend")
    extend.add_argument("--checkpoint", type=Path, required=True)
    extend.add_argument("--audit", action="append", type=Path, required=True)
    extend.add_argument("--corpus", type=Path, required=True)
    extend.add_argument("--source-root", type=Path)
    extend.add_argument("--output", type=Path, required=True)
    validate_incremental = operations.add_parser("validate-incremental")
    validate_incremental.add_argument("--report", type=Path, required=True)
    validate_incremental.add_argument("--checkpoint", type=Path, required=True)
    validate_incremental.add_argument("--corpus", type=Path, required=True)
    validate_incremental.add_argument("--source-root", type=Path)
    advance = operations.add_parser("advance")
    advance.add_argument("--report", type=Path, required=True)
    advance.add_argument("--checkpoint", type=Path, required=True)
    advance.add_argument("--corpus", type=Path, required=True)
    advance.add_argument("--source-root", type=Path)
    advance.add_argument("--output", type=Path, required=True)
    return value


def main() -> int:
    args = parser().parse_args()
    if args.operation == "build":
        atomic_json(
            args.output,
            build_checkpoint(
                args.funnel,
                args.corpus,
                source_root=args.source_root,
            ),
        )
        print(args.output.resolve())
    elif args.operation == "validate":
        print(validate_checkpoint(args.checkpoint, args.corpus))
    elif args.operation == "validate-fast":
        print(
            validate_checkpoint_fast(
                args.checkpoint,
                args.corpus,
                source_root=args.source_root,
            )
        )
    elif args.operation == "extend":
        atomic_json(
            args.output,
            extend_funnel(
                args.checkpoint,
                args.audit,
                args.corpus,
                source_root=args.source_root,
            ),
        )
        print(args.output.resolve())
    elif args.operation == "validate-incremental":
        print(
            validate_incremental_funnel(
                args.report,
                args.checkpoint,
                args.corpus,
                source_root=args.source_root,
            )
        )
    else:
        atomic_json(
            args.output,
            advance_checkpoint(
                args.report,
                args.checkpoint,
                args.corpus,
                source_root=args.source_root,
            ),
        )
        print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
