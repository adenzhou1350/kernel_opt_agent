"""Read-only delivery admission; source inspection is not execution or qualification."""

from __future__ import annotations

import ast
import copy
import hashlib
import json
import os
import re
import sqlite3
import stat
from collections import deque
from pathlib import Path
from urllib.parse import urlsplit

import kimi_scout as scout

SOURCE_LIMIT = 100_000
CACHE_LIMIT = 1_000_000
# Explicit Python 3.10 top-level stdlib names, not the controller interpreter's
# sys.stdlib_module_names (which would admit newer modules such as tomllib).
# Platform-specific modules and newer APIs within these modules still need the
# isolated runtime check. This compatibility filter is NOT a security sandbox.
STDLIB_310 = frozenset(
    """__future__ _thread abc aifc argparse array ast asynchat asyncio asyncore
    atexit audioop base64 bdb binascii bisect builtins bz2 cProfile calendar cgi
    cgitb chunk cmath cmd code codecs codeop collections colorsys compileall
    concurrent configparser contextlib contextvars copy copyreg crypt csv ctypes
    curses dataclasses datetime dbm decimal difflib dis distutils doctest email
    encodings ensurepip enum errno faulthandler fcntl filecmp fileinput fnmatch
    fractions ftplib functools gc getopt getpass gettext glob graphlib grp gzip
    hashlib heapq hmac html http imaplib imghdr imp importlib inspect io ipaddress
    itertools json keyword lib2to3 linecache locale logging lzma mailbox mailcap
    marshal math mimetypes mmap modulefinder msilib msvcrt multiprocessing netrc
    nis nntplib numbers operator optparse os ossaudiodev pathlib pdb pickle
    pickletools pipes pkgutil platform plistlib poplib posix posixpath pprint
    profile pstats pty pwd py_compile pyclbr pydoc queue quopri random re readline
    reprlib resource rlcompleter runpy sched secrets select selectors shelve shlex
    shutil signal site smtpd smtplib sndhdr socket socketserver spwd sqlite3 ssl
    stat statistics string stringprep struct subprocess sunau symtable sys
    sysconfig syslog tabnanny tarfile telnetlib tempfile termios textwrap threading
    time timeit tkinter token tokenize trace traceback tracemalloc tty turtle
    turtledemo types typing unicodedata unittest urllib uu uuid venv warnings wave
    weakref webbrowser winreg winsound wsgiref xdrlib xml xmlrpc zipapp zipfile
    zipimport zlib zoneinfo""".split()  # noqa: SIM905 - compact explicit compatibility table
)


class UnsupportedEnvironment(ValueError):
    """A precise static-admission rejection, not a failed reproduction."""

    def __init__(self, reason, path=None):
        self.reason = reason
        self.path = path
        super().__init__(f"{path}: {reason}" if path else reason)


def _repo(value):
    scout.public_repo(value)
    if any(part in {".", ".."} for part in value.split("/")):
        raise ValueError("invalid repository path")
    return value


def _raw_sources(packet, repo):
    """Yield only exact immutable packet URLs; never turn model prose into URLs."""
    for source in packet.get("sources", []):
        if not isinstance(source, dict) or not isinstance(source.get("url"), str):
            continue
        url = source["url"]
        try:
            parsed = urlsplit(url)
        except ValueError:
            continue
        if (
            parsed.scheme != "https"
            or parsed.netloc != "raw.githubusercontent.com"
            or parsed.query
            or parsed.fragment
            or url != "https://raw.githubusercontent.com" + parsed.path
        ):
            continue
        match = re.fullmatch(
            "/" + re.escape(repo) + r"/([0-9a-f]{40})/([A-Za-z0-9_./-]+)",
            parsed.path,
        )
        if not match:
            continue
        commit, path = match.groups()
        if any(part in {"", ".", ".."} for part in path.split("/")):
            continue
        yield {"url": url, "commit": commit, "path": path}


