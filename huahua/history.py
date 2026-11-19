"""Conversation history kept locally as readable JSON."""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

from .config import APP_DIR


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


class HistoryStore:
    def __init__(self, path: Path | None = None, max_sessions: int = 30, enabled: bool = True):
        APP_DIR.mkdir(parents=True, exist_ok=True)
        self.path = path or (APP_DIR / "history.json")
        self.max_sessions = max_sessions
        self.enabled = enabled
        self.sessions: list[dict[str, Any]] = []
        self.current_id: str | None = None
        self.load()

    # ------------------------------------------------------------------
    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                self.sessions = [s for s in raw if isinstance(s, dict) and s.get("id")]
            elif isinstance(raw, dict):
                self.sessions = [s for s in raw.get("sessions", []) if isinstance(s, dict)]
                self.current_id = raw.get("current_id")
        except Exception:
            self.sessions = []
        self.sessions.sort(key=lambda s: s.get("updated", ""), reverse=True)
        if self.sessions and not self.current_id:
            self.current_id = self.sessions[0]["id"]

    def save(self) -> None:
        if not self.enabled:
            return
        data = {"version": 1, "current_id": self.current_id, "sessions": self.sessions[: self.max_sessions]}
        tmp = self.path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, self.path)
        except Exception:
            try:
                self.path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            except Exception:
                pass

    # ------------------------------------------------------------------
    def new_session(self) -> dict[str, Any]:
        s = {
            "id": uuid.uuid4().hex[:12],
            "title": "新的对话",
            "created": _now(),
            "updated": _now(),
            "messages": [],
        }
        self.sessions.insert(0, s)
        self.current_id = s["id"]
        self.sessions = self.sessions[: self.max_sessions]
        self.save()
        return s

    def current(self) -> dict[str, Any]:
        s = self.get(self.current_id) if self.current_id else None
        return s or self.new_session()

    def get(self, sid: str) -> dict[str, Any] | None:
        return next((s for s in self.sessions if s.get("id") == sid), None)

    def switch(self, sid: str) -> dict[str, Any] | None:
        s = self.get(sid)
        if s:
            self.current_id = sid
            s["updated"] = _now()
            self.save()
        return s

    def remove(self, sid: str) -> None:
        self.sessions = [s for s in self.sessions if s.get("id") != sid]
        if self.current_id == sid:
            self.current_id = self.sessions[0]["id"] if self.sessions else None
        self.save()

    def clear(self) -> None:
        self.sessions = []
        self.current_id = None
        self.save()

    def recent(self, limit: int = 8) -> list[dict[str, Any]]:
        return sorted(self.sessions, key=lambda s: s.get("updated", ""), reverse=True)[:limit]

    def append(self, message: dict[str, Any], session: dict[str, Any] | None = None) -> dict[str, Any]:
        s = session or self.current()
        message.setdefault("id", uuid.uuid4().hex[:12])
        message.setdefault("ts", _now())
        s.setdefault("messages", []).append(message)
        s["updated"] = _now()
        if s.get("title", "新的对话") in ("新的对话", "") and message.get("role") == "user":
            text = (message.get("text") or "").strip().replace("\n", " ")
            if text:
                s["title"] = text[:18] + ("…" if len(text) > 18 else "")
        # keep context bounded; old sessions still remain readable
        if len(s["messages"]) > 240:
            s["messages"] = s["messages"][-220:]
        s["updated"] = _now()
        self.sessions.sort(key=lambda x: x.get("updated", ""), reverse=True)
        self.current_id = s["id"]
        if self.get(s["id"]):
            idx = self.sessions.index(self.get(s["id"]))
            self.sessions[idx] = s
        self.save()
        return message

    def update(self, message: dict[str, Any], session: dict[str, Any] | None = None) -> None:
        s = session or self.current()
        for i, m in enumerate(s.get("messages", [])):
            if m.get("id") == message.get("id"):
                s["messages"][i] = message
                break
        s["updated"] = _now()
        self.current_id = s["id"]
        self.sessions.sort(key=lambda x: x.get("updated", ""), reverse=True)
        self.save()

    def delete_message(self, mid: str, session: dict[str, Any] | None = None) -> None:
        s = session or self.current()
        s["messages"] = [m for m in s.get("messages", []) if m.get("id") != mid]
        s["updated"] = _now()
        self.save()

    def messages_for_api(self, session: dict[str, Any] | None = None, limit: int = 16) -> list[dict[str, Any]]:
        """Convert persisted messages to a compact OpenAI-style context."""
        s = session or self.current()
        out: list[dict[str, Any]] = []
        for m in s.get("messages", [])[-limit:]:
            role = m.get("role")
            text = (m.get("text") or "").strip()
            if not text or role not in ("user", "assistant"):
                continue
            if m.get("kind") in ("error", "progress"):
                continue
            out.append({"role": role, "content": text[:12000]})
        return out
