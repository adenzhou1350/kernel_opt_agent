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


def validate_source_ranges(ranges, *, max_lines=80, max_chars=4500):
    """Validate a jointly bounded, ordered set before any source acquisition."""
    if (
        type(max_lines) is not int or not 1 <= max_lines <= 80
        or type(max_chars) is not int or not 1 <= max_chars <= 10000
        or not isinstance(ranges, (list, tuple)) or not 1 <= len(ranges) <= 8
    ):
        raise ValueError("invalid excerpt-set budget or ranges")
    checked = []
    for item in ranges:
        if (
            not isinstance(item, dict) or set(item) != {"start_line", "line_count"}
            or type(item["start_line"]) is not int or item["start_line"] < 1
            or type(item["line_count"]) is not int or item["line_count"] < 1
        ):
            raise ValueError("invalid source range")
        checked.append(dict(item))
    if sum(item["line_count"] for item in checked) > max_lines:
        raise ValueError("source ranges exceed shared line budget")
    ordered = sorted(checked, key=lambda item: item["start_line"])
    if any(
        left["start_line"] + left["line_count"] > right["start_line"]
        for left, right in zip(ordered, ordered[1:])
    ):
        raise ValueError("overlapping source ranges")
    return checked


def source_windows(text, ranges, *, max_lines=80, max_chars=4500):
    """Select disjoint exact ranges from one source under a shared budget.

    Unlike the single-window reader, no requested range is silently shortened
    at EOF or to fit characters. A failed set exposes no partial source text.
    Character cost is the sum of excerpt text plus one newline between ranges;
    metadata/JSON/prompt overhead is separate and must also be budgeted by callers.
    This optional primitive does not change any historical trial or live policy.
    """
    checked = validate_source_ranges(ranges, max_lines=max_lines, max_chars=max_chars)
    windows = []
    used = 0
    for index, item in enumerate(checked):
        window = source_window(
            text, start_line=item["start_line"],
            max_lines=item["line_count"], max_chars=max_chars,
        )
        if window["status"] != "ACQUIRED":
            return {"status": "FAILED", "error_kind": window["error_kind"],
                    "failed_range": index}
        if window["end_line"] - window["start_line"] + 1 != item["line_count"]:
            return {"status": "FAILED", "error_kind": "INCOMPLETE_REQUESTED_RANGE",
                    "failed_range": index}
        used += len(window["text"]) + bool(windows)
        if used > max_chars:
            return {"status": "FAILED", "error_kind": "SHARED_CHAR_BUDGET_EXCEEDED",
                    "failed_range": index}
        windows.append(window)
    return {
        "status": "ACQUIRED", "source_sha256": windows[0]["source_sha256"],
        "windows": windows, "selected_lines": sum(i["line_count"] for i in checked),
        "selected_chars": used,
    }
