"""Opt-in known-fixture control for pytest plugin import order; no installs."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import xml.etree.ElementTree as ET


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, required=True, help="fresh private output directory"
    )
    args = parser.parse_args(argv)
    output = args.output.absolute()
    output.mkdir(parents=True, exist_ok=False)
    fixture = Path(__file__).with_name("test_startup.py").resolve()
    fixture_hash = hashlib.sha256(fixture.read_bytes()).hexdigest()
    # Metadata reads do not pre-import the plugins we are about to register.
    versions = {
        name: importlib.metadata.version(name)
        for name in (
            "pytest",
            "pytest-asyncio",
            "pytest-mock",
            "pytest-repeat",
            "pytest-timeout",
            "typing-extensions",
        )
    }
    common = [
        "-q",
        "--trace-config",
        "-c",
        os.devnull,
        "--rootdir",
        str(fixture.parent),
        "-W",
        "error",
        "-o",
        "asyncio_mode=strict",
        "-o",
        "asyncio_default_fixture_loop_scope=function",
        "-p",
        "no:cacheprovider",
        "-p",
        "pytest_asyncio.plugin",
        "-p",
        "pytest_mock",
        "-p",
        "pytest_repeat",
        "-p",
        "pytest_timeout",
        str(fixture),
    ]
    environment = dict(
        os.environ, PYTHONDONTWRITEBYTECODE="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1"
    )
    environment.pop("PYTEST_ADDOPTS", None)
    environment.pop("PYTEST_PLUGINS", None)
    observations = []
    for mode in ("normal_cli", "preimport_negative"):
        report = output / (mode + ".xml")
        pytest_args = [*common, "--junitxml=" + str(report)]
        if mode == "normal_cli":
            command = [sys.executable, "-B", "-m", "pytest", *pytest_args]
        else:
            code = (
                "import pytest_asyncio.plugin; import pytest; "
                "raise SystemExit(pytest.main(" + repr(pytest_args) + "))"
            )
            command = [sys.executable, "-B", "-c", code]
        started = time.monotonic()
        # These reviewed toy cases start no subprocesses or server. This is not
        # a containment wrapper for arbitrary source/model-generated commands.
        result = subprocess.run(
            command,
            cwd=output,
            env=environment,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
        for stream in ("stdout", "stderr"):
            text = getattr(result, stream)
            with (output / (mode + "." + stream + ".txt")).open(
                "x", encoding="utf-8"
            ) as handle:
                handle.write(text)
        observations.append(
            dict(
                mode=mode,
                command=command,
                exit_code=result.returncode,
                wall_seconds=time.monotonic() - started,
            )
        )
        if mode == "normal_cli":
            if result.returncode != 0:
                raise RuntimeError(
                    "Normal CLI did not pass; inspect retained output, do not retry implicitly"
                )
            cases = ET.parse(report).getroot().findall(".//testcase")
            names = [case.attrib["name"] for case in cases]
            if (
                len(cases) != 4
                or len(set(names)) != 4
                or "test_sync_fixture" not in names
                or "test_async_fixture" not in names
                or sum(name.startswith("test_repeat_plugin[") for name in names) != 2
                or any(
                    case.find(tag) is not None
                    for case in cases
                    for tag in ("failure", "error", "skipped")
                )
            ):
                raise RuntimeError(
                    "Original four-case canary was not completely exercised"
                )
        elif (
            result.returncode != 1
            or report.exists()
            or "PytestAssertRewriteWarning" not in result.stdout + result.stderr
            or "Module already imported so cannot be rewritten; pytest_asyncio.plugin"
            not in result.stdout + result.stderr
        ):
            raise RuntimeError(
                "Expected startup negative control not discriminated; inspect this version"
            )
    if hashlib.sha256(fixture.read_bytes()).hexdigest() != fixture_hash:
        raise RuntimeError("Canary source changed")
    summary = dict(
        status="STARTUP_ORDER_CONTROL_CONFIRMED",
        versions=versions,
        fixture_sha256=fixture_hash,
        observations=observations,
        boundary="Four synthetic fixture cases and an expected pre-collection initialization failure; "
        "not target-project qualification, repaired historical trial, model calls or measured savings.",
    )
    with (output / "result.json").open("x", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)
        handle.write("\n")
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
