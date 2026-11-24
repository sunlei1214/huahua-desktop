"""Persistent settings for 华华."""
from __future__ import annotations

import copy
import json
import os
import uuid
from pathlib import Path
from typing import Any

from . import secrets

APP_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / "HuaHua"
OLD_APP_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / "XiaoZhi"
CONFIG_PATH = APP_DIR / "config.json"
LOG_PATH = APP_DIR / "error.log"


def migrate_legacy_data() -> None:
    """Keep the key, history and window position from the earlier 小织 build."""
    try:
        if OLD_APP_DIR.exists() and not CONFIG_PATH.exists():
            APP_DIR.mkdir(parents=True, exist_ok=True)
            for name in ("config.json", "history.json"):
                src = OLD_APP_DIR / name
                if src.exists():
                    (APP_DIR / name).write_bytes(src.read_bytes())
            # A fresh identity for the 华华/熙熙 release: start bottom-right,
            # keep the user's key/history, and use the new作品 folder when the
            # old one was never actually used.
            cfg = APP_DIR / "config.json"
            if cfg.exists():
                raw = json.loads(cfg.read_text(encoding="utf-8"))
                appearance = raw.setdefault("appearance", {})
                appearance.setdefault("character", "huahua")
                appearance["position"] = None
                storage = raw.setdefault("storage", {})
                old_out = Path(storage.get("output_dir", ""))
                if "小织作品" in str(old_out):
                    new_out = default_output_dir()
                    old_empty = not old_out.exists() or not any(
                        p.is_file() for p in old_out.rglob("*")
                    )
                    if old_empty:
                        try:
                            if old_out.exists() and not new_out.exists():
                                old_out.rename(new_out)
                        except Exception:
                            pass
                        storage["output_dir"] = str(new_out)
                raw.setdefault("ui", {})["last_session"] = None
                cfg.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

MODEL_CHAT = "DeepSeek-V4.1-Flash-1017"
MODEL_IMAGE = "qwen-image-2.0-pro"
MODEL_VIDEO = "HappyHorse-1.0"
MODEL_TTS = "Qwen3-TTS"
BASE_URL = "https://api.moark.com/v1"


def default_output_dir() -> Path:
    pictures = Path.home() / "Pictures"
    if not pictures.exists():
        pictures = Path.home()
    return pictures / "华华作品"


def new_profile(name: str = "模力方舟", key: str = "") -> dict[str, Any]:
    return {
        "id": uuid.uuid4().hex[:10],
        "name": name,
        "base_url": BASE_URL,
        "api_key_enc": secrets.protect(key),
        "chat_model": MODEL_CHAT,
        "image_model": MODEL_IMAGE,
        "video_model": MODEL_VIDEO,
        "tts_model": MODEL_TTS,
        "tts_speaker": "Vivian",
        "tts_instruction": "温柔、轻快、干净，像邻家女孩在耳边说话",
        "timeout": 180,
        "video_timeout": 1800,
    }


def default_config() -> dict[str, Any]:
    key = secrets.find_work_key()
    profile = new_profile(key=key)
    return {
        "version": 1,
        "profiles": [profile],
        "active_profile": profile["id"],
        "appearance": {
            "character": "huahua",
            "size": 260,
            "opacity": 100,
            "always_on_top": True,
            "animations": True,
            "bubble": True,
            "walk": False,
            "position": None,
        },
        "storage": {
            "output_dir": str(default_output_dir()),
            "auto_open": False,
            "max_history": 30,
            "save_history": True,
        },
        "mothx": {
            "runtime_path": "",
            "workspace": "",
            "mode": "agent",
            "model": "",
            "thinking": "medium",
        },
        "behavior": {
            "notify": True,
            "sound": True,
            "sleep_minutes": 8,
            "focus_minutes": 25,
            "autostart": False,
            "deep_think": False,
            "enter_to_send": True,
        },
        "ui": {
            "chat_pos": None,
            "last_session": None,
            "onboarded": False,
        },
        "meta": {
            "key_imported": bool(key),
        },
    }


