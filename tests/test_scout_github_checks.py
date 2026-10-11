import unittest

from scripts.scout_github_checks import (
    observe_check_runs, observe_failed_job_steps, observe_pull_request,
)


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


class JobStepObservationTests(unittest.TestCase):
    def setUp(self):
        self.check = check(10, conclusion="failure", details_url=
                           "https://github.com/owner/repo/actions/runs/20/job/30")
        self.job = dict(id=30, run_id=20, head_sha=SHA,
                        url="https://api.github.com/repos/owner/repo/actions/jobs/30",
                        run_url="https://api.github.com/repos/owner/repo/actions/runs/20",
                        check_run_url="https://api.github.com/repos/owner/repo/check-runs/10",
                        status="completed", conclusion="failure", steps=[
                            dict(number=1, name="Test with pytest", status="completed",
                                 conclusion="success"),
                            dict(number=2, name="Upload Coverage", status="completed",
                                 conclusion="failure"),
                        ])
        self.calls = []

    def fetch(self, path):
        self.calls.append(path)
        return self.job

    def observe(self, check_value=None):
        return observe_failed_job_steps(self.fetch, "owner/repo", SHA,
                                        self.check if check_value is None else check_value)

    def test_failed_upload_does_not_relabel_the_job_or_check_as_passing(self):
        result = self.observe()
        self.assertEqual(self.calls, ["repos/owner/repo/actions/jobs/30"])
        self.assertEqual(result["state"], "OBSERVED_JOB_STEPS")
        self.assertEqual(result["job_conclusion"], "failure")
        self.assertEqual([step["conclusion"] for step in result["steps"]],
                         ["success", "failure"])
        self.assertEqual(self.check["conclusion"], "failure")
        # Names alone must not become a test-quality or infrastructure classifier.
        self.assertNotIn("tests_passed", result)
        self.assertNotIn("recommended_action", result)

    def test_only_an_exact_local_failed_actions_handle_makes_a_request(self):
        for updates in (
            dict(status="in_progress", conclusion=None), dict(conclusion="success"),
            dict(details_url=None), dict(details_url="https://other.invalid/job/30"),
            dict(details_url=self.check["details_url"].replace("owner/repo", "other/repo")),
            dict(details_url=self.check["details_url"] + "?x=1"),
            dict(details_url=self.check["details_url"].replace("/30", "/030")),
        ):
            with self.subTest(updates=updates):
                result = self.observe({**self.check, **updates})
                self.assertEqual(result["state"], "UNAVAILABLE")
        self.assertEqual(self.calls, [])

    def test_job_run_repository_check_and_source_identity_are_all_bound(self):
        for key, value in (
            ("id", True), ("id", 31), ("run_id", True), ("run_id", 21),
            ("head_sha", "b" * 40), ("url", "https://other.invalid/30"),
            ("run_url", "https://api.github.com/repos/other/repo/actions/runs/20"),
            ("check_run_url", "https://api.github.com/repos/owner/repo/check-runs/11"),
        ):
            saved = self.job[key]
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.job[key] = value
                self.observe()
            self.job[key] = saved

    def test_missing_oversized_duplicate_and_malformed_steps_fail(self):
        row = self.job["steps"][0]
        for steps in (None, [row] * 201, [row, row], [None],
                      [{**row, "number": True}], [{**row, "name": "x" * 2001}],
                      [{**row, "status": None}], [{**row, "conclusion": 1}]):
            with self.subTest(steps_type=type(steps).__name__), self.assertRaises(ValueError):
                self.job["steps"] = steps
                self.observe()

    def test_job_outcomes_are_typed_but_not_inferred_from_previous_check_state(self):
        for key, value in (("status", []), ("conclusion", {})):
            saved = self.job[key]
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.job[key] = value
                self.observe()
            self.job[key] = saved
        self.job["status"], self.job["conclusion"] = "in_progress", None
        result = self.observe()
        self.assertEqual(result["job_status"], "in_progress")
        self.assertIsNone(result["job_conclusion"])
        self.assertEqual(self.check["conclusion"], "failure")

    def test_unknown_or_empty_steps_are_observations_not_a_pass(self):
        for steps in ([], [dict(number=1, name="untrusted label", status="new-status",
                               conclusion="new-conclusion")]):
            self.job["steps"] = steps
            result = self.observe()
            self.assertEqual(result["state"], "OBSERVED_JOB_STEPS")
            self.assertEqual(result["steps"], steps)
            self.assertEqual(result["job_conclusion"], "failure")

    def test_invalid_inputs_and_transport_errors_are_not_empty_successes(self):
        for repo, sha, row in (("../repo", SHA, self.check), ("owner/repo", "main", self.check),
                              ("owner/repo", SHA, {}), ("owner/repo", SHA, dict(id=True))):
            with self.subTest(repo=repo), self.assertRaises(ValueError):
                observe_failed_job_steps(self.fetch, repo, sha, row)
        self.assertEqual(self.calls, [])
        def broken(path):
            raise TimeoutError("not free or successful evidence")
        with self.assertRaises(TimeoutError):
            observe_failed_job_steps(broken, "owner/repo", SHA, self.check)

    def test_check_observation_preserves_the_details_handle(self):
        result = observe_check_runs(
            lambda path: dict(total_count=1, check_runs=[self.check]), "owner/repo", SHA)
        self.assertEqual(result["failed"][0]["details_url"], self.check["details_url"])


if __name__ == "__main__":
    unittest.main()