def select_leads(root, limit=20):
    """Return terminal REVIEW leads fairly across repos; no DB/cache writes.

    Reproduction plans come first within each repository. canonical_key is exact
    normalized text/path deduplication, not semantic hypothesis uniqueness.
    """
    if type(limit) is not int or not 0 <= limit <= 10_000:
        raise ValueError("limit must be an integer between 0 and 10000")
    if not limit:
        return []
    db_path = (Path(root) / "scout.sqlite").resolve()
    connection = sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True, timeout=15)
    connection.row_factory = sqlite3.Row
    buckets = {}
    seen = set()
    try:
        connection.execute("PRAGMA query_only=ON")
        # NOT IN materializes the parent set once, avoiding a correlated scan
        # over the entire job history for every REVIEW row.
        rows = connection.execute(
            """SELECT id,packet,result FROM jobs
            WHERE state='REVIEW' AND id NOT IN (
              SELECT json_extract(packet,'$.research.parent_job_id') FROM jobs
              WHERE json_extract(packet,'$.research.parent_job_id') IS NOT NULL
            )
            ORDER BY CASE json_extract(packet,'$.research.stage')
              WHEN 'reproduction_plan' THEN 0 ELSE 1 END, finished DESC, id"""
        )
        for row in rows:
            try:
                packet = json.loads(row["packet"])
                analysis = json.loads(row["result"])["analysis"]
                repo = _repo(packet["repo"])
                if not isinstance(analysis, dict):
                    continue
                sources = list(_raw_sources(packet, repo))
                primary = sources[0] if sources else None
                python = next((s for s in sources if s["path"].endswith(".py")), None)
                text = analysis.get("hypothesis") or analysis.get("title") or row["id"]
                if not isinstance(text, str):
                    continue
            except (ValueError, TypeError, KeyError):
                continue
            key = hashlib.sha256(
                scout.dumps(
                    [
                        repo,
                        primary["path"] if primary else None,
                        " ".join(text.casefold().split()),
                    ]
                ).encode("utf-8")
            ).hexdigest()
            if key in seen:
                continue
            seen.add(key)
            buckets.setdefault(repo, deque()).append(
                {
                    "id": row["id"],
                    "repo": repo,
                    "commit": (python or primary or {}).get("commit"),
                    "packet": packet,
                    "analysis": analysis,
                    "canonical_key": key,
                }
            )
    finally:
        connection.close()
    selected = []
    active = deque(buckets.values())
    while active and len(selected) < limit:
        bucket = active.popleft()
        selected.append(bucket.popleft())
        if bucket:
            active.append(bucket)
    return selected


