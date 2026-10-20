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


def _quoted_lines_excerpt(text, limit, quotes):
    """Prior citations are hints only: select literal lines still present now."""
    budget = min(1000, limit // 3)
    spans = []
    for quote in quotes[:5]:
        if (not isinstance(quote, str) or not 1 <= len(quote) <= 300
                or OMISSION.strip() in quote or text.count(quote) != 1):
            continue
        start = text.index(quote)
        end = start + len(quote)
        start = text.rfind('\n', 0, start) + 1
        stop = text.find('\n', end)
        end = len(text) if stop == -1 else stop
        # Keep the complete line, including adjacent qualifications. A long or
        # ambiguous line is unavailable, not permission to paraphrase a quote.
        span = (start, end)
        if span in spans or end - start + len(OMISSION) > budget:
            continue
        spans.append(span)
        budget -= end - start + len(OMISSION)
    if not spans:
        return None
    remaining = limit - sum(b-a for a, b in spans) - (len(spans)+1)*len(OMISSION)
    tail = remaining // 3
    windows = sorted([(0, remaining-tail), *spans, (len(text)-tail, len(text))])
    merged = []
    for start, end in windows:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return OMISSION.join(text[a:b] for a, b in merged)


def issue_text_excerpt(text, limit, *, quotes=()):
    """Keep ends/work section, or bounded current lines of prior citations.

    Citation hints do not validate a claim or bring missing source text back.
    Overlong/ambiguous lines and small budgets retain ordinary excerpting.
    """
    if not isinstance(text, str) or type(limit) is not int or limit < 128:
        raise ValueError("issue excerpt needs text and a limit of at least 128")
    if not isinstance(quotes, (tuple, list)) or len(quotes) > 5:
        raise ValueError("issue excerpt supports at most five citation hints")
    if len(text) <= limit:
        return text
    if quotes and limit >= 512:
        anchored = _quoted_lines_excerpt(text, limit, quotes)
        if anchored is not None:
            return anchored
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
