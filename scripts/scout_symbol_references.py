"""Bounded C-family/Python/JS reference hints from a cached pinned source.

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
    ".js",
    ".mjs",
    ".cjs",
    ".ts",
)
REQUEST = re.compile(
    r"\breferences\(([A-Za-z_][A-Za-z0-9_]{0,127}"
    r"(?:\.[A-Za-z_][A-Za-z0-9_]{0,127}){0,4})\)"
)
PYTHON_CACHE_LIMIT = 1_000_000
LEXICAL_CACHE_LIMIT = 131072


def reference_cache_limit(path):
    """Reuse the existing Python source-read budget; keep lexical scans small."""
    return PYTHON_CACHE_LIMIT if path.endswith(".py") else LEXICAL_CACHE_LIMIT


LITERALS = re.compile(
    r"//[^\n]*|/\*[\s\S]*?(?:\*/|\Z)|"
    r"'(?:\\[\s\S]|[^'\\])*'|\"(?:\\[\s\S]|[^\"\\])*\""
)
SIMPLE_INTERPOLATION = re.compile(r"\$\{[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*\}")


def _javascript_code(raw, *, prefix_on_unsupported=False):
    """Mask lexical trivia, or abstain on unsupported slash/template syntax.

    This is a non-exhaustive hint, not a JS/TS parser. Template interpolation is
    opaque: only simple name/member interpolations are admitted, with all their
    references omitted. Regex literals/division, complex interpolations, and
    unterminated trivia abstain rather than invent a resolved reference. When
    requested, retain only the masked complete-line prefix before that trivia.
    """
    output = list(raw)
    index = 0

    def unsupported(start):
        if not prefix_on_unsupported:
            return None
        # Never admit a partial line, even if a symbol precedes the unsupported
        # token. All earlier complete lines have already had trivia masked.
        boundary = raw.rfind("\n", 0, start) + 1
        return "".join(output[:boundary])

    while index < len(raw):
        start = index
        if raw.startswith("//", index):
            end = raw.find("\n", index + 2)
            index = len(raw) if end < 0 else end
        elif raw.startswith("/*", index):
            end = raw.find("*/", index + 2)
            if end < 0:
                return unsupported(start)
            index = end + 2
        elif raw[index] in "'\"`":
            quote = raw[index]
            index += 1
            while index < len(raw) and raw[index] != quote:
                if raw[index] == "\\":
                    index += 2
                elif quote == "`" and raw.startswith("${", index):
                    interpolation = SIMPLE_INTERPOLATION.match(raw, index)
                    if interpolation is None:
                        return unsupported(start)
                    index += len(interpolation[0])
                elif quote != "`" and raw[index] in "\r\n":
                    return unsupported(start)
                else:
                    index += 1
            if index >= len(raw):
                return unsupported(start)
            index += 1
        elif raw[index] == "/":
            # Deliberately do not distinguish regex literals from division.
            return unsupported(start)
        else:
            index += 1
            continue
        for offset in range(start, index):
            if raw[offset] not in "\r\n":
                output[offset] = " "
    return "".join(output)


def reference_requests(packet, snapshot, analysis, cached_source, *, limit=2):
    """Honor explicit references(NAME), with <=2 existing-tree source windows.

    Use the primary source, or one explicitly named already-supplied source,
    at the same observed immutable revision. A basename must identify only one
    supplied path. Ambiguous or drifted named sources abstain. A cache
    miss, unsupported syntax, missing symbols or already shown matches abstain.
    Qualified requests use their terminal identifier as a hint, not a resolved
    receiver. Python AST loads and literal getattr/hasattr calls exclude other
    strings, comments and definitions; built-in names may themselves be shadowed.
    These are syntactic references, not resolved bindings or runtime calls.
    When no unseen Python uses remain, an unqualified name may expose its
    unique top-level import statement instead. This does not resolve the
    imported value, follow a dependency, or rule out rebinding/shadowing.
    C-family comments/literals and directive lines are excluded; local
    declarations may still be included. Macros/aliases are not expanded. Pick the
    first and last unseen match windows, not an exhaustive consumer inventory.
    JS/TS hints are lexical, include type references but skip same-name type
    declaration lines, and omit template interpolations; unsupported syntax ends
    a disclosed, complete-line prefix scan. No binding resolution.
    The callback is a read-only bounded cache lookup, never a new acquisition.
    """
    if type(limit) is not int or not 1 <= limit <= 2:
        raise ValueError("reference context limit must be 1..2")
    request = analysis.get("next_check", "")
    if not isinstance(request, str):
        return []
    names = list(dict.fromkeys(REQUEST.findall(request[:2000])))
    if not 1 <= len(names) <= 2:
        return []
    symbols = list(dict.fromkeys(name.rsplit(".", 1)[-1] for name in names))
    if not 1 <= len(symbols) <= 2:
        return []
    sources = packet.get("sources", [])
    if not sources:
        return []
    repo, commit = packet.get("repo", ""), snapshot.get("commit", "")
    if not repo or not re.fullmatch(r"[a-f0-9]{40}", commit):
        return []
    # The model can choose among observed files, not introduce a fetch target.
    # Follow-ups often ask about a secondary definition/consumer. Looking only
    # in sources[0] then falls back to another search of the wrong file.
    observed = {}
    for source in sources[:8]:
        parsed = urlsplit(source.get("url", ""))
        match = re.fullmatch(rf"/{re.escape(repo)}/[a-f0-9]{{40}}/(.+)", parsed.path)
        if match:
            observed.setdefault(unquote(match[1]), source)

    def mentioned(value):
        return bool(
            re.search(rf"(?<![\w./-]){re.escape(value)}(?![\w./-])", request[:2000])
        )

    named = [
        path
        for path in observed
        if mentioned(path) or mentioned(path.rsplit("/", 1)[-1])
    ]
    if len(named) > 1:
        return []
    selected = observed[named[0]] if named else sources[0]
    selected_url = selected.get("url", "")
    url = urlsplit(selected_url)
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
    if (
        not isinstance(raw, str)
        or len(raw.encode("utf-8")) > reference_cache_limit(path)
        or "\x00" in raw
    ):
        return []
    reference_scan = None
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
        occurrences.update(
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in {"getattr", "hasattr"}
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and isinstance(node.args[1].value, str)
            and node.args[1].value in symbols
        )
    elif path.endswith((".js", ".mjs", ".cjs", ".ts")):
        masked = _javascript_code(raw, prefix_on_unsupported=True)
        if masked is None:
            return []
        if len(masked) < len(raw):
            reference_scan = {
                "complete": False,
                "scanned_through_line": len(masked.splitlines()),
                "scope": "Lexical prefix only; unsupported syntax ends the scan; not reachability or full-file absence proof.",
            }
        occurrences = {
            number
            for symbol in symbols
            for number, line in enumerate(masked.splitlines(), 1)
            if re.search(rf"(?<![\w$]){re.escape(symbol)}(?![\w$])", line)
            and not re.match(
                rf"\s*(?:export\s+)?(?:declare\s+)?(?:type|interface)\s+{re.escape(symbol)}(?![\w$])",
                line,
            )
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

    def supplied(number):
        return any(
            source.get("url") == selected_url
            and type(source.get("start_line")) is int
            and type(source.get("end_line")) is int
            and source["start_line"] <= number <= source["end_line"]
            for source in sources
        )

    hits = [number for number in occurrences if not supplied(number)]
    if not hits:
        if path.endswith(".py"):
            return _python_import_windows(tree, names, path, supplied, limit)
        return []
    requests = []
    for number in dict.fromkeys((min(hits), max(hits))):
        if any(r["start"] <= number < r["start"] + r["max_lines"] for r in requests):
            continue
        start = max(1, number - 8)
        selected_request = {"path": path, "start": start, "max_lines": 80}
        if reference_scan is not None:
            selected_request["max_lines"] = min(
                80, reference_scan["scanned_through_line"] - start + 1
            )
            selected_request["reference_scan"] = dict(reference_scan)
        requests.append(selected_request)
        if len(requests) == limit:
            break
    return requests


def _python_import_windows(tree, names, path, supplied, limit):
    """Expose syntax only: unique module-level imports, never resolve bindings."""
    requests = []
    for name in names:
        if "." in name:
            continue  # A receiver's attribute need not be this module's import.
        matches = []
        for node in tree.body:
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            for alias in node.names:
                local = alias.asname or (
                    alias.name.split(".")[0]
                    if isinstance(node, ast.Import)
                    else alias.name
                )
                if local == name:
                    matches.append(node)
        if len(matches) != 1:
            continue
        node = matches[0]
        first, last = node.lineno, node.end_lineno
        if last - first >= 80 or all(supplied(n) for n in range(first, last + 1)):
            continue
        if any(r["start"] <= first and last < r["start"] + 80 for r in requests):
            continue
        # Keep the entire import statement within the existing window budget.
        requests.append(
            {"path": path, "start": max(1, first - 8, last - 79), "max_lines": 80}
        )
        if len(requests) == limit:
            break
    return requests
