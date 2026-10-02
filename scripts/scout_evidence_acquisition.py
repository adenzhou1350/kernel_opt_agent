"""One bounded public-source GET with observable failure costs.

For shadow acquisition comparisons, not a live routing or candidate-quality
policy. Counts application body bytes returned to this reader, not wire/TLS
traffic. The timeout is a socket-operation timeout, not a hard wall deadline.
There are no retries, redirects, credentials, or writes.
"""

import hashlib
import http.client
import math
import re
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def pinned_raw_url(url):
    if not isinstance(url, str) or not 0 < len(url) <= 2048:
        return False
    try:
        parsed = urlsplit(url)
    except ValueError:
        return False
    parts = parsed.path.lstrip("/").split("/", 3)
    return (
        parsed.scheme == "https"
        and parsed.netloc == "raw.githubusercontent.com"
        and not parsed.query
        and not parsed.fragment
        and len(parts) == 4
        and all(re.fullmatch(r"[A-Za-z0-9_.-]+", item) for item in parts[:2])
        and all(item not in (".", "..") for item in parts[:2])
        and re.fullmatch(r"[a-f0-9]{40}", parts[2]) is not None
        and all(item not in ("", ".", "..") for item in parts[3].split("/"))
        and not re.search(r"[\s%\\\x00-\x1f\x7f]", parsed.path)
        and not parsed.path.startswith("//")
    )


def fetch_source(url, *, max_bytes=1_000_000, socket_timeout=20, opener=None):
    """Return text only on success; preserve status/observed bytes on failure.

    A limit sentinel permits at most max_bytes+1 observed bytes. Partial read
    failures retain already returned chunks. Failure bodies are not exposed as
    source text; their observed prefix digest supports reproducibility only.
    Caller enforces cohort repository/revision and per-arm acquisition budgets.
    """
    if (
        type(max_bytes) is not int
        or not 1 <= max_bytes <= 1_000_000
        or type(socket_timeout) not in (int, float)
        or not math.isfinite(socket_timeout)
        or not 0 < socket_timeout <= 20
    ):
        raise ValueError("invalid bounded acquisition budget")
    record = {
        "url": url,
        "attempted_get": False,
        "http_status": None,
        "body_bytes_observed": 0,
        "body_complete": False,
        "body_sha256": None,
        "declared_body_bytes": None,
        "socket_timeout_seconds": socket_timeout,
        "max_bytes": max_bytes,
        "elapsed_seconds": 0.0,
        "status": "FAILED",
        "error_kind": None,
    }
    if not pinned_raw_url(url):
        record["error_kind"] = "INVALID_PINNED_URL"
        return record
    opener = opener or urllib.request.build_opener(NoRedirect())
    request = urllib.request.Request(
        url, headers={"User-Agent": "kernel-opt-evidence-acquisition/1"}
    )
    response, body = None, bytearray()
    started = time.perf_counter()
    record["attempted_get"] = True
    try:
        try:
            response = opener.open(request, timeout=socket_timeout)
            record["http_status"] = response.getcode()
        except urllib.error.HTTPError as error:
            response = error
            record["http_status"] = error.code
            record["error_kind"] = "HTTP_STATUS"
        length = response.headers.get("Content-Length")
        if isinstance(length, str) and re.fullmatch(r"[0-9]{1,20}", length.strip()):
            record["declared_body_bytes"] = int(length.strip())
        while len(body) <= max_bytes:
            read_size = min(65536, max_bytes + 1 - len(body))
            try:
                chunk = response.read(read_size)
            except http.client.IncompleteRead as error:
                body.extend(error.partial[:read_size])
                record["error_kind"] = "INCOMPLETE_READ"
                break
            if not chunk:
                declared = record["declared_body_bytes"]
                if declared is not None and len(body) != declared:
                    record["error_kind"] = "CONTENT_LENGTH_MISMATCH"
                else:
                    record["body_complete"] = True
                break
            body.extend(chunk)
        if len(body) > max_bytes:
            record["error_kind"] = "BODY_LIMIT_EXCEEDED"
        elif record["http_status"] != 200:
            record["error_kind"] = record["error_kind"] or "HTTP_STATUS"
        elif record["error_kind"] is None:
            try:
                record["text"] = body.decode("utf-8")
            except UnicodeDecodeError:
                record["error_kind"] = "INVALID_UTF8"
            else:
                record["status"] = "FETCHED"
    except (OSError, urllib.error.URLError) as error:
        # Do not copy potentially credential-bearing exception messages.
        record["error_kind"] = type(error).__name__
    finally:
        if response is not None:
            response.close()
        record["elapsed_seconds"] = time.perf_counter() - started
        record["body_bytes_observed"] = len(body)
        if response is not None:
            record["body_sha256"] = hashlib.sha256(body).hexdigest()
    return record


class AcquisitionSession:
    """Deduplicate physical GETs while retaining every arm's request count.

    Cache hits (including failures) have zero additional observed GET cost.
    Their original response latency is not a measured counterfactual latency.
    Session memory is bounded by 64 requested URLs and the per-source byte cap.
    """

    def __init__(self, *, max_bytes=1_000_000, socket_timeout=20, opener=None):
        self.kwargs = {
            "max_bytes": max_bytes,
            "socket_timeout": socket_timeout,
            "opener": opener,
        }
        self.cache = {}
        self.requests = []

    def acquire(self, url):
        if len(self.requests) >= 64:
            raise ValueError("session request budget exhausted")
        cache_hit = isinstance(url, str) and url in self.cache
        if cache_hit:
            result = dict(self.cache[url])
        else:
            result = fetch_source(url, **self.kwargs)
            if isinstance(url, str):
                self.cache[url] = dict(result)
        result.update(
            cache_hit=cache_hit,
            actual_get=not cache_hit and result["attempted_get"],
            additional_get_seconds=0.0 if cache_hit else result["elapsed_seconds"],
            additional_body_bytes=0 if cache_hit else result["body_bytes_observed"],
        )
        self.requests.append({k: v for k, v in result.items() if k != "text"})
        return result

    def costs(self):
        return {
            "requested_targets": len(self.requests),
            "logical_gets": sum(r["attempted_get"] for r in self.requests),
            "actual_gets": sum(r["actual_get"] for r in self.requests),
            "actual_body_bytes_observed": sum(
                r["additional_body_bytes"] for r in self.requests
            ),
            "actual_get_seconds": sum(
                r["additional_get_seconds"] for r in self.requests
            ),
            "logical_response_bytes_observed": sum(
                r["body_bytes_observed"] for r in self.requests
            ),
            "failed_targets": sum(r["status"] == "FAILED" for r in self.requests),
            "unmeasured": [
                "wire bytes",
                "counterfactual uncached latency",
                "model/owner cost",
                "dollars",
            ],
        }
