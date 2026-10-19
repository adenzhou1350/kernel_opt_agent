"""Current official example, real loopback HTTP, synthetic P/D only."""

import importlib.metadata
import importlib.util
import json
from pathlib import Path
import socket
import threading
import time
import unittest

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
import uvicorn


ROOT = Path(__file__).resolve().parent
EVENTS = []
CASES = []


class LocalServer:
    def __init__(self, app):
        self.socket = socket.socket()
        self.socket.bind(("127.0.0.1", 0))
        self.socket.listen(16)
        self.port = self.socket.getsockname()[1]
        self.server = uvicorn.Server(
            uvicorn.Config(
                app,
                host="127.0.0.1",
                port=self.port,
                log_level="critical",
                access_log=False,
                lifespan="on",
                loop="asyncio",
                http="h11",
            )
        )
        self.thread = threading.Thread(
            target=self.server.run,
            kwargs={"sockets": [self.socket]},
            daemon=True,
        )
        self.thread.start()
        deadline = time.monotonic() + 8
        while not self.server.started:
            if not self.thread.is_alive() or time.monotonic() > deadline:
                self.close()
                raise RuntimeError("owned loopback server did not start")
            time.sleep(0.01)

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}"

    def close(self):
        self.server.should_exit = True
        self.thread.join(5)
        self.socket.close()
        if self.thread.is_alive():
            raise RuntimeError("owned server thread did not terminate")


class ProxyWire(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        prefill = FastAPI()
        decode = FastAPI()

        @prefill.get("/health")
        async def health():
            return {"ready": True}

        @prefill.get("/query")
        async def query():
            return {"0": {"engine_id": "synthetic-engine"}}

        @prefill.post("/v1/completions")
        @prefill.post("/v1/chat/completions")
        async def prefill_request(request: Request):
            body = await request.json()
            EVENTS.append({"role": "P", "path": request.url.path, "body": body})
            return {"choices": []}

        @decode.post("/v1/completions")
        @decode.post("/v1/chat/completions")
        async def decode_request(request: Request):
            body = await request.json()
            EVENTS.append({"role": "D", "path": request.url.path, "body": body})
            if body["model"] == "controlled-error":
                return JSONResponse(
                    {"error": {"message": "controlled failure"}}, status_code=500
                )
            content = (
                b'data: {"choices":[]}\n\ndata: [DONE]\n\n'
                if body["stream"]
                else b'{"choices":[]}'
            )
            return Response(
                content,
                media_type="text/event-stream"
                if body["stream"]
                else "application/json",
            )

        # Unmodeled paths are not production 404 findings.
        for app in (prefill, decode):

            @app.api_route("/{rest:path}", methods=["GET", "POST", "PUT", "DELETE"])
            async def unknown(rest: str):
                return Response("UNMODELED", status_code=501)

        cls.servers = []
        try:
            p = LocalServer(prefill)
            cls.servers.append(p)
            d = LocalServer(decode)
            cls.servers.append(d)
            spec = importlib.util.spec_from_file_location(
                "official_proxy_under_test", ROOT / "proxy.py"
            )
            cls.module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(cls.module)
            # Configure the ordinary example lifespan, not its routing/client functions.
            from types import SimpleNamespace

            cls.module.global_args = SimpleNamespace(
                prefill=[(p.url, p.port)], decode=[d.url]
            )
            cls.proxy = LocalServer(cls.module.app)
            cls.servers.append(cls.proxy)
            deadline = time.monotonic() + 5
            while not cls.module.app.state.ready.is_set():
                if time.monotonic() > deadline:
                    raise RuntimeError(
                        "ordinary prefill bootstrap did not become ready"
                    )
                time.sleep(0.01)
        except BaseException:
            for server in reversed(cls.servers):
                server.close()
            raise

    @classmethod
    def tearDownClass(cls):
        for server in reversed(cls.servers):
            server.close()
        result = {
            "cases": CASES,
            "upstream_requests": EVENTS,
            "owned_server_threads_alive": [s.thread.is_alive() for s in cls.servers],
            "dependencies": {
                name: importlib.metadata.version(name)
                for name in (
                    "fastapi",
                    "starlette",
                    "httpx",
                    "httpcore",
                    "uvicorn",
                    "pydantic",
                    "pydantic-core",
                )
            },
            "boundary": "Real local HTTP through unchanged official proxy, synthetic P/D. Not native transfer, GPU/RDMA, full vLLM or reporter private-fix validation.",
        }
        with (ROOT / "wire.json").open("x") as stream:
            json.dump(result, stream, indent=2)

    def exercise(self, endpoint, stream, status):
        payload = {
            "model": "controlled-error" if status == 500 else "healthy",
            "stream": stream,
        }
        payload.update(
            {"messages": [{"role": "user", "content": "test"}]}
            if "chat" in endpoint
            else {"prompt": "test"}
        )
        error = None
        content = b""
        with httpx.Client(timeout=5, trust_env=False) as client:
            with client.stream(
                "POST", self.proxy.url + endpoint, json=payload
            ) as response:
                received = response.status_code
                content_type = response.headers.get("content-type", "")
                try:
                    content = response.read()
                except httpx.RemoteProtocolError as exc:
                    error = type(exc).__name__
        record = dict(
            endpoint=endpoint,
            stream=stream,
            expected_status=status,
            received_status=received,
            content_type=content_type,
            body=content.decode(),
            read_error=error,
        )
        CASES.append(record)
        # Verify the wire actually reached the real proxy's ordinary upstream code.
        deadline = time.monotonic() + 2
        while not any(
            e["role"] == "P"
            and e["path"] == endpoint
            and e["body"]["model"] == payload["model"]
            for e in EVENTS
        ):
            if time.monotonic() > deadline:
                self.fail("prefill request was not observed")
            time.sleep(0.01)
        self.assertTrue(
            any(
                e["role"] == "D"
                and e["path"] == endpoint
                and e["body"]["stream"] is stream
                and e["body"]["model"] == payload["model"]
                for e in EVENTS
            )
        )
        self.assertEqual(received, status, record)
        self.assertIsNone(error, record)
        if status == 500:
            self.assertEqual(
                json.loads(content), {"error": {"message": "controlled failure"}}
            )
            self.assertTrue(content_type.startswith("application/json"))
        else:
            self.assertEqual(
                content,
                b'data: {"choices":[]}\n\ndata: [DONE]\n\n'
                if stream
                else b'{"choices":[]}',
            )
            self.assertTrue(
                content_type.startswith(
                    "text/event-stream" if stream else "application/json"
                )
            )


for route in ("completions", "chat/completions"):
    for streaming in (False, True):
        for status in (200, 500):

            def case(self, route=route, streaming=streaming, status=status):
                self.exercise("/v1/" + route, streaming, status)

            setattr(
                ProxyWire, f"test_{route.replace('/', '_')}_{streaming}_{status}", case
            )
