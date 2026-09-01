#!/usr/bin/env python3
"""Exercise opportunity ranking, claim bounds, and implementation-first routing."""

from __future__ import annotations

import json
import hashlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from optimizer_step import discovery_action


def write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def cli(command: str, run: Path, *args: str, expected: int = 0) -> dict:
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts/kernel_opt.py"), command, *args, "--run", str(run)],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    assert completed.returncode == expected, (completed.stdout, completed.stderr)
    return json.loads(completed.stdout) if completed.stdout.strip() else {}


def opportunity_spec(identifier: str, family: str, gain: tuple[float, float], ceiling: float, cost: float, evidence_sha256: str) -> dict:
    return {
        "opportunity_id": identifier,
        "name": identifier,
        "model_scope": "CURRENT_SCHEDULE",
        "source_model_term": f"term-{identifier}",
        "affected_stages": [identifier],
        "current_contribution_us": ceiling + 1,
        "optimistic_gain_ceiling_us": ceiling,
        "likely_gain_interval_us": {"lower": gain[0], "upper": gain[1]},
        "confidence": "HIGH",
        "rewrite_families": [family],
        "implementation_budget_minutes": cost,
        "hypothesis": "remove globally visible scheduled work",
        "derivation": "measured stage contribution times removable work fraction",
        "evidence": [{"path": "models/baseline.json", "sha256": evidence_sha256, "claim": "current objective contribution"}],
    }


def main() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        run = Path(temporary) / "run"
        (run / "models").mkdir(parents=True)
        for name in ("operator.json", "workload.json", "hardware.json"):
            shutil.copyfile(ROOT / "tests" / "fixtures" / name, run / name)
        write(run / "models" / "baseline.json", {"status": "VALID", "correctness": {"status": "PASS"}})
        evidence_sha256 = hashlib.sha256((run / "models/baseline.json").read_bytes()).hexdigest()
        cli("candidate", run, "init", "--min-candidates", "2", "--max-candidates", "4", "--min-families", "2")
        first = discovery_action(run, ROOT / "scripts")
        assert first and first["action"] == "BUILD_OPPORTUNITY_MAP", first
        cli(
            "opportunity", run, "init", "--min-opportunities", "2", "--max-opportunities", "4",
            "--min-rewrite-families", "2", "--min-candidate-opportunities", "2",
        )
        specs = [
            opportunity_spec("large-cheap", "cross-stage-fusion", (3.0, 5.0), 6.0, 10.0, evidence_sha256),
            opportunity_spec("small-expensive", "tile-retune", (1.0, 2.0), 3.0, 30.0, evidence_sha256),
        ]
        for spec in specs:
            path = run / "models" / f"{spec['opportunity_id']}.json"
            write(path, spec)
            cli("opportunity", run, "add", "--spec", str(path))
        before_rank = discovery_action(run, ROOT / "scripts")
        assert before_rank and before_rank["action"] == "RANK_OPPORTUNITIES", before_rank
        ranked = cli("opportunity", run, "rank")
        assert ranked["opportunities"][0]["opportunity_id"] == "large-cheap", ranked
        map_path = run / "models" / "opportunity_map.json"
        tampered = json.loads(map_path.read_text(encoding="utf-8"))
        tampered["opportunities"][0]["priority_score"] = 999.0
        write(map_path, tampered)
        blocked = discovery_action(run, ROOT / "scripts")
        assert blocked and blocked["action"] == "BLOCK_INVALID_OPPORTUNITY_MAP", blocked
        cli("opportunity", run, "rank")
        retrieve = discovery_action(run, ROOT / "scripts")
        assert retrieve and retrieve["action"] == "RETRIEVE_OPTIMIZATION_METHODS", retrieve
        cli("method", run, "recommend")
        implement = discovery_action(run, ROOT / "scripts")
        assert implement and implement["action"] == "EXPAND_DISCOVERY_PORTFOLIO", implement
        target = implement["blocking_inputs"][0]["next_ranked_uncovered_opportunity"]
        assert target["opportunity_id"] == "large-cheap", target
        pool_path = run / "models" / "candidate_pool.json"
        pool = json.loads(pool_path.read_text(encoding="utf-8"))
        pool["candidates"] = [
            {"candidate_id": "low-first", "opportunity_id": "small-expensive", "family": "tile-retune", "status": "PROPOSED"},
            {"candidate_id": "high-second", "opportunity_id": "large-cheap", "family": "cross-stage-fusion", "status": "PROPOSED"},
        ]
        write(pool_path, pool)
        ranked_implementation = discovery_action(run, ROOT / "scripts")
        assert ranked_implementation and ranked_implementation["action"] == "IMPLEMENT_DISCOVERY_CANDIDATE"
        assert ranked_implementation["blocking_inputs"][0]["candidate_id"] == "high-second", ranked_implementation

        invalid = opportunity_spec("false-proof", "bad-family", (1.0, 2.0), 2.0, 10.0, evidence_sha256)
        invalid["model_scope"] = "ABSOLUTE_GLOBAL_OPTIMUM"
        invalid_path = run / "models" / "invalid.json"
        write(invalid_path, invalid)
        failed = cli("opportunity", run, "add", "--spec", str(invalid_path), expected=1)
        assert not failed

        candidate_root = run / "candidates" / "bad"
        candidate_root.mkdir(parents=True)
        source = candidate_root / "kernel.py"
        source.write_text("pass\n", encoding="utf-8")
        candidate_spec = {
            "candidate_id": "bad", "opportunity_id": "missing", "name": "bad",
            "family": "cross-stage-fusion", "change_axes": ["fusion"], "hypothesis": "test",
            "expected_global_effect": "test", "predicted_global_gain_us": {"lower": 1, "upper": 2},
            "source_paths": ["candidates/bad/kernel.py"],
            "commands": {stage: {"argv": [sys.executable, "-c", "pass"], "cwd": "candidates/bad", "timeout_seconds": 2} for stage in ("build", "correctness", "smoke")},
            "smoke_result_path": "candidates/bad/smoke.json",
        }
        candidate_path = candidate_root / "spec.json"
        write(candidate_path, candidate_spec)
        failed_candidate = cli("candidate", run, "add", "--spec", str(candidate_path), expected=1)
        assert not failed_candidate
    print("opportunity-driven search test: PASS")


if __name__ == "__main__":
    main()
