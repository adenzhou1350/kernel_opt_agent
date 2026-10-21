"""Real clients against the upstream local handler; no storage-service claim."""

import io
import threading
from http.server import HTTPServer

import pytest

from fsspec.implementations.http import HTTPFileSystem as AsyncHTTPFileSystem
from fsspec.implementations.http_sync import HTTPFileSystem as SyncHTTPFileSystem
from fsspec.tests.conftest import HTTPTestHandler


@pytest.fixture(scope="module")
def sink():
    class Handler(HTTPTestHandler):
        files = {}
        requests = []

        def do_POST(self):
            self.requests.append((self.command, self.path))
            super().do_POST()

        do_PUT = do_POST

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", Handler
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)
        assert not thread.is_alive()


@pytest.mark.parametrize("backend", ["requests", "aiohttp"])
@pytest.mark.parametrize("method", ["post", "put"])
@pytest.mark.parametrize(
    "suffix,wire_path",
    [
        ("plain", "/plain"),
        ("space name", "/space%20name"),
        ("caf\u00e9", "/caf%C3%A9"),
        ("pre%20quoted", "/pre%20quoted"),
        ("slash%2Fname", "/slash%2Fname"),
        ("literal%25name", "/literal%25name"),
    ],
)
def test_real_upload_preserves_encoded_target_and_bytes(
    sink, backend, method, suffix, wire_path
):
    base, handler = sink
    handler.files.clear()
    handler.requests.clear()
    cls = SyncHTTPFileSystem if backend == "requests" else AsyncHTTPFileSystem
    fs = cls(skip_instance_cache=True)
    stream = io.BytesIO(b"exact-upload-body")
    if backend == "requests":
        fs.session.trust_env = False
    try:
        fs.put_file(stream, base + "/" + suffix, method=method)
        assert handler.requests == [(method.upper(), wire_path)]
        assert handler.files == {wire_path: b"exact-upload-body"}
        assert not stream.closed
    finally:
        if backend == "requests":
            fs.session.close()
        elif fs._session is not None:
            fs.close_session(fs.loop, fs._session)
