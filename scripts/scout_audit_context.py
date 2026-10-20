"""Bounded source-discovery context additions, never an omission or verdict."""

import ast
import hashlib
import re
import urllib.parse


def contextual_audit_tests(context, repo, snapshot, path, source):
    """One cached Rust inline-test window instead of a basename-only companion.

    This is a literal retrieval hint, not a Rust parser: cfg activity, macros,
    comments/strings, binding, completeness and test execution are unresolved.
    Preserve the original window and existing 70-line optional-source budget.
    Missing/mismatched cache leaves ordinary companion selection unchanged.
    """
    commit, blob = snapshot.get("commit"), snapshot.get("blobs", {}).get(path)
    reader = getattr(context, "cached_source_text", None)
    if (not path.endswith(".rs") or path not in snapshot.get("files", [])
            or not callable(reader) or not isinstance(commit, str)
            or not re.fullmatch(r"[0-9a-f]{40}", commit)
            or not isinstance(blob, str) or not re.fullmatch(r"[0-9a-f]{40}", blob)):
        return None
    url = (f"https://raw.githubusercontent.com/{repo}/{commit}/"
           + urllib.parse.quote(path, safe="/"))
    if source.get("url") != url:
        return None
    try:
        raw = reader(repo, commit, path)
        data = raw.encode("utf-8") if isinstance(raw, str) else None
    except (OSError, ValueError, UnicodeEncodeError):
        return None
    if (data is None or len(data) > 512 * 1024 or b"\0" in data
            or hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest() != blob):
        return None
    lines = raw.splitlines()
    start, end, total = (source.get(key) for key in ("start_line", "end_line", "total_lines"))
    if (any(type(value) is not int for value in (start, end, total))
            or not 1 <= start <= end <= total or total != len(lines)
            or source.get("text") != "\n".join(
                f"{i + 1}: {lines[i]}" for i in range(start - 1, end))):
        return None
    modules = list(re.finditer(r"(?m)^#\[cfg\(test\)\][ \t]*\r?\nmod tests[ \t]*\{", raw))
    if len(modules) != 1:
        return None
    # Conventional top-level trailing module only; ambiguous layouts abstain.
    tail = raw[modules[0].end():]
    if re.search(r"(?m)^\S", tail.rstrip().removesuffix("}")):
        return None
    tests = list(re.finditer(r"(?m)^[ \t]+#\[test\][ \t]*\r?\n[ \t]+(?:async[ \t]+)?fn[ \t]+([A-Za-z_]\w*)[ \t]*\(", tail))
    if not tests:
        return None
    module_line = raw.count("\n", 0, modules[0].start()) + 1
    if start >= module_line:
        return None
    visible_implementation = "\n".join(lines[start - 1:min(end, module_line - 1)])
    names = set(re.findall(r"\bfn[ \t]+([A-Za-z_]\w{3,})[ \t]*(?:<|\()", visible_implementation))
    selected = min(tests, key=lambda match: (
        -sum(match[1] == name or match[1].startswith(name + "_") for name in names),
        match.start(),
    ))
    first = raw.count("\n", 0, modules[0].end() + selected.start()) + 1
    last = min(total, first + 69)
    if start <= first <= last <= end:
        return None
    text = "\n".join(f"{i + 1}: {lines[i]}" for i in range(first - 1, last))
    if len(text) > 9000:
        return None
    return dict(url=url, text=text, start_line=first, end_line=last,
                total_lines=total, truncated=first > 1 or last < total,
                inline_test_hint=dict(name=selected[1], scope=(
                    "Literal same-file cfg(test)/test-name hint; not execution, "
                    "active cfg, parsed binding or complete behavioral coverage.")))


def contextual_audit_owners(context, repo, commit, path, source):
    """Label Python window ownership from pinned cached bytes, without fetching.

    A window can begin inside one function and end inside another. Names and
    full-file AST ranges help distinguish them without copying their bodies or
    claiming that a lexical definition proves runtime dispatch or reachability.
    The range is explicitly the original window if packet fitting trims later.
    Under the four-definition cap, retain the innermost owners of both window
    edges before filling with earlier overlaps. This is not a body extension.
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
    boundary_owners = {}
    stack = [(tree, "")]
    while stack:
        node, prefix = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            name = prefix + node.name
            first, last = node.lineno, node.end_lineno
            if last < start or first > end:
                continue
            if not isinstance(node, ast.ClassDef):
                if len(name.encode("utf-8")) <= 128:
                    definition = {"qualified_name": name,
                                  "start_line": first, "end_line": last}
                    if len(definitions) < 4:
                        definitions.append(definition)
                    else:
                        omitted = True
                    for edge in (start, end):
                        previous = boundary_owners.get(edge)
                        if first <= edge <= last and (
                            previous is None or last - first
                            < previous["end_line"] - previous["start_line"]
                        ):
                            boundary_owners[edge] = definition
                else:
                    omitted = True
            prefix = name + "."
        stack.extend((child, prefix) for child in reversed(list(ast.iter_child_nodes(node))))
    if not definitions:
        return source
    # At most two edge owners plus the original four candidates are retained;
    # do not accumulate full-file metadata or acquire any extra source text.
    selected = []
    for definition in (*boundary_owners.values(), *definitions):
        if definition not in selected and len(selected) < 4:
            selected.append(definition)
    definitions = sorted(selected, key=lambda item: (
        item["start_line"], -item["end_line"], item["qualified_name"]))
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
