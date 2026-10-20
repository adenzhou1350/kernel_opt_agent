"""Optional agent Environment over the configured CPU broker, never a host shell.

The caller owns health/create/write/release and reviews the task/source scope.
Dynamic commands require explicit opt-in; this is not a VM for hostile code.
Only the injected broker client can execute, and uncertain outcomes stop reuse.
"""

from __future__ import annotations

import math
import re
import time


class SandboxFailure(RuntimeError):
    """Infrastructure/budget failure, not a target assertion or syntax error."""


def require_text_submission(native_finish, *, marker):
    """Optional task-output contract, not a change to an agent's native parser.

    A patch benchmark may validly submit no text. Read-only investigations may
    instead require a conclusion. An empty marker remains a successful shell
    command, but gets task feedback rather than ending that investigation.
    This checks presence only, never truth or adequacy of the supplied text.
    """
    if (not callable(native_finish) or not isinstance(marker, str) or not marker
            or marker != marker.strip() or len(marker) > 128 or "\n" in marker or "\r" in marker):
        raise ValueError("supply a native finish callback and a literal single-line marker")

    def finish(environment, output):
        lines = output.get("output", "").lstrip().splitlines(keepends=True)
        if (output.get("returncode") == 0 and lines and lines[0].strip() == marker
                and not "".join(lines[1:]).strip()):
            environment.record(f"action-{environment.attempts}-submission-rejected.json", {
                "reason": "task requires nonempty final text", "shell_returncode": 0,
                "boundary": "Output presence only; raw action result is retained unchanged."})
            output["output"] += (
                "\nTASK_OUTPUT_INCOMPLETE: This command exited 0 but supplied no final text. "
                "Within the remaining budget, print the marker followed by your honest "
                "conclusion, executed checks and uncertainty. No extra budget is granted.\n")
            return
        native_finish(environment, output)

    return finish


