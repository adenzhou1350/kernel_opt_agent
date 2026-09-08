#!/usr/bin/env python3
"""Validate the first cross-framework policy-evaluation preregistration."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from community_knowledge import sha256_file  # noqa: E402
from schema_utils import validate_instance  # noqa: E402


def test_meta_cycle_preregistration() -> None:
    path = ROOT / "knowledge/community/meta_cycles/cycle-1-theory-first-prior-gate.v1.json"
    cycle = json.loads(path.read_text(encoding="utf-8"))
    schema = json.loads(
        (ROOT / "schemas/community_meta_cycle.schema.json").read_text(encoding="utf-8")
    )
    assert not validate_instance(cycle, schema)
    for key in ("governance_identity", "discovery_preregistration_identity"):
        identity = cycle[key]
        target = ROOT / identity["path"]
        assert target.is_file()
        assert sha256_file(target) == identity["sha256"]
    discovery_path = ROOT / cycle["discovery_preregistration_identity"]["path"]
    discovery = json.loads(discovery_path.read_text(encoding="utf-8"))
    discovery_schema = json.loads(
        (ROOT / "schemas/community_heldout_preregistration.schema.json").read_text(
            encoding="utf-8"
        )
    )
    assert not validate_instance(discovery, discovery_schema)
    assert discovery["cutoff_at"] == cycle["cutoff_at"]
    assert set(discovery["repositories"]) == set(cycle["selection"]["repositories"])
    assert discovery["evaluation"]["repeats"] == cycle["selection"]["repeats"]
    assert cycle["arms"]["champion"]["protocol_arm"] == "CONTROL"
    assert cycle["arms"]["challenger"]["protocol_arm"] == "COMMUNITY_AUGMENTED"


if __name__ == "__main__":
    test_meta_cycle_preregistration()
