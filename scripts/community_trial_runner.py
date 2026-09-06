#!/usr/bin/env python3
"""Run one materialized community A/B trial with auditable Codex JSONL logs."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trial", type=Path, required=True)
    parser.add_argument("--model", default="gpt-5.6-sol")
    parser.add_argument("--reasoning-effort", default="high")
    parser.add_argument("--startup-grace-seconds", type=int, default=30)
    parser.add_argument("--codex", default="codex")
    return parser.parse_args()


def command_for(
    codex: str, trial: Path, model: str, reasoning_effort: str
) -> list[str]:
    # Do not pass input/result.schema.json as --output-schema.  The repository
    # schema is intentionally stronger than the structured-output provider
    # subset (for example, it uses uniqueItems).  The completed result is
    # validated locally by audit-execution and assess-trial instead.
    return [
        codex,
        "exec",
        "--dangerously-bypass-approvals-and-sandbox",
        "--skip-git-repo-check",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--json",
        "-C",
        str(trial),
        "-m",
        model,
        "-c",
        f'model_reasoning_effort="{reasoning_effort}"',
        "-o",
        str(trial / "result.json"),
        "-",
    ]


def main() -> int:
    args = parse_args()
    trial = args.trial.resolve()
    manifest_path = trial / "trial.json"
    executor_path = trial / "input" / "executor.md"
    if not manifest_path.is_file() or not executor_path.is_file():
        raise FileNotFoundError("materialized trial or executor prompt is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    wall_budget = int(manifest["budget"]["wall_clock_seconds"])
    if args.startup_grace_seconds < 0:
        raise ValueError("startup grace must be non-negative")
    timeout = wall_budget + args.startup_grace_seconds
    codex = shutil.which(args.codex)
    if codex is None:
        raise FileNotFoundError(f"Codex executable not found: {args.codex}")
    command = command_for(codex, trial, args.model, args.reasoning_effort)
    started_at = datetime.now(timezone.utc)
    search_stop_at = started_at + timedelta(seconds=wall_budget * 0.70)
    result_due_at = started_at + timedelta(seconds=wall_budget)
    prompt = executor_path.read_text(encoding="utf-8")
    prompt += (
        "\n\nFinal identity reminder (copy these exact strings without editing):\n"
        f"trial_id={manifest['trial_id']}\n"
        f"task_id={manifest['task_id']}\n"
        f"arm={manifest['arm']}\n"
        "Concrete runtime deadlines (UTC; runner-enforced):\n"
        f"started_at={started_at.isoformat()}\n"
        f"stop_candidate_search_at={search_stop_at.isoformat()}\n"
        f"result_json_due_at={result_due_at.isoformat()}\n"
        "At stop_candidate_search_at, do not start another candidate or broad "
        "inspection. Run only the minimum held-out check for the selected "
        "candidate and write the final JSON. If result_json_due_at is near, "
        "skip optional summaries and emit a valid conservative result immediately.\n"
    )
    transcript_path = trial / "executor.jsonl"
    stderr_path = trial / "executor.stderr.log"
    with transcript_path.open("w", encoding="utf-8", newline="\n") as stdout_file:
        with stderr_path.open("w", encoding="utf-8", newline="\n") as stderr_file:
            process = subprocess.Popen(
                command,
                cwd=trial,
                stdin=subprocess.PIPE,
                stdout=stdout_file,
                stderr=stderr_file,
                text=True,
                encoding="utf-8",
            )
            try:
                process.communicate(prompt, timeout=timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                print(
                    json.dumps(
                        {
                            "status": "TIMEOUT",
                            "trial_id": manifest["trial_id"],
                            "timeout_seconds": timeout,
                        },
                        sort_keys=True,
                    )
                )
                return 124
    if process.returncode == 0:
        result_path = trial / "result.json"
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            print(json.dumps({"status": "INVALID_RESULT", "error": str(exc)}))
            return 3
        mismatches = [
            field
            for field in ("trial_id", "task_id", "arm")
            if result.get(field) != manifest[field]
        ]
        if mismatches:
            print(
                json.dumps(
                    {"status": "IDENTITY_MISMATCH", "fields": mismatches},
                    sort_keys=True,
                )
            )
            return 3
    print(
        json.dumps(
            {
                "status": "COMPLETE" if process.returncode == 0 else "FAILED",
                "trial_id": manifest["trial_id"],
                "returncode": process.returncode,
                "transcript": transcript_path.name,
                "stderr": stderr_path.name,
            },
            sort_keys=True,
        )
    )
    return process.returncode


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
