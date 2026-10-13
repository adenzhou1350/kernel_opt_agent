import unittest

from scripts.scout_shadow_admission import observed_capacity, wait_for_capacity


def runtime(**changes):
    return dict(state="RUNNING", active=16, admission_limit=16, heartbeat_at=100,
                memory_paused=False, disk_paused=False, cooldown_until=None, **changes)


class AdmissionTests(unittest.TestCase):
    def wait(self, read, **kwargs):
        now = [0.0]
        return wait_for_capacity(read, clock=lambda: now[0], wall_clock=lambda: 100,
            sleep=lambda seconds: now.__setitem__(0, now[0]+seconds), **kwargs)

    def test_busy_then_spare_observed_without_dispatch(self):
        values = [runtime(), {**runtime(), "active": 14}]
        result = self.wait(lambda: values.pop(0))
        self.assertEqual(result["status"], "OBSERVED_SPARE_CAPACITY")
        self.assertEqual(result["wait_seconds"], 2)
        self.assertEqual(result["observations"], 2)
        self.assertFalse(result["atomic_reservation"])

    def test_busy_exhaustion_retained(self):
        result = self.wait(runtime, max_wait=5, poll_seconds=2)
        self.assertEqual(result["status"], "ADMISSION_WAIT_EXHAUSTED")
        self.assertEqual(result["last_observation"], "BUSY")
        self.assertEqual(result["wait_seconds"], 5)

    def test_stale_future_unknown_paused_and_cooldown_not_ready(self):
        for changes in ({"heartbeat_at": 69}, {"heartbeat_at": 101},
                        {"memory_paused": True}, {"disk_paused": None},
                        {"cooldown_until": 101}, {"active": True},
                        {"admission_limit": 0}, {"state": "TERMINAL"}):
            with self.subTest(changes=changes):
                state = {**runtime(), "active": 0, **changes}
                self.assertNotEqual(observed_capacity(state, 100), "OBSERVED_SPARE_CAPACITY")

    def test_missing_runtime_and_read_error_are_not_capacity(self):
        for value in (None, {}, {**runtime(), "heartbeat_at": float("nan")}):
            self.assertNotEqual(observed_capacity(value, 100), "OBSERVED_SPARE_CAPACITY")
        def fail():
            raise OSError("private path not copied to evidence")
        result = self.wait(fail, max_wait=0)
        self.assertEqual(result["last_observation"], "RUNTIME_READ_FAILED")
        self.assertNotIn("private", str(result))

    def test_limit_and_active_threshold(self):
        self.assertEqual(observed_capacity({**runtime(), "active": 1, "admission_limit": 1}, 100), "BUSY")
        self.assertEqual(observed_capacity({**runtime(), "active": 15}, 100), "BUSY")
        self.assertEqual(observed_capacity({**runtime(), "active": 0, "admission_limit": 1}, 100), "OBSERVED_SPARE_CAPACITY")

    def test_bad_wait_budgets_raise(self):
        for kwargs in ({"max_wait": -1}, {"max_wait": 601}, {"poll_seconds": 0},
                       {"max_active": True}, {"max_age": 0}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.wait(runtime, **kwargs)


if __name__ == "__main__":
    unittest.main()
