"""Clock-controlled regression for concurrent failures draining an open circuit."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from kimi_scout import update_error_cooldown


class CooldownTests(unittest.TestCase):
    def test_sixteen_failures_drain_without_extending_first_deadline(self):
        state = update_error_cooldown(2, 0, 0, 0, 100, 900)
        self.assertEqual(state, (0, 0, 1, 1000))
        for now in range(101, 108):
            state = update_error_cooldown(2, 0, state[2], state[3], now, 900)
            self.assertEqual(state, (0, 0, 1, 1000))
        self.assertEqual(update_error_cooldown(*state, 1000, 900), (0, 0, 1, 0))

    def test_answer_failure_drain_does_not_extend_deadline_or_leave_counters(self):
        state = update_error_cooldown(0, 8, 0, 0, 100, 900)
        for failures, answers in ((0, 8), (1, 7), (1, 0)):
            state = update_error_cooldown(
                failures, answers, state[2], state[3], 200, 900
            )
            self.assertEqual(state, (0, 0, 1, 1000))

    def test_new_failure_round_after_expiry_still_backs_off(self):
        self.assertEqual(
            update_error_cooldown(2, 0, 1, 1000, 1100, 900), (0, 0, 2, 2900)
        )
        self.assertEqual(
            update_error_cooldown(0, 8, 2, 2900, 3000, 900), (0, 0, 3, 6600)
        )
        self.assertEqual(
            update_error_cooldown(2, 0, 20, 0, 8000, 900), (0, 0, 21, 11600)
        )

    def test_success_reset_preserves_open_wait_then_first_round_duration(self):
        # The scheduler resets counters and cycles on success, not the deadline.
        self.assertEqual(
            update_error_cooldown(0, 0, 0, 1000, 500, 900), (0, 0, 0, 1000)
        )
        self.assertEqual(
            update_error_cooldown(2, 0, 0, 1000, 1100, 900), (0, 0, 1, 2000)
        )

    def test_subthreshold_failures_are_retained_only_outside_cooldown(self):
        self.assertEqual(update_error_cooldown(1, 7, 0, 0, 100, 900), (1, 7, 0, 0))

    def test_failed_recovery_probe_reopens_circuit_immediately(self):
        self.assertEqual(update_error_cooldown(1, 0, 1, 0, 100, 60), (0, 0, 2, 220))
        self.assertEqual(update_error_cooldown(0, 1, 2, 0, 300, 60), (0, 0, 3, 540))


if __name__ == "__main__":
    unittest.main()
