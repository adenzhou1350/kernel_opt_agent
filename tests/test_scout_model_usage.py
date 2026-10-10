import copy
import unittest

from scripts.scout_model_usage import COUNTERS, messages_usage


class MessagesUsageTests(unittest.TestCase):
    def test_observed_minimax_response_includes_cache_reads(self):
        usage = dict(input_tokens=46, cache_creation_input_tokens=0,
                     cache_read_input_tokens=128, output_tokens=7,
                     service_tier="standard")
        before = copy.deepcopy(usage)
        view = messages_usage(usage)
        self.assertEqual(view["total_input_tokens"], 174)
        self.assertEqual(view["total_tokens"], 181)
        self.assertEqual(view["missing_counters"], [])
        self.assertEqual(usage, before)

    def test_cache_write_read_and_uncached_input_are_disjoint(self):
        view = messages_usage(dict(input_tokens=21, cache_creation_input_tokens=30,
                                   cache_read_input_tokens=100, output_tokens=5))
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
                    self.assertEqual(view["total_input_tokens"],
                                     0 if name == "output_tokens" else None)

    def test_absent_usage_is_not_a_free_call(self):
        for usage in (None, {}):
            view = messages_usage(usage)
            self.assertIsNone(view["total_input_tokens"])
            self.assertIsNone(view["total_tokens"])
            self.assertEqual(view["missing_counters"], list(COUNTERS))

    def test_rejects_inclusive_prompt_usage_instead_of_double_counting_cache(self):
        usage = dict(prompt_tokens=1200, completion_tokens=300, total_tokens=1500,
                     prompt_tokens_details={"cached_tokens": 800})
        with self.assertRaisesRegex(ValueError, "inclusive"):
            messages_usage(usage)

    def test_rejects_invalid_counter_and_container_types(self):
        for value in (-1, True, 0.5, "7", float("nan"), [], {}):
            for name in COUNTERS:
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    messages_usage({name: value})
        for usage in ([], "", 0, False):
            with self.subTest(usage=usage), self.assertRaises(ValueError):
                messages_usage(usage)


if __name__ == "__main__":
    unittest.main()
