#!/usr/bin/env python3
"""Exercise repairable discovery, screening and qualification promotion."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from optimizer_step import discovery_action


def write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        path.write_text(data, encoding="utf-8")
    else:
        path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_cli(run: Path, *args: str, expected: int = 0) -> dict:
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts/kernel_opt.py"), "candidate", *args, "--run", str(run)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert completed.returncode == expected, (completed.stdout, completed.stderr)
    return json.loads(completed.stdout) if completed.stdout.strip() else {}


def main() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        run = Path(temporary) / "runs" / "discovery"
        (run / "models").mkdir(parents=True)
        workspace = run / "candidates" / "c1" / "workspace"
        workspace.mkdir(parents=True)
        write(run / "models/baseline.json", {
            "schema_version": "production-baseline-v1",
            "status": "VALID",
            "correctness": {"status": "PASS", "evidence": []},
        })
        write(run / "models/experiment_queue.json", {"requests": []})
        write(workspace / "kernel.py", "VALUE = 1\n")
        write(workspace / "build.py", "from pathlib import Path\nraise SystemExit(0 if Path('ready.flag').exists() else 3)\n")
        write(workspace / "correctness.py", "raise SystemExit(0)\n")
        write(workspace / "smoke.py", """
import json
from pathlib import Path
result = {
    "schema_version": "candidate-smoke-result-v1",
    "status": "PASS",
    "candidate_id": "c1",
    "objective": {"direction": "minimize", "baseline": 10.0, "candidate": 8.0, "unit": "us"},
    "cases": [{"case_id": "anchor", "role": "ANCHOR"}, {"case_id": "edge", "role": "EDGE"}],
}
Path('../smoke.json').write_text(json.dumps(result))
""".lstrip())
        spec_path = run / "candidates" / "c1" / "spec.json"
        write(spec_path, {
            "candidate_id": "c1",
            "name": "repairable candidate",
            "family": "layout-redesign",
            "change_axes": ["layout", "warp-ownership"],
            "hypothesis": "remove a materialized transfer",
            "expected_global_effect": "reduce weighted production latency",
            "source_paths": ["candidates/c1/workspace/kernel.py"],
            "commands": {
                "build": {"argv": ["{python}", "build.py"], "cwd": "candidates/c1/workspace", "timeout_seconds": 30},
                "correctness": {"argv": ["{python}", "correctness.py"], "cwd": "candidates/c1/workspace", "timeout_seconds": 30},
                "smoke": {"argv": ["{python}", "smoke.py"], "cwd": "candidates/c1/workspace", "timeout_seconds": 30}
            },
            "smoke_result_path": "candidates/c1/smoke.json",
            "development_budget": {"max_technical_attempts": 3}
        })
        run_cli(
            run, "init", "--min-candidates", "1", "--max-candidates", "2",
            "--min-families", "1", "--max-technical-attempts", "3",
            "--max-candidate-wall-clock-minutes", "5", "--max-total-wall-clock-minutes", "10",
            "--promotion-threshold-percent", "1.0",
        )
        run_cli(run, "add", "--spec", str(spec_path))
        failed = run_cli(run, "run", "--candidate-id", "c1")
        assert failed["status"] == "DEVELOPING"
        pool = json.loads((run / "models/candidate_pool.json").read_text(encoding="utf-8"))
        item = pool["candidates"][0]
        assert item["attempts"][0]["status"] == "TECHNICAL_FAILURE"
        assert item["status"] != "REJECTED"
        repair = discovery_action(run, ROOT / "scripts")
        assert repair and repair["action"] == "REPAIR_DISCOVERY_CANDIDATE"

        write(workspace / "ready.flag", "ready\n")
        screened = run_cli(run, "run", "--candidate-id", "c1")
        assert screened["status"] == "QUALIFICATION_READY"
        assert abs(screened["improvement_percent"] - 20.0) < 1e-9
        promoted = run_cli(run, "promote", "--candidate-id", "c1")
        assert promoted["status"] == "PROMOTED_TO_QUALIFICATION"
        qualification = discovery_action(run, ROOT / "scripts")
        assert qualification and qualification["action"] == "BUILD_QUALIFICATION_CONTRACT"
        promotion_path = run / promoted["promotion"]["path"]
        promotion = json.loads(promotion_path.read_text(encoding="utf-8"))
        assert "production acceptance" in promotion["claims_forbidden"]
        pool = json.loads((run / "models/candidate_pool.json").read_text(encoding="utf-8"))
        pool["status"] = "PAUSED"
        write(run / "models/candidate_pool.json", pool)
        paused = discovery_action(run, ROOT / "scripts")
        assert paused and paused["action"] == "DISCOVERY_BUDGET_REVIEW"
    print("candidate discovery loop test: PASS")


if __name__ == "__main__":
    main()
