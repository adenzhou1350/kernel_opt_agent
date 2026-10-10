"""Select an observed Python function, or an explicitly requested class.

Syntax-only, never imported/executed code or production-reachability proof.
Ambiguous/missing/non-Python declarations fall back to existing context selection.
"""
import ast
import io
import re
import tokenize


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
