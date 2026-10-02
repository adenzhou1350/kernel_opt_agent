import json
import unittest

from scripts.scout_review_citations import (
    citation_view,
    numbered_citation_view,
    resolve_review,
)


class ReviewCitationTests(unittest.TestCase):
    def setUp(self):
        self.view = citation_view(
            [
                {
                    "url": "https://example.org/source",
                    "text": '315: a = "x"\r\n316: b = "\\n"\r317: 判断 = "\u2028"',
                }
            ]
        )
        self.review = {
            "decision": "SUPPORTED_STATIC_DEFECT",
            "reason": "A hypothesis, not verified here.",
            "citations": [{"evidence_id": "s0", "first_row": 1, "last_row": 2}],
            "next_verification": "Run native tests.",
        }

    def resolve(self):
        return resolve_review(json.dumps(self.review), self.view)

    def test_controller_extracts_escaped_numbered_text_exactly(self):
        result = self.resolve()
        self.assertTrue(result["valid"])
        self.assertEqual(
            result["resolved_citations"][0]["quote"], '315: a = "x"\n316: b = "\\n"'
        )
        self.assertEqual(len(self.view[0]["rows"]), 3)
        self.assertIn("\u2028", self.view[0]["rows"][2])

    def test_identical_urls_have_distinct_excerpt_ids(self):
        view = citation_view(
            [{"url": "same", "text": "a"}, {"url": "same", "text": "b"}]
        )
        self.review["citations"][0] = {
            "evidence_id": "s1",
            "first_row": 1,
            "last_row": 1,
        }
        result = resolve_review(json.dumps(self.review), view)
        self.assertEqual(result["resolved_citations"][0]["quote"], "b")

    def test_empty_catalog_entry_cannot_be_cited(self):
        self.view = citation_view([{"url": "catalog", "text": ""}])
        self.assertFalse(self.resolve()["valid"])

    def test_unknown_or_duplicate_id_cannot_be_repaired(self):
        self.review["citations"][0]["evidence_id"] = "s99"
        self.assertEqual(self.resolve()["error"], "UNKNOWN_OR_AMBIGUOUS_EVIDENCE")
        self.review["citations"][0]["evidence_id"] = "s0"
        self.view.append(self.view[0])
        self.assertFalse(self.resolve()["valid"])

    def test_range_types_order_bounds_and_budget(self):
        for first, last in ((True, 1), (1, False), (0, 1), (2, 1), (1, 4), ("1", 2)):
            with self.subTest(first=first, last=last):
                self.review["citations"][0].update(first_row=first, last_row=last)
                self.assertFalse(self.resolve()["valid"])
        view = citation_view([{"url": "a", "text": "\n".join("x" for _ in range(9))}])
        self.review["citations"][0].update(first_row=1, last_row=9)
        self.assertFalse(resolve_review(json.dumps(self.review), view)["valid"])

    def test_no_invented_quote_url_or_extra_fields(self):
        self.review["citations"][0]["quote"] = "invented"
        self.assertEqual(self.resolve()["error"], "INVALID_CITATION")

    def test_blank_oversize_and_duplicate_citations_fail(self):
        for text in ("   ", "x" * 1401):
            view = citation_view([{"url": "a", "text": text}])
            self.review["citations"][0]["last_row"] = 1
            self.assertFalse(resolve_review(json.dumps(self.review), view)["valid"])
        self.review["citations"].append(dict(self.review["citations"][0]))
        self.assertEqual(self.resolve()["error"], "DUPLICATE_CITATION")

    def test_insufficient_can_abstain_but_decisive_needs_citation(self):
        self.review["citations"] = []
        self.assertFalse(self.resolve()["valid"])
        self.review["decision"] = "INSUFFICIENT"
        self.assertTrue(self.resolve()["valid"])

    def test_output_not_semantic_truth(self):
        # A locatable citation still requires independent semantic adjudication.
        self.review["reason"] = (
            "This plainly false assertion is not checked by this interface."
        )
        self.assertTrue(self.resolve()["valid"])

    def test_numbered_prompt_rows_preserve_exact_citation_identity(self):
        sources = [{"url": "same", "text": '315: x="\\n"\r\n900: 第二行'}]
        original = json.loads(json.dumps(sources))
        numbered = numbered_citation_view(sources)
        plain = citation_view(sources)
        self.assertEqual(sources, original)
        self.assertEqual(
            numbered[0]["rows"],
            [
                {"row": 1, "text": '315: x="\\n"'},
                {"row": 2, "text": "900: 第二行"},
            ],
        )
        self.assertEqual(numbered[0]["display_sha256"], plain[0]["display_sha256"])
        result = resolve_review(json.dumps(self.review), plain)
        self.assertTrue(result["valid"])
        self.assertEqual(
            result["resolved_citations"][0]["quote"], '315: x="\\n"\n900: 第二行'
        )

    def test_numbered_prompt_empty_and_identical_urls_are_unambiguous(self):
        result = numbered_citation_view(
            [
                {"url": "same", "text": ""},
                {"url": "same", "text": "x\n"},
            ]
        )
        self.assertEqual(result[0]["rows"], [])
        self.assertEqual(result[1]["evidence_id"], "s1")
        self.assertEqual(
            result[1]["rows"],
            [
                {"row": 1, "text": "x"},
                {"row": 2, "text": ""},
            ],
        )

    def test_bounded_input_and_output(self):
        for sources in (
            [{}],
            [{"url": "", "text": "a"}],
            [{"url": "a", "text": "x" * 10001}],
            [{"url": "a", "text": "x" * 10000}] * 3,
            [{"url": "a", "text": ""}] * 26,
        ):
            with self.assertRaises(ValueError):
                citation_view(sources)
        self.review["reason"] = "x" * 601
        self.assertFalse(self.resolve()["valid"])
        for text in ("not JSON", "null", "[]"):
            self.assertFalse(resolve_review(text, self.view)["valid"])
        self.review["decision"] = []
        self.assertFalse(self.resolve()["valid"])


if __name__ == "__main__":
    unittest.main()
