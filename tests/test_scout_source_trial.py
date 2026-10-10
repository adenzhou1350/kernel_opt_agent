"""Composed offline flow tests, not provider-quality or native-utility evidence."""

import copy
import io
import unittest
import urllib.error
from unittest.mock import Mock

from scripts.scout_evidence_acquisition import AcquisitionSession
from scripts.scout_pending_cohort import compact_acquisition_view
from scripts.scout_source_trial import ARMS, run_case

URL = "https://raw.githubusercontent.com/example/project/" + "a" * 40 + "/src/main.py"


class Response(io.BytesIO):
    headers = {}

    def getcode(self):
        return 200


def view(url=URL, end=80):
    return compact_acquisition_view({"repo": "example/project", "question": "review",
        "sources": [{"url": url, "text": "line", "end_line": end}]})


class SourceTrialTests(unittest.TestCase):
    def setUp(self):
        self.opener = Mock()
        self.opener.open.side_effect = lambda *a, **k: Response(
            "\n".join(f"line {i}" for i in range(1, 301)).encode()
        )
        self.session = AcquisitionSession(opener=self.opener)
        self.selector = Mock(return_value={"url": URL, "start_line": 181,
                                           "reason": "private selector rationale"})
        self.reviews = []

        def reviewer(original, additional):
            self.reviews.append((copy.deepcopy(original), additional))
            return {"unverified": True}

        self.reviewer = Mock(side_effect=reviewer)

    def run_case(self, original=None, **kwargs):
        return run_case(view() if original is None else original,
                        selector=self.selector, reviewer=self.reviewer,
                        session=self.session, **kwargs)

    def test_issue_only_is_retained_without_callbacks_or_acquisition(self):
        for sources in ([], [{"url": "https://github.com/example/project/issues/1",
                             "text": "unverified issue"}]):
            original = compact_acquisition_view({"repo": "example/project", "sources": sources})
            result = self.run_case(original)
            self.assertEqual(result["status"], "UNAVAILABLE_ACTION_SPACE")
            self.assertEqual([r["arm"] for r in result["arms"]], list(ARMS))
            self.assertTrue(all(r["status"] == "UNAVAILABLE_ACTION_SPACE" for r in result["arms"]))
        self.selector.assert_not_called()
        self.reviewer.assert_not_called()
        self.opener.open.assert_not_called()
        self.assertEqual(self.session.costs()["actual_gets"], 0)

    def test_composed_success_keeps_blind_reviews_and_shared_cache_costs(self):
        original = view()
        saved = copy.deepcopy(original)
        result = self.run_case(original)
        self.assertEqual(result["selection_status"], "SELECTED")
        self.assertEqual([r["arm"] for r in result["arms"]], list(ARMS))
        self.assertIsNone(self.reviews[0][1])
        self.assertEqual(self.reviews[1][1]["start_line"], 81)
        self.assertEqual(self.reviews[2][1]["start_line"], 181)
        for _, evidence in self.reviews[1:]:
            self.assertLessEqual(len(evidence["text"]), 4500)
            self.assertLessEqual(len(evidence["text"].splitlines()), 80)
        for review_view, evidence in self.reviews:
            self.assertEqual(review_view, saved)
            self.assertNotIn("private selector rationale", str(evidence))
        self.assertEqual(original, saved)
        self.assertEqual(result["session_costs"]["logical_gets"], 2)
        self.assertEqual(result["session_costs"]["actual_gets"], 1)
        self.opener.open.assert_called_once()
        self.selector.assert_called_once()
        self.assertEqual(self.reviewer.call_count, 3)

    def test_reused_session_reports_cumulative_not_per_case_cost(self):
        first = self.run_case()
        second = self.run_case()
        self.assertEqual(first["session_costs"]["logical_gets"], 2)
        self.assertEqual(second["session_costs"]["logical_gets"], 4)
        self.assertEqual(second["session_costs"]["actual_gets"], 1)
        self.opener.open.assert_called_once()

    def test_eof_retains_failure_without_replacing_window(self):
        self.selector.return_value["start_line"] = 900
        result = self.run_case(view(end=300))
        for record in result["arms"][1:]:
            self.assertEqual(record["acquisition"]["acquisition"]["status"], "FETCHED")
            self.assertEqual(record["acquisition"]["window"]["error_kind"], "WINDOW_BEYOND_SOURCE")
        self.assertEqual(result["session_costs"]["actual_gets"], 1)
        self.assertTrue(all(r[1]["status"] == "FAILED" for r in self.reviews[1:]))

    def test_abstention_and_invalid_choices_are_distinct_and_never_repaired(self):
        choices = [
            ({"url": None, "start_line": None, "reason": "no useful catalog action"}, "ABSTAINED"),
            (None, "INVALID_SELECTION"),
            ({"url": URL, "start_line": True, "reason": "bad"}, "INVALID_SELECTION"),
            ({"url": URL.replace("/src/", "/other/"), "start_line": 1, "reason": "invented"}, "INVALID_SELECTION"),
            ({"url": URL, "start_line": None, "reason": "partial abstention"}, "INVALID_SELECTION"),
            ({"url": [], "start_line": 1, "reason": "bad"}, "INVALID_SELECTION"),
        ]
        for choice, status in choices:
            with self.subTest(choice=choice):
                self.selector.return_value = choice
                result = self.run_case()
                self.assertEqual(result["selection_status"], status)
                self.assertIsNone(result["arms"][2]["acquisition"])
                self.assertEqual(self.session.requests[-1]["url"], URL)
        self.assertEqual(self.selector.call_count, len(choices))

    def test_transport_failure_is_cached_visible_and_not_source_text(self):
        self.opener.open.side_effect = urllib.error.HTTPError(
            URL, 404, "missing", {}, io.BytesIO(b"not source")
        )
        result = self.run_case()
        for record in result["arms"][1:]:
            self.assertEqual(record["acquisition"]["acquisition"]["status"], "FAILED")
            self.assertNotIn("text", record["acquisition"]["window"])
        self.assertEqual(result["session_costs"]["actual_gets"], 1)
        self.opener.open.assert_called_once()

    def test_callback_failures_are_not_retried_or_echoed(self):
        self.selector.side_effect = RuntimeError("credential-like private detail")
        self.reviewer.side_effect = TimeoutError("private provider diagnostic")
        result = self.run_case()
        self.assertEqual(result["selection_status"], "CALL_FAILED")
        self.assertEqual(result["selection"]["error_kind"], "RuntimeError")
        self.assertTrue(all(r["review"]["status"] == "CALL_FAILED" for r in result["arms"]))
        self.assertNotIn("private", str(result))
        self.selector.assert_called_once()
        self.assertEqual(self.reviewer.call_count, 3)

    def test_session_failure_retains_all_arms_without_retry_or_fake_cost(self):
        session = Mock()
        session.acquire_window.side_effect = ValueError("private session diagnostic")
        session.costs.return_value = {"unmeasured": ["failed session attempts"]}
        result = run_case(view(), selector=self.selector, reviewer=self.reviewer,
                          session=session)
        self.assertEqual(len(result["arms"]), 3)
        self.assertEqual(session.acquire_window.call_count, 2)
        self.assertEqual(self.reviewer.call_count, 3)
        for record in result["arms"][1:]:
            acquired = record["acquisition"]
            self.assertEqual(acquired["acquisition"]["cost_scope"],
                             "SESSION_FAILURE_COST_MAY_BE_INCOMPLETE")
            self.assertEqual(acquired["window"]["error_kind"], "SESSION_FAILURE")
        self.assertNotIn("private session diagnostic", str(result))

    def test_user_interrupt_is_not_reclassified_as_provider_failure(self):
        self.selector.side_effect = KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.run_case()
        self.reviewer.assert_not_called()
        self.opener.open.assert_not_called()

    def test_rule_uses_first_pinned_catalog_entry_and_missing_range_starts_at_one(self):
        original = view(end=None)
        issue = view(url="https://github.com/example/project/issues/1")["sources"][0]
        original["sources"].insert(0, issue)
        result = self.run_case(original)
        self.assertEqual(result["arms"][1]["choice"], {"url": URL, "start_line": 1})
        self.assertEqual(result["arms"][2]["choice"]["start_line"], 181)

    def test_review_record_is_opaque_not_a_quality_label(self):
        self.reviewer.side_effect = None
        self.reviewer.return_value = {"status": "unsupported", "usage": {"tokens": 23}}
        result = self.run_case()
        for record in result["arms"]:
            self.assertEqual(record["review"]["status"], "RETURNED")
            self.assertEqual(record["review"]["record"]["status"], "unsupported")
            self.assertEqual(record["review"]["record"]["usage"]["tokens"], 23)
            self.assertNotIn("qualified", record)

    def test_callback_mutation_cannot_change_later_arms_or_catalog(self):
        original = view()
        saved = copy.deepcopy(original)

        def mutate_selector(value):
            value["sources"].clear()
            return {"url": URL, "start_line": 181, "reason": "test"}

        def mutate_reviewer(value, evidence):
            self.assertEqual(value, saved)
            value["sources"].clear()

        self.selector.side_effect = mutate_selector
        self.reviewer.side_effect = mutate_reviewer
        result = self.run_case(original, arm_order=list(reversed(ARMS)))
        self.assertEqual(result["selection_status"], "SELECTED")
        self.assertEqual([r["arm"] for r in result["arms"]], list(reversed(ARMS)))
        self.assertEqual(original, saved)

    def test_invalid_order_or_outcome_contaminated_view_fails_before_calls(self):
        for order in ([], [ARMS[0]] * 3, [*ARMS, ARMS[0]]):
            with self.assertRaises(ValueError):
                self.run_case(arm_order=order)
        original = view()
        original["result"] = {"qualified": True}
        with self.assertRaises(ValueError):
            self.run_case(original)
        self.selector.assert_not_called()
        self.reviewer.assert_not_called()
        self.opener.open.assert_not_called()

    def test_malformed_or_oversized_catalog_fails_before_calls(self):
        bad_views = []
        for bad_source in (None, {}, {**view()["sources"][0], "outcome": True},
                           {**view()["sources"][0], "end_line": True}):
            original = view()
            original["sources"] = [bad_source]
            bad_views.append(original)
        original = view()
        original["question"] = "x" * 6501
        bad_views.append(original)
        for original in bad_views:
            with self.subTest(original=original), self.assertRaises(ValueError):
                self.run_case(original)
        self.selector.assert_not_called()
        self.reviewer.assert_not_called()
        self.opener.open.assert_not_called()


if __name__ == "__main__":
    unittest.main()
