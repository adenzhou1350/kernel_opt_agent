"""Offline transport and disconnect tests: no SSH, credentials or API calls."""
from concurrent.futures import ThreadPoolExecutor
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
remote = __import__("kimi_scout_remote")


class RemoteTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.hosts = self.root / "known_hosts"
        self.hosts.write_text("pinned-test-key", encoding="utf-8")
        self.transport = self.root / "transport.json"
        self.config = dict(host="worker@host.example", port=2222,
                           root="/private/scout", known_hosts=str(self.hosts))
        self.save()

    def save(self):
        self.transport.write_text(json.dumps(self.config), encoding="utf-8")

    def test_command_pins_host_and_uses_only_private_cpu_paths(self):
        cmd = remote.ssh_command(self.transport)
        self.assertIn("StrictHostKeyChecking=yes", cmd)
        self.assertIn("BatchMode=yes", cmd)
        self.assertIn("CUDA_VISIBLE_DEVICES=", cmd[-1])
        self.assertIn("/private/scout/provider.toml", cmd[-1])
        self.assertIn("-I -B -X utf8", cmd[-1])

    def test_rejects_credentials_in_transport_and_shell_options(self):
        for key, value in (("api_key", "secret"), ("host", "-oProxyCommand=bad"),
                           ("port", True), ("root", "/private/../shared"),
                           ("root", "/x;bad"), ("known_hosts", "missing")):
            with self.subTest(key=key):
                original = self.config.copy()
                self.config[key] = value
                self.save()
                with self.assertRaises((ValueError, TypeError)):
                    remote.ssh_command(self.transport)
                self.config = original

    def test_local_progress_and_bounded_pool_no_cross_wiring(self):
        code = """
import sys,json
for raw in sys.stdin:
 e=json.loads(raw)
 print(json.dumps({'request_id':e['request_id'],'payload':{'ok':True,'text':e['request']['prompt'],'usage':{'total_tokens':7}}}),flush=True)
"""
        with patch.object(remote, "ssh_command", return_value=[sys.executable, "-I", "-B", "-c", code]):
            pool = remote.RemotePool(self.transport, self.root, None, 4)
        self.addCleanup(pool.close)
        def call(n):
            return pool.run({"prompt": str(n)}, self.root / f"{n}.json", 10)
        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(call, range(16)))
        self.assertEqual([json.loads(r.stdout)["text"] for r in results], list(map(str, range(16))))
        self.assertLessEqual(pool.process_starts, 4)
        self.assertEqual(json.loads((self.root / "0.json").read_text())["phase"], "completed")

    def test_server_ignores_foreign_progress_path_and_refuses_low_resources(self):
        backend = remote.load_backend()
        async def complete(request, provider, progress):
            self.assertIsNone(progress)
            return {"ok": True, "text": "done"}
        config = SimpleNamespace(is_symlink=lambda: False,
                                 stat=lambda: SimpleNamespace(st_mode=0o600))
        envelope = dict(request_id="a" * 32,
                        request=dict(prompt="public", max_output_tokens=256, timeout_seconds=10),
                        progress_file="C:/never-open-this.json")
        for ready in (True, False):
            output = io.StringIO()
            with patch.object(remote, "MAX_REQUESTS", 1), \
                    patch.object(remote.sys, "flags", SimpleNamespace(isolated=1, dev_mode=False, ignore_environment=True)), \
                    patch.object(backend, "load_provider", return_value={"model_alias": "test"}), \
                    patch.object(backend, "complete", side_effect=complete) as calls, \
                    patch.object(remote, "load_backend", return_value=backend), \
                    patch.object(remote, "resource_ready", return_value=ready):
                remote.serve(config, self.root, io.BytesIO((json.dumps(envelope) + "\n").encode()),
                             output, exit_on_eof=lambda code: None)
            result = json.loads(output.getvalue())
            self.assertEqual(result["request_id"], "a" * 32)
            self.assertEqual(result["payload"]["ok"], ready)
            self.assertEqual(calls.call_count, int(ready))
        self.assertFalse((self.root / "never-open-this.json").exists())

    def test_already_retired_worker_is_replaced_before_sending(self):
        from kimi_scout_resident import BackendPool
        code = ("import json,sys\ne=json.loads(sys.stdin.readline())\n"
                "print(json.dumps({'request_id':e['request_id'],'payload':{'ok':True}}),flush=True)\n")
        pool = BackendPool(sys.executable, self.root, None, 1,
                           command=[sys.executable, "-I", "-B", "-c", code])
        self.addCleanup(pool.close)
        pool.run({"prompt": "first"}, self.root / "unused", 5)
        pool.idle.queue[0].process.wait(timeout=3)
        self.assertEqual(pool.run({"prompt": "second"}, self.root / "unused", 5).returncode, 0)
        self.assertEqual(pool.process_starts, 2)

    def test_stdin_disconnect_exits_during_active_request(self):
        code = f"""
import sys,asyncio
from types import SimpleNamespace
sys.path.insert(0,{str(SCRIPTS)!r})
import kimi_scout_remote as r
b=r.load_backend()
b.load_provider=lambda p: {{'model_alias':'test'}}
async def complete(*a):
 print('active',flush=True)
 await asyncio.sleep(60)
b.complete=complete
r.load_backend=lambda:b
r.resource_ready=lambda p:True
c=SimpleNamespace(is_symlink=lambda:False,stat=lambda:SimpleNamespace(st_mode=0o600))
r.serve(c,None,sys.stdin.buffer,sys.stdout)
"""
        process = subprocess.Popen([sys.executable, "-I", "-B", "-c", code],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: process.kill() if process.poll() is None else None)
        frame = dict(request_id="a" * 32, request={"prompt": "public"}, progress_file="unused")
        process.stdin.write((json.dumps(frame) + "\n").encode())
        process.stdin.flush()
        self.assertEqual(process.stdout.readline(), b"active\r\n" if sys.platform == "win32" else b"active\n")
        process.stdin.close()
        self.assertEqual(process.wait(timeout=3), 0)
        process.stdout.close()

    def test_controller_selects_remote_mode_and_persists_usage(self):
        import kimi_scout as scout
        from kimi_scout_resident import BackendPool
        scout.initialize(self.root)
        scout.enqueue(self.root, dict(name="remote test", commit="a" * 40,
            question="review", sources=[dict(url="https://github.com/a/b/blob/main/a.py", text="return 1")]))
        answer = {key: "" for key in ("title", "hypothesis", "baseline", "next_check",
            "duplicate_risk", "uncertainty", "knowledge_suggestion")}
        answer.update(decision="no_lead", evidence=[])
        payload = dict(ok=True, text=json.dumps(answer), tools_advertised=0,
                       tool_calls_executed=0, usage=dict(total_tokens=17))
        code = ("import json,sys\nfor raw in sys.stdin:\n e=json.loads(raw)\n"
                + " print(json.dumps({'request_id':e['request_id'],'payload':"
                + repr(payload) + "}),flush=True)\n")
        pool = BackendPool(sys.executable, self.root, None, 1,
            command=[sys.executable, "-I", "-B", "-c", code])
        self.addCleanup(pool.close)
        args = SimpleNamespace(root=self.root, hours=0, concurrency=1, max_jobs=0,
            token_budget=0, feeds=None, github_auth=False, poll_seconds=300,
            output_tokens=256, timeout=15, error_cooldown_seconds=60,
            kimi_python=sys.executable, once=True, resident_backend=False,
            remote_backend=self.transport)
        with patch.object(remote, "RemotePool", return_value=pool) as factory:
            result = scout.run(args)
        factory.assert_called_once()
        self.assertTrue(pool.closed)
        self.assertEqual(result["runtime"]["backend_mode"], "remote_ssh")
        self.assertEqual(result["runtime"]["attempted_this_run"], 1)
        self.assertEqual(result["jobs"][0]["state"], "NO_LEAD")
        with scout.connect(self.root) as db:
            self.assertEqual(db.execute("SELECT sum(charge) FROM jobs").fetchone()[0], 17)


if __name__ == "__main__":
    unittest.main()
