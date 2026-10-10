"""Synthetic policy mechanics; exposed development cases are not fresh wins."""
import copy
import io
import unittest
from unittest.mock import Mock

from scripts.scout_acquisition_choice import (
    first_clipped_or_continuation,
    first_visible_frontier_or_continuation,
    observe_choice,
)
from scripts.scout_evidence_acquisition import AcquisitionSession

URL = "https://raw.githubusercontent.com/example/project/" + "a" * 40 + "/main.py"


def view(**updates):
    return {"repo": "example/project", "sources": [{"url": URL,
        "start_line": 11, "end_line": 130, "clipped": True,
        "text": "11: first\n12: incomplete", **updates}]}


class Response(io.BytesIO):
    headers = {}

    def getcode(self):
        return 200


class VisibleFrontierTests(unittest.TestCase):
    def test_one_window_reaches_beyond_reread_prefix_without_more_gets(self):
        lines = [f"row_{i}()" for i in range(1, 151)]
        lines[120] = "contract_guard()"
        text = "\n".join(f"{i}: {lines[i - 1]}" for i in range(11, 51))[:-2]
        data = view(text=text)
        before = copy.deepcopy(data)
        opener = Mock()
        opener.open.return_value = Response("\n".join(lines).encode())
        session = AcquisitionSession(opener=opener)
        old = observe_choice(data, first_clipped_or_continuation(data), session)
        new = observe_choice(data, first_visible_frontier_or_continuation(data), session)
        self.assertNotIn("contract_guard()", old["window"]["text"])
        self.assertIn("contract_guard()", new["window"]["text"])
        self.assertEqual(new["window"]["start_line"], 50)
        self.assertEqual(new["window"]["end_line"], 129)
        self.assertEqual(session.costs()["logical_gets"], 2)  # One per policy.
        self.assertEqual(session.costs()["actual_gets"], 1)  # Shared test cache.
        self.assertEqual(data, before)

    def test_complete_row_advances_partial_row_is_repeated(self):
        for ending, expected in (("", 12), ("\n", 13), ("\r\n", 13)):
            with self.subTest(ending=ending):
                self.assertEqual(first_visible_frontier_or_continuation(
                    view(text="11: first\n12: second" + ending))["start_line"], expected)

    def test_ambiguous_labels_or_missing_ranges_fall_back_without_guessing(self):
        for changes in ({"text": ""}, {"text": "plain code"},
                        {"text": "12: wrong start"}, {"text": "11: x\n13: gap"},
                        {"text": "11: x\n12"}, {"text": "011: x"},
                        {"text": "11: x\n12: outside", "end_line": 11},
                        {"start_line": None}, {"end_line": None}):
            with self.subTest(changes=changes):
                data = view(**changes)
                self.assertEqual(first_visible_frontier_or_continuation(data),
                                 first_clipped_or_continuation(data))

    def test_complete_and_duplicate_entries_preserve_original_selection(self):
        data = view(clipped=False)
        data["sources"].append(view()["sources"][0])
        self.assertEqual(first_visible_frontier_or_continuation(data)["start_line"], 131)
        self.assertEqual(first_clipped_or_continuation(view())["start_line"], 11)

    def test_safety_validation_is_inherited_and_malformed_text_is_explicit(self):
        for url in (URL.replace("a" * 40, "main"), URL + "?secret=x",
                    URL.replace("example/project", "other/project")):
            self.assertEqual(first_visible_frontier_or_continuation(view(url=url))["status"],
                             "UNAVAILABLE")
        with self.assertRaises(ValueError):
            first_visible_frontier_or_continuation(view(text=[]))
        with self.assertRaises(ValueError):
            first_visible_frontier_or_continuation(view(start_line=True))


if __name__ == "__main__":
    unittest.main()
