"""Bounded source-discovery context additions, never an omission or verdict."""

import ast
import urllib.parse


def contextual_audit_owners(context, repo, commit, path, source):
    """Label Python window ownership from pinned cached bytes, without fetching.

    A window can begin inside one function and end inside another. Names and
    full-file AST ranges help distinguish them without copying their bodies or
    claiming that a lexical definition proves runtime dispatch or reachability.
    The range is explicitly the original window if packet fitting trims later.
    """
    start, end, total = (source.get(key) for key in
                         ("start_line", "end_line", "total_lines"))
    if not (path.endswith(".py")
            and all(type(value) is int for value in (start, end, total))
            and 1 <= start <= end <= total):
        return source
    url = (f"https://raw.githubusercontent.com/{repo}/{commit}/"
           + urllib.parse.quote(path, safe="/"))
    key, load = getattr(context, "_cache_path", None), getattr(context, "_load", None)
    if source.get("url") != url or not callable(key) or not callable(load):
        return source
    cached = load(key("raw", [repo, commit, path]))
    raw = cached.get("text") if isinstance(cached, dict) and cached.get("url") == url else None
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > 1_000_000:
        return source
    lines = raw.splitlines()
    if len(lines) != total or source.get("text") != "\n".join(
        f"{i + 1}: {lines[i]}" for i in range(start - 1, end)
    ):
        return source
    try:
        tree = ast.parse(raw)
    except (SyntaxError, ValueError, RecursionError):
        return source
    definitions, omitted = [], False
    stack = [(tree, "")]
    while stack:
        node, prefix = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            name = prefix + node.name
            first, last = node.lineno, node.end_lineno
            if last < start or first > end:
                continue
            if not isinstance(node, ast.ClassDef):
                if len(definitions) < 4 and len(name.encode("utf-8")) <= 128:
                    definitions.append({"qualified_name": name,
                                        "start_line": first, "end_line": last})
                else:
                    omitted = True
            prefix = name + "."
        stack.extend((child, prefix) for child in reversed(list(ast.iter_child_nodes(node))))
    if not definitions:
        return source
    return {**source, "python_definition_context": {
        "window_start_line": start, "window_end_line": end,
        "definitions": definitions, "omitted": omitted,
        "scope": "Lexical ownership of the original window, not runtime dispatch or complete bodies.",
    }}


def contextual_audit_header(context, repo, commit, path, source):
    """Extend an import-only Python prefix within the existing 160-line cap.

    Inspect only already-cached immutable bytes. Retain every numbered original
    line; imports can have side effects and export compatibility bugs. Do not
    change sweep/seen keys or apply this to explicit follow-up selectors. A
    syntax/identity/budget uncertainty keeps ordinary discovery unchanged.
    """
    end, total = source.get("end_line"), source.get("total_lines")
    if not (
        path.endswith(".py")
        and source.get("start_line") == 1
        and type(end) is int and 1 <= end <= 120
        and type(total) is int and end < total
        and isinstance(source.get("text"), str) and source["text"]
    ):
        return source
    cached = getattr(context, "cached_source_text", None)
    if callable(cached):
        raw = cached(repo, commit, path)
    else:
        # Compatibility with the existing PublicContext cache before the
        # optional reference-hint reader was introduced. No cache fill/GET.
        key = getattr(context, "_cache_path", None)
        load = getattr(context, "_load", None)
        if not callable(key) or not callable(load):
            return source
        record = load(key("raw", [repo, commit, path]))
        raw = record.get("text") if (
            isinstance(record, dict) and record.get("url") == source.get("url")
        ) else None
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > 1_000_000:
        return source
    lines = raw.splitlines()
    if len(lines) != total or source["text"] != "\n".join(
        f"{i + 1}: {lines[i]}" for i in range(end)
    ):
        return source
    try:
        tree = ast.parse(raw)
    except (SyntaxError, ValueError, RecursionError):
        return source
    first = next((node for node in tree.body if not (
        isinstance(node, (ast.Import, ast.ImportFrom))
        or isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )), None)
    # Don't extend an actual implementation, export assignment, capability
    # probe, or side-effect call; nor a forwarding-only file with no next body.
    if first is None or not end < first.lineno <= 160:
        return source
    expanded_end = min(160, total)
    text = "\n".join(f"{i + 1}: {lines[i]}" for i in range(expanded_end))
    # Match PublicContext's 9,000-character excerpt cap. Do not call source():
    # even a raw-cache hit could revalidate repository visibility over network.
    # A larger packet that would clip the retained prefix/body is not helpful.
    if len(text) > 9000:
        return source
    return {**source, "text": text, "end_line": expanded_end,
            "truncated": expanded_end < total}