class Config:
    def __init__(self, path: Path = CONFIG_PATH):
        self.path = path
        if path == CONFIG_PATH:
            migrate_legacy_data()
        self.data: dict[str, Any] = default_config()
        self.load()

    @property
    def character(self) -> str:
        key = self.get("appearance.character", "huahua")
        return key if key in ("huahua", "xixi") else "huahua"

    # ------------------------------------------------------------------
    def load(self) -> None:
        if not self.path.exists():
            self.save()
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("invalid config")
            merged = default_config()
            _deep_update(merged, raw)
            # Remove the auto-generated profile if the saved config has profiles.
            if raw.get("profiles"):
                merged["profiles"] = raw["profiles"]
                merged["active_profile"] = raw.get("active_profile") or raw["profiles"][0]["id"]
            for profile in merged.get("profiles", []):
                if profile.get("video_model") in (None, "", "Duix-Avatar"):
                    profile["video_model"] = MODEL_VIDEO
            self.data = merged
        except Exception:
            self.data = default_config()
            self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            os.replace(tmp, self.path)
        except OSError:
            self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass

    # ------------------------------------------------------------------
    def get(self, path: str, default: Any = None) -> Any:
        cur: Any = self.data
        for part in path.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur

    def set(self, path: str, value: Any) -> None:
        parts = path.split(".")
        cur = self.data
        for part in parts[:-1]:
            if not isinstance(cur.get(part), dict):
                cur[part] = {}
            cur = cur[part]
        cur[parts[-1]] = value

    # ------------------------------------------------------------------
    def profiles(self) -> list[dict[str, Any]]:
        return self.data.get("profiles", [])

    def active_profile(self) -> dict[str, Any]:
        pid = self.data.get("active_profile")
        for p in self.profiles():
            if p.get("id") == pid:
                return p
        if self.profiles():
            return self.profiles()[0]
        p = new_profile()
        self.data["profiles"] = [p]
        self.data["active_profile"] = p["id"]
        return p

    def profile_by_id(self, pid: str) -> dict[str, Any] | None:
        return next((p for p in self.profiles() if p.get("id") == pid), None)

    def set_active_profile(self, pid: str) -> None:
        if self.profile_by_id(pid):
            self.data["active_profile"] = pid
            self.save()

    def api_key(self, profile: dict[str, Any] | None = None) -> str:
        p = profile or self.active_profile()
        return secrets.unprotect(p.get("api_key_enc", ""))

    def set_api_key(self, key: str, profile: dict[str, Any] | None = None) -> None:
        p = profile or self.active_profile()
        p["api_key_enc"] = secrets.protect(key.strip())
        self.save()

    def is_configured(self) -> bool:
        return bool(self.api_key())

    # ------------------------------------------------------------------
    @property
    def output_dir(self) -> Path:
        raw = self.get("storage.output_dir") or str(default_output_dir())
        p = Path(raw).expanduser()
        return p

    def ensure_dirs(self) -> None:
        try:
            for sub in ("图片", "视频", "音频", "缓存"):
                (self.output_dir / sub).mkdir(parents=True, exist_ok=True)
        except Exception:
            fallback = Path.home() / "华华作品"
            self.set("storage.output_dir", str(fallback))
            for sub in ("图片", "视频", "音频", "缓存"):
                (fallback / sub).mkdir(parents=True, exist_ok=True)
        APP_DIR.mkdir(parents=True, exist_ok=True)

    def snapshot(self) -> dict[str, Any]:
        return copy.deepcopy(self.data)


def _deep_update(base: dict[str, Any], other: dict[str, Any]) -> None:
    for k, v in other.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_update(base[k], v)
        else:
            base[k] = v


def autostart_command() -> str:
    """A cmd wrapper placed in Startup that launches the app silently."""
    import sys

    exe = Path(sys.executable)
    if getattr(sys, "frozen", False):
        target = f'"{exe}"'
    else:
        pyw = exe.with_name("pythonw.exe")
        target = f'"{pyw if pyw.exists() else exe}" "{Path(__file__).resolve().parent.parent / "main.py"}"'
    return "@echo off\r\nstart \"\" " + target + "\r\n"


def set_autostart(enabled: bool) -> tuple[bool, str]:
    startup = Path(os.environ.get("APPDATA", str(Path.home()))) / "Microsoft/Windows/Start Menu/Programs/Startup"
    f = startup / "华华.cmd"
    old = startup / "小织.cmd"
    try:
        startup.mkdir(parents=True, exist_ok=True)
        old.unlink(missing_ok=True)
        if enabled:
            f.write_text(autostart_command(), encoding="gbk", errors="ignore")
        else:
            f.unlink(missing_ok=True)
        return True, ""
    except Exception as e:
        return False, str(e)
