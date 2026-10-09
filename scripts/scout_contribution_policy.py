"""Read bounded public contribution documents before spending on a new Scout scope.

Optional owner intake, not an automatic policy classifier or publication gate.
GitHub's community profile can point at an owner's inherited .github document.
"""

import argparse
import base64
import binascii
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import quote

import kimi_scout as scout

API = "https://api.github.com/repos/"
DOCUMENT_LIMIT = 32768
CAUTION = (
    "Read these documents and any linked rules/AGENTS.md before selecting a "
    "contribution scope. This is bounded discovery, not permission to publish or "
    "proof that all policies were found. No AI-ban, disclosure, human-review or "
    "CLA requirement is classified automatically. Recheck live rules before publishing."
    " Document discovery does not check current interaction limits, contributor"
    " eligibility or permission to open a PR; passing native tests cannot establish them."
)


def repository(value):
    scout.public_repo(value)
    if any(part in {".", ".."} for part in value.split("/")):
        raise ValueError("invalid repository")
    return value


def collect(repo, *, github_auth=False, fetch=None):
    repo = repository(repo)
    read = fetch or scout.fetch
    metadata = {}
    commits = {}

    def get(path):
        return json.loads(read(API + path, limit=100000, github_auth=github_auth))

    def public(name):
        if name not in metadata:
            item = get(name)
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("full_name"), str)
                or item["full_name"].casefold() != name.casefold()
                or item.get("private") is not False
                or item.get("visibility") != "public"
            ):
                raise ValueError("repository is not verified public")
            metadata[name] = item
        return metadata[name]

    def document(item):
        # Do not follow arbitrary returned URLs or the profile's contents URL:
        # inherited CONTRIBUTING entries can expose a target-repo contents URL
        # even though their html_url belongs to the owner's .github repository.
        url = item.get("html_url") if isinstance(item, dict) else None
        match = (
            re.fullmatch(r"https://github\.com/([^/]+/[^/]+)/blob/([^?#]+)", url)
            if isinstance(url, str)
            else None
        )
        if not match:
            raise ValueError("invalid policy source URL")
        source_repo, suffix = match.groups()
        allowed = {repo.casefold(), (repo.split("/")[0] + "/.github").casefold()}
        if source_repo.casefold() not in allowed:
            raise ValueError("policy source belongs to an unrelated repository")
        info = public(source_repo)
        branch = info.get("default_branch")
        if not isinstance(branch, str) or not suffix.startswith(branch + "/"):
            raise ValueError("policy source does not use the verified default branch")
        path = suffix[len(branch) + 1 :]
        if (
            not path
            or any(part in {"", ".", ".."} for part in path.split("/"))
            or any(ord(char) < 32 or char in "\\:%" for char in path)
        ):
            raise ValueError("unsafe policy path")
        if source_repo not in commits:
            commit = get(source_repo + "/commits/" + quote(branch, safe=""))
            sha = commit.get("sha") if isinstance(commit, dict) else None
            if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
                raise ValueError("invalid policy commit")
            commits[source_repo] = sha
        sha = commits[source_repo]
        content = get(
            source_repo + "/contents/" + quote(path, safe="/") + "?ref=" + sha
        )
        if (
            not isinstance(content, dict)
            or content.get("type") != "file"
            or content.get("path") != path
            or content.get("encoding") != "base64"
            or not isinstance(content.get("content"), str)
            or type(content.get("size")) is not int
            or not 0 <= content["size"] <= DOCUMENT_LIMIT
        ):
            raise ValueError("policy content is unavailable or exceeds the read budget")
        raw = base64.b64decode("".join(content["content"].split()), validate=True)
        blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        if (
            len(raw) != content["size"]
            or len(raw) > DOCUMENT_LIMIT
            or blob != content.get("sha")
        ):
            raise ValueError("policy content identity mismatch")
        return {
            "repo": source_repo,
            "commit": sha,
            "path": path,
            "inherited": source_repo.casefold() != repo.casefold(),
            "url": f"https://github.com/{source_repo}/blob/{sha}/{quote(path, safe='/')}",
            "sha256": hashlib.sha256(raw).hexdigest(),
            "text": raw.decode("utf-8"),
        }

    result = {
        "repo": repo,
        "status": "UNKNOWN",
        "documents": [],
        "errors": [],
        "caution": CAUTION,
    }
    try:
        public(repo)
        profile = get(repo + "/community/profile")
        files = profile.get("files") if isinstance(profile, dict) else None
        if not isinstance(files, dict):
            raise ValueError("invalid community profile")
    except (OSError, ValueError) as exc:
        result["errors"].append({"scope": "profile", "error": type(exc).__name__})
        return result
    for kind in ("contributing", "pull_request_template"):
        item = files.get(kind)
        if item is None:
            continue
        try:
            result["documents"].append({"kind": kind, **document(item)})
        except (OSError, ValueError, KeyError, binascii.Error) as exc:
            result["errors"].append({"scope": kind, "error": type(exc).__name__})
    if not result["errors"]:
        result["status"] = (
            "DOCUMENTS_REQUIRE_REVIEW"
            if result["documents"]
            else "NO_DOCUMENTS_IN_PROFILE"
        )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--github-auth", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        help="optional new local evidence file; never overwritten",
    )
    args = parser.parse_args()
    if args.output and args.output.exists():
        parser.error("output already exists; choose a fresh evidence file")
    result = collect(args.repo, github_auth=args.github_auth)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(text + "\n")
        print(json.dumps({"status": result["status"], "output": str(args.output)}))
    else:
        print(text)
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
