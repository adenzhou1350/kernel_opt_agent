"""Read-only, bounded GitHub check observations; never a Ready/merge decision.

`fetch(path)` is the caller's JSON GET transport. Authentication stays there.
Check runs are not commit statuses, required-check policy or proof that a
workflow was allowed to start. Pages are live observations, not an atomic snapshot.
"""

import re


def _validate_repository(repository):
    if (not isinstance(repository, str)
            or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository)
            or any(part in {".", ".."} for part in repository.split("/"))):
        raise ValueError("repository must be owner/name")


def observe_check_runs(fetch, repository, sha, *, per_page=100, max_pages=10):
    """Read every advertised page or explicitly report incomplete evidence."""
    _validate_repository(repository)
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("sha must be an exact lowercase commit SHA")
    if type(per_page) is not int or not 1 <= per_page <= 100:
        raise ValueError("per_page must be between 1 and 100")
    if type(max_pages) is not int or not 1 <= max_pages <= 100:
        raise ValueError("max_pages must be between 1 and 100")
    checks, seen, total, reason = [], set(), None, "page_limit"
    for page in range(1, max_pages + 1):
        value = fetch(f"repos/{repository}/commits/{sha}/check-runs"
                      f"?filter=latest&per_page={per_page}&page={page}")
        if not isinstance(value, dict):
            raise ValueError("check response must be an object")
        count, batch = value.get("total_count"), value.get("check_runs")
        if type(count) is not int or count < 0 or not isinstance(batch, list):
            raise ValueError("check response needs total_count and check_runs")
        if total is not None and total != count:
            reason = "total_count_changed"
            break
        total = count
        if len(batch) > per_page:
            reason = "oversized_page"
            break
        for check in batch:
            if not isinstance(check, dict) or type(check.get("id")) is not int:
                raise ValueError("check run must have an integer id")
            if check["id"] in seen:
                reason = "duplicate_check_id"
                break
            if check.get("head_sha") != sha:
                reason = "check_head_mismatch"
                break
            seen.add(check["id"])
            checks.append({key: check.get(key) for key in
                           ("id", "name", "status", "conclusion", "html_url")})
        else:
            if len(checks) == total:
                reason = None
                break
            if len(checks) > total:
                reason = "more_checks_than_reported"
                break
            if not batch:
                reason = "empty_page_before_total"
                break
            continue
        break

    pending, failed, unknown, skipped, success = [], [], [], [], []
    for check in checks:
        status, conclusion = check["status"], check["conclusion"]
        if status in {"queued", "in_progress", "requested", "waiting", "pending"}:
            (pending if conclusion is None else unknown).append(check)
        elif status != "completed":
            unknown.append(check)
        elif conclusion == "success":
            success.append(check)
        elif conclusion in {"skipped", "neutral"}:
            skipped.append(check)
        elif conclusion in {"failure", "cancelled", "timed_out", "action_required",
                            "startup_failure", "stale"}:
            failed.append(check)
        else:
            unknown.append(check)
    if reason:
        state = "INCOMPLETE"
    elif not checks:
        state = "NO_CHECKS"
    elif failed:
        state = "FAILED"
    elif unknown:
        state = "UNKNOWN"
    elif pending:
        state = "PENDING"
    elif skipped:
        state = "COMPLETED_WITH_SKIPS_OR_NEUTRAL"
    else:
        state = "ALL_OBSERVED_SUCCESS"
    return dict(repository=repository, sha=sha, state=state,
                complete=reason is None, incomplete_reason=reason, pages=page,
                reported_count=total, fetched_count=len(checks), checks=checks,
                pending=pending, failed=failed, unknown=unknown,
                success_count=len(success), skipped_or_neutral_count=len(skipped))


def observe_pull_request(fetch, repository, number, **limits):
    """Bind check observations to the PR head and recheck it after acquisition."""
    if type(number) is not int or number < 1:
        raise ValueError("pull request number must be a positive integer")
    # Validate the repository before passing a path to the caller's transport.
    _validate_repository(repository)
    path = f"repos/{repository}/pulls/{number}"
    sha = fetch(path)["head"]["sha"]
    result = observe_check_runs(fetch, repository, sha, **limits)
    result["pull_request"] = number
    result["head_unchanged"] = fetch(path)["head"]["sha"] == sha
    if not result["head_unchanged"]:
        result.update(state="INCOMPLETE", complete=False,
                      incomplete_reason="pull_request_head_changed")
    return result