def _import_notes(tree, path, allow_dependencies=False):
    notes = []
    dependencies = set()
    required = set()

    def check(name, node, deferred):
        root = name.split(".", 1)[0]
        if root in STDLIB_310:
            return
        if name.startswith("."):
            raise UnsupportedEnvironment(
                f"relative import requires package context (line {node.lineno})", path
            )
        dependencies.add(root)
        if not deferred:
            required.add(root)
        reason = f"non-Python-3.10-stdlib import: {name}"
        reason += f" (line {node.lineno})"
        if deferred or allow_dependencies:
            notes.append(
                reason
                + (
                    "; optional/lazy, runtime compatibility unknown"
                    if deferred
                    else "; dependency runtime required, compatibility unknown"
                )
            )
        else:
            raise UnsupportedEnvironment(reason, path)

    def optional_handler(handler):
        return handler.type is not None and any(
            isinstance(node, ast.Name)
            and node.id in {"ImportError", "ModuleNotFoundError"}
            for node in ast.walk(handler.type)
        )

    def visit(node, deferred=False):
        if isinstance(node, ast.Import):
            for alias in node.names:
                check(alias.name, node, deferred)
            return
        if isinstance(node, ast.ImportFrom):
            check("." * node.level + (node.module or ""), node, deferred)
            return
        if isinstance(node, ast.Call) and node.args:
            dynamic_import = (
                isinstance(node.func, ast.Name) and node.func.id == "__import__"
            ) or (
                isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "importlib"
                and node.func.attr == "import_module"
            )
            if (
                dynamic_import
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                check(node.args[0].value, node, deferred)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for child in node.body:
                visit(child, True)
            return
        if isinstance(node, ast.If):
            type_checking = (
                isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING"
            ) or (
                isinstance(node.test, ast.Attribute)
                and node.test.attr == "TYPE_CHECKING"
            )
            for child in node.body:
                visit(child, deferred or type_checking)
            for child in node.orelse:
                visit(child, deferred)
            return
        if isinstance(node, ast.Try):
            optional = any(optional_handler(handler) for handler in node.handlers)
            for child in node.body:
                visit(child, deferred or optional)
            for handler in node.handlers:
                for child in handler.body:
                    visit(child, deferred or optional)
            for child in node.orelse + node.finalbody:
                visit(child, deferred)
            return
        for child in ast.iter_child_nodes(node):
            visit(child, deferred)

    visit(tree)
    return list(dict.fromkeys(notes)), sorted(dependencies), sorted(required)


def _cache_entry_stat(cache, source_path):
    """Reject links/reparse points, including directory ancestors, before opening."""
    for entry in [*reversed(cache.parents), cache]:
        try:
            info = entry.lstat()
        except FileNotFoundError:
            return None
        if stat.S_ISLNK(info.st_mode) or getattr(
            info, "st_file_attributes", 0
        ) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
            raise UnsupportedEnvironment(
                "source cache path contains a symlink/reparse point", source_path
            )
        if entry != cache and not stat.S_ISDIR(info.st_mode):
            raise UnsupportedEnvironment(
                "source cache ancestor is not a directory", source_path
            )
    if not stat.S_ISREG(info.st_mode):
        raise UnsupportedEnvironment(
            "source cache entry is not a regular file", source_path
        )
    return info


def _cached_source(root, repo, item):
    if root is None:
        return None
    key = hashlib.sha256(
        scout.dumps([repo, item["commit"], item["path"]]).encode("utf-8")
    ).hexdigest()
    cache = Path(root).absolute() / "public-cache" / f"raw-{key}.json"
    try:
        info = _cache_entry_stat(cache, item["path"])
        if info is None:
            return None
        if info.st_size > CACHE_LIMIT:
            raise UnsupportedEnvironment(
                "cached source record exceeds read budget", item["path"]
            )
        descriptor = os.open(
            cache,
            os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        with os.fdopen(descriptor, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise UnsupportedEnvironment(
                    "source cache entry is not a regular file", item["path"]
                )
            data = stream.read(CACHE_LIMIT + 1)
        if len(data) > CACHE_LIMIT:
            raise UnsupportedEnvironment(
                "cached source record exceeds read budget", item["path"]
            )
        value = json.loads(data)
        if isinstance(value, dict) and value.get("url") == item["url"]:
            text = value.get("text")
            return text if isinstance(text, str) else None
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        pass
    return None


def load_source(lead, github_auth=False, *, root=None, allow_dependencies=False):
    """Load one complete public Python module, never execute it or write cache.

    Pass the scout root explicitly for cache reuse; local paths never enter the
    returned public context. Optional/lazy dependencies are reported, not proved
    runnable. Transport errors propagate for the controller to classify.
    """
    if type(allow_dependencies) is not bool:
        raise ValueError("allow_dependencies must be boolean")
    repo = _repo(lead["repo"])
    packet = lead["packet"]
    if packet.get("repo") != repo:
        raise UnsupportedEnvironment("lead/packet repository mismatch")
    item = next(
        (s for s in _raw_sources(packet, repo) if s["path"].endswith(".py")), None
    )
    if item is None:
        raise UnsupportedEnvironment(
            "no immutable same-repository Python source URL in packet"
        )
    path = item["path"]
    if lead.get("commit") is not None and lead["commit"] != item["commit"]:
        raise UnsupportedEnvironment("lead/source revision mismatch", path)
    metadata = json.loads(
        scout.fetch(
            f"https://api.github.com/repos/{repo}",
            limit=100_000,
            github_auth=github_auth,
        )
    )
    if (
        not isinstance(metadata, dict)
        or metadata.get("private") is not False
        or metadata.get("visibility") != "public"
        or metadata.get("full_name", "").casefold() != repo.casefold()
    ):
        raise UnsupportedEnvironment("repository is not explicitly public", path)
    source = _cached_source(root, repo, item)
    if source is None:
        try:
            source = scout.fetch(item["url"], limit=SOURCE_LIMIT, github_auth=False)
        except ValueError as exc:
            if str(exc) == "source exceeds read budget":
                raise UnsupportedEnvironment(
                    "full module exceeds 100000 bytes", path
                ) from exc
            raise
    if not isinstance(source, str) or len(source.encode("utf-8")) > SOURCE_LIMIT:
        raise UnsupportedEnvironment("full module exceeds 100000 UTF-8 bytes", path)
    try:
        tree = ast.parse(source, filename=path, feature_version=(3, 10))
    except (SyntaxError, ValueError) as exc:
        raise UnsupportedEnvironment(
            "not parseable as Python 3.10 source", path
        ) from exc
    notes, dependencies, required = _import_notes(tree, path, allow_dependencies)
    return {
        "source": source,
        "sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
        "path": path,
        "url": item["url"],
        "context": copy.deepcopy(packet),
        "compatibility_notes": notes,
        "dependency_modules": dependencies,
        "required_dependency_modules": required,
    }
