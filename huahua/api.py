"""模力方舟 (MoArk) client.

All four modalities share one OpenAI-compatible base URL:
  - chat / vision:  POST /chat/completions
  - image:          POST /images/generations
  - speech:         POST /async/audio/speech  -> GET /task/<id>
  - digital human:  POST /async/videos/audio-video-to-video -> GET /task/<id>
"""
from __future__ import annotations

import base64
import json
import threading
import time
from pathlib import Path
from typing import Any, Callable

import requests

from . import media


class ApiError(RuntimeError):
    pass


class Stopped(RuntimeError):
    pass


class MoArkClient:
    def __init__(self, profile: dict[str, Any], api_key: str, timeout: int = 180):
        self.profile = profile
        self.key = (api_key or "").strip()
        self.base = (profile.get("base_url") or "https://api.moark.com/v1").rstrip("/")
        if self.base.endswith("/v1") is False and not self.base.endswith("/api/v1"):
            # Accept a hostname entered without /v1.
            self.base += "/v1"
        self.timeout = int(profile.get("timeout") or timeout)
        self.video_timeout = int(profile.get("video_timeout") or 1800)
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {self.key}",
                "X-Failover-Enabled": "true",
                "User-Agent": "HuaHua-Desktop/1.1",
            }
        )

    # ------------------------------------------------------------------
    def _url(self, path: str) -> str:
        return f"{self.base}/{path.lstrip('/')}"

    def _check(self, r: requests.Response, what: str) -> None:
        if r.status_code < 400:
            return
        try:
            data = r.json()
            err = data.get("error") or data
            if isinstance(err, dict):
                msg = err.get("message") or err.get("code") or json.dumps(err, ensure_ascii=False)
            else:
                msg = str(err)
        except Exception:
            msg = (r.text or "").strip()[:500]
        if r.status_code == 401:
            msg = "API Key 无效或已过期，请在右键 → 设置里更新。"
        elif r.status_code == 403:
            msg = "这个访问令牌没有调用该模型的权限。"
        elif r.status_code == 429:
            msg = "请求太频繁或额度不足，稍等一下再试。"
        raise ApiError(f"{what}失败（{r.status_code}）：{msg}")

    def list_models(self) -> list[str]:
        r = self.session.get(self._url("models"), timeout=30)
        self._check(r, "读取模型列表")
        data = r.json()
        return [m.get("id", "") for m in data.get("data", []) if m.get("id")]

    def test_connection(self) -> dict[str, Any]:
        models = self.list_models()
        wanted = {
            "对话": self.profile.get("chat_model", ""),
            "生图": self.profile.get("image_model", ""),
            "视频": self.profile.get("video_model", ""),
            "语音": self.profile.get("tts_model", ""),
        }
        missing = [v for v in wanted.values() if v and v not in models]
        return {"count": len(models), "missing": missing, "models": wanted}

    # ------------------------------------------------------------------
    def chat_stream(
        self,
        messages: list[dict[str, Any]],
        on_delta: Callable[[str], None],
        on_reasoning: Callable[[str], None] | None = None,
        stop_event: threading.Event | None = None,
        deep_think: bool = False,
    ) -> str:
        payload: dict[str, Any] = {
            "model": self.profile.get("chat_model", "DeepSeek-V4.1-Flash-1017"),
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
            "max_tokens": 4096 if not deep_think else 8192,
        }
        if deep_think:
            payload["thinking"] = {"type": "enabled"}
        else:
            payload["thinking"] = {"type": "disabled"}
        try:
            r = self.session.post(
                self._url("chat/completions"), json=payload, stream=True, timeout=(20, 300)
            )
        except requests.RequestException as e:
            raise ApiError(f"连接模力方舟失败：{e}") from e
        self._check(r, "对话")
        # MoArk's SSE endpoint often omits charset; requests would otherwise
        # fall back to ISO-8859-1 and turn Chinese into mojibake.
        r.encoding = "utf-8"
        full: list[str] = []
        try:
            for raw in r.iter_lines(decode_unicode=False):
                if stop_event is not None and stop_event.is_set():
                    raise Stopped("已停止")
                if not raw:
                    continue
                line = raw.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                except Exception:
                    continue
                choices = obj.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                piece = delta.get("content")
                if piece:
                    full.append(piece)
                    on_delta(piece)
                reason = delta.get("reasoning_content")
                if reason and on_reasoning:
                    on_reasoning(reason)
            return "".join(full)
        finally:
            r.close()

    # ------------------------------------------------------------------
    def generate_image(
        self,
        prompt: str,
        out_dir: Path,
        images: list[str] | None = None,
        negative_prompt: str = "低分辨率，低画质，肢体畸形，手指畸形，画面过饱和，蜡像感，文字模糊扭曲",
        seed: int | None = None,
        n: int = 1,
        stop_event: threading.Event | None = None,
        on_progress: Callable[[str], None] | None = None,
    ) -> list[Path]:
        payload: dict[str, Any] = {
            "model": self.profile.get("image_model", "qwen-image-2.0-pro"),
            "prompt": prompt[:3500],
            "n": max(1, min(int(n), 4)),
            "size": "2048*2048",
            "negative_prompt": negative_prompt[:500],
            "prompt_extend": True,
            "watermark": False,
        }
        if seed is not None:
            payload["seed"] = int(seed)
        if images:
            payload["images"] = images[:3]
        if on_progress:
            on_progress("正在生成画面…")
        r: requests.Response | None = None
        for attempt in range(2):
            try:
                r = self.session.post(self._url("images/generations"), json=payload, timeout=(20, 600))
                if r.status_code in (502, 503, 504) and attempt == 0:
                    time.sleep(2)
                    continue
                break
            except requests.RequestException as e:
                if attempt == 0:
                    time.sleep(2)
                    continue
                raise ApiError(f"生图请求失败：{e}") from e
        if r is None:
            raise ApiError("生图请求失败。")
        self._check(r, "生图")
        data = r.json()
        items = data.get("data") or []
        if not items:
            raise ApiError("生图完成，但接口没有返回图片。")
        folder = out_dir / "图片"
        folder.mkdir(parents=True, exist_ok=True)
        paths: list[Path] = []
        for i, item in enumerate(items):
            if stop_event is not None and stop_event.is_set():
                raise Stopped("已停止")
            if on_progress:
                on_progress(f"正在取回第 {i + 1}/{len(items)} 张图…")
            if item.get("b64_json"):
                raw = base64.b64decode(item["b64_json"])
                p = media.save_bytes(raw, folder, f"桌面生图_{i + 1}", ".png")
                paths.append(media.fix_image_suffix(p))
            elif item.get("url"):
                p = media.unique_path(folder, f"桌面生图_{i + 1}", ".png")
                media.download(item["url"], p, timeout=240)
                paths.append(media.fix_image_suffix(p))
        if not paths:
            raise ApiError("图片链接为空，请重试。")
        return paths

    # ------------------------------------------------------------------
    def submit_async(self, path: str, payload: dict[str, Any], timeout: int = 90) -> str:
        r = self.session.post(self._url(path), json=payload, timeout=timeout)
        self._check(r, "提交任务")
        data = r.json()
        tid = data.get("task_id") or data.get("id")
        if not tid:
            raise ApiError(f"任务提交成功但没有 task_id：{str(data)[:300]}")
        return str(tid)

    def poll_task(
        self,
        task_id: str,
        timeout: int,
        on_progress: Callable[[str, dict[str, Any]], None] | None = None,
        stop_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        start = time.time()
        last = ""
        while time.time() - start < timeout:
            if stop_event is not None and stop_event.is_set():
                raise Stopped("已停止")
            try:
                r = self.session.get(self._url(f"task/{task_id}"), timeout=30)
            except requests.RequestException:
                time.sleep(4)
                continue
            self._check(r, "查询任务")
            data = r.json()
            status = str(data.get("status") or "unknown").lower()
            if on_progress:
                on_progress(status, data)
            if status in ("success", "succeeded", "finished"):
                return data
            if status in ("failed", "failure", "cancelled", "canceled", "error"):
                msg = data.get("message") or data.get("error") or "任务失败"
                raise ApiError(str(msg))
            last = status
            time.sleep(5)
        raise ApiError(f"任务等待超时（最后状态：{last or 'unknown'}）。可以稍后在作品文件夹查看，或重试。")

    def synthesize(
        self,
        text: str,
        out_dir: Path,
        on_progress: Callable[[str], None] | None = None,
        stop_event: threading.Event | None = None,
        speaker: str | None = None,
    ) -> Path:
        text = text.strip()
        if not text:
            raise ApiError("要先写一段口播文案，才能合成声音。")
        if on_progress:
            on_progress("正在合成声音…")
        payload = {
            "inputs": [
                {
                    "prompt": text[:1500],
                    "speaker": speaker or self.profile.get("tts_speaker", "Vivian"),
                    "language": "Chinese",
                    "instruction": self.profile.get("tts_instruction", "温柔、自然、轻快"),
                }
            ],
            "model": self.profile.get("tts_model", "Qwen3-TTS"),
            "output_format": "mp3",
        }
        tid = self.submit_async("async/audio/speech", payload)
        data = self.poll_task(tid, min(self.video_timeout, 600), stop_event=stop_event)
        url = media.recursive_find_url(data.get("output"), (".mp3", ".wav", ".m4a"))
        if not url:
            # Some responses put audio_urls under output.result.
            url = media.recursive_find_url(data, (".mp3", ".wav", ".m4a"))
        if not url:
            raise ApiError("语音合成成功，但没有找到音频地址。")
        folder = out_dir / "音频"
        p = media.unique_path(folder, "桌面配音", ".mp3")
        media.download(url, p, timeout=180)
        return p

    def generate_text_video(
        self,
        prompt: str,
        out_dir: Path,
        on_progress: Callable[[str], None] | None = None,
        stop_event: threading.Event | None = None,
    ) -> Path:
        prompt = prompt.strip()
        if not prompt:
            raise ApiError("要先写一段画面描述，才能生成视频。")
        if on_progress:
            on_progress("正在提交视频任务…")
        payload = {
            "model": self.profile.get("video_model", "HappyHorse-1.0"),
            "prompt": prompt[:600],
        }
        tid = self.submit_async("async/videos/generations", payload, timeout=90)
        started = time.time()
        last_tick = 0.0

        def report(status: str, _payload: dict[str, Any]):
            nonlocal last_tick
            now = time.time()
            if on_progress and (now - last_tick > 1.2 or status in ("success", "failed")):
                elapsed = int(now - started)
                label = "排队中" if status in ("waiting", "queued") else "正在生成视频"
                on_progress(f"{label}… {elapsed // 60:02d}:{elapsed % 60:02d}")
                last_tick = now

        task = self.poll_task(
            str(tid), self.video_timeout, on_progress=report, stop_event=stop_event
        )
        url = None
        output = task.get("output")
        if isinstance(output, dict):
            url = output.get("file_url") or output.get("video_url")
        if not url:
            url = media.recursive_find_url(task.get("output"), (".mp4", ".mov", ".webm"))
        if not url:
            url = media.recursive_find_url(task, (".mp4", ".mov", ".webm"))
        if not url:
            raise ApiError("视频任务完成，但没有找到视频地址。")
        if on_progress:
            on_progress("正在下载成片…")
        folder = out_dir / "视频"
        p = media.unique_path(folder, "桌面视频", ".mp4")
        media.download(url, p, timeout=600)
        return p

    def generate_video(
        self,
        ref_video: Path,
        script: str,
        out_dir: Path,
        audio: Path | None = None,
        on_progress: Callable[[str], None] | None = None,
        stop_event: threading.Event | None = None,
    ) -> tuple[Path, Path]:
        if not ref_video.exists():
            raise ApiError("请先选择一段数字人参考视频。")
        if audio is None:
            audio = self.synthesize(script, out_dir, on_progress=on_progress, stop_event=stop_event)
        elif on_progress:
            on_progress("正在上传口播音频…")
        if on_progress:
            on_progress("正在让数字人对上口型…")
        files = {
            "ref_audio": (audio.name, open(audio, "rb"), media.mime_of(audio)),
            "ref_video": (ref_video.name, open(ref_video, "rb"), media.mime_of(ref_video)),
        }
        try:
            r = self.session.post(
                self._url("async/videos/audio-video-to-video"),
                data={"model": self.profile.get("video_model", "Duix-Avatar")},
                files=files,
                timeout=(30, 900),
            )
        except requests.RequestException as e:
            raise ApiError(f"上传视频素材失败：{e}") from e
        finally:
            for _, f, _ in files.values():
                try:
                    f.close()
                except Exception:
                    pass
        self._check(r, "提交数字人任务")
        data = r.json()
        tid = data.get("task_id") or data.get("id")
        if not tid:
            raise ApiError(f"没有拿到视频任务编号：{str(data)[:300]}")

        last_tick = 0.0

        def report(status: str, _payload: dict[str, Any]):
            nonlocal last_tick
            now = time.time()
            if on_progress and (now - last_tick > 1.2 or status in ("success", "failed")):
                elapsed = int(now - start_time)
                on_progress(f"数字人工作中… {elapsed // 60:02d}:{elapsed % 60:02d}")
                last_tick = now

        start_time = time.time()
        task = self.poll_task(str(tid), self.video_timeout, on_progress=report, stop_event=stop_event)
        url = media.recursive_find_url(task.get("output"), (".mp4", ".mov", ".webm"))
        if not url:
            url = media.recursive_find_url(task, (".mp4", ".mov", ".webm"))
        if not url:
            raise ApiError("数字人任务完成，但没有找到视频地址。")
        if on_progress:
            on_progress("正在下载成片…")
        folder = out_dir / "视频"
        p = media.unique_path(folder, "数字人视频", ".mp4")
        media.download(url, p, timeout=600)
        return p, audio


def sse_test(profile: dict[str, Any], key: str) -> str:
    client = MoArkClient(profile, key)
    info = client.test_connection()
    missing = info.get("missing") or []
    if missing:
        return f"连接成功，共 {info['count']} 个模型；缺少：{'、'.join(missing)}"
    return f"连接成功，共 {info['count']} 个模型，四个模型都在。"
