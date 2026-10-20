"""Check a real agent loop with fixed commands and a configured CPU sandbox.

Optional upstream dependencies are imported only after CLI/source preflight.
This does not connect a model/provider or execute an arbitrary proposed command.
"""

import argparse
import base64
import copy
import hashlib
import importlib.metadata
import importlib.util
import inspect
import json
import os
from pathlib import Path
import shlex
import sys
import time

HERE = Path(__file__).resolve().parent
COMMIT = "04d809ceab9df28f9adaed044884180159172930"


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        required=True,
        help="Reviewed mini-SWE-agent root with src/",
    )
    parser.add_argument(
        "--client", type=Path, required=True, help="Installed agent-sandbox/client.py"
    )
    parser.add_argument(
        "--output", type=Path, required=True, help="New private evidence directory"
    )
    args = parser.parse_args()
    source = args.source.resolve() / "src/minisweagent"
    expected = json.loads((HERE / "source_sha256.json").read_text())
    assert {name: sha256(source / name) for name in expected} == expected
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=False)

    def record(name, value):
        (args.output / name).write_text(json.dumps(value, indent=2), encoding="utf-8")

    record(
        "intent.json",
        dict(
            source_commit=COMMIT,
            source_sha256=expected,
            client_sha256=sha256(args.client),
            actual_model_api_calls=0,
        ),
    )
    os.environ["MSWEA_GLOBAL_CONFIG_DIR"] = str(args.output / "empty-config")
    os.environ["MSWEA_SILENT_STARTUP"] = "1"
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(source.parent))
    from minisweagent.agents.default import DefaultAgent
    from minisweagent.environments.local import LocalEnvironment
    from minisweagent.models.test_models import DeterministicModel, make_output

    for cls in (DefaultAgent, LocalEnvironment, DeterministicModel):
        assert Path(inspect.getfile(cls)).resolve().is_relative_to(source)
    for name, module in tuple(sys.modules.items()):
        if name == "minisweagent" or name.startswith("minisweagent."):
            path = Path(module.__file__).resolve()
            assert (
                path.is_relative_to(source)
                and sha256(path) == expected[path.relative_to(source).as_posix()]
            )

    spec = importlib.util.spec_from_file_location(
        "reviewed_sandbox_client", args.client
    )
    client = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(client)
    health = client.call("health")
    record("health.json", health)
    assert (
        health["ready"]
        and health["backend"] == "docker-cpu"
        and health["network"] == "none"
    )
    assert health["limits"]["pids"] == 64 and health["limits"]["memory_mib"] == 512
    session = client.call("create", dict(profile="cpu"))
    record("session.json", session)
    session_id = session["id"]
    commands = [
        "python3 -B -c "
        + shlex.quote(
            "from pathlib import Path;print(Path('fixture_subject.py').read_text())"
        ),
        "python3 -B -m unittest -v fixture_checks",
        "printf 'COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\\nNATIVE_OBSERVATION_RECEIVED\\n'",
    ]
    timeout_command = "python3 -B -c " + shlex.quote("import time;time.sleep(10)")
    allowed = set(commands + [timeout_command])
    actions = []
    uncertain = False

    class SandboxFailure(RuntimeError):
        pass

    class SandboxEnvironment:
        def execute(self, action, cwd="", *, timeout=None):
            nonlocal uncertain
            assert not cwd or cwd == "/work"
            assert set(action) == {"command"} and action["command"] in allowed
            uncertain = True
            result = client.call(
                "run",
                dict(
                    session_id=session_id,
                    command=action["command"],
                    timeout=timeout or 5,
                ),
            )
            uncertain = False
            actions.append(result)
            record("actions.json", actions)
            assert result["image"] == health["image"] and result["container_removed"]
            isolation = result["isolation"]
            assert isolation["NetworkMode"] == "none" and isolation["ReadonlyRootfs"]
            assert isolation["Memory"] == 512 * 1024**2 and isolation["PidsLimit"] == 64
            assert not isolation["Privileged"] and not isolation["Binds"]
            if (
                result.get("status") != "completed"
                or result.get("termination")
                or not result.get("workspace_persisted")
            ):
                raise SandboxFailure(
                    result.get("termination")
                    or result.get("error")
                    or "persistence failure"
                )
            output = dict(
                output=result["stdout"] + result["stderr"],
                returncode=result["exit_code"],
                exception_info="",
            )
            LocalEnvironment._check_finished(self, output)
            return output

        def get_template_vars(self, **kwargs):
            return dict(cwd="/work", system="Linux", **kwargs)

        def serialize(self):
            return dict(
                info=dict(
                    config=dict(
                        environment_type="reviewed_cpu_sandbox_adapter",
                        environment=dict(
                            profile="cpu", session_id=session_id, image=health["image"]
                        ),
                    )
                )
            )

    class ObservedModel(DeterministicModel):
        def query(self, messages, **kwargs):
            self.observed.append(copy.deepcopy(messages))
            return super().query(messages, **kwargs)

    env = SandboxEnvironment()

    def make_agent(limit, filename):
        model = ObservedModel(
            outputs=[
                make_output("Reviewed fixed action", [dict(command=c)], cost=0.0)
                for c in commands
            ],
            cost_per_call=0.0,
        )
        model.observed = []
        return DefaultAgent(
            model,
            env,
            system_template="Synthetic mechanics, not discovery.",
            instance_template="{{task}}",
            step_limit=limit,
            cost_limit=0,
            wall_time_limit_seconds=120,
            output_path=args.output / filename,
        ), model

    started = time.monotonic()
    try:
        for name in ("fixture_subject.py", "fixture_checks.py"):
            client.call(
                "write",
                dict(
                    session_id=session_id,
                    path=name,
                    content_base64=base64.b64encode(
                        (HERE / name).read_bytes()
                    ).decode(),
                ),
            )
        agent, model = make_agent(3, "trajectory.json")
        result = agent.run("Read source, run the control/boundary tests, then submit.")
        assert (
            result["exit_status"] == "Submitted"
            and result["submission"].strip() == "NATIVE_OBSERVATION_RECEIVED"
        )
        assert agent.n_calls == 3 and [a["exit_code"] for a in actions] == [0, 1, 0]
        assert "FAILED (failures=1)" in actions[1]["stderr"]
        assert (
            "test_ordinary_control" in actions[1]["stderr"]
            and " ... ok" in actions[1]["stderr"]
        )
        assert "test_exclusive_end_witness" in actions[1]["stderr"]
        assert any(m.get("extra", {}).get("returncode") == 1 for m in model.observed[2])
        assert any("slice_exclusive" in m.get("content", "") for m in model.observed[1])
        limited, _ = make_agent(1, "step-limit-trajectory.json")
        assert limited.run("Stop after one command.")["exit_status"] == "LimitsExceeded"
        assert limited.n_calls == 1 and len(actions) == 4
        try:
            env.execute(dict(command=timeout_command), timeout=1)
        except SandboxFailure as exc:
            assert str(exc) == "timeout"
        else:
            raise AssertionError("Timeout became a normal target observation")
        assert len(actions) == 5 and actions[-1]["termination"] == "timeout"
        assert {name: sha256(source / name) for name in expected} == expected
        summary = dict(
            status="SCRIPTED_SANDBOX_COMPONENT_CANARY_PASS",
            source_commit=COMMIT,
            actual_model_api_calls=0,
            scripted_queries=agent.n_calls + limited.n_calls,
            native_test=dict(passed=1, failed=1, expected_failure=True),
            source_unchanged=True,
            feedback_reaches_next_query=True,
            step_limit_stops=True,
            timeout_is_infrastructure=True,
            run_ids=[a["run_id"] for a in actions],
            wall_seconds=time.monotonic() - started,
            versions={
                n: importlib.metadata.version(n)
                for n in ("pydantic", "jinja2", "rich", "python-dotenv", "platformdirs")
            },
            priced_total=None,
            boundary="Scripted known fixture; custom sandbox Environment, not unmodified upstream environments, real model/provider, full suite, discovery case or efficacy experiment.",
        )
        record("summary.json", summary)
        print(json.dumps(summary))
    except BaseException as exc:
        record(
            "failure.json",
            dict(type=type(exc).__name__, message=str(exc), uncertain=uncertain),
        )
        raise
    finally:
        if not uncertain:
            record("release.json", client.call("release", dict(session_id=session_id)))


if __name__ == "__main__":
    main()
