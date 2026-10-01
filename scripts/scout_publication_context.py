"""Bounded local publication memory, not a duplicate or readiness verdict."""

import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from urllib.parse import urlsplit

CAUTION = (
    "Owner-recorded PR links only; not an exhaustive duplicate search or current "
    "CI/review/merge state. Prior hypotheses are untrusted summaries, not PR titles. "
    "Inspect the actual PR before judging coverage. A same-file match does not "
    "disprove a distinct bug. Never reject or publish from this memory alone."
)
PR_URL = re.compile(
    r"https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/pull/[1-9][0-9]*"
)


def source_paths(sources, repo):
    paths = set()
    for source in sources if isinstance(sources, list) else []:
        if not isinstance(source, dict) or not isinstance(source.get("url"), str):
            continue
        try:
            url = urlsplit(source["url"])
        except ValueError:
            continue
        parts = url.path.strip("/").split("/", 3)
        if (
            url.scheme == "https"
            and url.netloc == "raw.githubusercontent.com"
            and len(parts) == 4
            and "/".join(parts[:2]).casefold() == repo.casefold()
            and re.fullmatch(r"[0-9a-f]{40}", parts[2])
            and 0 < len(parts[3]) <= 256
        ):
            paths.add(parts[3])
    return paths


def publication_context(root, repo, sources):
    """Read at most 24 terminal rows; never create a DB or rewrite worker state."""
    path = Path(root).resolve() / "delivery" / "delivery.sqlite"
    if not path.is_file():
        return None
    wanted = source_paths(sources, repo)
    try:
        with closing(
            sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=0.05)
        ) as db:
            rows = db.execute(
                "SELECT substr(title,1,201),substr(result,1,131073),substr(payload,1,131073) "
                "FROM delivery WHERE repo=? AND state='PR_OPEN' "
                "ORDER BY updated_at DESC,id LIMIT 24",
                (repo,),
            ).fetchall()
    except (OSError, sqlite3.Error):
        return None
    matches, seen = [], set()
    for title, result, payload in rows:
        if not isinstance(title, str) or not all(
            isinstance(x, str) and len(x) <= 131072 for x in (result, payload)
        ):
            continue
        try:
            record = json.loads(result)
            packet = json.loads(payload)
            url = record.get("pr", {}).get("url", "")
            match = PR_URL.fullmatch(url) if isinstance(url, str) else None
            paths = source_paths(packet.get("packet", {}).get("sources", []), repo)
        except (ValueError, AttributeError, TypeError):
            continue
        if (
            not match
            or match[1].casefold() != repo.casefold()
            or url.casefold() in seen
        ):
            continue
        seen.add(url.casefold())
        matches.append(
            (
                bool(paths & wanted),
                {
                    "url": url,
                    "prior_hypothesis": title[:200],
                    "source_paths": sorted(paths)[:2],
                },
            )
        )
    if not matches:
        return None
    matches.sort(
        key=lambda item: not item[0]
    )  # Same-file hints first; preserve recency within ties.
    return {"caution": CAUTION, "items": [item for _, item in matches[:3]]}


def fit_publication_context(packet, limit, prefix=""):
    """Optional memory must not force clipping of primary source evidence."""
    if (
        len((prefix + json.dumps(packet, ensure_ascii=False, sort_keys=True)).encode())
        > limit
    ):
        packet.pop("owner_publications", None)
