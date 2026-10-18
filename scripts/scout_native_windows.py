"""Opt-in Windows capture for reviewed commands, not a security sandbox.

A trusted isolated base Python launcher joins a private Job Object before
starting target code. Avoid venv trampolines around that ownership boundary;
the reviewed target command and its venv are unchanged. Ordinary CreateProcess
descendants inherit that job. WMI/service launches are outside this contract.
No platform-policy fallback is attempted.
"""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

_LAUNCH_LOCK = threading.Lock()


class JobAPI:
    def __init__(self):
        if os.name != "nt":
            raise ValueError("Windows Job Object backend requires native Windows")
        self.dll = ctypes.WinDLL("kernel32", use_last_error=True)
        dword, size, handle = ctypes.c_uint32, ctypes.c_size_t, ctypes.c_void_p

        class Limits(ctypes.Structure):
            _fields_ = [("user", ctypes.c_int64), ("job_user", ctypes.c_int64),
                        ("flags", dword), ("min_ws", size), ("max_ws", size),
                        ("process_limit", dword), ("affinity", size),
                        ("priority", dword), ("scheduling", dword)]

        class Extended(ctypes.Structure):
            _fields_ = [("basic", Limits), ("io", ctypes.c_uint64 * 6),
                        ("process_memory", size), ("job_memory", size),
                        ("peak_process_memory", size), ("peak_job_memory", size)]

        class Accounting(ctypes.Structure):
            _fields_ = [("times", ctypes.c_int64 * 4), ("faults", dword),
                        ("total", dword), ("active", dword), ("terminated", dword)]

        self.Extended, self.Accounting = Extended, Accounting
        signatures = {
            "CreateJobObjectW": ([handle, ctypes.c_wchar_p], handle),
            "SetInformationJobObject": ([handle, ctypes.c_int, handle, dword], ctypes.c_int),
            "QueryInformationJobObject": ([handle, ctypes.c_int, handle, dword, handle], ctypes.c_int),
            "AssignProcessToJobObject": ([handle, handle], ctypes.c_int),
            "GetCurrentProcess": ([], handle),
            "TerminateJobObject": ([handle, dword], ctypes.c_int),
            "CloseHandle": ([handle], ctypes.c_int),
            "SetHandleInformation": ([handle, dword, dword], ctypes.c_int),
            "OpenProcess": ([dword, ctypes.c_int, dword], handle),
            "WaitForSingleObject": ([handle, dword], dword),
            "PeekNamedPipe": ([handle, handle, dword, handle, handle, handle], ctypes.c_int),
        }
        for name, (args, result) in signatures.items():
            function = getattr(self.dll, name)
            function.argtypes, function.restype = args, result

    def checked(self, name, *args):
        result = getattr(self.dll, name)(*args)
        if not result:
            raise ctypes.WinError(ctypes.get_last_error())
        return result

    def create(self):
        job = self.checked("CreateJobObjectW", None, None)
        try:
            limits = self.Extended()
            limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE; no breakaway.
            self.checked("SetInformationJobObject", job, 9, ctypes.byref(limits), ctypes.sizeof(limits))
            return job
        except BaseException:
            self.checked("CloseHandle", job)
            raise

    def active(self, job):
        info = self.Accounting()
        self.checked("QueryInformationJobObject", job, 1, ctypes.byref(info), ctypes.sizeof(info), None)
        return info.active

    def cpu_accounting(self, job):
        """Cumulative private-job CPU, including the trusted launcher."""
        info = self.Accounting()
        self.checked("QueryInformationJobObject", job, 1, ctypes.byref(info), ctypes.sizeof(info), None)
        if info.times[0] < 0 or info.times[1] < 0:
            raise ValueError("negative Windows job CPU counters")
        return {"method": "windows_private_job_including_launcher",
                "user_seconds": info.times[0] / 10_000_000,
                "system_seconds": info.times[1] / 10_000_000,
                "active_processes": info.active}

    def wait_empty(self, job, deadline):
        while self.active(job):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(0.01, remaining))
        return True

    def member_handles(self, job):
        # Capture wait handles before termination. ActiveProcesses can reach zero
        # before Windows releases a terminating child's working-directory handle.
        class Members(ctypes.Structure):
            _fields_ = [("assigned", ctypes.c_uint32), ("listed", ctypes.c_uint32),
                        ("pids", ctypes.c_size_t * 4096)]
        info, handles = Members(), []
        try:
            self.checked("QueryInformationJobObject", job, 3, ctypes.byref(info), ctypes.sizeof(info), None)
            if info.assigned != info.listed or info.listed > 4096:
                raise ValueError("Windows owned-job membership snapshot incomplete")
            for pid in info.pids[:info.listed]:
                handle = self.dll.OpenProcess(0x100000, False, pid)
                if handle:
                    handles.append(handle)
                elif ctypes.get_last_error() != 87:  # Already exited, not access denied.
                    raise ctypes.WinError(ctypes.get_last_error())
            return handles
        except BaseException:
            for handle in handles:
                self.checked("CloseHandle", handle)
            raise


def launcher(config_path):
    """Only this trusted, -I -S interpreter runs before job assignment."""
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    api = JobAPI()
    job = config["job"]
    assigned = False
    try:
        api.checked("AssignProcessToJobObject", job, api.dll.GetCurrentProcess())
        assigned = True
    finally:
        # Native descendants must not keep the kill-on-close handle alive.
        api.checked("CloseHandle", job)
    status = {"nonce": config["nonce"], "assigned": assigned}
    try:
        process = subprocess.Popen(config["command"], stdin=subprocess.DEVNULL, close_fds=True)
        status["exit_code"] = process.wait()
    except OSError as error:
        status["error"] = str(error)
    with Path(config["status"]).open("x", encoding="utf-8") as stream:
        json.dump(status, stream)
    return 0


