"""Tests for the non-dispatching SemIf option scorer audit."""

import json
import tempfile
import unittest
from pathlib import Path

from scripts.semantic_option_shadow import evaluate, load_cases, top_choice


class SemanticOptionShadowTests(unittest.TestCase):
    def test_order_disagreement_abstains(self):
        case = {
            "id": "example",
            "state": "No correctness test has run.",
            "expected_action": "cpu",
            "options": [
                {"id": "source", "description": "Inspect source"},
                {"id": "cpu", "description": "Run CPU test"},
            ],
        }

        def score(_case, options):
            ids = [option["id"] for option in options]
            return {"option_ids": ids, "probabilities": [0.9, 0.1]}

        report = evaluate([case], score)
        self.assertEqual(report["summary"]["order_disagreements"], 1)
        self.assertIsNone(report["rows"][0]["consensus_action"])

    def test_response_ids_must_match_request_order(self):
        with self.assertRaisesRegex(ValueError, "does not match"):
            top_choice(
                {"option_ids": ["b", "a"], "probabilities": [0.8, 0.2]}, ["a", "b"]
            )
        with self.assertRaisesRegex(ValueError, "invalid option probabilities"):
            top_choice(
                {"option_ids": ["a", "b"], "probabilities": [float("nan"), 0.2]},
                ["a", "b"],
            )
        for probabilities in ([0.0, 0.0], [0.9, 0.9], [True, 0.0], [1.1, -0.1]):
            with (
                self.subTest(probabilities=probabilities),
                self.assertRaisesRegex(ValueError, "invalid option probabilities"),
            ):
                top_choice(
                    {"option_ids": ["a", "b"], "probabilities": probabilities},
                    ["a", "b"],
                )

    def test_unlabeled_real_case_has_no_accuracy_claim(self):
        case = {
            "id": "public-window",
            "question": "What evidence should be acquired next?",
            "state": "Public source excerpt. " * 100,
            "data_classification": "public_sanitized",
            "options": [
                {"id": "source", "description": "Inspect missing caller context"},
                {"id": "cpu", "description": "Reproduce with a CPU test"},
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cases.jsonl"
            path.write_text(json.dumps(case) + "\n", encoding="utf-8")
            cases = load_cases(path, unlabeled=True)
            with self.assertRaisesRegex(ValueError, "unexpected fields"):
                load_cases(path)

        def score(_case, options):
            return {
                "option_ids": [item["id"] for item in options],
                "probabilities": [
                    0.9 if item["id"] == "source" else 0.1 for item in options
                ],
            }

        report = evaluate(cases, score)
        self.assertEqual(report["status"], "COMPLETE")
        self.assertEqual(report["summary"]["labeled_valid"], 0)
        self.assertEqual(report["summary"]["score_calls"], 2)
        for key in ("forward_correct", "reverse_correct", "consensus_correct"):
            self.assertIsNone(report["summary"][key])
        self.assertEqual(report["summary"]["consensus_coverage"], 1)
        self.assertEqual(
            report["rows"][0]["forward_probabilities"],
            report["rows"][0]["reverse_probabilities"],
        )
        self.assertGreaterEqual(report["summary"]["client_seconds"]["p95"], 0)

    def test_failed_request_remains_in_latency_accounting(self):
        def score(_case, _options):
            raise TimeoutError("service did not respond")

        report = evaluate([{"id": "timeout", "options": []}], score)
        self.assertEqual(report["status"], "INCOMPLETE")
        self.assertEqual(report["summary"]["valid"], 0)
        self.assertEqual(report["summary"]["score_calls"], 1)
        self.assertIsNone(report["summary"]["consensus_coverage"])
        self.assertEqual(report["rows"][0]["error"], "TimeoutError")

    def test_same_choice_can_hide_probability_instability(self):
        case = {
            "id": "stable-choice",
            "state": "Partial public source",
            "options": [{"id": "source"}, {"id": "cpu"}],
        }

        def score(_case, options):
            ids = [item["id"] for item in options]
            return {
                "option_ids": ids,
                "probabilities": [0.8, 0.2] if ids[0] == "source" else [0.05, 0.95],
            }

        report = evaluate([case], score)
        self.assertEqual(report["summary"]["order_disagreements"], 0)
        self.assertAlmostEqual(
            report["summary"]["order_probability_total_variation"]["mean"], 0.15
        )
        self.assertEqual(report["rows"][0]["consensus_action"], "source")

    def test_matching_orders_report_correct_consensus(self):
        case = {
            "id": "example",
            "state": "No source checked",
            "expected_action": "source",
            "options": [
                {"id": "source", "description": "Inspect source"},
                {"id": "gpu", "description": "Run GPU benchmark"},
            ],
        }

        def score(_case, options):
            ids = [option["id"] for option in options]
            return {
                "option_ids": ids,
                "probabilities": [0.9 if name == "source" else 0.1 for name in ids],
            }

        report = evaluate([case], score)
        self.assertEqual(report["summary"]["consensus_correct"], 1)
        self.assertEqual(report["summary"]["consensus_coverage"], 1.0)


if __name__ == "__main__":
    unittest.main()
