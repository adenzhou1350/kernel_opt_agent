"""Offline adapter checks, not acquisition-policy or reviewer-quality results."""

import copy
import io
import unittest
import urllib.error
from unittest.mock import Mock

from scripts.scout_acquisition_choice import (
    acquisition_catalog,
    first_catalog_continuation,
    first_clipped_or_continuation,
    observe_choice,
    validate_selection,
)
from scripts.scout_evidence_acquisition import AcquisitionSession
from scripts.scout_pending_cohort import compact_acquisition_view

URL = "https://raw.githubusercontent.com/example/project/" + "a" * 40 + "/main.py"


def view(*sources):
    return {"repo": "example/project", "sources": list(sources)}


def selected(url=URL, start_line=1):
    return {"url": url, "start_line": start_line, "reason": "Missing caller"}


class Response(io.BytesIO):
    headers = {}

    def getcode(self):
        return 200


class AcquisitionChoiceTests(unittest.TestCase):
    def test_restore_clipped_view_reaches_omitted_source_before_original_end(self):
        body = "\n".join(["# preamble " + "x" * 60] * 30 + ["implementation()"])
        data = compact_acquisition_view({
            "repo": "example/project",
            "sources": [{"url": URL, "text": body, "start_line": 1, "end_line": 31}],
        })
        before = copy.deepcopy(data)
        self.assertTrue(data["sources"][0]["clipped"])
        self.assertNotIn("implementation()", data["sources"][0]["text"])
        opener = Mock()
        opener.open.return_value = Response(body.encode())
        session = AcquisitionSession(opener=opener)
        old = observe_choice(data, first_catalog_continuation(data), session)
        self.assertEqual(old["window"]["error_kind"], "WINDOW_BEYOND_SOURCE")
        result = observe_choice(data, first_clipped_or_continuation(data), session)
        self.assertEqual(result["status"], "ACQUIRED")
        self.assertIn("implementation()", result["window"]["text"])
        self.assertEqual(session.costs()["logical_gets"], 2)
        self.assertEqual(session.costs()["actual_gets"], 1)
        self.assertEqual(data, before)

    def test_restore_first_clipped_file_including_catalog_only_entries(self):
        other = URL.replace("main.py", "other.ts")
        data = view({"url": URL, "end_line": 4, "clipped": False},
                    {"url": other, "start_line": 42, "end_line": 121,
                     "clipped": True, "text": ""})
        self.assertEqual(first_clipped_or_continuation(data),
                         {"status": "SELECTED", "url": other, "start_line": 42})
        data["sources"][1]["start_line"] = None
        self.assertEqual(first_clipped_or_continuation(data)["start_line"], 1)

    def test_restore_preserves_first_duplicate_entry_and_complete_continuation(self):
        for clipped in (False, True):
            data = view({"url": URL, "start_line": 5, "end_line": 10,
                         "clipped": clipped},
                        {"url": URL, "start_line": 100, "end_line": 200,
                         "clipped": True})
            choice = first_clipped_or_continuation(data)
            self.assertEqual(choice["start_line"], 5 if clipped else 11)
            self.assertEqual(first_catalog_continuation(data)["start_line"], 11)

    def test_restore_does_not_select_unsafe_foreign_or_unpinned_clipped_files(self):
        for url in (None, [], URL.replace("a" * 40, "main"), URL + "?hidden=yes",
                    URL.replace("example/project", "other/project"),
                    "https://github.com/example/project/issues/1"):
            data = view({"url": url, "clipped": True}, {"url": URL, "end_line": 2})
            self.assertEqual(first_clipped_or_continuation(data),
                             first_catalog_continuation(data))
        for data in (view(), view({"url": "https://github.com/example/project/issues/1"})):
            self.assertEqual(first_clipped_or_continuation(data)["status"], "UNAVAILABLE")

    def test_restore_rejects_malformed_clipping_and_original_ranges(self):
        for metadata in ({"clipped": "true"}, {"clipped": 1},
                         {"clipped": True, "start_line": True},
                         {"clipped": True, "start_line": 0},
                         {"clipped": True, "start_line": 1.5},
                         {"clipped": True, "start_line": 10, "end_line": 9}):
            with self.subTest(metadata=metadata), self.assertRaises(ValueError):
                first_clipped_or_continuation(view({"url": URL, **metadata}))

    def test_restore_does_not_expand_window_budget_to_reach_omitted_text(self):
        body = ("line\n" * 100 + "implementation()\n").encode()
        opener = Mock()
        opener.open.return_value = Response(body)
        session = AcquisitionSession(opener=opener)
        data = view({"url": URL, "start_line": 1, "end_line": 101, "clipped": True})
        result = observe_choice(data, first_clipped_or_continuation(data), session)
        self.assertEqual(result["status"], "ACQUIRED")
        self.assertEqual(result["window"]["end_line"], 80)
        self.assertNotIn("implementation()", result["window"]["text"])
        self.assertEqual(session.costs()["logical_gets"], 1)

    def test_empty_and_issue_only_catalogs_do_not_assert_or_fetch(self):
        for data in (view(), view({"url": "https://github.com/example/project/issues/1"})):
            session = Mock()
            choice = first_catalog_continuation(data)
            self.assertEqual(choice["status"], "UNAVAILABLE")
            self.assertEqual(validate_selection(data, None)["status"], "UNAVAILABLE")
            self.assertEqual(observe_choice(data, choice, session)["status"], "UNAVAILABLE")
            session.acquire_window.assert_not_called()

    def test_only_pinned_same_repository_sources_are_eligible(self):
        data = view({"url": URL.replace("example/project", "other/project")},
                    {"url": URL.replace("a" * 40, "main")},
                    {"url": URL + "?token=hidden"}, {"url": URL, "end_line": 10},
                    {"url": URL, "end_line": 100})
        before = copy.deepcopy(data)
        self.assertEqual(acquisition_catalog(data), [{"url": URL, "start_line": 11}])
        self.assertEqual(data, before)

    def test_explicit_abstention_is_distinct_from_invalid_model_output(self):
        data = view({"url": URL})
        abstain = {"url": None, "start_line": None, "reason": "Already supplied"}
        self.assertEqual(validate_selection(data, abstain)["status"], "ABSTAIN")
        for invalid in (None, {}, {**selected(), "extra": True},
                        {**selected(), "reason": "x" * 601},
                        {**selected(), "reason": None}, selected(start_line=True),
                        selected(start_line=0), selected(start_line=1.5),
                        selected(url=None), {**abstain, "start_line": 1},
                        selected(url=URL.replace("a" * 40, "b" * 40))):
            with self.subTest(invalid=invalid):
                choice = validate_selection(data, invalid)
                self.assertEqual(choice["status"], "INVALID_SELECTION")
                session = Mock()
                observe_choice(data, choice, session)
                session.acquire_window.assert_not_called()

    def test_nonselected_choices_never_spend_a_get(self):
        session = Mock()
        for status in ("NO_ADDITIONAL_SOURCE", "ABSTAIN", "INVALID_SELECTION", "UNAVAILABLE"):
            observe_choice(view({"url": URL}), {"status": status}, session)
        session.acquire_window.assert_not_called()

    def test_real_composed_adapter_delivers_text_and_preserves_cache_costs(self):
        opener = Mock()
        opener.open.return_value = Response(b"first\ncaller()\nlast\n")
        session = AcquisitionSession(opener=opener)
        data = view({"url": URL, "end_line": 1})
        choice = first_catalog_continuation(data)
        for _ in range(2):
            result = observe_choice(data, choice, session)
            self.assertEqual(result["status"], "ACQUIRED")
            self.assertIn("caller()", result["window"]["text"])
            self.assertNotIn("first", result["window"]["text"])
        self.assertEqual(session.costs()["actual_gets"], 1)
        self.assertEqual(session.costs()["logical_gets"], 2)
        opener.open.assert_called_once()

    def test_eof_is_retained_without_a_fallback_target(self):
        opener = Mock()
        opener.open.return_value = Response(b"one\n")
        session = AcquisitionSession(opener=opener)
        data = view({"url": URL, "end_line": 100})
        result = observe_choice(data, first_catalog_continuation(data), session)
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(result["acquisition"]["status"], "FETCHED")
        self.assertEqual(result["window"]["error_kind"], "WINDOW_BEYOND_SOURCE")
        self.assertEqual(session.costs()["actual_gets"], 1)

    def test_http_failure_and_its_cost_do_not_become_empty_catalog(self):
        opener = Mock()
        opener.open.side_effect = urllib.error.HTTPError(URL, 404, "missing", {}, io.BytesIO(b"no"))
        session = AcquisitionSession(opener=opener)
        data = view({"url": URL})
        result = observe_choice(data, first_catalog_continuation(data), session)
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(result["acquisition"]["http_status"], 404)
        self.assertNotIn("text", result["window"])
        self.assertEqual(session.costs()["actual_body_bytes_observed"], 2)

    def test_invalid_selected_target_is_rejected_before_transport(self):
        session = Mock()
        for choice in ({"status": "invented"},
                       {"status": "SELECTED", **selected(URL.replace("a" * 40, "b" * 40))}):
            with self.assertRaises(ValueError):
                observe_choice(view({"url": URL}), choice, session)
        session.acquire_window.assert_not_called()

    def test_invalid_catalog_and_controller_budget_errors_still_raise(self):
        for data in (None, view(*([{"url": URL}] * 25)), view(None),
                     view({"url": URL, "end_line": True})):
            with self.assertRaises(ValueError):
                acquisition_catalog(data)
        data = view({"url": URL})
        session = Mock()
        session.acquire_window.side_effect = ValueError("session request budget exhausted")
        with self.assertRaisesRegex(ValueError, "budget exhausted"):
            observe_choice(data, first_catalog_continuation(data), session)


if __name__ == "__main__":
    unittest.main()
