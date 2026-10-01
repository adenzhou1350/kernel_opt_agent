"""Offline freshness facts; no credentials, network, model or source execution."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import scout_source_freshness as freshness

OLD, NEW, BLOB = "a" * 40, "b" * 40, "c" * 40
BASE = "https://api.github.com/repos/owner/project"
URL = f"https://raw.githubusercontent.com/owner/project/{OLD}/src/check.py"


class FreshnessTests(unittest.TestCase):
    def responses(self, old=None, new=None):
        return {
            BASE: {
                "private": False,
                "visibility": "public",
                "full_name": "owner/project",
                "default_branch": "master",
            },
            BASE + "/commits/master": {"sha": NEW},
            BASE + "/contents/src/check.py?ref=" + OLD: old
            if old is not None
            else {"path": "src/check.py", "type": "file", "sha": BLOB},
            BASE + "/contents/src/check.py?ref=" + NEW: new
            if new is not None
            else {"path": "src/check.py", "type": "file", "sha": BLOB},
        }

    def run_check(self, data, urls=None, **kwargs):
        import json

        def fetch(url, **options):
            value = data[url]
            if isinstance(value, Exception):
                raise value
            return json.dumps(value)

        with patch.object(freshness.scout, "fetch", side_effect=fetch) as mock:
            result = freshness.inspect_sources(urls or [URL], **kwargs)
        return result, mock

    def test_unchanged_blob_not_equal_commit_and_uses_default_branch(self):
        report, mock = self.run_check(self.responses(), [URL, URL], github_auth=True)
        self.assertEqual(report["api_requests"], 4)
        self.assertEqual(len(report["results"]), 1)
        item = report["results"][0]
        self.assertEqual(item["status"], "BLOB_UNCHANGED")
        self.assertEqual(item["target_ref"], "master")
        self.assertNotEqual(item["source_revision"], item["target_revision"])
        self.assertTrue(all(call.kwargs["github_auth"] for call in mock.call_args_list))

    def test_changed_blob_is_not_a_bug_or_fixed_verdict(self):
        report, _ = self.run_check(
            self.responses(
                new={"path": "src/check.py", "type": "file", "sha": "d" * 40}
            )
        )
        self.assertEqual(report["results"][0]["status"], "BLOB_CHANGED")
        self.assertIn("not fix status", report["claim_boundary"])

    def test_pinned_target_404_is_absence_not_deleted_or_no_bug(self):
        error = HTTPError(BASE, 404, "Not Found", {}, None)
        report, _ = self.run_check(self.responses(new=error))
        self.assertEqual(report["results"][0]["status"], "PATH_ABSENT_AT_TARGET")
        self.assertEqual(report["results"][0]["target_revision"], NEW)

    def test_baseline_404_or_rate_limit_remains_inconclusive(self):
        for old, new in [
            (HTTPError(BASE, 404, "Not Found", {}, None), None),
            (None, HTTPError(BASE, 403, "Forbidden", {}, None)),
            (None, TimeoutError("timeout")),
        ]:
            with self.subTest(old=old, new=new):
                report, _ = self.run_check(self.responses(old, new))
                self.assertEqual(report["results"][0]["status"], "INCONCLUSIVE")

    def test_head_failure_does_not_claim_path_absence(self):
        data = self.responses()
        data[BASE + "/commits/master"] = HTTPError(BASE, 404, "Not Found", {}, None)
        report, _ = self.run_check(data)
        self.assertEqual(report["results"][0]["status"], "INCONCLUSIVE")

    def test_rejects_private_or_wrong_repo_before_file_read(self):
        for field, value in [
            ("private", True),
            ("visibility", "private"),
            ("full_name", "other/project"),
        ]:
            data = self.responses()
            data[BASE][field] = value
            report, mock = self.run_check(data)
            self.assertEqual(report["results"][0]["status"], "INCONCLUSIVE")
            self.assertEqual(mock.call_count, 1)

    def test_path_type_and_hash_identity_must_match(self):
        for field, value in [
            ("path", "wrong.py"),
            ("type", "dir"),
            ("sha", "0" * 64),
            ("submodule_git_url", "https://example.com"),
        ]:
            old = {"path": "src/check.py", "type": "file", "sha": BLOB, field: value}
            report, _ = self.run_check(self.responses(old=old))
            self.assertEqual(report["results"][0]["status"], "INCONCLUSIVE")

    def test_untrusted_url_and_budget_rejected_before_fetch(self):
        for urls in [
            [],
            [URL] * 33,
            [URL, URL + "?token=x"],
            [URL.replace("src/check.py", "src/../check.py")],
            [URL.replace(OLD, "main")],
            [URL.replace("https:", "http:")],
            [URL.replace("raw.githubusercontent.com", "example.com")],
            [URL.replace("owner/project", "../project")],
        ]:
            with patch.object(freshness.scout, "fetch") as mock:
                with self.assertRaises(ValueError):
                    freshness.inspect_sources(urls)
                mock.assert_not_called()

    def test_explicit_release_ref_does_not_rewrite_source_revision(self):
        data = self.responses()
        data[BASE + "/commits/release%2Fv1"] = {"sha": OLD}
        report, _ = self.run_check(data, target_ref="release/v1")
        self.assertEqual(report["api_requests"], 3)
        self.assertEqual(report["results"][0]["target_revision"], OLD)
        self.assertEqual(report["results"][0]["status"], "BLOB_UNCHANGED")


if __name__ == "__main__":
    unittest.main()
