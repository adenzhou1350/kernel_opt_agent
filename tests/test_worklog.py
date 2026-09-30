"""Portable tests for the standalone run notebook (no governance dependencies)."""

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "worklog.py"
SPEC = importlib.util.spec_from_file_location("worklog", SCRIPT)
worklog = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(worklog)


class WorklogTests(unittest.TestCase):
    def candidate(self, name, family, latency, **kwargs):
        source = self.evidence(name + '.py', b'# complete candidate\n')
        evidence = self.evidence(name + '.json', b'{"correctness":"PASS"}\n')
        arguments = ['record', '--kind', 'decision', '--status', kwargs.get('status', 'ACCEPT'),
                     '--summary', 'Measured candidate', '--candidate', str(source), '--family', family,
                     '--latency-us', str(latency), '--evidence', str(evidence)]
        for key in ('workload', 'hardware'):
            if key in kwargs:
                arguments += ['--' + key, kwargs[key]]
        self.cli(*arguments)
        return source, evidence

    def test_frontier_retains_distinct_mechanisms_and_separates_context(self):
        self.initialize('--workload', 'FP32 N32 exact event settings', '--hardware', 'GPU A runtime X')
        self.candidate('fast', 'vectorized', 9)
        self.candidate('redundant', 'vectorized', 11)
        self.candidate('different', 'persistent', 13)
        self.candidate('other_shape', 'vectorized', 3, workload='FP32 N64 exact event settings')
        before = self.path.read_bytes()
        result = self.cli('frontier')
        self.assertEqual(len(result['groups']), 2)
        members = result['groups'][0]['members']
        self.assertEqual([m['family'] for m in members], ['vectorized', 'persistent'])
        self.assertEqual([m['latency_us'] for m in members], [9, 13])
        self.assertEqual(self.path.read_bytes(), before)

    def test_frontier_drops_stale_evidence_and_withdrawn_candidate(self):
        self.initialize('--workload', 'contract', '--hardware', 'device/settings')
        source, _ = self.candidate('source_changed', 'tiled', 9)
        source.write_text('# different source', encoding='utf-8')
        _, evidence = self.candidate('result_changed', 'persistent', 10)
        evidence.write_text('changed', encoding='utf-8')
        source2, _ = self.candidate('withdrawn', 'vectorized', 7)
        self.cli('record', '--kind', 'decision', '--status', 'REJECT', '--summary', 'Held-out failure',
                 '--candidate', str(source2), '--family', 'vectorized')
        result = self.cli('frontier')
        self.assertEqual(result['groups'], [])
        self.assertEqual([item['reason'] for item in result['excluded']],
                         ['source or evidence changed', 'source or evidence changed', 'REJECT'])

    def test_candidate_admission_requires_finite_measurement_and_known_context(self):
        self.initialize()
        source = self.evidence('candidate.py')
        evidence = self.evidence('results.json')
        arguments = ['--kind', 'decision', '--status', 'ACCEPT', '--summary', 'candidate',
                     '--candidate', str(source), '--family', 'tiled', '--evidence', str(evidence)]
        original = self.path.read_bytes()
        self.cli('record', *arguments, '--latency-us', '1', expected=2)
        for latency in ('nan', 'inf', '0', '-1'):
            self.cli('record', *arguments, '--latency-us', latency,
                     '--workload', 'contract', '--hardware', 'device', expected=2)
        self.cli('record', *arguments, '--workload', 'contract', '--hardware', 'device', expected=2)
        self.assertEqual(self.path.read_bytes(), original)

    def test_public_cli_help_forwarding_and_exit_status(self):
        public = SCRIPT.with_name("kernel_opt.py")
        help_result = subprocess.run(
            [sys.executable, "-B", str(public), "worklog", "init", "--help"],
            text=True,
            encoding="utf-8",
            capture_output=True,
        )
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        self.assertIn("--objective", help_result.stdout)
        failure = subprocess.run(
            [
                sys.executable,
                "-B",
                str(public),
                "worklog",
                "status",
                "--run",
                str(self.run),
            ],
            text=True,
            encoding="utf-8",
            capture_output=True,
        )
        self.assertEqual(failure.returncode, 2)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.run = self.root / "a run"
        self.path = self.run / "run.json"

    def cli(self, action, *arguments, expected=0):
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                str(SCRIPT),
                action,
                "--run",
                str(self.run),
                *arguments,
            ],
            cwd=self.root,
            text=True,
            encoding="utf-8",
            capture_output=True,
        )
        self.assertEqual(result.returncode, expected, result.stderr)
        return json.loads(result.stdout) if expected == 0 else result

    def initialize(self, *arguments):
        return self.cli("init", "--objective", "Reduce decode latency", *arguments)

    def evidence(self, name="timing.txt", content=b"baseline_us=11\ncandidate_us=9\n"):
        path = self.root / name
        path.write_bytes(content)
        return path

    def test_unknown_context_and_no_overwrite(self):
        state = self.initialize()
        self.assertEqual(state["status"], "OPEN")
        self.assertEqual(state["records"], [])
        self.assertEqual([state[field] for field in worklog.CONTEXT], ["UNKNOWN"] * 3)
        self.assertEqual(state["created_at"], state["updated_at"])
        self.assertEqual(list(self.run.iterdir()), [self.path])
        original = self.path.read_bytes()
        result = self.initialize_again()
        self.assertIn("already exists", result.stderr)
        self.assertEqual(original, self.path.read_bytes())

    def initialize_again(self):
        return self.cli("init", "--objective", "Different objective", expected=2)

    def test_explicit_empty_initial_context_is_rejected(self):
        self.cli("init", "--objective", "A valid objective", "--source", "", expected=2)
        self.assertFalse(self.run.exists())

    def test_cli_end_to_end_preserves_context_and_literal_command(self):
        self.initialize("--source", "upstream abc123", "--workload", "batch 1 decode")
        artifact = self.evidence()
        command = "python benchmark.py; touch SHOULD_NOT_EXIST"
        baseline = self.cli(
            "record",
            "--kind",
            "baseline",
            "--summary",
            "11 us",
            "--evidence",
            artifact.name,
            "--command",
            command,
        )
        self.assertEqual(baseline["status"], "OPEN")
        entry = baseline["records"][0]
        self.assertEqual(entry["command"], command)
        self.assertEqual(
            entry["evidence"],
            {
                "path": str(artifact),
                "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
            },
        )
        self.assertFalse((self.root / "SHOULD_NOT_EXIST").exists())
        correctness = self.evidence("test.log", b"all focused tests passed\n")
        self.cli(
            "record",
            "--kind",
            "correctness",
            "--summary",
            "focused cases passed",
            "--evidence",
            str(correctness),
            "--hardware",
            "CPU test host",
        )
        self.cli(
            "record",
            "--kind",
            "performance",
            "--summary",
            "local candidate 9 us",
            "--evidence",
            str(artifact),
            "--hardware",
            "lab device, exact setup in log",
        )
        decision = self.cli(
            "record",
            "--kind",
            "decision",
            "--summary",
            "candidate worth review",
            "--status",
            "ACCEPT",
            "--pr",
            "https://example.org/pull/17",
        )
        self.assertEqual(decision["status"], "ACCEPT")
        self.assertEqual(decision["records"][0]["context"]["hardware"], "UNKNOWN")
        self.assertEqual(decision["records"][1]["context"]["hardware"], "CPU test host")
        self.assertEqual(decision["source"], "upstream abc123")
        self.assertEqual(decision["workload"], "batch 1 decode")
        self.assertEqual(decision["records"][-1]["pr"], "https://example.org/pull/17")
        summary = self.cli("status")
        self.assertEqual(
            [check["status"] for check in summary["evidence_checks"]], ["MATCH"] * 3
        )
        self.assertIn("not automatic PR readiness", summary["note"])
        self.assertNotIn(
            "evidence_checks", json.loads(self.path.read_text(encoding="utf-8"))
        )

    def test_status_detects_changed_and_missing_evidence_without_rewriting_judgment(
        self,
    ):
        self.initialize()
        artifact = self.evidence()
        self.cli(
            "record",
            "--kind",
            "performance",
            "--summary",
            "results",
            "--evidence",
            str(artifact),
        )
        self.cli(
            "record",
            "--kind",
            "decision",
            "--summary",
            "too noisy",
            "--status",
            "INCONCLUSIVE",
        )
        original = self.path.read_bytes()
        artifact.write_bytes(b"edited after capture")
        self.assertEqual(self.cli("status")["evidence_checks"][0]["status"], "CHANGED")
        artifact.unlink()
        state = self.cli("status")
        self.assertEqual(state["evidence_checks"][0]["status"], "MISSING")
        self.assertEqual(state["status"], "INCONCLUSIVE")
        self.assertEqual(original, self.path.read_bytes())

    def test_decision_note_does_not_invent_a_verdict(self):
        self.initialize()
        self.assertEqual(
            self.cli("record", "--kind", "decision", "--summary", "GPU unavailable")[
                "status"
            ],
            "OPEN",
        )
        self.cli(
            "record",
            "--kind",
            "decision",
            "--summary",
            "no material gain",
            "--status",
            "REJECT",
        )
        self.assertEqual(
            self.cli("record", "--kind", "decision", "--summary", "saved notes")[
                "status"
            ],
            "REJECT",
        )

    def test_invalid_record_arguments_do_not_change_notebook(self):
        self.initialize()
        artifact = self.evidence()
        original = self.path.read_bytes()
        cases = [
            ("--kind", "baseline", "--summary", "no evidence"),
            ("--kind", "correctness", "--summary", "no evidence"),
            ("--kind", "performance", "--summary", "no evidence"),
            ("--kind", "decision", "--summary", " "),
            ("--kind", "decision", "--summary", "note", "--hardware", " "),
            ("--kind", "decision", "--summary", "note", "--command", ""),
            ("--kind", "decision", "--summary", "note", "--status", "READY"),
            ("--kind", "decision", "--summary", "note", "--pr", "not-a-url"),
            (
                "--kind",
                "baseline",
                "--summary",
                "note",
                "--evidence",
                str(artifact),
                "--status",
                "ACCEPT",
            ),
            (
                "--kind",
                "baseline",
                "--summary",
                "note",
                "--evidence",
                str(artifact),
                "--pr",
                "https://example.org/1",
            ),
            ("--kind", "decision", "--summary", "note", "--evidence", str(self.path)),
            ("--kind", "decision", "--summary", "note", "--evidence", "missing.log"),
        ]
        for arguments in cases:
            with self.subTest(arguments=arguments):
                self.cli("record", *arguments, expected=2)
                self.assertEqual(original, self.path.read_bytes())

    def test_corrupt_notebooks_are_rejected_without_repair_or_overwrite(self):
        initial = self.initialize()
        good_record = {
            "kind": "decision",
            "summary": "note",
            "at": initial["created_at"],
            "context": {field: "UNKNOWN" for field in worklog.CONTEXT},
            "status": None,
            "evidence": None,
            "pr": None,
            "command": None,
        }
        corrupt = ["{unfinished", "[]", '{"objective":"first","objective":"duplicate"}']
        for update in [
            {"records": {}},
            {"source": None},
            {"created_at": "today"},
            {"status": "ACCEPT"},
            {"records": [None]},
            {"records": [{**good_record, "kind": "invented"}]},
            {"records": [{**good_record, "kind": "performance"}]},
            {"records": [{**good_record, "context": {}}]},
            {"records": [{**good_record, "evidence": {"path": "x", "sha256": "bad"}}]},
        ]:
            corrupt.append(json.dumps({**initial, **update}))
        for contents in corrupt:
            with self.subTest(contents=contents):
                self.path.write_text(contents, encoding="utf-8")
                self.cli("status", expected=2)
                self.cli(
                    "record", "--kind", "decision", "--summary", "new note", expected=2
                )
                self.assertEqual(self.path.read_text(encoding="utf-8"), contents)

    def test_atomic_replace_failure_keeps_previous_file_and_cleans_temporary(self):
        state = self.initialize()
        original = self.path.read_bytes()
        state["objective"] = "replacement"
        with patch.object(
            worklog.os, "replace", side_effect=OSError("simulated write failure")
        ):
            with self.assertRaisesRegex(OSError, "simulated"):
                worklog.write_run(self.path, state)
        self.assertEqual(original, self.path.read_bytes())
        self.assertEqual(list(self.run.iterdir()), [self.path])

    def test_busy_writer_is_reported_without_mutation(self):
        self.initialize()
        original = self.path.read_bytes()
        with worklog.writer(self.path):
            result = self.cli(
                "record", "--kind", "decision", "--summary", "note", expected=2
            )
            self.assertIn("notebook is busy", result.stderr)
        self.assertEqual(original, self.path.read_bytes())
        self.assertFalse((self.run / ".worklog.lock").exists())


if __name__ == "__main__":
    unittest.main()
