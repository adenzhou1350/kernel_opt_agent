#!/usr/bin/env python3
"""Prospective two-framework check for local-rank-first typed routing."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from community_knowledge import community_routing_signal


def metrics(cases: list[dict], *, typed: bool) -> dict:
    true_positive = 0
    false_positive = 0
    selected_case_ids = []
    for case in sorted(cases, key=lambda row: row["opportunity"]["priority_rank"]):
        opportunity = dict(case["opportunity"])
        if not typed:
            opportunity.pop("primary_transformation_axes")
        selected = []
        for candidate in case["community_candidates"]:
            signal = community_routing_signal(candidate["node"], opportunity)
            if signal["eligible"]:
                selected.append(candidate)
        if selected:
            selected_case_ids.append(case["case_id"])
        true_positive += sum(row["relevant"] for row in selected)
        false_positive += sum(not row["relevant"] for row in selected)
    precision = true_positive / (true_positive + false_positive)
    return {
        "true_positive": true_positive,
        "false_positive": false_positive,
        "precision": precision,
        "selected_case_ids": selected_case_ids,
    }


def main() -> None:
    fixture = json.loads(
        (ROOT / "tests/fixtures/primary_axis_routing_cases.json").read_text(
            encoding="utf-8"
        )
    )
    assert fixture["frozen_before_routing"] is True
    cases = fixture["cases"]
    assert [row["source"]["repository"] for row in cases] == [
        "vllm-project/vllm",
        "sgl-project/sglang",
    ]
    assert all(len(row["source"]["commit"]) == 40 for row in cases)
    assert all(len(row["source"]["git_blob"]) == 40 for row in cases)

    control = metrics(cases, typed=False)
    challenger = metrics(cases, typed=True)
    expected_order = [row["case_id"] for row in cases]
    assert control["selected_case_ids"] == expected_order
    assert challenger["selected_case_ids"] == expected_order
    assert control == {
        "true_positive": 2,
        "false_positive": 2,
        "precision": 0.5,
        "selected_case_ids": expected_order,
    }
    assert challenger == {
        "true_positive": 2,
        "false_positive": 0,
        "precision": 1.0,
        "selected_case_ids": expected_order,
    }
    print("primary axis routing prospective test: PASS")


if __name__ == "__main__":
    main()
