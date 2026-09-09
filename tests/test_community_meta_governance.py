#!/usr/bin/env python3
"""Validate the checked-in cross-framework community governance contract."""

from __future__ import annotations

import json
import hashlib
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from schema_utils import validate_instance  # noqa: E402


def test_frozen_meta_governance_v1_contract() -> None:
    policy_path = ROOT / "knowledge/community/meta_governance.v1.json"
    policy = json.loads(
        policy_path.read_text(encoding="utf-8")
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
    assert hashlib.sha256(policy_path.read_bytes()).hexdigest() == (
        "a9d822f569d4423c9f42f9df29cd743d60244c73355c9d3e6353e3bc76851a15"
    )


def test_current_meta_governance_v2_contract() -> None:
    policy = json.loads(
        (ROOT / "knowledge/community/meta_governance.v2.json").read_text(
            encoding="utf-8"
        )
    )
    schema = json.loads(
        (ROOT / "schemas/community_meta_governance_v2.schema.json").read_text(
            encoding="utf-8"
        )
    )
    assert not validate_instance(policy, schema)
    delivery = policy["repository_delivery_policy"]
    assert delivery["fork_sync"]["push_remote"] == "fork"
    assert delivery["fork_sync"]["fetch_before_decision"] is True
    assert (
        delivery["upstream_pull_requests"]["forbids_monolithic_backlog_pr"]
        is True
    )
    assert (
        delivery["upstream_pull_requests"]["forbids_unverified_performance_claims"]
        is True
    )
    continuity = policy["continuity_policy"]
    assert continuity["local_gate_blocks_only_dependent_actions"] is True
    assert continuity["continue_bounded_safe_work"] is True
    assert set(continuity["whole_task_stop_conditions"]) == {
        "FINITE_CYCLE_COMPLETE",
        "USER_PAUSED",
        "STRICT_BLOCKED_AUDIT_SATISFIED",
    }


if __name__ == "__main__":
    test_frozen_meta_governance_v1_contract()
    test_current_meta_governance_v2_contract()
