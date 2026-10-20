"""No-model mechanics: non-menu CPU commands, error feedback and a workspace edit.

Review this scripted task before opting in. This is not hostile-code isolation,
agent discovery, a model-generated repair, or a performance comparison.
"""

import argparse
import base64
import copy
import importlib.util
import inspect
import json
import os
from pathlib import Path
import shlex
import sys
import time

from check import COMMIT, HERE, sha256


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--client", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = args.source.resolve() / "src/minisweagent"
    expected = json.loads((HERE / "source_sha256.json").read_text())
    assert {name: sha256(source / name) for name in expected} == expected
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=False)

    def record(name, value):
        with (args.output / name).open("x", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2)

    os.environ.update(MSWEA_SILENT_STARTUP="1", MSWEA_GLOBAL_CONFIG_DIR=str(args.output / "mini-config"))
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(HERE.parents[1] / "scripts"))
    sys.path.insert(0, str(source.parent))
    from scout_agent_sandbox_environment import CPUSandboxEnvironment, require_text_submission
    from minisweagent.agents.default import DefaultAgent
    from minisweagent.environments.local import LocalEnvironment
    from minisweagent.models.test_models import DeterministicModel, make_output

    for cls in (DefaultAgent, LocalEnvironment, DeterministicModel):
        assert Path(inspect.getfile(cls)).resolve().is_relative_to(source)
    spec = importlib.util.spec_from_file_location("reviewed_sandbox_client", args.client)
    client = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(client)
    health = client.call("health")
    record("health.json", health)
    session = client.call("create", {"profile": "cpu"})
    record("session.json", session)
    session_id = session["id"]
    env = None
    started = time.monotonic()
    commands = [
        "python3 -B -c 'print('",
        "python3 -B -c " + shlex.quote("from pathlib import Path;print(Path('fixture_subject.py').read_text())"),
        "python3 -B -m unittest -v fixture_checks",
        "python3 -B -c " + shlex.quote(
            "from pathlib import Path;Path('fixture_subject.py').write_text("
            "'def slice_exclusive(data, start, end):\\n    return data[start:end]\\n')"),
        "python3 -B -m unittest -v fixture_checks",
        "printf 'COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\\n'",
        "printf 'COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\\nSCRIPTED_EDIT_VERIFIED\\n'",
    ]
    record("intent.json", {"source_commit": COMMIT, "actual_model_api_calls": 0,
           "commands": commands, "adapter_sha256": sha256(HERE.parents[1] / "scripts/scout_agent_sandbox_environment.py"),
           "input_fixture_sha256": {name: sha256(HERE / name) for name in ("fixture_subject.py", "fixture_checks.py")},
           "allow_dynamic_commands": True, "max_actions": 7,
           "require_nonempty_final_text": True})

    class ObservedModel(DeterministicModel):
        def query(self, messages, **kwargs):
            self.observed.append(copy.deepcopy(messages))
            return super().query(messages, **kwargs)

    try:
        env = CPUSandboxEnvironment(client.call, session=session, health=health,
            record=record, finish=require_text_submission(LocalEnvironment._check_finished,
                marker="COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"),
            allow_dynamic_commands=True, max_actions=7, command_timeout=5, wall_seconds=120)
        for name in ("fixture_subject.py", "fixture_checks.py"):
            client.call("write", {"session_id": session_id, "path": name,
                        "content_base64": base64.b64encode((HERE / name).read_bytes()).decode()})
        model = ObservedModel(outputs=[make_output("Scripted mechanics", [{"command": c}], cost=0.0)
                                       for c in commands], cost_per_call=0.0)
        model.observed = []
        agent = DefaultAgent(model, env, system_template="Scripted known fixture, not discovery.",
            instance_template="{{task}}", step_limit=7, cost_limit=0, wall_time_limit_seconds=120,
            output_path=args.output / "trajectory.json")
        outcome = agent.run("Run the reviewed scripted command/error/edit sequence.")
        assert outcome["exit_status"] == "Submitted" and agent.n_calls == 7
        assert outcome["submission"].strip() == "SCRIPTED_EDIT_VERIFIED"
        assert [r["exit_code"] for r in env.results] == [1, 0, 1, 0, 0, 0, 0]
        assert "SyntaxError" in env.results[0]["stderr"]
        assert "SyntaxError" in model.observed[1][-1]["content"]
        assert "FAILED (failures=1)" in env.results[2]["stderr"]
        assert "FAILED (failures=1)" in model.observed[3][-1]["content"]
        assert "Ran 2 tests" in env.results[4]["stderr"] and "OK" in env.results[4]["stderr"]
        assert "OK" in model.observed[5][-1]["content"]
        assert "TASK_OUTPUT_INCOMPLETE" in model.observed[6][-1]["content"]
        assert env.results[5]["stdout"] == "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\n"
        assert all(r["container_removed"] for r in env.results)
        assert {name: sha256(source / name) for name in expected} == expected
        record("summary.json", {"state": "SCRIPTED_DYNAMIC_SANDBOX_COMPONENT_PASS", "scripted_queries": 7,
               "actual_model_api_calls": 0, "sandbox_calls": 7, "syntax_error_reaches_next_query": True,
               "empty_submission_is_task_feedback_not_success": True,
               "within_session_toy_edit_persists": True, "host_source_unchanged": True,
               "exit_codes": [r["exit_code"] for r in env.results], "wall_seconds": time.monotonic()-started,
               "priced_total": None, "boundary": "Scripted known fixture. No model-generated command or repair, arbitrary hostile-code guarantee, discovery, matched baseline or efficacy claim."})
        print((args.output / "summary.json").read_text())
    except BaseException as error:
        record("failure.json", {"type": type(error).__name__, "message": str(error),
                                "uncertain": bool(env and env.uncertain)})
        raise
    finally:
        if env is None or not env.uncertain:
            record("release.json", client.call("release", {"session_id": session_id}))


if __name__ == "__main__":
    main()
