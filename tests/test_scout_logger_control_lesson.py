"""Native config advice remains scoped and does not qualify a candidate."""
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from scout_lesson_context import MAX_CARD_BYTES, lesson_suggestions


class LoggerControlLessonTests(unittest.TestCase):
    def test_relevant_advice_retains_native_controls_and_scope(self):
        result = lesson_suggestions(
            "DeepSpeed timed_op comms_logger configure enabled disabled synchronization"
        )
        self.assertEqual(result["status"], "ADVISORY_MATCH")
        card = result["matches"][0]
        self.assertEqual(card["id"], "logger-disabled-control-realization")
        self.assertLessEqual(len(json.dumps(card).encode()), MAX_CARD_BYTES)
        self.assertIn("masks a configuration regression", card["lesson"])
        self.assertIn("both initial states", card["lesson"])
        self.assertIn("MPI behavior", card["avoid_when"])
        self.assertNotIn("qualified", result)
        self.assertTrue(all("b90283d5" in item["url"] or "/issues/2861" in item["url"]
                            for item in card["evidence"]))

    def test_unrelated_work_does_not_receive_the_logger_card(self):
        result = lesson_suggestions("Go HTTP response Body.Close EOF connection reuse")
        self.assertNotIn("logger-disabled-control-realization",
                         [card["id"] for card in result["matches"]])

    def test_probe_help_needs_no_accelerator_or_deepspeed_import(self):
        result = subprocess.run(
            [sys.executable, "-I", "-B", str(ROOT / "examples/native_deepspeed_comms_config.py"), "--help"],
            capture_output=True, text=True, timeout=15, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--source-root", result.stdout)
        self.assertIn("--logging-sha256", result.stdout)


if __name__ == "__main__":
    unittest.main()
