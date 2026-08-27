#!/usr/bin/env python3
"""Recompute all oracle rows and audit two static proof binaries."""

from __future__ import annotations

import argparse
import json
import subprocess
from collections import defaultdict
from pathlib import Path

from common import (
    dump,
    experiment_dir,
    identity,
    load,
    sha256,
    verify_cutlass_layout_sources,
    verify_production_sources,
)


D, BT = 128, 64


def expected_coordinate(tid: int, item: int) -> tuple[int, int]:
    warp_id, lane = divmod(tid, 32)
    lane_group, lane_in_group = divmod(lane, 4)
    atom_item = item % 4
    return (
        16 * warp_id + lane_group + 8 * (atom_item // 2),
        8 * (item // 4) + 2 * lane_in_group + atom_item % 2,
    )


def audit_oracle(path: Path) -> dict:
    domain = set()
    coordinates = set()
    owner_items = set()
    per_thread = defaultdict(set)
    per_thread_tile = defaultdict(set)
    count = 0
    with path.open() as handle:
        for line_number, line in enumerate(handle, start=1):
            row = json.loads(line)
            tid, tile, slot = int(row["tid"]), int(row["tile"]), int(row["slot"])
            if not (0 <= tid < 256 and 0 <= tile < 4 and 0 <= slot < 8):
                raise RuntimeError(f"oracle domain violation at line {line_number}")
            key = (tid, tile, slot)
            if key in domain:
                raise RuntimeError(f"duplicate oracle domain row: {key}")
            domain.add(key)
            item = int(row["oracle_o1_item"])
            d, n = expected_coordinate(tid, item)
            sv_d, sv_n = expected_coordinate(tid, slot)
            expected_fields = {
                "owner_warp": tid // 32,
                "owner_lane": tid % 32,
                "oracle_o1_item": tile * 8 + slot,
                "oracle_o1_d": d,
                "oracle_o1_n": n,
                "oracle_o1_linear": d + D * n,
                "oracle_scorev_d": sv_d,
                "oracle_scorev_n_local": sv_n,
                "oracle_scorev_linear": sv_d + D * sv_n,
            }
            legacy_d, legacy_n = expected_coordinate(tid % 32, slot)
            expected_fields.update({
                "oracle_legacy_d": legacy_d,
                "oracle_legacy_n_local": legacy_n,
                "oracle_legacy_linear": legacy_d + 16 * legacy_n,
            })
            for field, expected in expected_fields.items():
                if row.get(field) != expected:
                    raise RuntimeError(
                        f"oracle field mismatch line={line_number} field={field} "
                        f"expected={expected} observed={row.get(field)}"
                    )
            if (d, n) != (sv_d, tile * 16 + sv_n):
                raise RuntimeError(f"O1/scoreV coordinate mismatch at line {line_number}")
            coordinate = (d, n)
            owner_item = (tid, item)
            if coordinate in coordinates or owner_item in owner_items:
                raise RuntimeError(f"oracle alias at line {line_number}")
            coordinates.add(coordinate)
            owner_items.add(owner_item)
            per_thread[tid].add(item)
            per_thread_tile[(tid, tile)].add(item)
            count += 1
    expected_domain = {(tid, tile, slot) for tid in range(256) for tile in range(4) for slot in range(8)}
    expected_coordinates = {(d, n) for d in range(D) for n in range(BT)}
    if domain != expected_domain or coordinates != expected_coordinates or count != D * BT:
        raise RuntimeError("oracle full-domain/full-coordinate coverage failed")
    if any(per_thread[tid] != set(range(32)) for tid in range(256)):
        raise RuntimeError("per-thread O1 item union failed")
    for tid in range(256):
        tile_sets = [per_thread_tile[(tid, tile)] for tile in range(4)]
        if any(len(values) != 8 for values in tile_sets):
            raise RuntimeError(f"tile cardinality failed for tid={tid}")
        if any(tile_sets[left] & tile_sets[right] for left in range(4) for right in range(left + 1, 4)):
            raise RuntimeError(f"tile disjointness failed for tid={tid}")
    return {
        "row_count": count,
        "unique_domain_rows": len(domain),
        "unique_global_coordinates": len(coordinates),
        "unique_owner_item_pairs": len(owner_items),
        "full_per_thread_union": True,
        "pairwise_disjoint_tiles": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    experiment = experiment_dir(args.run.resolve())
    manifest_path = experiment / "build/manifest.json"
    manifest = load(manifest_path)
    if manifest.get("status") != "PASS" or manifest.get("predicate_outcome") != "PASS":
        raise RuntimeError("PASS-only build manifest is unavailable")
    if manifest.get("binary_pass") != 1 or manifest.get("cuda_kernel_launches") != 0:
        raise RuntimeError("manifest violates PASS-only/zero-launch contract")
    if manifest.get("production_sources") != verify_production_sources():
        raise RuntimeError("production identity changed after clean build")
    if manifest.get("cutlass_layout_sources") != verify_cutlass_layout_sources():
        raise RuntimeError("CUTLASS layout implementation changed after clean build")

    mapping_path = Path(manifest["mapping_report_identity"]["path"])
    if sha256(mapping_path) != manifest["mapping_report_identity"]["sha256"]:
        raise RuntimeError("mapping report identity changed")
    mapping = load(mapping_path)
    witness_path = Path(mapping["witness_identity"]["path"])
    if sha256(witness_path) != mapping["witness_identity"]["sha256"]:
        raise RuntimeError("oracle witness identity changed")
    oracle_audit = audit_oracle(witness_path)

    artifact_names = set(manifest.get("artifacts", {}))
    if artifact_names != {"short", "long"}:
        raise RuntimeError(f"expected exact short/long proof artifacts, observed={artifact_names}")
    sass_identities = {}
    binary_identities = {}
    for name in ("short", "long"):
        cubin_identity = manifest["artifacts"][name]["cubin"]
        cubin = Path(cubin_identity["path"])
        if sha256(cubin) != cubin_identity["sha256"]:
            raise RuntimeError(f"cubin identity changed: {name}")
        completed = subprocess.run(
            ["/usr/local/cuda/bin/cuobjdump", "--dump-sass", str(cubin)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if completed.returncode:
            raise RuntimeError(f"cuobjdump failure: {completed.stdout}{completed.stderr}")
        sass_path = experiment / f"static/{name}.sass"
        sass_path.write_text(completed.stdout)
        sass_identities[name] = identity(sass_path)
        binary_identities[name] = cubin_identity

    audit_path = experiment / "static/instruction_audit.json"
    dump(audit_path, {
        "schema_version": "n2-static-layout-audit-v3",
        "status": "PASS",
        "audit_status": "PASS",
        "predicate_outcome": "PASS",
        "binary_pass": 1,
        "build_manifest_identity": identity(manifest_path),
        "mapping_report_identity": identity(mapping_path),
        "witness_identity": identity(witness_path),
        "oracle_recomputation": oracle_audit,
        "binary_identities": binary_identities,
        "sass_identities": sass_identities,
        "compiled_callable_invocations": 0,
        "cuda_kernel_launches": 0,
        "gpu_performance_samples": 0,
        "claims_allowed": ["static logical same-backing/type admission"],
        "claims_forbidden": [
            "candidate rejection", "latency", "speedup", "numerical correctness",
            "K-loop order", "physical registers", "production SASS/resources",
            "production acceptance",
        ],
    })
    print(f"PASS: recomputed {oracle_audit['row_count']} rows; static binaries=2")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
