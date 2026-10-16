"""Bounded, advisory reuse of curated lessons; never a qualification verdict."""

import json
import re
from itertools import islice
from urllib.parse import urlsplit

import knowledge_notes

MAX_QUERY_CHARS = 1024
MAX_CARD_BYTES = 8192
MAX_SOURCE_URLS = 16


def source_file_identity(value):
    """Recognize immutable public GitHub file links without fetching them."""
    if not isinstance(value, str) or len(value) > 2048:
        return None
    try:
        url = urlsplit(value)
        if url.scheme != "https" or url.query:
            return None
        parts = url.path.split("/")[1:]
        if url.netloc == "github.com" and len(parts) >= 5 and parts[2] == "blob":
            owner, repo, _, revision, *path = parts
        elif url.netloc == "raw.githubusercontent.com" and len(parts) >= 4:
            owner, repo, revision, *path = parts
        else:
            return None
        if not all(re.fullmatch(r"[A-Za-z0-9_.-]+", name) for name in (owner, repo)):
            return None
        if not re.fullmatch(r"[A-Fa-f0-9]{40}", revision):
            return None
        if any(not part or part in (".", "..") or "\\" in part for part in path):
            return None
        return owner.casefold(), repo.casefold(), "/".join(path), revision.casefold()
    except ValueError:
        return None


def source_path_matches(source_urls, directory, query=""):
    """Same repository and full path, not basename/fork or behavior equivalence.

    An older revision is still useful advice; current source must be checked.
    Duplicate source windows do not increase its rank. No extra network reads.
    """
    if isinstance(source_urls, str):
        return []
    identities = {
        identity for url in islice(source_urls, MAX_SOURCE_URLS)
        if (identity := source_file_identity(url)) is not None
    }
    if not identities:
        return []
    paths = {identity[:3] for identity in identities}
    matches = []
    for _, card in knowledge_notes.read_cards(directory):
        evidence = {
            identity for item in card["evidence"]
            if (identity := source_file_identity(item["url"])) is not None
        }
        overlap = paths & {identity[:3] for identity in evidence}
        if overlap:
            matches.append((len(identities & evidence), len(overlap),
                            knowledge_notes.query_score(query, card), card))
    # Several distinct lessons can cite the same large implementation file.
    # Do not let filename alphabetization hide a relevant policy lesson. Exact
    # revision/path affinity still wins; query overlap only breaks equal ties.
    matches.sort(key=lambda item: (-item[0], -item[1], -item[2], item[3]["id"]))
    return [{"card": item[3]} for item in matches]


def fit_lesson_context(packet, limit, prefix=""):
    """Optional advice must never displace supplied primary source evidence."""
    suggestion = packet.get("lesson_suggestions", {})
    if suggestion.get("status") == "NO_MATCH":
        packet.pop("lesson_suggestions", None)
        return
    size = len(
        (prefix + json.dumps(packet, ensure_ascii=False, sort_keys=True)).encode()
    )
    if size > limit:
        packet.pop("lesson_suggestions", None)


def lesson_suggestions(query, *, source_urls=(), exclude=(), directory=None):
    """Add at most one intact related card, without copying private source paths.

    No card is an unconditional baseline. Match scores are lexical suggestions,
    not applicability, confidence or policy. Optional
    library errors must not stop discovery or turn into a defect verdict.
    """
    text = str(query).strip()
    result = {
        "matches": [],
        "caution": knowledge_notes.CAUTION,
        "query_truncated": len(text) > MAX_QUERY_CHARS,
        "oversized_matches_omitted": 0,
        "status": "NO_MATCH",
    }
    if not text:
        return result
    excluded = set(exclude)
    try:
        source_matches = source_path_matches(
            source_urls, directory or knowledge_notes.DEFAULT_DIRECTORY,
            query=text[:MAX_QUERY_CHARS],
        )
        found = knowledge_notes.search(
            text[:MAX_QUERY_CHARS],
            directory=directory or knowledge_notes.DEFAULT_DIRECTORY,
            limit=16,
        )
    except (OSError, ValueError):
        result["status"] = "LIBRARY_UNAVAILABLE"
        return result
    for from_source, match in (
        [(True, match) for match in source_matches]
        + [(False, match) for match in found["matches"]]
    ):
        card = match["card"]
        if card["id"] in excluded:
            continue
        if len(json.dumps(card, ensure_ascii=False).encode()) > MAX_CARD_BYTES:
            result["oversized_matches_omitted"] += 1
            continue
        result["matches"] = [card]
        result["status"] = "ADVISORY_MATCH"
        if from_source:
            result["source_path_match"] = True
        break
    return result
