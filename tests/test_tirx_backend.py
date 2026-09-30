"""Exercise candidate rejection separately from runtime/coverage failures."""
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import tirx_backend as backend


class Report:
    def __init__(self, verdict):
        self.verdict = verdict

    def to_dict(self):
        return {"verdict": self.verdict, "findings": []}


def runtime(verdict="clean", output=None, fail=False, simulation_verdict="clean", diagnostics=None):
    calls = []

    def checker(kernel, inputs):
        if fail:
            raise NotImplementedError("unsupported modeled operation")
        # Checkers may mutate buffers. The next stage must get fresh inputs.
        calls.append(float(inputs["out"][0]))
        inputs["out"][0] = 999
        return Report(verdict)

    def run(module, inputs, outputs):
        calls.append(float(inputs["out"][0]))
        return SimpleNamespace(outputs={"out": output if output is not None else np.array([3.0])},
                               diagnostics=[] if diagnostics is None else diagnostics, verdict=simulation_verdict)

    return SimpleNamespace(synccheck=checker, racecheck=checker,
                           numsim=SimpleNamespace(transpile=lambda *a, **k: "compiled",
                                                  Engine=lambda **k: SimpleNamespace(run=run))), calls


def case():
    return {"kernel": object(), "inputs": {"out": np.zeros(1)},
            "expected": {"out": np.array([3.0])}, "rtol": 0, "atol": 0}


def test_clean_numerical_pass_uses_independent_inputs(tmp_path):
    harness, calls = runtime()
    data = case()
    result = backend.evaluate(data, np, harness, tmp_path)
    assert result["status"] == "PASS"
    assert calls == [0, 0, 0]
    assert data["inputs"]["out"][0] == 0


@pytest.mark.parametrize("output", [np.array([4.0]), np.array([np.nan]), np.array([np.inf]), np.array([[3.0]])])
def test_wrong_nonfinite_or_wrong_shape_is_rejected(tmp_path, output):
    harness, _ = runtime(output=output)
    result = backend.evaluate(case(), np, harness, tmp_path)
    assert result["status"] == "FAIL"
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("actual,reference", [
    (np.array([2**60 + 1], dtype=np.int64), np.array([2**60], dtype=np.int64)),
    (np.array([2**64 - 1], dtype=np.uint64), np.array([2**64 - 2], dtype=np.uint64)),
    (np.array([2**63], dtype=np.uint64), np.array([2**63 - 1], dtype=np.int64)),
    (np.array([True]), np.array([False])),
])
def test_integer_and_boolean_outputs_are_exact_without_lossy_casts(tmp_path, actual, reference):
    harness, _ = runtime(output=actual)
    data = case()
    data["expected"]["out"] = reference
    result = backend.evaluate(data, np, harness, tmp_path)
    assert result["status"] == "FAIL"
    assert result["checks"]["numerical"]["outputs"]["out"]["max_abs_error"] == 1
    json.dumps(result, allow_nan=False)


def test_equal_large_integer_values_pass_and_tolerance_cannot_hide_integer_errors(tmp_path):
    data = case()
    data["expected"]["out"] = np.array([2**60], dtype=np.int64)
    data["rtol"] = data["atol"] = 1
    matching, _ = runtime(output=data["expected"]["out"].copy())
    assert backend.evaluate(data, np, matching, tmp_path)["status"] == "PASS"
    different, _ = runtime(output=np.array([2**60 + 1], dtype=np.int64))
    assert backend.evaluate(data, np, different, tmp_path)["status"] == "FAIL"


def test_float_tolerance_is_preserved(tmp_path):
    harness, _ = runtime(output=np.array([3.01]))
    data = case()
    data["atol"] = 0.02
    assert backend.evaluate(data, np, harness, tmp_path)["status"] == "PASS"


@pytest.mark.parametrize("verdict", ["review", "incomplete", "unexpected", None])
def test_numerical_match_does_not_hide_simulator_coverage_review(tmp_path, verdict):
    diagnostics = [{"status": "review", "kind": "model_advisory"}]
    harness, _ = runtime(simulation_verdict=verdict, diagnostics=diagnostics)
    result = backend.evaluate(case(), np, harness, tmp_path)
    assert result["status"] == "ERROR"
    assert result["checks"]["numerical"]["status"] == "PASS"
    assert result["checks"]["simulation"]["verdict"] == verdict
    assert result["checks"]["simulation"]["diagnostics"] == diagnostics


@pytest.mark.parametrize("verdict,status", [("error", "FAIL"), ("unknown", "ERROR")])
def test_checker_findings_or_incomplete_analysis_skip_simulation(tmp_path, verdict, status):
    harness, calls = runtime(verdict=verdict)
    result = backend.evaluate(case(), np, harness, tmp_path)
    assert result["status"] == status
    assert result["checks"]["numerical"]["status"] == "SKIPPED"
    assert len(calls) == 2


def test_unsupported_operation_is_error_not_candidate_rejection(tmp_path):
    harness, _ = runtime(fail=True)
    result = backend.evaluate(case(), np, harness, tmp_path)
    assert result["status"] == "ERROR"
    assert "unsupported" in result["checks"]["synccheck"]["error"]


def test_no_reference_or_invalid_tolerance_cannot_pass(tmp_path):
    harness, _ = runtime()
    data = case()
    data["expected"] = {}
    with pytest.raises(ValueError):
        backend.evaluate(data, np, harness, tmp_path)
    data = case()
    data["atol"] = float("inf")
    with pytest.raises(ValueError):
        backend.evaluate(data, np, harness, tmp_path)


def test_probe_and_public_cli_do_not_require_harness():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, "-B", str(root / "scripts/kernel_opt.py"), "tirx", "probe"],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "tirx-harness" in json.loads(result.stdout)["versions"]


def test_timeout_clears_old_pass_and_stops_only_own_process(tmp_path, monkeypatch):
    source = tmp_path / "case.py"
    source.write_text("# trusted case", encoding="utf-8")
    output = tmp_path / "result.json"
    output.write_text('{"status":"PASS"}', encoding="utf-8")
    killed = []

    class Process:
        pid = 12345

        def wait(self, timeout=None):
            if timeout is not None:
                raise subprocess.TimeoutExpired("test worker", timeout)
            return -9

    monkeypatch.setattr(backend.subprocess, "Popen", lambda *a, **k: Process())
    if backend.os.name == "nt":
        monkeypatch.setattr(backend.subprocess, "run", lambda cmd, **k: killed.append(cmd))
    else:
        monkeypatch.setattr(backend.os, "killpg", lambda pid, sig: killed.append(pid))
    args = SimpleNamespace(output=output, case_file=source, cache_dir=None, case=["valid"], timeout=1)
    assert backend.bounded_check(args) == 2
    assert json.loads(output.read_text())["status"] == "ERROR"
    assert killed
