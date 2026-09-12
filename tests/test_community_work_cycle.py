#!/usr/bin/env python3
"""Exercise evidence-bound work-cycle timing and fail-closed guards."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from artifact_io import atomic_json, sha256_file  # noqa: E402
from community_work_cycle import (  # noqa: E402
    audit_roots,
    end_phase,
    import_phase_receipt,
    init_ledger,
    pair_baseline,
    record_pr_stage,
    run_phase_command,
    seal_evidence,
    summarize,
    switch_phase,
    validate_ledger,
    write_ledger,
)
from schema_utils import validate_instance  # noqa: E402


def identity(path: Path) -> dict:
    return {"path": path.as_posix(), "sha256": sha256_file(path)}


def ledger(evidence: Path) -> dict:
    return {
        "schema_version": "community-work-cycle-v1",
        "cycle_id": "cycle-1",
        "task_id": "task-1",
        "started_at": "2026-09-07T04:00:00Z",
        "observation_mode": "PROSPECTIVE_EXACT",
        "claim_boundary": "WORK_CYCLE_TIMING_NOT_PERFORMANCE_CAUSALITY",
        "minimum_material_speedup": 1.02,
        "spans": [
            {
                "span_id": "research",
                "phase": "COMMUNITY_RESEARCH",
                "actor": "AGENT",
                "resource_id": None,
                "started_at": "2026-09-07T04:00:00Z",
                "ended_at": "2026-09-07T04:01:00Z",
                "status": "COMPLETE",
                "evidence": [identity(evidence)],
            },
            {
                "span_id": "compute",
                "phase": "COMPILE_AND_MEASURE",
                "actor": "GPU",
                "resource_id": "local-sm89",
                "started_at": "2026-09-07T04:01:00Z",
                "ended_at": "2026-09-07T04:03:00Z",
                "status": "COMPLETE",
                "evidence": [identity(evidence)],
            },
            {
                "span_id": "validate",
                "phase": "CORRECTNESS_VALIDATION",
                "actor": "GPU",
                "resource_id": "local-sm89",
                "started_at": "2026-09-07T04:03:00Z",
                "ended_at": "2026-09-07T04:04:00Z",
                "status": "COMPLETE",
                "evidence": [identity(evidence)],
            },
        ],
        "milestones": [
            {
                "kind": "FIRST_CANDIDATE_PROPOSED",
                "at": "2026-09-07T04:01:00Z",
                "evidence": [identity(evidence)],
            },
            {
                "kind": "FIRST_SCREEN_CORRECT",
                "at": "2026-09-07T04:04:00Z",
                "evidence": [identity(evidence)],
            },
            {
                "kind": "FIRST_MATERIAL_IMPROVEMENT",
                "at": "2026-09-07T04:04:00Z",
                "evidence": [identity(evidence)],
            },
            {
                "kind": "FIRST_QUALIFIED_RESULT",
                "at": "2026-09-07T04:04:00Z",
                "evidence": [identity(evidence)],
            },
        ],
        "outcome": {
            "correctness": "PASS",
            "best_speedup": 1.10,
            "best_whole_model_speedup": None,
            "upstream_ready": False,
            "pull_request_url": None,
            "merged": False,
        },
    }


def test_work_cycle_summary_and_guards() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        evidence = base / "evidence.json"
        evidence.write_text('{"ok": true}\n', encoding="utf-8")
        cycle = base / "cycle.json"
        atomic_json(cycle, ledger(evidence))
        assert validate_ledger(cycle)["cycle_id"] == "cycle-1"
        report = summarize(cycle)
        assert report["buckets"]["research_seconds"] == 60
        assert report["buckets"]["compute_seconds"] == 120
        assert report["buckets"]["validation_seconds"] == 60
        assert report["buckets"]["environment_seconds"] == 0
        assert report["buckets"]["governance_seconds"] == 0
        assert (
            report["phase_coverage"]["environment_governance_measurement_status"]
            == "NOT_SEPARATELY_RECORDED"
        )
        assert (
            report["ratios"]["environment_governance_share_of_attributed_active"]
            is None
        )
        assert report["wall_clock"]["observed_seconds"] == 240
        assert report["wall_clock"]["unaccounted_seconds"] == 0
        assert report["time_to_milestone_seconds"]["FIRST_QUALIFIED_RESULT"] == 240
        schema = json.loads(
            (ROOT / "schemas/community_work_cycle_summary.schema.json").read_text(
                encoding="utf-8"
            )
        )
        assert not validate_instance(report, schema)
        legacy_report = json.loads(json.dumps(report))
        legacy_report["phase_seconds"].pop("ENVIRONMENT_SETUP")
        legacy_report["phase_seconds"].pop("GOVERNANCE_VALIDATION")
        legacy_report["buckets"].pop("environment_seconds")
        legacy_report["buckets"].pop("governance_seconds")
        legacy_report.pop("phase_coverage")
        legacy_report.pop("ratios")
        assert not validate_instance(legacy_report, schema)

        broken = ledger(evidence)
        broken["spans"][1]["started_at"] = "2026-09-07T04:00:30Z"
        original = cycle.read_bytes()
        try:
            write_ledger(cycle, broken)
        except ValueError as error:
            assert "overlap" in str(error)
        else:
            raise AssertionError("overlapping primary phases must fail")
        assert cycle.read_bytes() == original

        below = ledger(evidence)
        below["outcome"]["best_speedup"] = 1.01
        atomic_json(cycle, below)
        try:
            validate_ledger(cycle)
        except ValueError as error:
            assert "threshold" in str(error)
        else:
            raise AssertionError("sub-threshold improvement must fail")


def test_environment_and_governance_overhead_reporting() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        evidence = base / "evidence.json"
        evidence.write_text('{"ok": true}\n', encoding="utf-8")
        cycle = base / "cycle.json"
        value = ledger(evidence)
        value["spans"][0]["phase"] = "ENVIRONMENT_SETUP"
        value["spans"][1]["phase"] = "GOVERNANCE_VALIDATION"
        atomic_json(cycle, value)
        report = summarize(cycle)
        assert report["buckets"]["environment_seconds"] == 60
        assert report["buckets"]["governance_seconds"] == 120
        assert (
            report["phase_coverage"]["environment_governance_measurement_status"]
            == "MEASURED"
        )
        assert (
            report["ratios"]["environment_governance_share_of_attributed_active"]
            == 0.75
        )
        assert report["ratios"]["environment_governance_share_of_accounted"] == 0.75


def test_prospective_init_and_atomic_phase_switch() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        evidence = base / "evidence.json"
        evidence.write_text('{"ok": true}\n', encoding="utf-8")
        cycle = base / "cycle.json"
        created = init_ledger(
            SimpleNamespace(
                output=cycle,
                cycle_id="cycle-atomic-start",
                task_id="task-1",
                started_at="2026-09-07T04:00:00Z",
                observation_mode="PROSPECTIVE_EXACT",
                minimum_material_speedup=1.02,
                initial_phase=None,
                initial_span_id="diagnose",
                initial_actor="AGENT",
                initial_resource_id=None,
                candidate_evidence=[evidence],
            )
        )
        assert created["spans"][0]["phase"] == "BOTTLENECK_DIAGNOSIS"
        assert created["spans"][0]["status"] == "ACTIVE"
        assert created["milestones"] == [
            {
                "kind": "FIRST_CANDIDATE_PROPOSED",
                "at": "2026-09-07T04:00:00Z",
                "evidence": [identity(evidence)],
            }
        ]

        switched = switch_phase(
            SimpleNamespace(
                ledger=cycle,
                span_id="environment",
                phase="ENVIRONMENT_SETUP",
                actor="CPU",
                resource_id="worker-1",
                status="COMPLETE",
                at="2026-09-07T04:01:00Z",
                evidence=[evidence],
            )
        )
        assert switched["spans"][0]["ended_at"] == switched["spans"][1]["started_at"]
        assert switched["spans"][1]["status"] == "ACTIVE"
        end_phase(
            SimpleNamespace(
                ledger=cycle,
                span_id="environment",
                status="COMPLETE",
                at="2026-09-07T04:03:00Z",
                evidence=[evidence],
            )
        )
        report = summarize(cycle)
        assert report["wall_clock"]["unaccounted_seconds"] == 0
        assert report["buckets"]["environment_seconds"] == 120
        assert (
            report["phase_coverage"]["environment_governance_measurement_status"]
            == "MEASURED"
        )


def test_run_phase_closes_success_failure_timeout_and_launch_error() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        cycle = base / "cycle.json"
        init_ledger(
            SimpleNamespace(
                output=cycle,
                cycle_id="phase-runner",
                task_id="task",
                started_at=None,
                observation_mode="PROSPECTIVE_EXACT",
                minimum_material_speedup=1.02,
                initial_phase=None,
                initial_span_id="initial",
                initial_actor="AGENT",
                initial_resource_id=None,
            )
        )
        evidence = base / "initial.json"
        evidence.write_text('{"ok": true}\n', encoding="utf-8")
        end_phase(
            SimpleNamespace(
                ledger=cycle,
                span_id="initial",
                status="COMPLETE",
                at=None,
                evidence=[evidence],
            )
        )

        def run(span_id: str, code: str, timeout: float = 5) -> tuple[dict, int]:
            return run_phase_command(
                SimpleNamespace(
                    ledger=cycle,
                    span_id=span_id,
                    phase="ENVIRONMENT_SETUP",
                    actor="CPU",
                    resource_id=None,
                    cwd=base,
                    timeout_seconds=timeout,
                    receipt=base / f"{span_id}.json",
                    command=[sys.executable, "-c", code],
                )
            )

        passed, passed_code = run("pass", "raise SystemExit(0)")
        failed, failed_code = run("fail", "raise SystemExit(7)")
        timed_out, timeout_code = run("timeout", "import time; time.sleep(1)", 0.05)
        launch_failed, launch_code = run_phase_command(
            SimpleNamespace(
                ledger=cycle,
                span_id="launch-fail",
                phase="ENVIRONMENT_SETUP",
                actor="CPU",
                resource_id=None,
                cwd=base,
                timeout_seconds=5,
                receipt=base / "launch-fail.json",
                command=[str(base / "missing-executable")],
            )
        )
        assert passed_code == 0
        assert passed["outcome"]["status"] == "PASS"
        assert failed_code == 7
        assert failed["outcome"]["status"] == "COMMAND_FAILED"
        assert timeout_code == 124
        assert timed_out["outcome"]["status"] == "TIMED_OUT"
        assert launch_code == 127
        assert launch_failed["outcome"]["status"] == "LAUNCH_FAILED"
        recorded = validate_ledger(cycle)
        assert [span["status"] for span in recorded["spans"]] == [
            "COMPLETE",
            "COMPLETE",
            "INTERRUPTED",
            "INTERRUPTED",
            "INTERRUPTED",
        ]
        assert all(len(span["evidence"]) == 1 for span in recorded["spans"])


def test_import_phase_receipt_records_existing_machine_wall_time() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        cycle = base / "cycle.json"
        initial = base / "initial.json"
        initial.write_text('{"ok": true}\n', encoding="utf-8")
        init_ledger(
            SimpleNamespace(
                output=cycle,
                cycle_id="receipt-import",
                task_id="task",
                started_at="2026-09-07T04:00:00Z",
                observation_mode="PROSPECTIVE_EXACT",
                minimum_material_speedup=1.02,
                initial_phase=None,
                initial_span_id="initial",
                initial_actor="AGENT",
                initial_resource_id=None,
            )
        )
        end_phase(
            SimpleNamespace(
                ledger=cycle,
                span_id="initial",
                status="COMPLETE",
                at="2026-09-07T04:00:00Z",
                evidence=[initial],
            )
        )
        receipt = base / "worker-receipt.json"
        atomic_json(
            receipt,
            {
                "started_at": "2026-09-07T04:01:00Z",
                "finished_at": "2026-09-07T04:03:00Z",
                "elapsed_seconds": 120.25,
                "status": "FAILED_TERMINAL",
            },
        )
        imported = import_phase_receipt(
            SimpleNamespace(
                ledger=cycle,
                span_id="environment-1",
                phase="ENVIRONMENT_SETUP",
                actor="CPU",
                resource_id="worker-1",
                receipt=receipt,
                started_at_field="started_at",
                ended_at_field="finished_at",
                duration_field="elapsed_seconds",
                status="INTERRUPTED",
            )
        )
        span = imported["spans"][1]
        assert span["started_at"] == "2026-09-07T04:01:00Z"
        assert span["ended_at"] == "2026-09-07T04:03:00Z"
        assert span["status"] == "INTERRUPTED"
        assert span["evidence"] == [identity(receipt)]
        assert summarize(cycle)["buckets"]["environment_seconds"] == 120

        receipt.write_text('{"changed": true}\n', encoding="utf-8")
        try:
            validate_ledger(cycle)
        except ValueError as error:
            assert "evidence changed" in str(error)
        else:
            raise AssertionError("imported receipt drift must fail closed")


def test_import_phase_receipt_atomically_closes_active_phase() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        cycle = base / "cycle.json"
        init_ledger(
            SimpleNamespace(
                output=cycle,
                cycle_id="receipt-import-active",
                task_id="task",
                started_at="2026-09-07T04:00:00Z",
                observation_mode="PROSPECTIVE_EXACT",
                minimum_material_speedup=1.02,
                initial_phase="BOTTLENECK_DIAGNOSIS",
                initial_span_id="initial",
                initial_actor="AGENT",
                initial_resource_id=None,
            )
        )
        receipt = base / "worker-receipt.json"
        atomic_json(
            receipt,
            {
                "started_at": "2026-09-07T03:59:00Z",
                "finished_at": "2026-09-07T04:00:00Z",
                "elapsed_seconds": 60.0,
            },
        )
        before = cycle.read_bytes()
        args = SimpleNamespace(
            ledger=cycle,
            span_id="environment-1",
            phase="ENVIRONMENT_SETUP",
            actor="CPU",
            resource_id="worker-1",
            receipt=receipt,
            started_at_field="started_at",
            ended_at_field="finished_at",
            duration_field="elapsed_seconds",
            status="COMPLETE",
        )
        try:
            import_phase_receipt(args)
        except ValueError as error:
            assert "starts before the active phase" in str(error)
            assert cycle.read_bytes() == before
        else:
            raise AssertionError("receipt cannot precede the active phase")

        atomic_json(
            receipt,
            {
                "started_at": "2026-09-07T04:01:00Z",
                "finished_at": "2026-09-07T04:03:00Z",
                "elapsed_seconds": 120.0,
            },
        )
        imported = import_phase_receipt(args)

        assert imported["spans"][0]["status"] == "COMPLETE"
        assert imported["spans"][0]["ended_at"] == "2026-09-07T04:01:00Z"
        assert imported["spans"][0]["evidence"] == [identity(receipt)]
        assert imported["spans"][1]["started_at"] == "2026-09-07T04:01:00Z"
        assert not any(span["status"] == "ACTIVE" for span in imported["spans"])


def test_import_phase_receipt_rejects_backfill_and_duration_drift() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        cycle = base / "cycle.json"
        initial = base / "initial.json"
        initial.write_text('{"ok": true}\n', encoding="utf-8")
        init_ledger(
            SimpleNamespace(
                output=cycle,
                cycle_id="receipt-import-negative",
                task_id="task",
                started_at="2026-09-07T04:00:00Z",
                observation_mode="PROSPECTIVE_EXACT",
                minimum_material_speedup=1.02,
                initial_phase=None,
                initial_span_id="initial",
                initial_actor="AGENT",
                initial_resource_id=None,
            )
        )
        end_phase(
            SimpleNamespace(
                ledger=cycle,
                span_id="initial",
                status="COMPLETE",
                at="2026-09-07T04:00:00Z",
                evidence=[initial],
            )
        )

        def attempt(receipt_value: dict) -> str:
            receipt = base / "worker-receipt.json"
            atomic_json(receipt, receipt_value)
            before = cycle.read_bytes()
            try:
                import_phase_receipt(
                    SimpleNamespace(
                        ledger=cycle,
                        span_id="environment-1",
                        phase="ENVIRONMENT_SETUP",
                        actor="CPU",
                        resource_id=None,
                        receipt=receipt,
                        started_at_field="started_at",
                        ended_at_field="finished_at",
                        duration_field="elapsed_seconds",
                        status="INTERRUPTED",
                    )
                )
            except ValueError as error:
                assert cycle.read_bytes() == before
                return str(error)
            raise AssertionError("invalid receipt import must fail")

        assert "duration conflicts" in attempt(
            {
                "started_at": "2026-09-07T04:01:00Z",
                "finished_at": "2026-09-07T04:03:00Z",
                "elapsed_seconds": 1,
            }
        )
        assert "span starts before cycle" in attempt(
            {
                "started_at": "2026-09-07T03:59:00Z",
                "finished_at": "2026-09-07T04:00:00Z",
                "elapsed_seconds": 60,
            }
        )


def test_candidate_evidence_bootstrap_fails_without_partial_ledger() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        cycle = base / "cycle.json"
        missing = base / "missing-decision.json"
        args = SimpleNamespace(
            output=cycle,
            cycle_id="candidate-cycle",
            task_id="lane-task",
            started_at=None,
            observation_mode="PROSPECTIVE_EXACT",
            minimum_material_speedup=1.02,
            candidate_evidence=[missing],
            initial_phase=None,
            initial_span_id="diagnose",
            initial_actor="AGENT",
            initial_resource_id=None,
        )
        try:
            init_ledger(args)
        except FileNotFoundError:
            pass
        else:
            raise AssertionError("missing candidate evidence must fail")
        assert not cycle.exists()

        evidence = base / "decision.json"
        evidence.write_text("{}\n", encoding="utf-8")
        args.candidate_evidence = [evidence]
        args.observation_mode = "LEGACY_MILESTONE_BOUNDS"
        try:
            init_ledger(args)
        except ValueError as error:
            assert "PROSPECTIVE_EXACT" in str(error)
        else:
            raise AssertionError("legacy cycles cannot bootstrap exact selection time")
        assert not cycle.exists()


def test_pr_stage_is_atomic_and_fail_closed() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        evidence = base / "github-event.json"
        evidence.write_text('{"state": "draft"}\n', encoding="utf-8")
        cycle = base / "cycle.json"
        value = ledger(evidence)
        atomic_json(cycle, value)

        record_pr_stage(
            SimpleNamespace(
                ledger=cycle,
                stage="DRAFT",
                url="https://github.com/example/project/pull/7",
                at="2026-09-07T04:05:00Z",
                evidence=[evidence],
            )
        )
        recorded = validate_ledger(cycle)
        assert recorded["outcome"]["pull_request_url"].endswith("/pull/7")
        assert recorded["milestones"][-1]["kind"] == "PR_DRAFT_OPENED"

        record_pr_stage(
            SimpleNamespace(
                ledger=cycle,
                stage="READY",
                url="https://github.com/example/project/pull/7",
                at="2026-09-07T04:06:00Z",
                evidence=[evidence],
            )
        )
        recorded = validate_ledger(cycle)
        assert recorded["milestones"][-1]["kind"] == "PR_READY_FOR_REVIEW"

        original = cycle.read_bytes()
        try:
            record_pr_stage(
                SimpleNamespace(
                    ledger=cycle,
                    stage="MERGED",
                    url="https://github.com/example/project/pull/8",
                    at="2026-09-07T04:07:00Z",
                    evidence=[evidence],
                )
            )
        except ValueError as error:
            assert "URL changed" in str(error)
        else:
            raise AssertionError("one work cycle must not switch pull requests")
        assert cycle.read_bytes() == original

        record_pr_stage(
            SimpleNamespace(
                ledger=cycle,
                stage="MERGED",
                url="https://github.com/example/project/pull/7",
                at="2026-09-07T04:07:00Z",
                evidence=[evidence],
            )
        )
        recorded = validate_ledger(cycle)
        assert recorded["outcome"]["merged"] is True
        assert recorded["milestones"][-1]["kind"] == "PR_MERGED"

        without_draft = base / "without-draft.json"
        atomic_json(without_draft, value)
        try:
            record_pr_stage(
                SimpleNamespace(
                    ledger=without_draft,
                    stage="READY",
                    url="https://github.com/example/project/pull/9",
                    at="2026-09-07T04:06:00Z",
                    evidence=[evidence],
                )
            )
        except ValueError as error:
            assert "PR_DRAFT_OPENED" in str(error)
        else:
            raise AssertionError("READY must not invent a missing Draft event")


def test_pr_stage_atomically_closes_only_an_external_wait() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        evidence = base / "github-event.json"
        evidence.write_text('{"state": "draft"}\n', encoding="utf-8")
        cycle = base / "cycle.json"
        value = ledger(evidence)
        value["spans"].append(
            {
                "span_id": "publish-wait",
                "phase": "EXTERNAL_WAIT",
                "actor": "EXTERNAL",
                "resource_id": "USER_BROWSER_CONFIRMATION",
                "started_at": "2026-09-07T04:04:00Z",
                "ended_at": None,
                "status": "ACTIVE",
                "evidence": [],
            }
        )
        atomic_json(cycle, value)

        before = cycle.read_bytes()
        try:
            record_pr_stage(
                SimpleNamespace(
                    ledger=cycle,
                    stage="DRAFT",
                    url="https://github.com/example/project/pull/7",
                    at="2026-09-07T04:03:59Z",
                    evidence=[evidence],
                )
            )
        except ValueError as error:
            assert "precedes the active external wait" in str(error)
            assert cycle.read_bytes() == before
        else:
            raise AssertionError("PR event cannot precede its external wait")

        recorded = record_pr_stage(
            SimpleNamespace(
                ledger=cycle,
                stage="DRAFT",
                url="https://github.com/example/project/pull/7",
                at="2026-09-07T04:05:00Z",
                evidence=[evidence],
            )
        )
        wait = recorded["spans"][-1]
        assert wait["status"] == "COMPLETE"
        assert wait["ended_at"] == "2026-09-07T04:05:00Z"
        assert wait["evidence"] == [identity(evidence)]

        active_cycle = base / "active-work.json"
        active_value = ledger(evidence)
        active_value["spans"].append(
            {
                "span_id": "qualification",
                "phase": "PERFORMANCE_VALIDATION",
                "actor": "GPU",
                "resource_id": "worker-1",
                "started_at": "2026-09-07T04:04:00Z",
                "ended_at": None,
                "status": "ACTIVE",
                "evidence": [],
            }
        )
        atomic_json(active_cycle, active_value)
        recorded = record_pr_stage(
            SimpleNamespace(
                ledger=active_cycle,
                stage="DRAFT",
                url="https://github.com/example/project/pull/8",
                at="2026-09-07T04:05:00Z",
                evidence=[evidence],
            )
        )
        assert recorded["spans"][-1]["status"] == "ACTIVE"


def test_pair_baseline_reads_bound_assessments() -> None:
    pair = (
        ROOT.parent
        / "community-validation/temporal-unseen-2026-09-07/run-v3/paired-r1.json"
    )
    if not pair.is_file():
        return
    report = pair_baseline([pair])
    assert report["pair_count"] == 1
    assert report["arm_medians"]["control"]["elapsed_seconds"] > 0
    assert (
        report["arm_medians"]["community_augmented"][
            "time_to_first_improvement_seconds"
        ]
        > 0
    )


def test_audit_roots_reports_live_timing_blind_spots() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        tracked_path = base / "tracked.json"
        tracked = init_ledger(
            SimpleNamespace(
                output=tracked_path,
                cycle_id="tracked-cycle",
                task_id="lane-a",
                started_at="2026-09-07T04:00:00Z",
                observation_mode="PROSPECTIVE_EXACT",
                minimum_material_speedup=1.02,
                initial_phase="ENVIRONMENT_SETUP",
                initial_span_id="environment",
                initial_actor="CPU",
                initial_resource_id=None,
            )
        )
        assert tracked["spans"]

        blind_path = base / "blind.json"
        blind = init_ledger(
            SimpleNamespace(
                output=blind_path,
                cycle_id="blind-cycle",
                task_id="lane-b",
                started_at="2026-09-07T04:00:00Z",
                observation_mode="PROSPECTIVE_EXACT",
                minimum_material_speedup=1.02,
                initial_phase=None,
                initial_span_id="initial",
                initial_actor="AGENT",
                initial_resource_id=None,
            )
        )
        blind["spans"] = []
        atomic_json(blind_path, blind)

        report = audit_roots(
            [base], at="2026-09-07T12:00:01Z", max_active_phase_seconds=3600
        )
        assert report["status"] == "PARTIAL"
        assert report["prospective_cycle_count"] == 2
        assert report["exact_phase_tracked_count"] == 1
        assert report["explicit_environment_governance_count"] == 1
        assert report["environment_governance_measurement_status"] == "PARTIAL"
        rows = {row["cycle_id"]: row for row in report["cycles"]}
        assert rows["tracked-cycle"]["active_phase"] == "ENVIRONMENT_SETUP"
        assert "ACTIVE_PHASE_OVER_THRESHOLD" in rows["tracked-cycle"]["alerts"]
        assert "NO_EXACT_PHASE_ATTRIBUTION" in rows["blind-cycle"]["alerts"]
        assert "NO_PRIMARY_PHASE" in rows["blind-cycle"]["alerts"]


def test_audit_roots_reports_invalid_ledgers_without_hiding_valid_ones() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        evidence = base / "evidence.json"
        evidence.write_text('{"ok": true}\n', encoding="utf-8")
        valid_path = base / "valid.json"
        atomic_json(valid_path, ledger(evidence))
        invalid_path = base / "invalid.json"
        invalid = ledger(evidence)
        invalid["spans"][0]["evidence"][0]["sha256"] = "0" * 64
        atomic_json(invalid_path, invalid)

        report = audit_roots([base], at="2026-09-07T05:00:00Z")
        assert report["prospective_cycle_count"] == 1
        assert report["invalid_ledger_count"] == 1
        assert report["invalid_ledgers"][0]["path"].endswith("invalid.json")


def test_seal_evidence_preserves_content_addressed_history() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        source = base / "status.json"
        store = base / "sealed"
        source.write_text('{"state": "draft"}\n', encoding="utf-8")

        first = seal_evidence(source, store)
        first_path = Path(first["sealed"]["path"])
        assert first["created"] is True
        assert first_path.read_bytes() == source.read_bytes()
        assert first_path.name == f"{first['sealed']['sha256']}.json"

        repeated = seal_evidence(source, store)
        assert repeated["created"] is False
        assert repeated["sealed"] == first["sealed"]

        source.write_text('{"state": "ci-complete"}\n', encoding="utf-8")
        second = seal_evidence(source, store)
        second_path = Path(second["sealed"]["path"])
        assert second["created"] is True
        assert second_path != first_path
        assert first_path.read_text(encoding="utf-8") == '{"state": "draft"}\n'
        assert second_path.read_bytes() == source.read_bytes()


def test_seal_evidence_rejects_corrupted_content_addressed_target() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        source = base / "receipt.json"
        store = base / "sealed"
        source.write_text('{"ok": true}\n', encoding="utf-8")
        digest = sha256_file(source)
        target = store / digest[:2] / f"{digest}.json"
        target.parent.mkdir(parents=True)
        target.write_text('{"ok": false}\n', encoding="utf-8")

        try:
            seal_evidence(source, store)
        except ValueError as error:
            assert "corrupted" in str(error)
        else:
            raise AssertionError("corrupted sealed evidence was accepted")


if __name__ == "__main__":
    test_work_cycle_summary_and_guards()
    test_environment_and_governance_overhead_reporting()
    test_prospective_init_and_atomic_phase_switch()
    test_run_phase_closes_success_failure_timeout_and_launch_error()
    test_import_phase_receipt_records_existing_machine_wall_time()
    test_import_phase_receipt_atomically_closes_active_phase()
    test_import_phase_receipt_rejects_backfill_and_duration_drift()
    test_pr_stage_is_atomic_and_fail_closed()
    test_pr_stage_atomically_closes_only_an_external_wait()
    test_pair_baseline_reads_bound_assessments()
    test_audit_roots_reports_live_timing_blind_spots()
    test_audit_roots_reports_invalid_ledgers_without_hiding_valid_ones()
    test_seal_evidence_preserves_content_addressed_history()
    test_seal_evidence_rejects_corrupted_content_addressed_target()
