"""Bounded read-only blob comparison before investing in an old Scout lead.

No source execution, queue mutation or defect verdict. A missing path can mean
deletion or a move; changed blobs require inspection, not automatic rejection.
"""

import argparse
import json
import re
from urllib.error import HTTPError
from urllib.parse import quote

import kimi_scout as scout

MAX_URLS = 32
RAW = re.compile(
    r"https://raw\.githubusercontent\.com/"
    r"([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/([0-9a-f]{40})/([A-Za-z0-9_./-]+)"
)
SHA = re.compile(r"[0-9a-f]{40}")


def parse_source(url):
    match = RAW.fullmatch(url)
    if not match:
        raise ValueError("expected an immutable GitHub raw source URL")
    repo, revision, path = match.groups()
    scout.public_repo(repo)
    if any(part in {".", ".."} for part in repo.split("/")):
        raise ValueError("invalid repository path")
    if any(part in {"", ".", ".."} for part in path.split("/")):
        raise ValueError("invalid source path")
    return repo, revision, path


class FreshnessCheck:
    """Memoize only within this check; every new invocation resolves a fresh head."""

    def __init__(self, github_auth=False, target_ref=None):
        if target_ref is not None and (
            not isinstance(target_ref, str)
            or not target_ref
            or len(target_ref) > 200
            or any(c.isspace() or ord(c) < 32 for c in target_ref)
        ):
            raise ValueError("invalid target ref")
        self.github_auth = github_auth
        self.target_ref = target_ref
        self.responses = {}
        self.heads = {}
        self.requests = 0

    def get(self, url):
        if url not in self.responses:
            self.requests += 1
            try:
                self.responses[url] = json.loads(
                    scout.fetch(url, github_auth=self.github_auth)
                )
            except (OSError, ValueError) as exc:
                self.responses[url] = exc
        value = self.responses[url]
        if isinstance(value, Exception):
            raise value
        return value

    def target(self, repo):
        if repo not in self.heads:
            base = f"https://api.github.com/repos/{repo}"
            info = self.get(base)
            if (
                not isinstance(info, dict)
                or info.get("private") is not False
                or info.get("visibility") != "public"
                or str(info.get("full_name", "")).casefold() != repo.casefold()
            ):
                raise ValueError(
                    "repository is not explicitly public with matching identity"
                )
            ref = self.target_ref or info.get("default_branch")
            if not isinstance(ref, str) or not ref:
                raise ValueError("missing target branch")
            commit = self.get(base + "/commits/" + quote(ref, safe=""))
            revision = commit.get("sha") if isinstance(commit, dict) else None
            if not isinstance(revision, str) or not SHA.fullmatch(revision):
                raise ValueError("invalid resolved target commit")
            self.heads[repo] = ref, revision
        return self.heads[repo]

    def blob(self, repo, revision, path):
        url = (
            f"https://api.github.com/repos/{repo}/contents/"
            f"{quote(path, safe='/')}?ref={revision}"
        )
        item = self.get(url)
        if not isinstance(item, dict) or item.get("path") != path:
            raise ValueError("contents response path mismatch")
        if item.get("type") != "file" or item.get("submodule_git_url"):
            raise ValueError("source is not a file contents entry")
        value = item.get("sha")
        if not isinstance(value, str) or not SHA.fullmatch(value):
            raise ValueError("invalid file blob identity")
        return value

    def check(self, url):
        repo, revision, path = parse_source(url)
        result = {
            "source_url": url,
            "repo": repo,
            "path": path,
            "source_revision": revision,
            "status": "INCONCLUSIVE",
        }
        try:
            ref, target = self.target(repo)
            result.update(target_ref=ref, target_revision=target)
            result["source_blob"] = self.blob(repo, revision, path)
            try:
                result["target_blob"] = self.blob(repo, target, path)
            except HTTPError as exc:
                if exc.code != 404:
                    raise
                result["status"] = "PATH_ABSENT_AT_TARGET"
                return result
            result["status"] = (
                "BLOB_UNCHANGED"
                if result["source_blob"] == result["target_blob"]
                else "BLOB_CHANGED"
            )
        except (OSError, ValueError) as exc:
            # A head/baseline lookup failure is not evidence of target deletion.
            result["error"] = str(exc)
        return result


def inspect_sources(urls, *, github_auth=False, target_ref=None):
    if not 1 <= len(urls) <= MAX_URLS:
        raise ValueError(f"supply 1 to {MAX_URLS} source URLs")
    for url in urls:
        parse_source(url)  # Reject the whole invalid request before any network read.
    checker = FreshnessCheck(github_auth, target_ref)
    results = [checker.check(url) for url in dict.fromkeys(urls)]
    return {
        "results": results,
        "api_requests": checker.requests,
        "claim_boundary": "Path/blob freshness only, not fix status, reachability, "
        "execution, novelty or PR readiness. Inspect moves and "
        "release-branch scope before parking a missing path.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_urls", nargs="+")
    parser.add_argument("--github-auth", action="store_true")
    parser.add_argument(
        "--target-ref", help="default: each repository's default branch"
    )
    args = parser.parse_args()
    print(
        json.dumps(
            inspect_sources(
                args.source_urls,
                github_auth=args.github_auth,
                target_ref=args.target_ref,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
