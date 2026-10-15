"""Python declaration selection and qualified C++ literal source locations.

Syntax-only, never imported/executed code or production-reachability proof.
Ambiguous/missing declarations fall back to existing context selection. C++
locations are explicitly lexical, not parsed definitions or complete bodies.
"""
import ast
import io
import re
import tokenize
from urllib.parse import unquote


def cached_qualified_definition_path(packet, snapshot, analysis, cached_source):
    """Locate one explicit Class.method declaration in <=8 already-cached files.

    No fetch, import, execution, new path or receiver-resolution claim. Ambiguous
    or unavailable caches abstain. Callers retain their existing read budgets.
    """
    request = analysis.get("next_check") if isinstance(analysis, dict) else None
    if not isinstance(request, str) or not callable(cached_source):
        return None
    request = request[:2000]
    if len(re.findall(r"(?<!\w)definition[ \t]*\(", request)) != 1:
        return None
    if not re.search(
        r"(?<!\w)definition[ \t]*\([ \t]*[A-Za-z_]\w{0,127}"
        r"\.[A-Za-z_]\w{0,127}[ \t]*\)", request
    ):
        return None
    repo, commit = packet.get("repo"), snapshot.get("commit")
    if (
        not isinstance(repo, str)
        or not isinstance(commit, str)
        or not re.fullmatch(r"[0-9a-f]{40}", commit)
    ):
        return None
    prefix = f"https://raw.githubusercontent.com/{repo}/{commit}/"
    files = set(snapshot.get("files", []))
    candidates = []
    for source in packet.get("sources", [])[:8]:
        url = source.get("url") if isinstance(source, dict) else None
        if not isinstance(url, str) or not url.startswith(prefix):
            continue
        path = unquote(url[len(prefix) :])
        if path in files and path.endswith(".py") and path not in candidates:
            candidates.append(path)
    explicit_paths = [path for path in candidates if path in request]
    matches = []
    for path in candidates:
        if explicit_paths and path not in explicit_paths:
            continue
        try:
            raw = cached_source(repo, commit, path)
            if not isinstance(raw, str) or len(raw) > 1_000_000:
                continue
            target = requested_function_window(raw.splitlines(), request)
        except (OSError, ValueError, RecursionError):
            continue
        if target is not None:
            matches.append(path)
    return matches[0] if len(matches) == 1 else None


def requested_native_literal_anchor(raw, request):
    """Locate one explicit qualified C++ literal, not a parsed definition.

    Comments/generated strings and inactive branches are not resolved. Repeated
    occurrences abstain; no overload/owner/body inference or complete-body flag.
    """
    if not isinstance(raw, str) or len(raw) > 1_000_000 or not isinstance(request, str):
        return None
    request = request[:2000]
    markers = list(re.finditer(r"(?<!\w)definition[ \t]*\(", request))
    if len(markers) != 1:
        return None
    match = re.match(
        r"[ \t]*([A-Za-z_][A-Za-z0-9_]{0,127}"
        r"(?:::[A-Za-z_][A-Za-z0-9_]{0,127}){1,4})[ \t]*\)",
        request[markers[0].end():],
    )
    if match is None or len(match[1]) > 256:
        return None
    symbol = match[1]
    pattern = rf"(?<![\w:]){re.escape(symbol)}(?![\w:])\s*\("
    matches = re.finditer(pattern, raw)
    first = next(matches, None)
    if first is None or next(matches, None) is not None:
        return None
    return {
        "literal": symbol,
        "line": raw.count("\n", 0, first.start()) + 1,
        "scope": (
            "Unique requested qualified literal followed by ( in this pinned "
            "C-family file, including comments/strings. Not a parsed definition, "
            "resolved owner, active preprocessor branch or complete body."
        ),
    }


def absent_requested_identifiers(raw, request):
    """Disclose missing literal names in already-read source, in any language.

    Do not silently substitute a spelling or infer a missing declaration. Even
    a comment/string occurrence prevents this conservative absence observation.
    Qualified requests test only their terminal identifier, not a binding.
    """
    if not isinstance(raw, str) or not isinstance(request, str):
        return []
    request = request[:2000]
    markers = list(re.finditer(r"(?<!\w)(?:definition|references)[ \t]*\(", request))
    names = []
    for marker in markers:
        match = re.match(
            r"[ \t]*([A-Za-z_][A-Za-z0-9_]{0,127}"
            r"(?:\.[A-Za-z_][A-Za-z0-9_]{0,127}){0,4})[ \t]*\)",
            request[marker.end():],
        )
        if match is None:
            return []
        name = match[1].rsplit(".", 1)[-1]
        if name not in names:
            names.append(name)
    if not 1 <= len(names) <= 2:
        return []
    return [name for name in names if name not in raw]


