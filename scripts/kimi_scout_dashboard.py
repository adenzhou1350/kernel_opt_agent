"""Read-only, loopback-only live viewer for a Kimi scout inbox (stdlib only).

No provider configuration, arbitrary files, agent tools or mutation endpoints are
loaded. Run independently of the scout; stopping the viewer never stops research.
"""

from __future__ import annotations

import argparse
from collections import Counter
import ctypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import sqlite3
import time
from urllib.parse import urlsplit

PAGE = Path(__file__).with_suffix(".html")
JOB_ID = re.compile(r"[0-9a-f]{24}")
MAX_FILE_BYTES = 2_000_000


def json_object(value):
    try:
        obj = json.loads(value) if isinstance(value, str) else value
        return obj if isinstance(obj, dict) else {}
    except (ValueError, TypeError):
        return {}


def read_artifact(root, relative):
    """Only caller-selected fixed artifact names, with symlink/path confinement."""
    try:
        path = (root / relative).resolve(strict=True)
        if not path.is_relative_to(root) or path.stat().st_size > MAX_FILE_BYTES:
            return {}
        return json_object(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RuntimeError):
        return {}


def process_alive(pid):
    if type(pid) is not int or pid <= 0:
        return False
    if os.name == "nt":
        # os.kill(pid, 0) is not a safe Windows liveness probe.
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.DWORD),
        ]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        try:
            code = wintypes.DWORD()
            return (
                bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code)))
                and code.value == 259
            )
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def valid_usage(value):
    if not isinstance(value, dict) or type(value.get("total_tokens")) is not int:
        return None
    if value["total_tokens"] < 0:
        return None
    keys = ("input_tokens", "output_tokens", "total_tokens", "cached_input_tokens")
    return {k: v for k in keys if type(v := value.get(k)) is int and v >= 0}


