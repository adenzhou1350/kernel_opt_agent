#!/usr/bin/env python3
"""Validate the checked-in cross-framework community governance contract."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from schema_utils import validate_instance  # noqa: E402


def test_meta_governance_contract() -> None:
    policy = json.loads(
        (ROOT / "knowledge/community/meta_governance.v1.json").read_text(
            encoding="utf-8"
        )
    )
    schema = json.loads(
        (ROOT / "schemas/community_meta_governance.schema.json").read_text(
            encoding="utf-8"
        )
    )
    assert not validate_instance(policy, schema)
    assert policy["roles"]["control_plane"]["single_writer"] is True
    assert set(policy["roles"]["execution_lanes"]) == {
        "VLLM",
        "MOONCAKE",
        "SGLANG",
        "STRATEGY_EVALUATION",
    }
    assert policy["promotion_policy"]["minimum_frameworks"] == 2
    assert policy["promotion_policy"]["requires_unseen_candidates"] is True


if __name__ == "__main__":
    test_meta_governance_contract()
