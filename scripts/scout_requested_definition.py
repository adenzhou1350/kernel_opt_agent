"""Select one observed Python function from an explicit next-evidence request.

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
    text = "\n".join(lines)
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError):
        return None
    qualified = set(re.findall(r"\b([A-Z][A-Za-z0-9_]*)\.([A-Za-z_]\w*)\b", request[:2000]))
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
        names = set(re.findall(r"[A-Za-z_]\w{2,}", request[:2000]))
        matches = [node for node in ast.walk(tree) if isinstance(node, functions) and node.name in names]
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
