"""Matched HTTPX admission and sandbox controls; no network/model/container runs."""

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import kimi_scout_delivery as delivery
import kimi_scout_delivery_source as source_loader
import kimi_scout_verify as verify
import scout_httpx_cpu as httpx_cpu


class HttpxCpuTests(unittest.TestCase):
    def source(self):
        text = "from ._urls import URL\n"
        return {
            "repo": "encode/httpx",
            "commit": httpx_cpu.COMMIT,
            "path": "httpx/_api.py",
            "source": text,
            "sha256": hashlib.sha256(text.encode()).hexdigest(),
            "package_context_required": True,
            "required_dependency_modules": ["httpx"],
        }

    def test_default_remains_blocked_and_opt_in_requires_exact_source(self):
        source = self.source()
        with self.assertRaises(delivery.UnsupportedEnvironment):
            delivery.choose_profile(source)
        self.assertEqual(
            delivery.choose_profile(source, httpx_native=True), httpx_cpu.PROFILE
        )
        for field, value in (
            ("commit", "0" * 40),
            ("sha256", "0" * 64),
            ("path", "tests/test_client.py"),
            ("path", "httpx/../secret.py"),
        ):
            with self.subTest(field=field, value=value):
                invalid = dict(source, **{field: value})
                self.assertFalse(httpx_cpu.source_supported(invalid))
                with self.assertRaises(delivery.UnsupportedEnvironment):
                    delivery.choose_profile(invalid, httpx_native=True)
        self.assertFalse(httpx_cpu.source_supported(dict(source, repo="private/httpx")))

    def test_module_paths_and_baseline_identity_are_not_interpreted_as_code(self):
        self.assertEqual(httpx_cpu.module_name("httpx/_urlparse.py"), "httpx._urlparse")
        self.assertEqual(httpx_cpu.module_name("httpx/__init__.py"), "httpx")
        for path in (
            "httpx/../x.py",
            "other/x.py",
            "httpx/x.py,readonly",
            "httpx/x.py\n",
        ):
            with self.subTest(path=path), self.assertRaises(ValueError):
                httpx_cpu.module_name(path)
        with self.assertRaises(ValueError):
            httpx_cpu.harness("httpx/_api.py", "not a hash", verify.HARNESS)

    def test_controller_check_precedes_subject_and_test_execution(self):
        harness = httpx_cpu.harness("httpx/_api.py", "a" * 64, verify.HARNESS)
        self.assertLess(
            harness.index("original.read_bytes()"), harness.index("target.write_bytes")
        )
        self.assertLess(
            harness.index("target.write_bytes"), harness.index("import httpx")
        )
        self.assertLess(
            harness.index("wrong HTTPX subject import"), harness.index("suite =")
        )
        self.assertIn("sys.path.insert(0, str(scratch))", harness)
        self.assertIn("shutil.copytree(root / 'httpx'", harness)
        args = verify.command(
            "/private/subject.py",
            "/private/test.py",
            "kimi-verify-" + "c" * 32,
            profile=httpx_cpu.PROFILE,
            module_path="httpx/_api.py",
            baseline_sha256="a" * 64,
        )
        self.assertIn(httpx_cpu.IMAGE, args)
        self.assertEqual(args[args.index("--memory") + 1], "768m")
        self.assertIn("--read-only", args)
        self.assertEqual(args[args.index("--network") + 1], "none")
        self.assertNotIn("--gpus", args)
        self.assertNotIn("--privileged", args)

    def test_two_arms_share_baseline_byte_identity_and_revision(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = [Path(directory) / (name + ".py") for name in ("b", "c", "t")]
            for index, path in enumerate(paths):
                path.write_bytes(f"# fixture {index}\n".encode())
            with (
                patch.object(verify.sys, "platform", "linux"),
                patch.object(
                    verify,
                    "run_case",
                    return_value={
                        "inconclusive": False,
                        "cleanup_ok": True,
                    },
                ) as run,
            ):
                result = verify.verify(
                    *paths,
                    profile=httpx_cpu.PROFILE,
                    module_path="httpx/_api.py",
                    source_commit=httpx_cpu.COMMIT,
                )
                expected = hashlib.sha256(paths[0].read_bytes()).hexdigest()
                self.assertEqual(run.call_count, 2)
                self.assertTrue(
                    all(
                        c.kwargs["baseline_sha256"] == expected
                        for c in run.call_args_list
                    )
                )
                self.assertEqual(result["source_commit"], httpx_cpu.COMMIT)
                self.assertEqual(result["claim_scope"], httpx_cpu.CLAIM_SCOPE)
                self.assertEqual(result["label"], "TEST_RESULT_NOT_PR_READY")
                with self.assertRaisesRegex(ValueError, "new reviewed image"):
                    verify.verify(
                        *paths, profile=httpx_cpu.PROFILE, source_commit="0" * 40
                    )

    def test_loader_carries_actual_raw_identity_and_httpx_relative_context(self):
        path = "httpx/_api.py"
        url = (
            f"https://raw.githubusercontent.com/encode/httpx/{httpx_cpu.COMMIT}/{path}"
        )
        lead = {
            "repo": "encode/httpx",
            "commit": httpx_cpu.COMMIT,
            "packet": {
                "repo": "encode/httpx",
                "sources": [{"url": url, "text": "clipped"}],
            },
        }
        text = "from ._urls import URL\n"

        def fetch(address, **kwargs):
            if address == url:
                return text
            return json.dumps(
                {"full_name": "encode/httpx", "private": False, "visibility": "public"}
            )

        with patch.object(source_loader.scout, "fetch", side_effect=fetch):
            source = source_loader.load_source(lead, allow_dependencies=True)
        self.assertEqual(source["commit"], httpx_cpu.COMMIT)
        self.assertEqual(source["repo"], "encode/httpx")
        self.assertTrue(source["package_context_required"])
        self.assertTrue(httpx_cpu.source_supported(source))

    def test_worker_threads_exact_path_and_revision_without_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            args = SimpleNamespace(
                root=Path(directory),
                execution_concurrency=1,
                concurrency=1,
                httpx_native=True,
                github_auth=False,
            )
            worker = delivery.Delivery(args)
            delivery.initialize(worker.root)
            source = self.source()
            source.update(source="def value():\n    return 1\n")
            source["sha256"] = hashlib.sha256(source["source"].encode()).hexdigest()
            source["url"] = (
                "https://raw.githubusercontent.com/encode/httpx/"
                + httpx_cpu.COMMIT
                + "/httpx/_api.py"
            )
            lead = {
                "id": "native-fixture",
                "repo": "encode/httpx",
                "commit": httpx_cpu.COMMIT,
                "canonical_key": "native-fixture",
                "packet": {},
                "analysis": {"title": "fixture", "hypothesis": "fixture only"},
            }
            delivery.stage(worker.root, [lead])
            job = delivery.claim(worker.root)
            proposal = {
                "decision": "test",
                "reason": "offline wiring fixture",
                "test_code": "import unittest\nimport subject\nclass Tests(unittest.TestCase):\n"
                "    def test_regression(self): self.assertEqual(subject.value(), 2)\n"
                "    def test_control(self): self.assertIsInstance(subject.value(), int)\n",
                "edits": [{"old": "return 1", "new": "return 2"}],
            }
            result = {
                "inconclusive": False,
                "before": {"exit_code": 1, "reported_tests_run": 2},
                "fixed": {"exit_code": 0, "reported_tests_run": 2},
            }
            with (
                patch.object(delivery, "load_source", return_value=source),
                patch.object(worker, "model", return_value=proposal),
                patch.object(worker, "sandbox", return_value=result) as sandbox,
            ):
                state = worker.execute(job)
            self.assertEqual(state, delivery.OWNER_STATE)
            self.assertEqual(
                sandbox.call_args.args[2:],
                (httpx_cpu.PROFILE, source["path"], httpx_cpu.COMMIT),
            )
            self.assertFalse(result["qualified"])


if __name__ == "__main__":
    unittest.main()
