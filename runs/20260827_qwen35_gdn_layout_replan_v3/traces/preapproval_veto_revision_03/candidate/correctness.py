#!/usr/bin/env python3
"""Independently close the PASS-only static admission evidence."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from common import dump, experiment_dir, identity, load, sha256


def ptx_coordinate(tid: int, item: int) -> tuple[int, int]:
    warp_id = tid // 32
    lane = tid - 32 * warp_id
    group = lane // 4
    lane4 = lane - 4 * group
    atom = item - 4 * (item // 4)
    return (
        16 * warp_id + group + 8 * (atom // 2),
        8 * (item // 4) + 2 * lane4 + atom % 2,
    )


def independently_check_rows(path: Path) -> dict:
    rows = []
    with path.open() as handle:
        for line_number, line in enumerate(handle, start=1):
            row = json.loads(line)
            row["_line"] = line_number
            rows.append(row)
    if len(rows) != 8192:
        raise RuntimeError(f"expected 8192 oracle rows, observed={len(rows)}")

    domain_counts = Counter((row["tid"], row["tile"], row["slot"]) for row in rows)
    if len(domain_counts) != 8192 or set(domain_counts.values()) != {1}:
        raise RuntimeError("(tid,tile,slot) is not an exact unique domain")
    thread_counts = Counter(row["tid"] for row in rows)
    tile_counts = Counter((row["tid"], row["tile"]) for row in rows)
    if set(thread_counts) != set(range(256)) or set(thread_counts.values()) != {32}:
        raise RuntimeError("each active thread must own exactly 32 records")
    if len(tile_counts) != 1024 or set(tile_counts.values()) != {8}:
        raise RuntimeError("each thread/tile must own exactly eight records")

    coordinates = set()
    owners = set()
    offsets_by_thread_tile = defaultdict(set)
    legacy_owner_coordinate = defaultdict(set)
    for row in rows:
        tid, tile, slot = row["tid"], row["tile"], row["slot"]
        item = row["oracle_o1_item"]
        if item != tile * 8 + slot:
            raise RuntimeError(f"oracle item partition mismatch line={row['_line']}")
        d, n = ptx_coordinate(tid, item)
        sv_d, sv_n = ptx_coordinate(tid, slot)
        if [row["oracle_o1_d"], row["oracle_o1_n"]] != [d, n]:
            raise RuntimeError(f"O1 oracle mismatch line={row['_line']}")
        if [row["oracle_scorev_d"], row["oracle_scorev_n_local"]] != [sv_d, sv_n]:
            raise RuntimeError(f"scoreV oracle mismatch line={row['_line']}")
        if (d, n) != (sv_d, 16 * tile + sv_n):
            raise RuntimeError(f"global coordinate join mismatch line={row['_line']}")
        if row["owner_warp"] != tid // 32 or row["owner_lane"] != tid % 32:
            raise RuntimeError(f"owner decomposition mismatch line={row['_line']}")
        legacy_d, legacy_n = ptx_coordinate(tid % 32, slot)
        if [row["oracle_legacy_d"], row["oracle_legacy_n_local"]] != [legacy_d, legacy_n]:
            raise RuntimeError(f"legacy oracle mismatch line={row['_line']}")
        if row["oracle_legacy_linear"] != legacy_d + 16 * legacy_n:
            raise RuntimeError(f"legacy linear mapping mismatch line={row['_line']}")
        coordinate = (d, n)
        owner = (tid, item)
        if coordinate in coordinates or owner in owners:
            raise RuntimeError(f"coordinate/owner alias line={row['_line']}")
        coordinates.add(coordinate)
        owners.add(owner)
        offsets_by_thread_tile[(tid, tile)].add(item)
        legacy_owner_coordinate[(tid % 32, slot)].add(tid // 32)

    if coordinates != {(d, n) for d in range(128) for n in range(64)}:
        raise RuntimeError("global 128x64 coverage is incomplete")
    for tid in range(256):
        groups = [offsets_by_thread_tile[(tid, tile)] for tile in range(4)]
        if set().union(*groups) != set(range(32)):
            raise RuntimeError(f"thread offset union mismatch tid={tid}")
        if sum(len(group) for group in groups) != len(set().union(*groups)):
            raise RuntimeError(f"thread tile overlap tid={tid}")
    if not all(len(warps) == 8 for warps in legacy_owner_coordinate.values()):
        raise RuntimeError("legacy one-warp owner map did not expose eight-way replication")
    return {
        "rows": len(rows),
        "domain_unique": len(domain_counts),
        "global_coordinates_unique": len(coordinates),
        "owner_item_pairs_unique": len(owners),
        "per_thread_tile_cardinality": 8,
        "per_thread_union_cardinality": 32,
        "legacy_owner_replication_factor": 8,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    experiment = experiment_dir(args.run.resolve())
    manifest = load(experiment / "build/manifest.json")
    audit = load(experiment / "static/instruction_audit.json")
    if manifest.get("predicate_outcome") != "PASS" or manifest.get("binary_pass") != 1:
        raise RuntimeError("PASS-only manifest is unavailable")
    if audit.get("audit_status") != "PASS" or set(audit.get("binary_identities", {})) != {"short", "long"}:
        raise RuntimeError("static audit does not bind exact short/long binaries")

    ast_path = Path(manifest["ast_report_identity"]["path"])
    if sha256(ast_path) != manifest["ast_report_identity"]["sha256"]:
        raise RuntimeError("production/proof AST report identity changed")
    ast_report = load(ast_path)
    triplet = ast_report.get("triplet_check", {})
    hashes = triplet.get("triplet_hashes", {})
    if ast_report.get("status") != "PASS" or set(hashes) != {"short", "long", "proof"}:
        raise RuntimeError("production/proof AST triplet is incomplete")
    if len(set(hashes.values())) != 1:
        raise RuntimeError("production/proof AST triplet is unequal")

    mapping_path = Path(manifest["mapping_report_identity"]["path"])
    mapping = load(mapping_path)
    witness_path = Path(mapping["witness_identity"]["path"])
    if sha256(witness_path) != mapping["witness_identity"]["sha256"]:
        raise RuntimeError("oracle identity changed before correctness")
    recomputed = independently_check_rows(witness_path)

    output = experiment / "correctness/correctness.json"
    checks = [
        "short/long/proof normalized O1 AST chain hashes are identical",
        "real CuTe O1 and scoreV TV layouts compiled against the independent 8192-row PTX oracle",
        "real partition_C coordinate tensors compiled against both TV layouts",
        "real logical_divide/slice_and_offset offsets form one-to-one same-backing joins",
        "four N16 views are pairwise disjoint and cover each 32-item O1 fragment",
        "global owner/coordinate mapping covers 128x64 exactly once",
        "exact attempt-2 one-warp append layout is an unequal negative control",
        "short block512-active256 and long block256-active256 emitted separate static binaries",
    ]
    dump(output, {
        "schema_version": "n2-static-admission-correctness-v3",
        "status": "PASS",
        "predicate_outcome": "PASS",
        "binary_pass": 1,
        "candidate_numerical_correctness": "NOT_TESTED",
        "recomputed_oracle": recomputed,
        "checks": checks,
        "ast_report_identity": identity(ast_path),
        "mapping_report_identity": identity(mapping_path),
        "static_audit_identity": identity(experiment / "static/instruction_audit.json"),
        "failure_semantics": "ANY_FAILURE_IS_INVALID_WITHOUT_N2_DISPOSITION",
    })
    print("PASS: independent static-admission correctness closed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
