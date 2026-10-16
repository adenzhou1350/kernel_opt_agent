"""Queue races must not be recorded as an exhausted evidence frontier."""
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import kimi_scout as scout
import kimi_scout_research as research
from tests.test_kimi_scout_research import Context


class RefillCapacityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        scout.initialize(self.root)
        config = self.root / "config.json"
        config.write_text(json.dumps(dict(objective="Offline capacity control", queue_target=4,
            context_workers=2, repos=[dict(repo="a/b", source_prefixes=["src/"], question="Check contract")])))
        self.producer = research.ResearchProducer(self.root, config, context=Context())
        self.spec = self.producer.config["repos"][0]

    def test_full_queue_before_first_method_is_not_a_dry_rotation(self):
        with patch.object(self.producer, "pending", return_value=4), patch.multiple(self.producer,
                followup=Mock(), issue=Mock(), source_audit=Mock()):
            self.assertIsNone(self.producer.refill(self.spec, {}, 0))
            self.producer.followup.assert_not_called()
            self.producer.issue.assert_not_called()
            self.producer.source_audit.assert_not_called()

    def test_capacity_race_after_one_empty_method_keeps_deferred_state(self):
        with patch.object(self.producer, "pending", side_effect=[0, 4]), patch.multiple(self.producer,
                followup=Mock(return_value=False), issue=Mock(), source_audit=Mock()):
            self.assertIsNone(self.producer.refill(self.spec, {}, 0))
            self.producer.followup.assert_called_once()
            self.producer.issue.assert_not_called()

    def test_atomic_emit_capacity_race_is_deferred(self):
        with patch.object(self.producer, "pending", return_value=0), patch.object(
                self.producer, "followup", side_effect=research.QueueFull):
            self.assertIsNone(self.producer.refill(self.spec, {}, 0))

    def test_three_real_empty_methods_are_still_dry(self):
        with patch.object(self.producer, "pending", return_value=0), patch.multiple(self.producer,
                followup=Mock(return_value=False), issue=Mock(return_value=False), source_audit=Mock(return_value=False)):
            self.assertIs(self.producer.refill(self.spec, {}, 0), False)
            for name in ("followup", "issue", "source_audit"):
                getattr(self.producer, name).assert_called_once()

    def test_success_before_capacity_race_is_preserved(self):
        with patch.object(self.producer, "pending", side_effect=[0, 4]), patch.object(
                self.producer, "followup", return_value=True):
            self.assertIs(self.producer.refill(self.spec, {}, 0, 4), True)

    def test_deferred_delay_does_not_inherit_empty_backoff(self):
        self.assertEqual(research.refill_retry_delay(None, None, 6), 0.5)
        self.assertEqual(research.refill_retry_delay(False, None, 6), 120)
        self.assertEqual(research.refill_retry_delay(None, "TimeoutError", 6), 60)

    def test_coordinator_discloses_deferral_without_counting_empty_attempt(self):
        ready = threading.Event()
        frames, delays = [], []
        original_publish = self.producer.publish
        original_delay = research.refill_retry_delay
        def publish(*args, **kwargs):
            original_publish(*args, **kwargs)
            rows = self.producer.refill_health
            if rows and rows[0].get("last_outcome"):
                frames.append(dict(rows[0]))
                ready.set()
        def delay(made, failure, empty, **kwargs):
            delays.append((made, failure, empty))
            return original_delay(made, failure, empty, **kwargs)
        with patch.object(self.producer, "refill", return_value=None), patch.object(
                self.producer, "publish", side_effect=publish), patch.object(
                research, "refill_retry_delay", side_effect=delay):
            self.producer.start()
            try:
                self.assertTrue(ready.wait(3))
            finally:
                self.producer.stop()
        self.assertEqual(frames[0]["last_outcome"], "QUEUE_CAPACITY_DEFERRED")
        self.assertIn((None, None, 0), delays)


if __name__ == "__main__":
    unittest.main()
