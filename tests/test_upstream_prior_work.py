#!/usr/bin/env python3
"""Exercise fail-closed routing for historical and overlapping upstream PRs."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/upstream_prior_work.py"


def prior(
    number: int,
    *,
    state: str = "CLOSED",
    relationship: str = "EXACT_PREDECESSOR",
    closure: str = "INACTIVITY_AUTOMATION",
) -> dict:
    return {
        "number": number,
        "url": f"https://github.com/sgl-project/sglang/pull/{number}",
        "author": "Aphoh",
        "state": state,
        "draft": False,
        "head_commit": "3" * 40,
        "relationship": relationship,
        "closure_class": closure,
        "closure_evidence_url": (
            f"https://github.com/sgl-project/sglang/pull/{number}#issuecomment-1"
            if state == "CLOSED"
            else None
        ),
        "core_change_signature": "batch top-logprob token ids across positions",
        "changed_paths": ["python/sglang/srt/managers/tokenizer_manager.py"],
        "material_delta": ["guard top_k greater than 20"],
    }


def base() -> dict:
    return {
        "schema_version": "upstream-prior-work-v1",
        "observed_at": "2026-09-12T23:17:07+08:00",
        "repository": "sgl-project/sglang",
        "queries": [
            "https://github.com/sgl-project/sglang/pulls?q=detokenize_top_logprobs_tokens"
        ],
        "candidate": {
            "candidate_id": "sglang-batched-top-logprob",
            "branch": "perf/batch-top-logprob",
            "commit": "e" * 40,
            "core_change_signature": "batch top-logprob token ids across positions",
            "changed_paths": ["python/sglang/srt/managers/tokenizer_manager.py"],
            "attributed_pr_numbers": [],
            "coordination_status": "NONE",
        },
        "matches": [],
    }


def run(record: dict, expected_code: int = 0) -> dict:
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "input.json"
        path.write_text(json.dumps(record), encoding="utf-8")
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), str(path)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    assert completed.returncode == expected_code, (completed.stdout, completed.stderr)
    return json.loads(completed.stdout)


def decision(record: dict) -> dict:
    return run(record)["decision"]


def main() -> None:
    assert decision(base())["recommended_action"] == "PROCEED_NO_PRIOR_MATCH"

    inactive = base()
    inactive["matches"] = [prior(24447)]
    routed = decision(inactive)
    assert routed["recommended_action"] == "PREPARE_ATTRIBUTED_REVIVAL"
    assert routed["implementation_allowed"] is True
    assert routed["draft_publication_allowed"] is False

    inactive["candidate"]["attributed_pr_numbers"] = [24447]
    inactive["candidate"]["coordination_status"] = "POSTED"
    routed = decision(inactive)
    assert (
        routed["recommended_action"] == "REVIVE_INACTIVE_PREDECESSOR_WITH_ATTRIBUTION"
    )
    assert routed["draft_publication_allowed"] is True

    opened = base()
    opened["matches"] = [prior(8366, state="OPEN", closure="NOT_CLOSED")]
    opened["matches"][0]["url"] = "https://github.com/sgl-project/sglang/pull/8366"
    routed = decision(opened)
    assert routed["recommended_action"] == "CONTRIBUTE_TO_EXISTING_OPEN_PR"
    assert routed["implementation_allowed"] is False

    merged = base()
    merged["matches"] = [prior(100, state="MERGED", closure="MERGED")]
    assert decision(merged)["recommended_action"] == "STOP_ALREADY_MERGED"

    rejected = base()
    rejected["matches"] = [prior(101, closure="TECHNICAL_REJECTION")]
    assert (
        decision(rejected)["recommended_action"] == "REQUIRE_REJECTION_RESPONSIVE_DELTA"
    )

    unknown = base()
    unknown["matches"] = [prior(102, closure="UNKNOWN")]
    assert (
        decision(unknown)["recommended_action"]
        == "REVIEW_UNKNOWN_CLOSURE_BEFORE_IMPLEMENTATION"
    )

    overlap = base()
    overlap["matches"] = [
        prior(103, state="OPEN", relationship="FEATURE_OVERLAP", closure="NOT_CLOSED")
    ]
    assert (
        decision(overlap)["recommended_action"]
        == "COORDINATE_OR_PROVE_MATERIAL_DIFFERENCE"
    )

    adjacent = base()
    adjacent["matches"] = [prior(104, relationship="ADJACENT")]
    assert (
        decision(adjacent)["recommended_action"] == "PROCEED_WITH_PRIOR_WORK_DISCLOSURE"
    )

    invalid = base()
    invalid["matches"] = [prior(24447), prior(24447)]
    result = run(invalid, expected_code=1)
    assert any("duplicate PR number" in error for error in result["errors"])

    invalid = base()
    invalid["matches"] = [prior(24447, state="OPEN", closure="INACTIVITY_AUTOMATION")]
    result = run(invalid, expected_code=1)
    assert any(
        "state and closure_class disagree" in error for error in result["errors"]
    )

    invalid = base()
    invalid["candidate"]["attributed_pr_numbers"] = [999]
    result = run(invalid, expected_code=1)
    assert any("unobserved PRs" in error for error in result["errors"])

    invalid = base()
    invalid["matches"] = [prior(24447)]
    invalid["matches"][0]["url"] = "https://github.com/other/repo/pull/24447"
    result = run(invalid, expected_code=1)
    assert any("must match repository" in error for error in result["errors"])

    invalid = base()
    invalid["queries"] = ["https://github.com/other/repo/pulls?q=same"]
    result = run(invalid, expected_code=1)
    assert any("declared GitHub repository" in error for error in result["errors"])

    invalid = base()
    invalid["matches"] = [prior(24447)]
    invalid["matches"][0]["core_change_signature"] = "different mechanism"
    result = run(invalid, expected_code=1)
    assert any("match candidate core signature" in error for error in result["errors"])
    print("upstream prior-work test: PASS")


if __name__ == "__main__":
    main()
