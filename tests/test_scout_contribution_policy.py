"""Owner intake preserves inherited public provenance and incomplete reads."""

import base64
import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import scout_contribution_policy as policy
import scout_lesson_context


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.responses = {}
        self.calls = []
        self.add_repo("example/project")
        self.add_repo("example/.github")
        self.responses["example/project/community/profile"] = {"files": {}}

    def add_repo(self, repo, branch="main"):
        self.responses[repo] = {
            "full_name": repo,
            "private": False,
            "visibility": "public",
            "default_branch": branch,
        }
        self.responses[repo + "/commits/" + policy.quote(branch, safe="")] = {
            "sha": "a" * 40
        }

    def add_document(
        self,
        kind="contributing",
        repo="example/.github",
        path="CONTRIBUTING.md",
        text="Read these rules.",
    ):
        branch = self.responses[repo]["default_branch"]
        self.responses["example/project/community/profile"]["files"][kind] = {
            "html_url": f"https://github.com/{repo}/blob/{branch}/{path}",
            "url": "https://api.github.com/repos/example/project/contents/wrong",
        }
        raw = text.encode()
        content = {
            "type": "file",
            "path": path,
            "encoding": "base64",
            "size": len(raw),
            "sha": hashlib.sha1(
                b"blob " + str(len(raw)).encode() + b"\0" + raw
            ).hexdigest(),
            "content": base64.encodebytes(raw).decode(),
        }
        key = repo + "/contents/" + path + "?ref=" + "a" * 40
        self.responses[key] = content
        return content

    def fetch(self, url, *, limit, github_auth):
        self.assertTrue(url.startswith(policy.API))
        self.assertEqual(limit, 100000)
        key = url[len(policy.API) :]
        self.calls.append(key)
        result = self.responses[key]
        if isinstance(result, Exception):
            raise result
        return json.dumps(result)

    def collect(self):
        return policy.collect("example/project", fetch=self.fetch)

    def test_inherited_policy_uses_actual_owner_repository_not_wrong_contents_url(self):
        self.add_document(text="AI-generated contributions are not accepted.")
        self.add_document(
            "pull_request_template",
            "example/project",
            ".github/pull_request_template.md",
        )
        result = self.collect()
        self.assertEqual(result["status"], "DOCUMENTS_REQUIRE_REVIEW")
        inherited, local = result["documents"]
        self.assertTrue(inherited["inherited"])
        self.assertFalse(local["inherited"])
        self.assertIn("/blob/" + "a" * 40 + "/", inherited["url"])
        self.assertEqual(
            inherited["text"], "AI-generated contributions are not accepted."
        )
        self.assertFalse(any("/wrong" in call for call in self.calls))
        self.assertEqual(result["errors"], [])
        # Contents are evidence, never an automatic acceptance or ban decision.
        self.assertNotIn("allowed", result)

    def test_local_policy_does_not_require_owner_default_repository(self):
        self.add_document(repo="example/project")
        del self.responses["example/.github"]
        self.assertEqual(self.collect()["status"], "DOCUMENTS_REQUIRE_REVIEW")
        self.assertNotIn("example/.github", self.calls)

    def test_absence_is_not_permission(self):
        result = self.collect()
        self.assertEqual(result["status"], "NO_DOCUMENTS_IN_PROFILE")
        self.assertIn("not permission", result["caution"])

    def test_private_target_stops_before_profile(self):
        self.responses["example/project"]["private"] = True
        self.assertEqual(self.collect()["status"], "UNKNOWN")
        self.assertEqual(self.calls, ["example/project"])

    def test_foreign_policy_url_is_not_fetched(self):
        self.responses["example/project/community/profile"]["files"]["contributing"] = {
            "html_url": "https://github.com/evil/other/blob/main/CONTRIBUTING.md"
        }
        result = self.collect()
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertEqual(
            self.calls, ["example/project", "example/project/community/profile"]
        )

    def test_transport_failure_is_unknown_not_absence(self):
        self.responses["example/project/community/profile"] = HTTPError(
            "https://api.github.com/", 403, "limited", {}, None
        )
        self.assertEqual(self.collect()["status"], "UNKNOWN")

    def test_content_size_hash_type_and_path_are_checked(self):
        content = self.add_document()
        original = copy.deepcopy(content)
        for field, value in (
            ("size", policy.DOCUMENT_LIMIT + 1),
            ("sha", "0" * 40),
            ("type", "symlink"),
            ("path", "other"),
            ("content", "!!!!"),
        ):
            with self.subTest(field=field):
                content.clear()
                content.update(original)
                content[field] = value
                self.assertEqual(self.collect()["status"], "UNKNOWN")

    def test_branch_with_slash_is_resolved_then_pinned(self):
        self.add_repo("example/.github", "docs/default")
        self.add_document()
        self.assertEqual(self.collect()["status"], "DOCUMENTS_REQUIRE_REVIEW")
        self.assertIn("example/.github/commits/docs%2Fdefault", self.calls)

    def test_inherited_private_repository_and_missing_content_remain_unknown(self):
        self.add_document()
        self.responses["example/.github"]["private"] = True
        self.assertEqual(self.collect()["status"], "UNKNOWN")

    def test_malformed_names_urls_and_contents_are_unknown(self):
        self.add_document()
        original = copy.deepcopy(self.responses)
        for scope in ("name", "url", "content"):
            with self.subTest(scope=scope):
                self.responses = copy.deepcopy(original)
                if scope == "name":
                    self.responses["example/project"]["full_name"] = None
                elif scope == "url":
                    self.responses["example/project/community/profile"]["files"][
                        "contributing"
                    ]["html_url"] = 7
                else:
                    self.responses[
                        "example/.github/contents/CONTRIBUTING.md?ref=" + "a" * 40
                    ]["content"] = None
                self.assertEqual(self.collect()["status"], "UNKNOWN")

    def test_traversal_input_never_fetches(self):
        with self.assertRaises(ValueError):
            policy.collect("../project", fetch=self.fetch)
        self.assertEqual(self.calls, [])

    def test_policy_lesson_is_retrievable_as_one_complete_advisory_card(self):
        result = scout_lesson_context.lesson_suggestions(
            "inherited contribution policy AI eligibility",
            directory=Path(__file__).resolve().parents[1] / "knowledge/lessons",
        )
        self.assertEqual(result["status"], "ADVISORY_MATCH")
        card = result["matches"][0]
        self.assertEqual(card["id"], "inherited-contribution-policy-before-intake")
        self.assertLessEqual(len(json.dumps(card, ensure_ascii=False).encode()), 8192)


if __name__ == "__main__":
    unittest.main()
