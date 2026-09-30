"""Feedback integration is offline and cannot promote a case to PR Ready."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import tirx_feedback as feedback
import worklog


def saved(tmp_path, status="PASS", inspection=False):
    source = tmp_path / "case.py"
    source.write_text("raise RuntimeError('must not execute')\n", encoding="utf-8")
    result = {
        "status": status, "case_file": str(source), "source_unchanged": True,
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "scope": "Compiler artifacts only; no GPU execution" if inspection else "CPU concrete-input checks; no GPU correctness",
        "cases": {"valid": {"status": status, "checks": {
            "simulation": {"status": status, "verdict": "clean"},
            "numerical": {"status": status, "outputs": {"out": {"status": status, "max_abs_error": 0}}},
        }}},
    }
    path = tmp_path / "result.json"
    path.write_text(json.dumps(result), encoding="utf-8")
    return source, path, result


def store(path, result):
    path.write_text(json.dumps(result), encoding="utf-8")


def test_public_cli_is_read_only_without_harness_and_keeps_pending_device_checks(tmp_path):
    source, path, _ = saved(tmp_path)
    before = path.read_bytes(), source.read_bytes()
    command = [sys.executable, "-B", str(Path(feedback.__file__).with_name("kernel_opt.py")),
               "tirx", "summarize", "--result", str(path)]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
    brief = json.loads(result.stdout)
    assert brief["local_source_check"] == "MATCH"
    assert "device outputs" in brief["next_check"]
    assert "No GPU correctness" in brief["boundary"]
    assert before == (path.read_bytes(), source.read_bytes())
    assert brief["evidence"]["sha256"] == hashlib.sha256(before[0]).hexdigest()


def test_errors_and_source_drift_are_not_accepted_or_candidate_rejections(tmp_path):
    source, path, result = saved(tmp_path, "ERROR")
    result["cases"]["valid"]["checks"]["simulation"] = {
        "status": "ERROR", "verdict": "review", "diagnostics": [{"kind": "unsupported"}],
    }
    store(path, result)
    brief = feedback.summarize(path)
    assert brief["cases"][0]["checks"]["simulation"]["verdict"] == "review"
    assert "do not establish a candidate defect" in brief["next_check"]
    source.write_text("# changed", encoding="utf-8")
    assert feedback.summarize(path)["local_source_check"] == "CHANGED"
    assert "Source changed" in feedback.summarize(path)["next_check"]
    source.unlink()
    assert feedback.summarize(path)["local_source_check"] == "UNAVAILABLE"


def test_failure_details_survive_bounded_context_and_large_integer_errors(tmp_path):
    _, path, result = saved(tmp_path, "FAIL")
    result["cases"] = {str(i): {"status": "PASS"} for i in range(30)}
    result["cases"]["wrong"] = {"status": "FAIL", "checks": {
        "racecheck": {"status": "FAIL", "report": {"findings": [{"kind": "data_race", "details": "X" * 100000}] * 5}},
        "numerical": {"status": "FAIL", "outputs": {"out": {"status": "FAIL", "max_abs_error": 2**64 - 1}}},
    }}
    store(path, result)
    brief = feedback.summarize(path)
    assert brief["case_counts"] == {"PASS": 30, "FAIL": 1}
    assert brief["cases"][0]["name"] == "wrong"
    assert brief["cases_omitted"] == 25
    race = brief["cases"][0]["checks"]["racecheck"]
    assert race["findings_omitted"] == 2
    assert "data_race" in race["findings"][0]
    assert brief["cases"][0]["checks"]["numerical"]["outputs"][0]["max_abs_error"] == 2**64 - 1
    assert len(json.dumps(brief)) < 5000


def test_inspection_and_correctness_link_raw_evidence_without_changing_decision(tmp_path):
    run = tmp_path / "run"
    worklog.execute(SimpleNamespace(action="init", run=run, objective="Real operator",
                                    source="upstream commit", workload="actual shapes", hardware="target GPU"))
    worklog.execute(SimpleNamespace(action="record", run=run, kind="decision", summary="pending",
                                    source=None, workload=None, hardware=None, status="INCONCLUSIVE", pr=None,
                                    evidence=None, command=None, candidate=None, family=None, latency_us=None))
    _, path, result = saved(tmp_path, inspection=True)
    result["cases"] = {"kernel": {"status": "PASS", "arch": "sm_103a", "ptxas": {"registers": 12}, "errors": []}}
    store(path, result)
    brief = feedback.summarize(path)
    assert brief["cases"][0]["reported_resources"] == {"registers": 12}
    assert "not the loaded binary" in brief["next_check"]
    assert feedback.record(run, brief, "saved inspection")["status"] == "INCONCLUSIVE"
    state = worklog.read_run(run / "run.json")
    assert state["records"][-1]["kind"] == "inspection"
    assert state["records"][-1]["evidence"] == brief["evidence"]
    assert state["hardware"] == "target GPU"
    assert not state["records"][-1]["pr"]
    _, path, _ = saved(tmp_path)
    feedback.record(run, feedback.summarize(path), "saved check")
    state = worklog.read_run(run / "run.json")
    assert state["records"][-1]["kind"] == "correctness"
    assert state["status"] == "INCONCLUSIVE"


@pytest.mark.parametrize("content", ['{"status":"PASS","status":"FAIL"}',
                                     '{"status":"PASS","scope":"GPU performance"}',
                                     '{"status":"PASS","scope":NaN}', '[]'])
def test_malformed_or_foreign_results_are_not_reinterpreted(tmp_path, content):
    path = tmp_path / "result.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError):
        feedback.summarize(path)


def test_parent_timeout_and_running_records_remain_incomplete(tmp_path):
    path = tmp_path / "result.json"
    store(path, {"status": "ERROR", "reason": "timeout", "cases": ["valid"]})
    brief = feedback.summarize(path)
    assert brief["mode"] == "execution_incomplete"
    assert brief["reason"] == "timeout"
    assert brief["cases"] == []


def test_changed_raw_result_is_not_linked_under_a_stale_summary(tmp_path):
    _, path, _ = saved(tmp_path)
    brief = feedback.summarize(path)
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="changed after"):
        feedback.record(tmp_path / "unused", brief, "summary")
    assert not (tmp_path / "unused").exists()


def test_cli_success_summarizes_failure_without_promoting_it(tmp_path):
    _, path, _ = saved(tmp_path, "FAIL")
    result = subprocess.run([sys.executable, "-B", str(Path(feedback.__file__).with_name("tirx_backend.py")),
                             "summarize", "--result", str(path)],
                            capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["declared_status"] == "FAIL"


def test_bounded_read_does_not_accept_oversized_result(tmp_path, monkeypatch):
    _, path, _ = saved(tmp_path)
    monkeypatch.setattr(feedback, "MAX_RESULT_BYTES", 3)
    with pytest.raises(ValueError, match="exceeds"):
        feedback.summarize(path)


def test_native_race_sites_survive_long_messages_without_recursive_payloads(tmp_path):
    _, path, result = saved(tmp_path, "FAIL")
    def access(lane):
        return {"lane": lane, "operation": {"source_op_id": 13, "source": {
            "source_text": 'output[0] = lane',
            "source_span": {"source_name": "affine_cases.py", "line": 19,
                            "column": 5, "end_line": 19, "end_column": 21},
        }}}
    finding = {"kind": "data_race", "message": "unordered write/write " * 100,
               "details": {"ordering_domain": "execution",
                           "ordering_failure": "missing_same_warp_lane_order",
                           "access_pair": "write_write", "prior": access(10),
                           "current": access(18), "unrelated_trace": "x" * 100000}}
    result["cases"]["valid"]["checks"]["racecheck"] = {
        "status": "FAIL", "report": {"findings": [finding]}}
    store(path, result)
    brief = feedback.summarize(path)
    race = brief["cases"][0]["checks"]["racecheck"]
    assert 'affine_cases.py' not in race["findings"][0]
    context = race["findings_context"][0]
    assert context["ordering_failure"] == "missing_same_warp_lane_order"
    assert [(site["role"], site["lane"], site["line"]) for site in
            context["source_sites"]] == [("prior", 10, 19), ("current", 18, 19)]
    assert context["source_sites"][0]["source_excerpt"] == "output[0] = lane"
    assert "unrelated_trace" not in json.dumps(brief)
    assert len(json.dumps(brief)) < 5000
    assert brief["declared_status"] == "FAIL"


def test_sync_operation_sites_and_unknown_shapes_remain_partial():
    context = feedback.finding_context({"details": {
        "effect": "mbarrier.arrive", "operation": {"source_op_id": 25,
        "source": {"source_span": {"line": 29, "column": 9},
                   "source_text": "x" * 1000}},
    }})
    assert context["effect"] == "mbarrier.arrive"
    assert context["source_sites"][0]["line"] == 29
    assert len(context["source_sites"][0]["source_excerpt"]) == 240
    for unknown in ("text report", {"details": []}, {"details": {"operation": []}}):
        assert feedback.finding_context(unknown) == {}
