#!/usr/bin/env python3
"""Exercise temporal isolation and fixed-budget community A/B scoring."""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from community_evaluation import (
    assess_trial,
    compare_trials,
    materialize_trial,
    validate_suite,
)
from community_knowledge import (
    atomic_json,
    build_graph,
    capture_pr,
    sha256_file,
)
from test_community_knowledge import FakeGitHubClient, event_for


def identity(path: Path, base: Path) -> dict:
    return {
        "path": path.relative_to(base).as_posix(),
        "sha256": sha256_file(path),
    }


def candidate(
    candidate_id: str,
    proposed: float,
    evaluated: float,
    family: str,
    speedup: float,
    whole_model_speedup: float,
    evidence: dict,
    upstream_ready: bool,
) -> dict:
    return {
        "candidate_id": candidate_id,
        "proposed_at_seconds": proposed,
        "evaluated_at_seconds": evaluated,
        "architecture_family": family,
        "compile_attempts": 1,
        "measurement_attempts": 1,
        "correctness": "PASS",
        "speedup": speedup,
        "heldout_correctness": "PASS",
        "whole_model_speedup": whole_model_speedup,
        "upstream_ready": upstream_ready,
        "evidence": [evidence],
    }


def write_result(trial_dir: Path, rows: list[dict], elapsed: float) -> None:
    trial = json.loads((trial_dir / "trial.json").read_text(encoding="utf-8"))
    atomic_json(
        trial_dir / "result.json",
        {
            "schema_version": "community-trial-result-v1",
            "trial_id": trial["trial_id"],
            "task_id": trial["task_id"],
            "arm": trial["arm"],
            "agent_identity": "fixed-agent-and-prompt",
            "completion_status": "COMPLETE",
            "elapsed_seconds": elapsed,
            "technical_repair_attempts": 1,
            "causal_revisions": 1,
            "candidates": rows,
            "notes": [],
        },
    )


