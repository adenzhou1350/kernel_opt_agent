"""Offline transport/accounting tests, not model-quality experiments."""

import hashlib
import http.client
import io
import unittest
import urllib.error
from unittest.mock import Mock

from scripts.scout_evidence_acquisition import (
    AcquisitionSession,
    NoRedirect,
    fetch_source,
)

URL = "https://raw.githubusercontent.com/example/project/" + "a" * 40 + "/src/main.py"


class Response(io.BytesIO):
    headers = {}

    def getcode(self):
        return 200


class AcquisitionTests(unittest.TestCase):
    def test_success_counts_raw_utf8_bytes_and_closes(self):
        body = "# 判断\nvalue=1\n".encode()
        response = Response(body)
        opener = Mock()
        opener.open.return_value = response
        result = fetch_source(URL, opener=opener)
        self.assertEqual(result["status"], "FETCHED")
        self.assertEqual(result["text"].encode(), body)
        self.assertEqual(result["body_bytes_observed"], len(body))
        self.assertEqual(result["body_sha256"], hashlib.sha256(body).hexdigest())
        self.assertTrue(result["body_complete"])
        self.assertTrue(response.closed)
        request = opener.open.call_args.args[0]
        self.assertNotIn("Authorization", request.headers)
        self.assertEqual(opener.open.call_args.kwargs["timeout"], 20)

    def test_http_failure_retains_status_and_bounded_body(self):
        for status in (302, 404, 429, 500):
            with self.subTest(status=status):
                body = io.BytesIO(b"failure body")
                error = urllib.error.HTTPError(URL, status, "failure", {}, body)
                opener = Mock()
                opener.open.side_effect = error
                result = fetch_source(URL, opener=opener)
                self.assertEqual(result["status"], "FAILED")
                self.assertEqual(result["http_status"], status)
                self.assertEqual(result["error_kind"], "HTTP_STATUS")
                self.assertEqual(result["body_bytes_observed"], 12)
                self.assertTrue(result["body_complete"])
                self.assertNotIn("text", result)
                self.assertTrue(body.closed)
                opener.open.assert_called_once()

    def test_body_limit_applies_to_success_and_error_bodies(self):
        for response in (
            Response(b"123456"),
            urllib.error.HTTPError(URL, 404, "failure", {}, io.BytesIO(b"123456")),
        ):
            opener = Mock()
            if isinstance(response, urllib.error.HTTPError):
                opener.open.side_effect = response
            else:
                opener.open.return_value = response
            result = fetch_source(URL, max_bytes=4, opener=opener)
            self.assertEqual(result["error_kind"], "BODY_LIMIT_EXCEEDED")
            self.assertEqual(result["body_bytes_observed"], 5)
            self.assertFalse(result["body_complete"])
            self.assertNotIn("text", result)

    def test_mid_read_timeout_preserves_returned_prefix(self):
        response = Mock()
        response.getcode.return_value = 200
        response.read.side_effect = [b"prefix", TimeoutError("private message")]
        opener = Mock()
        opener.open.return_value = response
        result = fetch_source(URL, opener=opener)
        self.assertEqual(result["error_kind"], "TimeoutError")
        self.assertEqual(result["body_bytes_observed"], 6)
        self.assertEqual(result["body_sha256"], hashlib.sha256(b"prefix").hexdigest())
        self.assertFalse(result["body_complete"])
        self.assertNotIn("private message", str(result))
        response.close.assert_called_once()

    def test_incomplete_read_and_utf8_failure_are_not_success(self):
        response = Mock()
        response.getcode.return_value = 200
        response.read.side_effect = [b"pre", http.client.IncompleteRead(b"fix", 20)]
        opener = Mock()
        opener.open.return_value = response
        result = fetch_source(URL, opener=opener)
        self.assertEqual(result["error_kind"], "INCOMPLETE_READ")
        self.assertEqual(result["body_bytes_observed"], 6)
        opener.open.return_value = Response(b"\xff")
        result = fetch_source(URL, opener=opener)
        self.assertEqual(result["error_kind"], "INVALID_UTF8")
        self.assertTrue(result["body_complete"])
        self.assertNotIn("text", result)

    def test_connection_error_has_no_observed_body_or_retry(self):
        opener = Mock()
        opener.open.side_effect = urllib.error.URLError("secret message")
        result = fetch_source(URL, opener=opener)
        self.assertEqual(result["body_bytes_observed"], 0)
        self.assertIsNone(result["http_status"])
        self.assertIsNone(result["body_sha256"])
        self.assertNotIn("secret message", str(result))
        opener.open.assert_called_once()

    def test_short_eof_against_content_length_does_not_qualify_prefix_as_source(self):
        response = Response(b"prefix")
        response.headers = {"Content-Length": "12"}
        opener = Mock()
        opener.open.return_value = response
        result = fetch_source(URL, opener=opener)
        self.assertEqual(result["error_kind"], "CONTENT_LENGTH_MISMATCH")
        self.assertEqual(result["declared_body_bytes"], 12)
        self.assertEqual(result["body_bytes_observed"], 6)
        self.assertFalse(result["body_complete"])
        self.assertNotIn("text", result)

    def test_invalid_pinned_targets_never_open(self):
        opener = Mock()
        for url in (
            None,
            42,
            URL.replace("https", "http"),
            URL + "?token=x",
            URL + "#L1",
            URL.replace("a" * 40, "main"),
            URL.replace("/src/", "/../"),
            URL.replace("/src/", "/%2e%2e/"),
            URL.replace(
                "raw.githubusercontent.com", "user:pass@raw.githubusercontent.com"
            ),
            URL.replace("/src/", "//src/"),
            URL.replace("/src/", "/src\\"),
        ):
            with self.subTest(url=url):
                result = fetch_source(url, opener=opener)
                self.assertEqual(result["error_kind"], "INVALID_PINNED_URL")
                self.assertFalse(result["attempted_get"])
        opener.open.assert_not_called()

    def test_invalid_budgets_and_redirect_policy(self):
        for kwargs in (
            {"max_bytes": True},
            {"max_bytes": 0},
            {"max_bytes": 1_000_001},
            {"socket_timeout": float("nan")},
            {"socket_timeout": True},
            {"socket_timeout": 21},
        ):
            with self.assertRaises(ValueError):
                fetch_source(URL, **kwargs)
        self.assertIsNone(
            NoRedirect().redirect_request(
                None, None, 302, None, {}, "https://private.example"
            )
        )

    def test_cache_success_and_failure_keep_logical_counts_without_retries(self):
        for fail in (False, True):
            opener = Mock()
            if fail:
                opener.open.side_effect = urllib.error.HTTPError(
                    URL, 404, "failure", {}, io.BytesIO(b"missing")
                )
            else:
                opener.open.return_value = Response(b"source")
            session = AcquisitionSession(opener=opener)
            first, second = session.acquire(URL), session.acquire(URL)
            self.assertTrue(first["actual_get"])
            self.assertFalse(second["actual_get"])
            self.assertTrue(second["cache_hit"])
            self.assertEqual(second["additional_get_seconds"], 0)
            self.assertEqual(first["body_sha256"], second["body_sha256"])
            costs = session.costs()
            self.assertEqual(costs["requested_targets"], 2)
            self.assertEqual(costs["logical_gets"], 2)
            self.assertEqual(costs["actual_gets"], 1)
            self.assertEqual(
                costs["actual_body_bytes_observed"],
                len(b"missing" if fail else b"source"),
            )
            self.assertEqual(costs["failed_targets"], 2 if fail else 0)
            opener.open.assert_called_once()
            first["status"] = "MUTATED"
            self.assertNotEqual(session.acquire(URL)["status"], "MUTATED")

    def test_invalid_targets_count_as_failures_not_network_work(self):
        session = AcquisitionSession(opener=Mock())
        session.acquire("not a URL")
        costs = session.costs()
        self.assertEqual(costs["failed_targets"], 1)
        self.assertEqual(costs["logical_gets"], 0)
        self.assertEqual(costs["actual_gets"], 0)
        for _ in range(63):
            session.acquire("not a URL")
        with self.assertRaisesRegex(ValueError, "budget exhausted"):
            session.acquire(URL)

    def test_fetched_body_reaches_window_consumer_and_shared_cache(self):
        body = b"header\nstop_wakes_worker()\ntail\n"
        opener = Mock()
        opener.open.return_value = Response(body)
        session = AcquisitionSession(opener=opener)
        result = session.acquire_window(URL, start_line=2, max_lines=1)
        self.assertEqual(result["acquisition"]["status"], "FETCHED")
        self.assertNotIn("text", result["acquisition"])
        self.assertEqual(result["window"]["status"], "ACQUIRED")
        self.assertEqual(result["window"]["text"], "stop_wakes_worker()")
        self.assertEqual(result["window"]["start_line"], 2)
        self.assertEqual(result["window"]["end_line"], 2)
        self.assertEqual(result["window"]["source_sha256"], hashlib.sha256(body).hexdigest())
        second = session.acquire_window(URL, start_line=3, max_lines=1)
        self.assertEqual(second["window"]["text"], "tail")
        self.assertTrue(second["acquisition"]["cache_hit"])
        self.assertEqual(session.costs()["actual_gets"], 1)
        opener.open.assert_called_once()

    def test_transport_and_window_failures_are_separate(self):
        for body, status in ((b"failure", 404), (b"only one line", 200)):
            with self.subTest(status=status):
                opener = Mock()
                if status == 404:
                    opener.open.side_effect = urllib.error.HTTPError(
                        URL, status, "failure", {}, io.BytesIO(body))
                else:
                    opener.open.return_value = Response(body)
                result = AcquisitionSession(opener=opener).acquire_window(URL, start_line=2)
                self.assertEqual(result["window"]["status"], "FAILED")
                self.assertNotIn("text", result["window"])
                self.assertEqual(result["acquisition"]["status"], "FAILED" if status == 404 else "FETCHED")
                self.assertEqual(result["window"]["error_kind"],
                                 "SOURCE_ACQUISITION_FAILED" if status == 404 else "WINDOW_BEYOND_SOURCE")

    def test_bad_window_selector_does_not_spend_get(self):
        opener = Mock()
        session = AcquisitionSession(opener=opener)
        for kwargs in (dict(start_line=0), dict(start_line=True),
                       dict(start_line=1,max_lines=81), dict(start_line=1,max_chars=0)):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                session.acquire_window(URL, **kwargs)
        opener.open.assert_not_called()
        self.assertEqual(session.costs()["actual_gets"], 0)


if __name__ == "__main__":
    unittest.main()
