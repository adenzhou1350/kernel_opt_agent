"""Offline consistency controls; no provider, acquisition or discovery claims."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from scout_trial_replay import reported_cost, request_digest, validate_saved_call


class TrialReplayTests(unittest.TestCase):
    def pair(self, *, ok=True, tokens=100):
        request = {
            "prompt": "source α",
            "max_output_tokens": 512,
            "timeout_seconds": 60,
        }
        record = {
            "request_sha256": request_digest(request),
            "response": {
                "ok": ok,
                "usage": {"total_tokens": tokens},
                "text": "saved answer",
            },
        }
        return request, record

    def test_identical_request_replays_and_key_order_does_not_matter(self):
        request, record = self.pair()
        reordered = dict(reversed(list(request.items())))
        self.assertIs(validate_saved_call(request, record, requested=reordered), record)

    def test_changed_prompt_timeout_or_output_budget_cannot_replay(self):
        request, record = self.pair()
        for field, value in [
            ("prompt", "new source"),
            ("timeout_seconds", 61),
            ("max_output_tokens", 256),
        ]:
            with (
                self.subTest(field=field),
                self.assertRaisesRegex(ValueError, "requested input differs"),
            ):
                validate_saved_call(
                    request, record, requested=dict(request, **{field: value})
                )

    def test_missing_or_changed_request_digest_is_not_accepted(self):
        request, record = self.pair()
        for digest in [None, "0" * 64, True]:
            with (
                self.subTest(digest=digest),
                self.assertRaisesRegex(ValueError, "does not bind"),
            ):
                validate_saved_call(request, dict(record, request_sha256=digest))
        with self.assertRaisesRegex(ValueError, "does not bind"):
            validate_saved_call(dict(request, prompt="changed saved request"), record)

    def test_nonfinite_request_and_nonobjects_are_not_hashable_inputs(self):
        for request in [None, [], {"x": float("nan")}, {"x": float("inf")}]:
            with (
                self.subTest(request=request),
                self.assertRaisesRegex(ValueError, "REQUEST_IDENTITY"),
            ):
                request_digest(request)

    def test_failed_calls_still_count_once(self):
        self.assertEqual(
            reported_cost([self.pair(tokens=100), self.pair(ok=False, tokens=23)]),
            (2, 123),
        )
        self.assertEqual(reported_cost([]), (0, 0))

    def test_unknown_cost_does_not_become_free(self):
        for tokens in [None, True, -1, 1.5, "123"]:
            with (
                self.subTest(tokens=tokens),
                self.assertRaisesRegex(ValueError, "REPORTED_COST"),
            ):
                reported_cost([self.pair(tokens=tokens)])


if __name__ == "__main__":
    unittest.main()