def cpu_health_matches(health, image):
    """Shared receipt check, not a new discovery or an execution authority."""
    if not isinstance(health, dict) or not isinstance(health.get("limits"), dict):
        return False
    limits = health["limits"]
    return (health.get("ready") is True and health.get("backend") == "docker-cpu"
            and health.get("network") == "none" and health.get("image") == image
            and isinstance(image, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", image) is not None
            and limits.get("memory_mib") == 512 and limits.get("pids") == 64 and limits.get("cpus") == 1)


def cpu_isolation_matches(raw):
    """Reuse the same pinned CPU controls in comparison and agent adapters."""
    isolation = raw.get("isolation") if isinstance(raw, dict) else None
    return isinstance(isolation, dict) and (
        isolation.get("NetworkMode") == "none" and isolation.get("ReadonlyRootfs") is True
        and isolation.get("Privileged") is False and isolation.get("Binds") in (None, [])
        and isolation.get("Devices") in (None, []) and isolation.get("Memory") == 512 * 1024**2
        and isolation.get("MemorySwap") == 512 * 1024**2 and isolation.get("NanoCpus") == 1_000_000_000
        and isolation.get("PidsLimit") == 64 and isolation.get("CapDrop") == ["ALL"]
        and isinstance(isolation.get("SecurityOpt"), list)
        and "no-new-privileges:true" in isolation["SecurityOpt"]
    )


class CPUSandboxEnvironment:
    def __init__(self, call, *, session, health, record, finish=None,
                 allowed_commands=(), allow_dynamic_commands=False,
                 max_actions=8, command_timeout=5, wall_seconds=300):
        if (not callable(call) or not callable(record) or not isinstance(session, dict)
                or (finish is not None and not callable(finish))
                or session.get("profile") != "cpu" or session.get("released") is True
                or not isinstance(session_id := session.get("id"), str)
                or not re.fullmatch(r"[0-9a-f]{24}", session_id)):
            raise ValueError("supply a configured client, owned CPU session and recorder")
        if not cpu_health_matches(health, health.get("image") if isinstance(health, dict) else None):
            raise ValueError("reviewed offline CPU broker health is required")
        if (type(max_actions) is not int or not 1 <= max_actions <= 64
                or type(command_timeout) is not int or not 1 <= command_timeout <= 60
                or type(wall_seconds) not in (int, float) or not math.isfinite(wall_seconds)
                or not 1 <= wall_seconds <= 3600
                or type(allow_dynamic_commands) is not bool):
            raise ValueError("invalid agent execution budget")
        if (not isinstance(allowed_commands, (list, tuple, set, frozenset)) or len(allowed_commands) > 64
                or any(not isinstance(c, str) or not c or len(c.encode()) > 8192 or "\0" in c for c in allowed_commands)):
            raise ValueError("supply at most 64 literal command strings")
        allowed = frozenset(allowed_commands)
        if (allow_dynamic_commands and allowed) or not (allow_dynamic_commands or allowed):
            raise ValueError("choose literal reviewed commands or explicit dynamic mode")
        self.call, self.record, self.finish = call, record, finish
        self.session_id, self.image = session_id, health["image"]
        self.allowed, self.allow_dynamic_commands = allowed, allow_dynamic_commands
        self.max_actions, self.command_timeout = max_actions, command_timeout
        self.wall_seconds = wall_seconds
        self.deadline = time.monotonic() + wall_seconds
        self.attempts, self.results = 0, []
        self.uncertain, self.failed = False, False

    def _check_action(self, action, cwd=""):
        if (not isinstance(action, dict) or set(action) - {"command", "tool_call_id"}
                or not isinstance(command := action.get("command"), str)
                or not command or "\0" in command or len(command.encode()) > 8192
                or ("tool_call_id" in action and (
                    not isinstance(action["tool_call_id"], str) or not action["tool_call_id"]
                )) or cwd not in ("", "/work")):
            raise ValueError("invalid sandbox agent action")
        if not self.allow_dynamic_commands and command not in self.allowed:
            raise ValueError("command is outside the reviewed literal set")
        return command

    def check_action_capacity(self):
        """Return usable action slots without dispatch, reservation or charging.

        A caller that requires a native action even to submit can use this
        BEFORE a model request. Do not use it to forbid a legitimate tool-free
        final answer. Provider/query/token budgets remain the caller's concern;
        a later execute still checks actual time and records its own attempt.
        """
        if self.uncertain or self.failed:
            raise SandboxFailure("inspect retained history/evidence before any new execution")
        remaining = self.max_actions - self.attempts
        if remaining <= 0 or self.deadline - time.monotonic() < 1:
            raise SandboxFailure("agent action or wall budget exhausted before model request")
        return remaining

    def check_actions(self, actions):
        """Optional whole-response preflight before native sequential execution.

        This neither executes nor reserves actions. The single owning loop must
        call it immediately before dispatch; each execute still checks its real
        budget, records its own intent/result and stops on uncertainty. Reject
        the whole response rather than silently truncate or merge commands.
        A rejected response still costs its caller's real model query/tokens.
        """
        if self.uncertain or self.failed:
            raise SandboxFailure("inspect retained history/evidence before any new execution")
        if not isinstance(actions, list) or not actions or len(actions) > 64:
            raise ValueError("supply a nonempty native action list of at most 64 entries")
        if len(actions) > self.max_actions - self.attempts or self.deadline - time.monotonic() < 1:
            raise SandboxFailure("agent action or wall budget exhausted before batch dispatch")
        call_ids = set()
        for action in actions:
            self._check_action(action)
            if (call_id := action.get("tool_call_id")) is not None:
                if call_id in call_ids:
                    raise ValueError("duplicate tool_call_id in native action batch")
                call_ids.add(call_id)

    def execute(self, action, cwd="", *, timeout=None):
        if self.uncertain or self.failed:
            raise SandboxFailure("inspect retained history/evidence before any new execution")
        command = self._check_action(action, cwd)
        limit = self.command_timeout if timeout is None else timeout
        if type(limit) is not int or not 1 <= limit <= 60:
            raise ValueError("command timeout must be 1..60 seconds")
        remaining = self.deadline - time.monotonic()
        if self.attempts >= self.max_actions or remaining < 1:
            raise SandboxFailure("agent action or wall budget exhausted")
        number = self.attempts + 1
        request = {"session_id": self.session_id, "command": command,
                   "timeout": min(limit, int(remaining))}
        self.record(f"action-{number}-intent.json", {"request": request, "action": action})
        self.attempts = number
        self.uncertain = True
        result = self.call("run", request)
        self.results.append(result)
        self.record(f"action-{number}-result.json", result)
        if not isinstance(result, dict):
            raise SandboxFailure("malformed broker result; inspect the same invocation")
        if (result.get("image") != self.image or result.get("profile") != "cpu"
                or result.get("container_removed") is not True or not cpu_isolation_matches(result)):
            raise SandboxFailure("broker isolation/cleanup mismatch; inspect retained evidence")
        self.uncertain = False
        if (result.get("status") != "completed" or result.get("termination") is not None
                or result.get("oom_killed") is not False
                or result.get("workspace_persisted") is not True
                or type(result.get("exit_code")) is not int
                or not all(isinstance(result.get(k), str) for k in ("stdout", "stderr"))
                or len((result["stdout"] + result["stderr"]).encode()) > 32768):
            self.failed = True
            raise SandboxFailure(str(result.get("termination") or result.get("error") or "incomplete execution"))
        output = {"output": result["stdout"] + result["stderr"],
                  "returncode": result["exit_code"], "exception_info": ""}
        if self.finish:
            self.finish(self, output)
        return output

    def get_template_vars(self, **kwargs):
        return {**kwargs, "cwd": "/work", "system": "Linux"}

    def serialize(self):
        return {"info": {"config": {"environment_type": "explicit_cpu_sandbox_adapter",
                "environment": {"session_id": self.session_id, "profile": "cpu", "image": self.image,
                                "dynamic_commands": self.allow_dynamic_commands,
                                "allowed_commands": sorted(self.allowed),
                                "max_actions": self.max_actions,
                                "command_timeout": self.command_timeout,
                                "wall_seconds": self.wall_seconds}}}}