class Inbox:
    def __init__(self, root):
        self.root = Path(root).resolve(strict=True)
        database = self.root / "scout.sqlite"
        if not database.is_file() or database.resolve().parent != self.root:
            raise ValueError("expected an existing scout inbox with scout.sqlite")
        self.database = database

    def rows(self, job_id=None):
        # Do not call scout.connect(): its WAL setup/transactions are for writers.
        db = sqlite3.connect(self.database.as_uri() + "?mode=ro", uri=True, timeout=2)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA query_only=ON")
            if job_id is not None:
                return [
                    dict(row)
                    for row in db.execute("SELECT * FROM jobs WHERE id=?", (job_id,))
                ]
            return [
                dict(row)
                for row in db.execute("SELECT * FROM jobs ORDER BY created DESC")
            ]
        finally:
            db.close()

    def artifact(self, job_id, suffix):
        if not JOB_ID.fullmatch(job_id):
            return {}
        return read_artifact(self.root, f"results/{job_id}.{suffix}.json")

    def describe(self, row, now):
        result = json_object(row.get("result"))
        analysis = json_object(result.get("analysis"))
        packet = json_object(row.get("packet"))
        research = json_object(packet.get("research"))
        answer = self.artifact(row["id"], "answer")
        usage = valid_usage(result.get("usage")) or valid_usage(answer.get("usage"))
        started, finished = row.get("started"), row.get("finished")
        elapsed = max(0, (finished or now) - started) if started else 0
        live = self.artifact(row["id"], "live") if row["state"] == "RUNNING" else {}
        return {
            **{
                k: row.get(k)
                for k in (
                    "id",
                    "name",
                    "state",
                    "created",
                    "started",
                    "finished",
                    "charge",
                    "error",
                )
            },
            "repo": packet.get("repo", ""),
            "stage": research.get("stage"),
            "parent_job_id": research.get("parent_job_id"),
            "root_job_id": research.get("root_job_id"),
            "title": analysis.get("title", ""),
            "elapsed_seconds": round(elapsed, 2),
            "usage": usage,
            "has_live_output": bool(live.get("text")),
        }

    def state(self):
        now = time.time()
        runtime = read_artifact(self.root, "runtime.json")
        feed = read_artifact(self.root, "last-feed.json")
        research = read_artifact(self.root, "research.json") or None
        rows = self.rows()
        jobs = [self.describe(row, now) for row in rows]
        warnings = []
        runtime["alive"] = process_alive(runtime.get("pid"))
        if runtime.get("state") != "STOPPED" and not runtime["alive"]:
            runtime["state"] = "OFFLINE"
            warnings.append("Scout 进程未运行；页面仍可查看历史记录。")
        heartbeat = runtime.get("heartbeat_at")
        if runtime["alive"] and not heartbeat:
            warnings.append("旧版进程没有心跳；存活不代表正在生成。")
        elif runtime["alive"] and now - heartbeat > 180:
            warnings.append("Scout 心跳超过 3 分钟未更新，请检查抓取或运行状态。")
        if (self.root / "STOP").exists() and runtime["alive"]:
            warnings.append("已请求停止；在途调用可能仍在完成。")
        if len(jobs) > 500:
            warnings.append("列表仅展示最近 500 项；汇总包含全部历史任务。")
        return {
            "now": now,
            "runtime": runtime,
            "research": research,
            "summary": {
                "counts": dict(Counter(row["state"] for row in rows)),
                "total_jobs": len(jobs),
                # A review chain can contain multiple analysis calls. Even its
                # root count is not a claim of unique leads or ready PRs.
                "candidate_roots": len(
                    {
                        j["root_job_id"]
                        if isinstance(j["root_job_id"], str)
                        and JOB_ID.fullmatch(j["root_job_id"])
                        else j["id"]
                        for j in jobs
                        if j["state"] == "REVIEW"
                    }
                ),
                "reported_tokens": sum(
                    j["usage"]["total_tokens"] for j in jobs if j["usage"] is not None
                ),
                "reserved_tokens": sum(j["charge"] for j in jobs if j["usage"] is None),
                "usage_known_jobs": sum(j["usage"] is not None for j in jobs),
            },
            "feed": {
                "at": feed.get("at"),
                "errors": [s for s in feed.get("sources", []) if s.get("error")],
            },
            "jobs": jobs[:500],
            "warnings": warnings,
        }

    def detail(self, job_id):
        if not JOB_ID.fullmatch(job_id):
            raise KeyError(job_id)
        rows = self.rows(job_id)
        if not rows:
            raise KeyError(job_id)
        row = rows[0]
        request = self.artifact(job_id, "request")
        answer = self.artifact(job_id, "answer")
        live = self.artifact(job_id, "live")
        result = json_object(row.get("result"))
        packet = json_object(row.get("packet"))
        prompt = request.get("prompt")
        reconstructed = not isinstance(prompt, str)
        if reconstructed:
            # Old runs have exact evidence packets, not saved historical prompts.
            prompt = "历史公开输入材料（当时完整指令未保存）\n" + json.dumps(
                packet, ensure_ascii=False, indent=2
            )
        return {
            "job": self.describe(row, time.time()),
            "packet": packet,
            "prompt": prompt,
            "system_prompt": request.get("system_prompt"),
            "prompt_reconstructed": reconstructed,
            "analysis": result.get("analysis"),
            "answer": answer.get("text", ""),
            "live": {k: live[k] for k in ("text", "updated_at", "phase") if k in live}
            or None,
            "usage": valid_usage(result.get("usage"))
            or valid_usage(answer.get("usage")),
            "finish_reason": answer.get("finish_reason"),
        }


def make_server(root, port=8767):
    inbox = Inbox(root)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # No request text or public packet content in access logs.

        def respond(self, status, body, mime="application/json; charset=utf-8"):
            data = (
                body
                if isinstance(body, bytes)
                else json.dumps(body, ensure_ascii=False).encode("utf-8")
            )
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'",
            )
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            hosts = {
                f"127.0.0.1:{self.server.server_port}",
                f"localhost:{self.server.server_port}",
            }
            origin = self.headers.get("Origin")
            if self.headers.get("Host") not in hosts or (
                origin and origin not in {"http://" + h for h in hosts}
            ):
                self.respond(403, {"error": "local_same_origin_only"})
                return
            path = urlsplit(self.path).path
            try:
                if path == "/":
                    self.respond(200, PAGE.read_bytes(), "text/html; charset=utf-8")
                elif path == "/api/state":
                    self.respond(200, inbox.state())
                elif path.startswith("/api/jobs/"):
                    self.respond(200, inbox.detail(path.removeprefix("/api/jobs/")))
                elif path == "/health":
                    self.respond(200, {"ok": True, "read_only": True})
                else:
                    self.respond(404, {"error": "not_found"})
            except KeyError:
                self.respond(404, {"error": "job_not_found"})
            except (OSError, sqlite3.Error, ValueError):
                self.respond(503, {"error": "inbox_temporarily_unavailable"})

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8767)
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("invalid port")
    with make_server(args.root, args.port) as server:
        print(
            f"Kimi scout viewer: http://127.0.0.1:{server.server_port} (read-only)",
            flush=True,
        )
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
