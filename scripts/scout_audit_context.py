"""Bounded source-discovery context additions, never an omission or verdict."""

import ast


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
