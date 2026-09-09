#!/usr/bin/env python3
"""Validate the current autonomous optimization-lane topology."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from community_knowledge import read_object, sha256_file
from schema_utils import validate_instance


SCHEMA_VERSION = "community-lane-topology-v3"
LANE_IDS = {
    "VLLM_OPTIMIZATION",
    "VLLM_A800_ADAPTATION",
    "MOONCAKE_OPTIMIZATION",
    "SGLANG_OPTIMIZATION",
}


def root() -> Path:
    return Path(__file__).resolve().parents[1]


def validate_topology(path: Path) -> dict:
    path = path.resolve()
    topology = read_object(path)
    errors = validate_instance(
        topology, read_object(root() / "schemas/community_lane_topology.schema.json")
    )
    if errors:
        raise ValueError("invalid community lane topology: " + "; ".join(errors))
    if topology["schema_version"] != SCHEMA_VERSION:
        raise ValueError("unsupported community lane topology")

    supersedes = topology["supersedes"]
    expected_path = root() / "knowledge/community/meta_governance.v2.json"
    declared_path = Path(supersedes["path"])
    if declared_path.is_absolute() or ".." in declared_path.parts:
        raise ValueError("superseded governance path must be repository-relative")
    if (root() / declared_path).resolve() != expected_path.resolve():
        raise ValueError("lane topology must supersede meta_governance.v2.json")
    if sha256_file(expected_path) != supersedes["sha256"]:
        raise ValueError("superseded governance identity changed")

    lane_ids = [lane["lane_id"] for lane in topology["execution_lanes"]]
    if len(lane_ids) != len(set(lane_ids)):
        raise ValueError("duplicate execution lane")
    if set(lane_ids) != LANE_IDS:
        raise ValueError("execution lane set does not match the four autonomous lanes")
    if "STRATEGY_EVALUATION" in lane_ids:
        raise ValueError("strategy evaluation belongs to the control plane")

    return {
        "status": "PASS",
        "schema_version": SCHEMA_VERSION,
        "topology_sha256": sha256_file(path),
        "lane_ids": lane_ids,
        "control_plane_role": topology["control_plane"]["role"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--topology",
        type=Path,
        default=root() / "knowledge/community/lane_topology.v3.json",
    )
    args = parser.parse_args()
    print(json.dumps(validate_topology(args.topology), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
