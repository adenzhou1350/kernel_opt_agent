"""Bounded C-family/Python/JS reference hints from a cached pinned source.

Never execute source or fetch a model-provided target. References, declarations
and preprocessor branches are not a call graph or proof of runtime reachability.
"""

import ast
import re
from urllib.parse import unquote, urlsplit

from scout_requested_definition import prefer_supplied_snapshot_source

NATIVE_SUFFIXES = (
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
)
SUFFIXES = NATIVE_SUFFIXES + (
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
    """Reuse the source-read budget for native/Python; keep JS scans smaller."""
    return (
        PYTHON_CACHE_LIMIT
        if path.endswith(NATIVE_SUFFIXES + (".py",))
        else LEXICAL_CACHE_LIMIT
    )


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


def _literal_initializer(node):
    """Recognize literal/uppercase-name container syntax, without evaluation."""
    if node is None:
        return False
    container = isinstance(node, (ast.Tuple, ast.List, ast.Set, ast.Dict))
    for child in ast.walk(node):
        if (
            container
            and isinstance(child, ast.Name)
            and isinstance(child.ctx, ast.Load)
            and re.fullmatch(r"[A-Z][A-Z0-9_]{1,127}", child.id)
        ):
            continue  # An observed symbolic entry, not its resolved value.
        if not isinstance(
            child, (ast.Constant, ast.Tuple, ast.List, ast.Set, ast.Dict, ast.Load)
        ):
            return False
        if isinstance(child, ast.Dict) and any(key is None for key in child.keys):
            return False  # Even literal-looking **unpacking is outside this hint.
    return True


def _python_literal_assignments(tree, names):
    """Locate unambiguous module-level literal assignments, without evaluation.

    Only an unqualified uppercase request admits this extra syntax hint. Any
    other syntactic binding of the name (even in another scope) abstains.
    Scalar and container initializers (including symbolic uppercase entries)
    are source hints, not resolved runtime constants, immutable values, class
    attributes or reachability assertions.
    """
    lines = set()
    nodes = list(ast.walk(tree))
    if any(isinstance(node, ast.alias) and node.name == "*" for node in nodes):
        return lines
    for name in names:
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{1,127}", name):
            continue
        candidates = []
        for node in tree.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                target = node.targets[0]
            elif isinstance(node, ast.AnnAssign):
                target = node.target
            else:
                continue
            if (
                isinstance(target, ast.Name)
                and target.id == name
                and _literal_initializer(node.value)
            ):
                candidates.append(node)
        if len(candidates) != 1:
            continue
        bindings = sum(
            (
                isinstance(node, ast.Name)
                and node.id == name
                and isinstance(node.ctx, (ast.Store, ast.Del))
            )
            or (isinstance(node, ast.arg) and node.arg == name)
            or (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                and node.name == name
            )
            or (
                isinstance(node, ast.alias)
                and (node.asname or node.name.split(".")[0]) == name
            )
            or (
                isinstance(node, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar))
                and node.name == name
            )
            or (isinstance(node, ast.MatchMapping) and node.rest == name)
            for node in nodes
        )
        if bindings == 1:
            lines.add(candidates[0].lineno)
    return lines


def _native_code_lines(raw):
    """Reuse the limited native trivia masking; no macro/binding resolution."""
    if re.search(r'\b(?:u8|u|U|L)?R"', raw):
        return None
    if any(
        m[0].startswith("/*") and not m[0].endswith("*/")
        for m in LITERALS.finditer(raw)
    ):
        return None
    masked = LITERALS.sub(lambda m: re.sub(r"[^\n]", " ", m[0]), raw)
    lines = masked.splitlines()
    directive = False
    for index, line in enumerate(lines):
        if directive or line.lstrip().startswith("#"):
            directive = line.rstrip().endswith("\\")
            lines[index] = ""
    return lines


def native_invocation_hint_line(raw, symbol):
    """Prefer an invocation-shaped occurrence over imports in already-read bytes.

    Return a zero-based line hint, not a resolved call. Declarations and inactive
    branches can match. Unsupported syntax or no match keeps literal fallback.
    """
    if (
        not isinstance(raw, str)
        or len(raw.encode("utf-8")) > PYTHON_CACHE_LIMIT
        or not isinstance(symbol, str)
        or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", symbol)
    ):
        return None
    lines = _native_code_lines(raw)
    if lines is None:
        return None
    masked = "\n".join(lines)
    match = re.search(rf"\b{re.escape(symbol)}\s*\(", masked)
    return masked.count("\n", 0, match.start()) if match else None


