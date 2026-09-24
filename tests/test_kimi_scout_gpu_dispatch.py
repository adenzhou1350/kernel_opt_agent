"""Offline tests; these never connect to a worker or execute GPU code."""

import hashlib
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import kimi_scout_gpu_dispatch as dispatch

GPU = "GPU-36ff58ec-0188-f3a9-d932-0c3a4b3d0338"


def completed(code=0, output=b""):
    return types.SimpleNamespace(returncode=code, stdout=output, stderr=b"")


class DispatchTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        hashes = {}
        paths = {}
        for name in ("baseline", "candidate", "test"):
            path = root / (name + ".py")
            payload = ("# " + name + "\n").encode()
            path.write_bytes(payload)
            paths[name] = str(path)
            hashes[name] = hashlib.sha256(payload).hexdigest()
        manifest = root / "reviewed.json"
        manifest.write_text(json.dumps(hashes), encoding="utf-8")
        self.args = types.SimpleNamespace(
            **paths,
            reviewed_sha256=str(manifest),
            host="worker.example.test",
            port=31201,
            gpu_uuid=GPU,
            python="/usr/bin/python3",
        )

    def test_plan_checks_reviewed_bytes_and_fixed_remote_names(self):
        plan = dispatch.dispatch_plan(self.args)
        self.assertEqual(
            plan["reviewed_sha256"]["candidate"],
            hashlib.sha256(b"# candidate\n").hexdigest(),
        )
        self.assertEqual(
            plan["remote_names"],
            ["baseline.py", "candidate.py", "test.py", "reviewed.json", "verify.py"],
        )
        self.assertIn("--gpu-uuid", plan["command"])
        self.assertIn(GPU, plan["command"])
        self.args.host = "worker;touch /tmp/bad"
        with self.assertRaisesRegex(ValueError, "host"):
            dispatch.dispatch_plan(self.args)

    def test_tampered_input_rejected_before_network(self):
        Path(self.args.candidate).write_text("changed\n", encoding="utf-8")
        with mock.patch.object(dispatch, "bounded_run") as run:
            with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
                dispatch.dispatch_plan(self.args)
            run.assert_not_called()

    def test_worker_result_requires_exact_transfer_and_verdict(self):
        plan = dispatch.dispatch_plan(self.args)
        hash_output = "".join(
            f"{digest}  {name}\n" for name, digest in plan["remote_file_sha256"].items()
        ).encode()
        report = {
            "scope": "OWNER_REVIEWED_SINGLE_MODULE_GPU_SCREEN_NOT_UPSTREAM_SUITE",
            "qualified": False,
            "reviewed_sha256": plan["reviewed_sha256"],
            "gpu_uuid": GPU,
            "screen_passed": True,
        }
        replies = [completed() for _ in range(6)] + [
            completed(output=hash_output),
            completed(output=json.dumps(report).encode()),
        ]
        with mock.patch.object(dispatch, "bounded_run", side_effect=replies) as run:
            result = dispatch.execute(plan)
        self.assertTrue(result["report"]["screen_passed"])
        self.assertEqual(run.call_count, 8)
        bad = [completed() for _ in range(6)] + [
            completed(output=hash_output.replace(b"a", b"b", 1))
        ]
        with (
            mock.patch.object(dispatch, "bounded_run", side_effect=bad) as run,
            self.assertRaisesRegex(RuntimeError, "hash mismatch"),
        ):
            dispatch.execute(plan)
        self.assertEqual(run.call_count, 7)


if __name__ == "__main__":
    unittest.main()
