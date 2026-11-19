"""Windows DPAPI helpers: API keys never need to be written as plain text."""
from __future__ import annotations

import base64
import ctypes
import os
from ctypes import wintypes
from pathlib import Path

_CRYPTPROTECT_UI_FORBIDDEN = 0x1


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes) -> _DATA_BLOB:
    buf = ctypes.create_string_buffer(data, len(data))
    return _DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))


def _blob_bytes(blob: _DATA_BLOB) -> bytes:
    return ctypes.string_at(blob.pbData, blob.cbData)


def protect(text: str) -> str:
    """Return a DPAPI-protected, base64-encoded token; empty string on failure."""
    if not text:
        return ""
    if os.name != "nt":
        return ""
    try:
        data = _blob(text.encode("utf-8"))
        out = _DATA_BLOB()
        ok = ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(data),
            "HuaHua API key",
            None,
            None,
            None,
            _CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(out),
        )
        if not ok:
            return ""
        try:
            return "dpapi:" + base64.b64encode(_blob_bytes(out)).decode("ascii")
        finally:
            ctypes.windll.kernel32.LocalFree(out.pbData)
    except Exception:
        return ""


def unprotect(token: str) -> str:
    if not token:
        return ""
    if token.startswith("dpapi:"):
        if os.name != "nt":
            return ""
        try:
            raw = base64.b64decode(token[6:])
            data = _blob(raw)
            out = _DATA_BLOB()
            ok = ctypes.windll.crypt32.CryptUnprotectData(
                ctypes.byref(data), None, None, None, None, _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out)
            )
            if not ok:
                return ""
            try:
                return _blob_bytes(out).decode("utf-8")
            finally:
                ctypes.windll.kernel32.LocalFree(out.pbData)
        except Exception:
            return ""
    # Backwards compatibility for a config written by an early build.
    if token.startswith("plain:"):
        return token[6:]
    return ""


def find_work_key(start: Path | None = None) -> str:
    """Find the MoArk token the user left in 工作资料.txt (without logging it)."""
    import sys

    here = (start or Path(__file__).resolve().parent.parent).resolve()
    exe_dir = Path(sys.executable).resolve().parent
    candidates = [
        here / "工作资料.txt",
        here.parent / "工作资料.txt",
        Path.cwd() / "工作资料.txt",
        exe_dir / "工作资料.txt",
    ]
    for p in candidates:
        try:
            if not p.exists() or p.stat().st_size > 100_000:
                continue
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for line in text.splitlines():
            low = line.lower()
            if "key" not in low or "github_pat" in low:
                continue
            # The useful token sits after the colon and is 24-48 ASCII chars.
            tail = line.split(":", 1)[-1].strip() if ":" in line else ""
            token = "".join(ch for ch in tail if ch.isalnum())
            if 24 <= len(token) <= 64 and any(c.upper() in "GHIJKLMNOPQRSTUVWXYZ" for c in token):
                if not all(c in "0123456789abcdefABCDEF" for c in token):  # skip hex Gitee token
                    return token
    return ""