def main() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        corpus = base / "corpus"
        captured = capture_pr(
            "example/project", 7, corpus, FakeGitHubClient(), ROOT
        )
        event_path = corpus / "events" / "training-event.json"
        event_path.parent.mkdir(parents=True)
        event_path.write_text(
            json.dumps(event_for(Path(captured["manifest"])), indent=2) + "\n",
            encoding="utf-8",
        )
        graph = build_graph(corpus, ["example/project", "other/project"], ROOT)

        suite_dir = base / "suite"
        assets = suite_dir / "assets"
        assets.mkdir(parents=True)
        graph_path = assets / "community_graph.json"
        task_path = assets / "task.json"
        oracle_path = assets / "oracle.json"
        prompt_path = assets / "prompt.md"
        atomic_json(graph_path, graph)
        atomic_json(
            task_path,
            {
                "operator": "held-out logits projection",
                "constraint": "preserve exact outputs",
            },
        )
        atomic_json(
            oracle_path,
            {"hidden_until_after_trial": True, "known_family": "operator-fusion"},
        )
        prompt_path.write_text("Optimize the frozen task under its budget.\n")

        captured_at = datetime.fromisoformat(
            json.loads(Path(captured["manifest"]).read_text())["captured_at"]
        )
        cutoff = captured_at + timedelta(hours=1)
        suite = {
            "schema_version": "community-temporal-suite-v1",
            "suite_id": "example.temporal-v1",
            "cutoff_at": cutoff.isoformat(),
            "claim_boundary": "EVALUATION_PROTOCOL_ONLY",
            "training_graph": identity(graph_path, suite_dir),
            "protocol": {
                "arms": ["CONTROL", "COMMUNITY_AUGMENTED"],
                "repeats": 2,
                "randomized_order": True,
                "network_policy": "DISABLED_AFTER_MATERIALIZATION",
                "model_identity": "same-model-same-settings",
                "prompt_identity": identity(prompt_path, suite_dir),
                "budgets": {
                    "wall_clock_seconds": 900,
                    "max_candidates": 4,
                    "max_compile_attempts": 6,
                    "max_measurements": 6,
                    "max_technical_repairs": 2,
                    "max_causal_revisions": 2,
                },
                "metrics": [
                    "TIME_TO_FIRST_CORRECT",
                    "TIME_TO_FIRST_IMPROVEMENT",
                    "BEST_SPEEDUP",
                    "ARCHITECTURE_FAMILY_COVERAGE",
                    "HELDOUT_CORRECTNESS",
                    "WHOLE_MODEL_SPEEDUP",
                    "UPSTREAM_READINESS",
                ],
            },
            "tasks": [
                {
                    "task_id": "heldout.logits",
                    "available_at": (cutoff + timedelta(hours=1)).isoformat(),
                    "repository": "other/project",
                    "pr_number": 8,
                    "base_revision": "1234567",
                    "target_hardware": "test GPU",
                    "packet": identity(task_path, suite_dir),
                    "hidden_oracle": identity(oracle_path, suite_dir),
                }
            ],
        }
        suite_path = suite_dir / "suite.json"
        atomic_json(suite_path, suite)
        assert validate_suite(suite_path, corpus, ROOT)["status"] == "PASS"

        control_dir = base / "control"
        community_dir = base / "community"
        materialize_trial(
            suite_path,
            corpus,
            "heldout.logits",
            "CONTROL",
            1,
            control_dir,
            ROOT,
        )
        materialize_trial(
            suite_path,
            corpus,
            "heldout.logits",
            "COMMUNITY_AUGMENTED",
            1,
            community_dir,
            ROOT,
        )
        assert not (control_dir / "knowledge").exists()
        assert (community_dir / "knowledge" / "community_graph.json").is_file()
        assert not (control_dir / "input" / "oracle.json").exists()
        assert not (community_dir / "input" / "oracle.json").exists()

        for trial_dir in (control_dir, community_dir):
            evidence_path = trial_dir / "evidence.json"
            atomic_json(evidence_path, {"correctness": "PASS"})
            evidence = identity(evidence_path, trial_dir)
            if trial_dir == control_dir:
                rows = [
                    candidate(
                        "control-one",
                        100,
                        420,
                        "schedule-tuning",
                        1.04,
                        1.01,
                        evidence,
                        False,
                    )
                ]
                elapsed = 700
            else:
                rows = [
                    candidate(
                        "community-one",
                        20,
                        140,
                        "operator-fusion",
                        1.18,
                        1.08,
                        evidence,
                        True,
                    ),
                    candidate(
                        "community-two",
                        60,
                        250,
                        "data-layout",
                        1.10,
                        1.03,
                        evidence,
                        False,
                    ),
                ]
                elapsed = 500
            write_result(trial_dir, rows, elapsed)

        control_assessment = assess_trial(control_dir, ROOT)
        community_assessment = assess_trial(community_dir, ROOT)
        assert control_assessment["metrics"]["best_speedup"] == 1.04
        assert community_assessment["metrics"]["upstream_ready_count"] == 1
        report = compare_trials(
            control_dir, community_dir, base / "comparison.json", ROOT
        )
        assert report["deltas"]["time_to_first_correct_seconds_saved"] == 280
        assert report["deltas"]["best_speedup_gain"] > 0

        over_budget = json.loads(
            (community_dir / "result.json").read_text(encoding="utf-8")
        )
        over_budget["elapsed_seconds"] = 901
        atomic_json(community_dir / "result.json", over_budget)
        try:
            assess_trial(community_dir, ROOT)
        except ValueError as error:
            assert "frozen budget" in str(error)
        else:
            raise AssertionError("over-budget trial was accepted")

        leaking = json.loads(suite_path.read_text(encoding="utf-8"))
        leaking["cutoff_at"] = "2025-12-31T00:00:00+00:00"
        atomic_json(suite_path, leaking)
        try:
            validate_suite(suite_path, corpus, ROOT)
        except ValueError as error:
            assert "available after cutoff" in str(error)
        else:
            raise AssertionError("post-cutoff training evidence was accepted")

    print("community evaluation test: PASS")


if __name__ == "__main__":
    main()
