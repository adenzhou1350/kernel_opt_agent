"""Bounded, advisory reuse of curated lessons; never a qualification verdict."""

import json
import re
from itertools import islice
from urllib.parse import urlsplit

import knowledge_notes

MAX_QUERY_CHARS = 1024
MAX_CARD_BYTES = 8192
MAX_SOURCE_CHARS = 24000
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


def source_api_query(source_text):
    """Bounded imported-namespace hints, not parsing or behavior evidence.

    Preserve the existing runtime's source_text lookup. Comments/strings may
    match; these anchors never authorize execution or establish applicability.
    No additional source is fetched and unqualified row.name fields add nothing.
    """
    source = str(source_text)[:MAX_SOURCE_CHARS]
    aliases = set()
    for module, alias in re.findall(
        r"(?m)^\s*(?:\d+:\s*)?import\s+([A-Za-z_][\w.]*)(?:\s+as\s+(\w+))?", source
    ):
        aliases.add(alias or module.split(".")[0])
    for imported in re.findall(
        r"(?m)^\s*(?:\d+:\s*)?from\s+[\w.]+\s+import\s+([^\n#]+)", source
    ):
        for name in imported.split(","):
            match = re.fullmatch(r"\s*(\w+)(?:\s+as\s+(\w+))?\s*", name)
            if match:
                aliases.add(match.group(2) or match.group(1))
    aliases.update(re.findall(r"\bimport\s+\*\s+as\s+(\w+)\s+from\b", source))
    assignment = (
        r"(?m)^\s*(?:\d+:\s*)?(?:(?:const|let|var)\s+)?"
        r"([A-Za-z_]\w*)\s*=\s*(?:await\s+)?"
    )
    module = r"[@A-Za-z0-9_./-]+"
    js_imports = [
        (alias, package)
        for alias, _, package in re.findall(
            assignment + r"import\s*\(\s*(['\"])(" + module
            + r")\2\s*\)\s*(?:;|$)", source
        )
    ]
    js_imports.extend(
        (alias, double_quoted or single_quoted)
        for alias, double_quoted, single_quoted in re.findall(
            assignment + r"eval\s*\(\s*(?:'import\(\"(" + module
            + r")\"\)'|\"import\('(" + module + r")'\)\")\s*\)\s*(?:;|$)", source
        )
    )
    js_namespaces = {
        alias: package.rsplit("/", 1)[-1] for alias, package in js_imports
    }
    aliases.update(js_namespaces)
    go_imports = re.findall(
        r'(?m)^\s*(?:\d+:\s*)?import\s+(?:(\w+|\.)\s+)?"([\w./-]+)"', source
    )
    for block in re.findall(
        r"(?ms)^\s*(?:\d+:\s*)?import\s*\((.*?)^\s*(?:\d+:\s*)?\)", source
    ):
        go_imports.extend(re.findall(
            r'(?m)^\s*(?:\d+:\s*)?(?:(\w+|\.)\s+)?"([\w./-]+)"', block
        ))
    go_namespaces = {
        alias or module.rsplit("/", 1)[-1]: module.rsplit("/", 1)[-1]
        for alias, module in go_imports if alias not in ("_", ".")
    }
    aliases.update(go_namespaces)
    namespaces = {**go_namespaces, **js_namespaces}
    names = re.findall(r"\b[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+", source)
    terms = sorted({
        term.casefold()
        for name in names if name.split(".")[0] in aliases
        for term in name.split(".") if len(term) > 1
    } | {
        namespaces[name.split(".")[0]].casefold()
        for name in names if name.split(".")[0] in namespaces
        and re.fullmatch(r"[A-Za-z_]\w*", namespaces[name.split(".")[0]])
    })
    selected, size = [], 0
    for term in terms:
        if size + len(term) + 1 > MAX_QUERY_CHARS:
            break
        selected.append(term)
        size += len(term) + 1
    return " ".join(selected)


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


def lesson_suggestions(query, *, source_text="", source_urls=(), exclude=(), directory=None):
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
        "source_query_used": False,
    }
    if not text:
        return result
    excluded = set(exclude)
    try:
        path_matches = source_path_matches(
            source_urls, directory or knowledge_notes.DEFAULT_DIRECTORY,
            query=text[:MAX_QUERY_CHARS],
        )
        found = knowledge_notes.search(
            text[:MAX_QUERY_CHARS],
            directory=directory or knowledge_notes.DEFAULT_DIRECTORY,
            limit=16,
        )
        api_terms = set(source_api_query(source_text).split())
        source_matches = []
        if len(api_terms) >= 2:
            source_found = knowledge_notes.search(
                " ".join(sorted(api_terms)),
                directory=directory or knowledge_notes.DEFAULT_DIRECTORY, limit=16,
            )
            source_matches = [
                match for match in source_found["matches"]
                if len(api_terms & set(knowledge_notes.normalized(
                    match["card"]["title"]).split())) >= 2
            ]
    except (OSError, ValueError):
        result["status"] = "LIBRARY_UNAVAILABLE"
        return result
    for from_path, from_source, match in (
        [(True, False, match) for match in path_matches]
        + [(False, True, match) for match in source_matches]
        + [(False, False, match) for match in found["matches"]]
    ):
        card = match["card"]
        if card["id"] in excluded:
            continue
        if len(json.dumps(card, ensure_ascii=False).encode()) > MAX_CARD_BYTES:
            result["oversized_matches_omitted"] += 1
            continue
        result["matches"] = [card]
        result["status"] = "ADVISORY_MATCH"
        result["source_query_used"] = from_source
        if from_path:
            result["source_path_match"] = True
        break
    return result
