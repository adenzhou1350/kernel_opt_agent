import unittest

from scripts.scout_github_checks import observe_check_runs, observe_pull_request


SHA = "a" * 40


def check(number, status="completed", conclusion="success", **extra):
    return dict(id=number, name=f"test-{number}", head_sha=SHA,
                status=status, conclusion=conclusion, **extra)


class CheckObservationTests(unittest.TestCase):
    def observe(self, pages, **limits):
        calls = []
        def fetch(path):
            calls.append(path)
            return pages[len(calls) - 1]
        result = observe_check_runs(fetch, "owner/repo", SHA, **limits)
        return result, calls

    def test_pending_check_after_default_thirty_is_not_all_green(self):
        rows = [check(n) for n in range(41)]
        rows[40] = check(40, "in_progress", None)
        result, calls = self.observe([
            dict(total_count=41, check_runs=rows[:30]),
            dict(total_count=41, check_runs=rows[30:]),
        ], per_page=30)
        self.assertEqual(result["state"], "PENDING")
        self.assertTrue(result["complete"])
        self.assertEqual(result["pending"][0]["id"], 40)
        self.assertEqual(result["fetched_count"], 41)
        self.assertTrue(calls[-1].endswith("per_page=30&page=2"))

    def test_page_budget_does_not_hide_incomplete_acquisition(self):
        result, _ = self.observe([dict(total_count=41, check_runs=[check(n) for n in range(30)])],
                                 per_page=30, max_pages=1)
        self.assertEqual(result["state"], "INCOMPLETE")
        self.assertEqual(result["incomplete_reason"], "page_limit")

    def test_failure_in_second_page_is_not_hidden(self):
        result, _ = self.observe([
            dict(total_count=2, check_runs=[check(1)]),
            dict(total_count=2, check_runs=[check(2, conclusion="failure")]),
        ], per_page=1)
        self.assertEqual(result["state"], "FAILED")
        self.assertEqual(result["failed"][0]["id"], 2)

    def test_empty_checks_are_not_passed_ci(self):
        result, _ = self.observe([dict(total_count=0, check_runs=[])])
        self.assertEqual(result["state"], "NO_CHECKS")
        self.assertTrue(result["complete"])

    def test_success_skipped_failure_and_unknown_are_distinct(self):
        for status, conclusion, expected in [
            ("completed", "success", "ALL_OBSERVED_SUCCESS"),
            ("completed", "skipped", "COMPLETED_WITH_SKIPS_OR_NEUTRAL"),
            ("completed", "neutral", "COMPLETED_WITH_SKIPS_OR_NEUTRAL"),
            ("completed", "failure", "FAILED"),
            ("completed", None, "UNKNOWN"),
            ("completed", "new-result", "UNKNOWN"),
            ("new-status", None, "UNKNOWN"),
        ]:
            with self.subTest(status=status, conclusion=conclusion):
                result, _ = self.observe([dict(total_count=1, check_runs=[check(1, status, conclusion)])])
                self.assertEqual(result["state"], expected)

    def test_missing_pages_changed_counts_duplicates_and_wrong_head(self):
        cases = [
            ([dict(total_count=2, check_runs=[check(1)]), dict(total_count=2, check_runs=[])], "empty_page_before_total"),
            ([dict(total_count=2, check_runs=[check(1)]), dict(total_count=3, check_runs=[check(2)])], "total_count_changed"),
            ([dict(total_count=2, check_runs=[check(1)]), dict(total_count=2, check_runs=[check(1)])], "duplicate_check_id"),
            ([dict(total_count=1, check_runs=[dict(check(1), head_sha="b"*40)])], "check_head_mismatch"),
            ([dict(total_count=2, check_runs=[check(1), check(2)])], "oversized_page"),
            ([dict(total_count=0, check_runs=[check(1)])], "more_checks_than_reported"),
        ]
        for pages, reason in cases:
            with self.subTest(reason=reason):
                result, _ = self.observe(pages, per_page=1)
                self.assertEqual(result["state"], "INCOMPLETE")
                self.assertEqual(result["incomplete_reason"], reason)

    def test_head_change_during_read_invalidates_pr_observation(self):
        for changed in (False, True):
            responses = iter([dict(head=dict(sha=SHA)),
                              dict(total_count=1, check_runs=[check(1)]),
                              dict(head=dict(sha="b"*40 if changed else SHA))])
            result = observe_pull_request(lambda path: next(responses), "owner/repo", 1)
            self.assertEqual(result["head_unchanged"], not changed)
            self.assertEqual(result["state"], "INCOMPLETE" if changed else "ALL_OBSERVED_SUCCESS")

    def test_malformed_responses_and_transport_failure_are_not_success(self):
        for value in ([], {}, dict(total_count=True, check_runs=[]),
                      dict(total_count=-1, check_runs=[]),
                      dict(total_count=1, check_runs=[dict(id=True)])):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.observe([value])
        def broken(path):
            raise TimeoutError("transport failed")
        with self.assertRaises(TimeoutError):
            observe_check_runs(broken, "owner/repo", SHA)

    def test_input_validation_precedes_transport(self):
        def forbidden(path):
            self.fail("transport must not be called")
        for repo, sha, options in [
            ("../repo", SHA, {}), ("owner/repo", "main", {}),
            ("owner/..", SHA, {}), ("./repo", SHA, {}),
            (None, SHA, {}), ("owner/repo", None, {}),
            ("owner/repo", SHA, dict(per_page=True)),
            ("owner/repo", SHA, dict(per_page=101)),
            ("owner/repo", SHA, dict(max_pages=0)),
        ]:
            with self.subTest(repo=repo, options=options), self.assertRaises(ValueError):
                observe_check_runs(forbidden, repo, sha, **options)
        for repo in ("../repo", "owner/..", None):
            with self.subTest(repo=repo), self.assertRaises(ValueError):
                observe_pull_request(forbidden, repo, 1)


if __name__ == "__main__":
    unittest.main()