def requested_definition_inventory(lines, request, symbol):
    """Expose ambiguous Python declarations without selecting a receiver/body.

    Only an explicit unqualified definition(symbol) activates this advisory
    inventory. Its source is the already acquired exact file, not another read.
    """
    if not isinstance(symbol, str) or not re.fullmatch(
        r"[A-Za-z_][A-Za-z0-9_]{3,127}", symbol
    ):
        return None
    if not isinstance(request, str) or not re.search(
        rf"(?<!\w)definition[ \t]*\([ \t]*{re.escape(symbol)}[ \t]*\)",
        request[:2000],
    ):
        return None
    try:
        tree = ast.parse("\n".join(lines))
    except (SyntaxError, ValueError, RecursionError):
        return None
    declarations = (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    stack = [(tree, ())]
    matches = []
    while stack:
        node, owners = stack.pop()
        if isinstance(node, declarations):
            qualified = owners + (node.name,)
            if node.name == symbol:
                name = ".".join(qualified)
                # Do not admit an unbounded lexical owner into a model packet.
                if len(name) > 256:
                    return None
                matches.append(
                    {
                        "qualified_name": name,
                        "kind": type(node).__name__,
                        "declaration_line": node.lineno,
                        "end_line": node.end_lineno,
                    }
                )
            owners = qualified
        stack.extend((child, owners) for child in ast.iter_child_nodes(node))
    if len(matches) < 2:
        return None
    matches.sort(key=lambda item: item["declaration_line"])
    return {
        "symbol": symbol,
        "total_matches": len(matches),
        "candidates": matches[:8],
        "truncated": len(matches) > 8,
        "scope": (
            "Syntax-only declarations in this pinned Python file; locations may be "
            "outside the visible body window. Not receiver resolution, inheritance "
            "dispatch, callable identity or proof of unread implementation behavior."
        ),
    }


def requested_function_window(lines, request):
    if not request:
        return None
    request = request[:2000]
    # Explicit syntax chooses the evidence target, not other API names in the
    # explanation. Reject malformed/multiple targets rather than silently
    # selecting a different function mentioned in prose.
    markers = list(re.finditer(r"(?<!\w)definition[ \t]*\(", request))
    explicit = set()
    for marker in markers:
        match = re.match(
            r"[ \t]*([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?)[ \t]*\)",
            request[marker.end():],
        )
        if match is None:
            return None
        explicit.add(match[1])
    if markers and len(explicit) != 1:
        return None
    if explicit:
        request = next(iter(explicit))
    text = "\n".join(lines)
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError):
        return None
    qualified = set(re.findall(r"\b([A-Z][A-Za-z0-9_]*)\.([A-Za-z_]\w*)\b", request))
    if explicit and "." in request:
        qualified = {tuple(request.split("."))}
    functions = (ast.FunctionDef, ast.AsyncFunctionDef)
    if qualified:
        if len(qualified) != 1:
            return None
        owner, name = next(iter(qualified))
        classes = [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef) and node.name == owner]
        if len(classes) != 1:
            return None
        matches = [node for node in classes[0].body if isinstance(node, functions) and node.name == name]
    else:
        names = explicit or set(re.findall(r"[A-Za-z_]\w{2,}", request))
        # Classes can contain the requested lifecycle evidence. Admit them only
        # for definition(Name), not incidental class names in free-form prose.
        # A same-name function/class remains ambiguous rather than guessing.
        declarations = functions + (ast.ClassDef,) if explicit else functions
        matches = [node for node in ast.walk(tree) if isinstance(node, declarations) and node.name in names]
    if len(matches) != 1:
        return None
    node = matches[0]
    start = node.lineno
    if node.decorator_list:
        # AST decorator expressions can start *inside* a parenthesized @(...).
        # Find its actual @ token, not a comment/string or a matrix operator.
        first_expression = min(decorator.lineno for decorator in node.decorator_list)
        for token in tokenize.generate_tokens(io.StringIO(text).readline):
            if token.start[0] > first_expression:
                break
            if (token.type == tokenize.OP and token.string == "@"
                    and token.start[1] == node.col_offset):
                start = token.start[0]
    return {"name": node.name, "start_line": start, "end_line": node.end_lineno}
