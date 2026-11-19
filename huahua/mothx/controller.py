"""Qt-facing controller for a MothX ACP session."""
from __future__ import annotations

import base64
import json
import mimetypes
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QObject, Signal

from ..config import Config
from .client import AcpClient
from .runtime import MothXRuntime, find_runtime


def _text_from_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        if isinstance(content.get("text"), str):
            return content["text"]
        if content.get("type") == "text":
            return str(content.get("text") or "")
    if isinstance(content, list):
        return "".join(_text_from_content(x) for x in content)
    return ""


class AgentController(QObject):
    state_changed = Signal(str, str)  # state, message
    assistant_delta = Signal(str)
    thought_delta = Signal(str)
    tool_started = Signal(dict)
    tool_updated = Signal(dict)
    plan_updated = Signal(list)
    usage_updated = Signal(dict)
    permission_requested = Signal(dict)
    question_requested = Signal(dict)
    run_started = Signal()
    run_finished = Signal(str)
    session_ready = Signal(dict)
    failed = Signal(str)
    log = Signal(str)

    def __init__(self, config: Config, parent=None):
        super().__init__(parent)
        self.config = config
        self.runtime: MothXRuntime | None = None
        self.client: AcpClient | None = None
        self.session_id = ""
        self.cwd = ""
        self.config_options: list[dict[str, Any]] = []
        self.selected_model = str(config.get("mothx.model", "") or "")
        self.selected_mode = str(config.get("mothx.mode", "agent") or "agent")
        self.running = False
        self._initializing = False
        self._init_waiters: list[Callable[[str], None]] = []
        self._run_finished = False

    # ------------------------------------------------------------------
    @property
    def models(self) -> list[dict[str, Any]]:
        return self.runtime.models if self.runtime else []

    def _set_state(self, state: str, message: str = "") -> None:
        self.state_changed.emit(state, message)

    def ensure_client(self, callback: Callable[[str], None]) -> None:
        """Start the sidecar if needed; callback receives an error string or ''."""
        if self.client and self.client.initialized:
            callback("")
            return
        if self._initializing:
            self._init_waiters.append(callback)
            return
        self._initializing = True
        self._init_waiters.append(callback)
        self._set_state("starting", "正在启动 MothX…")
        key = self.config.api_key().strip()
        if not key:
            self._fail_init("没有配置模力方舟 API Key，先在设置里填一下。")
            return
        self.runtime = find_runtime(self.config)
        if not self.runtime.available:
            self._fail_init(
                "找不到 MothX 运行时。请把 runtime/mothx.exe 放在程序目录，"
                "或在设置里指定路径。"
            )
            return
        try:
            self.runtime.prepare(
                key,
                self.config.active_profile().get("chat_model", ""),
                self.config.active_profile().get("base_url", ""),
            )
            self.runtime.probe(key)
        except Exception as e:
            self._fail_init(str(e))
            return
        self.client = AcpClient(self.runtime, key, self)
        self.client.ready.connect(self._on_ready)
        self.client.failed.connect(self._on_client_failed)
        self.client.notification.connect(self._on_notification)
        self.client.permission_requested.connect(self._on_permission)
        self.client.question_requested.connect(self._on_question)
        self.client.log.connect(self.log.emit)
        self.client.start()
        if not self.client.alive:
            self._fail_init("MothX 进程没有启动。")
            return

        def initialized(_result: Any, error: str) -> None:
            if error:
                self._fail_init(error)
                return
            # The ready signal also fires; keep this callback for API symmetry.
        self.client.initialize(initialized)

    def _on_ready(self, result: dict[str, Any]) -> None:
        self._initializing = False
        info = result.get("agentInfo") or {}
        self._set_state("ready", f"{info.get('title', 'MothX')} {info.get('version', '')}".strip())
        waiters, self._init_waiters = self._init_waiters, []
        for cb in waiters:
            cb("")

    def _fail_init(self, message: str) -> None:
        self._initializing = False
        if self.client:
            self.client.stop()
            self.client = None
        waiters, self._init_waiters = self._init_waiters, []
        for cb in waiters:
            cb(message)
        self._set_state("error", message)
        self.failed.emit(message)

    def _on_client_failed(self, message: str) -> None:
        self.running = False
        self._initializing = False
        self._set_state("error", message)
        self.failed.emit(message)
        waiters, self._init_waiters = self._init_waiters, []
        for cb in waiters:
            cb(message)

    # ------------------------------------------------------------------
    def new_session(self, cwd: str, callback: Callable[[dict[str, Any] | None, str], None]) -> None:
        if not cwd:
            callback(None, "还没有选择工作区。")
            return
        Path(cwd).mkdir(parents=True, exist_ok=True)

        def start(error: str):
            if error:
                callback(None, error)
                return
            if not self.client:
                callback(None, "MothX 未启动。")
                return
            self.cwd = cwd
            self._set_state("starting", "正在建立任务…")

            def done(result: Any, err: str):
                if err or not isinstance(result, dict):
                    callback(None, err or "MothX 没有返回会话。")
                    return
                self.session_id = str(result.get("sessionId") or "")
                self.config_options = list(result.get("configOptions") or [])
                self._set_state("ready", "任务就绪")

                def prefs_done(pref_err: str):
                    self.session_ready.emit(result)
                    callback(result, pref_err)

                self._apply_preferences(prefs_done)

            self.client.request("session/new", {"cwd": cwd}, done)

        self.ensure_client(start)

    def _apply_preferences(self, callback: Callable[[str], None] | None = None) -> None:
        if not self.client or not self.session_id:
            if callback:
                callback("")
            return
        wanted = []
        if self.selected_mode:
            wanted.append(("mode", self.selected_mode))
        if self.selected_model:
            wanted.append(("model", self.selected_model))
        if not wanted:
            if callback:
                callback("")
            return
        remaining = len(wanted)
        errors: list[str] = []

        def one_done(err: str):
            nonlocal remaining
            if err:
                errors.append(err)
            remaining -= 1
            if remaining <= 0 and callback:
                callback(errors[0] if errors else "")

        for cid, value in wanted:
            def done(result: Any, err: str):
                if isinstance(result, dict) and result.get("configOptions"):
                    self.config_options = list(result["configOptions"])
                one_done(err)
            self.client.request(
                "session/set_config_option",
                {"sessionId": self.session_id, "configId": cid, "value": value},
                done,
            )

    # ------------------------------------------------------------------
    def send(self, text: str, attachments: list[Path] | None = None) -> None:
        if not self.client or not self.session_id:
            self.failed.emit("任务还没有建立。")
            return
        self.running = True
        self._run_finished = False
        self._set_state("working", "正在执行…")
        blocks: list[dict[str, Any]] = [{"type": "text", "text": text}]
        for path in attachments or []:
            try:
                if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}:
                    mime = mimetypes.guess_type(str(path))[0] or "image/png"
                    blocks.append(
                        {
                            "type": "image",
                            "mimeType": mime,
                            "data": base64.b64encode(path.read_bytes()).decode("ascii"),
                        }
                    )
                else:
                    mime = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
                    blocks.append(
                        {"type": "resource_link", "name": path.name, "uri": path.resolve().as_uri(), "mimeType": mime}
                    )
            except Exception:
                pass
        params = {"sessionId": self.session_id, "prompt": blocks}
        self.run_started.emit()

        def done(result: Any, err: str):
            if err:
                self._finish("error", err)
                return
            reason = ""
            if isinstance(result, dict):
                reason = str(result.get("stopReason") or "")
            self._finish("cancelled" if reason == "cancelled" else "completed", "")

        try:
            self.client.request("session/prompt", params, done)
        except Exception as e:
            self._finish("error", str(e))

    def _finish(self, reason: str, error: str = "") -> None:
        if self._run_finished:
            return
        self._run_finished = True
        self.running = False
        if error:
            self._set_state("error", error)
            self.failed.emit(error)
        elif reason == "cancelled":
            self._set_state("idle", "已停止")
        else:
            self._set_state("idle", "任务完成")
        self.run_finished.emit(reason if not error else "error")

    # ------------------------------------------------------------------
    def _on_notification(self, method: str, params: dict[str, Any]) -> None:
        if method == "session/update":
            if self.session_id and str(params.get("sessionId") or "") not in ("", self.session_id):
                return
            update = params.get("update") or {}
            kind = str(update.get("sessionUpdate") or "")
            if kind == "agent_message_chunk":
                text = _text_from_content(update.get("content"))
                if text:
                    self.assistant_delta.emit(text)
            elif kind == "agent_thought_chunk":
                text = _text_from_content(update.get("content"))
                if text:
                    self.thought_delta.emit(text)
            elif kind == "tool_call":
                self.tool_started.emit(self._tool_info(update))
            elif kind == "tool_call_update":
                self.tool_updated.emit(self._tool_info(update))
            elif kind == "plan":
                entries = update.get("entries") or []
                if isinstance(entries, list):
                    self.plan_updated.emit(entries)
            elif kind == "usage_update":
                self.usage_updated.emit(
                    {
                        "used": update.get("used", 0),
                        "size": update.get("size", 0),
                        "cost": update.get("cost") or {},
                    }
                )
            return

        if method == "_mothx/session_event":
            event = str(params.get("event") or "")
            status = str(params.get("status") or "")
            if event == "run_status":
                if status == "running":
                    self._set_state("working", "正在执行…")
                elif status in ("completed", "cancelled", "error"):
                    if not self.running:
                        self._set_state("idle", "任务结束")
            elif event == "terminal":
                if status == "completed":
                    self._finish("completed")
                elif status == "cancelled":
                    self._finish("cancelled")
                elif status in ("error", "failed"):
                    self._finish("error", str(params.get("error") or "任务失败"))
            elif event == "subagent":
                self._set_state("working", str(params.get("memberDisplayName") or "子 Agent 工作中"))
            elif event == "turn_started":
                self._set_state("working", "正在思考…")
            elif event == "retry":
                self._set_state("working", "重试中…")

    @staticmethod
    def _tool_info(update: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(update.get("toolCallId") or ""),
            "title": str(update.get("title") or "工具"),
            "kind": str(update.get("kind") or ""),
            "status": str(update.get("status") or ""),
            "raw_input": update.get("rawInput") or {},
            "raw_output": update.get("rawOutput") or {},
            "locations": update.get("locations") or [],
        }

    # ------------------------------------------------------------------
    def _on_permission(self, message: dict[str, Any]) -> None:
        params = message.get("params") or {}
        tool = params.get("toolCall") or {}
        options = []
        for opt in params.get("options") or []:
            oid = str(opt.get("optionId") or "")
            kind = str(opt.get("kind") or "")
            raw_name = str(opt.get("name") or oid or "允许")
            marker = f"{oid} {kind} {raw_name}".lower()
            if "allow" in marker:
                name = "本会话允许" if any(x in marker for x in ("always", "session", "persist")) else "允许一次"
            elif "reject" in marker or "deny" in marker:
                name = "拒绝"
            else:
                name = raw_name
            options.append({"id": oid, "name": name, "kind": kind})
        self._set_state("waiting", "等你确认…")
        self.permission_requested.emit(
            {
                "request_id": message.get("id"),
                "session_id": params.get("sessionId") or self.session_id,
                "title": str(tool.get("title") or "工具操作"),
                "kind": str(tool.get("kind") or ""),
                "raw_input": tool.get("rawInput") or {},
                "options": options,
            }
        )

    def _on_question(self, message: dict[str, Any]) -> None:
        params = message.get("params") or {}
        self._set_state("waiting", "等你回答…")
        options_raw = params.get("options") or []
        options: list[dict[str, str]] = []
        if isinstance(options_raw, list):
            for item in options_raw:
                if isinstance(item, dict):
                    options.append({"id": str(item.get("id") or item.get("label") or ""), "label": str(item.get("label") or item.get("id") or "")})
                elif isinstance(item, str):
                    options.append({"id": item, "label": item})
        self.question_requested.emit(
            {
                "request_id": message.get("id"),
                "method": message.get("method"),
                "title": str(params.get("title") or "华华想确认一下"),
                "question": str(params.get("question") or params.get("prompt") or params.get("message") or ""),
                "options": options,
                "multi": bool(params.get("multi")),
            }
        )

    def answer_permission(self, request_id: Any, option_id: str) -> None:
        if not self.client:
            return
        if option_id:
            self.client.respond(
                request_id,
                {"outcome": {"outcome": "selected", "optionId": option_id}},
            )
        else:
            self.client.respond(request_id, {"outcome": {"outcome": "cancelled"}})
        self._set_state("working", "继续执行…")

    def answer_question(self, request_id: Any, answer: str) -> None:
        if not self.client:
            return
        self.client.respond(request_id, {"answer": answer})
        self._set_state("working", "继续执行…")

    # ------------------------------------------------------------------
    def set_model(self, model: str) -> None:
        self.selected_model = model
        self.config.set("mothx.model", model)
        self.config.save()
        if self.client and self.session_id:
            self.client.request(
                "session/set_config_option",
                {"sessionId": self.session_id, "configId": "model", "value": model},
                lambda result, err: self._on_config_option(result, err),
            )

    def set_mode(self, mode: str) -> None:
        self.selected_mode = mode
        self.config.set("mothx.mode", mode)
        self.config.save()
        if self.client and self.session_id:
            self.client.request(
                "session/set_config_option",
                {"sessionId": self.session_id, "configId": "mode", "value": mode},
                lambda result, err: self._on_config_option(result, err),
            )

    def _on_config_option(self, result: Any, error: str) -> None:
        if isinstance(result, dict) and result.get("configOptions"):
            self.config_options = list(result["configOptions"])

    def cancel(self) -> None:
        if self.client and self.session_id:
            try:
                self.client.request("session/cancel", {"sessionId": self.session_id}, lambda *_: None)
            except Exception:
                pass
            self._set_state("idle", "已停止")

    def new_task(self) -> None:
        if self.client and self.session_id:
            try:
                self.client.request("session/close", {"sessionId": self.session_id}, lambda *_: None)
            except Exception:
                pass
        self.session_id = ""
        self.config_options = []
        self.running = False
        self._run_finished = False
        self._set_state("ready" if self.client and self.client.initialized else "idle", "新任务")

    def shutdown(self) -> None:
        if self.client:
            self.client.stop()
            self.client = None
        self.session_id = ""
        self.running = False
