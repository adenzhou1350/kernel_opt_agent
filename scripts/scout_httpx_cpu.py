"""One reviewed full-package HTTPX environment; no downloads or queue mutation."""

from __future__ import annotations

import hashlib
import json
import re

COMMIT = "b5addb64f0161ff6bfe94c124ef76f6a1fba5254"
IMAGE = "sha256:ad47b9d7b2ed3afc265fdf95732bd35527cdf092362ba4382c722949a36a4309"
PROFILE = "httpx-cpu"
CLAIM_SCOPE = "MATCHED_PACKAGE_SINGLE_MODULE_CPU_SCREEN_NOT_UPSTREAM_SUITE"


def module_name(path):
    if not isinstance(path, str) or not re.fullmatch(
        r"httpx/(?:[A-Za-z_][A-Za-z_0-9]*/)*[A-Za-z_][A-Za-z_0-9]*\.py", path
    ):
        raise ValueError("HTTPX profile requires an exact httpx/*.py module path")
    parts = path[:-3].split("/")
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def source_supported(source):
    """Admission is based on fetched source identity, never the model's proposal."""
    if source.get("repo") != "encode/httpx" or source.get("commit") != COMMIT:
        return False
    try:
        module_name(source.get("path"))
    except ValueError:
        return False
    content = source.get("source")
    return (
        isinstance(content, str)
        and source.get("sha256") == hashlib.sha256(content.encode("utf-8")).hexdigest()
    )


def harness(path, baseline_sha256, unittest_harness):
    module = module_name(path)
    if not isinstance(baseline_sha256, str) or not re.fullmatch(
        r"[0-9a-f]{64}", baseline_sha256
    ):
        raise ValueError("HTTPX profile requires the baseline byte identity")
    # All sibling modules come from this reviewed image's complete source export.
    # Check the original before replacing the selected file in private scratch.
    # Neither mounted subject nor generated tests run before this check.
    return (
        "import hashlib, importlib, pathlib, shutil, sys\n"
        "root = pathlib.Path('/opt/httpx')\n"
        f"original = root / {json.dumps(path)}\n"
        f"assert hashlib.sha256(original.read_bytes()).hexdigest() == {json.dumps(baseline_sha256)}, 'HTTPX baseline/image source mismatch'\n"
        "scratch = pathlib.Path('/tmp/httpx-source')\n"
        "shutil.copytree(root / 'httpx', scratch / 'httpx')\n"
        f"target = scratch / {json.dumps(path)}\n"
        "target.write_bytes(pathlib.Path('/input/subject.py').read_bytes())\n"
        "sys.path.insert(0, str(scratch))\n"
        "import httpx\n"
        "assert pathlib.Path(httpx.__file__).resolve().is_relative_to(scratch), 'wrong HTTPX package import'\n"
        f"subject = importlib.import_module({json.dumps(module)})\n"
        "assert pathlib.Path(subject.__file__).resolve() == target.resolve(), 'wrong HTTPX subject import'\n"
        "sys.modules['subject'] = subject\n" + unittest_harness
    )
