"""Literal bounded issue excerpts; never infer ownership or authorize actions."""

OMISSION = "\n[... middle of issue omitted ...]\n"


def issue_text_excerpt(text, limit):
    """Keep both ends within the existing character budget, explicitly partial."""
    if not isinstance(text, str) or type(limit) is not int or limit < 128:
        raise ValueError("issue excerpt needs text and a limit of at least 128")
    if len(text) <= limit:
        return text
    available = limit - len(OMISSION)
    tail = available // 3
    return text[: available - tail] + OMISSION + text[-tail:]


def issue_evidence(url, title, body, *, already_truncated=False, limit=5000):
    text = title + "\n" + body
    return {
        "url": url,
        "text": issue_text_excerpt(text, limit),
        "truncated": bool(already_truncated) or len(text) > limit,
        "issue_excerpt": "head-tail",
    }
