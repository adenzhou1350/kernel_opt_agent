"""Select an observed Python function, or an explicitly requested class.

Syntax-only, never imported/executed code or production-reachability proof.
Ambiguous/missing/non-Python declarations fall back to existing context selection.
"""
import ast
import io
import re
import tokenize


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
