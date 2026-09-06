#!/usr/bin/env python3
"""Run one materialized community A/B trial with auditable Codex JSONL logs."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
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
    codex: str,
    trial: Path,
    model: str,
    reasoning_effort: str,
    output_path: Path | None = None,
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
        str(output_path or (trial / "result.json")),
        "-",
    ]


def run_phase(
    command: list[str],
    trial: Path,
    prompt: str,
    transcript_path: Path,
    stderr_path: Path,
    timeout_seconds: float,
) -> tuple[int, bool]:
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
                process.communicate(prompt, timeout=max(timeout_seconds, 1.0))
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                return process.returncode, True
    return process.returncode, False


def valid_result(result_path: Path, manifest: dict) -> tuple[bool, list[str]]:
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        return False, [str(exc)]
    mismatches = [
        field
        for field in ("trial_id", "task_id", "arm")
        if result.get(field) != manifest[field]
    ]
    return not mismatches, mismatches


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compact_finalizer_context(
    trial: Path,
    manifest: dict,
    started_at: datetime,
    search_transcript: Path,
    finalization_started_at_seconds: float,
) -> dict:
    artifacts = []
    for path in sorted((trial / "evidence").glob("*.json")):
        try:
            content = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        written_at = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
        artifacts.append(
            {
                "path": path.relative_to(trial).as_posix(),
                "sha256": sha256(path),
                "written_at_seconds": max(
                    0.0, (written_at - started_at).total_seconds()
                ),
                "content": content,
            }
        )
    source_identities = []
    for path in sorted((trial / "source").rglob("community_candidate.py")):
        source_identities.append(
            {
                "path": path.relative_to(trial).as_posix(),
                "sha256": sha256(path),
            }
        )
    shortlist_path = trial / "knowledge" / "prior_shortlist.json"
    shortlist = None
    if shortlist_path.is_file():
        shortlist = json.loads(shortlist_path.read_text(encoding="utf-8"))
    frontier_identity = manifest.get("frontier_contract")
    frontier_contract = None
    if frontier_identity is not None:
        frontier_contract = json.loads(
            (trial / frontier_identity["path"]).read_text(encoding="utf-8")
        )
    execution_summary = {
        "command_count": 0,
        "failed_command_count": 0,
        "declined_command_count": 0,
        "source_change_count": 0,
        "primary_agent_messages": [],
    }
    with search_transcript.open(encoding="utf-8", newline="") as transcript:
        for line in transcript:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            item = event.get("item") or {}
            if (
                event.get("type") == "item.started"
                and item.get("type") == "command_execution"
            ):
                execution_summary["command_count"] += 1
            if (
                event.get("type") == "item.completed"
                and item.get("type") == "command_execution"
            ):
                status = item.get("status")
                if status == "declined":
                    execution_summary["declined_command_count"] += 1
                elif status == "failed" or item.get("exit_code") not in (None, 0):
                    execution_summary["failed_command_count"] += 1
            if (
                event.get("type") == "item.completed"
                and item.get("type") == "file_change"
                and item.get("status") == "completed"
            ):
                for change in item.get("changes") or []:
                    changed_path = str(change.get("path", "")).replace(
                        "\\", "/"
                    ).lower()
                    if "/source/" in changed_path or changed_path.startswith(
                        "source/"
                    ):
                        execution_summary["source_change_count"] += 1
            if (
                event.get("type") == "item.completed"
                and item.get("type") == "agent_message"
            ):
                text = str(item.get("text", "")).strip()
                if text:
                    execution_summary["primary_agent_messages"].append(text[:1500])
    execution_summary["primary_agent_messages"] = execution_summary[
        "primary_agent_messages"
    ][-6:]
    return {
        "manifest": manifest,
        "result_schema": json.loads(
            (trial / "input" / "result.schema.json").read_text(encoding="utf-8")
        ),
        "frontier_closure_schema": json.loads(
            (trial / "input" / "frontier-closure.schema.json").read_text(
                encoding="utf-8"
            )
        ),
        "frontier_contract": frontier_contract,
        "artifacts": artifacts,
        "source_identities": source_identities,
        "prior_shortlist": shortlist,
        "search_execution_summary": execution_summary,
        "finalization_started_at_seconds": finalization_started_at_seconds,
    }


def combine_phase_logs(
    trial: Path,
    search_transcript: Path,
    search_stderr: Path,
    finalizer_transcript: Path | None,
    finalizer_stderr: Path | None,
    marker: dict | None,
    commit_events: list[dict] | None = None,
) -> tuple[Path, Path]:
    transcript_path = trial / "executor.jsonl"
    stderr_path = trial / "executor.stderr.log"
    transcript = search_transcript.read_bytes()
    stderr = search_stderr.read_bytes()
    if marker is not None:
        transcript += (json.dumps(marker, sort_keys=True) + "\n").encode("utf-8")
    if finalizer_transcript is not None:
        transcript += finalizer_transcript.read_bytes()
    for event in commit_events or []:
        transcript += (json.dumps(event, sort_keys=True) + "\n").encode("utf-8")
    if finalizer_stderr is not None:
        stderr += b"\n--- FINALIZER ---\n" + finalizer_stderr.read_bytes()
    transcript_path.write_bytes(transcript)
    stderr_path.write_bytes(stderr)
    return transcript_path, stderr_path


def commit_finalizer_draft(
    trial: Path,
    draft_path: Path,
    finalization_started_at_seconds: float,
    technical_repair_lower_bound: int,
) -> list[dict]:
    draft = json.loads(draft_path.read_text(encoding="utf-8"))
    if set(draft) != {"frontier_closure", "result"}:
        raise ValueError(
            "finalizer draft must contain exactly frontier_closure and result"
        )
    closure = draft["frontier_closure"]
    result = draft["result"]
    if not isinstance(closure, dict) or not isinstance(result, dict):
        raise ValueError("finalizer draft closure and result must be objects")
    closure_path = trial / "evidence" / "frontier-closure.json"
    closure_path.write_text(
        json.dumps(closure, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    closure_identity = {
        "path": closure_path.relative_to(trial).as_posix(),
        "sha256": sha256(closure_path),
    }
    result["frontier_closure"] = closure_identity
    result["completion_status"] = "BUDGET_EXHAUSTED"
    result["technical_repair_attempts"] = max(
        int(result.get("technical_repair_attempts", 0)),
        technical_repair_lower_bound,
    )
    result["elapsed_seconds"] = max(
        float(result.get("elapsed_seconds", 0)),
        finalization_started_at_seconds,
    )
    result_path = trial / "result.json"
    result_text = json.dumps(result, separators=(",", ":"), sort_keys=True)
    result_path.write_text(result_text + "\n", encoding="utf-8")
    return [
        {
            "type": "runner.result_committed",
            "draft_sha256": sha256(draft_path),
            "frontier_closure_sha256": closure_identity["sha256"],
            "result_sha256": sha256(result_path),
        },
        {
            "type": "item.completed",
            "item": {
                "id": "runner_committed_result",
                "type": "agent_message",
                "text": result_text,
            },
        },
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
    frontier_identity = manifest.get("frontier_contract")
    if frontier_identity is None:
        search_stop_fraction = 0.7
    else:
        frontier_contract_path = trial / frontier_identity["path"]
        frontier_contract = json.loads(
            frontier_contract_path.read_text(encoding="utf-8")
        )
        search_stop_fraction = float(
            frontier_contract["policy"]["deadline_fraction"]
        )
    primary_fraction = min(search_stop_fraction + 0.15, 0.9)
    if not 0 < search_stop_fraction < primary_fraction < 1:
        raise ValueError(
            "require 0 < sealed frontier deadline_fraction < primary-fraction < 1"
        )
    timeout = wall_budget + args.startup_grace_seconds
    codex = shutil.which(args.codex)
    if codex is None:
        raise FileNotFoundError(f"Codex executable not found: {args.codex}")
    command = command_for(codex, trial, args.model, args.reasoning_effort)
    started_at = datetime.now(timezone.utc)
    monotonic_started = time.monotonic()
    search_stop_at = started_at + timedelta(
        seconds=wall_budget * search_stop_fraction
    )
    primary_due_at = started_at + timedelta(
        seconds=wall_budget * primary_fraction
    )
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
        f"primary_result_due_at={primary_due_at.isoformat()}\n"
        f"result_json_due_at={result_due_at.isoformat()}\n"
        "At stop_candidate_search_at, do not start another candidate or broad "
        "inspection. Run only the minimum held-out check for the selected "
        "candidate, close the frontier and write the final JSON. The primary "
        "executor will be terminated at primary_result_due_at if it has not "
        "returned. If that deadline is near, "
        "skip optional summaries and emit a valid conservative result immediately.\n"
    )
    search_transcript = trial / "executor.search.jsonl"
    search_stderr = trial / "executor.search.stderr.log"
    primary_seconds = wall_budget * primary_fraction
    primary_returncode, primary_timed_out = run_phase(
        command,
        trial,
        prompt,
        search_transcript,
        search_stderr,
        primary_seconds,
    )
    result_path = trial / "result.json"
    result_ok, result_errors = valid_result(result_path, manifest)
    finalizer_transcript = None
    finalizer_stderr = None
    phase_marker = None
    finalized = False

    if not (primary_returncode == 0 and result_ok):
        phase_started_at = datetime.now(timezone.utc)
        phase_marker = {
            "type": "runner.finalization_started",
            "started_at": phase_started_at.isoformat(),
            "reason": (
                "PRIMARY_DEADLINE"
                if primary_timed_out
                else "PRIMARY_RESULT_INVALID"
            ),
            "search_transcript_sha256": sha256(search_transcript),
            "search_stderr_sha256": sha256(search_stderr),
        }
        remaining_seconds = wall_budget - (time.monotonic() - monotonic_started)
        if remaining_seconds <= 1:
            combine_phase_logs(
                trial,
                search_transcript,
                search_stderr,
                None,
                None,
                phase_marker,
                None,
            )
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
        finalization_started_at_seconds = time.monotonic() - monotonic_started
        finalizer_context = compact_finalizer_context(
            trial,
            manifest,
            started_at,
            search_transcript,
            finalization_started_at_seconds,
        )
        finalizer_prompt = (
            "You are a clerical bounded finalizer for an interrupted optimization "
            "trial. The complete compact state is embedded below. Do not call any "
            "tool, run any command, inspect another file, edit source, repeat a "
            "measurement, or propose a candidate. Immediately emit only one JSON "
            "draft object with exactly two keys: frontier_closure and result. "
            "frontier_closure must conform to the embedded frontier_closure_schema; "
            "result must conform to result_schema except that it must omit the "
            "frontier_closure identity, which the runner will hash and inject. Use only "
            "hashes, candidate metrics and correctness already present in the "
            "embedded artifacts. Reuse a valid existing closure content when one is "
            "embedded; otherwise construct conservative closure accounting from the "
            "frozen ranking and artifacts. Preserve unknowns and set upstream_ready false and "
            "whole_model_speedup null unless explicit artifacts prove otherwise. "
            "For proposed/evaluated times, use conservative artifact "
            "written_at_seconds; these are telemetry, not chronology proof. Do not "
            "invent a performance value, correctness result or readiness claim. "
            "Set elapsed_seconds to at least finalization_started_at_seconds because "
            "the finalizer itself is part of trial wall time.\n"
            "Final identity (copy exactly):\n"
            f"trial_id={manifest['trial_id']}\n"
            f"task_id={manifest['task_id']}\n"
            f"arm={manifest['arm']}\n"
            f"original_started_at={started_at.isoformat()}\n"
            f"hard_result_deadline_at={result_due_at.isoformat()}\n"
            "COMPACT_FINALIZER_CONTEXT_JSON:\n"
            + json.dumps(finalizer_context, sort_keys=True)
            + "\n"
        )
        finalizer_transcript = trial / "executor.finalizer.jsonl"
        finalizer_stderr = trial / "executor.finalizer.stderr.log"
        finalizer_draft = trial / "finalizer_draft.json"
        finalizer_command = command_for(
            codex, trial, args.model, "low", finalizer_draft
        )
        finalizer_returncode, finalizer_timed_out = run_phase(
            finalizer_command,
            trial,
            finalizer_prompt,
            finalizer_transcript,
            finalizer_stderr,
            remaining_seconds,
        )
        finalized = True
        commit_events = []
        if finalizer_returncode == 0 and not finalizer_timed_out:
            try:
                commit_events = commit_finalizer_draft(
                    trial,
                    finalizer_draft,
                    finalization_started_at_seconds,
                    max(
                        finalizer_context["search_execution_summary"][
                            "failed_command_count"
                        ],
                        finalizer_context["search_execution_summary"][
                            "declined_command_count"
                        ],
                    ),
                )
            except (FileNotFoundError, json.JSONDecodeError, TypeError, ValueError):
                commit_events = []
        result_ok, result_errors = valid_result(result_path, manifest)
        process_returncode = finalizer_returncode
        timed_out = finalizer_timed_out
    else:
        process_returncode = primary_returncode
        timed_out = False
        commit_events = []

    transcript_path, stderr_path = combine_phase_logs(
        trial,
        search_transcript,
        search_stderr,
        finalizer_transcript,
        finalizer_stderr,
        phase_marker,
        commit_events,
    )
    if timed_out:
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
    if not result_ok:
        print(
            json.dumps(
                {"status": "INVALID_RESULT", "errors": result_errors},
                sort_keys=True,
            )
        )
        return 3
    if process_returncode != 0:
        print(
            json.dumps(
                {
                    "status": "FAILED",
                    "trial_id": manifest["trial_id"],
                    "returncode": process_returncode,
                },
                sort_keys=True,
            )
        )
        return process_returncode
    print(
        json.dumps(
            {
                "status": "FINALIZED" if finalized else "COMPLETE",
                "trial_id": manifest["trial_id"],
                "returncode": process_returncode,
                "transcript": transcript_path.name,
                "stderr": stderr_path.name,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
