"""Offline raw-reset fallback; no TLS/auth/budget failures are bypassed."""
import base64
import hashlib
import json
import ssl
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import kimi_scout_context as context


class BlobFallbackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.client = context.PublicContext(self.temp.name, github_auth=True)
        self.data = b"def answer():\n    return 42\n"
        self.blob = hashlib.sha1(b"blob " + str(len(self.data)).encode() + b"\0" + self.data).hexdigest()
        self.repo = "owner/project"
        self.url = "https://raw.githubusercontent.com/owner/project/" + "a" * 40 + "/src/code.py"
        self.api = f"https://api.github.com/repos/{self.repo}/git/blobs/{self.blob}"
        self.value = dict(sha=self.blob, encoding="base64", size=len(self.data),
                          content=base64.encodebytes(self.data).decode())
        self.failure = urllib.error.URLError(ConnectionResetError(104, "reset"))
        self.calls = []

    def fetch(self, url, limit, github_auth):
        self.calls.append((url, limit, github_auth))
        if url == self.url:
            raise self.failure
        self.assertEqual(url, self.api)
        return json.dumps(self.value)

    def read(self):
        with patch.object(context.scout, "fetch", side_effect=self.fetch):
            return self.client._source_text(self.repo, self.blob, self.url)

    def test_reset_fetches_only_snapshot_blob_and_verifies_bytes(self):
        self.assertEqual(self.read(), (self.data.decode(), "git_blob_api"))
        self.assertEqual(self.calls, [(self.url, context.RAW_LIMIT, False),
                                     (self.api, context.RAW_LIMIT * 2 + 4096, True)])

    def test_timeouts_are_bounded_to_one_fallback(self):
        for failure in (TimeoutError(), urllib.error.URLError(TimeoutError())):
            with self.subTest(failure=type(failure).__name__):
                self.failure = failure
                self.calls.clear()
                self.assertEqual(self.read()[1], "git_blob_api")
                self.assertEqual(len(self.calls), 2)

    def test_no_fallback_for_http_tls_dns_budget_or_unknown_errors(self):
        for failure in (urllib.error.HTTPError(self.url, 403, "denied", {}, None),
                        urllib.error.HTTPError(self.url, 404, "absent", {}, None),
                        urllib.error.URLError(ssl.SSLCertVerificationError()),
                        urllib.error.URLError(OSError(-2, "DNS unavailable")),
                        urllib.error.URLError("unknown"),
                        ValueError("source exceeds read budget")):
            with self.subTest(failure=type(failure).__name__):
                self.failure = failure
                self.calls.clear()
                with self.assertRaises(type(failure)):
                    self.read()
                self.assertEqual(len(self.calls), 1)

    def test_rejects_wrong_identity_size_encoding_and_malformed_data(self):
        original = dict(self.value)
        for changes in (dict(sha="b" * 40), dict(size=len(self.data) + 1),
                        dict(size=True), dict(size=context.RAW_LIMIT + 1),
                        dict(encoding="utf8"), dict(content="%%bad%%"),
                        dict(content=base64.b64encode(b"wrong bytes").decode()),
                        dict(content="x" * (context.RAW_LIMIT * 2 + 1))):
            with self.subTest(fields=tuple(changes)):
                self.value = {**original, **changes}
                with self.assertRaises(ValueError):
                    self.read()

    def test_second_transport_failure_propagates_without_retry(self):
        with patch.object(context.scout, "fetch", side_effect=self.failure) as fetch:
            with self.assertRaises(urllib.error.URLError):
                self.client._source_text(self.repo, self.blob, self.url)
            self.assertEqual(fetch.call_count, 2)

    def test_api_auth_is_still_opt_in_and_response_urls_are_not_followed(self):
        self.client.github_auth = False
        self.value["url"] = "https://untrusted.invalid/redirect"
        self.assertEqual(self.read()[0], self.data.decode())
        self.assertTrue(all(not auth for _, _, auth in self.calls))

    def test_invalid_utf8_is_not_accepted_as_source(self):
        self.data = b"\xff"
        self.blob = hashlib.sha1(b"blob 1\0" + self.data).hexdigest()
        self.api = f"https://api.github.com/repos/{self.repo}/git/blobs/{self.blob}"
        self.value.update(sha=self.blob, size=1, content=base64.b64encode(self.data).decode())
        with self.assertRaises(UnicodeDecodeError):
            self.read()

    def test_verified_fallback_is_cached_under_original_immutable_url(self):
        snapshot = dict(files=["src/code.py"], blobs={"src/code.py": self.blob})
        with patch.object(self.client, "snapshot", return_value=snapshot), \
             patch.object(context.scout, "fetch", side_effect=self.fetch):
            first = self.client.source(self.repo, "a" * 40, "src/code.py")
            second = self.client.source(self.repo, "a" * 40, "src/code.py")
        self.assertEqual(first, second)
        self.assertEqual(first["url"], self.url)
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.client.cached_source_text(self.repo, "a" * 40, "src/code.py"), self.data.decode())
        record = json.loads(next(self.client.cache.glob("raw-*.json")).read_text())
        self.assertEqual(record["transport"], "git_blob_api")


if __name__ == "__main__":
    unittest.main()
