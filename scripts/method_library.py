#!/usr/bin/env python3
"""Match evidence cards to run-local opportunities without treating literature as proof."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from schema_utils import validate_instance, validate_json_file


SCHEMA = "optimization-method-v1"
RECEIPT_SCHEMA = "method-match-receipt-v1"
SNAPSHOT_SCHEMA = "optimization-method-snapshot-v1"
INPUT_PATHS = ("operator.json", "workload.json", "hardware.json", "models/opportunity_map.json")
EVIDENCE_WEIGHTS = {"PEER_REVIEWED_PRIMARY": 3.0, "VENDOR_OFFICIAL_GUIDANCE": 2.5, "PROJECT_OFFICIAL_GUIDANCE": 2.5, "PRIMARY_PREPRINT": 2.0, "INTERNAL_REPRODUCTION": 2.0}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_object(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def card_paths(root: Path | None = None) -> list[Path]:
    knowledge = (root or repository_root()) / "knowledge"
    return sorted(
        [
            *knowledge.joinpath("methods").glob("*.json"),
            *knowledge.joinpath("primitives").glob("*.json"),
            *knowledge.joinpath("method_revisions").glob("*.json"),
        ],
        key=lambda path: path.as_posix(),
    )


def load_card_revisions(root: Path | None = None) -> list[tuple[Path, dict]]:
    root = root or repository_root()
    schema = root / "schemas" / "optimization_method.schema.json"
    revisions: list[tuple[Path, dict]] = []
    identities: set[tuple[str, int]] = set()
    for path in card_paths(root):
        errors = validate_json_file(path, schema)
        if errors:
            raise ValueError(f"invalid method card {path.name}: {'; '.join(errors)}")
        card = read_object(path)
        if card.get("schema_version") != SCHEMA:
            raise ValueError(f"unsupported method card schema: {path}")
        identifier = str(card["method_id"])
        revision = int(card.get("revision", 1))
        identity = (identifier, revision)
        if identity in identities:
            raise ValueError(f"duplicate method revision: {identifier}@{revision}")
        identities.add(identity)
        revisions.append((path, card))
    if not revisions:
        raise ValueError("method library is empty")

    by_method: dict[str, list[tuple[Path, dict]]] = {}
    for path, card in revisions:
        by_method.setdefault(card["method_id"], []).append((path, card))
    root_resolved = root.resolve()
    for identifier, rows in by_method.items():
        rows.sort(key=lambda row: int(row[1].get("revision", 1)))
        observed = [int(card.get("revision", 1)) for _, card in rows]
        if observed != list(range(1, len(rows) + 1)):
            raise ValueError(f"method revision chain is not contiguous: {identifier}")
        for index, (path, card) in enumerate(rows):
            revision = int(card.get("revision", 1))
            supersedes = card.get("supersedes")
            if revision == 1:
                if supersedes is not None:
                    raise ValueError(f"method revision 1 cannot supersede another card: {identifier}")
                continue
            if supersedes is None or supersedes["revision"] != revision - 1:
                raise ValueError(f"method revision does not name its predecessor: {identifier}@{revision}")
            previous_path, previous_card = rows[index - 1]
            declared_path = (root / supersedes["path"]).resolve()
            try:
                declared_path.relative_to(root_resolved)
            except ValueError as error:
                raise ValueError("method predecessor escapes repository root") from error
            if declared_path != previous_path.resolve():
                raise ValueError(f"method predecessor path mismatch: {identifier}@{revision}")
            if supersedes["sha256"] != sha256(previous_path):
                raise ValueError(f"method predecessor hash mismatch: {identifier}@{revision}")
            if previous_card["method_id"] != identifier:
                raise ValueError(f"method predecessor id mismatch: {identifier}@{revision}")
            previous_available = parse_timestamp(
                previous_card["source"]["available_at"],
                f"{identifier}@{revision - 1}.source.available_at",
            )
            current_available = parse_timestamp(
                card["source"]["available_at"],
                f"{identifier}@{revision}.source.available_at",
            )
            if current_available <= previous_available:
                raise ValueError(
                    f"method revision availability must increase: {identifier}@{revision}"
                )
    return sorted(
        revisions,
        key=lambda row: (row[1]["method_id"], int(row[1].get("revision", 1))),
    )


def load_cards(root: Path | None = None) -> list[tuple[Path, dict]]:
    revisions = load_card_revisions(root)
    current: dict[str, tuple[Path, dict]] = {}
    for path, card in revisions:
        identifier = card["method_id"]
        if (
            identifier not in current
            or int(card.get("revision", 1))
            > int(current[identifier][1].get("revision", 1))
        ):
            current[identifier] = (path, card)
    return sorted(current.values(), key=lambda row: row[1]["method_id"])


def identities(run: Path) -> list[dict]:
    result = []
    for relative in INPUT_PATHS:
        path = run / relative
        if not path.is_file():
            raise FileNotFoundError(f"method matching requires {relative}")
        result.append({"path": relative, "sha256": sha256(path)})
    return result


def library_identity(cards: list[tuple[Path, dict]], root: Path) -> dict:
    entries = [{"path": path.relative_to(root).as_posix(), "sha256": sha256(path)} for path, _ in cards]
    encoded = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
    return {"sha256": hashlib.sha256(encoded).hexdigest(), "cards": entries}


def flattened(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=True).lower()


def scalar_text(value: object) -> str:
    if isinstance(value, dict):
        return " ".join(scalar_text(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(scalar_text(item) for item in value)
    return str(value).lower()


def contains_term(text: str, term: str) -> bool:
    pattern = rf"(?<![a-z0-9]){re.escape(term.lower())}(?![a-z0-9])"
    return re.search(pattern, text) is not None


def match_card(card: dict, opportunity: dict, context: str, hardware_text: str) -> dict | None:
    applicability = card["applicability"]
    vendor = str(read_vendor(hardware_text)).lower()
    allowed_vendors = {str(item).lower() for item in applicability["vendors"]}
    family_hits = sorted(set(card["opportunity_families"]) & set(opportunity["rewrite_families"]))
    opportunity_text = scalar_text(opportunity)
    opportunity_signature_hits = sorted(term for term in applicability["problem_signatures"] if contains_term(opportunity_text, term))
    context_signature_hits = sorted(term for term in applicability["problem_signatures"] if contains_term(context, term))
    if card["kind"] == "EVALUATION_GUARD":
        if not family_hits and not context_signature_hits:
            return None
    elif not family_hits and not opportunity_signature_hits:
        return None

    missing = sorted(term for term in applicability["required_capabilities"] if term.lower() not in hardware_text)
    affinities = applicability["architecture_affinity"]
    affinity_hits = sorted(term for term in affinities if term.lower() in hardware_text)
    vendor_ok = "any" in allowed_vendors or vendor in allowed_vendors
    if not vendor_ok:
        status = "INCOMPATIBLE"
    elif missing:
        status = "BLOCKED_UNVERIFIED_CAPABILITY"
    elif affinities and not affinity_hits:
        status = "ADAPTATION_REQUIRED"
    else:
        status = "DIRECT"

    score = (
        12.0 * len(family_hits)
        + 3.0 * len(opportunity_signature_hits)
        + min(2.0, float(len(context_signature_hits)))
        + EVIDENCE_WEIGHTS[card["source"]["evidence_tier"]]
        - 4.0 * len(missing)
        - (2.0 if status == "ADAPTATION_REQUIRED" else 0.0)
        - (100.0 if status == "INCOMPATIBLE" else 0.0)
    )
    return {
        "method_id": card["method_id"],
        "title": card["title"],
        "kind": card["kind"],
        "transfer_status": status,
        "score": score,
        "family_hits": family_hits,
        "opportunity_signature_hits": opportunity_signature_hits,
        "context_signature_hits": context_signature_hits,
        "architecture_affinity_hits": affinity_hits,
        "missing_required_capabilities": missing,
        "candidate_archetypes": card["candidate_archetypes"] if status in {"DIRECT", "ADAPTATION_REQUIRED"} else [],
        "implementation_recipe": card["implementation_recipe"],
        "validation_recipe": card["validation_recipe"],
        "expected_bottleneck_shifts": card["expected_bottleneck_shifts"],
        "failure_modes": card["failure_modes"],
        "algorithmic_decomposition": card.get("algorithmic_decomposition"),
        "claim_boundary": "DISCOVERY_PRIOR_ONLY",
        "source": card["source"],
    }


def parse_timestamp(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{label} must be an ISO-8601 timestamp") from error
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must include a timezone")
    return parsed


def build_snapshot(cutoff_at: str, root: Path | None = None) -> dict:
    root = root or repository_root()
    cutoff = parse_timestamp(cutoff_at, "cutoff_at")
    revisions = load_card_revisions(root)
    by_method: dict[str, list[dict]] = {}
    for _, card in revisions:
        by_method.setdefault(card["method_id"], []).append(card)
    included = []
    excluded = []
    for identifier, cards in sorted(by_method.items()):
        eligible = [
            card
            for card in cards
            if parse_timestamp(
                card["source"]["available_at"],
                f"{identifier}.source.available_at",
            )
            <= cutoff
        ]
        if eligible:
            included.append(
                max(eligible, key=lambda card: int(card.get("revision", 1)))
            )
        else:
            excluded.append(identifier)
    if not included:
        raise ValueError("method snapshot contains no cards available by the cutoff")
    included_revisions = {
        (card["method_id"], int(card.get("revision", 1))) for card in included
    }
    visible_revision_files = [
        (path, card)
        for path, card in revisions
        if (card["method_id"], int(card.get("revision", 1)))
        in included_revisions
    ]
    snapshot = {
        "schema_version": SNAPSHOT_SCHEMA,
        "generated_at": now(),
        "cutoff_at": cutoff_at,
        "claim_boundary": "DISCOVERY_PRIOR_ONLY",
        "library_identity": library_identity(visible_revision_files, root),
        "included_method_ids": sorted(card["method_id"] for card in included),
        # Kept empty for v1 schema compatibility. Naming future methods here
        # leaks their solution vocabulary into historical executor inputs.
        "excluded_method_ids": [],
        "excluded_method_count": len(excluded),
        "withheld_revision_count": len(revisions) - len(included),
        "cards": sorted(included, key=lambda card: card["method_id"]),
    }
    errors = validate_instance(
        snapshot,
        read_object(root / "schemas" / "optimization_method_snapshot.schema.json"),
    )
    if errors:
        raise ValueError("invalid method snapshot: " + "; ".join(errors))
    return snapshot


def read_vendor(hardware_text: str) -> str:
    match = re.search(r'"vendor"\s*:\s*"([^"]+)"', hardware_text)
    return match.group(1) if match else "unknown"


def build_receipt(run: Path, root: Path | None = None, limit: int = 3) -> dict:
    root = root or repository_root()
    cards = load_cards(root)
    revisions = load_card_revisions(root)
    operator = read_object(run / "operator.json")
    workload = read_object(run / "workload.json")
    hardware = read_object(run / "hardware.json")
    opportunity_map = read_object(run / "models" / "opportunity_map.json")
    if opportunity_map.get("schema_version") != "opportunity-map-v1" or opportunity_map.get("status") != "READY":
        raise ValueError("method matching requires a READY opportunity-map-v1")
    context = scalar_text({"operator": operator, "workload": workload, "hardware": hardware})
    hardware_text = flattened(hardware)
    recommendations = []
    guards: dict[str, dict] = {}
    for opportunity in opportunity_map["opportunities"]:
        if opportunity.get("status") == "CLOSED":
            continue
        rows = []
        for _, card in cards:
            match = match_card(card, opportunity, context, hardware_text)
            if match is None:
                continue
            if card["kind"] == "EVALUATION_GUARD":
                guards[card["method_id"]] = match
            elif match["transfer_status"] != "INCOMPATIBLE":
                rows.append(match)
        rows.sort(key=lambda row: (-float(row["score"]), row["method_id"]))
        recommendations.append({
            "opportunity_id": opportunity["opportunity_id"],
            "opportunity_priority_rank": opportunity["priority_rank"],
            "matches": rows[:limit],
        })
    recommendations.sort(key=lambda row: (int(row["opportunity_priority_rank"]), row["opportunity_id"]))
    receipt = {
        "schema_version": RECEIPT_SCHEMA,
        "generated_at": now(),
        "claim_scope": "DISCOVERY_PRIOR_ONLY",
        "input_identities": identities(run),
        "library_identity": library_identity(revisions, root),
        "policy": {
            "max_matches_per_opportunity": limit,
            "hardware_requirement_policy": "FAIL_CLOSED",
            "literature_claim_policy": "HYPOTHESIS_NOT_PERFORMANCE_EVIDENCE",
            "score_formula": "12*family_hits + 3*opportunity_signature_hits + min(2,context_signature_hits) + evidence_weight - 4*missing_capabilities - 2*adaptation - 100*incompatible",
        },
        "recommendations": recommendations,
        "evaluation_guards": sorted(guards.values(), key=lambda row: row["method_id"]),
    }
    return receipt


def validate_receipt(receipt: dict, run: Path, root: Path | None = None) -> None:
    root = root or repository_root()
    schema = read_object(root / "schemas" / "method_match_receipt.schema.json")
    schema_errors = validate_instance(receipt, schema)
    if schema_errors:
        raise ValueError("invalid method-match receipt: " + "; ".join(schema_errors))
    if receipt.get("schema_version") != RECEIPT_SCHEMA or receipt.get("claim_scope") != "DISCOVERY_PRIOR_ONLY":
        raise ValueError("unsupported method-match receipt")
    if receipt.get("input_identities") != identities(run):
        raise ValueError("method-match inputs are stale")
    if receipt.get("library_identity") != library_identity(
        load_card_revisions(root), root
    ):
        raise ValueError("method library changed after matching")
    if receipt.get("policy", {}).get("hardware_requirement_policy") != "FAIL_CLOSED":
        raise ValueError("method matching must fail closed on unverified capabilities")
    limit = int(receipt.get("policy", {}).get("max_matches_per_opportunity", 0))
    expected = build_receipt(run, root, limit=limit)
    observed_stable = {key: value for key, value in receipt.items() if key != "generated_at"}
    expected_stable = {key: value for key, value in expected.items() if key != "generated_at"}
    if observed_stable != expected_stable:
        raise ValueError("method-match recommendations are stale or were edited without recomputation")


def command_validate(args: argparse.Namespace) -> dict:
    root = repository_root()
    cards = load_cards(root)
    revisions = load_card_revisions(root)
    return {
        "status": "PASS",
        "card_count": len(cards),
        "revision_count": len(revisions),
        "library_identity": library_identity(revisions, root),
    }


def command_recommend(args: argparse.Namespace) -> dict:
    run = args.run.resolve()
    receipt = build_receipt(run, limit=args.limit)
    validate_receipt(receipt, run)
    atomic_json(run / "models" / "method_matches.json", receipt)
    return receipt


def command_snapshot(args: argparse.Namespace) -> dict:
    snapshot = build_snapshot(args.cutoff_at)
    atomic_json(args.output.resolve(), snapshot)
    return snapshot


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="operation", required=True)
    subparsers.add_parser("validate", help="validate every reusable method card")
    recommend = subparsers.add_parser("recommend", help="match method cards to a READY run opportunity map")
    recommend.add_argument("--run", type=Path, required=True)
    recommend.add_argument("--limit", type=int, default=3, choices=range(1, 9))
    snapshot = subparsers.add_parser("export-snapshot", help="export only method cards available by a temporal cutoff")
    snapshot.add_argument("--cutoff-at", required=True)
    snapshot.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.operation == "validate":
            result = command_validate(args)
        elif args.operation == "recommend":
            result = command_recommend(args)
        else:
            result = command_snapshot(args)
    except Exception as error:
        print(f"ERROR: {error}", file=__import__("sys").stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
