"""Offline protocol/lifecycle checks: owned native children, no API/WSL/GPU."""
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
resident = __import__("kimi_scout_resident")

spec = importlib.util.spec_from_file_location("backend_resident_test", SCRIPTS / "kimi_scout_backend.py")
backend = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backend)

ECHO = '''
import json,sys
for raw in sys.stdin:
    e=json.loads(raw)
    print(json.dumps({'request_id':e['request_id'],'payload':{'ok':True,'text':e['request']['prompt'],'tools_advertised':0,'tool_calls_executed':0,'usage':{'total_tokens':17}}}),flush=True)
'''


class ResidentTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def pool(self, code=ECHO, capacity=2):
        pool = resident.BackendPool(sys.executable, self.root, None, capacity,
                                    command=[sys.executable, "-I", "-B", "-c", code])
        self.addCleanup(pool.close)
        return pool

    def call(self, pool, text="public", timeout=5):
        return pool.run({"prompt": text}, self.root / "live.json", timeout)

    def test_sequential_reuse_and_32_request_recycling(self):
        pool = self.pool(capacity=1)
        for i in range(33):
            result = self.call(pool, str(i))
            self.assertEqual(json.loads(result.stdout)["text"], str(i))
        self.assertEqual(pool.process_starts, 2)
        workers = list(pool.idle.queue)
        pool.close()
        self.assertTrue(all(w is None or w.process.poll() is not None for w in workers))

    def test_concurrency_is_bounded_and_answers_are_not_cross_wired(self):
        pool = self.pool(capacity=4)
        with ThreadPoolExecutor(max_workers=16) as threads:
            results = list(threads.map(lambda n: self.call(pool, str(n)), range(48)))
        self.assertEqual([json.loads(r.stdout)["text"] for r in results], list(map(str, range(48))))
        self.assertLessEqual(pool.process_starts, 5)
        self.assertEqual(pool.idle.qsize(), 4)

    def test_malformed_wrong_id_and_oversized_frames_fail_without_replay(self):
        for code in (
            "import sys;sys.stdin.readline();print('not-json',flush=True)",
            "import sys,json;sys.stdin.readline();print(json.dumps({'request_id':'wrong','payload':{'ok':True}}),flush=True)",
            "import sys;sys.stdin.readline();print('x'*1000001,flush=True)",
            "import sys;sys.stdin.readline();sys.exit(1)",
        ):
            with self.subTest(code=code):
                pool = self.pool(code, capacity=1)
                with self.assertRaisesRegex(ValueError, "invalid_resident_protocol"):
                    self.call(pool)
                self.assertEqual(pool.process_starts, 1)
                self.assertIsNone(pool.idle.queue[0])

    def test_timeout_including_blocked_stdin_is_bounded_and_not_retried(self):
        pool = self.pool("import time;time.sleep(60)", capacity=1)
        started = time.monotonic()
        with self.assertRaises(subprocess.TimeoutExpired):
            self.call(pool, "x" * 260000, timeout=0.1)
        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual(pool.process_starts, 1)
        self.assertIsNone(pool.idle.queue[0])

    def test_queue_timeout_never_starts_an_extra_child(self):
        pool = self.pool(capacity=1)
        slot = pool.idle.get_nowait()
        try:
            with self.assertRaises(subprocess.TimeoutExpired):
                self.call(pool, timeout=0.05)
            self.assertEqual(pool.process_starts, 0)
        finally:
            pool.idle.put(slot)

    def test_failed_completion_retires_worker_without_replay(self):
        pool = self.pool(ECHO.replace("'ok':True", "'ok':False,'retryable':True"), capacity=1)
        result = self.call(pool)
        self.assertEqual(result.returncode, 75)
        self.assertEqual(pool.process_starts, 1)
        self.assertIsNone(pool.idle.queue[0])

    def test_close_refuses_further_requests(self):
        pool = self.pool()
        pool.close()
        with self.assertRaisesRegex(ValueError, "resident_pool_closed"):
            self.call(pool)

    def test_controller_persists_usage_and_drains_owned_resident_children(self):
        scout = __import__("kimi_scout")
        scout.initialize(self.root)
        for i in range(3):
            scout.enqueue(self.root, {
                "name": str(i), "commit": "a" * 40, "question": "review " + str(i),
                "sources": [{"url": "https://github.com/a/b/blob/main/a.py", "text": "return 1"}],
            })
        answer = {key: "" for key in (
            "title", "hypothesis", "baseline", "next_check", "duplicate_risk",
            "uncertainty", "knowledge_suggestion",
        )}
        answer.update(decision="no_lead", evidence=[])
        code = ECHO.replace("e['request']['prompt']", repr(json.dumps(answer)))
        factory = resident.BackendPool
        pools = []

        def create(python, root, env, capacity):
            pool = factory(python, root, env, capacity,
                           command=[sys.executable, "-I", "-B", "-c", code])
            pools.append(pool)
            return pool

        args = SimpleNamespace(root=self.root, hours=0, concurrency=1, max_jobs=0,
                               token_budget=0, feeds=None, github_auth=False,
                               poll_seconds=300, output_tokens=256, timeout=15,
                               error_cooldown_seconds=60, kimi_python=sys.executable,
                               once=True, resident_backend=True)
        with patch.object(resident, "BackendPool", side_effect=create):
            result = scout.run(args)
        self.assertTrue(pools[0].closed)
        self.assertEqual(result["runtime"]["backend_mode"], "resident")
        self.assertEqual(result["runtime"]["backend_process_starts"], 1)
        self.assertEqual(result["runtime"]["attempted_this_run"], 3)
        self.assertTrue(all(job["state"] == "NO_LEAD" for job in result["jobs"]))
        with scout.connect(self.root) as db:
            self.assertEqual(db.execute("SELECT sum(charge) FROM jobs").fetchone()[0], 51)

    def serve(self, envelopes, complete):
        fake = SimpleNamespace(
            load_provider=lambda _: {"model_alias": "test"},
            BackendError=backend.BackendError, safe_error=backend.safe_error,
            read_request=backend.read_request, ProgressFile=backend.ProgressFile,
            report_progress=backend.report_progress, complete=complete,
            SUPPORTED_KIMI_VERSION="1.30.0",
        )
        output = io.StringIO()
        flags = sys.flags

        class IsolatedFlags:
            isolated = True

            def __getattr__(self, name):
                return getattr(flags, name)

        with (patch.object(resident, "load_backend", return_value=fake),
              patch.object(resident.sys, "flags", IsolatedFlags())):
            resident.serve(self.root / "not-read", io.BytesIO(envelopes), output)
        return [json.loads(line) for line in output.getvalue().splitlines()]

    def envelope(self, prompt="public", **changes):
        value = {"request_id": "a" * 32, "request": {"prompt": prompt},
                 "progress_file": str(self.root / "live.json")}
        value.update(changes)
        return json.dumps(value).encode() + b"\n"

    def test_server_passes_only_fresh_request_not_prior_conversation(self):
        seen = []

        async def complete(request, provider, progress):
            seen.append(dict(request))
            return {"ok": True, "text": request["prompt"], "tools_advertised": 0}

        result = self.serve(self.envelope("first") + self.envelope("second"), complete)
        self.assertEqual([x["payload"]["text"] for x in result], ["first", "second"])
        self.assertNotIn("first", json.dumps(seen[1]))
        self.assertEqual(set(seen[1]), {"prompt", "timeout_seconds", "max_output_tokens"})

    def test_server_retirement_and_invalid_frames_do_not_call_provider(self):
        calls = []

        async def complete(*args):
            calls.append(1)
            return {"ok": True, "text": "answer"}

        result = self.serve(self.envelope() * 33, complete)
        self.assertEqual(len(result), 32)
        self.assertEqual(len(calls), 32)
        calls.clear()
        self.assertEqual(self.serve(b"x" * (resident.MAX_FRAME_BYTES + 1), complete), [])
        for raw in (
            self.envelope(request={"prompt": "public", "tools": ["shell"]}),
            self.envelope(progress_file="relative.json"), b"[]\n", b"oops\n",
        ):
            result = self.serve(raw, complete)
            self.assertFalse(result[0]["payload"]["ok"])
        self.assertEqual(calls, [])

    def test_server_exception_does_not_leak_configuration_or_error_text(self):
        async def complete(*args):
            raise RuntimeError("Authorization: PRIVATE_KEY")

        result = self.serve(self.envelope(), complete)
        self.assertNotIn("PRIVATE_KEY", json.dumps(result))
        self.assertFalse(result[0]["payload"]["ok"])


if __name__ == "__main__":
    unittest.main()
