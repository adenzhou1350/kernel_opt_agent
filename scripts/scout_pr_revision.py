"""Read one requested, already displayed public PR at immutable revisions.

These are partial patch excerpts, never a duplicate/fix/test verdict. All request
URLs are controller constructed; model text only selects a displayed PR number.
"""

import re
import urllib.parse

SHA = re.compile(r"[0-9a-f]{40}")


def requested_pr_number(repo, sources, analysis):
    """Choose the first displayed PR explicitly named in bounded next_check.

    Do not infer requests from a title, hypothesis or duplicate-risk speculation.
    Multiple explicit requests use prose order, not search-result order; the caller
    reads only one. A foreign URL containing the same number is not a local #ref.
    """
    if not isinstance(repo, str) or not re.fullmatch(
        r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo
    ):
        return None
    if not isinstance(sources, list) or not isinstance(analysis, dict):
        return None
    request = analysis.get("next_check")
    if not isinstance(request, str):
        return None
    displayed = set()
    pattern = re.compile(
        r"https://github\.com/" + re.escape(repo) + r"/pull/([1-9][0-9]{0,9})"
    )
    for source in sources[:25]:
        if not isinstance(source, dict):
            continue
        url = source.get("url")
        match = pattern.fullmatch(url) if isinstance(url, str) else None
        if match and int(match[1]) <= 1_000_000_000:
            displayed.add(int(match[1]))
    # Match whole URLs first so a foreign URL or comment fragment cannot be
    # reinterpreted as a local number. No URL from this expression is fetched.
    for match in re.finditer(
        r"https?://[^\s<>\"']+|(?<![\w/#])#([1-9][0-9]{0,9})(?!\w)", request[:2000]
    ):
        if match[1]:
            number = int(match[1])
        else:
            local = pattern.fullmatch(match[0].rstrip(".,;:()"))
            number = int(local[1]) if local else None
        if number in displayed:
            return number
    return None


def _sha(value):
    if not isinstance(value, str) or not SHA.fullmatch(value):
        raise ValueError("invalid PR revision")
    return value


def _path(value):
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 1024
        or any(part in ("", ".", "..") for part in value.split("/"))
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
        or any(char in value for char in "\\:")
    ):
        raise ValueError("invalid PR file path")
    return value


def pr_revision_sources(context, repo, number, sources):
    """Two bounded reads plus public-visibility checks; no mutable files endpoint.

    Refresh the PR metadata every call. Compare BASE...HEAD at its observed SHAs,
    so a force push between requests cannot silently substitute different bytes.
    GitHub's compare API caps files at 300 and may omit/truncate patches. Select
    up to three files, prioritizing already displayed source paths, with 1,800
    characters per patch. Never interpret omission as absence or coverage.
    """
    repo = context._public(repo)
    if type(number) is not int or not 1 <= number <= 1_000_000_000:
        raise ValueError("invalid PR number")
    api = f"https://api.github.com/repos/{repo}"
    html = f"https://github.com/{repo}"
    pr = context._json(f"{api}/pulls/{number}", limit=300_000)
    if (
        not isinstance(pr, dict)
        or type(pr.get("number")) is not int
        or pr["number"] != number
        or pr.get("html_url") != f"{html}/pull/{number}"
    ):
        raise ValueError("invalid PR identity")
    base, head = pr.get("base"), pr.get("head")
    if not isinstance(base, dict) or not isinstance(head, dict):
        raise ValueError("missing PR revisions")
    base_repo, head_repo = base.get("repo"), head.get("repo")
    if (
        not isinstance(base_repo, dict)
        or base_repo.get("full_name") != repo
        or not isinstance(head_repo, dict)
        or head_repo.get("private") is not False
        or head_repo.get("visibility") != "public"
    ):
        raise ValueError("non-public or mismatched PR repository")
    context._public(head_repo.get("full_name"))
    base_sha, head_sha = _sha(base.get("sha")), _sha(head.get("sha"))
    compare_url = f"{api}/compare/{base_sha}...{head_sha}"
    comparison = context._json(compare_url + "?per_page=1&page=1", limit=300_000)
    if (
        not isinstance(comparison, dict)
        or comparison.get("url") != compare_url
        or not isinstance(comparison.get("base_commit"), dict)
        or comparison["base_commit"].get("sha") != base_sha
        or not isinstance(comparison.get("merge_base_commit"), dict)
    ):
        raise ValueError("mismatched immutable PR comparison")
    merge_base = _sha(comparison["merge_base_commit"].get("sha"))
    files = comparison.get("files")
    if not isinstance(files, list) or len(files) > 300:
        raise ValueError("invalid bounded PR file list")
    observed = {}
    for item in files:
        if not isinstance(item, dict):
            raise ValueError("invalid PR file")
        path = _path(item.get("filename"))
        if path in observed:
            raise ValueError("duplicate PR file")
        if item.get("previous_filename") is not None:
            _path(item["previous_filename"])
        observed[path] = item
    preferred = set()
    prefix = f"https://raw.githubusercontent.com/{repo}/"
    for source in sources[:25]:
        url = source.get("url", "") if isinstance(source, dict) else ""
        if isinstance(url, str) and url.startswith(prefix):
            revision, separator, path = url[len(prefix) :].partition("/")
            if separator and SHA.fullmatch(revision):
                preferred.add(urllib.parse.unquote(path))
    paths = sorted(observed, key=lambda path: (path not in preferred, path))[:3]
    text = [
        f"Observed PR #{number}: {html}/pull/{number}",
        f"base={base_sha}; head={head_sha}; merge_base={merge_base}",
        "Partial immutable BASE...HEAD patch excerpts (merge-base to head), not "
        "full files, coverage, tests, merge status or proof a reported bug is fixed. "
        "API file list is capped at 300; absent/short patches may be omitted by "
        "the API. Only the first requested displayed PR is inspected.",
    ]
    for path in paths:
        item = observed[path]
        text.append(f"\nfile={path}; previous_filename={item.get('previous_filename')}")
        patch = item.get("patch")
        if not isinstance(patch, str):
            text.append("[API supplied no patch; binary/omission not distinguished]")
        else:
            text.append(patch[:1800])
            if len(patch) > 1800:
                text.append("[patch excerpt truncated]")
    return [
        {
            "url": f"{html}/compare/{base_sha}...{head_sha}",
            "text": "\n".join(text),
            "truncated": True,
            "pr_number": number,
            "base_commit": base_sha,
            "head_commit": head_sha,
            "merge_base_commit": merge_base,
            "pr_revision_excerpt": True,
            "patch_exhaustive": False,
            "observed_files": len(files),
            "displayed_files": paths,
        }
    ]
