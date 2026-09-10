#!/usr/bin/env python3
"""Exercise bounded Draft progress and exit routing."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/upstream_draft_progress.py"


def base() -> dict:
    return {
        "schema_version": "upstream-draft-progress-v1",
        "pull_request": {
            "url": "https://github.com/sgl-project/sglang/pull/38882",
            "repository": "sgl-project/sglang",
            "number": 38882,
            "state": "OPEN",
            "draft": True,
        },
        "observation": {
            "draft_since": "2026-09-10T20:00:00Z",
            "last_material_progress_at": "2026-09-11T04:00:00Z",
            "observed_at": "2026-09-11T06:00:00Z",
            "source": "DASHBOARD_STAGE_HISTORY",
            "prospective_lower_bound_only": True,
        },
        "qualification": {
            "status": "ACTIVE",
            "value_status": "UNPROVEN",
            "next_gate": "official package tests and production materiality",
            "blocker_owner": "EXECUTION_LANE",
        },
        "policy": {"stale_after_hours": 48},
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


def main() -> None:
    active = run(base())["decision"]
    assert active["state"] == "ACTIVE_QUALIFICATION"
    assert active["automatic_close_or_ready_authorized"] is False

    passed = base()
    passed["qualification"].update({"status": "PASS", "value_status": "POSITIVE"})
    assert run(passed)["decision"]["recommended_action"] == "MARK_READY"

    failed = base()
    failed["qualification"]["status"] = "FAILED"
    assert run(failed)["decision"]["recommended_action"] == "CLOSE_OR_REVISE_DRAFT"

    disproven = base()
    disproven["qualification"]["value_status"] = "DISPROVEN"
    assert run(disproven)["decision"]["state"] == "EXIT_REQUIRED"

    stale = base()
    stale["observation"]["observed_at"] = "2026-09-13T05:00:00Z"
    assert run(stale)["decision"]["recommended_action"] == "REPLAN_OR_CLOSE_DRAFT"

    environment = copy.deepcopy(stale)
    environment["qualification"].update(
        {"status": "ENVIRONMENT_BLOCKED", "blocker_owner": "EXTERNAL_RESOURCE"}
    )
    decision = run(environment)["decision"]
    assert decision["state"] == "STALE_EXTERNAL_GATE"
    assert decision["recommended_action"] == "EXTERNALIZE_GATE_OR_CLOSE_DRAFT"

    ready = base()
    ready["pull_request"]["draft"] = False
    ready["observation"]["draft_since"] = None
    ready["observation"]["last_material_progress_at"] = None
    assert run(ready)["decision"]["recommended_action"] == "USE_REVIEW_HANDOFF"

    bad_clock = base()
    bad_clock["observation"]["observed_at"] = "2026-09-11T06:00:00"
    result = run(bad_clock, expected_code=1)
    assert any("timezone is required" in error for error in result["errors"])

    hidden = base()
    hidden["qualification"]["hidden"] = True
    result = run(hidden, expected_code=1)
    assert any("unexpected keys" in error for error in result["errors"])
    print("upstream draft-progress test: PASS")


if __name__ == "__main__":
    main()
