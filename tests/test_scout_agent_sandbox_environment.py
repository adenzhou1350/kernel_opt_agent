"""Pure adapter controls; live broker evidence is a separate optional check."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from scout_agent_sandbox_environment import CPUSandboxEnvironment, SandboxFailure, require_text_submission

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

    def test_native_batch_preflight_does_not_dispatch_or_consume_actions(self):
        env = self.environment(max_actions=2)
        actions = [{"command": "echo hello", "tool_call_id": f"call-{i}"} for i in range(2)]
        original = copy.deepcopy(actions)
        self.assertIsNone(env.check_actions(actions))
        self.assertEqual((env.attempts, self.requests, self.records), (0, [], []))
        outputs = [env.execute(action) for action in actions]
        self.assertEqual([output["returncode"] for output in outputs], [0, 0])
        self.assertEqual(env.attempts, 2)
        self.assertEqual(actions, original)
        self.assertEqual([value["action"]["tool_call_id"] for name, value in self.records
                          if name.endswith("intent.json")], ["call-0", "call-1"])
        with self.assertRaises(SandboxFailure):
            env.check_actions(actions[:1])
        self.assertEqual(len(self.requests), 2)

    def test_capacity_guard_stops_before_model_delegate_after_last_action(self):
        env = self.environment(max_actions=1)
        self.assertEqual(env.check_action_capacity(), 1)
        self.assertEqual((env.attempts, self.requests, self.records), (0, [], []))
        env.execute({"command": "echo hello"})
        model_query = Mock()
        with self.assertRaises(SandboxFailure):
            env.check_action_capacity()
            model_query()
        model_query.assert_not_called()
        self.assertEqual((env.attempts, len(self.requests)), (1, 1))

    def test_capacity_guard_does_not_reserve_or_reject_target_nonzero_feedback(self):
        failed_assertion = copy.deepcopy(RESULT)
        failed_assertion.update(exit_code=1, stdout="", stderr="AssertionError: target")
        env = self.environment(failed_assertion, max_actions=2)
        self.assertEqual(env.check_action_capacity(), 2)
        self.assertEqual(env.check_action_capacity(), 2)
        env.execute({"command": "echo hello"})
        self.assertEqual(env.check_action_capacity(), 1)
        self.assertFalse(env.failed or env.uncertain)
        self.assertEqual((env.attempts, len(self.requests)), (1, 1))

    def test_capacity_guard_rejects_failed_uncertain_and_subsecond_states(self):
        for flag in ("failed", "uncertain"):
            with self.subTest(flag=flag):
                env = self.environment()
                setattr(env, flag, True)
                with self.assertRaises(SandboxFailure):
                    env.check_action_capacity()
                self.assertEqual((env.attempts, self.requests, self.records), (0, [], []))
        env = self.environment()
        with patch("scout_agent_sandbox_environment.time.monotonic", return_value=env.deadline - 0.5):
            with self.assertRaises(SandboxFailure):
                env.check_action_capacity()
        self.assertEqual((env.attempts, self.requests, self.records), (0, [], []))

    def test_whole_batch_rejects_invalid_later_action_before_first_dispatch(self):
        for second in ({"command": "outside"}, {"command": "echo hello", "tool_call_id": ""},
                       {"command": "echo hello", "extra": True}, {"command": "a\0b"}, None):
            with self.subTest(second=second):
                env = self.environment()
                with self.assertRaises(ValueError):
                    env.check_actions([{"command": "echo hello"}, second])
                self.assertEqual((env.attempts, self.requests, self.records), (0, [], []))
                self.assertFalse(env.failed or env.uncertain)

    def test_whole_batch_budget_cannot_run_a_prefix_or_grant_extra_actions(self):
        env = self.environment(max_actions=2)
        env.execute({"command": "echo hello"})
        with self.assertRaises(SandboxFailure):
            env.check_actions([{"command": "echo hello"}] * 2)
        self.assertEqual((env.attempts, len(self.requests)), (1, 1))
        env.check_actions([{"command": "echo hello"}])
        env.deadline = 0
        with self.assertRaises(SandboxFailure):
            env.execute({"command": "echo hello"})
        self.assertEqual((env.attempts, len(self.requests)), (1, 1))

    def test_batch_is_not_permission_to_reuse_a_failed_or_uncertain_environment(self):
        for flag in ("failed", "uncertain"):
            with self.subTest(flag=flag):
                env = self.environment()
                setattr(env, flag, True)
                with self.assertRaises(SandboxFailure):
                    env.check_actions([{"command": "echo hello"}])
                self.assertEqual(self.requests, [])

    def test_native_batch_shape_and_duplicate_ids_are_rejected(self):
        action = {"command": "echo hello", "tool_call_id": "same"}
        for actions in (None, [], (), "action", [action] * 65, [action, action]):
            with self.subTest(kind=type(actions).__name__):
                env = self.environment()
                with self.assertRaises(ValueError):
                    env.check_actions(actions)
                self.assertEqual(self.requests, [])
        # Scripted/native text actions need not manufacture tool-call IDs.
        env.check_actions([{"command": "echo hello"}] * 2)

    def test_uncertain_batch_prefix_is_preserved_and_suffix_never_runs(self):
        env = self.environment()
        actions = [{"command": "echo hello", "tool_call_id": f"call-{i}"} for i in range(3)]
        env.check_actions(actions)
        calls = []

        def lose_second(action, arguments):
            calls.append(arguments)
            if len(calls) == 2:
                raise TimeoutError("second invocation outcome unknown")
            return copy.deepcopy(RESULT)

        env.call = lose_second
        with self.assertRaises(TimeoutError):
            [env.execute(action) for action in actions]
        self.assertEqual((env.attempts, len(env.results), len(calls)), (2, 1, 2))
        self.assertTrue(env.uncertain)
        self.assertEqual([name for name, _ in self.records],
                         ["action-1-intent.json", "action-1-result.json", "action-2-intent.json"])
        with self.assertRaises(SandboxFailure):
            env.execute(actions[2])
        self.assertEqual(len(calls), 2)

    def test_batch_submission_retains_prefix_without_charging_unexecuted_suffix(self):
        class Submitted(Exception):
            pass

        def finish(env, output):
            raise Submitted()

        env = self.environment(finish=finish)
        actions = [{"command": "echo hello", "tool_call_id": f"call-{i}"} for i in range(2)]
        env.check_actions(actions)
        with self.assertRaises(Submitted):
            [env.execute(action) for action in actions]
        self.assertEqual((env.attempts, len(env.results), len(self.requests)), (1, 1, 1))
        self.assertEqual([name for name, _ in self.records], ["action-1-intent.json", "action-1-result.json"])
        self.assertFalse(env.uncertain or env.failed)

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

    def test_optional_text_contract_rejects_empty_marker_without_rewriting_raw_exit(self):
        marker = "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"
        called = []
        result = copy.deepcopy(RESULT)
        result["stdout"] = "  " + marker + "\n \t\n"
        original = copy.deepcopy(result)
        env = self.environment(result, finish=require_text_submission(
            lambda *args: called.append(args), marker=marker))
        output = env.execute({"command": "echo hello"})
        self.assertEqual(output["returncode"], 0)
        self.assertIn("TASK_OUTPUT_INCOMPLETE", output["output"])
        self.assertFalse(called)
        self.assertEqual(self.records[1][1], original)
        self.assertEqual(self.records[2][0], "action-1-submission-rejected.json")
        self.assertEqual(env.attempts, 1)
        self.assertFalse(env.failed or env.uncertain)
        self.assertEqual(result, original)
        # A rejection consumed the real action. It never extends the budget.
        env.max_actions = 1
        with self.assertRaises(SandboxFailure):
            env.execute({"command": "echo hello"})

    def test_text_contract_delegates_nonempty_normal_and_failed_outputs(self):
        marker = "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"
        for text, code in ((marker + "\nNO_FINDING; checks incomplete\n", 0),
                           (marker + "\n", 1), ("normal observation\n", 0)):
            with self.subTest(text=text, code=code):
                seen = []
                result = copy.deepcopy(RESULT)
                result.update(stdout=text, exit_code=code)
                finish = require_text_submission(lambda env, output: seen.append(copy.deepcopy(output)), marker=marker)
                output = self.environment(result, finish=finish).execute({"command": "echo hello"})
                self.assertEqual(seen, [output])
                self.assertEqual(len(self.records), 2)

    def test_text_contract_is_opt_in_and_validates_callback_and_marker(self):
        marker = "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"
        seen = []
        result = copy.deepcopy(RESULT)
        result["stdout"] = marker + "\n"
        self.environment(result, finish=lambda env, output: seen.append(output)).execute({"command": "echo hello"})
        self.assertEqual(seen[0]["output"], marker + "\n")
        for callback, value in ((None, marker), (lambda *a: None, ""),
                                (lambda *a: None, " x"), (lambda *a: None, "x\ny"),
                                (lambda *a: None, "x\ry"), (lambda *a: None, "x" * 129)):
            with self.subTest(value=value), self.assertRaises(ValueError):
                require_text_submission(callback, marker=value)

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
