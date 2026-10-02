"""Bounded source excerpts by exact line or unique literal, without execution.

Language-neutral text location, not a parser, definition resolver or quality
judgment. A match can be in a comment/string; callers must inspect its meaning.
"""

import hashlib


def source_window(text, *, start_line=None, anchor=None, max_lines=80, max_chars=10000):
    """Select one window; never guess, wrap EOF, repair or silently fall back.

    Anchors are single-line literal substrings, at most 512 characters, occurring
    exactly once in the complete source. Repeated substrings on one line are
    also ambiguous. Returns source digest and one-based bounds only on success.
    """
    if (
        type(max_lines) is not int
        or not 1 <= max_lines <= 80
        or type(max_chars) is not int
        or not 1 <= max_chars <= 10000
    ):
        raise ValueError("invalid excerpt budget")

    def fail(reason):
        return {"status": "FAILED", "error_kind": reason}

    if not isinstance(text, str) or len(text) > 1_000_000:
        return fail("INVALID_SOURCE")
    try:
        raw = text.encode("utf-8")
    except UnicodeEncodeError:
        return fail("INVALID_SOURCE")
    if len(raw) > 1_000_000:
        return fail("SOURCE_LIMIT_EXCEEDED")
    if (start_line is None) == (anchor is None):
        return fail("EXACTLY_ONE_SELECTOR_REQUIRED")
    if anchor is not None:
        if (
            not isinstance(anchor, str)
            or not anchor.strip()
            or len(anchor) > 512
            or any(c in anchor for c in "\r\n\x00")
        ):
            return fail("INVALID_LITERAL_ANCHOR")
        offset = text.find(anchor)
        if offset < 0:
            return fail("ANCHOR_NOT_FOUND")
        if text.find(anchor, offset + 1) >= 0:
            return fail("AMBIGUOUS_ANCHOR")
        # Match splitlines' CRLF/LF/CR handling without changing source bytes.
        prefix = text[:offset].replace("\r\n", "\n").replace("\r", "\n")
        start_line = prefix.count("\n") + 1
    elif type(start_line) is not int or start_line < 1:
        return fail("INVALID_START_LINE")
    # Only conventional source newlines, not Unicode separators in literals.
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    if start_line > len(lines):
        return fail("WINDOW_BEYOND_SOURCE")
    selected = []
    used = 0
    for line in lines[start_line - 1 : start_line - 1 + max_lines]:
        needed = len(line) + (1 if selected else 0)
        if used + needed > max_chars:
            break
        selected.append(line)
        used += needed
    if not selected:
        return fail("FIRST_LINE_EXCEEDS_CHAR_BUDGET")
    end_line = start_line + len(selected) - 1
    return {
        "status": "ACQUIRED",
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "selector": "literal" if anchor is not None else "line",
        "start_line": start_line,
        "end_line": end_line,
        "truncated": end_line < len(lines),
        "text": "\n".join(selected),
    }
