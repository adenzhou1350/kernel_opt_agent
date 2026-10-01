"""Optional bounded public Discussion evidence, never a novelty verdict."""

import json
import re
import time
import urllib.request

import kimi_scout as scout
from kimi_scout_context import API_LIMIT, SNAPSHOT_TTL, _repo

QUERY = """query($q:String!) {
  search(query:$q,type:DISCUSSION,first:3) {
    nodes { ... on Discussion {
      number title body url repository { nameWithOwner isPrivate }
      comments(first:3) { nodes { body url } pageInfo { hasNextPage } }
    } }
  }
}"""


def _query(context, text):
    request = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": QUERY, "variables": {"q": text}}).encode(),
        headers={
            "Authorization": scout.github_auth_header(),
            "Content-Type": "application/json",
        },
    )
    with urllib.request.build_opener(scout.NoRedirect()).open(
        request, timeout=20
    ) as response:
        raw = response.read(API_LIMIT + 1)
    if len(raw) > API_LIMIT:
        raise ValueError("discussion response exceeds read budget")
    value = json.loads(raw)
    if not isinstance(value, dict) or value.get("errors"):
        raise ValueError("discussion search unavailable")
    data = value.get("data")
    search = data.get("search") if isinstance(data, dict) else None
    if not isinstance(search, dict) or not isinstance(search.get("nodes"), list):
        raise TypeError("invalid discussion response")
    return search["nodes"][:3]


def discussion_sources(context, repo, title):
    """One scoped query, <=3 reports with <=3 comments, 15-minute cache.

    No anonymous token fallback, model-created fetch target, source execution,
    automatic rejection or claim that empty search excludes existing work.
    """
    repo = _repo(repo)
    if not isinstance(title, str):
        raise TypeError("discussion query title must be text")
    words = list(dict.fromkeys(re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", title[:1000])))
    if not words:
        return []
    anchor = next(
        (
            word
            for word in words
            if "_" in word.strip("_")
            or re.search(r"[a-z][A-Z]|[A-Z]{2}[a-z]|[A-Za-z][0-9]", word)
        ),
        None,
    )
    terms = " ".join(
        '"' + word[:32] + '"' for word in ([anchor] if anchor else words[:2])
    )
    query_text = f"repo:{repo} {terms}"
    context._public(repo)  # Access credentials never establish public visibility.
    if not context.github_auth:
        raise ValueError("discussion search requires configured GitHub auth")
    path = context._cache_path("discussion", [repo, query_text])
    cached = context._load(path)
    if (
        cached
        and type(cached.get("at")) in (int, float)
        and 0 <= time.time() - cached["at"] < SNAPSHOT_TTL
    ):
        rows = cached.get("nodes")
    else:
        rows = _query(context, query_text)
        scout.write_json(path, {"at": time.time(), "nodes": rows})
    if not isinstance(rows, list):
        raise TypeError("invalid cached discussions")
    result = []
    for row in rows[:3]:
        if not isinstance(row, dict):
            continue
        owner = row.get("repository", {})
        number = row.get("number")
        if (
            not isinstance(owner, dict)
            or owner.get("isPrivate") is not False
            or str(owner.get("nameWithOwner", "")).casefold() != repo.casefold()
            or type(number) is not int
            or not 1 <= number <= 1_000_000_000
        ):
            continue
        url = f"https://github.com/{repo}/discussions/{number}"
        if row.get("url") != url or not all(
            isinstance(row.get(k), str) for k in ("title", "body")
        ):
            continue
        comments = row.get("comments", {})
        nodes = comments.get("nodes", []) if isinstance(comments, dict) else []
        comments_clipped = not isinstance(nodes, list) or len(nodes) > 3
        text = row["title"][:200] + "\n" + row["body"][:3500]
        for comment in nodes[:3] if isinstance(nodes, list) else []:
            if (
                isinstance(comment, dict)
                and isinstance(comment.get("body"), str)
                and isinstance(comment.get("url"), str)
                and re.fullmatch(
                    re.escape(url) + r"#discussioncomment-[1-9][0-9]*", comment["url"]
                )
            ):
                text += "\n" + comment["url"] + "\n" + comment["body"][:600]
                comments_clipped |= len(comment["body"]) > 600
            else:
                comments_clipped = True
        evidence = scout.evidence(url, text, 5500)
        page = comments.get("pageInfo") if isinstance(comments, dict) else None
        evidence.update(
            is_discussion=True,
            search_exhaustive=False,
            search_query=query_text,
            truncated=evidence["truncated"]
            or len(row["body"]) > 3500
            or len(row["title"]) > 200
            or comments_clipped,
            comments_truncated=comments_clipped or page.get("hasNextPage") is not False
            if isinstance(page, dict)
            else True,
        )
        result.append(evidence)
    return result
