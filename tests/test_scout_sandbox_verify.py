"""Offline broker-protocol controls; no SSH, Docker, model or GPU calls."""

import base64
import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import kimi_scout_delivery as delivery
from kimi_scout_verify import MARKER, SUMMARY_MARKER
from scout_sandbox_verify import SandboxCPU

IMAGE = "sha256:" + "a" * 64


class Broker:
    def __init__(self, damage=None, disconnect=False):
        self.actions = []
        self.files = {}
        self.snapshots = {}
        self.damage = damage
        self.disconnect = disconnect
        self.runs = 0

    def __call__(self, action, arguments=None):
        value = arguments or {}
        self.actions.append((action, copy.deepcopy(value)))
        if action == "health":
            return {
                "ready": True,
                "backend": "docker-cpu",
                "network": "none",
                "image": IMAGE,
                "limits": {"memory_mib": 512, "cpus": 1, "pids": 64},
            }
        if action == "create":
            self.files["first"] = {}
            return {"id": "first"}
        sid = value["session_id"]
        if action == "write":
            self.files[sid][value["path"]] = base64.b64decode(value["content_base64"])
            return {"written": value["path"]}
        if action == "checkpoint":
            self.snapshots["snapshot"] = copy.deepcopy(self.files[sid])
            return {"checkpoint_id": "snapshot"}
        if action == "restore":
            self.files["second"] = copy.deepcopy(self.snapshots[value["checkpoint_id"]])
            return {"id": "second"}
        if action == "release":
            return {"released": sid}
        if action != "run":
            raise AssertionError(action)
        self.runs += 1
        if self.disconnect:
            raise RuntimeError("outcome uncertain")
        failed = sid == "first"
        summary = {
            "tests_run": 2,
            "failures": int(failed),
            "errors": 0,
            "skipped": 0,
            "expected_failures": 0,
            "unexpected_successes": 0,
        }
        result = {
            "status": "completed",
            "profile": "cpu",
            "image": IMAGE,
            "exit_code": int(failed),
            "termination": None,
            "oom_killed": False,
            "container_removed": True,
            "workspace_persisted": True,
            "run_id": str(self.runs),
            "stderr": "",
            "workspace_sha256": {
                k: hashlib.sha256(v).hexdigest() for k, v in self.files[sid].items()
            },
            "stdout": SUMMARY_MARKER + json.dumps(summary) + "\n" + MARKER + "2\n",
            "isolation": {
                "NetworkMode": "none",
                "ReadonlyRootfs": True,
                "Privileged": False,
                "Memory": 512 * 1024 * 1024,
                "MemorySwap": 512 * 1024 * 1024,
                "NanoCpus": 1_000_000_000,
                "PidsLimit": 64,
                "CapDrop": ["ALL"],
                "SecurityOpt": ["no-new-privileges:true"],
                "Binds": None,
                "Devices": None,
            },
        }
        if self.damage:
            self.damage(result)
        return result


class Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.inputs = []
        for name, text in (
            ("old.py", "value = 1\n"),
            ("new.py", "value = 2\n"),
            ("test.py", "# reviewed fixture\n"),
        ):
            path = self.root / name
            path.write_text(text, encoding="utf8")
            self.inputs.append(path)

    def compare(self, broker, name="journal.jsonl"):
        return SandboxCPU(broker, image=IMAGE).verify(
            *self.inputs, journal=self.root / name
        )

    def test_fresh_candidate_restores_pre_execution_snapshot_and_releases(self):
        broker = Broker()
        value = self.compare(broker)
        self.assertFalse(value["inconclusive"])
        self.assertEqual(delivery.classify(value)[0], "REVIEWING")
        self.assertEqual(broker.runs, 2)
        actions = [a for a, _ in broker.actions]
        self.assertLess(actions.index("checkpoint"), actions.index("run"))
        self.assertEqual(actions[-2:], ["release", "release"])
        self.assertEqual(
            broker.files["first"]["subject.py"], self.inputs[0].read_bytes()
        )
        self.assertEqual(
            broker.files["second"]["test_subject.py"], self.inputs[2].read_bytes()
        )
        events = [
            json.loads(row)
            for row in (self.root / "journal.jsonl").read_text().splitlines()
        ]
        self.assertTrue(
            any(e.get("state") == "STARTED_OUTCOME_UNCERTAIN" for e in events)
        )
        self.assertNotIn("content_base64", (self.root / "journal.jsonl").read_text())

    def test_uncertain_run_never_replays_or_starts_candidate(self):
        broker = Broker(disconnect=True)
        with self.assertRaises(RuntimeError):
            self.compare(broker)
        self.assertEqual(broker.runs, 1)
        self.assertNotIn("restore", [a for a, _ in broker.actions])
        self.assertNotIn("release", [a for a, _ in broker.actions])
        before = len(broker.actions)
        with self.assertRaises(FileExistsError):
            self.compare(broker)
        self.assertEqual(len(broker.actions), before)

    def test_bad_environment_or_inputs_reject_before_remote_creation(self):
        broker = Broker()
        adapter = SandboxCPU(broker, image="sha256:" + "b" * 64)
        self.assertFalse(adapter.check_runtime()["available"])
        with self.assertRaises(ValueError):
            adapter.verify(*self.inputs, journal=self.root / "bad-health.jsonl")
        for profile in ("torch-cpu", "gpu", "arbitrary"):
            with self.assertRaises(ValueError):
                SandboxCPU(broker, image=IMAGE).verify(
                    *self.inputs, profile=profile, journal=self.root / "unused"
                )
        self.assertEqual([a for a, _ in broker.actions], ["health", "health"])

    def test_broker_controls_input_and_summary_mismatch_are_not_a_pass(self):
        def damage(key, value):
            return lambda row: row.update({key: value})

        cases = [
            damage("container_removed", False),
            damage("workspace_persisted", False),
            damage("termination", "timeout"),
            damage("oom_killed", True),
            damage("image", "other"),
            damage("profile", "gpu"),
            damage("isolation", {}),
            damage("workspace_sha256", {}),
            damage("stdout", MARKER + "2\n" + MARKER + "2\n"),
        ]
        for index, corrupt in enumerate(cases):
            with self.subTest(index=index):
                broker = Broker(damage=corrupt)
                value = self.compare(broker, name=str(index) + ".jsonl")
                self.assertTrue(value["inconclusive"])
                self.assertEqual(broker.runs, 1)
                self.assertEqual(delivery.classify(value)[0], "INCONCLUSIVE")
                self.assertNotIn("restore", [a for a, _ in broker.actions])

    def test_shell_success_and_visible_test_text_do_not_replace_outcome_summary(self):
        def shell_masks_failure(row):
            row.update(exit_code=0, stdout="Ran 2 tests\nFAILED (failures=1)\nexit=1\n")

        broker = Broker(damage=shell_masks_failure)
        value = self.compare(broker)
        self.assertTrue(value["inconclusive"])
        self.assertEqual(delivery.classify(value)[0], "INCONCLUSIVE")
        self.assertEqual(broker.runs, 1)
        self.assertNotIn("restore", [action for action, _ in broker.actions])

    def test_shell_exit_must_agree_with_structured_test_outcomes(self):
        value = self.compare(Broker())
        self.assertEqual(delivery.classify(value)[0], "REVIEWING")
        for arm, masked_exit in (("before", 0), ("fixed", 1)):
            with self.subTest(arm=arm):
                damaged = copy.deepcopy(value)
                damaged[arm]["exit_code"] = masked_exit
                state, reason = delivery.classify(damaged)
                self.assertEqual(state, "INCONCLUSIVE")
                self.assertIn("contradicts unittest outcome", reason)


if __name__ == "__main__":
    unittest.main()
