"""Read-only live viewer for a Kimi scout inbox (stdlib only).

No provider configuration, arbitrary files, agent tools or mutation endpoints are
loaded. The safe default remains loopback-only; LAN exposure requires an explicit
bind address and exact allowed Host headers. Run independently of the scout;
stopping the viewer never stops research.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import re
import sqlite3
import threading
import time
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
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


def activity_summary(jobs, research, now):
    """Aggregate the full inbox; research leaves are still unvalidated output."""
    window_seconds = 900
    parents = {
        job["parent_job_id"]
        for job in jobs
        if isinstance(job["parent_job_id"], str)
    }
    repositories = {}

    def repository(repo):
        repo = repo if isinstance(repo, str) else ""
        if repo not in repositories:
            repositories[repo] = {
                "repo": repo,
                "total": 0,
                "running": 0,
                "pending": 0,
                "review_leaves": 0,
                "reproduction_leaves": 0,
                "completed": 0,
                "failed": 0,
                "reported_tokens": 0,
                "last_finished": None,
            }
        return repositories[repo]

    goals = (research or {}).get("goals", [])
    if isinstance(goals, list):
        for goal in goals:
            if isinstance(goal, dict) and isinstance(goal.get("repo"), str):
                repository(goal["repo"])

    recent = []
    for job in jobs:
        repo = repository(job["repo"])
        repo["total"] += 1
        repo["running"] += job["state"] == "RUNNING"
        repo["pending"] += job["state"] == "PENDING"
        repo["failed"] += job["state"] == "FAILED"
        leaf = job["state"] == "REVIEW" and job["id"] not in parents
        repo["review_leaves"] += leaf
        repo["reproduction_leaves"] += leaf and job["stage"] == "reproduction_plan"
        if job["usage"] is not None:
            repo["reported_tokens"] += job["usage"]["total_tokens"]
        finished = job["finished"]
        if finished is not None and job["state"] in (
            "REVIEW", "NO_LEAD", "NEEDS_CONTEXT", "FAILED"
        ):
            repo["completed"] += 1
            previous = repo["last_finished"]
            repo["last_finished"] = (
                max(previous, finished) if previous is not None else finished
            )
            if now - window_seconds <= finished <= now:
                recent.append(job)

    observed_seconds = min(
        window_seconds, max(0, now - min((job["created"] for job in jobs), default=now))
    )
    elapsed = [
        max(0, job["finished"] - job["started"])
        for job in recent
        if job["started"] is not None
    ]
    repos = sorted(repositories.values(), key=lambda repo: repo["repo"])
    return {
        "window_seconds": window_seconds,
        "observed_seconds": observed_seconds,
        "completed": len(recent),
        "completed_per_minute": (
            len(recent) * 60 / observed_seconds if observed_seconds else 0
        ),
        "failed": sum(job["state"] == "FAILED" for job in recent),
        "average_elapsed_seconds": (
            round(sum(elapsed) / len(elapsed), 2) if elapsed else None
        ),
        "last_completion": max(
            (
                repo["last_finished"]
                for repo in repos
                if repo["last_finished"] is not None
            ),
            default=None,
        ),
        "review_leaves": sum(repo["review_leaves"] for repo in repos),
        "reproduction_leaves": sum(repo["reproduction_leaves"] for repo in repos),
        "repos": repos,
    }


class Inbox:
    def __init__(self, root):
        self.root = Path(root).resolve(strict=True)
        database = self.root / "scout.sqlite"
        if not database.is_file() or database.resolve().parent != self.root:
            raise ValueError("expected an existing scout inbox with scout.sqlite")
        self.database = database
        self._snapshot_lock = threading.Lock()
        self._snapshot = None
        self._snapshot_at = 0.0

    def cached_state(self, max_age=5):
        """Single-flight the expensive historical projection for HTTP polling."""
        with self._snapshot_lock:
            now = time.monotonic()
            if self._snapshot is None or now - self._snapshot_at >= max_age:
                self._snapshot = self.state()
                self._snapshot_at = time.monotonic()
            return self._snapshot

    def rows(self, job_id=None, limit=None):
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
            if limit is not None:
                return [
                    dict(row)
                    for row in db.execute(
                        "SELECT * FROM jobs ORDER BY created DESC LIMIT ?", (limit,)
                    )
                ]
            return [
                dict(row)
                for row in db.execute("SELECT * FROM jobs ORDER BY created DESC")
            ]
        finally:
            db.close()

    def activity_rows(self):
        """Read only dashboard fields, never the large public evidence packets."""
        db = sqlite3.connect(self.database.as_uri() + "?mode=ro", uri=True, timeout=2)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA query_only=ON")
            return [
                dict(row)
                for row in db.execute(
                    """SELECT id,state,created,started,finished,charge,
                    json_extract(packet,'$.repo') AS repo,
                    json_extract(packet,'$.research.stage') AS stage,
                    json_extract(packet,'$.research.parent_job_id') AS parent_job_id,
                    json_extract(packet,'$.research.root_job_id') AS root_job_id,
                    json_extract(result,'$.usage.input_tokens') AS input_tokens,
                    json_extract(result,'$.usage.output_tokens') AS output_tokens,
                    json_extract(result,'$.usage.total_tokens') AS total_tokens,
                    json_extract(result,'$.usage.cached_input_tokens') AS cached_input_tokens
                    FROM jobs"""
                )
            ]
        finally:
            db.close()

    @staticmethod
    def activity_job(row, latest_usage):
        usage = None
        if type(row.get("total_tokens")) is int and row["total_tokens"] >= 0:
            usage = {
                key: value
                for key in (
                    "input_tokens",
                    "output_tokens",
                    "total_tokens",
                    "cached_input_tokens",
                )
                if type(value := row.get(key)) is int and value >= 0
            }
        elif row["id"] in latest_usage:
            usage = latest_usage[row["id"]]
        return {
            **row,
            "repo": row.get("repo") or "",
            "usage": usage,
        }

    def artifact(self, job_id, suffix):
        if not JOB_ID.fullmatch(job_id):
            return {}
        return read_artifact(self.root, f"results/{job_id}.{suffix}.json")

    def describe(self, row, now):
        result = json_object(row.get("result"))
        analysis = json_object(result.get("analysis"))
        packet = json_object(row.get("packet"))
        research = json_object(packet.get("research"))
        usage = valid_usage(result.get("usage"))
        if usage is None:
            usage = valid_usage(self.artifact(row["id"], "answer").get("usage"))
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
        delivery = read_artifact(self.root, "delivery/runtime.json") or None
        delivery_gpu = read_artifact(self.root, "delivery/gpu-latest.json") or None
        if delivery is not None:
            delivery["alive"] = process_alive(delivery.get("pid"))
            if not delivery["alive"] and delivery.get("state") != "STOPPED":
                delivery["state"] = "OFFLINE"
            heartbeat = delivery.get("heartbeat_at")
            delivery["heartbeat_fresh"] = (
                type(heartbeat) in (int, float) and 0 <= now - heartbeat <= 180
            )
            recent = delivery.get("jobs")
            delivery["jobs"] = (
                [job for job in recent if isinstance(job, dict)][:20]
                if isinstance(recent, list)
                else []
            )
        # The inbox can contain tens of thousands of multi-KiB evidence packets.
        # Expand only the visible tail; all-history counters use a narrow SQL
        # projection so dashboard polling cannot starve the producer database.
        rows = self.rows(limit=500)
        jobs = [self.describe(row, now) for row in rows]
        latest_usage = {
            job["id"]: job["usage"] for job in jobs if job["usage"] is not None
        }
        history = [self.activity_job(row, latest_usage) for row in self.activity_rows()]
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
        if len(history) > 500:
            warnings.append("列表仅展示最近 500 项；汇总包含全部历史任务。")
        return {
            "now": now,
            "runtime": runtime,
            "research": research,
            "delivery": delivery,
            "delivery_gpu": delivery_gpu,
            "activity": activity_summary(history, research, now),
            "summary": {
                "counts": dict(Counter(job["state"] for job in history)),
                "total_jobs": len(history),
                # A review chain can contain multiple analysis calls. Even its
                # root count is not a claim of unique leads or ready PRs.
                "candidate_roots": len(
                    {
                        j["root_job_id"]
                        if isinstance(j["root_job_id"], str)
                        and JOB_ID.fullmatch(j["root_job_id"])
                        else j["id"]
                        for j in history
                        if j["state"] == "REVIEW"
                    }
                ),
                "reported_tokens": sum(
                    j["usage"]["total_tokens"]
                    for j in history
                    if j["usage"] is not None
                ),
                "reserved_tokens": sum(
                    j["charge"] for j in history if j["usage"] is None
                ),
                "usage_known_jobs": sum(j["usage"] is not None for j in history),
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


def make_server(root, port=8767, bind="127.0.0.1", allowed_hosts=()):
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
                *allowed_hosts,
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
                    self.respond(200, inbox.cached_state())
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

    return ThreadingHTTPServer((bind, port), Handler)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8767)
    parser.add_argument(
        "--bind",
        default="127.0.0.1",
        help="listen address (default: 127.0.0.1; use 0.0.0.0 for LAN access)",
    )
    parser.add_argument(
        "--allow-host",
        action="append",
        default=[],
        help="exact additional HTTP Host header, including port; repeat as needed",
    )
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("invalid port")
    with make_server(args.root, args.port, args.bind, tuple(args.allow_host)) as server:
        print(
            f"Kimi scout viewer: http://{args.bind}:{server.server_port} (read-only)",
            flush=True,
        )
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
