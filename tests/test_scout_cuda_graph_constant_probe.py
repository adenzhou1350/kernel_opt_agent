"""CPU checks for the schedule and scoped advice, not native CUDA qualification."""

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "examples/scout-native-cuda-graphs/check_constant_initialization.py"
spec = importlib.util.spec_from_file_location("constant_probe", PROBE)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)
sys.path.insert(0, str(ROOT / "scripts"))
from scout_lesson_context import MAX_CARD_BYTES, lesson_suggestions  # noqa: E402


class ConstantProbeTests(unittest.TestCase):
    def test_even_schedule_balances_orders_and_is_reproducible(self):
        orders = probe.balanced_orders(12)
        self.assertEqual(orders, probe.balanced_orders(12))
        self.assertEqual(orders.count(("fresh", "cached")), 6)
        self.assertEqual(orders.count(("cached", "fresh")), 6)

    def test_invalid_budget_is_rejected_before_gpu_work(self):
        for args in [("--pairs", "3"), ("--replays", "257")]:
            result = subprocess.run(
                [sys.executable, "-B", str(PROBE), *args],
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("even 2..32 pairs", result.stderr)
            self.assertNotIn("Traceback", result.stderr)

    def test_graph_advice_keeps_initialization_and_claim_limits(self):
        result = lesson_suggestions("graph replay constant initialization fills")
        card = next(
            card
            for card in result["matches"]
            if card["id"] == "measure-production-execution-mode"
        )
        self.assertLessEqual(len(json.dumps(card).encode()), MAX_CARD_BYTES)
        self.assertIn("device fills", card["lesson"])
        self.assertIn("not automatically", card["avoid_when"])
        self.assertEqual(card["status"], "hypothesis")
        self.assertNotIn("qualified", result)


if __name__ == "__main__":
    unittest.main()
