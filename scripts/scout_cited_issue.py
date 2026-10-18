"""A verified displayed issue citation may supply one related-work query.

Never adopt it as candidate focus, fetch a model URL or classify duplication.
"""

import re

try:
    from .scout_issue_excerpt import issue_evidence
except ImportError:
    from scout_issue_excerpt import issue_evidence


def requested_issue_number(repo, sources, analysis):
    """First explicit next-check reference to an already displayed canonical issue."""
    if not isinstance(repo, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        return None
    if not isinstance(sources, list) or not isinstance(analysis, dict):
        return None
    request = analysis.get('next_check')
    if not isinstance(request, str):
        return None
    pattern = re.compile(r'https://github\.com/'+re.escape(repo)+r'/issues/([1-9][0-9]{0,9})')
    displayed = set()
    for source in sources[:25]:
        match = pattern.fullmatch(source.get('url', '')) if isinstance(source, dict) and isinstance(source.get('url'), str) else None
        if match and int(match[1]) <= 1_000_000_000:
            displayed.add(int(match[1]))
    for match in re.finditer(r'https?://[^\s<>"\']+|(?<![\w/#])#([1-9][0-9]{0,9})(?!\w)', request[:2000]):
        local = pattern.fullmatch(match[0].rstrip('.,;:()')) if not match[1] else None
        number = int(match[1]) if match[1] else int(local[1]) if local else None
        if number in displayed:
            return number
    return None


def related_issue_body(context, repo, number):
    """One controller-constructed body GET, not a recursive issue/PR crawl."""
    repo = context._public(repo)
    if type(number) is not int or not 1 <= number <= 1_000_000_000:
        raise ValueError('invalid related issue number')
    url = f'https://github.com/{repo}/issues/{number}'
    item = context._json(f'https://api.github.com/repos/{repo}/issues/{number}')
    if (not isinstance(item, dict) or type(item.get('number')) is not int
            or item['number'] != number or 'pull_request' in item
            or item.get('html_url') != url
            or not all(isinstance(item.get(key), str) for key in ('title', 'body'))):
        raise ValueError('related issue response identity mismatch')
    source = issue_evidence(url, item['title'], item['body'])
    source['related_issue_expansion'] = dict(
        number=number, candidate_focus_adopted=False,
        scope='One bounded current body, possibly head-tail clipped; no comments, timeline, recursive links, fix/merge verdict or publication authority.')
    return source


def cited_issue_number(repo, sources, analysis):
    """Return one displayed, exactly quoted related-work target.

    An explicit next-check target disambiguates verified citations; without one,
    multiple issues abstain. The requested issue must itself be exactly quoted.
    Inspect at most five citations and 25 bounded source excerpts. Malformed,
    cross-repository, comment-only and invented references abstain.
    A comment additionally requires its canonical parent issue to be displayed.
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
        r"(https://github\.com/" + re.escape(repo)
        + r"/issues/([1-9][0-9]{0,9}))(?:#issuecomment-([1-9][0-9]{0,18}))?"
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
            and int(match[2]) <= 1_000_000_000
            and (
                match[3] is None
                or (int(match[3]) <= 10**18 and match[1] in displayed)
            )
            and 20 <= len(quote.strip()) <= 600
            and any(quote in text for text in displayed.get(url, []))
        ):
            numbers.add(int(match[2]))
    requested = requested_issue_number(repo, sources, analysis)
    if requested is not None:
        return requested if requested in numbers else None
    return numbers.pop() if len(numbers) == 1 else None
