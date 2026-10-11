import copy
import unittest

from scripts.scout_model_usage import COUNTERS, messages_usage, summarize_token_attempts


class MessagesUsageTests(unittest.TestCase):
    def test_observed_minimax_response_includes_cache_reads(self):
        usage = {
            "input_tokens": 46,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 128,
            "output_tokens": 7,
            "service_tier": "standard",
        }
        before = copy.deepcopy(usage)
        view = messages_usage(usage)
        self.assertEqual(view["total_input_tokens"], 174)
        self.assertEqual(view["total_tokens"], 181)
        self.assertEqual(view["missing_counters"], [])
        self.assertEqual(usage, before)

    def test_cache_write_read_and_uncached_input_are_disjoint(self):
        view = messages_usage(
            {
                "input_tokens": 21,
                "cache_creation_input_tokens": 30,
                "cache_read_input_tokens": 100,
                "output_tokens": 5,
            }
        )
        self.assertEqual(view["total_input_tokens"], 151)
        self.assertEqual(view["total_tokens"], 156)

    def test_explicit_zero_is_complete(self):
        view = messages_usage(dict.fromkeys(COUNTERS, 0))
        self.assertEqual(view["total_tokens"], 0)
        self.assertEqual(view["missing_counters"], [])

    def test_each_missing_or_null_counter_remains_unknown(self):
        for name in COUNTERS:
            for explicit_null in (False, True):
                usage = dict.fromkeys(COUNTERS, 0)
                if explicit_null:
                    usage[name] = None
                else:
                    del usage[name]
                with self.subTest(name=name, explicit_null=explicit_null):
                    view = messages_usage(usage)
                    self.assertIsNone(view["total_tokens"])
                    self.assertEqual(view["missing_counters"], [name])
                    self.assertEqual(
                        view["total_input_tokens"],
                        0 if name == "output_tokens" else None,
                    )

    def test_absent_usage_is_not_a_free_call(self):
        for usage in (None, {}):
            view = messages_usage(usage)
            self.assertIsNone(view["total_input_tokens"])
            self.assertIsNone(view["total_tokens"])
            self.assertEqual(view["missing_counters"], list(COUNTERS))

    def test_rejects_inclusive_prompt_usage_instead_of_double_counting_cache(self):
        usage = {
            "prompt_tokens": 1200,
            "completion_tokens": 300,
            "total_tokens": 1500,
            "prompt_tokens_details": {"cached_tokens": 800},
        }
        with self.assertRaisesRegex(ValueError, "inclusive"):
            messages_usage(usage)

    def test_rejects_invalid_counter_and_container_types(self):
        for value in (-1, True, 0.5, "7", float("nan"), [], {}):
            for name in COUNTERS:
                with (
                    self.subTest(name=name, value=value),
                    self.assertRaises(ValueError),
                ):
                    messages_usage({name: value})
        for usage in ([], "", 0, False):
            with self.subTest(usage=usage), self.assertRaises(ValueError):
                messages_usage(usage)


class AttemptAccountingTests(unittest.TestCase):
    def attempt(
        self, identity="review", arm="rules", tokens=100, final=True, elapsed=2
    ):
        return {
            "attempt_id": identity,
            "arm": arm,
            "total_tokens": tokens,
            "usage_final": final,
            "elapsed_seconds": elapsed,
        }

    def test_selection_overhead_is_in_selected_arm_not_shared_or_discarded(self):
        records = [
            self.attempt(),
            self.attempt("selector", "selected", 40),
            self.attempt("selected-review", "selected", 100),
        ]
        before = copy.deepcopy(records)
        result = summarize_token_attempts(records)
        self.assertEqual(result["rules"]["final_token_total"], 100)
        self.assertEqual(result["selected"]["final_token_total"], 140)
        self.assertEqual(result["selected"]["attempts"], 2)
        self.assertEqual(result["selected"]["call_seconds_total"], 4)
        self.assertEqual(records, before)

    def test_failed_partial_attempt_is_not_erased_by_successful_retry(self):
        result = summarize_token_attempts(
            [
                self.attempt("timeout", tokens=60, final=False),
                self.attempt("retry", tokens=100),
            ]
        )["rules"]
        self.assertEqual(result["observed_token_sum"], 160)
        self.assertIsNone(result["final_token_total"])
        self.assertEqual(result["partial_usage_attempts"], 1)
        self.assertEqual(result["final_usage_attempts"], 1)

    def test_unmetered_attempt_is_not_free_or_replaced_by_later_usage(self):
        result = summarize_token_attempts(
            [
                self.attempt("unknown", tokens=None, final=False, elapsed=None),
                self.attempt("retry"),
            ]
        )["rules"]
        self.assertEqual(result["observed_token_sum"], 100)
        self.assertEqual(result["missing_usage_attempts"], 1)
        self.assertEqual(result["missing_elapsed_attempts"], 1)
        self.assertIsNone(result["final_token_total"])
        self.assertIsNone(result["call_seconds_total"])

    def test_final_truncated_or_invalid_answer_usage_still_costs_tokens(self):
        # Answer quality is absent from this interface: final usage is charged
        # even when the answer was unusable.
        result = summarize_token_attempts([self.attempt(tokens=70)])["rules"]
        self.assertEqual(result["final_token_total"], 70)

    def test_explicit_zero_and_empty_enrollment_are_different(self):
        self.assertEqual(summarize_token_attempts([]), {})
        result = summarize_token_attempts([self.attempt(tokens=0, elapsed=0)])["rules"]
        self.assertEqual(result["attempts"], 1)
        self.assertEqual(result["final_token_total"], 0)
        self.assertEqual(result["call_seconds_total"], 0)

    def test_duplicate_identity_cannot_double_charge_or_hide_in_another_arm(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            summarize_token_attempts([self.attempt(), self.attempt(arm="selected")])

    def test_rejects_malformed_unknown_or_unbounded_records(self):
        for key, values in {
            "total_tokens": [-1, True, 1.5, "10"],
            "usage_final": [None, 1, "true"],
            "elapsed_seconds": [-1, True, float("nan"), float("inf"), "2", 10**1000],
            "attempt_id": [None, "", "a/b", "a" * 129],
            "arm": [False, "with space"],
        }.items():
            for value in values:
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    summarize_token_attempts([{**self.attempt(), key: value}])
        for records in (
            None,
            {},
            (),
            [self.attempt()] * 4097,
            [{**self.attempt(), "prompt": "unneeded private text"}],
            [self.attempt(tokens=None)],
            [None],
        ):
            with (
                self.subTest(records_type=type(records)),
                self.assertRaises(ValueError),
            ):
                summarize_token_attempts(records)


if __name__ == "__main__":
    unittest.main()
