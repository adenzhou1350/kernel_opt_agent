"""Bounded hints for missing relative-import definitions, never a resolver proof.

Use only cached, pinned primary source and members of the same observed tree.
No source execution, cache fill, model-created fetch target, or quality verdict.
Unsupported syntax/resolution leaves ordinary context acquisition unchanged.
"""

import ast
import re
from urllib.parse import unquote, urlsplit

IDENT = r"[A-Za-z_$][A-Za-z0-9_$]*"
NAMED_IMPORT = re.compile(
    rf"import\s+(?:type\s+)?(?:{IDENT}\s*,\s*)?"
    r"\{([^{};]{1,4000})\}\s*from\s*(['\"])([^'\"\r\n\\]{1,512})\2\s*;?"
)
OTHER_IMPORT = re.compile(
    rf"import\s+(?:(?:{IDENT}|\*\s+as\s+{IDENT})\s+from\s+)?"
    r"(['\"])[^'\"\r\n\\]{1,512}\1\s*;?"
)
DIRECTIVE = re.compile(r"(['\"])[A-Za-z _-]{1,40}\1\s*;")


def _trivia(raw, pos):
    while pos < len(raw):
        match = re.match(r"\s+|//[^\n]*|/\*[\s\S]*?\*/", raw[pos:])
        if match is None:
            break
        pos += match.end()
    return pos


def _js_bindings(raw):
    """Conservatively scan the import prefix, not strings or later source text."""
    pos = 0
    for _ in range(128):
        pos = _trivia(raw, pos)
        directive = DIRECTIVE.match(raw, pos)
        if directive:
            pos = directive.end()
            continue
        match = NAMED_IMPORT.match(raw, pos)
        if match:
            for entry in match[1].split(","):
                name = re.fullmatch(
                    rf"\s*(?:type\s+)?({IDENT})(?:\s+as\s+({IDENT}))?\s*", entry
                )
                if name:
                    yield name[2] or name[1], name[1], match[3]
            pos = match.end()
            continue
        other = OTHER_IMPORT.match(raw, pos)
        if other:
            pos = other.end()
            continue
        break  # Unsupported/import-later syntax is not guessed.


def _bindings(path, raw):
    if path.endswith(".py"):
        try:
            tree = ast.parse(raw)
        except (SyntaxError, ValueError, RecursionError):
            return
        # Only module-level relative imports; no installed-package speculation.
        for node in tree.body:
            if (
                not isinstance(node, ast.ImportFrom)
                or not node.level
                or not node.module
            ):
                continue
            module = "../" * (node.level - 1) + "./" + node.module.replace(".", "/")
            for name in node.names:
                if name.name != "*":
                    yield name.asname or name.name, name.name, module
    elif path.endswith((".ts", ".tsx", ".js", ".jsx", ".mts", ".mjs", ".cts", ".cjs")):
        yield from _js_bindings(raw)


def _resolve(path, module, files):
    if not module.startswith(("./", "../")):
        return None
    parts = path.split("/")[:-1]
    for part in module.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if not parts:
                return None
            parts.pop()
        elif any(c in part for c in "\\:?%#") or any(ord(c) < 32 for c in part):
            return None
        else:
            parts.append(part)
    base = "/".join(parts)
    if path.endswith(".py"):
        choices = [base + ".py", base + "/__init__.py"]
    else:
        rewrites = {
            ".js": (".ts", ".tsx", ".js"),
            ".mjs": (".mts", ".mjs"),
            ".cjs": (".cts", ".cjs"),
        }
        suffix = "." + base.rsplit(".", 1)[-1]
        if suffix in rewrites:
            choices = [base[: -len(suffix)] + ext for ext in rewrites[suffix]]
        elif suffix in {".ts", ".tsx", ".mts", ".cts", ".jsx"}:
            choices = [base]
        else:
            choices = [
                base + ext for ext in (".ts", ".tsx", ".js", "/index.ts", "/index.js")
            ]
    observed = [p for p in choices if p in files and p != path]
    return observed[0] if len(observed) == 1 else None


def import_requests(packet, snapshot, analysis, cached_source, *, limit=2):
    """Propose <=2 definitions explicitly requested in the prior next_check.

    Named aliases and .js -> .ts are lexical hints only. Ambiguous tree members,
    absent cache, revision drift, bare package imports and wildcard imports abstain.
    The callback must be a read-only cache lookup, not another acquisition step.
    """
    if type(limit) is not int or not 1 <= limit <= 2:
        raise ValueError("import context limit must be 1..2")
    hints = analysis.get("next_check", "")
    if not isinstance(hints, str):
        return []
    requested = list(dict.fromkeys(re.findall(IDENT, hints[:4000])))[:64]
    sources = packet.get("sources", [])
    if not sources or not requested:
        return []
    url = urlsplit(sources[0].get("url", ""))
    repo, commit = packet.get("repo", ""), snapshot.get("commit", "")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        return []
    prefix = f"/{repo}/{commit}/"
    if (
        not repo
        or url.scheme != "https"
        or url.netloc != "raw.githubusercontent.com"
        or url.query
        or url.fragment
        or not url.path.startswith(prefix)
    ):
        return []
    path = unquote(url.path[len(prefix) :])
    files = set(snapshot.get("files", []))
    if path not in files or any(p in {"", ".", ".."} for p in path.split("/")):
        return []
    raw = cached_source(repo, commit, path)
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > 131072 or "\x00" in raw:
        return []
    bindings = {}
    for local, imported, module in _bindings(path, raw):
        target = _resolve(path, module, files)
        if target:
            bindings.setdefault(local, set()).add((imported, target))
    requests, paths = [], set()
    for symbol in requested:
        candidates = bindings.get(symbol, set())
        if len(candidates) != 1:
            continue
        imported, target = next(iter(candidates))
        if target in paths:
            continue
        paths.add(target)
        requests.append({"path": target, "hints": imported, "max_lines": 80})
        if len(requests) == limit:
            break
    return requests
