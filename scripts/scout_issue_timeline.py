"""Bounded issue-timeline PR hints, never an automatic duplicate verdict."""

import json
import time

import kimi_scout as scout
from scout_issue_excerpt import issue_evidence

TTL = 900
LIMIT = 300_000
EVENTS = 50
SOURCES = 3
CACHE_LIMIT = 64_000


def linked_pr_context(context, repo, number):
    """One cached page for an observed public issue; no linked URL is fetched."""
    scout.public_repo(repo)
    if type(number) is not int or not 1 <= number <= 1_000_000_000:
        raise ValueError("invalid issue number")
    context._public(repo)
    api = f"https://api.github.com/repos/{repo}"
    endpoint = f"{api}/issues/{number}/timeline?per_page={EVENTS}&page=1"
    cache = context._cache_path("issue-linked-pr", [repo, number])
    base = {
        "sources": [],
        "status": "PARTIAL_TIMELINE",
        "search_exhaustive": False,
        "endpoint": endpoint,
        "scope": (
            "First 50 issue-timeline events, at most three same-repository PR "
            "cross-references. Not a coverage, fix, merge, CI or absence verdict; "
            "embedded PR state is only a cached timeline observation."
        ),
    }
    try:
        try:
            with cache.open("rb") as stream:
                raw = stream.read(CACHE_LIMIT + 1)
            record = json.loads(raw) if len(raw) <= CACHE_LIMIT else None
        except (OSError, ValueError):
            record = None
        now = time.time()
        fresh = False
        if not (
            isinstance(record, dict)
            and type(record.get("at")) in (int, float)
            and 0 <= now - record["at"] < TTL
            and isinstance(record.get("events"), list)
            and len(record["events"]) <= SOURCES
            and type(record.get("events_observed")) is int
            and 0 <= record["events_observed"] <= EVENTS
        ):
            events = context._json(endpoint, limit=LIMIT)
            if not isinstance(events, list) or len(events) > EVENTS:
                raise ValueError("invalid issue timeline")
            record = {"at": now, "events": events, "events_observed": len(events)}
            fresh = True
    except (OSError, ValueError) as exc:
        return {**base, "status": "TIMELINE_UNAVAILABLE", "error": type(exc).__name__}

    sources, seen, compact = [], set(), []
    for event in record["events"]:
        if not isinstance(event, dict) or event.get("event") != "cross-referenced":
            continue
        origin = event.get("source")
        if not isinstance(origin, dict) or origin.get("type") != "issue":
            continue
        item = origin.get("issue")
        if not isinstance(item, dict):
            continue
        pr, link = item.get("number"), item.get("pull_request")
        if (
            type(pr) is not int or not 1 <= pr <= 1_000_000_000
            or pr in seen
            or not isinstance(link, dict)
            or item.get("url") != f"{api}/issues/{pr}"
            or item.get("repository_url") != api
            or item.get("html_url") != f"https://github.com/{repo}/pull/{pr}"
            or link.get("url") != f"{api}/pulls/{pr}"
            or item.get("state") not in ("open", "closed")
            or not isinstance(item.get("title"), str)
            or not isinstance(item.get("body"), (str, type(None)))
        ):
            continue
        source = issue_evidence(
            item["html_url"], item["title"], item.get("body") or "",
            already_truncated=item.get("_excerpt_truncated") is True, limit=1800
        )
        source.update(
            is_pr=True, referenced_issue=number,
            relationship="issue_timeline_cross_reference",
            observed_pr_state=item["state"], timeline_observed_at=record["at"],
            search_exhaustive=False, relationship_scope=base["scope"],
        )
        sources.append(source)
        # Cache only selected literal excerpts, not 50 full event/repository/user payloads.
        title, body = source["text"].split("\n", 1)
        compact.append({"event": "cross-referenced", "source": {"type": "issue", "issue": {
            **{key: item[key] for key in ("number", "state", "url", "repository_url", "html_url")},
            "pull_request": {"url": link["url"]},
            "title": title, "body": body, "_excerpt_truncated": source["truncated"],
        }}})
        seen.add(pr)
        if len(sources) == SOURCES:
            break
    if fresh:
        try:
            scout.write_json(cache, {**record, "events": compact})
        except OSError:
            pass  # Valid public evidence is still useful without a writable cache.
    return {
        **base, "sources": sources, "events_observed": record["events_observed"],
        "observed_at": record["at"],
    }
