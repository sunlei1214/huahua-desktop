"""Reusable, hand-drawn UI pieces."""
from __future__ import annotations

import html as html_lib
import math
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import markdown
from PySide6.QtCore import (
    QByteArray,
    QEasingCurve,
    QMimeData,
    QPoint,
    QPointF,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QCursor,
    QDesktopServices,
    QDrag,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QTextOption,
)
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from . import media
from . import theme
from .theme import (
    CREAM,
    CREAM_2,
    DANGER,
    GOLD,
    INK,
    INK_SOFT,
    LINE,
    LINE_STRONG,
    MUTED,
    PAPER,
    PEACH,
    PEACH_DEEP,
    PEACH_SOFT,
    TEAL,
    TEAL_DEEP,
    TEAL_SOFT,
    WHITE,
    font,
    icon_font,
    icon_glyph,
)


# ----------------------------------------------------------------------
def glyph_icon(name: str, color: str = INK_SOFT, size: int = 18):
    from PySide6.QtGui import QIcon

    dpr = 2
    pm = QPixmap(size * dpr, size * dpr)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QColor(color))
    p.setFont(icon_font(int(size * 0.82 * dpr)))
    p.drawText(QRect(0, 0, size * dpr, size * dpr), Qt.AlignmentFlag.AlignCenter, icon_glyph(name))
    p.end()
    pm.setDevicePixelRatio(dpr)
    return QIcon(pm)


class IconButton(QPushButton):
    def __init__(self, glyph: str, tooltip: str = "", size: int = 30, parent=None):
        super().__init__(icon_glyph(glyph), parent)
        self.setObjectName("Icon")
        self.setFont(icon_font(14))
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        if tooltip:
            self.setToolTip(tooltip)


class SegmentedControl(QFrame):
    """Shared top-level switch (会话 / 执行) and compact mode switch."""

    changed = Signal(str)

    def __init__(
        self,
        options: list[tuple[str, str]],
        active: str = "",
        parent=None,
        compact: bool = False,
        variant: str = "view",
    ):
        super().__init__(parent)
        self.variant = variant
        self.setObjectName("ViewSwitch" if variant == "view" else "ModeSwitch")
        self.options = options
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: dict[str, QPushButton] = {}
        lay = QHBoxLayout(self)
        if variant == "view":
            lay.setContentsMargins(0, 2, 0, 0)
        else:
            lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(2)
        for i, (label, value) in enumerate(options):
            b = QPushButton(label)
            b.setObjectName("Segment")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFixedHeight(25 if compact else 27)
            b.setMinimumWidth(42 if compact else 46)
            b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self.group.addButton(b, i)
            lay.addWidget(b)
            self.buttons[value] = b
        self.group.idClicked.connect(lambda i: self.changed.emit(self.options[i][1]))
        self.set_active(active or (options[0][1] if options else ""))

    def set_active(self, value: str) -> None:
        btn = self.buttons.get(value)
        if btn is None:
            return
        btn.setChecked(True)


