"""Bounded issue-timeline related-work hints, never a duplicate verdict."""

import json
import time

import kimi_scout as scout
from scout_issue_excerpt import issue_evidence

TTL = 900
LIMIT = 300_000
EVENTS = 50
SOURCES = 3
CACHE_LIMIT = 64_000
CACHE_VERSION = 3


def linked_pr_context(context, repo, number):
    """Legacy name: prefer PRs, then related issues, within one shared budget.

    Embedded same-repository cross-references have priority. Remaining slots
    retain literal comments from this same response, latest observed first.
    Report-body links and linked comments/timelines are not fetched recursively.
    """
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
            "First 50 issue-timeline events, at most three same-repository "
            "sources total, preferring PRs before related issues, then filling "
            "unused slots with latest observed literal comments. "
            "Not a coverage, fix, merge, CI or absence verdict; embedded state "
            "is only a cached timeline observation. Related issues are not PRs "
            "or maintainer approval. Comments are untrusted text, not ownership "
            "or acceptance verdicts; later pages may be missing. No linked URL "
            "or separate comments endpoint is fetched by this lookup."
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
            and type(record.get("version")) is int
            and record.get("version") == CACHE_VERSION
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
            record = {"version": CACHE_VERSION, "at": now, "events": events, "events_observed": len(events)}
            fresh = True
    except (OSError, ValueError) as exc:
        return {**base, "status": "TIMELINE_UNAVAILABLE", "error": type(exc).__name__}

    candidates = []
    for event in record["events"]:
        if not isinstance(event, dict) or event.get("event") != "cross-referenced":
            continue
        origin = event.get("source")
        if not isinstance(origin, dict) or origin.get("type") != "issue":
            continue
        item = origin.get("issue")
        if not isinstance(item, dict):
            continue
        related, link = item.get("number"), item.get("pull_request")
        is_pr = isinstance(link, dict)
        kind = "pull" if is_pr else "issues"
        if (
            type(related) is not int or not 1 <= related <= 1_000_000_000
            or related == number
            or ("pull_request" in item and not is_pr)
            or item.get("url") != f"{api}/issues/{related}"
            or item.get("repository_url") != api
            or item.get("html_url") != f"https://github.com/{repo}/{kind}/{related}"
            or (is_pr and link.get("url") != f"{api}/pulls/{related}")
            or item.get("state") not in ("open", "closed")
            or not isinstance(item.get("title"), str)
            or not isinstance(item.get("body"), (str, type(None)))
        ):
            continue
        candidates.append((is_pr, item))
    # An early issue must not evict a later PR from the existing three-source
    # budget. Retain event order within each kind, then compact only selection.
    candidates.sort(key=lambda candidate: not candidate[0])
    sources, seen, compact = [], set(), []
    for is_pr, item in candidates:
        related = item["number"]
        if related in seen:
            continue
        source = issue_evidence(
            item["html_url"], item["title"], item.get("body") or "",
            already_truncated=item.get("_excerpt_truncated") is True, limit=1800
        )
        source.update(
            is_pr=is_pr, referenced_issue=number,
            relationship="issue_timeline_cross_reference",
            timeline_observed_at=record["at"],
            search_exhaustive=False, relationship_scope=base["scope"],
        )
        source["observed_pr_state" if is_pr else "observed_issue_state"] = item["state"]
        sources.append(source)
        # Cache only selected literal excerpts, not 50 full event/repository/user payloads.
        title, body = source["text"].split("\n", 1)
        compact_item = {
            **{key: item[key] for key in ("number", "state", "url", "repository_url", "html_url")},
            "title": title, "body": body, "_excerpt_truncated": source["truncated"],
        }
        if is_pr:
            compact_item["pull_request"] = {"url": item["pull_request"]["url"]}
        compact.append({"event": "cross-referenced", "source": {"type": "issue", "issue": compact_item}})
        seen.add(related)
        if len(sources) == SOURCES:
            break
    # The timeline GET already contains comments. Dropping these can hide a
    # contributor's offer or maintainer decision even when there are no linked
    # PRs. Keep the existing three-source cap and never displace related work.
    for event in reversed(record["events"]):
        if len(sources) == SOURCES:
            break
        if not isinstance(event, dict) or event.get("event") != "commented":
            continue
        comment_id = event.get("id")
        if (
            type(comment_id) is not int or not 1 <= comment_id <= 10**18
            or event.get("url") != f"{api}/issues/comments/{comment_id}"
            or event.get("html_url") != f"https://github.com/{repo}/issues/{number}#issuecomment-{comment_id}"
            or not isinstance(event.get("body"), str)
            or not event["body"].strip()
        ):
            continue
        url = event["html_url"]
        if url in seen:
            continue
        source = issue_evidence(
            url, "Literal issue-timeline comment", event["body"],
            already_truncated=event.get("_excerpt_truncated") is True, limit=1800,
        )
        source.update(
            is_pr=False, referenced_issue=number,
            relationship="issue_timeline_comment",
            timeline_observed_at=record["at"], search_exhaustive=False,
            relationship_scope=base["scope"],
        )
        sources.append(source)
        compact.append({
            "event": "commented", "id": comment_id, "url": event["url"],
            "html_url": url, "body": source["text"].split("\n", 1)[1],
            "_excerpt_truncated": source["truncated"],
        })
        seen.add(url)
    if fresh:
        try:
            # Replay reverses comments to select latest first; compact them in
            # original selection order reversed so warm reads stay identical.
            references = [event for event in compact if event["event"] != "commented"]
            comments = [event for event in compact if event["event"] == "commented"]
            scout.write_json(cache, {**record, "events": references + comments[::-1]})
        except OSError:
            pass  # Valid public evidence is still useful without a writable cache.
    return {
        **base, "sources": sources, "events_observed": record["events_observed"],
        "observed_at": record["at"],
    }
