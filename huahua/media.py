"""Files, images, documents and video frames used by the widget."""
from __future__ import annotations

import base64
import io
import mimetypes
import os
import re
import time
from pathlib import Path
from typing import Any, Callable

import requests
from PIL import Image, ImageOps

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}
TEXT_EXTS = {
    ".txt", ".md", ".markdown", ".csv", ".json", ".jsonl", ".xml", ".html", ".htm", ".yaml", ".yml",
    ".ini", ".log", ".py", ".js", ".ts", ".tsx", ".jsx", ".css", ".scss", ".java", ".c", ".cpp", ".h",
    ".hpp", ".cs", ".go", ".rs", ".rb", ".php", ".sql", ".sh", ".bat", ".ps1", ".toml", ".env",
}


def kind_of(path: str | Path) -> str:
    ext = Path(path).suffix.lower()
    if ext in IMAGE_EXTS:
        return "image"
    if ext in VIDEO_EXTS:
        return "video"
    if ext in AUDIO_EXTS:
        return "audio"
    if ext == ".pdf":
        return "pdf"
    if ext in (".doc", ".docx"):
        return "doc"
    if ext in (".ppt", ".pptx"):
        return "slides"
    if ext in (".xls", ".xlsx"):
        return "sheet"
    if ext in TEXT_EXTS:
        return "text"
    return "file"


def pretty_size(n: int | float) -> str:
    n = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def safe_name(name: str, limit: int = 36) -> str:
    name = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", name).strip(" .")
    return (name[:limit] or "未命名")


def unique_path(folder: Path, prefix: str, ext: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    p = folder / f"{prefix}_{stamp}{ext}"
    i = 2
    while p.exists():
        p = folder / f"{prefix}_{stamp}_{i}{ext}"
        i += 1
    return p


def save_bytes(data: bytes, folder: Path, prefix: str, ext: str) -> Path:
    p = unique_path(folder, prefix, ext)
    p.write_bytes(data)
    return p


def download(url: str, dest: Path, timeout: int = 180, on_progress: Callable[[int, int], None] | None = None) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with requests.get(url, stream=True, timeout=timeout) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1024 * 256):
                if not chunk:
                    continue
                f.write(chunk)
                done += len(chunk)
                if on_progress:
                    on_progress(done, total)
    os.replace(tmp, dest)
    return dest


def image_size(path: str | Path) -> tuple[int, int]:
    try:
        with Image.open(path) as im:
            return im.size
    except Exception:
        return (0, 0)


def image_data_url(path: str | Path, max_side: int = 1280, jpeg_quality: int = 90) -> str:
    """Downscale for vision / editing, preserving orientation and flattening alpha."""
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im)
        im.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
            rgba = im.convert("RGBA")
            bg = Image.new("RGB", rgba.size, (255, 255, 255))
            bg.paste(rgba, mask=rgba.getchannel("A"))
            im = bg
        elif im.mode != "RGB":
            im = im.convert("RGB")
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=jpeg_quality, optimize=True)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return "data:image/jpeg;base64," + b64


def fix_image_suffix(path: str | Path) -> Path:
    """MoArk sometimes returns JPEG bytes under a .png URL; keep the suffix truthful."""
    p = Path(path)
    try:
        with Image.open(p) as im:
            fmt = (im.format or "").upper()
        mapping = {"JPEG": ".jpg", "MPO": ".jpg", "PNG": ".png", "WEBP": ".webp", "GIF": ".gif"}
        ext = mapping.get(fmt)
        if ext and p.suffix.lower() != ext:
            new = p.with_suffix(ext)
            i = 2
            while new.exists():
                new = p.with_name(f"{p.stem}_{i}{ext}")
                i += 1
            p.rename(new)
            return new
    except Exception:
        pass
    return p


def thumb_bytes(path: str | Path, max_side: int = 480) -> bytes:
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im)
        im.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        if im.mode in ("RGBA", "LA"):
            bg = Image.new("RGB", im.size, (255, 250, 245))
            bg.paste(im, mask=im.getchannel("A"))
            im = bg
        elif im.mode != "RGB":
            im = im.convert("RGB")
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=88)
        return buf.getvalue()


def video_info(path: str | Path) -> dict[str, Any]:
    import cv2

    cap = cv2.VideoCapture(str(path))
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 0
        frames = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        dur = frames / fps if fps else 0
        return {"fps": fps, "frames": int(frames), "width": w, "height": h, "duration": dur}
    finally:
        cap.release()


def video_frames_data_urls(path: str | Path, n: int = 3, max_side: int = 1024) -> list[str]:
    import cv2

    cap = cv2.VideoCapture(str(path))
    urls: list[str] = []
    try:
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if total <= 0:
            return urls
        for i in range(n):
            idx = max(0, min(total - 1, int(total * (i + 1) / (n + 1))))
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ok, frame = cap.read()
            if not ok:
                continue
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            im = Image.fromarray(frame)
            im.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=88)
            urls.append("data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii"))
    finally:
        cap.release()
    return urls


