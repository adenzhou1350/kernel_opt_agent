"""Bounded C-family/Python reference hints from a cached pinned source.

Never execute source or fetch a model-provided target. References, declarations
and preprocessor branches are not a call graph or proof of runtime reachability.
"""

import ast
import re
from urllib.parse import unquote, urlsplit

SUFFIXES = (
    ".c",
    ".cc",
    ".cpp",
    ".cxx",
    ".h",
    ".hh",
    ".hpp",
    ".hxx",
    ".cu",
    ".cuh",
    ".py",
)
REQUEST = re.compile(r"\breferences\(([A-Za-z_]\w{0,127})\)")
LITERALS = re.compile(
    r"//[^\n]*|/\*[\s\S]*?(?:\*/|\Z)|"
    r"'(?:\\[\s\S]|[^'\\])*'|\"(?:\\[\s\S]|[^\"\\])*\""
)


def reference_requests(packet, snapshot, analysis, cached_source, *, limit=2):
    """Honor explicit references(NAME), with <=2 existing-tree source windows.

    Use only the primary source at the same observed immutable revision. A cache
    miss, unsupported syntax, missing symbols or already shown matches abstain.
    Python AST name loads and attributes exclude plain strings, comments and
    definitions; they are syntactic references, not resolved bindings or calls.
    C-family comments/literals and directive lines are excluded; local
    declarations may still be included. Macros/aliases are not expanded. Pick the
    first and last unseen match windows, not an exhaustive consumer inventory.
    The callback is a read-only bounded cache lookup, never a new acquisition.
    """
    if type(limit) is not int or not 1 <= limit <= 2:
        raise ValueError("reference context limit must be 1..2")
    request = analysis.get("next_check", "")
    if not isinstance(request, str):
        return []
    symbols = list(dict.fromkeys(REQUEST.findall(request[:2000])))
    if not 1 <= len(symbols) <= 2:
        return []
    sources = packet.get("sources", [])
    if not sources:
        return []
    repo, commit = packet.get("repo", ""), snapshot.get("commit", "")
    if not repo or not re.fullmatch(r"[a-f0-9]{40}", commit):
        return []
    url = urlsplit(sources[0].get("url", ""))
    prefix = f"/{repo}/{commit}/"
    if (
        url.scheme != "https"
        or url.netloc != "raw.githubusercontent.com"
        or url.query
        or url.fragment
        or not url.path.startswith(prefix)
    ):
        return []
    path = unquote(url.path[len(prefix) :])
    if (
        path not in snapshot.get("files", [])
        or not path.endswith(SUFFIXES)
        or any(part in {"", ".", ".."} for part in path.split("/"))
        or any(c in path for c in "\\:")
        or any(ord(c) < 32 or ord(c) == 127 for c in path)
    ):
        return []
    raw = cached_source(repo, commit, path)
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > 131072 or "\x00" in raw:
        return []
    if path.endswith(".py"):
        try:
            tree = ast.parse(raw)
        except (SyntaxError, ValueError, RecursionError):
            return []
        occurrences = {
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, (ast.Name, ast.Attribute))
            and isinstance(node.ctx, ast.Load)
            and (node.id if isinstance(node, ast.Name) else node.attr) in symbols
        }
    else:
        # Do not pretend ordinary quote masking understands C++ raw strings.
        if re.search(r'\b(?:u8|u|U|L)?R"', raw):
            return []
        if any(
            m[0].startswith("/*") and not m[0].endswith("*/")
            for m in LITERALS.finditer(raw)
        ):
            return []
        masked = LITERALS.sub(lambda m: re.sub(r"[^\n]", " ", m[0]), raw)
        lines = masked.splitlines()
        # Ignore complete continued preprocessor directives, not just the prefix.
        directive = False
        for index, line in enumerate(lines):
            if directive or line.lstrip().startswith("#"):
                directive = line.rstrip().endswith("\\")
                lines[index] = ""
        occurrences = {
            number
            for symbol in symbols
            for number, line in enumerate(lines, 1)
            if re.search(rf"\b{re.escape(symbol)}\b", line)
        }
    hits = [
        number
        for number in occurrences
        if not any(
            source.get("url") == sources[0]["url"]
            and type(source.get("start_line")) is int
            and type(source.get("end_line")) is int
            and source["start_line"] <= number <= source["end_line"]
            for source in sources
        )
    ]
    if not hits:
        return []
    requests = []
    for number in dict.fromkeys((min(hits), max(hits))):
        if any(r["start"] <= number < r["start"] + r["max_lines"] for r in requests):
            continue
        requests.append({"path": path, "start": max(1, number - 8), "max_lines": 80})
        if len(requests) == limit:
            break
    return requests
