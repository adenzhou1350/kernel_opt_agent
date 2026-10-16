"""Capture one reviewed Go/Rust/pytest/GoogleTest/Node/Vitest CPU command on POSIX.

No downloads, environment provisioning, SSH, model calls or queue mutations.
This is execution/log accounting, not a sandbox or a PR qualification oracle.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import selectors
import signal
import subprocess
import time
from pathlib import Path

import scout_native_results as native

RUNTIME_FILES = ("scout_native_run.py", "scout_native_results.py", "qualification_source_bundle.py")


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


def run(*, cwd, output, command, sources, format, expected_tests, package=None,
        timeout=120, environment=None, _gpu_uuid=None):
    invocation_started = time.monotonic()
    if os.name != "posix":
        raise ValueError("execute on an authorized POSIX worker; do not start local WSL")
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
    if format == "gtest-xml" and any(
        arg.startswith(("--gtest_output", "--gtest_repeat")) for arg in command[1:]
    ):
        raise ValueError("the runner owns the fresh GoogleTest report; repeated runs overwrite XML")
    before = source_identities(cwd, sources)
    # Validate accounting inputs before executing anything, including empty targets.
    native.summarize("", format=format, exit_code=0,
                     expected_tests=expected_tests, package=package)
    environment = dict(environment or {})
    if any(not isinstance(key, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key)
           or not isinstance(value, str) or "\0" in value
           for key, value in environment.items()):
        raise ValueError("invalid process environment override")
    if format == "gtest-xml" and any(
        key in environment or key in os.environ for key in ("GTEST_OUTPUT", "GTEST_REPEAT")
    ):
        raise ValueError("GoogleTest output/repeat environment must be unset for fresh single-run capture")
    # Only the owner-reviewed GPU companion uses this library hook. The CLI
    # remains CPU-only; device admission/locking is the companion's responsibility.
    visible = "" if _gpu_uuid is None else _gpu_uuid
    if _gpu_uuid is not None and (format != "pytest-junit" or not isinstance(visible, str)
                                 or not re.fullmatch(
                                     r"GPU-[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", visible)):
        raise ValueError("GPU library hook requires pytest and a full GPU UUID")
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
    started = time.monotonic()
    reason, written = None, 0
    post_exit_group_wait_seconds, post_exit_group_cleanup_required = 0.0, False
    # Keep output off RAM; cap both the file and the later parser input.
    with (output / "terminal.log").open("xb") as log:
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
                    stop_group(process)
            process.stdout.close()
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
            if format in {"pytest-junit", "vitest-json", "gtest-xml"}:
                report_name = {"pytest-junit": "junit.xml", "vitest-json": "vitest.json",
                               "gtest-xml": "gtest.xml"}[format]
                report_path = output / report_name
                if report_path.is_symlink() or not report_path.is_file():
                    raise ValueError("missing or non-regular test report")
                with report_path.open("rb") as stream:
                    raw = stream.read(native.MAX_BYTES + 1)
                if len(raw) > native.MAX_BYTES:
                    raise ValueError("test report exceeds 2 MiB; no partial-report verdict")
                text = raw.decode("utf-8")
                report = {"path": str(report_path), "sha256": hashlib.sha256(raw).hexdigest()}
            summary = native.summarize(text, format=format, exit_code=process.returncode,
                                       expected_tests=expected_tests, package=package)
        except UnicodeError:
            issues.append("log or test report is not UTF-8")
        except (OSError, ValueError) as error:
            issues.append(str(error))
    result = {"status": "INCONCLUSIVE" if issues else summary["status"],
              "issues": issues, "summary": summary, "exit_code": process.returncode,
              "wall_seconds": time.monotonic() - invocation_started,
              "command_wall_seconds": command_wall_seconds, "cwd": str(cwd),
              "post_exit_group_wait_seconds": post_exit_group_wait_seconds,
              "post_exit_group_cleanup_required": post_exit_group_cleanup_required,
              "command": list(command), "tool_path": str(executable), "tool_sha256": tool_hash,
              "source_before": before, "source_after": after,
              "terminal_log_sha256": digest(output / "terminal.log"),
              "test_report": report,
              "environment_sha256": {key: hashlib.sha256(value.encode()).hexdigest()
                                     for key, value in sorted(environment.items())},
              "boundary": "Reviewed command only; selected file/tool observations do not prove "
                          "the executed binary corresponds to source, full dependency identity, "
                          "test quality, isolation, performance or PR readiness."}
    (output / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


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
                        help="copy the three stdlib-only CPU tools into a fresh directory; do not execute")
    parser.add_argument("--cwd", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--format", choices=native.FORMATS)
    parser.add_argument("--package")
    parser.add_argument("--expect-test", action="append")
    parser.add_argument("--source", action="append")
    parser.add_argument("--env", action="append", default=[])
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.export_runtime is not None:
        if any((args.cwd, args.output, args.format, args.package, args.expect_test,
                args.source, args.env, args.command)) or args.timeout != 120:
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
                     environment=dict(assignments(args.env, environment=True)), timeout=args.timeout)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(result))
    return {"TESTS_PASSED": 0, "TESTS_FAILED": 1, "INCONCLUSIVE": 2}[result["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