def capture(*, command, cwd, output, environment, timeout, max_bytes, log):
    import msvcrt

    api, job, process = JobAPI(), None, None
    reason, returncode, written = None, None, 0
    members = []
    cleanup_required, cleanup_verified, wait_seconds = False, False, 0.0
    cpu = {"method": "windows_private_job_including_launcher",
           "user_seconds": None, "system_seconds": None, "active_processes": None}
    started = time.monotonic()
    nonce = uuid.uuid4().hex
    status_path = output / "windows-launch-status.json"
    config_path = output / "windows-launch.json"
    launcher_python = None
    try:
        # A venv executable may itself start Python and assign a competing job
        # after Python begins running. Join our job from the real interpreter,
        # not through that asynchronous wrapper. -I -S needs no venv packages.
        base_python = getattr(sys, "_base_executable", None) or sys.executable
        launcher_python = str(Path(base_python).resolve(strict=True))
        job = api.create()
        config = {"job": job, "nonce": nonce, "command": command, "status": str(status_path)}
        with config_path.open("x", encoding="utf-8") as stream:
            json.dump(config, stream)
        startup = subprocess.STARTUPINFO()
        startup.lpAttributeList = {"handle_list": [job]}
        # Narrow inheritance to this launcher; never inherit the handle into target code.
        with _LAUNCH_LOCK:
            api.checked("SetHandleInformation", job, 1, 1)
            try:
                process = subprocess.Popen(
                    [launcher_python, "-I", "-S", "-B", str(Path(__file__).resolve()), str(config_path)],
                    cwd=cwd, env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, close_fds=True, startupinfo=startup,
                )
            finally:
                api.checked("SetHandleInformation", job, 1, 0)
        pipe = msvcrt.get_osfhandle(process.stdout.fileno())
        while True:
            if time.monotonic() - started >= timeout:
                reason = "wall timeout (including compilation and pipe closure)"
                break
            available = ctypes.c_uint32()
            if not api.dll.PeekNamedPipe(pipe, None, 0, None, ctypes.byref(available), None):
                error = ctypes.get_last_error()
                if error == 109:  # ERROR_BROKEN_PIPE: all writers closed.
                    break
                raise ctypes.WinError(error)
            if available.value:
                chunk = os.read(process.stdout.fileno(), min(available.value, 65536))
                room = max_bytes - written
                log.write(chunk[:room])
                written += min(len(chunk), room)
                if len(chunk) > room:
                    reason = "log exceeds 2 MiB; no partial-log verdict"
                    break
            else:
                time.sleep(0.01)
        if not reason:
            try:
                process.wait(timeout=max(0.01, started + timeout - time.monotonic()))
            except subprocess.TimeoutExpired:
                reason = "wall timeout after output closure"
        if not reason:
            if process.returncode != 0:
                raise ValueError(f"Windows trusted launcher failed: exit {process.returncode}")
            wait_started = time.monotonic()
            cleanup_verified = api.wait_empty(job, min(started + timeout, wait_started + 0.5))
            wait_seconds = time.monotonic() - wait_started
            if not cleanup_verified:
                reason = "owned Windows job remains after command exit"
        if not reason:
            with status_path.open("rb") as stream:
                raw = stream.read(16385)
            if len(raw) > 16384:
                raise ValueError("Windows launcher status exceeds budget")
            status = json.loads(raw)
            if status.get("nonce") != nonce or status.get("assigned") is not True:
                raise ValueError("Windows launcher did not confirm job assignment")
            if "error" in status:
                reason = "Windows native launch failed: " + status["error"]
            elif type(status.get("exit_code")) is not int:
                raise ValueError("Windows launcher did not record native exit code")
            else:
                returncode = status["exit_code"]
    except (OSError, ValueError) as error:
        reason = "Windows capture unavailable: " + str(error)
    finally:
        try:
            if job is not None and (reason or not cleanup_verified):
                cleanup_required = bool(api.active(job))
                if cleanup_required:
                    members = api.member_handles(job)
                    api.checked("TerminateJobObject", job, 1)
                # The trusted launcher can fail before assignment. It is the only
                # exact Popen handle outside the job, never an inventory PID.
                if process is not None and process.poll() is None:
                    process.kill()
                if process is not None:
                    process.wait(timeout=5)
                deadline = time.monotonic() + 5
                cleanup_verified = api.wait_empty(job, deadline)
                for handle in members:
                    if api.dll.WaitForSingleObject(handle, max(0, int((deadline - time.monotonic()) * 1000))) != 0:
                        cleanup_verified = False
                if not cleanup_verified:
                    reason = (reason or "Windows cleanup failed") + "; owned job cleanup unverified"
        except (OSError, ValueError, subprocess.TimeoutExpired) as error:
            cleanup_verified = False
            reason = (reason or "Windows cleanup failed") + "; " + str(error)
        finally:
            for handle in members:
                api.checked("CloseHandle", handle)
            if process is not None:
                process.stdout.close()
            if job is not None:
                try:
                    cpu = api.cpu_accounting(job)
                except (OSError, ValueError):
                    pass  # Missing cost observation must not become zero or a test failure.
                api.checked("CloseHandle", job)
    return {"exit_code": returncode, "reason": reason,
            "post_exit_group_wait_seconds": wait_seconds,
            "post_exit_group_cleanup_required": cleanup_required,
            "cpu_accounting": cpu,
            "launcher_python": launcher_python,
            "windows_job_cleanup_verified": cleanup_verified}


if __name__ == "__main__":
    raise SystemExit(launcher(sys.argv[1]))
