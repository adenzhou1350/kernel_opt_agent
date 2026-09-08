#!/usr/bin/env python3
"""Keep direct candidate commands from bypassing global exploration."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import candidate_discovery as discovery
from candidate_discovery import portfolio_admission, portfolio_execution_deficits


def opportunity(identifier: str, rank: int, status: str = "UNIMPLEMENTED") -> dict:
    return {
        "opportunity_id": identifier,
        "priority_rank": rank,
        "status": status,
    }


def candidate(identifier: str, opportunity_id: str, family: str) -> dict:
    return {
        "candidate_id": identifier,
        "opportunity_id": opportunity_id,
        "family": family,
    }


def candidate_spec(identifier: str, opportunity_id: str, family: str) -> dict:
    return {
        "candidate_id": identifier,
        "opportunity_id": opportunity_id,
        "name": identifier,
        "family": family,
        "change_axes": [family],
        "hypothesis": "cover a distinct ranked global opportunity",
        "expected_global_effect": "reduce the frozen end-to-end objective",
        "source_paths": ["candidate.py"],
        "commands": {},
        "smoke_result_path": f"candidates/{identifier}/smoke.json",
        "predicted_global_gain_us": {"lower": 0.1, "upper": 1.0},
        "dependency_contract": {},
        "execution_plan": {"path": f"models/{identifier}-plan.json"},
        "persistent_session_specs": [],
    }


def main() -> None:
    opportunities = {
        "policy": {"min_candidate_opportunities": 3},
        "opportunities": [
            opportunity("lm-head", 1),
            opportunity("fused-moe", 2),
            opportunity("scheduler", 3),
            opportunity("closed-route", 0, "CLOSED"),
        ],
    }
    pool = {
        "policy": {"min_candidates": 3, "min_families": 2},
        "candidates": [],
    }

    first = portfolio_admission(pool, opportunities)
    assert first["required_next_opportunity_id"] == "lm-head"
    assert first["exploration_debt"] == 3
    assert "closed-route" not in first["uncovered_opportunity_ids_by_rank"]

    # One familiar candidate cannot authorize a second variant of the same
    # component while higher-ranked global opportunities remain uncovered.
    pool["candidates"].append(candidate("head-1", "lm-head", "projection"))
    second = portfolio_admission(pool, opportunities)
    assert second["required_next_opportunity_id"] == "fused-moe"
    assert second["exploration_debt"] == 2
    assert portfolio_execution_deficits(pool, opportunities) == {
        "candidate_count": 2,
        "architecture_family_count": 1,
        "opportunity_count": 2,
    }

    pool["candidates"].append(candidate("moe-1", "fused-moe", "tiling"))
    pool["candidates"].append(candidate("scheduler-1", "scheduler", "batching"))
    complete = portfolio_admission(pool, opportunities)
    assert complete["required_next_opportunity_id"] is None
    assert complete["exploration_debt"] == 0
    assert portfolio_execution_deficits(pool, opportunities) == {
        "candidate_count": 0,
        "architecture_family_count": 0,
        "opportunity_count": 0,
    }

    # Exercise the public command boundaries, not only the pure policy helper.
    # All filesystem and schema dependencies are replaced with deterministic
    # fixtures so a failure proves admission behavior rather than setup noise.
    command_opportunities = {
        "status": "READY",
        "policy": {"min_candidate_opportunities": 3},
        "opportunities": [
            {
                **opportunity("lm-head", 1),
                "rewrite_families": ["projection"],
                "optimistic_gain_ceiling_us": 2.0,
                "candidate_ids": [],
            },
            {
                **opportunity("fused-moe", 2),
                "rewrite_families": ["tiling"],
                "optimistic_gain_ceiling_us": 2.0,
                "candidate_ids": [],
            },
            {
                **opportunity("scheduler", 3),
                "rewrite_families": ["batching"],
                "optimistic_gain_ceiling_us": 2.0,
                "candidate_ids": [],
            },
        ],
    }
    command_pool = {
        "status": "ACTIVE",
        "discovery_started_at": None,
        "policy": {
            "min_candidates": 3,
            "max_candidates": 4,
            "min_families": 2,
            "max_technical_attempts_per_candidate": 2,
            "max_candidate_wall_clock_minutes": 5.0,
        },
        "candidates": [],
        "events": [],
    }
    specs = {
        "wrong-first.json": candidate_spec("wrong-first", "fused-moe", "tiling"),
        "head.json": candidate_spec("head", "lm-head", "projection"),
        "repeat.json": candidate_spec("repeat", "lm-head", "projection"),
    }
    with tempfile.TemporaryDirectory() as temporary, patch.multiple(
        discovery,
        load_pool=lambda _run: command_pool,
        read_object=lambda path: specs[path.name],
        validate_spec=lambda _run, _spec: None,
        load_opportunity_map=lambda _run: command_opportunities,
        validate_opportunity_map=lambda *_args, **_kwargs: None,
        validate_execution_plan=lambda *_args, **_kwargs: (
            Path("plan.json"),
            {"estimates": {"selected_seconds": 1.0}},
        ),
        atomic_json=lambda *_args, **_kwargs: None,
    ):
        run = Path(temporary)
        try:
            discovery.command_add(
                SimpleNamespace(run=run, spec=run / "wrong-first.json")
            )
        except ValueError as error:
            assert "must target ranked uncovered opportunity 'lm-head'" in str(error)
        else:
            raise AssertionError("out-of-rank candidate add unexpectedly succeeded")

        discovery.command_add(SimpleNamespace(run=run, spec=run / "head.json"))
        assert command_pool["candidates"][0]["portfolio_admission"][
            "required_next_opportunity_id"
        ] == "lm-head"

        try:
            discovery.command_add(SimpleNamespace(run=run, spec=run / "repeat.json"))
        except ValueError as error:
            assert "must target ranked uncovered opportunity 'fused-moe'" in str(error)
        else:
            raise AssertionError("same-opportunity revisit unexpectedly succeeded")

    with patch.multiple(
        discovery,
        load_pool=lambda _run: command_pool,
        validate_execution_plan=lambda *_args, **_kwargs: (
            Path("plan.json"),
            {"selection": {}, "estimates": {"selected_seconds": 1.0}},
        ),
        persistent_specs=lambda *_args, **_kwargs: [],
        load_opportunity_map=lambda _run: command_opportunities,
        validate_opportunity_map=lambda *_args, **_kwargs: None,
    ):
        try:
            discovery.command_run(SimpleNamespace(run=Path("."), candidate_id="head"))
        except ValueError as error:
            assert "portfolio is not execution-ready" in str(error)
            assert "candidate_count" in str(error)
            assert "opportunity_count" in str(error)
        else:
            raise AssertionError("GPU/build execution gate unexpectedly opened")

    print("candidate portfolio enforcement test: PASS")


if __name__ == "__main__":
    main()
