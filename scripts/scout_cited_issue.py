"""A verified displayed issue citation may supply one related-work query.

Never adopt it as candidate focus, fetch a model URL or classify duplication.
"""

import re


def cited_issue_number(repo, sources, analysis):
    """Return one unambiguous issue already displayed and exactly quoted.

    Inspect at most five citations and 25 bounded source excerpts. Malformed,
    ambiguous, cross-repository, comment-only and invented references abstain.
    The caller constructs its existing controller-owned API query from the number.
    """
    if not isinstance(repo, str) or not re.fullmatch(
        r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo
    ):
        return None
    if not isinstance(sources, list) or not isinstance(analysis, dict):
        return None
    evidence = analysis.get("evidence")
    if not isinstance(evidence, list):
        return None
    pattern = re.compile(
        r"https://github\.com/" + re.escape(repo) + r"/issues/([1-9][0-9]{0,9})"
    )
    displayed = {}
    for source in sources[:25]:
        if not isinstance(source, dict):
            continue
        url, text = source.get("url"), source.get("text")
        if isinstance(url, str) and isinstance(text, str) and len(text) <= 10000:
            displayed.setdefault(url, []).append(text)
    numbers = set()
    for reference in evidence[:5]:
        if not isinstance(reference, dict):
            continue
        url, quote = reference.get("url"), reference.get("quote")
        if not isinstance(url, str) or not isinstance(quote, str):
            continue
        match = pattern.fullmatch(url)
        if (
            match
            and int(match[1]) <= 1_000_000_000
            and 20 <= len(quote.strip()) <= 600
            and any(quote in text for text in displayed.get(url, []))
        ):
            numbers.add(int(match[1]))
    return numbers.pop() if len(numbers) == 1 else None
