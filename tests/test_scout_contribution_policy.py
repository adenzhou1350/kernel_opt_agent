"""Owner intake preserves inherited public provenance and incomplete reads."""

import base64
import copy
import io
import hashlib
import json
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError
from unittest import mock

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

    def collect(self, **kwargs):
        return policy.collect("example/project", fetch=self.fetch, **kwargs)

    def requested_document(self, path="DEVELOPMENT.md", text="Mark AI-assisted commits explicitly."):
        content = self.add_document("unused", "example/project", path, text)
        del self.responses["example/project/community/profile"]["files"]["unused"]
        return content

    def test_explicit_development_guide_is_pinned_without_classifying_permission(self):
        self.requested_document()
        result = self.collect(document_paths=["DEVELOPMENT.md"])
        self.assertEqual(result["status"], "DOCUMENTS_REQUIRE_REVIEW")
        doc, = result["documents"]
        self.assertEqual(doc["kind"], "requested")
        self.assertEqual(doc["path"], "DEVELOPMENT.md")
        self.assertFalse(doc["inherited"])
        self.assertIn("/blob/" + "a" * 40 + "/DEVELOPMENT.md", doc["url"])
        self.assertIn("AI-assisted commits", doc["text"])
        self.assertNotIn("allowed", result)
        self.assertNotIn("authorized", result)

    def test_requested_and_profile_guides_share_one_commit_and_skip_duplicates(self):
        self.add_document(repo="example/project")
        self.requested_document()
        result = self.collect(document_paths=["CONTRIBUTING.md", "DEVELOPMENT.md", "DEVELOPMENT.md"])
        self.assertEqual([d["path"] for d in result["documents"]], ["CONTRIBUTING.md", "DEVELOPMENT.md"])
        self.assertEqual(self.calls.count("example/project/commits/main"), 1)
        self.assertEqual(sum("contents/DEVELOPMENT.md" in call for call in self.calls), 1)
        self.assertEqual(sum("contents/CONTRIBUTING.md" in call for call in self.calls), 1)

    def test_requested_nested_path_uses_verified_default_branch(self):
        self.add_repo("example/project", "docs/default")
        self.requested_document("docs/DEVELOPMENT.md")
        result = self.collect(document_paths=["docs/DEVELOPMENT.md"])
        self.assertEqual(result["status"], "DOCUMENTS_REQUIRE_REVIEW")
        self.assertIn("example/project/commits/docs%2Fdefault", self.calls)
        self.assertEqual(result["documents"][0]["path"], "docs/DEVELOPMENT.md")

    def test_requested_path_validation_and_budget_precede_all_fetches(self):
        invalid = [None, "DEVELOPMENT.md", ["x"] * 5, [4], [""], ["../secret"],
                   ["/DEVELOPMENT.md"], ["docs//guide"], ["docs/./guide"],
                   ["C:\\secret"], ["https://other/guide"], ["docs/%2e%2e/guide"],
                   ["guide?ref=other"], ["guide#section"], ["guide\n"], ["x" * 513]]
        for paths in invalid:
            with self.subTest(paths=paths), self.assertRaises(ValueError):
                self.collect(document_paths=paths)
        self.assertEqual(self.calls, [])

    def test_four_requested_documents_are_bounded_and_default_scan_is_unchanged(self):
        paths = ["docs/guide%d.md" % index for index in range(4)]
        for path in paths:
            self.requested_document(path)
        result = self.collect(document_paths=paths)
        self.assertEqual([d["path"] for d in result["documents"]], paths)
        self.assertEqual(len(self.calls), 7)  # Metadata, profile, one commit, four contents.

    def test_requested_missing_or_bad_content_stays_unknown_with_good_documents(self):
        for bad in (HTTPError("https://api.github.com/", 404, "missing", {}, None),
                    {"type": "symlink"}, {"sha": "0" * 40}):
            with self.subTest(bad=bad):
                self.setUp()
                self.add_document("readme", "example/project", "README.md")
                content = self.requested_document()
                key = "example/project/contents/DEVELOPMENT.md?ref=" + "a" * 40
                if isinstance(bad, Exception):
                    self.responses[key] = bad
                else:
                    content.update(bad)
                result = self.collect(document_paths=["DEVELOPMENT.md"])
                self.assertEqual(result["status"], "UNKNOWN")
                self.assertEqual([d["path"] for d in result["documents"]], ["README.md"])
                self.assertEqual(result["errors"][0]["scope"], "requested:DEVELOPMENT.md")

    def test_requested_document_does_not_route_around_profile_denial(self):
        self.requested_document()
        self.responses["example/project/community/profile"] = HTTPError(
            "https://api.github.com/", 403, "limited", {}, None)
        result = self.collect(document_paths=["DEVELOPMENT.md"])
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertEqual(self.calls, ["example/project", "example/project/community/profile"])

    def test_cli_passes_only_explicit_document_paths(self):
        result = {"status": "DOCUMENTS_REQUIRE_REVIEW", "errors": []}
        argv = ["policy", "--repo", "example/project", "--document-path", "DEVELOPMENT.md"]
        with mock.patch.object(sys, "argv", argv), mock.patch.object(policy, "collect", return_value=result) as collect:
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(policy.main(), 0)
        collect.assert_called_once_with("example/project", github_auth=False,
                                        document_paths=["DEVELOPMENT.md"])
        self.assertEqual(json.loads(output.getvalue()), result)

    def test_cli_invalid_requested_path_stops_without_network(self):
        argv = ["policy", "--repo", "example/project", "--document-path", "../secret"]
        with mock.patch.object(sys, "argv", argv), mock.patch.object(policy.scout, "fetch") as fetch:
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                policy.main()
        self.assertEqual(error.exception.code, 2)
        fetch.assert_not_called()

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

    def test_readme_only_rules_are_retained_without_classifying_permission(self):
        self.add_document("readme", "example/project", "README.rst",
                          "AI-assisted reports require affected production code.")
        result = self.collect()
        self.assertEqual(result["status"], "DOCUMENTS_REQUIRE_REVIEW")
        self.assertEqual([d["kind"] for d in result["documents"]], ["readme"])
        self.assertEqual(result["documents"][0]["path"], "README.rst")
        self.assertIn("affected production code", result["documents"][0]["text"])
        self.assertNotIn("allowed", result)

    def test_readme_and_guide_share_one_pinned_commit_lookup(self):
        self.add_document(repo="example/project")
        self.add_document("readme", "example/project", "README.md")
        result = self.collect()
        self.assertEqual([d["kind"] for d in result["documents"]],
                         ["contributing", "readme"])
        self.assertEqual(self.calls.count("example/project/commits/main"), 1)
        self.assertEqual(result["errors"], [])

    def test_oversized_readme_remains_unknown_not_missing_policy(self):
        content = self.add_document("readme", "example/project", "README.md")
        content["size"] = policy.DOCUMENT_LIMIT + 1
        result = self.collect()
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertEqual(result["documents"], [])
        self.assertEqual(result["errors"][0]["scope"], "readme")

    def test_absence_is_not_permission(self):
        result = self.collect()
        self.assertEqual(result["status"], "NO_DOCUMENTS_IN_PROFILE")
        self.assertIn("not permission", result["caution"])

    def test_private_target_stops_before_profile(self):
        self.responses["example/project"]["private"] = True
        result = self.collect()
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertIsNone(result["repository_settings"])
        self.assertEqual(self.calls, ["example/project"])

    def test_enabled_prs_and_collaborator_policy_are_separate_observations(self):
        self.responses["example/project"].update(
            {
                "archived": False,
                "disabled": False,
                "has_issues": True,
                "has_pull_requests": True,
                "pull_request_creation_policy": "collaborators_only",
                "permissions": {"push": False},
            }
        )
        result = self.collect()
        settings = result["repository_settings"]
        self.assertTrue(settings["has_pull_requests"])
        self.assertTrue(settings["has_issues"])
        self.assertEqual(settings["pull_request_creation_policy"], "collaborators_only")
        self.assertFalse(settings["viewer_can_push"])
        self.assertEqual(settings["url"], policy.API + "example/project")
        self.assertIsNotNone(datetime.fromisoformat(settings["observed_at"]).tzinfo)
        self.assertEqual(result["status"], "NO_DOCUMENTS_IN_PROFILE")
        self.assertNotIn("authorized", result)
        self.assertEqual(
            self.calls, ["example/project", "example/project/community/profile"]
        )

    def test_no_settings_are_not_unrestricted_defaults(self):
        settings = self.collect()["repository_settings"]
        for key in (
            "archived",
            "disabled",
            "has_issues",
            "has_pull_requests",
            "pull_request_creation_policy",
            "viewer_can_push",
        ):
            with self.subTest(key=key):
                self.assertIsNone(settings[key])

    def test_malformed_or_future_values_are_unknown_not_truthy_permissions(self):
        for value in (1, "true", [], {}, "future_policy", None):
            with self.subTest(value=value):
                self.responses["example/project"].update(
                    {
                        "has_pull_requests": value,
                        "has_issues": value,
                        "pull_request_creation_policy": value,
                        "permissions": {"push": value},
                    }
                )
                settings = self.collect()["repository_settings"]
                for key in (
                    "has_pull_requests",
                    "has_issues",
                    "pull_request_creation_policy",
                    "viewer_can_push",
                ):
                    self.assertIsNone(settings[key])

    def test_archived_disabled_and_all_policy_are_not_publication_authority(self):
        self.responses["example/project"].update(
            {
                "archived": True,
                "disabled": True,
                "has_issues": False,
                "has_pull_requests": False,
                "pull_request_creation_policy": "all",
                "permissions": {"push": True},
            }
        )
        result = self.collect()
        settings = result["repository_settings"]
        self.assertTrue(settings["archived"])
        self.assertTrue(settings["disabled"])
        self.assertFalse(settings["has_issues"])
        self.assertFalse(settings["has_pull_requests"])
        self.assertEqual(settings["pull_request_creation_policy"], "all")
        self.assertTrue(settings["viewer_can_push"])
        self.assertNotIn("allowed", result)

    def test_profile_denial_preserves_observed_settings_not_document_approval(self):
        self.responses["example/project"]["pull_request_creation_policy"] = (
            "collaborators_only"
        )
        self.responses["example/project/community/profile"] = HTTPError(
            "https://api.github.com/", 403, "limited", {}, None
        )
        result = self.collect()
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertEqual(
            result["repository_settings"]["pull_request_creation_policy"],
            "collaborators_only",
        )
        self.assertEqual(result["documents"], [])
        self.assertTrue(result["errors"])

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

    def test_empty_profile_keeps_publication_eligibility_unknown(self):
        result = self.collect()
        self.assertEqual(result["status"], "NO_DOCUMENTS_IN_PROFILE")
        self.assertIn("does not check current interaction limits", result["caution"])
        self.assertIn("permission to open a PR", result["caution"])
        self.assertNotIn("authorized", result)

    def test_policy_lesson_is_retrievable_as_one_complete_advisory_card(self):
        result = scout_lesson_context.lesson_suggestions(
            "inherited contribution policy AI eligibility",
            directory=Path(__file__).resolve().parents[1] / "knowledge/lessons",
        )
        self.assertEqual(result["status"], "ADVISORY_MATCH")
        card = result["matches"][0]
        self.assertEqual(card["id"], "inherited-contribution-policy-before-intake")
        self.assertLessEqual(len(json.dumps(card, ensure_ascii=False).encode()), 8192)

    def test_named_guide_advice_keeps_disclosure_distinct_from_a_ban(self):
        result = scout_lesson_context.lesson_suggestions(
            "Pyee DEVELOPMENT.md AI contribution disclosure",
            source_urls=["https://raw.githubusercontent.com/jfhbrook/pyee/"
                         "3116911e09cadcc1e0c85631fbab8aebefc1b772/DEVELOPMENT.md"],
        )
        card = result["matches"][0]
        self.assertEqual(card["id"], "inherited-contribution-policy-before-intake")
        self.assertIn("reviewer disclosure, not a ban", card["lesson"])
        self.assertLessEqual(len(json.dumps(card, ensure_ascii=False).encode()), 8192)
        self.assertEqual(result["oversized_matches_omitted"], 0)
        self.assertNotIn("authorized", result)

    def test_linked_dask_rules_keep_drafts_distinct_from_human_ready_review(self):
        result = scout_lesson_context.lesson_suggestions(
            "Dask linked contribution policy human prose and review",
            source_urls=["https://raw.githubusercontent.com/dask/partd/"
                         "e832b655606342dc742ec1c564b07abf1ad58383/CONTRIBUTING.md"],
        )
        self.assertTrue(result.get("source_path_match"))
        card = result["matches"][0]
        self.assertEqual(card["id"], "inherited-contribution-policy-before-intake")
        linked = next(e for e in card["evidence"] if "docs.dask.org" in e["url"])
        self.assertIn("human-authored", linked["note"])
        self.assertIn("labelled unsupervised Draft", linked["note"])
        self.assertIn("not a blanket research ban", linked["note"])
        self.assertLessEqual(len(json.dumps(card, ensure_ascii=False).encode()), 8192)
        self.assertNotIn("authorized", result)


if __name__ == "__main__":
    unittest.main()