def python_invocation_hint_line(raw, symbol):
    """First matching Python call target, not an import or resolved binding.

    A syntactic call can be shadowed, conditional or a decorator. Parse existing
    bounded text only; invalid/unsupported source retains the caller's ordinary
    literal fallback rather than proving that no invocation exists.
    """
    if (
        not isinstance(raw, str)
        or not isinstance(symbol, str)
        or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", symbol)
        or len(raw.encode("utf-8")) > PYTHON_CACHE_LIMIT
        or "\x00" in raw
    ):
        return None
    try:
        tree = ast.parse(raw)
    except (SyntaxError, ValueError, RecursionError):
        return None
    lines = [
        node.func.end_lineno - 1
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, (ast.Name, ast.Attribute))
        and (node.func.id if isinstance(node.func, ast.Name) else node.func.attr)
        == symbol
    ]
    return min(lines) if lines else None


def _reference_source(packet, snapshot, analysis, cached_source):
    """Resolve the existing literal source/cache scope, never a new target."""
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
    selected = prefer_supplied_snapshot_source(sources, selected, repo, commit)
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
    return names, symbols, sources, selected_url, path, raw


def definition_only_reference_path(packet, snapshot, analysis, cached_source):
    """Hint that a named Python class's consumers may be in another file.

    Require one explicit unqualified class reference, one cached module-level
    declaration and no direct syntactic loads or obvious competing bindings.
    Not a resolved binding, exhaustive use inventory or runtime-absence proof;
    callers may reuse their existing bounded repository-search route only.
    """
    request = analysis.get("next_check", "")
    if (not callable(cached_source) or not isinstance(request, str)
            or len(re.findall(r"(?<!\w)(?:definition|references)[ \t]*\(", request[:2000])) != 1):
        return None
    selected = _reference_source(packet, snapshot, analysis, cached_source)
    if not selected:
        return None
    names, _, _, _, path, raw = selected
    if (len(names) != 1 or not path.endswith(".py")
            or not re.fullmatch(r"[A-Z][A-Za-z0-9_]{3,127}", names[0])):
        return None
    name = names[0]
    try:
        tree = ast.parse(raw)
    except (SyntaxError, ValueError, RecursionError):
        return None
    declarations = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == name]
    if len(declarations) != 1 or declarations[0].decorator_list:
        return None
    for node in ast.walk(tree):
        if node is declarations[0]:
            continue
        if ((isinstance(node, ast.Name) and node.id == name)
                or (isinstance(node, ast.Attribute) and node.attr == name)
                or (isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef, ast.arg))
                    and getattr(node, "name", getattr(node, "arg", None)) == name)
                or (isinstance(node, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar)) and node.name == name)
                or (isinstance(node, ast.MatchMapping) and node.rest == name)
                or (isinstance(node, ast.alias) and (node.asname or node.name.split('.')[0]) in {name, '*'})
                or (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id in {"getattr", "hasattr"} and len(node.args) >= 2
                    and isinstance(node.args[1], ast.Constant) and node.args[1].value == name)):
            return None
    return path


def reference_requests(packet, snapshot, analysis, cached_source, *, limit=2):
    """Honor references(NAME), with <=2 cached same-pin source windows.

    Select the primary or one unambiguously named already-supplied file.
    Qualified names are terminal-identifier hints, not resolved receivers.
    Python AST loads/literal getattr/hasattr exclude comments and definitions;
    unqualified uppercase names also admit unambiguous literal assignments.
    Otherwise a unique import can supply its observed guard, not a resolved value.
    C-family directives/literals are masked; declarations can still match.
    JS/TS scans stop at unsupported syntax with a disclosed complete-line prefix.
    First/last unseen windows are not exhaustive consumers or reachability proof.
    Missing, drifted, ambiguous or unsupported cached sources abstain without
    fetching. Already-shown references do not create another read request.
    """
    if type(limit) is not int or not 1 <= limit <= 2:
        raise ValueError("reference context limit must be 1..2")
    selected = _reference_source(packet, snapshot, analysis, cached_source)
    if not selected:
        return []
    names, symbols, sources, selected_url, path, raw = selected
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
        occurrences.update(_python_literal_assignments(tree, names))
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
        lines = _native_code_lines(raw)
        if lines is None:
            return []
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

    def module_imports(body, guards=()):
        for node in body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                yield node, guards
            elif isinstance(node, (ast.If, ast.Try)):
                nested = (*guards, node.lineno)
                yield from module_imports(node.body, nested)
                yield from module_imports(node.orelse, nested)
                if isinstance(node, ast.Try):
                    for handler in node.handlers:
                        yield from module_imports(
                            handler.body, (*nested, handler.lineno)
                        )
                    yield from module_imports(node.finalbody, nested)

    imports = list(module_imports(tree.body))
    requests = []
    for name in names:
        if "." in name:
            continue  # A receiver's attribute need not be this module's import.
        matches = []
        for node, guards in imports:
            for alias in node.names:
                local = alias.asname or (
                    alias.name.split(".")[0]
                    if isinstance(node, ast.Import)
                    else alias.name
                )
                if local == name:
                    matches.append((node, guards))
        if len(matches) != 1:
            continue
        node, guards = matches[0]
        first = min([node.lineno, *(g for g in guards if not supplied(g))])
        last = node.end_lineno
        if last - first >= 80 or all(supplied(n) for n in range(node.lineno, last + 1)):
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
