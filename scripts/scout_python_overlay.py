"""Prepare a fresh task-private Python package copy; never import or execute it.

Use only controlled, reviewed package directories. This is not adversarial
filesystem isolation, an atomic snapshot, dependency resolution or a build.
"""
import hashlib
from pathlib import Path, PurePosixPath
import re
import shutil
import time

from scout_dependency_tree import inspect_tree


def _digest_file(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(256*1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def stage_package(source, output, replacements, *, max_entries=20000,
                  max_bytes=1024**3, timeout=60):
    """Copy an existing package and replace 1..64 existing literal .py files.

    ``replacements`` maps POSIX paths relative to the package to reviewed bytes.
    Native libraries/resources are copied, never linked. Omit bytecode caches so
    stale timestamp-based .pyc files cannot conceal an overlaid module. A failure
    leaves any fresh partial output for inspection; it is never reused/deleted.

    Observation budgets/deadlines are cooperative, not disk or wall-time quotas;
    the caller must externally bound stalled filesystem I/O and target execution.
    Source/target parent directories must be under the caller's control.
    """
    if not isinstance(replacements, dict) or not 1 <= len(replacements) <= 64:
        raise ValueError('supply 1..64 reviewed Python module replacements')
    replacements = dict(replacements)  # Own the mapping across filesystem I/O.
    for name, body in replacements.items():
        if (not isinstance(name, str)
                or not re.fullmatch(r'[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*', name)
                or any(p in {'.', '..', '__pycache__'} for p in name.split('/'))
                or not name.endswith('.py') or type(body) is not bytes
                or len(body) > 8*1024**2):
            raise ValueError('replacements need literal relative .py paths and bounded bytes')
    source, output = Path(source).absolute(), Path(output).absolute()
    if (output.exists() or output.is_symlink()
            or getattr(output, 'is_junction', lambda: False)()
            or output.resolve().is_relative_to(source.resolve())):
        raise ValueError('output must be fresh and outside the source package')
    started = time.monotonic()
    before = inspect_tree(source, max_entries=max_entries, max_bytes=max_bytes, timeout=timeout)
    if before['symlinks']:
        raise ValueError('package links are not supported for copying')
    source = source.resolve(strict=True)
    original = {}
    for name in replacements:
        target = source.joinpath(*PurePosixPath(name).parts)
        if not target.is_file():
            raise ValueError('overlay must replace an existing package module: '+name)
        original[name] = _digest_file(target)

    def remaining():
        value = timeout - (time.monotonic() - started)
        if value <= 0:
            raise TimeoutError('package staging deadline exceeded')
        return value

    def copy_file(src, dst):
        remaining()
        return shutil.copy2(src, dst)

    # No imports, installer, hardlinks, cleanup or merge into an old directory.
    shutil.copytree(source, output, copy_function=copy_file,
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo'))
    for name, body in replacements.items():
        remaining()
        output.joinpath(*PurePosixPath(name).parts).write_bytes(body)
    after = inspect_tree(source, max_entries=max_entries, max_bytes=max_bytes, timeout=remaining())
    if after['content_sha256'] != before['content_sha256']:
        raise ValueError('source package changed during staging; preserve partial output')
    staged = inspect_tree(output, max_entries=max_entries, max_bytes=max_bytes, timeout=remaining())
    overlays = {}
    for name, body in replacements.items():
        expected = hashlib.sha256(body).hexdigest()
        actual = _digest_file(output.joinpath(*PurePosixPath(name).parts))
        if actual != expected:
            raise ValueError('staged module differs from reviewed bytes: '+name)
        overlays[name] = dict(original_sha256=original[name], replacement_sha256=actual)
    remaining()
    return dict(source=before, staged=staged, overlays=overlays,
                elapsed_seconds=time.monotonic()-started, bytecode_omitted=True,
                boundary='Private copy/content observation only; no execution, complete '
                         'environment identity, atomicity, sandbox, source-build compatibility or PR qualification.')
