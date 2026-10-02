import copy
import json
import unittest

from scripts.scout_pending_cohort import compact_acquisition_view


RAW = "https://raw.githubusercontent.com/example/project/" + "a" * 40 + "/"


def packet():
    return {
        "repo": "example/project",
        "question": "inspect update report",
        "untrusted_prior_analysis": json.dumps(
            {"hypothesis": "unverified", "next_check": "read consumer"}
        ),
        "research": {"root_job_id": "private-lineage"},
        "sources": [
            {
                "url": "https://github.com/example/project/issues/1",
                "text": "issue" * 500,
            },
            {
                "url": "https://github.com/example/project/issues/1#issuecomment-2",
                "text": "comment",
            },
            {
                "url": RAW + "launcher.mjs",
                "text": "launcher\n" * 300,
                "start_line": 2,
                "end_line": 301,
            },
            {
                "url": RAW + "src/report.test.ts",
                "text": "report consumer\n" * 300,
                "start_line": 1,
                "end_line": 300,
            },
        ],
    }


class AcquisitionViewTests(unittest.TestCase):
    def test_code_after_issues_remains_visible_with_complete_bounded_catalog(self):
        p = packet()
        original = copy.deepcopy(p)
        view = compact_acquisition_view(p)
        self.assertEqual(p, original)
        self.assertEqual(len(view["sources"]), 4)
        self.assertTrue(view["sources"][3]["text"].startswith("report consumer"))
        self.assertEqual(view["sources"][3]["original_index"], 3)
        self.assertEqual(view["sources"][2]["end_line"], 301)
        self.assertTrue(view["sources"][2]["clipped"])
        self.assertNotIn("private-lineage", json.dumps(view))

    def test_escaped_content_respects_serialized_budget_without_broken_json(self):
        p = packet()
        for s in p["sources"]:
            s["text"] = '\\"\n' * 5000
        p["untrusted_prior_analysis"] = json.dumps(
            {"hypothesis": '"' * 800, "next_check": "\\" * 500}
        )
        view = compact_acquisition_view(p)
        body = json.dumps(view, ensure_ascii=False, sort_keys=True)
        self.assertLessEqual(len(body), 6500)
        self.assertEqual(json.loads(body), view)
        self.assertTrue(view["sources"][2]["clipped"])

    def test_order_is_stable_and_catalog_omissions_are_explicit(self):
        p = packet()
        p["sources"] = [{"url": RAW + str(i), "text": str(i)} for i in range(26)]
        view = compact_acquisition_view(p)
        self.assertEqual(view["catalog_omitted"], 2)
        self.assertEqual(
            [s["original_index"] for s in view["sources"]], list(range(24))
        )
        self.assertEqual([s["text"] for s in view["sources"][:3]], ["0", "1", "2"])
        self.assertEqual(view["sources"][3]["text"], "")

    def test_no_outcome_fields_or_candidate_ranking_enters_view(self):
        p = packet()
        p.update(result="later answer", state="PR_OPEN", charge=9999)
        view = compact_acquisition_view(p)
        self.assertNotIn("later answer", json.dumps(view))
        self.assertNotIn("state", view)
        self.assertEqual(view, compact_acquisition_view(packet()))

    def test_invalid_or_oversized_catalog_is_explicit_failure_not_silent_selection(
        self,
    ):
        for p in (
            None,
            {"sources": []},
            {"sources": [], "untrusted_prior_analysis": "[]"},
        ):
            if p == {"sources": []}:
                self.assertEqual(compact_acquisition_view(p)["sources"], [])
            else:
                with self.assertRaises(ValueError):
                    compact_acquisition_view(p)
        p = packet()
        p["sources"][0]["url"] = "x" * 2049
        with self.assertRaises(ValueError):
            compact_acquisition_view(p)
        p["sources"] = [{"url": RAW + "x" * 1800, "text": ""}] * 24
        with self.assertRaisesRegex(ValueError, "budget"):
            compact_acquisition_view(p)


if __name__ == "__main__":
    unittest.main()
