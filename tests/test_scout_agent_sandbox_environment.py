"""Pure adapter controls; live broker evidence is a separate optional check."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from scout_agent_sandbox_environment import CPUSandboxEnvironment, SandboxFailure

IMAGE = "sha256:" + "a" * 64
HEALTH = {"ready": True, "backend": "docker-cpu", "network": "none", "image": IMAGE,
          "limits": {"memory_mib": 512, "pids": 64, "cpus": 1}}
RESULT = {"image": IMAGE, "container_removed": True, "status": "completed",
          "profile": "cpu", "oom_killed": False,
          "termination": None, "workspace_persisted": True, "exit_code": 0,
          "stdout": "hello\n", "stderr": "",
          "isolation": {"NetworkMode": "none", "ReadonlyRootfs": True, "Privileged": False,
                        "Binds": None, "Devices": [], "Memory": 512*1024**2,
                        "MemorySwap": 512*1024**2, "NanoCpus": 1_000_000_000,
                        "PidsLimit": 64, "CapDrop": ["ALL"], "SecurityOpt": ["no-new-privileges:true"]}}


class EnvironmentTests(unittest.TestCase):
    def environment(self, result=None, **kwargs):
        self.requests, self.records = [], []

        def call(action, arguments):
            self.requests.append((action, arguments))
            return copy.deepcopy(RESULT if result is None else result)

        return CPUSandboxEnvironment(call, session={"id": "b"*24, "profile": "cpu"}, health=HEALTH,
            record=lambda name, value: self.records.append((name, copy.deepcopy(value))),
            **({"allowed_commands": ["echo hello"]} | kwargs))

    def test_literal_mode_default_and_native_tool_id_are_preserved(self):
        env = self.environment()
        action = {"command": "echo hello", "tool_call_id": "call-1"}
        self.assertEqual(env.execute(action)["returncode"], 0)
        self.assertEqual(self.requests[0], ("run", {"session_id": "b"*24, "command": "echo hello", "timeout": 5}))
        self.assertEqual(self.records[0][1]["action"], action)
        self.assertFalse(env.uncertain)
        with self.assertRaises(ValueError):
            env.execute({"command": "other"})
        self.assertEqual(len(self.requests), 1)

    def test_dynamic_syntax_error_is_unmodified_target_feedback_not_infrastructure(self):
        result = copy.deepcopy(RESULT)
        result.update(exit_code=2, stdout="", stderr="Syntax error: unterminated quoted string")
        env = self.environment(result, allowed_commands=(), allow_dynamic_commands=True)
        command = "python3 -c 'print("
        self.assertEqual(env.execute({"command": command})["returncode"], 2)
        self.assertEqual(self.requests[0][1]["command"], command)
        self.assertFalse(env.failed)
        env.execute({"command": "printf recovered"})
        self.assertEqual(env.attempts, 2)

    def test_transport_uncertainty_never_replays_or_falls_back_to_host(self):
        env = self.environment()

        def lost(*args):
            raise TimeoutError("transport outcome unknown")

        env.call = lost
        with self.assertRaises(TimeoutError):
            env.execute({"command": "echo hello"})
        self.assertTrue(env.uncertain)
        self.assertEqual(env.attempts, 1)
        with self.assertRaises(SandboxFailure):
            env.execute({"command": "echo hello"})
        self.assertEqual(env.attempts, 1)

    def test_limits_and_timeout_failures_do_not_become_target_assertions(self):
        env = self.environment(max_actions=1)
        env.execute({"command": "echo hello"})
        with self.assertRaises(SandboxFailure):
            env.execute({"command": "echo hello"})
        env = self.environment()
        env.deadline = 0
        with self.assertRaises(SandboxFailure):
            env.execute({"command": "echo hello"})
        self.assertEqual(self.requests, [])
        result = copy.deepcopy(RESULT)
        result.update(status="terminated", termination="timeout", exit_code=137)
        env = self.environment(result)
        with self.assertRaisesRegex(SandboxFailure, "timeout"):
            env.execute({"command": "echo hello"})
        self.assertTrue(env.failed)
        self.assertFalse(env.uncertain)
        with self.assertRaises(SandboxFailure):
            env.execute({"command": "echo hello"})

    def test_isolation_cleanup_and_persistence_are_not_optional(self):
        changes = [("container_removed", False), ("workspace_persisted", False), ("image", "other"),
                   ("profile", "gpu"), ("oom_killed", True)]
        for name, value in changes:
            with self.subTest(field=name):
                result = copy.deepcopy(RESULT)
                result[name] = value
                env = self.environment(result)
                with self.assertRaises(SandboxFailure):
                    env.execute({"command": "echo hello"})
        for name, value in (("Devices", ["gpu"]), ("MemorySwap", -1), ("NanoCpus", 0),
                            ("Binds", ["/host:/work"]), ("SecurityOpt", []), ("CapDrop", [])):
            with self.subTest(isolation=name):
                result = copy.deepcopy(RESULT)
                result["isolation"][name] = value
                with self.assertRaises(SandboxFailure):
                    self.environment(result).execute({"command": "echo hello"})

    def test_finish_callback_runs_after_retaining_actual_result(self):
        class Submitted(Exception):
            pass

        def finish(env, output):
            self.assertEqual(len(self.records), 2)
            self.assertFalse(env.uncertain)
            self.assertEqual(output["returncode"], 0)
            raise Submitted()

        with self.assertRaises(Submitted):
            self.environment(finish=finish).execute({"command": "echo hello"})

    def test_recorder_failures_preserve_before_and_after_dispatch_distinction(self):
        env = self.environment()

        def broken(name, value):
            raise OSError("private evidence storage unavailable")

        env.record = broken
        with self.assertRaises(OSError):
            env.execute({"command": "echo hello"})
        self.assertFalse(env.uncertain)
        self.assertEqual(self.requests, [])
        env = self.environment()
        original = env.record

        def broken_result(name, value):
            if name.endswith("result.json"):
                raise OSError("evidence write failed after real execution")
            original(name, value)

        env.record = broken_result
        with self.assertRaises(OSError):
            env.execute({"command": "echo hello"})
        self.assertTrue(env.uncertain)
        with self.assertRaises(SandboxFailure):
            env.execute({"command": "echo hello"})
        self.assertEqual(len(self.requests), 1)

    def test_malformed_or_oversize_broker_outputs_do_not_become_target_results(self):
        for result in ([], {**RESULT, "isolation": "invalid"}, {**RESULT, "stdout": "x"*32769},
                       {**RESULT, "exit_code": True}):
            with self.subTest(kind=str(type(result))), self.assertRaises(SandboxFailure):
                self.environment(result).execute({"command": "echo hello"})

    def test_bad_health_and_malformed_isolation_do_not_admit_actions(self):
        for health in (None, {**HEALTH, "limits": "invalid"}, {**HEALTH, "network": "host"},
                       {**HEALTH, "backend": "docker-gpu"}, {**HEALTH, "image": "mutable:latest"}):
            with self.subTest(health=health), self.assertRaises(ValueError):
                CPUSandboxEnvironment(lambda *args: self.fail("must not run"), session={"id": "b"*24, "profile": "cpu"},
                    health=health, record=lambda *args: None, allowed_commands=["echo hello"])
        for name, value in (("CapDrop", None), ("SecurityOpt", "no-new-privileges:true"), ("Binds", "")):
            result = copy.deepcopy(RESULT)
            result["isolation"][name] = value
            with self.subTest(field=name), self.assertRaises(SandboxFailure):
                self.environment(result).execute({"command": "echo hello"})
        for session in (None, {"id": "b"*24, "profile": "gpu"}, {"id": "bad", "profile": "cpu"},
                        {"id": "b"*24, "profile": "cpu", "released": True}):
            with self.subTest(session=session), self.assertRaises(ValueError):
                CPUSandboxEnvironment(lambda *args: self.fail("must not run"), session=session,
                    health=HEALTH, record=lambda *args: None, allowed_commands=["echo hello"])

    def test_reject_bad_actions_budgets_and_implicit_dynamic_mode_before_execution(self):
        for kwargs in ({"allowed_commands": ()}, {"allow_dynamic_commands": True},
                       {"max_actions": True}, {"wall_seconds": float("nan")}, {"command_timeout": 0},
                       {"allowed_commands": "echo hello"}, {"allowed_commands": [{}]}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.environment(**kwargs)
        for action in ({}, {"command": "echo hello", "timeout": 999}, {"command": "a\0b"},
                       {"command": "echo hello", "tool_call_id": ""}, {"command": "x"*8193}):
            with self.subTest(action=str(action)[:80]), self.assertRaises(ValueError):
                self.environment().execute(action)
        with self.assertRaises(ValueError):
            self.environment().execute({"command": "echo hello"}, cwd="C:/host")
        self.assertEqual(self.requests, [])


if __name__ == "__main__":
    unittest.main()
