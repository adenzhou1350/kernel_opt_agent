"""Metadata-only historical repair enrollment; no clone, code execution or oracle.

Freeze the parameters before calling this on a fresh repository. A selected
parent/head is one related public-history group, not a fresh bug or unseen model
sample. Missing history/objects are failures, never a reason to replace a draw.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
from pathlib import Path

FIX = re.compile(r"\b(?:fix(?:es|ed)?|bug|correct)\b", re.I)
SECURITY = re.compile(r"\b(?:security|vulnerability|CVE)\b", re.I)
SHA = re.compile(r"[0-9a-f]{40}")


def draw(repo, ref, *, production_prefixes, test_prefixes, count=60,
         max_production_files=4, max_production_lines=180,
         history_scope="first-parent", language="python"):
    if type(count) is not int or not 1 <= count <= 1000:
        raise ValueError("frame count must be within 1..1000")
    if any(type(n) is not int or n <= 0 for n in (max_production_files, max_production_lines)):
        raise ValueError("positive production bounds required")
    if not isinstance(ref, str) or not ref or ref.startswith("-") or "\0" in ref:
        raise ValueError("nonempty Git revision, not an option, required")
    if history_scope not in ("first-parent", "reachable"):
        raise ValueError("history_scope must be first-parent or reachable")
    if language not in ("python", "go"):
        raise ValueError("language must be python or go")

    def valid_prefix(prefix):
        # Go convention puts production and *_test.go files together, often
        # at the module root. Only this explicit mode admits that root scope.
        if language == "go" and prefix == "./":
            return True
        return (isinstance(prefix, str) and prefix.endswith("/")
                and not prefix.startswith(("/", "-")) and "\\" not in prefix
                and ":" not in prefix
                and not any(part in ("", ".", "..") for part in prefix[:-1].split("/")))

    for group in (production_prefixes, test_prefixes):
        if not group or any(not valid_prefix(p) for p in group):
            raise ValueError("literal repository-relative directory prefixes required")
    if language == "python" and any(a.startswith(b) or b.startswith(a) for a in production_prefixes for b in test_prefixes):
        raise ValueError("production and test scopes must be disjoint")
    repo = Path(repo).resolve(strict=True)
    env = dict(os.environ, GIT_NO_LAZY_FETCH="1", GIT_TERMINAL_PROMPT="0")

    def git(*args):
        return subprocess.check_output(["git", "-C", str(repo), *args], env=env, timeout=30).decode("utf-8")

    if git("rev-parse", "--is-shallow-repository").strip() != "false":
        raise ValueError("incomplete shallow history; do not interpret as an empty draw")
    head = git("rev-parse", "--verify", ref + "^{commit}").strip()
    if not SHA.fullmatch(head):
        raise ValueError("only SHA-1 Git repositories are supported")
    frame = []
    history_args = ["--first-parent"] if history_scope == "first-parent" else []
    for line in git("log", *history_args, "--no-merges", f"-{count}",
                    "--format=%H%x00%P%x00%s", head).splitlines():
        commit, parents, title = line.split("\0", 2)
        frame.append(dict(commit=commit, parents=parents.split(), title=title))
    scanned, selected = [], None
    for row in frame:
        record = dict(row)
        scanned.append(record)
        if len(row["parents"]) != 1 or not FIX.search(row["title"]):
            continue
        if SECURITY.search(row["title"]):
            record["excluded"] = "SECURITY_TITLE"
            continue
        parent, commit = row["parents"][0], row["commit"]
        scopes = (*production_prefixes, *test_prefixes)
        pathspecs = [] if "./" in scopes else [":(literal)" + p for p in scopes]
        stat = git("diff", "--no-ext-diff", "--no-textconv", "--no-renames", "--numstat", "-z",
                   parent, commit, "--", *pathspecs)
        entries = [item.split("\t", 2) for item in stat.split("\0") if item]

        def in_scope(path, prefixes):
            return any(p == "./" or path.startswith(p) for p in prefixes)

        if language == "go":
            production = [e for e in entries if e[2].endswith(".go")
                          and not e[2].endswith("_test.go") and in_scope(e[2], production_prefixes)]
            tests = [e[2] for e in entries if e[2].endswith("_test.go")
                     and in_scope(e[2], test_prefixes)]
        else:
            production = [e for e in entries if e[2].endswith(".py") and in_scope(e[2], production_prefixes)]
            tests = [e[2] for e in entries if e[2].endswith(".py") and in_scope(e[2], test_prefixes)]
        if not 1 <= len(production) <= max_production_files or not tests:
            continue
        if any(not a.isdigit() or not b.isdigit() for a, b, _ in production):
            record["excluded"] = "NON_TEXT_PRODUCTION_STAT"
            continue
        changed = sum(int(a) + int(b) for a, b, _ in production)
        if changed > max_production_lines:
            continue
        selected = dict(commit=commit, parent=parent, title=row["title"],
                        production_paths=[e[2] for e in production], test_paths=tests,
                        changed_production_lines=changed,
                        tree=git("rev-parse", commit + "^{tree}").strip(),
                        parent_tree=git("rev-parse", parent + "^{tree}").strip())
        break
    return dict(head=head, frame_count=len(frame), requested_frame_count=count,
                history_scope=history_scope, language=language,
                production_prefixes=list(production_prefixes), test_prefixes=list(test_prefixes),
                max_production_files=max_production_files, max_production_lines=max_production_lines,
                scanned=scanned, selected=selected, source_semantics_shown=False,
                replacement_on_failure=False, model_calls=0,
                boundary="Non-shallow metadata frame of single-parent commits only; history scope and language are explicit. Production bounds count only that language's classified source, not the entire commit. Reachable side-branch commits are not independent groups or merge-net-change labels. No native discrimination, new PR, memorization-free holdout or policy utility implied.")


def main():
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--ref", default="HEAD")
    parser.add_argument("--count", type=int, default=60)
    parser.add_argument("--max-production-files", type=int, default=4)
    parser.add_argument("--max-production-lines", type=int, default=180)
    parser.add_argument("--history-scope", choices=("first-parent", "reachable"), default="first-parent",
                        help="reachable also includes single-parent commits on merged side branches; declares a different draw population")
    parser.add_argument("--language", choices=("python", "go"), default="python",
                        help="Go separates production and tests by *_test.go; permits co-located prefixes and explicit ./ root scope")
    parser.add_argument("--production-prefix", action="append", required=True)
    parser.add_argument("--test-prefix", action="append", required=True)
    args = parser.parse_args()
    print(json.dumps(draw(args.repo, args.ref, production_prefixes=args.production_prefix,
                          test_prefixes=args.test_prefix, count=args.count,
                          max_production_files=args.max_production_files,
                          max_production_lines=args.max_production_lines,
                          history_scope=args.history_scope, language=args.language), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
