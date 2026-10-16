"""Literal bounded issue excerpts; never infer ownership or authorize actions."""

import re

OMISSION = "\n[... middle of issue omitted ...]\n"


def _middle_work_section(text, earliest, budget):
    """Locate one literal work heading outside simple Markdown fences."""
    cursor, start, fence = 0, None, None
    for line in text.splitlines(keepends=True):
        if start is not None and cursor - start >= budget:
            return start, start + budget
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if marker:
            token = marker[1]
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence) and not line[marker.end():].strip():
                fence = None
        elif fence is None:
            heading = re.match(r"^ {0,3}#{1,6}[ \t]+(.{1,200})", line)
            if start is not None and (heading or line.startswith(OMISSION.strip())):
                return start, min(cursor, start + budget)
            if (heading and cursor >= earliest and re.search(
                r"\b(?:workaround|patch|proposed[ \t]+fix|suggested[ \t]+fix)\b",
                heading[1], re.I,
            )):
                start = cursor
        cursor += len(line)
    return (start, min(len(text), start + budget)) if start is not None else None


def issue_text_excerpt(text, limit):
    """Keep both ends and one literal work section within the same budget."""
    if not isinstance(text, str) or type(limit) is not int or limit < 128:
        raise ValueError("issue excerpt needs text and a limit of at least 128")
    if len(text) <= limit:
        return text
    available = limit - len(OMISSION)
    tail = available // 3
    if limit >= 512:
        middle_budget = min(1000, limit // 3)
        reserved = limit - middle_budget - 2 * len(OMISSION)
        middle = _middle_work_section(text, reserved - reserved // 3, middle_budget)
        if middle is not None:
            start, end = middle
            remaining = limit - (end - start) - 2 * len(OMISSION)
            end_budget = remaining // 3
            head_budget = remaining - end_budget
            if head_budget <= start < end <= len(text) - end_budget:
                return (text[:head_budget] + OMISSION + text[start:end]
                        + OMISSION + text[-end_budget:])
    return text[: available - tail] + OMISSION + text[-tail:]


def issue_evidence(url, title, body, *, already_truncated=False, limit=5000):
    text = title + "\n" + body
    return {
        "url": url,
        "text": issue_text_excerpt(text, limit),
        "truncated": bool(already_truncated) or len(text) > limit,
        "issue_excerpt": "head-tail",
    }