class Avatar(QWidget):
    def __init__(self, size: int = 38, online: bool = True, character: str = "huahua", parent=None):
        super().__init__(parent)
        self._size = size
        self.online = online
        self.character = theme.character_key(character)
        self.setFixedSize(size, size)

    def set_online(self, on: bool):
        self.online = on
        self.update()

    def set_character(self, character: str):
        self.character = theme.character_key(character)
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(1, 1, self.width() - 2, self.height() - 2)
        path = QPainterPath()
        path.addEllipse(r)
        p.setClipPath(path)
        p.drawPixmap(r.toRect(), theme.avatar_pixmap(self.width(), self.character))
        p.setClipping(False)
        p.setPen(QPen(QColor(WHITE), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(r.adjusted(1, 1, -1, -1))
        if self.online:
            d = max(8, self.width() // 4)
            dot = QRectF(self.width() - d - 1, self.height() - d - 1, d, d)
            p.setPen(QPen(QColor(WHITE), 2))
            p.setBrush(QColor("#59BA8D"))
            p.drawEllipse(dot)


class FlowLayout(QLayout):
    """A small wrapping layout for prompt chips."""

    def __init__(self, parent=None, margin=0, spacing=8):
        super().__init__(parent)
        self.setContentsMargins(margin, margin, margin, margin)
        self.setSpacing(spacing)
        self.items = []

    def addItem(self, item):
        self.items.append(item)

    def count(self):
        return len(self.items)

    def itemAt(self, i):
        return self.items[i] if 0 <= i < len(self.items) else None

    def takeAt(self, i):
        return self.items.pop(i) if 0 <= i < len(self.items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self.items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _do_layout(self, rect, test_only):
        x = rect.x()
        y = rect.y()
        line_h = 0
        space = self.spacing()
        for item in self.items:
            hint = item.sizeHint()
            next_x = x + hint.width() + space
            if next_x - space > rect.right() and line_h > 0:
                x = rect.x()
                y += line_h + space
                next_x = x + hint.width() + space
                line_h = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            line_h = max(line_h, hint.height())
        return y + line_h - rect.y()


class Chip(QPushButton):
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setObjectName("Chip")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)


class EmptyState(QWidget):
    prompt_clicked = Signal(str, str)  # mode, prompt

    def __init__(self, character: str = "huahua", parent=None):
        super().__init__(parent)
        self.mode = "chat"
        self.character = theme.character_key(character)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(18, 8, 18, 12)
        self._layout.setSpacing(10)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.art = QLabel()
        self.art.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pm = theme.pixmap("idle", self.character).scaled(
            150, 150, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
        )
        self.art.setPixmap(pm)
        self.art.setFixedHeight(156)
        self._layout.addWidget(self.art)

        self.title = QLabel("在呢，今天想织点什么？")
        self.title.setObjectName("Title")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._layout.addWidget(self.title)

        self.sub = QLabel("聊天、画图、图生图，或者把文件拖进来让我看看。")
        self.sub.setObjectName("Hint")
        self.sub.setWordWrap(True)
        self.sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._layout.addWidget(self.sub)

        self.chips_host = QWidget()
        self.flow = FlowLayout(self.chips_host, margin=0, spacing=4)
        self._layout.addWidget(self.chips_host)
        self._chips: list[Chip] = []
        self.set_mode("chat")

    def set_mode(self, mode: str):
        self.mode = mode
        while self.flow.count():
            item = self.flow.takeAt(0)
            if item and item.widget():
                chip = item.widget()
                chip.hide()
                chip.setParent(None)
                chip.deleteLater()
        for chip in self._chips:
            chip.hide()
            chip.setParent(None)
            chip.deleteLater()
        self._chips = []
        self.flow.invalidate()
        if mode == "chat":
            self.title.setText(
                "在呢，今天想织点什么？" if self.character == "huahua" else "来啦，今天整点什么好玩的？"
            )
            self.sub.setText("聊天、画图、图生图，或者把文件拖进来让我看看。")
            prompts = [
                ("帮我写一段有画面感的旅行文案", "写作"),
                ("解释一下什么是「心流」", "好奇"),
                ("给我三个今天的小确幸", "灵感"),
                ("用一句话夸夸我", "贴贴"),
            ]
        elif mode == "image":
            self.title.setText("把脑子里的小画面交给我")
            verb = "织" if self.character == "huahua" else "画"
            self.sub.setText(f"描述越具体，{verb}出来的图越接近你想象的样子；拖入参考图就变成图生图。")
            prompts = [
                ("一只戴珍珠耳环的橘猫，油画质感", "名画猫"),
                ("雨后的江南小巷，青石板反光，电影感", "江南"),
                ("奶油色手帐风插画，写着一行「慢慢来」", "手帐"),
                ("月球上的小茶馆，远处有地球升起", "幻想"),
            ]
        elif mode == "img2img":
            self.title.setText("给我一张参考图，我来变个魔法")
            self.sub.setText("先点左下角的回形针选图，或者直接把图片拖进来，再告诉我怎么改。")
            prompts = [
                ("保持构图，改成温柔的吉卜力动画风", "动画风"),
                ("把背景换成傍晚的海边", "换背景"),
                ("给人物加上一顶星星发卡", "加细节"),
            ]
        else:
            self.title.setText("把一段想象变成视频")
            self.sub.setText("写清主体、动作、镜头和氛围，我用 HappyHorse-1.0 生成一段短视频。")
            prompts = [
                ("海边落日，镜头缓慢推进，电影感", "落日"),
                ("一只橘猫在雨后的屋顶上伸懒腰，暖色调", "橘猫"),
                ("未来城市夜景，霓虹倒映在湿漉漉的街道上", "赛博"),
            ]
        for text, tag in prompts:
            c = Chip(text)
            c.clicked.connect(lambda _=False, t=text, m=mode: self.prompt_clicked.emit(m, t))
            self.flow.addWidget(c)
            self._chips.append(c)
        self.flow.invalidate()
        self.chips_host.updateGeometry()

    def set_character(self, character: str):
        self.character = theme.character_key(character)
        self.set_mode(self.mode)

    def set_pet(self, state: str):
        pm = theme.pixmap(state, self.character).scaled(
            160, 160, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
        )
        self.art.setPixmap(pm)


# ----------------------------------------------------------------------
class CoverLabel(QWidget):
    """Draw a pixmap with cover fit and rounded corners."""

    clicked = Signal()

    def __init__(self, path: str | Path, height: int = 180, radius: int = 14, parent=None):
        super().__init__(parent)
        self.path = Path(path)
        self._height = height
        self.radius = radius
        self._pm = self._load()
        self.setFixedHeight(height)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def _load(self) -> QPixmap:
        try:
            if self.path.suffix.lower() in media.VIDEO_EXTS:
                cache = self.path.parent.parent / "缓存"
                cache.mkdir(parents=True, exist_ok=True)
                thumb = cache / (self.path.stem + "_thumb.jpg")
                if not thumb.exists():
                    media.video_thumb(self.path, thumb)
                if thumb.exists():
                    return QPixmap(str(thumb))
            pm = QPixmap(str(self.path))
            return pm
        except Exception:
            return QPixmap()

    def set_path(self, path: str | Path):
        self.path = Path(path)
        self._pm = self._load()
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = QRectF(0, 0, self.width(), self.height())
        path = QPainterPath()
        path.addRoundedRect(r, self.radius, self.radius)
        p.setClipPath(path)
        p.fillRect(r, QColor(CREAM_2))
        if not self._pm.isNull():
            src = self._pm
            scale = max(r.width() / src.width(), r.height() / src.height())
            w, h = src.width() * scale, src.height() * scale
            target = QRectF((r.width() - w) / 2, (r.height() - h) / 2, w, h)
            p.drawPixmap(target, src, QRectF(src.rect()))
        else:
            p.setPen(QPen(QColor(MUTED), 1))
            p.setFont(font(9))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, "预览不可用")
        # subtle bottom fade
        grad = QLinearGradient(0, r.height() * 0.55, 0, r.height())
        grad.setColorAt(0, QColor(20, 12, 9, 0))
        grad.setColorAt(1, QColor(20, 12, 9, 80))
        p.fillRect(r, grad)
        p.setClipping(False)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()


class MediaCard(QFrame):
    open_requested = Signal(str)

    def __init__(self, path: str | Path, kind: str, note: str = "", parent=None):
        super().__init__(parent)
        self.path = Path(path)
        self.kind = kind
        self.setObjectName("SoftCard")
        self.setMaximumWidth(352)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.cover = CoverLabel(self.path, 190 if kind == "video" else 200)
        self.cover.clicked.connect(lambda: self.open_requested.emit(str(self.path)))
        lay.addWidget(self.cover)

        # play badge for video
        if kind == "video":
            self.play = QPushButton("▶", self.cover)
            self.play.setFont(font(16, QFont.Weight.Bold))
            self.play.setCursor(Qt.CursorShape.PointingHandCursor)
            self.play.setFixedSize(52, 52)
            self.play.setStyleSheet(
                "QPushButton{background:rgba(255,252,248,0.9);border:none;border-radius:26px;color:#E98F73;padding-left:4px;}"
                "QPushButton:hover{background:white;}"
            )
            self.play.clicked.connect(lambda: self.open_requested.emit(str(self.path)))
            self.cover.installEventFilter(self)

        info = QWidget()
        il = QHBoxLayout(info)
        il.setContentsMargins(12, 9, 10, 10)
        il.setSpacing(8)
        col = QVBoxLayout()
        col.setSpacing(1)
        name = QLabel(self.path.name)
        name.setFont(font(9, QFont.Weight.DemiBold))
        name.setStyleSheet(f"color:{INK};")
        name.setToolTip(str(self.path))
        sub = QLabel(note or self._subtitle())
        sub.setObjectName("Tiny")
        sub.setWordWrap(False)
        col.addWidget(name)
        col.addWidget(sub)
        il.addLayout(col, 1)
        for glyph, tip, fn in (
            ("folder", "打开所在文件夹", self._reveal),
            ("copy", "复制文件路径", self._copy_path),
            ("expand", "打开文件", lambda: self.open_requested.emit(str(self.path))),
        ):
            b = IconButton(glyph, tip, 28)
            b.clicked.connect(fn)
            il.addWidget(b)
        lay.addWidget(info)

        self._drag_start = QPoint()

    def _resize_play(self, e):
        self.play.move((self.cover.width() - 52) // 2, (self.cover.height() - 52) // 2)

    def eventFilter(self, obj, event):
        if obj is self.cover and event.type() == event.Type.Resize:
            self.play.move((self.cover.width() - 52) // 2, (self.cover.height() - 52) // 2)
        return super().eventFilter(obj, event)

    def _subtitle(self) -> str:
        try:
            if self.kind == "video":
                info = media.video_info(self.path)
                return f"数字人视频 · {info.get('duration', 0):.0f} 秒 · {media.pretty_size(self.path.stat().st_size)}"
            w, h = media.image_size(self.path)
            return f"{w}×{h} · {media.pretty_size(self.path.stat().st_size)}"
        except Exception:
            return media.pretty_size(self.path.stat().st_size) if self.path.exists() else ""

    def _reveal(self):
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", str(self.path)])
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.path.parent)))

    def _copy_path(self):
        QApplication.clipboard().setText(str(self.path))

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_start = e.position().toPoint()

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.MouseButton.LeftButton and not self._drag_start.isNull():
            if (e.position().toPoint() - self._drag_start).manhattanLength() > 12:
                drag = QDrag(self)
                mime = QMimeData()
                mime.setUrls([QUrl.fromLocalFile(str(self.path))])
                drag.setMimeData(mime)
                drag.setPixmap(self.cover._pm.scaled(120, 120, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
                drag.exec(Qt.DropAction.CopyAction)


class ImageViewer(QDialog):
    def __init__(self, path: str | Path, parent=None):
        super().__init__(parent)
        self.path = Path(path)
        self.setWindowTitle(self.path.name)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(980, 760)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        frame = QFrame()
        frame.setStyleSheet("QFrame{background:#211B19;border:1px solid #4A3E3A;border-radius:18px;}")
        outer.addWidget(frame)
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(12, 10, 12, 12)
        bar = QHBoxLayout()
        title = QLabel(self.path.name)
        title.setStyleSheet("color:#F7E9DF;font-weight:600;")
        bar.addWidget(title, 1)
        self.zoom_label = QLabel("100%")
        self.zoom_label.setStyleSheet("color:#B9A69D;")
        bar.addWidget(self.zoom_label)
        for text, fn in (
            ("适应窗口", self.fit),
            ("1:1", self.actual),
            ("复制", self.copy),
            ("另存为", self.save_as),
        ):
            b = QPushButton(text)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(
                "QPushButton{color:#F7E9DF;background:#3A302D;border:none;border-radius:9px;padding:6px 10px;}"
                "QPushButton:hover{background:#53433E;}"
            )
            b.clicked.connect(fn)
            bar.addWidget(b)
        close = QPushButton("\uE8BB")
        close.setFont(icon_font(14))
        close.setFixedSize(32, 32)
        close.setStyleSheet("QPushButton{color:#F7E9DF;background:transparent;border:none;border-radius:8px;}QPushButton:hover{background:#4A3C37;}")
        close.clicked.connect(self.accept)
        bar.addWidget(close)
        lay.addLayout(bar)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(False)
        self.scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scroll.setStyleSheet("QScrollArea{background:#171311;border:none;} QScrollBar:vertical{width:9px;background:#241E1C;}")
        self.label = QLabel()
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setStyleSheet("background:#171311;")
        self.pm = QPixmap(str(self.path))
        self.label.setPixmap(self.pm)
        self.scroll.setWidget(self.label)
        lay.addWidget(self.scroll, 1)
        self._scale = 1.0
        self._fit = True
        self._drag = None
        QTimer.singleShot(80, self.fit)
        self.mousePressEvent_base = self.mousePressEvent

    def fit(self):
        if self.pm.isNull():
            return
        area = self.scroll.viewport().size()
        area.setWidth(max(100, area.width() - 10))
        area.setHeight(max(100, area.height() - 10))
        scaled = self.pm.scaled(area, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self.label.setPixmap(scaled)
        self.label.resize(scaled.size())
        self._fit = True
        self._scale = scaled.width() / max(1, self.pm.width())
        self.zoom_label.setText(f"{int(self._scale * 100)}%")

    def actual(self):
        self.label.setPixmap(self.pm)
        self.label.resize(self.pm.size())
        self._fit = False
        self._scale = 1.0
        self.zoom_label.setText("100%")

    def wheelEvent(self, e):
        if self.pm.isNull():
            return
        factor = 1.12 if e.angleDelta().y() > 0 else 1 / 1.12
        new = max(0.1, min(5.0, self._scale * factor))
        if abs(new - self._scale) < 0.001:
            return
        self._scale = new
        self._fit = False
        scaled = self.pm.scaled(
            int(self.pm.width() * new), int(self.pm.height() * new),
            Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation,
        )
        self.label.setPixmap(scaled)
        self.label.resize(scaled.size())
        self.zoom_label.setText(f"{int(new * 100)}%")

    def copy(self):
        QApplication.clipboard().setPixmap(self.pm)
        self.zoom_label.setText("已复制到剪贴板")

    def save_as(self):
        dest, _ = QFileDialog.getSaveFileName(self, "另存图片", str(Path.home() / self.path.name), "图片 (*.png *.jpg *.webp)")
        if dest:
            QApplication.clipboard().clear()
            try:
                import shutil

                shutil.copy2(self.path, dest)
            except Exception:
                self.pm.save(dest)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self._fit is False:
            self._drag = e.globalPosition().toPoint()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._drag is not None and e.buttons() & Qt.MouseButton.LeftButton:
            delta = e.globalPosition().toPoint() - self._drag
            self.scroll.horizontalScrollBar().setValue(self.scroll.horizontalScrollBar().value() - delta.x())
            self.scroll.verticalScrollBar().setValue(self.scroll.verticalScrollBar().value() - delta.y())
            self._drag = e.globalPosition().toPoint()
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        self._drag = None
        super().mouseReleaseEvent(e)


# ----------------------------------------------------------------------
def md_to_html(text: str) -> str:
    text = re.sub(r"<script.*?</script>", "", text or "", flags=re.S | re.I)
    text = re.sub(r"<style.*?</style>", "", text, flags=re.S | re.I)
    text = re.sub(r"\son\w+\s*=", " data-x=", text, flags=re.I)
    try:
        body = markdown.markdown(text, extensions=["fenced_code", "tables", "sane_lists", "nl2br"])
    except Exception:
        body = "<p>" + html_lib.escape(text).replace("\n", "<br>") + "</p>"
    css = f"""
    <style>
      body {{ font-family:'Microsoft YaHei UI'; font-size:13px; color:{INK}; line-height:1.65; }}
      p {{ margin: 0 0 7px 0; }}
      h1,h2,h3,h4 {{ color:{INK}; margin: 10px 0 5px 0; }}
      h1 {{ font-size:17px; }} h2 {{ font-size:15px; }} h3 {{ font-size:14px; }}
      ul,ol {{ margin: 3px 0 7px 18px; }}
      li {{ margin: 2px 0; }}
      code {{ font-family:'Cascadia Mono','Consolas'; font-size:12px; background:#F8EDE5; color:#9C5B48; }}
      pre {{ background:#FAF2EC; padding:8px; border-radius:6px; white-space:pre-wrap; font-family:'Cascadia Mono','Consolas'; font-size:12px; color:#5A4A45; }}
      blockquote {{ margin:6px 0; padding-left:9px; border-left:3px solid {PEACH}; color:{INK_SOFT}; }}
      a {{ color:{TEAL_DEEP}; text-decoration:none; }}
      table {{ border-collapse:collapse; margin:5px 0; }}
      th,td {{ border:1px solid {LINE_STRONG}; padding:4px 7px; }}
      th {{ background:{CREAM_2}; }}
      hr {{ border:none; border-top:1px solid {LINE}; margin:9px 0; }}
    </style>"""
    return css + body


class NoWheelTextBrowser(QTextBrowser):
    """The bubble is already sized to its content, so let the outer timeline scroll."""

    def wheelEvent(self, e):
        e.ignore()


class MessageBubble(QFrame):
    regenerate_requested = Signal(str)
    media_open = Signal(str)

    def __init__(
        self,
        role: str,
        text: str = "",
        parent=None,
        name: str = "",
        time_text: str = "",
        mode: str = "",
        character: str = "huahua",
    ):
        super().__init__(parent)
        self.role = role
        self.character = theme.character_key(character)
        self.message_id = ""
        self._raw = text
        self._streaming = True
        self._attachments: list[Path] = []
        self._media_cards: list[MediaCard] = []
        self.setObjectName("Transparent")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self._row = row
        if role == "assistant":
            self.avatar = Avatar(30, True, self.character)
            wrap = QVBoxLayout()
            wrap.setContentsMargins(0, 0, 0, 0)
            wrap.setSpacing(3)
            wrap.addWidget(self.avatar, 0, Qt.AlignmentFlag.AlignTop)
            wrap.addStretch(1)
            row.addLayout(wrap, 0)
            row.addStretch(0)
        else:
            row.addStretch(1)

        self.col = QVBoxLayout()
        self.col.setContentsMargins(0, 0, 0, 0)
        self.col.setSpacing(4)
        self.col.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)

        head = QHBoxLayout()
        head.setContentsMargins(3, 0, 3, 0)
        head.setSpacing(6)
        self.name_label = QLabel(
            name or (theme.character_name(self.character) if role == "assistant" else "你")
        )
        self.name_label.setFont(font(9, QFont.Weight.DemiBold))
        self.name_label.setStyleSheet(f"color:{INK_SOFT};")
        self.time_label = QLabel(time_text or time.strftime("%H:%M"))
        self.time_label.setObjectName("Tiny")
        if role == "assistant":
            head.addWidget(self.name_label)
            if mode:
                badge = QLabel({"image": "生图", "img2img": "图生图", "video": "数字人", "chat": "对话"}.get(mode, mode))
                badge.setObjectName("Badge")
                head.addWidget(badge)
            head.addWidget(self.time_label)
            head.addStretch(1)
        else:
            head.addStretch(1)
            head.addWidget(self.time_label)
            head.addWidget(self.name_label)
        self.col.addLayout(head)

        self.bubble = QFrame()
        self.bubble.setObjectName("BubbleAssistant" if role == "assistant" else "BubbleUser")
        self.bubble.setMaximumWidth(346 if role == "assistant" else 326)
        self.bubble.setStyleSheet(
            f"QFrame#BubbleAssistant{{background:{WHITE};border:1px solid {LINE};border-radius:16px;}}"
            f"QFrame#BubbleUser{{background:{PEACH_SOFT};border:1px solid #F6D0BF;border-radius:16px;}}"
        )
        bl = QVBoxLayout(self.bubble)
        bl.setContentsMargins(12, 10, 12, 10)
        bl.setSpacing(7)
        self.textb = NoWheelTextBrowser()
        self.textb.setObjectName("MessageText")
        self.textb.setOpenExternalLinks(True)
        self.textb.setFrameShape(QFrame.Shape.NoFrame)
        self.textb.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.textb.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.textb.setStyleSheet("QTextBrowser{background:transparent;border:none;padding:0;}")
        self.textb.setFont(font(10))
        self.textb.document().setDocumentMargin(0)
        self.textb.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.LinksAccessibleByMouse
        )
        self.textb.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        bl.addWidget(self.textb)
        self.content_layout = bl
        self.attach_host = QWidget()
        self.attach_layout = QHBoxLayout(self.attach_host)
        self.attach_layout.setContentsMargins(0, 0, 0, 0)
        self.attach_layout.setSpacing(5)
        self.attach_host.hide()
        bl.addWidget(self.attach_host)
        self.media_host = QWidget()
        self.media_layout = QVBoxLayout(self.media_host)
        self.media_layout.setContentsMargins(0, 0, 0, 0)
        self.media_layout.setSpacing(7)
        self.media_host.hide()
        bl.addWidget(self.media_host)
        self.progress: ProgressCard | None = None

        self.footer = QWidget()
        fl = QHBoxLayout(self.footer)
        fl.setContentsMargins(2, 0, 0, 0)
        fl.setSpacing(2)
        if role == "assistant":
            self.copy_btn = IconButton("copy", "复制这段回答", 26)
            self.copy_btn.clicked.connect(self._copy)
            fl.addWidget(self.copy_btn)
            self.regen_btn = IconButton("refresh", "换个回答", 26)
            self.regen_btn.clicked.connect(lambda: self.regenerate_requested.emit(self.message_id))
            fl.addWidget(self.regen_btn)
            fl.addStretch(1)
        else:
            fl.addStretch(1)
            self.copy_btn = IconButton("copy", "复制", 24)
            self.copy_btn.clicked.connect(self._copy)
            fl.addWidget(self.copy_btn)
        self.footer.hide()
        self.col.addWidget(self.bubble, 0, Qt.AlignmentFlag.AlignRight if role == "user" else Qt.AlignmentFlag.AlignLeft)
        self.col.addWidget(self.footer, 0, Qt.AlignmentFlag.AlignRight if role == "user" else Qt.AlignmentFlag.AlignLeft)
        row.addLayout(self.col, 0)
        if role == "assistant":
            row.addStretch(1)

        if text:
            self.set_text(text)
        else:
            self.bubble.hide()
            self.footer.hide()

    # ------------------------------------------------------------------
    def set_text(self, text: str, markdown_final: bool = False):
        self._raw = text
        self.bubble.show()
        if not text:
            self.textb.hide()
            return
        self.textb.show()
        if markdown_final:
            self._streaming = False
            self.textb.setHtml(md_to_html(text))
            self.footer.show()
        else:
            self.textb.setPlainText(text)
        self._resize_text()
        self.updateGeometry()

    def _resize_text(self):
        width = 318 if self.role == "assistant" else 300
        doc = self.textb.document()
        doc.setTextWidth(width)
        h = doc.size().height() + 2
        self.textb.setFixedHeight(max(18, int(math.ceil(h))))
        self.textb.setFixedWidth(width)

    def finalize(self, text: str):
        self.set_text(text, True)

    def set_id(self, mid: str):
        self.message_id = mid
        self.regen_btn.setVisible(bool(mid)) if hasattr(self, "regen_btn") else None

    def set_character(self, character: str):
        self.character = theme.character_key(character)
        if self.role == "assistant":
            self.avatar.set_character(self.character)
            self.name_label.setText(theme.character_name(self.character))

    def add_attachments(self, paths: list[str | Path], removable: bool = False, on_remove=None):
        paths = [Path(p) for p in paths if Path(p).exists()]
        self._attachments.extend(paths)
        for p in paths:
            self.attach_layout.addWidget(AttachmentChip(p, removable=removable, on_remove=on_remove))
        if paths:
            self.attach_host.show()

    def add_media(self, paths: list[str | Path], kind: str, notes: list[str] | None = None):
        for i, p in enumerate(paths):
            card = MediaCard(p, kind, notes[i] if notes and i < len(notes) else "")
            card.open_requested.connect(self._open_media)
            self.media_layout.addWidget(card)
            self._media_cards.append(card)
        if paths:
            self.media_host.show()

    def add_progress(self, text: str) -> "ProgressCard":
        self.progress = ProgressCard(text)
        self.media_layout.addWidget(self.progress)
        self.media_host.show()
        self.bubble.show()
        return self.progress

    def finish_progress(self, text: str = "", error: bool = False):
        if self.progress:
            self.progress.stop()
            self.progress.hide()
            self.progress.setParent(None)
            self.progress.deleteLater()
            self.progress = None
        if not self._media_cards:
            self.media_host.hide()
        if text:
            self.set_text(text, True)
        if error:
            self.bubble.setStyleSheet(
                f"QFrame{{background:#FFF1EF;border:1px solid #F2C9C3;border-radius:16px;}}"
            )

    def _copy(self):
        QApplication.clipboard().setText(self._raw)
        self.copy_btn.setToolTip("已复制")

    def _open_media(self, path: str):
        if Path(path).suffix.lower() in media.VIDEO_EXTS:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        else:
            ImageViewer(path, self.window()).exec()
        self.media_open.emit(path)

    def showEvent(self, e):
        super().showEvent(e)
        self._resize_text()


class AttachmentChip(QFrame):
    remove_requested = Signal(str)

    def __init__(
        self,
        path: str | Path,
        removable: bool = False,
        on_remove=None,
        parent=None,
        compact: bool = False,
    ):
        super().__init__(parent)
        self.path = Path(path)
        self._compact = compact
        self.setObjectName("SoftCard")
        self.setFixedHeight(40 if compact else 48)
        self.setMaximumWidth(160 if compact else 188)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(3 if compact else 4, 3 if compact else 4, 5 if compact else 6, 3 if compact else 4)
        lay.setSpacing(4 if compact else 6)
        thumb = QLabel()
        thumb.setFixedSize(32 if compact else 38, 32 if compact else 38)
        pm = QPixmap(str(path))
        if pm.isNull() and Path(path).suffix.lower() in media.VIDEO_EXTS:
            try:
                cache = Path(path).parent.parent / "缓存"
                cache.mkdir(parents=True, exist_ok=True)
                vthumb = cache / (Path(path).stem + "_chip.jpg")
                if not vthumb.exists():
                    media.video_thumb(Path(path), vthumb)
                if vthumb.exists():
                    pm = QPixmap(str(vthumb))
            except Exception:
                pass
        if pm.isNull():
            pm = QPixmap(str(theme.ASSETS / "icon.png"))
        thumb.setPixmap(pm.scaled(32 if compact else 38, 32 if compact else 38, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation))
        thumb.setStyleSheet("border-radius:9px;background:#F5E7DE;")
        thumb.setScaledContents(True)
        lay.addWidget(thumb)
        col = QVBoxLayout()
        col.setSpacing(0)
        name = QLabel(self.path.name)
        name.setFont(font(8, QFont.Weight.DemiBold))
        name_width = 82 if compact else 108
        name.setMaximumWidth(name_width)
        fm = QFontMetrics(name.font())
        name.setText(fm.elidedText(self.path.name, Qt.TextElideMode.ElideMiddle, name_width))
        name.setToolTip(str(self.path))
        size = QLabel(media.pretty_size(self.path.stat().st_size) if self.path.exists() else "")
        size.setObjectName("Tiny")
        col.addWidget(name)
        col.addWidget(size)
        lay.addLayout(col)
        if removable:
            x = IconButton("close", "移除", 18 if compact else 20)
            x.clicked.connect(lambda: self._remove(on_remove))
            lay.addWidget(x)

    def _remove(self, cb):
        if cb:
            cb(str(self.path))
        self.remove_requested.emit(str(self.path))
        self.deleteLater()


# ----------------------------------------------------------------------
class ProgressCard(QFrame):
    def __init__(self, text: str = "正在处理…", parent=None):
        super().__init__(parent)
        self.setObjectName("TintCard")
        self.setMaximumWidth(346)
        self._angle = 0
        self._start = time.time()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 11, 12, 11)
        lay.setSpacing(10)
        self.spin = Spinner()
        lay.addWidget(self.spin)
        col = QVBoxLayout()
        col.setSpacing(2)
        self.label = QLabel(text)
        self.label.setFont(font(9, QFont.Weight.DemiBold))
        self.label.setStyleSheet(f"color:{PEACH_DEEP};")
        self.sub = QLabel("把灵感交给我，稍等一会儿")
        self.sub.setObjectName("Tiny")
        col.addWidget(self.label)
        col.addWidget(self.sub)
        lay.addLayout(col, 1)
        self.secs = QLabel("00:00")
        self.secs.setObjectName("Tiny")
        lay.addWidget(self.secs, 0, Qt.AlignmentFlag.AlignTop)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(500)

    def set_text(self, text: str):
        self.label.setText(text)

    def stop(self):
        self.timer.stop()

    def _tick(self):
        self.spin.step()
        elapsed = int(time.time() - self._start)
        self.secs.setText(f"{elapsed // 60:02d}:{elapsed % 60:02d}")


class Spinner(QWidget):
    def __init__(self, size: int = 24, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.angle = 0

    def step(self):
        self.angle = (self.angle + 28) % 360
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(3, 3, self.width() - 6, self.height() - 6)
        p.setPen(QPen(QColor("#F6D4C5"), 2.6))
        p.drawEllipse(r)
        p.setPen(QPen(QColor(PEACH_DEEP), 2.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(r, int(self.angle * 16), int(100 * 16))


# ----------------------------------------------------------------------
class DropOverlay(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.hide()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QColor(255, 250, 244, 236))
        p.setPen(QPen(QColor(PEACH_DEEP), 2, Qt.PenStyle.DashLine))
        r = QRectF(10, 10, self.width() - 20, self.height() - 20)
        p.drawRoundedRect(r, 22, 22)
        p.setPen(QColor(INK))
        p.setFont(font(14, QFont.Weight.Bold))
        p.drawText(r.adjusted(0, -18, 0, 0), Qt.AlignmentFlag.AlignCenter, "松手，让我看看")
        p.setPen(QColor(MUTED))
        p.setFont(font(9))
        p.drawText(r.adjusted(0, 18, 0, 0), Qt.AlignmentFlag.AlignCenter, "图片 · 文档 · 视频都可以")
        p.setPen(QPen(QColor(PEACH_DEEP), 2))
        c = r.center()
        p.drawLine(QPointF(c.x() - 12, c.y() - 46), QPointF(c.x() + 12, c.y() - 46))
        p.drawLine(QPointF(c.x(), c.y() - 58), QPointF(c.x(), c.y() - 34))


class ToastLabel(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(
            f"QLabel{{background:{INK};color:{CREAM};border-radius:10px;padding:7px 13px;font-size:12px;}}"
        )
        self.hide()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def show_text(self, text: str, ms: int = 2400):
        self.setText(text)
        self.adjustSize()
        self.show()
        self.raise_()
        parent = self.parentWidget()
        if parent:
            self.move((parent.width() - self.width()) // 2, parent.height() - self.height() - 58)
        self._timer.start(ms)
