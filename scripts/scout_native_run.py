"""Capture one reviewed native CPU command on POSIX or opt-in Windows.

No downloads, environment provisioning, SSH, model calls or queue mutations.
This is execution/log accounting, not a sandbox or a PR qualification oracle.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import selectors
import signal
import subprocess
import time
from pathlib import Path

import scout_native_results as native

RUNTIME_FILES = ("scout_native_run.py", "scout_native_results.py", "qualification_source_bundle.py",
                 "scout_native_windows.py", "scout_bun_junit.py", "scout_dependency_tree.py",
                 "scout_unittest.py", "scout_catch2_xml.py")


def export_runtime(output):
    """Copy the small stdlib-only CPU tool set into a fresh directory.

    No subprocess, target code, install, network or credential acquisition.
    Returned hashes identify these snapshots, not a project/environment approval.
    A write failure leaves a partial fresh directory, never an export success.
    """
    library = Path(__file__).absolute().parent
    snapshots = {}
    for name in RUNTIME_FILES:
        path = library / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"missing or non-regular runtime source: {name}")
        with path.open("rb") as stream:
            body = stream.read(512 * 1024 + 1)
        if len(body) > 512 * 1024:
            raise ValueError(f"runtime source exceeds export budget: {name}")
        compile(body, name, "exec")
        snapshots[name] = body
    output = Path(output).absolute()
    output.mkdir(exist_ok=False)
    records = {}
    for name, body in snapshots.items():
        with (output / name).open("xb") as stream:
            stream.write(body)
        records[name] = {"bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}
    return {"status": "EXPORTED", "directory": str(output), "files": records,
            "boundary": "Tool-source snapshots only; no target tests, environment qualification or execution authority."}


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(256 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def source_identities(cwd, sources):
    if not 1 <= len(sources) <= 64 or len(dict(sources)) != len(sources):
        raise ValueError("supply 1..64 distinct reviewed source paths")
    result = {}
    for relative, expected in sources:
        path = Path(relative)
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise ValueError("source paths must be relative to the test checkout")
        target = cwd / path
        if not target.resolve().is_relative_to(cwd) or any(
            (cwd.joinpath(*path.parts[:i])).is_symlink()
            for i in range(1, len(path.parts) + 1)
        ):
            raise ValueError("source path escapes checkout or contains a symlink")
        if not target.is_file() or target.stat().st_size > 8 * 1024 * 1024:
            raise ValueError("source must be a regular file no larger than 8 MiB")
        actual = digest(target)
        if actual != expected:
            raise ValueError(f"source identity mismatch: {relative}")
        result[relative] = actual
    return result


def stop_group(process):
    # The group belongs to the child started below, not an inventory PID.
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            pass
        if sig == signal.SIGTERM:
            time.sleep(0.1)
    process.wait(timeout=5)


def wait_for_group_exit(pgid, deadline):
    """Allow bounded natural shutdown; never classify a still-present group as gone."""
    while True:
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(0.01, remaining))


def observe_owned_group(pgid, *, proc_root=Path("/proc"), scan_limit=8192, member_limit=32):
    """Bounded Linux diagnostics only; never establish that cleanup succeeded."""
    if (type(pgid) is not int or pgid <= 0
            or type(scan_limit) is not int or not 1 <= scan_limit <= 8192
            or type(member_limit) is not int or not 1 <= member_limit <= 32):
        raise ValueError("invalid owned-group observation bounds")
    result = {"source": "linux_proc_stat", "available": False, "members": [],
              "scanned": 0, "unreadable": 0, "scan_truncated": False,
              "members_truncated": False}
    try:
        with os.scandir(proc_root) as entries:
            result["available"] = True
            for entry in entries:
                if not entry.name.isascii() or not entry.name.isdigit():
                    continue
                if result["scanned"] >= scan_limit:
                    result["scan_truncated"] = True
                    break
                result["scanned"] += 1
                try:
                    with (Path(entry.path) / "stat").open("rb") as stream:
                        raw = stream.read(4097)
                    if len(raw) > 4096:
                        raise ValueError("overlong process stat")
                    prefix, suffix = raw.decode("utf-8", errors="replace").rsplit(")", 1)
                    pid, name = prefix.split(" (", 1)
                    fields = suffix.split()
                    if int(pid) != int(entry.name) or len(fields) < 20:
                        raise ValueError("malformed process stat")
                    ppid, group, session, start_ticks = map(int, (fields[1], fields[2], fields[3], fields[19]))
                    if group != pgid or session != pgid:
                        continue
                    if len(result["members"]) >= member_limit:
                        result["members_truncated"] = True
                        continue
                    result["members"].append({"pid": int(pid), "ppid": ppid,
                        "pgrp": group, "session": session, "state": fields[0],
                        "start_ticks": start_ticks, "name": name[:64]})
                except (OSError, ValueError, IndexError):
                    result["unreadable"] += 1
    except OSError as error:
        result["error"] = type(error).__name__
    result["members"].sort(key=lambda member: member["pid"])
    return result


def reaped_child_cpu():
    """Process-wide POSIX counters, not a complete owned-process-tree meter."""
    try:
        value = os.times()
        return value.children_user, value.children_system
    except OSError:
        return None


def reaped_child_cpu_delta(before, after):
    """Keep unavailable/regressed readings unknown, never a free failed run.

    Includes other children reaped concurrently by this runner process; excludes
    descendants whose usage is not propagated through a waited parent. Prefer
    one sequential CLI invocation when interpreting these observed counters.
    """
    result = {"method": "posix_process_reaped_children_delta",
              "user_seconds": None, "system_seconds": None}
    if before is None or after is None:
        return result
    values = (*before, *after)
    if (len(before) != 2 or len(after) != 2
            or any(type(v) not in (int, float) or not math.isfinite(v) or v < 0
                   for v in values)
            or any(a < b for b, a in zip(before, after))):
        return result
    return dict(result, user_seconds=after[0] - before[0],
                system_seconds=after[1] - before[1])


def run(*, cwd, output, command, sources, format, expected_tests, package=None,
        timeout=120, environment=None, _gpu_uuid=None, native_windows=False,
        _execution_guard=None):
    invocation_started = time.monotonic()
    if os.name != "posix" and not (os.name == "nt" and native_windows):
        raise ValueError("execute on an authorized POSIX worker; do not start local WSL")
    if native_windows and (os.name != "nt" or _gpu_uuid is not None):
        raise ValueError("--native-windows requires native Windows and CPU-only execution")
    if _execution_guard is not None and (
        _gpu_uuid is None or not callable(_execution_guard)
        or not isinstance(getattr(_execution_guard, "evidence", None), dict)
    ):
        raise ValueError("execution guard requires the owner GPU hook and a bounded evidence dict")
    if not 0 < timeout <= 3600:
        raise ValueError("timeout must be within 0..3600 seconds")
    cwd = Path(cwd).resolve(strict=True)
    if not cwd.is_dir():
        raise ValueError("test checkout must be a directory")
    if not command or not Path(command[0]).is_absolute():
        raise ValueError("use an absolute path to the reviewed test executable")
    executable = Path(command[0]).resolve(strict=True)
    command = list(command)
    if format == "pytest-junit" and any(
        arg.startswith(("--junitxml", "--junit-xml")) for arg in command[1:]
    ):
        raise ValueError("the runner owns the fresh pytest JUnit report path")
    if format == "vitest-json" and any(
        arg.startswith(("--reporter", "--outputFile", "--output-file")) for arg in command[1:]
    ):
        raise ValueError("the runner owns the fresh Vitest JSON reporter and report path")
    if format == "bun-junit" and any(arg.startswith('--reporter') for arg in command[1:]):
        raise ValueError("the runner owns the fresh Bun JUnit reporter and report path")
    if format == "gtest-xml" and any(
        arg.startswith(("--gtest_output", "--gtest_repeat")) for arg in command[1:]
    ):
        raise ValueError("the runner owns the fresh GoogleTest report; repeated runs overwrite XML")
    if format == "catch2-v2-xml" and any(
        arg == "--" or (arg.startswith("-") and not arg.startswith("--"))
        or arg.startswith(("--reporter", "--out", "--success")) for arg in command[1:]
    ):
        raise ValueError("the runner owns Catch2 v2 XML/success/output options; use long forms for other options")
    before = source_identities(cwd, sources)
    # Validate accounting inputs before executing anything, including empty targets.
    native.summarize("", format=format, exit_code=0,
                     expected_tests=expected_tests, package=package)
    environment = dict(environment or {})
    if any(not isinstance(key, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key)
           or not isinstance(value, str) or "\0" in value
           for key, value in environment.items()):
        raise ValueError("invalid process environment override")
    if native_windows:
        if len({key.upper() for key in environment}) != len(environment):
            raise ValueError("duplicate case-insensitive Windows environment override")
        environment = {key.upper(): value for key, value in environment.items()}
    if format == "gtest-xml" and any(
        key in environment or key in os.environ for key in ("GTEST_OUTPUT", "GTEST_REPEAT")
    ):
        raise ValueError("GoogleTest output/repeat environment must be unset for fresh single-run capture")
    # Only the owner-reviewed GPU companion uses this library hook. The CLI
    # remains CPU-only; device admission/locking is the companion's responsibility.
    visible = "" if _gpu_uuid is None else _gpu_uuid
    devices = visible.split(",") if isinstance(visible, str) else []
    if _gpu_uuid is not None and (format != "pytest-junit" or not 1 <= len(devices) <= 8
            or len({item.lower() for item in devices}) != len(devices)
            or any(not re.fullmatch(
                r"GPU-[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", item)
                for item in devices)):
        raise ValueError("GPU library hook requires pytest and 1..8 distinct full GPU UUIDs")
    if environment.get("CUDA_VISIBLE_DEVICES", visible) != visible:
        raise ValueError("this entrance is CPU-only; use a separately reviewed GPU runner")
    environment["CUDA_VISIBLE_DEVICES"] = visible
    tool_hash = digest(executable)
    output = Path(output).resolve()
    output.mkdir(parents=False, exist_ok=False)
    if format == "pytest-junit":
        command.append(f"--junitxml={output / 'junit.xml'}")
    elif format == "vitest-json":
        command.extend(["--reporter=json", f"--outputFile={output / 'vitest.json'}"])
    elif format == "gtest-xml":
        command.append(f"--gtest_output=xml:{output / 'gtest.xml'}")
    elif format == "bun-junit":
        command.extend(['--reporter=junit', f"--reporter-outfile={output / 'bun.xml'}"])
    elif format == "catch2-v2-xml":
        command.extend(["--reporter", "xml", "--success", "--out", str(output / "catch2.xml")])
    started = time.monotonic()
    if native_windows:
        import scout_native_windows
        with (output / "terminal.log").open("xb") as log:
            captured = scout_native_windows.capture(
                command=command, cwd=cwd, output=output, environment={**os.environ, **environment},
                timeout=timeout, max_bytes=native.MAX_BYTES, log=log)
    else:
        guard_options = {} if _execution_guard is None else {"guard": _execution_guard}
        captured = capture_posix(command=command, cwd=cwd, output=output,
                                 environment=environment, timeout=timeout, started=started,
                                 **guard_options)
    reason, returncode = captured["reason"], captured["exit_code"]
    post_exit_group_wait_seconds = captured["post_exit_group_wait_seconds"]
    post_exit_group_cleanup_required = captured["post_exit_group_cleanup_required"]
    command_wall_seconds = time.monotonic() - started
    issues = [reason] if reason else []
    try:
        after = source_identities(cwd, sources)
    except (OSError, ValueError) as error:
        after = None
        issues.append(str(error))
    try:
        if digest(executable) != tool_hash:
            issues.append("test executable changed during execution")
    except OSError as error:
        issues.append(str(error))
    summary, report = None, None
    if not issues:
        try:
            text = (output / "terminal.log").read_text(encoding="utf-8")
            if format in native.REPORT_FILES:
                report_path = output / native.REPORT_FILES[format]
                if report_path.is_symlink() or not report_path.is_file():
                    raise ValueError("missing or non-regular test report")
                with report_path.open("rb") as stream:
                    raw = stream.read(native.MAX_BYTES + 1)
                if len(raw) > native.MAX_BYTES:
                    raise ValueError("test report exceeds 2 MiB; no partial-report verdict")
                text = raw.decode("utf-8")
                report = {"path": str(report_path), "sha256": hashlib.sha256(raw).hexdigest()}
            summary = native.summarize(text, format=format, exit_code=returncode,
                                       expected_tests=expected_tests, package=package)
        except UnicodeError:
            issues.append("log or test report is not UTF-8")
        except (OSError, ValueError) as error:
            issues.append(str(error))
    result = {"status": "INCONCLUSIVE" if issues else summary["status"],
              "issues": issues, "summary": summary, "exit_code": returncode,
              "wall_seconds": time.monotonic() - invocation_started,
              "command_wall_seconds": command_wall_seconds, "cwd": str(cwd),
              "post_exit_group_wait_seconds": post_exit_group_wait_seconds,
              "post_exit_group_cleanup_required": post_exit_group_cleanup_required,
              "post_exit_group_observation": captured.get("post_exit_group_observation"),
              "process_backend": "windows-job" if native_windows else "posix-process-group",
              "cpu_accounting": captured["cpu_accounting"],
              "command": list(command), "tool_path": str(executable), "tool_sha256": tool_hash,
              "source_before": before, "source_after": after,
              "terminal_log_sha256": digest(output / "terminal.log"),
              "test_report": report,
              "environment_sha256": {key: hashlib.sha256(value.encode()).hexdigest()
                                     for key, value in sorted(environment.items())},
              "boundary": "Reviewed command only; selected file/tool observations do not prove "
                          "the executed binary corresponds to source, full dependency identity, "
                          "test quality, isolation, performance or PR readiness."}
    if native_windows:
        result["windows_launcher_python"] = captured["launcher_python"]
        result["windows_job_cleanup_verified"] = captured["windows_job_cleanup_verified"]
    if _execution_guard is not None:
        result["execution_guard"] = _execution_guard.evidence
    (output / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def check_execution_guard(guard, phase):
    """Trusted owner hook: None continues; any error stops only our command."""
    if guard is None:
        return None
    try:
        reason = guard(phase)
    except Exception as error:
        return f"execution guard {phase} failed ({type(error).__name__})"
    if reason is None:
        return None
    if not isinstance(reason, str) or not reason.strip():
        return f"execution guard {phase} returned an invalid decision"
    return f"execution guard {phase}: {reason[:256]}"


def capture_posix(*, command, cwd, output, environment, timeout, started, guard=None):
    reason, written = None, 0
    cpu_before = reaped_child_cpu()
    post_exit_group_wait_seconds, post_exit_group_cleanup_required = 0.0, False
    post_exit_group_observation = None
    # Keep output off RAM; cap both the file and the later parser input.
    with (output / "terminal.log").open("xb") as log:
        reason = check_execution_guard(guard, "admission")
        if not reason and time.monotonic() - started >= timeout:
            reason = "wall timeout before command launch"
        if reason:
            return {"reason": reason, "exit_code": None,
                    "cpu_accounting": reaped_child_cpu_delta(cpu_before, reaped_child_cpu()),
                    "post_exit_group_wait_seconds": 0.0,
                    "post_exit_group_observation": None,
                    "post_exit_group_cleanup_required": False}
        process = subprocess.Popen(command, cwd=cwd, env={**os.environ, **environment},
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   start_new_session=True)
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                while selector.get_map():
                    remaining = timeout - (time.monotonic() - started)
                    if remaining <= 0:
                        reason = "wall timeout (including compilation and pipe closure)"
                        break
                    reason = check_execution_guard(guard, "running")
                    if reason:
                        break
                    for key, _ in selector.select(min(0.1, remaining)):
                        chunk = os.read(key.fd, 65536)
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        available = native.MAX_BYTES - written
                        log.write(chunk[:available])
                        written += min(len(chunk), available)
                        if len(chunk) > available:
                            reason = "log exceeds 2 MiB; no partial-log verdict"
                            break
                    if reason:
                        break
            if reason:
                stop_group(process)
            else:
                try:
                    # A child can close both output FDs and keep allocating.
                    # Keep monitoring until it exits, not only until pipe EOF.
                    if guard is not None:
                        while process.poll() is None:
                            remaining = timeout - (time.monotonic() - started)
                            if remaining <= 0:
                                raise subprocess.TimeoutExpired(command, timeout)
                            reason = check_execution_guard(guard, "running")
                            if reason:
                                stop_group(process)
                                break
                            time.sleep(min(0.1, remaining))
                    process.wait(timeout=max(0.01, timeout - (time.monotonic() - started)))
                except subprocess.TimeoutExpired:
                    reason = "wall timeout after output closure"
                    stop_group(process)
        finally:
            if process.poll() is None:
                stop_group(process)
            else:
                # EOF and a reaped leader do not prove descendants have exited:
                # a background child may close or redirect its output descriptors.
                # Python's forkserver can still be shutting down at leader exit.
                # Wait at most 0.5s, within the original command deadline. There
                # is no helper-name whitelist: every group must actually vanish.
                # Only query/signal the group created for this invocation.
                group_wait_started = time.monotonic()
                deadline = min(started + timeout, group_wait_started + 0.5)
                group_gone = wait_for_group_exit(process.pid, deadline)
                post_exit_group_wait_seconds = time.monotonic() - group_wait_started
                if not group_gone:
                    post_exit_group_cleanup_required = True
                    reason = reason or "owned process group remains after command exit"
                    try:
                        post_exit_group_observation = observe_owned_group(process.pid)
                    except Exception as error:
                        post_exit_group_observation = {
                            "source": "linux_proc_stat", "available": False,
                            "error": type(error).__name__}
                    finally:
                        stop_group(process)
            process.stdout.close()
    postflight_reason = check_execution_guard(guard, "postflight")
    reason = reason or postflight_reason
    return {"reason": reason, "exit_code": process.returncode,
            "cpu_accounting": reaped_child_cpu_delta(cpu_before, reaped_child_cpu()),
            "post_exit_group_wait_seconds": post_exit_group_wait_seconds,
            "post_exit_group_observation": post_exit_group_observation,
            "post_exit_group_cleanup_required": post_exit_group_cleanup_required}


def assignments(values, *, environment=False):
    pairs = []
    for value in values:
        key, separator, item = value.partition("=") if environment else value.rpartition("=")
        if not separator or not key:
            raise ValueError("expected PATH=SHA256 or NAME=VALUE")
        pairs.append((key, item))
    return pairs


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export-runtime", type=Path,
                        help="copy the stdlib-only CPU tools into a fresh directory; do not execute")
    parser.add_argument("--native-windows", action="store_true",
                        help="explicitly allow native Windows CPU capture using a private Job Object")
    parser.add_argument("--cwd", type=Path, help="test checkout; required for execution")
    parser.add_argument("--output", type=Path, help="fresh capture directory; required for execution")
    parser.add_argument("--format", choices=native.FORMATS, help="native report format; required for execution")
    parser.add_argument("--package")
    parser.add_argument("--expect-test", action="append", metavar="TEST_ID",
                        help="required for execution; repeat for each exact expected ID (pytest: CLASSNAME::NAME)")
    parser.add_argument("--source", action="append", metavar="RELATIVE_PATH=SHA256",
                        help="required for execution; repeat for reviewed raw file hashes, paths relative to --cwd")
    parser.add_argument("--env", action="append", default=[], metavar="NAME=VALUE",
                        help="reviewed child environment value; repeat for additional values")
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.export_runtime is not None:
        if any((args.cwd, args.output, args.format, args.package, args.expect_test,
                args.source, args.env, args.command, args.native_windows)) or args.timeout != 120:
            parser.error("--export-runtime cannot be combined with execution options")
        try:
            result = export_runtime(args.export_runtime)
        except (OSError, ValueError, SyntaxError) as error:
            parser.error(str(error))
        print(json.dumps(result))
        return 0
    missing = [name for name in ("cwd", "output", "format", "expect_test", "source")
               if getattr(args, name) is None]
    if missing:
        parser.error("required for execution: " + ", ".join("--" + name.replace("_", "-") for name in missing))
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    try:
        result = run(cwd=args.cwd, output=args.output, command=command,
                     sources=assignments(args.source), format=args.format,
                     expected_tests=args.expect_test, package=args.package,
                     environment=dict(assignments(args.env, environment=True)), timeout=args.timeout,
                     native_windows=args.native_windows)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(result))
    return {"TESTS_PASSED": 0, "TESTS_FAILED": 1, "INCONCLUSIVE": 2}[result["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