def video_thumb(path: str | Path, dest: Path) -> Path | None:
    import cv2

    cap = cv2.VideoCapture(str(path))
    try:
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, int(total * 0.15)))
        ok, frame = cap.read()
        if not ok:
            return None
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        im = Image.fromarray(rgb)
        im.thumbnail((960, 960), Image.Resampling.LANCZOS)
        dest.parent.mkdir(parents=True, exist_ok=True)
        im.save(dest, format="JPEG", quality=90)
        return dest
    finally:
        cap.release()


def _read_text_file(path: Path, limit: int) -> str:
    raw = path.read_bytes()[: max(limit * 4, 200_000)]
    for enc in ("utf-8-sig", "utf-8", "gb18030", "utf-16", "latin-1"):
        try:
            return raw.decode(enc, errors="strict")[:limit]
        except Exception:
            continue
    return raw.decode("utf-8", errors="replace")[:limit]


def extract_document(path: str | Path, limit: int = 60_000) -> str:
    p = Path(path)
    k = kind_of(p)
    try:
        if k == "text":
            return _read_text_file(p, limit)
        if k == "pdf":
            parts: list[str] = []
            try:
                import fitz  # PyMuPDF

                doc = fitz.open(str(p))
                try:
                    for i, page in enumerate(doc):
                        if i >= 80:
                            break
                        parts.append(page.get_text("text"))
                finally:
                    doc.close()
            except Exception:
                from pypdf import PdfReader

                reader = PdfReader(str(p))
                for page in reader.pages[:80]:
                    parts.append(page.extract_text() or "")
            return ("\n\n".join(parts))[:limit]
        if k == "doc":
            import docx

            d = docx.Document(str(p))
            parts = [x.text for x in d.paragraphs if x.text.strip()]
            for table in d.tables:
                for row in table.rows:
                    parts.append(" | ".join(c.text.strip() for c in row.cells))
            return "\n".join(parts)[:limit]
        if k == "slides":
            from pptx import Presentation

            prs = Presentation(str(p))
            parts = []
            for i, slide in enumerate(prs.slides, 1):
                texts = []
                for shape in slide.shapes:
                    if hasattr(shape, "text") and shape.text.strip():
                        texts.append(shape.text.strip())
                if texts:
                    parts.append(f"[第 {i} 页]\n" + "\n".join(texts))
            return "\n\n".join(parts)[:limit]
        if k == "sheet":
            import openpyxl

            wb = openpyxl.load_workbook(str(p), read_only=True, data_only=True)
            parts = []
            try:
                for ws in wb.worksheets[:8]:
                    parts.append(f"[工作表：{ws.title}]")
                    for r, row in enumerate(ws.iter_rows(values_only=True)):
                        if r >= 120:
                            break
                        vals = ["" if v is None else str(v) for v in row[:24]]
                        if any(vals):
                            parts.append(" | ".join(vals))
            finally:
                wb.close()
            return "\n".join(parts)[:limit]
    except Exception as e:
        return f"（文件解析失败：{e}）"
    return ""


def file_prompt_payload(path: str | Path) -> tuple[str, list[str]]:
    """Return (text context, image data URLs) for DeepSeek vision."""
    p = Path(path)
    k = kind_of(p)
    if k == "image":
        return "", [image_data_url(p, 1280)]
    if k == "video":
        info = video_info(p)
        text = (
            f"用户拖入了一个视频文件：{p.name}，"
            f"时长约 {info.get('duration', 0):.1f} 秒，{info.get('width')}×{info.get('height')}，"
            f"{info.get('fps', 0):.1f} fps。以下是按时间顺序抽取的画面："
        )
        return text, video_frames_data_urls(p, 3, 1024)
    if k == "audio":
        return f"用户拖入了一个音频文件：{p.name}（{pretty_size(p.stat().st_size)}）。当前版本不能直接听音频。", []
    if k in ("pdf", "doc", "slides", "sheet", "text"):
        text = extract_document(p, 55_000)
        label = {
            "pdf": "PDF 文档", "doc": "Word 文档", "slides": "演示文稿", "sheet": "表格", "text": "文本文件"
        }[k]
        return f"用户拖入了一个{label}：{p.name}。以下是文件内容：\n\n{text}", []
    return f"用户拖入了一个文件：{p.name}（{pretty_size(p.stat().st_size)}）。", []


def media_kind_for_ext(path: str | Path) -> str:
    return kind_of(path)


def mime_of(path: str | Path) -> str:
    return mimetypes.guess_type(str(path))[0] or "application/octet-stream"


def recursive_find_url(obj: Any, suffixes: tuple[str, ...] = (".mp4", ".mov", ".webm")) -> str | None:
    if isinstance(obj, str):
        if obj.startswith("http") and any(obj.split("?")[0].lower().endswith(s) for s in suffixes):
            return obj
        return None
    if isinstance(obj, dict):
        for key in ("file_url", "url", "video_url", "audio_url"):
            v = obj.get(key)
            if isinstance(v, str) and v.startswith("http"):
                if any(v.split("?")[0].lower().endswith(s) for s in suffixes):
                    return v
        for v in obj.values():
            got = recursive_find_url(v, suffixes)
            if got:
                return got
    if isinstance(obj, list):
        for v in obj:
            got = recursive_find_url(v, suffixes)
            if got:
                return got
    return None
