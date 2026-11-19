"""Minimal ACP v1 client for `mothx acp` (JSON-RPC 2.0 over stdio)."""
from __future__ import annotations

import json
import os
import subprocess
import threading
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QObject, Signal

from .runtime import MothXRuntime


class AcpClient(QObject):
    raw_line = Signal(str)
    ready = Signal(dict)
    failed = Signal(str)
    notification = Signal(str, dict)
    permission_requested = Signal(dict)
    question_requested = Signal(dict)
    exited = Signal(int)
    log = Signal(str)

    def __init__(self, runtime: MothXRuntime, key: str, parent=None):
        super().__init__(parent)
        self.runtime = runtime
        self.key = key
        self.process: subprocess.Popen | None = None
        self._id = 0
        self._lock = threading.Lock()
        self._callbacks: dict[int, Callable[[Any, str], None]] = {}
        self._stderr_lines: list[str] = []
        self._stopping = False
        self._initialized = False
        self.features: list[str] = []
        self.raw_line.connect(self._on_line)

    # ------------------------------------------------------------------
    @property
    def alive(self) -> bool:
        return self.process is not None and self.process.poll() is None

    @property
    def initialized(self) -> bool:
        return self._initialized and self.alive

    def start(self) -> None:
        if self.alive:
            return
        self._stopping = False
        self._initialized = False
        env = self.runtime.environment(self.key)
        try:
            self.process = subprocess.Popen(
                self.runtime.command(),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(self.runtime.config_dir),
                env=env,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception as e:
            self.failed.emit(f"启动 MothX 失败：{e}")
            return
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()

    def _read_stdout(self) -> None:
        proc = self.process
        if not proc or not proc.stdout:
            return
        for line in iter(proc.stdout.readline, ""):
            if line:
                self.raw_line.emit(line)
        code = proc.poll() if proc else -1
        if not self._stopping:
            self.exited.emit(int(code or 0))
            tail = "\n".join(self._stderr_lines[-8:]).strip()
            self.failed.emit("MothX 进程已退出。" + (f"\n{tail}" if tail else ""))

    def _read_stderr(self) -> None:
        proc = self.process
        if not proc or not proc.stderr:
            return
        for line in iter(proc.stderr.readline, ""):
            line = line.rstrip("\r\n")
            if line:
                self._stderr_lines.append(line)
                self._stderr_lines = self._stderr_lines[-80:]
                self.log.emit(line)

    # ------------------------------------------------------------------
    def request(self, method: str, params: dict[str, Any] | None = None,
                callback: Callable[[Any, str], None] | None = None) -> int:
        with self._lock:
            self._id += 1
            rid = self._id
            if callback:
                self._callbacks[rid] = callback
        self._write({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})
        return rid

    def respond(self, request_id: Any, result: Any) -> None:
        self._write({"jsonrpc": "2.0", "id": request_id, "result": result})

    def respond_error(self, request_id: Any, message: str) -> None:
        self._write({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32603, "message": message}})

    def _write(self, payload: dict[str, Any]) -> None:
        proc = self.process
        if not proc or not proc.stdin or proc.poll() is not None:
            raise RuntimeError("MothX 未运行")
        data = json.dumps(payload, ensure_ascii=False) + "\n"
        with self._lock:
            proc.stdin.write(data)
            proc.stdin.flush()

    # ------------------------------------------------------------------
    def initialize(self, callback: Callable[[Any, str], None]) -> None:
        def done(result: Any, error: str):
            if not error and isinstance(result, dict):
                self._initialized = True
                meta = result.get("_meta") or {}
                mothx_meta = meta.get("mothx.dev") or {}
                if not mothx_meta:
                    caps = result.get("agentCapabilities") or {}
                    mothx_meta = ((caps.get("_meta") or {}).get("mothx.dev") or {})
                self.features = list(mothx_meta.get("features") or [])
                self.ready.emit(result)
            callback(result, error)

        self.request(
            "initialize",
            {
                "protocolVersion": 1,
                "clientCapabilities": {},
                "clientInfo": {"name": "HuaHua", "title": "华华", "version": "1.1"},
            },
            done,
        )

    def _on_line(self, line: str) -> None:
        line = line.strip()
        if not line:
            return
        try:
            msg = json.loads(line)
        except Exception:
            self.log.emit(line[:500])
            return
        # Response to one of our requests.
        if "id" in msg and ("result" in msg or "error" in msg):
            rid = msg.get("id")
            cb = self._callbacks.pop(rid, None)
            if cb:
                err = ""
                if msg.get("error"):
                    e = msg["error"]
                    err = e.get("message", str(e)) if isinstance(e, dict) else str(e)
                cb(msg.get("result"), err)
            return
        method = str(msg.get("method") or "")
        params = msg.get("params") or {}
        if method == "session/request_permission":
            self.permission_requested.emit({"id": msg.get("id"), "method": method, "params": params})
        elif method in ("mothx/requestQuestion", "_mothx/request_question", "elicitation/create"):
            self.question_requested.emit({"id": msg.get("id"), "method": method, "params": params})
        else:
            self.notification.emit(method, params)

    # ------------------------------------------------------------------
    def stop(self) -> None:
        self._stopping = True
        self._initialized = False
        proc = self.process
        if not proc:
            return
        try:
            if proc.stdin:
                proc.stdin.close()
        except Exception:
            pass
        if proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        self.process = None
