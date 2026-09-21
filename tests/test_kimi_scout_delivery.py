"""Offline delivery-queue and repair-loop tests; no model, Docker or network."""

import json
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import kimi_scout_delivery as delivery

SOURCE = "def value():\n    return 1\n"
TEST = """import unittest
import subject
class Tests(unittest.TestCase):
    def test_regression(self): self.assertEqual(subject.value(), 2)
    def test_normal(self): self.assertIsInstance(subject.value(), int)
"""


def proposal():
    return {
        "decision": "test",
        "reason": "fixture",
        "test_code": TEST,
        "edits": [{"old": "return 1", "new": "return 2"}],
    }


def lead(number=1):
    return {
        "id": str(number),
        "repo": "public/project",
        "commit": "a" * 40,
        "canonical_key": "hypothesis" + str(number),
        "packet": {},
        "analysis": {"title": "fixture", "hypothesis": "small fixture"},
    }


def result(before=1, fixed=0, *, count=2, output="", cleanup=True):
    return {
        "inconclusive": False,
        "before": {
            "exit_code": before,
            "reported_tests_run": count,
            "output": output,
            "cleanup_ok": cleanup,
        },
        "fixed": {
            "exit_code": fixed,
            "reported_tests_run": count,
            "output": "",
            "cleanup_ok": cleanup,
        },
    }


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.inbox = Path(self.temp.name)
        self.args = SimpleNamespace(
            root=self.inbox,
            concurrency=4,
            execution_concurrency=2,
            github_auth=False,
            kimi_python=Path(sys.executable),
            wsl="Ubuntu",
        )
        self.worker = delivery.Delivery(self.args)
        delivery.initialize(self.worker.root)

    def test_admission_deduplicates_and_atomic_parallel_claims_are_unique(self):
        self.assertEqual(
            delivery.stage(self.worker.root, [lead(i) for i in range(12)], 8), 8
        )
        self.assertEqual(delivery.stage(self.worker.root, [lead(0)]), 0)
        with ThreadPoolExecutor(max_workers=4) as pool:
            jobs = list(pool.map(lambda _: delivery.claim(self.worker.root), range(10)))
        ids = [j["id"] for j in jobs if j]
        self.assertEqual(len(ids), 8)
        self.assertEqual(len(set(ids)), 8)

    def test_replacement_is_bounded_and_unique(self):
        self.assertIn("return 2", delivery.proposal(proposal(), SOURCE))
        for source in ("no match", SOURCE + SOURCE):
            with self.assertRaises(ValueError):
                delivery.proposal(proposal(), source)
        value = proposal()
        value["edits"][0]["path"] = "/outside/private.py"
        with self.assertRaises(ValueError):
            delivery.proposal(value, SOURCE)

    def test_zero_skip_and_copied_only_tests_do_not_admit(self):
        for code in (
            "pass",
            TEST.replace("import subject", ""),
            TEST.replace(
                "def test_normal", "@unittest.skip('fake')\n    def test_normal"
            ),
        ):
            with self.subTest(code=code), self.assertRaises(ValueError):
                delivery.proposal({**proposal(), "test_code": code}, SOURCE)

    def test_profile_is_controller_chosen_from_required_dependencies(self):
        self.assertEqual(delivery.choose_profile({"dependency_modules": []}), "stdlib")
        self.assertEqual(
            delivery.choose_profile({"dependency_modules": ["torch", "numpy"]}),
            "torch-cpu",
        )
        self.assertEqual(
            delivery.choose_profile(
                {
                    "required_dependency_modules": [],
                    "dependency_modules": ["unavailable_lazy"],
                }
            ),
            "stdlib",
        )
        with self.assertRaises(delivery.UnsupportedEnvironment):
            delivery.choose_profile({"dependency_modules": ["custom_framework"]})

    def test_outcomes_do_not_promote_zero_tests_or_missing_imports(self):
        self.assertEqual(delivery.classify(result())[0], "REVIEWING")
        self.assertEqual(delivery.classify(result(0, 0))[0], "INCONCLUSIVE")
        self.assertEqual(delivery.classify(result(count=0))[0], "INCONCLUSIVE")
        self.assertEqual(
            delivery.classify(result(output="ModuleNotFoundError: no torch\n"))[0],
            "ENVIRONMENT_BLOCKED",
        )
        self.assertEqual(delivery.classify({"inconclusive": True})[0], "INCONCLUSIVE")

    def run_job(self, outputs, answers):
        delivery.stage(self.worker.root, [lead()])
        job = delivery.claim(self.worker.root)
        source = {
            "source": SOURCE,
            "path": "public.py",
            "url": "https://public.invalid/data",
            "sha256": "a" * 64,
            "dependency_modules": [],
        }
        with (
            patch.object(delivery, "load_source", return_value=source),
            patch.object(self.worker, "model", side_effect=answers) as model,
            patch.object(self.worker, "sandbox", side_effect=outputs) as sandbox,
        ):
            state = self.worker.execute(job)
        with delivery.database(self.worker.root) as db:
            row = dict(db.execute("SELECT * FROM delivery").fetchone())
        return state, row, model, sandbox

    def test_real_output_gets_one_repair_then_separate_review(self):
        verdict = {"decision": "accept_for_owner", "reason": "needs maintainer tests"}
        state, row, model, sandbox = self.run_job(
            [result(1, 1), result()], [proposal(), proposal(), verdict]
        )
        self.assertEqual(state, "REPRODUCED")
        self.assertEqual(model.call_count, 3)
        self.assertEqual(sandbox.call_count, 2)
        self.assertIn("actual_result", model.call_args_list[1].args[2])
        self.assertFalse(json.loads(row["result"])["qualified"])

    def test_second_failure_is_terminal_without_third_execution(self):
        state, _, model, sandbox = self.run_job(
            [result(1, 1), result(1, 1)], [proposal(), proposal()]
        )
        self.assertEqual(state, "INCONCLUSIVE")
        self.assertEqual(model.call_count, 2)
        self.assertEqual(sandbox.call_count, 2)

    def test_model_rejection_has_no_container_and_is_labeled_advisory(self):
        rejection = {
            "decision": "reject",
            "reason": "caller excludes this input",
            "test_code": "",
            "edits": [],
        }
        state, row, _, sandbox = self.run_job([], [rejection])
        self.assertEqual(state, "NO_BUG")
        self.assertIn("Model advisory", row["reason"])
        sandbox.assert_not_called()

    def test_environment_failure_does_not_spend_repair_call(self):
        state, _, model, sandbox = self.run_job(
            [result(output="ImportError: package mismatch\n")], [proposal()]
        )
        self.assertEqual(state, "ENVIRONMENT_BLOCKED")
        self.assertEqual(model.call_count, 1)
        self.assertEqual(sandbox.call_count, 1)

    def test_review_can_reject_a_before_fail_fixed_pass(self):
        state, row, _, _ = self.run_job(
            [result()], [proposal(), {"decision": "reject", "reason": "wrong contract"}]
        )
        self.assertEqual(state, "INCONCLUSIVE")
        self.assertFalse(json.loads(row["result"])["qualified"])

    def test_sandbox_transport_or_cleanup_uncertainty_stops_new_work(self):
        work = self.worker.root / "jobs" / "a"
        work.mkdir()
        for response in (
            subprocess.TimeoutExpired("fixed verifier", 150),
            SimpleNamespace(stdout=b"not JSON", returncode=1),
            SimpleNamespace(stdout=b'{"inconclusive":true}', returncode=1),
        ):
            self.worker.halt.clear()
            options = (
                {"side_effect": response}
                if isinstance(response, Exception)
                else {"return_value": response}
            )
            with patch.object(delivery.subprocess, "run", **options):
                try:
                    self.worker.sandbox(work, 1, "stdlib")
                except RuntimeError:
                    pass
            self.assertTrue(self.worker.halt.is_set())

    def test_stop_blocks_new_model_and_container_stages(self):
        (self.worker.root / "STOP").write_text("owner stop", encoding="utf-8")
        with patch.object(delivery.subprocess, "run") as execute:
            with self.assertRaises(RuntimeError):
                self.worker.model({"id": "unused"}, "repair", "no new paid call")
            result = self.worker.sandbox(self.worker.root, 1, "stdlib")
            self.assertTrue(result["inconclusive"])
            execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
