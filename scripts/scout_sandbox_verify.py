"""Opt-in stdlib CPU comparison through an already reviewed agent-sandbox client.

No transport, credentials, installation or GPU selection lives in this adapter.
The owner supplies the installed client's call(action, arguments) and CPU image.
Child summaries remain untrusted; a passing screen is not upstream qualification.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import shlex
import time
from pathlib import Path

from kimi_scout_verify import CLAIM_SCOPE, HARNESS, parse_test_output, read_input
from scout_agent_sandbox_environment import cpu_health_matches, cpu_isolation_matches


class SandboxCPU:
    def __init__(self, call, *, image):
        if not callable(call) or not re.fullmatch(r"sha256:[0-9a-f]{64}", image):
            raise ValueError("supply a reviewed client and exact CPU image")
        self.call = call
        self.image = image

    def check_runtime(self, profile="stdlib"):
        if profile != "stdlib":
            raise ValueError("the installed CPU sandbox route supports stdlib only")
        observed = self.call("health")
        available = cpu_health_matches(observed, self.image)
        return {
            "available": available,
            "profile": profile,
            "image": self.image,
            "backend": "agent-sandbox-cpu",
            "qualified": False,
        }

    def verify(
        self,
        baseline,
        candidate,
        test,
        *,
        journal,
        timeout=30,
        profile="stdlib",
        module_path=None,
        source_commit=None,
    ):
        if (
            profile != "stdlib"
            or module_path is not None
            or source_commit is not None
            or type(timeout) is not int
            or not 1 <= timeout <= 60
        ):
            raise ValueError(
                "only bounded standalone stdlib CPU comparisons are supported"
            )
        contents = {
            k: read_input(v)
            for k, v in (
                ("baseline", baseline),
                ("candidate", candidate),
                ("test", test),
            )
        }
        hashes = {k: hashlib.sha256(v).hexdigest() for k, v in contents.items()}
        # Reserve before any remote side effect; never overwrite/replay a dispatch.
        with Path(journal).open("x", encoding="utf-8") as stream:

            def record(value):
                stream.write(json.dumps(value, ensure_ascii=True) + "\n")
                stream.flush()

            def call(action, arguments):
                safe = {
                    k: v
                    for k, v in arguments.items()
                    if k not in {"content_base64", "command"}
                }
                record({"action": action, "state": "STARTED_OUTCOME_UNCERTAIN", **safe})
                result = self.call(action, arguments)
                record({"action": action, "state": "RETURNED", "result": result})
                return result

            record({"image": self.image, "input_sha256": hashes, "qualified": False})
            if not self.check_runtime(profile)["available"]:
                raise ValueError("reviewed CPU sandbox runtime is unavailable")
            sessions = []
            # On transport/cleanup uncertainty, leave the session handle in this
            # journal for history/evidence inspection. Never run the other arm.
            session = call("create", {"profile": "cpu", "ttl": 600})["id"]
            sessions.append(session)
            for name, content in (
                ("subject.py", contents["baseline"]),
                ("test_subject.py", contents["test"]),
            ):
                call(
                    "write",
                    {
                        "session_id": session,
                        "path": name,
                        "content_base64": base64.b64encode(content).decode(),
                    },
                )
            checkpoint = call("checkpoint", {"session_id": session})["checkpoint_id"]
            command = "python3 -I -B -c " + shlex.quote(
                HARNESS.replace("'/input'", "'/work'")
            )

            def run(sid, subject_hash):
                started = time.monotonic()
                raw = call(
                    "run", {"session_id": sid, "command": command, "timeout": timeout}
                )
                output = raw.get("stdout", "") + raw.get("stderr", "")
                count, summary = parse_test_output(output)
                isolated = cpu_isolation_matches(raw)
                inputs_match = raw.get("workspace_sha256", {}) == {
                    "subject.py": subject_hash,
                    "test_subject.py": hashes["test"],
                }
                cleanup = raw.get("container_removed") is True
                inconclusive = (
                    raw.get("status") != "completed"
                    or raw.get("profile") != "cpu"
                    or raw.get("image") != self.image
                    or bool(raw.get("termination"))
                    or raw.get("oom_killed") is not False
                    or raw.get("workspace_persisted") is not True
                    or not cleanup
                    or not isolated
                    or not inputs_match
                    or not count
                    or summary is None
                )
                return {
                    "profile": profile,
                    "claim_scope": CLAIM_SCOPE,
                    "exit_code": raw.get("exit_code"),
                    "seconds": time.monotonic() - started,
                    "cleanup_ok": cleanup,
                    "inconclusive": bool(inconclusive),
                    "reported_tests_run": count,
                    "test_summary": summary,
                    "output": output,
                    "session_id": sid,
                    "run_id": raw.get("run_id"),
                    "broker_evidence": raw,
                }

            before = run(session, hashes["baseline"])
            if before["inconclusive"]:
                fixed = {
                    "inconclusive": True,
                    "cleanup_ok": False,
                    "skipped": "baseline infrastructure uncertain; inspect journal",
                }
            else:
                restored = call(
                    "restore", {"session_id": session, "checkpoint_id": checkpoint}
                )["id"]
                sessions.append(restored)
                call(
                    "write",
                    {
                        "session_id": restored,
                        "path": "subject.py",
                        "content_base64": base64.b64encode(
                            contents["candidate"]
                        ).decode(),
                    },
                )
                fixed = run(restored, hashes["candidate"])
            inconclusive = before["inconclusive"] or fixed["inconclusive"]
            if not inconclusive:
                for sid in sessions:
                    call("release", {"session_id": sid})
            return {
                "label": "TEST_RESULT_NOT_PR_READY",
                "profile": profile,
                "backend": "agent-sandbox-cpu",
                "claim_scope": CLAIM_SCOPE,
                "image": self.image,
                "input_sha256": hashes,
                "before": before,
                "fixed": fixed,
                "inconclusive": inconclusive,
            }
