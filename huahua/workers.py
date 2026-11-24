"""Background workers: slow network calls must never freeze the pet."""
from __future__ import annotations

import threading
import traceback
from pathlib import Path
from typing import Any

from PySide6.QtCore import QThread, Signal

from .api import ApiError, MoArkClient, Stopped
from .config import LOG_PATH


def log_exception(where: str) -> None:
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"\n[{where}]\n{traceback.format_exc()}\n")
    except Exception:
        pass


class ChatWorker(QThread):
    delta = Signal(str)
    reasoning = Signal(str)
    completed = Signal(str)
    failed = Signal(str)

    def __init__(self, profile: dict[str, Any], key: str, messages: list[dict[str, Any]], deep_think: bool = False):
        super().__init__()
        self.profile = profile
        self.key = key
        self.messages = messages
        self.deep_think = deep_think
        self.stop_event = threading.Event()
        self._full = ""

    def stop(self) -> None:
        self.stop_event.set()

    def run(self) -> None:
        try:
            client = MoArkClient(self.profile, self.key)
            self._full = client.chat_stream(
                self.messages,
                on_delta=self.delta.emit,
                on_reasoning=self.reasoning.emit,
                stop_event=self.stop_event,
                deep_think=self.deep_think,
            )
            self.completed.emit(self._full)
        except Stopped:
            self.completed.emit(self._full)
        except ApiError as e:
            self.failed.emit(str(e))
        except Exception as e:
            log_exception("chat")
            self.failed.emit(f"对话出了点小问题：{e}")


class ImageWorker(QThread):
    progress = Signal(str)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        profile: dict[str, Any],
        key: str,
        prompt: str,
        out_dir: Path,
        images: list[str] | None = None,
        n: int = 1,
        seed: int | None = None,
    ):
        super().__init__()
        self.profile = profile
        self.key = key
        self.prompt = prompt
        self.out_dir = out_dir
        self.images = images or []
        self.n = n
        self.seed = seed
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    def run(self) -> None:
        try:
            client = MoArkClient(self.profile, self.key)
            paths = client.generate_image(
                self.prompt,
                self.out_dir,
                images=self.images,
                n=self.n,
                seed=self.seed,
                stop_event=self.stop_event,
                on_progress=self.progress.emit,
            )
            self.completed.emit(paths)
        except Stopped:
            self.failed.emit("已停止生成。")
        except ApiError as e:
            self.failed.emit(str(e))
        except Exception as e:
            log_exception("image")
            self.failed.emit(f"生图出了点小问题：{e}")


class VideoWorker(QThread):
    progress = Signal(str)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        profile: dict[str, Any],
        key: str,
        prompt: str,
        out_dir: Path,
    ):
        super().__init__()
        self.profile = profile
        self.key = key
        self.prompt = prompt
        self.out_dir = out_dir
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    def run(self) -> None:
        try:
            client = MoArkClient(self.profile, self.key)
            video = client.generate_text_video(
                self.prompt,
                self.out_dir,
                on_progress=self.progress.emit,
                stop_event=self.stop_event,
            )
            self.completed.emit({"video": str(video)})
        except Stopped:
            self.failed.emit("已停止生成。")
        except ApiError as e:
            self.failed.emit(str(e))
        except Exception as e:
            log_exception("video")
            self.failed.emit(f"视频生成出了点小问题：{e}")


class TestWorker(QThread):
    completed = Signal(str)
    failed = Signal(str)

    def __init__(self, profile: dict[str, Any], key: str):
        super().__init__()
        self.profile = profile
        self.key = key

    def run(self) -> None:
        try:
            client = MoArkClient(self.profile, self.key)
            info = client.test_connection()
            missing = info.get("missing") or []
            if missing:
                self.completed.emit(f"连接成功 · {info['count']} 个模型；但缺少：{'、'.join(missing)}")
            else:
                self.completed.emit(f"连接成功 · {info['count']} 个模型，四个模型都在线")
        except ApiError as e:
            self.failed.emit(str(e))
        except Exception as e:
            log_exception("test")
            self.failed.emit(f"连接失败：{e}")
