"""Bounded choices for declared acquisition trials, never live quality routing.

Unavailable catalogs, abstention and invalid selections are not fetch failures.
Keep all of them in a trial's denominator, without a replacement target or case.
"""

import re
from urllib.parse import urlsplit

try:
    from .scout_evidence_acquisition import pinned_raw_url
except ImportError:
    from scout_evidence_acquisition import pinned_raw_url


def acquisition_catalog(view):
    """Eligible same-repository immutable URLs in original catalog order."""
    if not isinstance(view, dict):
        raise ValueError("expected a bounded catalog view")
    repo, sources = view.get("repo"), view.get("sources")
    if (not isinstance(repo, str)
            or re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo) is None
            or not isinstance(sources, list) or len(sources) > 24):
        raise ValueError("expected a bounded catalog view")
    targets = {}
    for source in sources:
        if not isinstance(source, dict):
            raise ValueError("invalid catalog source")
        url = source.get("url")
        if not pinned_raw_url(url):
            continue
        owner, repository, _commit, _path = urlsplit(url).path.lstrip("/").split("/", 3)
        if f"{owner}/{repository}" != repo:
            continue
        end = source.get("end_line")
        if end is not None and (type(end) is not int or end < 1):
            raise ValueError("invalid source end line")
        targets.setdefault(url, {"url": url, "start_line": end + 1 if end else 1})
    return list(targets.values())


def first_catalog_continuation(view):
    """A zero-model baseline; EOF is an observation, not permission to retry."""
    catalog = acquisition_catalog(view)
    if not catalog:
        return {"status": "UNAVAILABLE", "reason": "NO_ELIGIBLE_SOURCE"}
    return {"status": "SELECTED", **catalog[0]}


def first_clipped_or_continuation(view):
    """Restore the first clipped catalog file, otherwise continue the first file.

    Original snippet end_line is not the last line delivered after view clipping.
    Read from its original start (or 1 when absent), using the caller's unchanged
    one-window budget. Catalog-only clipped entries qualify; duplicate URLs use
    their first entry, just like acquisition_catalog. This does not infer where
    relevant evidence lies or promise to recover the whole omitted snippet.
    A separate policy for fresh trials, not a repair/rescore of old answers.
    """
    catalog = acquisition_catalog(view)
    eligible = {target["url"] for target in catalog}
    seen = set()
    for source in view["sources"]:
        url = source.get("url")
        if not isinstance(url, str) or url not in eligible or url in seen:
            continue
        seen.add(url)
        clipped = source.get("clipped", False)
        if type(clipped) is not bool:
            raise ValueError("invalid source clipping flag")
        if not clipped:
            continue
        start = source.get("start_line")
        if start is not None and (type(start) is not int or start < 1):
            raise ValueError("invalid source start line")
        end = source.get("end_line")
        if start is not None and end is not None and start > end:
            raise ValueError("invalid source line range")
        return {"status": "SELECTED", "url": url, "start_line": start or 1}
    return first_catalog_continuation(view)


def validate_selection(view, selection):
    """Validate the existing acquisition-only JSON interface without repairing it."""
    catalog = acquisition_catalog(view)
    if not catalog:
        return {"status": "UNAVAILABLE", "reason": "NO_ELIGIBLE_SOURCE"}
    if (not isinstance(selection, dict)
            or set(selection) != {"url", "start_line", "reason"}
            or not isinstance(selection["reason"], str)
            or len(selection["reason"]) > 600):
        return {"status": "INVALID_SELECTION", "reason": "INVALID_INTERFACE"}
    url, start = selection["url"], selection["start_line"]
    if url is None and start is None:
        return {"status": "ABSTAIN", "reason": selection["reason"]}
    if (not isinstance(url, str) or url not in {entry["url"] for entry in catalog}
            or type(start) is not int or start < 1):
        return {"status": "INVALID_SELECTION", "reason": "INVALID_TARGET"}
    return {"status": "SELECTED", "url": url, "start_line": start}


def observe_choice(view, choice, session, *, max_lines=80, max_chars=4500):
    """Pass only a valid selected window to the consumer; preserve both verdicts.

    The session retains physical/logical costs, including failed reads. Programming
    errors and exhausted session budgets still raise; they are not empty catalogs.
    No model calls, retries, replacement targets, code execution or file writes.
    """
    status = choice.get("status") if isinstance(choice, dict) else None
    if status in {"UNAVAILABLE", "ABSTAIN", "INVALID_SELECTION", "NO_ADDITIONAL_SOURCE"}:
        return {"status": status, "acquisition": None, "window": None}
    if status != "SELECTED":
        raise ValueError("invalid acquisition choice")
    checked = validate_selection(view, dict(url=choice.get("url"),
        start_line=choice.get("start_line"), reason="Validate before GET"))
    if checked["status"] != "SELECTED":
        raise ValueError("selected target is not eligible in this catalog")
    result = session.acquire_window(checked["url"], start_line=checked["start_line"],
                                    max_lines=max_lines, max_chars=max_chars)
    status = "ACQUIRED" if (result["acquisition"]["status"] == "FETCHED"
        and result["window"]["status"] == "ACQUIRED") else "FAILED"
    return {"status": status, **result}
