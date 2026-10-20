"""Real HTTP round trips to a local GitHub-contract fixture, no live API/token.

Only the opener's destination is remapped. The production fetch validation,
bounded read, JSON decoder, issue filter and URL construction still execute.
This is not evidence of live GitHub authentication, TLS or ordering guarantees.
"""

import json
import sys
import tempfile
import threading
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import kimi_scout_context as context


class IssueIntakeHttpTests(unittest.TestCase):
    def test_both_orderings_use_real_http_and_preserve_pr_only_pagination(self):
        paths = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                paths.append(self.path)
                parsed = urlsplit(self.path)
                query = parse_qs(parsed.query)
                if parsed.path == "/repos/owner/project":
                    value = {"private": False, "visibility": "public", "full_name": "owner/project"}
                elif parsed.path == "/repos/owner/project/issues" and query == {
                    "state": ["open"], "sort": ["updated"], "direction": ["desc"],
                    "per_page": ["30"], "page": ["1"],
                }:
                    value = [{"number": 1}]
                elif parsed.path == "/repos/owner/project/issues" and query == {
                    "state": ["open"], "sort": ["created"], "direction": ["desc"],
                    "per_page": ["30"], "page": ["1"],
                }:
                    value = [{"number": 2, "pull_request": {}}]
                elif parsed.path == "/repos/owner/project/issues" and query == {
                    "state": ["open"], "sort": ["created"], "direction": ["desc"],
                    "per_page": ["30"], "page": ["2"],
                }:
                    value = [{"number": 3, "html_url": "https://untrusted.invalid/"}]
                else:
                    self.send_error(501)
                    return
                data = json.dumps(value).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.addCleanup(server.server_close)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(server.shutdown)
        opener = urllib.request.build_opener(context.scout.NoRedirect())

        class LocalDestination:
            def open(self, request, timeout):
                parsed = urlsplit(request.full_url)
                if parsed.scheme != "https" or parsed.netloc != "api.github.com":
                    raise AssertionError("unexpected destination")
                url = f"http://127.0.0.1:{server.server_port}{parsed.path}"
                if parsed.query:
                    url += "?" + parsed.query
                return opener.open(urllib.request.Request(url, headers=request.headers), timeout=timeout)

        with tempfile.TemporaryDirectory() as root, patch.object(
            context.scout.urllib.request, "build_opener", return_value=LocalDestination(),
        ):
            client = context.PublicContext(Path(root))
            self.assertEqual(client.issue_page("owner/project")[0]["number"], 1)
            filtered = client.issue_page("owner/project", sort="created")
            self.assertEqual(filtered, [])
            self.assertFalse(filtered.exhausted)
            later = client.issue_page("owner/project", 2, sort="created")
            self.assertEqual(later[0]["number"], 3)
            self.assertEqual(later[0]["html_url"], "https://github.com/owner/project/issues/3")
        self.assertEqual(len(paths), 4)
