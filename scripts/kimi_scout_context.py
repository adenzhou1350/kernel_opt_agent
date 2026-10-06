"""Bounded public GitHub context for the scout controller; never executes source."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import re
import time
import urllib.parse

import kimi_scout as scout
from scout_public_cache import read_cache
from scout_issue_excerpt import issue_evidence

SNAPSHOT_TTL = 900
# Reuse verified visibility with the snapshot; a fresh controller rechecks it.
PUBLIC_TTL = SNAPSHOT_TTL
API_LIMIT = 1_000_000
TREE_LIMIT = 8_000_000
RAW_LIMIT = 1_000_000
CACHE_LIMIT = 20_000_000
SHA = re.compile(r"[0-9a-f]{40}")


def _repo(value):
    scout.public_repo(value)
    if len(value) > 256 or any(part in {".", ".."} for part in value.split("/")):
        raise ValueError("invalid public repository")
    return value


def _path(value):
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 1024
        or any(part in {"", ".", ".."} for part in value.split("/"))
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
        or any(char in value for char in "\\:")
    ):
        raise ValueError("unsafe repository-relative path")
    return value


def _ref(value):
    if (
        not isinstance(value, str)
        or len(value) > 255
        or not re.fullmatch(r"[A-Za-z0-9_./-]+", value)
    ):
        raise ValueError("invalid repository revision")
    _path(value)
    return value


def _sha(value):
    if not isinstance(value, str) or not SHA.fullmatch(value):
        raise ValueError("invalid immutable source revision")
    return value


def _number(value, label="issue number", maximum=1_000_000_000):
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError(f"invalid {label}")
    return value


def _text(value):
    return value if isinstance(value, str) else ""


_NATIVE_DECLARATIONS = {
    ".go": re.compile(r"^\s*func\s+(?:\([^()\n]*\)\s*)?([A-Za-z_]\w*)\s*(?:\[|\()"),
    ".rs": re.compile(r'^\s*(?:pub(?:\([^()\n]*\))?\s+)?(?:const\s+)?(?:async\s+)?'
                      r'(?:unsafe\s+)?(?:extern(?:\s+"[^"\n]+")?\s+)?fn\s+([A-Za-z_]\w*)\b'),
}


def _native_declaration(line, language=None):
    patterns = (_NATIVE_DECLARATIONS.values() if language is None else
                [_NATIVE_DECLARATIONS[language]] if language in _NATIVE_DECLARATIONS else [])
    return next((match for pattern in patterns if (match := pattern.match(line))), None)


def _native_definition_choices(lines, selected, language):
    """Bounded lexical alternatives in already-read bytes, not an owner resolver."""
    if language not in _NATIVE_DECLARATIONS:
        return None
    match = _native_declaration(lines[selected], language)
    if not match or len(match[1]) > 128:
        return None
    positions = [index + 1 for index, line in enumerate(lines)
                 if (other := _native_declaration(line, language)) and other[1] == match[1]]
    if len(positions) < 2:
        return None
    return {
        "symbol": match[1],
        "selected_line": selected + 1,
        "candidate_lines": positions[:5],
        "omitted": max(0, len(positions) - 5),
        "caution": "Same-name lexical declarations, not resolved owners or reachability. "
                   "The selected window is unchanged. Request 'declaration line N' for "
                   "a listed line outside it to inspect the intended impl/receiver.",
    }


def _definition_line(lines, hints, language=None):
    """Prefer a requested declaration to incidental keyword mentions.

    Qualified Python class methods use syntax-only ownership when unambiguous.
    Other declarations retain the lexical fallback; neither proves reachability.
    """
    hints = hints[:2000]
    targets = list(dict.fromkeys(re.findall(
        r"\b([A-Z][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)\b", hints
    )))
    if len(targets) == 1:
        owner, method = targets[0]
        try:
            tree = ast.parse("\n".join(lines))
        except (SyntaxError, ValueError, RecursionError):
            pass  # JS/TS and incomplete source still use lexical hints.
        else:
            classes = [node for node in ast.walk(tree)
                       if isinstance(node, ast.ClassDef) and node.name == owner]
            if len(classes) == 1:
                methods = [node for node in classes[0].body
                           if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                           and node.name == method]
                # A later unconditional definition shadows the earlier one.
                return (methods[-1] if methods else classes[0]).lineno - 1
            if classes:
                return None  # Identically named classes have no unique owner.
    names = list(dict.fromkeys(re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", hints)))[:32]
    priority = {name: index for index, name in enumerate(names)}
    qualified = set(re.findall(r"\.([A-Za-z_][A-Za-z0-9_]{2,})\b", hints))
    declaration = re.compile(
        r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?"
        r"(?:def|class|function|const|let|var|type|interface|enum)\s+"
        r"([A-Za-z_]\w*)\b"
    )
    matches = []
    native_matches = []
    for index, line in enumerate(lines):
        match = declaration.match(line)
        native_match = _native_declaration(line, language)
        match = native_match or match
        if match and match[1] in priority:
            name = match[1]
            selected = native_matches if native_match else matches
            selected.append((name not in qualified, priority[name], index))
    if native_matches:
        return min(native_matches)[2]
    return min(matches)[2] if matches else None


class IssuePage(list):
    """Filtered issues with pagination exhaustion from the raw API response."""

    def __init__(self, items, *, exhausted):
        super().__init__(items)
        self.exhausted = exhausted


class PublicContext:
    def __init__(self, root, github_auth=False, tree_roots=None):
        self.cache = Path(root) / "public-cache"
        self.cache.mkdir(parents=True, exist_ok=True)
        self.github_auth = bool(github_auth)
        self._public_until = {}
        self.tree_roots = tree_roots or {}
        for repo, roots in self.tree_roots.items():
            _repo(repo)
            if not isinstance(roots, list) or not 1 <= len(roots) <= 8:
                raise ValueError("tree_roots needs 1..8 explicit directories")
            for name in roots:
                if "/" in _path(name):
                    raise ValueError("tree_roots must be top-level directories")

    def _read(self, url, limit=API_LIMIT, authenticated=True):
        text = scout.fetch(
            url, limit=limit, github_auth=self.github_auth and authenticated
        )
        # Keep the bound enforceable even with an injected fetch implementation.
        if not isinstance(text, str) or len(text.encode("utf-8")) > limit:
            raise ValueError("public source exceeds read budget")
        return text

    def _json(self, url, limit=API_LIMIT, authenticated=True):
        return json.loads(self._read(url, limit, authenticated))

    def _public(self, repo):
        repo = _repo(repo)
        now = time.time()
        if self._public_until.get(repo, 0) > now:
            return repo
        # Authentication may provide API quota, but never establishes visibility.
        # GitHub must explicitly mark the repository public before context reads;
        # private repositories accessible to these credentials remain forbidden.
        metadata = self._json(f"https://api.github.com/repos/{repo}")
        if (
            not isinstance(metadata, dict)
            or metadata.get("private") is not False
            or metadata.get("visibility") != "public"
            or _text(metadata.get("full_name", repo)).lower() != repo.lower()
        ):
            raise ValueError("scout refuses non-public repositories")
        self._public_until[repo] = now + PUBLIC_TTL
        return repo

    def _cache_path(self, kind, identity):
        key = hashlib.sha256(scout.dumps(identity).encode("utf-8")).hexdigest()
        return self.cache / f"{kind}-{key}.json"

    def _load(self, path):
        try:
            data = read_cache(path, CACHE_LIMIT)
            value = json.loads(data)
            return value if isinstance(value, dict) else None
        except (OSError, ValueError, EOFError):
            return None

    def snapshot(self, repo, ref="main"):
        repo, ref = _repo(repo), _ref(ref)
        self._public(repo)
        roots = sorted(set(self.tree_roots.get(repo, [])))
        identity = [repo, ref, roots] if roots else [repo, ref]
        path = self._cache_path("snapshot", identity)
        cached = self._load(path)
        cached_at = cached.get("at") if cached else None
        # Commit-addressed trees do not expire; branch heads still do. Public
        # visibility is checked above, and cached identity/path checks remain.
        if type(cached_at) in {int, float} and (
            SHA.fullmatch(ref) or 0 <= time.time() - cached_at < SNAPSHOT_TTL
        ):
            value = cached.get("snapshot")
            if (
                isinstance(value, dict)
                and value.get("repo") == repo
                and isinstance(value.get("files"), list)
                and isinstance(value.get("blobs"), dict)
            ):
                _sha(value.get("commit"))
                if SHA.fullmatch(ref) and value["commit"] != ref:
                    raise ValueError("cached revision does not match requested commit")
                for name in value["files"]:
                    _path(name)
                    _sha(value["blobs"].get(name))
                return value
        encoded = urllib.parse.quote(ref, safe="")
        commit_data = self._json(
            f"https://api.github.com/repos/{repo}/commits/{encoded}"
        )
        commit = _sha(commit_data["sha"])
        if SHA.fullmatch(ref) and commit != ref:
            raise ValueError("resolved revision does not match requested commit")
        tree_sha = _sha(commit_data["commit"]["tree"]["sha"])
        tree_url = f"https://api.github.com/repos/{repo}/git/trees/"
        if roots:
            # Resolve only explicitly configured top-level trees, from a verified
            # root tree. Large monorepo responses need not be fetched or trusted.
            top = self._json(tree_url + tree_sha, TREE_LIMIT)
            if (
                not isinstance(top, dict)
                or not isinstance(top.get("tree"), list)
                or top.get("truncated")
            ):
                raise ValueError("invalid or truncated root tree")
            entries = [
                e
                for e in top["tree"]
                if isinstance(e, dict) and e.get("type") == "blob"
            ]
            directories = {
                e.get("path"): e
                for e in top["tree"]
                if isinstance(e, dict) and e.get("type") == "tree"
            }
            for name in roots:
                entry = directories.get(name)
                if not entry or entry.get("mode") != "040000":
                    raise ValueError("configured tree root is absent")
                subtree = self._json(
                    tree_url + _sha(entry.get("sha")) + "?recursive=1", TREE_LIMIT
                )
                if not isinstance(subtree, dict) or not isinstance(
                    subtree.get("tree"), list
                ):
                    raise ValueError("invalid public subtree")
                for item in subtree["tree"]:
                    if isinstance(item, dict) and isinstance(item.get("path"), str):
                        # Validate the relative component before prefixing it.
                        try:
                            relative = _path(item["path"])
                        except ValueError:
                            continue
                        entries.append({**item, "path": name + "/" + relative})
            tree = {"tree": entries, "truncated": True}
        else:
            tree = self._json(tree_url + tree_sha + "?recursive=1", TREE_LIMIT)
        if not isinstance(tree, dict) or not isinstance(tree.get("tree"), list):
            raise ValueError("invalid public repository tree")
        blobs, skipped = {}, 0
        for entry in tree["tree"]:
            if not isinstance(entry, dict) or entry.get("type") != "blob":
                continue
            try:
                name, blob = _path(entry.get("path")), _sha(entry.get("sha"))
                if entry.get("mode", "100644") not in {"100644", "100755"}:
                    raise ValueError("non-regular repository file")
            except ValueError:
                skipped += 1
                continue
            blobs[name] = blob
        value = {
            "repo": repo,
            "commit": commit,
            "files": sorted(blobs),
            "blobs": blobs,
            "truncated": bool(tree.get("truncated", False)),
            "skipped_paths": skipped,
            "tree_roots": roots,
        }
        record = {"at": time.time(), "snapshot": value}
        scout.write_json(path, record)
        # A follow-up for the resolved immutable revision reuses this tree.
        if ref != commit:
            alias = [repo, commit, roots] if roots else [repo, commit]
            scout.write_json(self._cache_path("snapshot", alias), record)
        return value

    def source(self, repo, commit, path, hints="", *, start=None, max_lines=120):
        repo, commit, path = _repo(repo), _sha(commit), _path(path)
        _number(max_lines, "source line count", 160)
        if start is not None:
            _number(start, "source start line")
        if not isinstance(hints, str):
            raise ValueError("source hints must be text")
        snapshot = self.snapshot(repo, ref=commit)
        if path not in snapshot["files"]:
            raise ValueError("source path is absent from the public snapshot")
        url = (
            f"https://raw.githubusercontent.com/{repo}/{commit}/"
            + urllib.parse.quote(path, safe="/")
        )
        cache_path = self._cache_path("raw", [repo, commit, path])
        cached = self._load(cache_path)
        raw = cached.get("text") if cached and cached.get("url") == url else None
        if not isinstance(raw, str) or len(raw.encode("utf-8")) > RAW_LIMIT:
            raw = self._read(url, RAW_LIMIT, authenticated=False)
            scout.write_json(cache_path, {"url": url, "text": raw})
        if "\x00" in raw:
            raise ValueError("binary source is not supported")
        lines = raw.splitlines()
        if start is not None and start > max(1, len(lines)):
            raise ValueError("source start line is beyond end of file")
        definition_selection = None
        if start is None:
            definition = _definition_line(lines, hints, language=Path(path).suffix)
            if definition is not None:
                definition_selection = _native_definition_choices(lines, definition, Path(path).suffix)
                offset = max(0, definition - min(30, max_lines // 4))
                start = min(offset, max(0, len(lines) - max_lines)) + 1
        if start is None:
            words = list(
                dict.fromkeys(
                    re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", hints[:2000].lower())
                )
            )[:16]
            scores = [sum(word in line.lower() for word in words) for line in lines]
            best = max(range(len(lines)), key=lambda i: scores[i]) if lines else 0
            offset = (
                max(0, best - min(30, max_lines // 4))
                if words and scores and max(scores)
                else 0
            )
            start = min(offset, max(0, len(lines) - max_lines)) + 1
        end = min(len(lines), start - 1 + max_lines)
        numbered = "\n".join(f"{i + 1}: {lines[i]}" for i in range(start - 1, end))
        evidence = scout.evidence(url, numbered, 9000)
        evidence.update(
            start_line=start,
            end_line=start - 1 + len(evidence["text"].splitlines()),
            total_lines=len(lines),
            truncated=evidence["truncated"] or start > 1 or end < len(lines),
        )
        if definition_selection is not None:
            evidence["definition_selection"] = definition_selection
        return evidence

    def cached_source_text(self, repo, commit, path):
        """Read an existing bounded pinned cache; never acquire new source."""
        repo, commit, path = _repo(repo), _sha(commit), _path(path)
        url = (f"https://raw.githubusercontent.com/{repo}/{commit}/"
               + urllib.parse.quote(path, safe="/"))
        cached = self._load(self._cache_path("raw", [repo, commit, path]))
        raw = cached.get("text") if cached and cached.get("url") == url else None
        return raw if isinstance(raw, str) and len(raw.encode("utf-8")) <= 131072 else None

    def issue_page(self, repo, page=1):
        repo = _repo(repo)
        _number(page, "issue page", 10000)
        self._public(repo)
        query = urllib.parse.urlencode(
            {
                "state": "open",
                "sort": "updated",
                "direction": "desc",
                "per_page": 30,
                "page": page,
            }
        )
        items = self._json(f"https://api.github.com/repos/{repo}/issues?{query}")
        if not isinstance(items, list):
            raise ValueError("invalid public issue page")
        # GitHub includes pull requests in this endpoint. A page containing only
        # filtered records is still a page; later pages may contain real issues.
        result = IssuePage([], exhausted=not items)
        for item in items[:30]:
            if (
                not isinstance(item, dict)
                or "pull_request" in item
                or item.get("state", "open") != "open"
            ):
                continue
            number = _number(item.get("number"))
            title, body = _text(item.get("title")), _text(item.get("body"))
            result.append(
                {
                    "number": number,
                    "title": title[:500],
                    "body": body[:5000],
                    "updated_at": _text(item.get("updated_at")),
                    "state": "open",
                    "html_url": f"https://github.com/{repo}/issues/{number}",
                    "truncated": len(title) > 500 or len(body) > 5000,
                }
            )
        return result

    def issue_sources(self, repo, number):
        repo, number = _repo(repo), _number(number)
        self._public(repo)
        api = f"https://api.github.com/repos/{repo}/issues/{number}"
        item = self._json(api)
        if not isinstance(item, dict) or item.get("number") != number:
            raise ValueError("issue response does not match requested issue")
        kind = "pull" if "pull_request" in item else "issues"
        url = f"https://github.com/{repo}/{kind}/{number}"
        result = [
            scout.evidence(
                url, _text(item.get("title")) + "\n" + _text(item.get("body")), 5000
            )
        ]
        comments = []
        if item.get("comments") != 0:
            comments = self._json(api + "/comments?per_page=3&page=1", 300_000)
            if not isinstance(comments, list):
                raise ValueError("invalid issue comments")
        # Keep lifecycle facts from the GET already performed. An old report
        # body can remain unchanged after a fix; closed is not itself proof
        # that this target revision is fixed or that a linked PR was merged.
        state = item.get("state")
        reason = item.get("state_reason")
        result[0].update(
            observed_report_kind="pull_request" if kind == "pull" else "issue",
            observed_report_state=state if state in ("open", "closed") else "unknown",
            observed_report_state_reason=reason
            if reason in ("completed", "not_planned", "reopened", "duplicate")
            else None,
            lifecycle_observed_at=time.time(),
            lifecycle_scope="Report state only, not fix, merge, release inclusion or regression proof.",
        )
        for comment in comments[:3]:
            comment_id = _number(comment.get("id"), "comment id", 10**18)
            result.append(
                scout.evidence(
                    f"{url}#issuecomment-{comment_id}", _text(comment.get("body")), 1200
                )
            )
        count = item.get("comments")
        result[0]["comments_truncated"] = (
            type(count) is not int or count > len(result) - 1
        )
        return result

    def issue_pr_context(self, repo, number):
        """One cached, bounded PR-body search for an observed issue number.

        Explicit references are related-work evidence, not a duplicate verdict.
        No pagination, source execution or inference of merge/CI status.
        """
        repo, number = _repo(repo), _number(number)
        self._public(repo)
        query_text = f"repo:{repo} is:pr in:body {number}"
        cache = self._cache_path("issue-pr", [repo, number])
        record = self._load(cache)
        def valid_search(found):
            return (
                isinstance(found, dict)
                and isinstance(found.get("items"), list)
                and type(found.get("total_count")) is int
                and found["total_count"] >= len(found["items"])
                and type(found.get("incomplete_results")) is bool
            )

        if (
            not record
            or type(record.get("at")) not in (int, float)
            or not 0 <= time.time() - record["at"] < SNAPSHOT_TTL
            or not valid_search(record.get("found"))
        ):
            query = urllib.parse.urlencode(
                {"q": query_text, "sort": "updated", "per_page": 5}
            )
            found = self._json(
                f"https://api.github.com/search/issues?{query}", limit=300_000
            )
            if not valid_search(found):
                raise ValueError("invalid issue PR search")
            record = {"at": time.time(), "found": found}
            scout.write_json(cache, record)
        found = record.get("found")
        reference = re.compile(
            rf"https://github\.com/{re.escape(repo)}/issues/{number}(?![0-9A-Za-z_/])"
            rf"|(?<![\w/#])#{number}(?![0-9A-Za-z_])"
        )
        result = []
        for item in found["items"][:5]:
            if not isinstance(item, dict):
                continue
            pr = item.get("number")
            link = item.get("pull_request")
            body = item.get("body")
            title = item.get("title")
            if (
                type(pr) is not int or not 1 <= pr <= 1_000_000_000
                or not isinstance(link, dict)
                or link.get("url") != f"https://api.github.com/repos/{repo}/pulls/{pr}"
                or item.get("html_url") != f"https://github.com/{repo}/pull/{pr}"
                or item.get("repository_url") != f"https://api.github.com/repos/{repo}"
                or not isinstance(body, str) or not isinstance(title, str)
                or item.get("state") not in ("open", "closed")
            ):
                continue
            match = reference.search(body)
            if match is None:
                continue  # A bare digit substring is not an issue reference.
            source = issue_evidence(item["html_url"], title, body, limit=2200)
            source.update(
                is_pr=True, search_exhaustive=False, search_query=query_text,
                referenced_issue=number, observed_pr_state=item["state"],
                reference_literal=match[0],
            )
            result.append(source)
        return {
            "sources": result,
            "query": query_text,
            "status": "PARTIAL_SEARCH",
            "search_exhaustive": False,
            "incomplete_results": found.get("incomplete_results"),
            "total_count": found.get("total_count"),
            "returned_items": len(found["items"][:5]),
            "scope": "At most five PR-body hits; explicit issue references only. Neither a fix/merge verdict nor proof that an empty sample excludes existing work.",
        }

    def duplicate_sources(self, repo, title):
        repo = _repo(repo)
        if not isinstance(title, str):
            raise ValueError("duplicate query title must be text")
        words = list(dict.fromkeys(re.findall(r"\w+", title[:1000])))[:6]
        if not words:
            return []
        self._public(repo)
        # Quoted words cannot inject GitHub search operators or change scope.
        terms = " ".join('"' + word[:32] + '"' for word in words)
        # Six title words are conjunctive, including incidental prose. An empty
        # result can hide an exact fix with a differently worded title. Try one
        # narrower identifier (or two words) after an empty/issue-only sample;
        # this stays bounded and supplies related evidence, never a verdict.
        identifiers = re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", title[:1000])
        anchor = next((word for word in identifiers if
                       "_" in word.strip("_") or
                       re.search(r"[a-z][A-Z]|[A-Z]{2}[a-z]|[A-Za-z][0-9]", word)), None)
        fallback = '"' + anchor[:32] + '"' if anchor else " ".join(
            '"' + word[:32] + '"' for word in words[:2]
        )
        query_text = f"repo:{repo} in:title,body {terms}"
        result = []
        repository_url = f"https://api.github.com/repos/{repo}"
        for attempt in range(2):
            query = urllib.parse.urlencode(
                {"q": query_text, "sort": "updated", "per_page": 5}
            )
            found = self._json(f"https://api.github.com/search/issues?{query}")
            if not isinstance(found, dict) or not isinstance(found.get("items"), list):
                raise ValueError("invalid public duplicate search")
            hits = []
            for item in found["items"][:5]:
                if (
                    not isinstance(item, dict)
                    or _text(item.get("repository_url", repository_url)).lower()
                    != repository_url.lower()
                ):
                    continue
                number = _number(item.get("number"))
                is_pr = isinstance(item.get("pull_request"), dict)
                if " is:pr " in query_text and not is_pr:
                    continue
                kind = "pull" if is_pr else "issues"
                evidence = scout.evidence(
                    f"https://github.com/{repo}/{kind}/{number}",
                    _text(item.get("title")) + "\n" + _text(item.get("body")),
                    1800,
                )
                evidence.update(is_pr=is_pr, search_exhaustive=False,
                                search_query=query_text)
                hits.append(evidence)
            known = {source["url"] for source in result}
            for source in hits:
                if source["url"] not in known:
                    result.append(source)
                    known.add(source["url"])
            if attempt or any(source["is_pr"] for source in hits):
                break
            # A title search often rediscovers its own issue. That is useful
            # context, but must not hide a differently titled fix PR. Use the
            # existing second-query allowance, retaining the original issue
            # sample. Empty searches keep the original broader fallback.
            scope = " is:pr" if hits else ""
            next_query = f"repo:{repo}{scope} in:title,body {fallback}"
            if next_query == query_text:
                break
            query_text = next_query
        # Same five-excerpt budget; fix candidates before issue context. A hit
        # remains partial related-work evidence, never a suppression verdict.
        return sorted(result, key=lambda source: not source["is_pr"])[:5]
