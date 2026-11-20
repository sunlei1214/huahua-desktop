"""Locate, configure and launch the MothX Agent runtime.

The runtime is an external sidecar (`runtime/mothx.exe`) rather than a Python
dependency.  It is launched as `mothx acp` and speaks ACP JSON-RPC over stdio.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .. import theme
from ..config import APP_DIR, Config

MOTHX_RELEASE = "https://github.com/oschina/mothx/releases"
MOTHX_STABLE = "v1.3.107"

# Curated through MoArk.  The active chat model is added automatically if it
# differs from this list.
MODEL_CHOICES: list[dict[str, Any]] = [
    {
        "id": "DeepSeek-V4.1-Flash-1017",
        "name": "DeepSeek V4.1 Flash 1017",
        "contextWindow": 1_000_000,
        "maxTokens": 384_000,
        "reasoning": True,
        "compat": {"thinkingFormat": "deepseek-v4.1"},
        "input": ["text", "image"],
        "badges": ["工具", "视觉", "长上下文"],
    },
    {
        "id": "Qwen4-Max",
        "name": "Qwen4 Max",
        "contextWindow": 1_000_000,
        "maxTokens": 384_000,
        "reasoning": True,
        "input": ["text", "image"],
        "badges": ["工具", "视觉", "推理"],
    },
    {
        "id": "Kimi-K3.1-Pro",
        "name": "Kimi K3.1 Pro",
        "contextWindow": 1_000_000,
        "maxTokens": 65_536,
        "reasoning": True,
        "input": ["text", "image"],
        "badges": ["工具", "视觉", "推理"],
    },
]


@dataclass
class MothXRuntime:
    exe: Path
    config_dir: Path
    models: list[dict[str, Any]]
    version: str = ""
    error: str = ""

    @property
    def available(self) -> bool:
        return self.exe.exists() and not self.error

    @property
    def settings_path(self) -> Path:
        return self.config_dir / "settings.json"

    def prepare(self, key: str, default_model: str = "", base_url: str = "") -> None:
        """Write app-local MothX settings, never touching the user's global config."""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        settings = {
            "defaultProvider": "moark",
            "defaultModel": default_model or self.models[0]["id"],
            "defaultMode": "agent",
            "defaultThinkingLevel": "medium",
            "providers": {
                "moark": {
                    "baseUrl": (base_url or "https://api.moark.com/v1").rstrip("/"),
                    "apiKey": "${MOARK_API_KEY}",
                    "api": "openai-chat",
                    "models": [{k: v for k, v in m.items() if k != "badges"} for m in self.models],
                }
            },
            "enablePlanTool": True,
            "contextFiles": {"enabled": True},
            "approval": {"confirmBeforeWrite": True},
        }
        tmp = self.settings_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.settings_path)

    def environment(self, key: str) -> dict[str, str]:
        env = os.environ.copy()
        env["MOTHX_DIR"] = str(self.config_dir)
        env["MOARK_API_KEY"] = key
        env["MOTHX_ACP_PERMISSION_TIMEOUT"] = "10m"
        env["MOTHX_ACP_QUESTION_TIMEOUT"] = "10m"
        env["NO_COLOR"] = "1"
        return env

    def command(self) -> list[str]:
        return [
            str(self.exe),
            "acp",
            "--mode",
            "agent",
            "--multi-agent",
            "--permission-timeout",
            "10m",
            "--question-timeout",
            "10m",
        ]

    def probe(self, key: str) -> str:
        """Return a friendly version string; raises RuntimeError on failure."""
        if not self.exe.exists():
            raise RuntimeError(f"找不到 MothX 运行时：{self.exe}")
        try:
            p = subprocess.run(
                [str(self.exe), "--version"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=12,
                env=self.environment(key),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception as e:
            raise RuntimeError(f"MothX 无法启动：{e}") from e
        out = (p.stdout or p.stderr or "").strip().splitlines()
        self.version = out[-1] if out else ""
        if p.returncode != 0:
            raise RuntimeError(self.version or f"MothX 返回 {p.returncode}")
        self.error = ""
        return self.version


def _app_root() -> Path:
    return theme.ROOT


def _candidate_paths(config: Config | None = None) -> list[Path]:
    candidates: list[Path] = []
    if config is not None:
        raw = str(config.get("mothx.runtime_path", "") or "").strip()
        if raw:
            candidates.append(Path(raw).expanduser())
    env_bin = os.environ.get("MOTHX_BIN", "").strip()
    if env_bin:
        candidates.append(Path(env_bin).expanduser())
    names = ["mothx.exe", "mothx"] if os.name == "nt" else ["mothx"]
    roots = [_app_root(), Path(sys.executable).resolve().parent, Path.cwd()]
    # PyInstaller onefile unpacks bundled data under _MEIPASS.  Keep this
    # explicit so the runtime works even if theme.ROOT changes.
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        roots.insert(0, Path(meipass))
    for root in roots:
        for name in names:
            candidates.append(root / "runtime" / name)
            candidates.append(root / name)
    which = shutil.which("mothx")
    if which:
        candidates.append(Path(which))
    # Keep order, drop duplicates.
    seen = set()
    unique = []
    for p in candidates:
        k = str(p).lower()
        if k not in seen:
            seen.add(k)
            unique.append(p)
    return unique


def _models_for(config: Config | None) -> list[dict[str, Any]]:
    models = [dict(m) for m in MODEL_CHOICES]
    if config is not None:
        active = config.active_profile()
        mid = str(active.get("chat_model") or "").strip()
        if mid and not any(m["id"] == mid for m in models):
            models.insert(
                0,
                {
                    "id": mid,
                    "name": mid,
                    "contextWindow": 1_000_000,
                    "maxTokens": 384_000,
                    "reasoning": False,
                    "input": ["text", "image"],
                    "badges": ["工具", "当前模型"],
                },
            )
    return models


def find_runtime(config: Config | None = None) -> MothXRuntime:
    config_dir = APP_DIR / "mothx"
    last_error = ""
    for p in _candidate_paths(config):
        if p.exists() and p.is_file():
            rt = MothXRuntime(exe=p.resolve(), config_dir=config_dir, models=_models_for(config))
            return rt
        if str(p).endswith(("mothx", "mothx.exe")):
            last_error = str(p)
    # Return a useful object even when unavailable so the UI can explain where
    # it looked and offer the release page.
    fallback = _app_root() / "runtime" / ("mothx.exe" if os.name == "nt" else "mothx")
    rt = MothXRuntime(exe=fallback, config_dir=config_dir, models=_models_for(config))
    rt.error = f"未找到 MothX 运行时，最后尝试：{last_error or fallback}"
    return rt
