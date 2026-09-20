"""Offline tests: no credentials, model calls, network or GPUs."""

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "kimi_scout.py"
SPEC = importlib.util.spec_from_file_location("kimi_scout", SCRIPT)
scout = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scout)


def packet(name="one", revision="a" * 40):
    return {
        "name": name,
        "commit": revision,
        "sources": [
            {
                "url": f"https://raw.githubusercontent.com/a/b/{revision}/file.py",
                "text": "12: return values[index]",
                "truncated": False,
            }
        ],
        "question": "find a real bug, or no_lead",
    }


def result():
    return {
        "decision": "lead",
        "title": "bounds question",
        "hypothesis": "check caller",
        "baseline": "unchanged",
        "next_check": "read caller",
        "duplicate_risk": "unknown",
        "uncertainty": "not tested",
        "knowledge_suggestion": "",
        "evidence": [
            {"url": packet()["sources"][0]["url"], "quote": "return values[index]"}
        ],
    }


class ScoutTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        scout.initialize(self.root)

    def add(self, name="one"):
        return scout.enqueue(self.root, packet(name))

    def test_content_dedup_across_moving_revision(self):
        a = scout.enqueue(self.root, packet())
        b = scout.enqueue(self.root, packet(revision="b" * 40))
        self.assertEqual(a, b)
        self.assertEqual(len(scout.status(self.root)["jobs"]), 1)

    def test_related_title_churn_does_not_trigger_another_call(self):
        first = packet()
        first["related_open_items_sample"] = [{"title": "incidental PR"}]
        second = dict(first, related_open_items_sample=[{"title": "other PR"}])
        self.assertEqual(
            scout.enqueue(self.root, first), scout.enqueue(self.root, second)
        )

    def test_citation_to_supplied_related_title_is_allowed(self):
        source = packet()
        source["related_open_items_sample"] = [
            {"url": "https://github.com/a/b/pull/1", "title": "Existing fix"}
        ]
        value = result()
        value["evidence"] = [
            {"url": "https://github.com/a/b/pull/1", "quote": "Existing fix"}
        ]
        self.assertEqual(scout.validate_result(value, source), value)

    def test_atomic_claim_and_persistent_daily_cap(self):
        for i in range(8):
            self.add(str(i))
        with ThreadPoolExecutor(max_workers=4) as pool:
            jobs = list(
                pool.map(lambda _: scout.claim(self.root, 2, 200000, 2048), range(8))
            )
        valid = [job for job in jobs if job]
        self.assertEqual(len(valid), 2)
        self.assertEqual(len({job["id"] for job in valid}), 2)
        self.assertIsNone(scout.claim(self.root, 2, 200000, 2048))

    def test_reservation_budget_blocks_before_provider_call(self):
        self.add()
        self.assertIsNone(scout.claim(self.root, 12, 100, 2048))
        self.assertEqual(scout.status(self.root)["jobs"][0]["state"], "PENDING")

    def test_private_or_oversized_packet_rejected(self):
        for url in (
            "http://github.com/a",
            "https://127.0.0.1/a",
            "https://github.com.evil.test/a",
            "file:///secret",
        ):
            bad = packet()
            bad["sources"][0]["url"] = url
            with self.assertRaises(ValueError):
                scout.enqueue(self.root, bad)
        bad = packet()
        bad["sources"][0]["text"] = "x" * 25000
        with self.assertRaises(ValueError):
            scout.enqueue(self.root, bad)

    def test_exact_evidence_required_no_invented_ready(self):
        self.assertEqual(scout.validate_result(result(), packet())["decision"], "lead")
        for change in (
            {"decision": "READY"},
            {"evidence": []},
            {"evidence": [{"url": "https://github.com/fake", "quote": "x"}]},
        ):
            with self.assertRaises(ValueError):
                scout.validate_result(dict(result(), **change), packet())
        bad = result()
        bad["evidence"][0]["quote"] = "imaginary measured speedup"
        with self.assertRaises(ValueError):
            scout.validate_result(bad, packet())

    def test_json_fence_only_no_arbitrary_prose(self):
        value = json.dumps(result())
        self.assertEqual(scout.parse_answer(value), result())
        self.assertEqual(scout.parse_answer("```json\n" + value + "\n```"), result())
        with self.assertRaises(ValueError):
            scout.parse_answer("I ran everything! " + value)

    def test_multiline_quote_can_omit_number_prefix_only(self):
        value = result()
        value["evidence"][0]["quote"] = "return values[index] + 1"
        source = packet()
        source["sources"][0]["text"] = "12: return values[index]\n13:     + 1"
        self.assertEqual(scout.validate_result(value, source), value)
        value["evidence"][0]["quote"] = "return values[index] + 2"
        with self.assertRaises(ValueError):
            scout.validate_result(value, source)

    def test_automatic_feed_rejects_private_repository(self):
        with patch.object(scout, "fetch", return_value='{"private": true}'):
            with self.assertRaisesRegex(ValueError, "private"):
                scout.collect_source({"repo": "owner/private"}, True)

    def test_invalid_answer_preserved_as_untrusted(self):
        self.add()
        job = scout.claim(self.root, 12, 200000, 2048)
        response = {
            "ok": True,
            "text": "{}",
            "tools_advertised": 0,
            "tool_calls_executed": 0,
            "finish_reason": "stop",
        }
        with patch.object(
            scout.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 0, json.dumps(response), ""),
        ):
            receipt = scout.execute(self.root, job, sys.executable, 30, 2048)
        self.assertEqual(receipt["error"], "unexpected result fields")
        raw = json.loads(
            (self.root / "results" / (job["id"] + ".answer.json")).read_text()
        )
        self.assertTrue(raw["untrusted"])
        self.assertEqual(raw["text"], "{}")

    def test_success_is_only_review_and_records_usage(self):
        self.add()
        job = scout.claim(self.root, 12, 200000, 2048)
        response = {
            "ok": True,
            "text": json.dumps(result()),
            "usage": {"total_tokens": 321},
            "model_alias": "test",
            "tools_advertised": 0,
            "tool_calls_executed": 0,
        }
        with patch.object(
            scout.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 0, json.dumps(response), ""),
        ) as run:
            receipt = scout.execute(self.root, job, sys.executable, 30, 2048)
        self.assertEqual(receipt["state"], "REVIEW")
        self.assertFalse(receipt["result"]["qualified"])
        self.assertEqual(receipt["charged_tokens_or_reservation"], 321)
        self.assertIn("-I", run.call_args.args[0])
        self.assertNotIn("shell", run.call_args.kwargs)
        request = json.loads(run.call_args.kwargs["input"])
        self.assertEqual(request["max_output_tokens"], 2048)
        self.assertIn(scout.SYSTEM, request["prompt"])

    def test_failure_and_timeout_not_retried_or_secret_logged(self):
        for name, response in (
            ("exit", subprocess.CompletedProcess([], 1, "secret", "api_key=SECRET")),
            ("timeout", subprocess.TimeoutExpired("secret", 30)),
        ):
            self.add(name)
            job = scout.claim(self.root, 12, 200000, 2048)
            kwargs = (
                {"side_effect": response}
                if isinstance(response, Exception)
                else {"return_value": response}
            )
            with patch.object(scout.subprocess, "run", **kwargs):
                receipt = scout.execute(self.root, job, sys.executable, 30, 2048)
            self.assertEqual(receipt["state"], "FAILED")
            self.assertEqual(receipt["charged_tokens_or_reservation"], job["charge"])
            self.assertNotIn("secret", json.dumps(receipt).lower())
        self.assertIsNone(scout.claim(self.root, 12, 200000, 2048))

    def test_unexpected_tool_capability_is_rejected(self):
        self.add()
        job = scout.claim(self.root, 12, 200000, 2048)
        response = {
            "ok": True,
            "text": json.dumps(result()),
            "tools_advertised": 1,
            "tool_calls_executed": 0,
        }
        with patch.object(
            scout.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 0, json.dumps(response), ""),
        ):
            self.assertEqual(
                scout.execute(self.root, job, sys.executable, 30, 2048)["state"],
                "FAILED",
            )

    def test_safe_fixed_remote_fetch(self):
        for url in (
            "https://localhost/",
            "https://api.github.com@evil.test/",
            "https://api.github.com:443/x",
            "file:///secret",
        ):
            with self.assertRaises(ValueError):
                scout.fetch(url)
        with self.assertRaises(ValueError):
            scout.NoRedirect().redirect_request(None, None, None, None, None, None)

    def test_single_runner_lock(self):
        with scout.single_runner(self.root):
            with self.assertRaises(OSError):
                with scout.single_runner(self.root):
                    self.fail("duplicate runner admitted")

    def test_stop_cli_does_not_touch_other_processes(self):
        self.assertEqual(scout.main(["--root", str(self.root), "stop"]), 0)
        self.assertTrue((self.root / "STOP").exists())
        self.assertTrue(scout.status(self.root)["stop_requested"])


if __name__ == "__main__":
    unittest.main()
