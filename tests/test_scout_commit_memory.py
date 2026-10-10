"""Pure budget boundaries and simulated Windows counters; no model processes."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import scout_commit_memory as memory


class CommitMemoryTests(unittest.TestCase):
    def test_headroom_uses_commit_not_physical_ram(self):
        with (
            patch.object(memory.sys, "platform", "win32"),
            patch.object(
                memory, "_windows_commit_pages", return_value=(850, 1000, memory.MIB)
            ),
        ):
            self.assertEqual(memory.available_commit_headroom_mb(), 50)

    def test_windows_probe_failure_and_invalid_counters_block(self):
        with patch.object(memory.sys, "platform", "win32"):
            with patch.object(memory, "_windows_commit_pages", side_effect=OSError):
                self.assertEqual(memory.available_commit_headroom_mb(), -1)
            for value in ((0, 0, 4096), (-1, 1, 4096), (0, 1, 0)):
                with (
                    self.subTest(value=value),
                    patch.object(memory, "_windows_commit_pages", return_value=value),
                ):
                    self.assertEqual(memory.available_commit_headroom_mb(), -1)
        self.assertFalse(memory.commit_admits_call(-1, 0))

    def test_unsupported_platform_does_not_query_windows(self):
        with (
            patch.object(memory.sys, "platform", "linux"),
            patch.object(memory, "_windows_commit_pages") as probe,
        ):
            self.assertIsNone(memory.available_commit_headroom_mb())
            probe.assert_not_called()
        self.assertTrue(memory.commit_admits_call(None, 16))

    def test_margin_pending_and_worker_charge_boundaries(self):
        self.assertFalse(memory.commit_admits_call(767, 0))
        self.assertTrue(memory.commit_admits_call(768, 0))
        self.assertFalse(memory.commit_admits_call(1023, 1, 128))
        self.assertTrue(memory.commit_admits_call(1024, 1, 128))
        self.assertFalse(memory.commit_admits_call(1535, 1, 512))
        self.assertTrue(memory.commit_admits_call(1536, 1, 512))

    def test_full_capacity_is_not_forced_under_moderate_headroom(self):
        # All 16 can be submitted before their memory appears in the counters
        # only when the budget covers all 16 cold-start charges plus margin.
        def admitted(room):
            return sum(memory.commit_admits_call(room, n, 128) for n in range(16))
        self.assertEqual(admitted(2560), 8)
        self.assertEqual(admitted(4608), 16)
        self.assertEqual(admitted(0), 0)

    def test_pressure_recovery_needs_no_restart_or_counter_reset(self):
        self.assertFalse(memory.commit_admits_call(500, 0))
        self.assertTrue(memory.commit_admits_call(1000, 0))


if __name__ == "__main__":
    unittest.main()
