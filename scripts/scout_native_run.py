"""Capture one reviewed Go/Rust CPU test command on an authorized POSIX worker.

No downloads, environment provisioning, SSH, model calls or queue mutations.
This is execution/log accounting, not a sandbox or a PR qualification oracle.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import signal
import subprocess
import time

import scout_native_results as native


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


def run(*, cwd, output, command, sources, format, expected_tests, package=None,
        timeout=120, environment=None):
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
    before = source_identities(cwd, sources)
    # Validate accounting inputs before executing anything, including empty targets.
    native.summarize("", format=format, exit_code=0,
                     expected_tests=expected_tests, package=package)
    environment = dict(environment or {})
    if any(not isinstance(key, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key)
           or not isinstance(value, str) or "\0" in value
           for key, value in environment.items()):
        raise ValueError("invalid process environment override")
    if environment.get("CUDA_VISIBLE_DEVICES", "") != "":
        raise ValueError("this entrance is CPU-only; use a separately reviewed GPU runner")
    environment["CUDA_VISIBLE_DEVICES"] = ""
    tool_hash = digest(executable)
    output = Path(output)
    output.mkdir(parents=False, exist_ok=False)
    started = time.monotonic()
    reason, written = None, 0
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
    summary = None
    if not issues:
        try:
            summary = native.summarize((output / "terminal.log").read_text(encoding="utf-8"),
                                       format=format, exit_code=process.returncode,
                                       expected_tests=expected_tests, package=package)
        except UnicodeError:
            issues.append("log is not UTF-8")
    result = {"status": "INCONCLUSIVE" if issues else summary["status"],
              "issues": issues, "summary": summary, "exit_code": process.returncode,
              "wall_seconds": time.monotonic() - invocation_started,
              "command_wall_seconds": command_wall_seconds, "cwd": str(cwd),
              "command": list(command), "tool_path": str(executable), "tool_sha256": tool_hash,
              "source_before": before, "source_after": after,
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cwd", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--format", choices=("go-json", "rust-libtest"), required=True)
    parser.add_argument("--package")
    parser.add_argument("--expect-test", action="append", required=True)
    parser.add_argument("--source", action="append", required=True)
    parser.add_argument("--env", action="append", default=[])
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
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
