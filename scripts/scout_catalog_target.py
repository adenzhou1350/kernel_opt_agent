"""Zero-model file targeting for bounded, declared evidence-acquisition trials.

Select only a unique explicitly mentioned catalog file, not an invented path.
This is a text rule, not binding, reachability, quality or execution authority.
It does not fetch source or change the live Scout router.
"""

import re
from urllib.parse import urlsplit

try:
    from .scout_evidence_acquisition import pinned_raw_url
except ImportError:
    from scout_evidence_acquisition import pinned_raw_url


def mentioned_catalog_target(view):
    """Return a same-repository pinned target, or an explicit abstention.

    Only next_check_unverified supplies mentions. Exact full paths outrank bare
    filenames; competing files or revisions at the best level abstain. Repeated
    snippets of the same URL are one target. The returned start line is 1,
    deliberately not a guess about where a relevant definition lives.
    """
    if not isinstance(view, dict):
        raise ValueError("view must be an object")
    request = view.get("next_check_unverified")
    sources = view.get("sources")
    repo = view.get("repo")
    if (
        not isinstance(request, str)
        or len(request) > 2000
        or not isinstance(sources, list)
        or len(sources) > 24
        or not isinstance(repo, str)
        or re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo) is None
    ):
        raise ValueError("invalid bounded catalog view")

    matches = {}
    for source in sources:
        if not isinstance(source, dict):
            continue
        url = source.get("url")
        if not pinned_raw_url(url):
            continue
        owner, repository, _commit, path = urlsplit(url).path.lstrip("/").split("/", 3)
        if f"{owner}/{repository}" != repo:
            continue

        # ASCII path boundaries also permit Chinese prose around a filename.
        def mentioned(name):
            return (
                re.search(
                    r"(?<![A-Za-z0-9_./-])" + re.escape(name) + r"(?![A-Za-z0-9_./-])",
                    request,
                )
                is not None
            )

        if "/" in path and mentioned(path):
            matches[url] = 2
        elif mentioned(path.rsplit("/", 1)[-1]):
            matches[url] = 1

    if not matches:
        return {"status": "ABSTAIN", "reason": "NO_EXPLICIT_CATALOG_FILE"}
    best = max(matches.values())
    winners = [url for url, score in matches.items() if score == best]
    if len(winners) != 1:
        return {
            "status": "ABSTAIN",
            "reason": "AMBIGUOUS_CATALOG_FILE",
            "matching_targets": len(winners),
        }
    return {
        "status": "SELECTED",
        "url": winners[0],
        "start_line": 1,
        "reason": "EXPLICIT_FULL_PATH" if best == 2 else "UNIQUE_FILENAME",
    }
