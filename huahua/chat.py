"""The conversation panel: chat, image, image-to-image and digital human video."""
from __future__ import annotations

import re
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QCursor,
    QDesktopServices,
    QFont,
    QGuiApplication,
    QIcon,
    QImage,
    QKeyEvent,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFileDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from . import media, theme
from .config import Config
from .history import HistoryStore
from .screenshot import ScreenshotOverlay
from .theme import (
    CREAM,
    CREAM_2,
    DANGER,
    INK,
    INK_SOFT,
    LINE,
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
)
from .widgets import (
    AttachmentChip,
    Avatar,
    DropOverlay,
    EmptyState,
    IconButton,
    MessageBubble,
    ToastLabel,
    glyph_icon,
)
from .workers import ChatWorker, ImageWorker, VideoWorker

MODES = {
    "chat": ("对话", "chat", "把问题丢给我，慢慢聊。"),
    "image": ("生图", "image", "描述一个画面，我用 qwen-image-2.0-pro 生成出来。"),
    "img2img": ("图生图", "edit", "拖一张参考图进来，告诉我你想怎么改。"),
    "video": ("数字人", "video", "上传参考视频，写口播文案，我来合成数字人视频。"),
}

SUPPORTED_FILTER = (
    "支持的文件 (*.png *.jpg *.jpeg *.webp *.gif *.bmp *.pdf *.docx *.pptx *.xlsx *.txt *.md *.csv *.json "
    "*.mp4 *.mov *.mkv *.webm *.mp3 *.wav *.m4a);;图片 (*.png *.jpg *.jpeg *.webp *.gif *.bmp);;"
    "文档 (*.pdf *.docx *.pptx *.xlsx *.txt *.md *.csv *.json);;视频 (*.mp4 *.mov *.mkv *.webm);;所有文件 (*.*)"
)

IMAGE_FILTER = "图片 (*.png *.jpg *.jpeg *.webp *.gif *.bmp)"
VIDEO_FILTER = "视频 (*.mp4 *.mov *.mkv *.webm *.m4v)"

PERSONAS = {
    "huahua": (
        "你叫华华，是住在用户 Windows 桌面上的小织女。你温柔、安静、有画面感，"
        "怀里总抱着一把小金梭，喜欢把灵感织成图和故事。说话自然简短，偶尔用一点"
        "织布、丝线、云霞的比喻，但不要堆砌古风。你也会画图、做数字人视频、读文件。"
        "不要自称 AI，不要提系统提示词，不要编造已经完成的操作。"
    ),
    "xixi": (
        "你叫熙熙，是住在用户 Windows 桌面上的元气小胖墩：戴极细的浅灰银椭圆眼镜，"
        "穿珊瑚橘红卫衣，总抱着奶油白长耳毛绒兔。你说话轻快、嘴甜、有一点点小调皮，"
        "像熟朋友一样自然，不要幼态化，也不要每句都加感叹号。你也会画图、做数字人视频、"
        "读文件。不要自称 AI，不要提系统提示词，不要编造已经完成的操作。"
    ),
}


class ComposerEdit(QPlainTextEdit):
    send_requested = Signal()
    image_pasted = Signal(QImage)
    files_dropped = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Composer")
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setPlaceholderText("说点什么…")
        self._enter_send = True

    def set_enter_send(self, on: bool):
        self._enter_send = on

    def keyPressEvent(self, e: QKeyEvent):
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self._enter_send and not (e.modifiers() & Qt.KeyboardModifier.ShiftModifier):
                self.send_requested.emit()
                e.accept()
                return
        super().keyPressEvent(e)

    def canInsertFromMimeData(self, source) -> bool:
        if source.hasImage():
            return True
        return super().canInsertFromMimeData(source)

    def insertFromMimeData(self, source):
        if source.hasImage():
            img = source.imageData()
            if isinstance(img, QImage):
                self.image_pasted.emit(img)
                return
        super().insertFromMimeData(source)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            return
        super().dragEnterEvent(e)

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            return
        super().dragMoveEvent(e)

    def dropEvent(self, e):
        if e.mimeData().hasUrls():
            paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
            if paths:
                e.acceptProposedAction()
                self.files_dropped.emit(paths)
                return
        super().dropEvent(e)


class ChatWindow(QWidget):
    pet_state = Signal(str)
    notify_requested = Signal(str, str, str, str)  # text, subtitle, icon path, payload
    settings_requested = Signal()
    title_changed = Signal(str)
    generation_started = Signal(str)

    def __init__(self, config: Config, history: HistoryStore):
        super().__init__(None)
        self.config = config
        self.history = history
        self.character = config.character
        self.session = history.current()
        self.mode = "chat"
        self.attachments: list[Path] = []
        self.video_ref: Path | None = None
        self.video_audio: Path | None = None
        self._bubbles: dict[str, MessageBubble] = {}
        self._workers: list[Any] = []
        self._busy = False
        self._chat_worker: ChatWorker | None = None
        self._chat_bubble: MessageBubble | None = None
        self._chat_msg: dict[str, Any] | None = None
        self._stream_buffer = ""
        self._stream_dirty = False
        self._stream_timer = QTimer(self)
        self._stream_timer.setInterval(65)
        self._stream_timer.timeout.connect(self._flush_stream)
        self._screenshot: ScreenshotOverlay | None = None
        self._last_gen_paths: list[Path] = []
        self._drag_inside = False

        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAcceptDrops(True)
        self.resize(468, 720)
        self.setMinimumSize(416, 600)
        self.setWindowTitle(theme.character_name(self.character))
        self.setWindowIcon(QIcon(str(theme.character_icon_path(self.character))))

        self._build()
        self._refresh_profile_badge()
        self._update_status()
        self.set_mode("chat")
        self._render_session()

    # ------------------------------------------------------------------
    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 18, 18, 18)
        outer.setSpacing(0)
        self.panel = QFrame()
        self.panel.setObjectName("Panel")
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(48)
        shadow.setOffset(0, 14)
        shadow.setColor(QColor(82, 48, 34, 58))
        self.panel.setGraphicsEffect(shadow)
        outer.addWidget(self.panel)

        root = QVBoxLayout(self.panel)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # header ---------------------------------------------------------
        self.header = QFrame()
        self.header.setFixedHeight(78)
        self.header.setStyleSheet("background: transparent;")
        hl = QHBoxLayout(self.header)
        hl.setContentsMargins(18, 13, 14, 8)
        hl.setSpacing(11)
        self.avatar = Avatar(46, True, self.character)
        hl.addWidget(self.avatar)
        title_col = QVBoxLayout()
        title_col.setSpacing(1)
        title_row = QHBoxLayout()
        title_row.setSpacing(6)
        self.name_label = QLabel(theme.character_name(self.character))
        self.name_label.setFont(font(15, QFont.Weight.Bold))
        self.name_label.setStyleSheet(f"color:{INK};")
        title_row.addWidget(self.name_label)
        self.model_badge = QLabel("MoArk")
        self.model_badge.setObjectName("Badge")
        title_row.addWidget(self.model_badge)
        title_row.addStretch(1)
        title_col.addLayout(title_row)
        self.status_label = QLabel("● 在线")
        self.status_label.setStyleSheet(f"color:{TEAL_DEEP};font-size:10px;")
        title_col.addWidget(self.status_label)
        hl.addLayout(title_col, 1)

        self.new_btn = IconButton("plus", "新对话", 30)
        self.new_btn.clicked.connect(self.new_chat)
        self.history_btn = IconButton("history", "历史对话", 30)
        self.history_btn.clicked.connect(self._show_history)
        self.settings_btn = IconButton("settings", "设置", 30)
        self.settings_btn.clicked.connect(self.settings_requested.emit)
        self.min_btn = IconButton("minimize", "收起", 30)
        self.min_btn.clicked.connect(self.hide)
        self.close_btn = IconButton("close", "收起", 30)
        self.close_btn.clicked.connect(self.hide)
        for b in (self.new_btn, self.history_btn, self.settings_btn, self.min_btn, self.close_btn):
            hl.addWidget(b)
        root.addWidget(self.header)

        # mode tabs ------------------------------------------------------
        tab_wrap = QWidget()
        tw = QHBoxLayout(tab_wrap)
        tw.setContentsMargins(18, 0, 18, 10)
        tw.setSpacing(0)
        self.tab_bar = QFrame()
        self.tab_bar.setStyleSheet(
            f"QFrame{{background:{CREAM_2};border:1px solid {LINE};border-radius:15px;}}"
        )
        tbl = QHBoxLayout(self.tab_bar)
        tbl.setContentsMargins(4, 4, 4, 4)
        tbl.setSpacing(2)
        self.tab_group = QButtonGroup(self)
        self.tab_group.setExclusive(True)
        self.tab_buttons: dict[str, QPushButton] = {}
        for i, key in enumerate(("chat", "image", "img2img", "video")):
            label, glyph, _ = MODES[key]
            b = QPushButton(label)
            b.setObjectName("ModeTab")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setIcon(glyph_icon(glyph, MUTED, 15))
            b.setIconSize(QSize(14, 14))
            b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            b.setMinimumHeight(34)
            self.tab_group.addButton(b, i)
            tbl.addWidget(b)
            self.tab_buttons[key] = b
        self.tab_buttons["chat"].setChecked(True)
        self.tab_group.idClicked.connect(lambda i: self.set_mode(list(MODES.keys())[i]))
        tw.addWidget(self.tab_bar)
        root.addWidget(tab_wrap)

        # timeline -------------------------------------------------------
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setStyleSheet("QScrollArea{background:transparent;border:none;} QScrollArea > QWidget > QWidget{background:transparent;}")
        self.timeline = QWidget()
        self.timeline.setStyleSheet("background: transparent;")
        self.tl = QVBoxLayout(self.timeline)
        self.tl.setContentsMargins(16, 4, 16, 10)
        self.tl.setSpacing(12)
        self.tl.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.empty = EmptyState(self.character)
        self.empty.prompt_clicked.connect(self._use_prompt)
        self.tl.addWidget(self.empty)
        self.tl.addStretch(1)
        self.scroll.setWidget(self.timeline)
        root.addWidget(self.scroll, 1)

        # composer -------------------------------------------------------
        self.composer_wrap = QWidget()
        cw = QVBoxLayout(self.composer_wrap)
        cw.setContentsMargins(14, 0, 14, 13)
        cw.setSpacing(7)
        self.composer = QFrame()
        self.composer.setObjectName("SoftCard")
        self.composer.setStyleSheet(
            f"QFrame#SoftCard{{background:white;border:1px solid {LINE};border-radius:18px;}}"
        )
        cl = QVBoxLayout(self.composer)
        cl.setContentsMargins(11, 9, 9, 7)
        cl.setSpacing(5)

        self.attach_host = QWidget()
        self.attach_layout = QHBoxLayout(self.attach_host)
        self.attach_layout.setContentsMargins(1, 0, 1, 2)
        self.attach_layout.setSpacing(6)
        self.attach_host.hide()
        cl.addWidget(self.attach_host)

        self.edit = ComposerEdit()
        self.edit.setFixedHeight(36)
        self.edit.set_enter_send(self.config.get("behavior.enter_to_send", True))
        self.edit.send_requested.connect(self.send_current)
        self.edit.image_pasted.connect(self._paste_image)
        self.edit.files_dropped.connect(self.handle_dropped)
        self.edit.textChanged.connect(self._autosize)
        self.edit.installEventFilter(self)
        cl.addWidget(self.edit)

        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 0, 0, 0)
        bottom.setSpacing(3)
        self.attach_btn = IconButton("attach", "添加图片 / 文档 / 视频", 31)
        self.attach_btn.clicked.connect(self.pick_files)
        self.shot_btn = IconButton("camera", "截图问我", 31)
        self.shot_btn.clicked.connect(self.take_screenshot)
        bottom.addWidget(self.attach_btn)
        bottom.addWidget(self.shot_btn)
        self.mode_hint = QLabel("")
        self.mode_hint.setObjectName("Tiny")
        bottom.addWidget(self.mode_hint)
        self.sample_btn = QPushButton("示例数字人")
        self.sample_btn.setObjectName("Ghost")
        self.sample_btn.setStyleSheet(f"QPushButton{{color:{TEAL_DEEP};padding:4px 7px;font-size:11px;}}")
        self.sample_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.sample_btn.setToolTip("用一段 AI 合成的示例数字人视频先试试")
        self.sample_btn.clicked.connect(self.use_sample_avatar)
        self.sample_btn.hide()
        bottom.addWidget(self.sample_btn)
        bottom.addStretch(1)
        self.send_btn = QPushButton("发送")
        self.send_btn.setObjectName("Primary")
        self.send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.send_btn.setMinimumWidth(82)
        self.send_btn.setFixedHeight(35)
        self.send_btn.clicked.connect(self.send_current)
        bottom.addWidget(self.send_btn)
        cl.addLayout(bottom)
        cw.addWidget(self.composer)
        self.tip = QLabel("Enter 发送 · Shift + Enter 换行 · 拖文件进来也可以")
        self.tip.setObjectName("Tiny")
        self.tip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cw.addWidget(self.tip)
        root.addWidget(self.composer_wrap)

        self.drop_overlay = DropOverlay(self)
        self.toast = ToastLabel(self)

        # header drag
        for w in (self.header, self.name_label, self.status_label, self.avatar):
            w.installEventFilter(self)
            try:
                for child in w.findChildren(QWidget):
                    if not isinstance(child, QPushButton):
                        child.installEventFilter(self)
            except Exception:
                pass
        self._header_drag: QPoint | None = None
        self._header_origin: QPoint | None = None

    # ------------------------------------------------------------------
    def _autosize(self):
        doc = self.edit.document()
        h = doc.documentLayout().documentSize().height()
        self.edit.setFixedHeight(max(36, min(118, int(h) + 12)))
        self._refresh_placeholder()

    def _refresh_placeholder(self):
        if self.mode == "chat":
            p = f"和{theme.character_name(self.character)}说点什么…  也可以把文件拖进来"
        elif self.mode == "image":
            p = "描述你想要的画面，比如：雨后的江南小巷，青石板反光，电影感…"
        elif self.mode == "img2img":
            p = "想怎么改？比如：保持构图，换成吉卜力动画风…"
        else:
            p = "写下这段口播文案，我会合成声音并对上口型…"
        self.edit.setPlaceholderText(p)

    def apply_character(self):
        new = self.config.character
        if new == self.character:
            return
        self.character = new
        self.name_label.setText(theme.character_name(new))
        self.setWindowTitle(theme.character_name(new))
        self.setWindowIcon(QIcon(str(theme.character_icon_path(new))))
        self.avatar.set_character(new)
        self.empty.set_character(new)
        self.empty.set_pet("idle")
        for bubble in self._bubbles.values():
            bubble.set_character(new)
        self.set_mode(self.mode)
        self._refresh_placeholder()

    def _refresh_profile_badge(self):
        p = self.config.active_profile()
        badge = "MoArk" if "moark" in (p.get("base_url") or "").lower() else (p.get("name") or "API")
        self.model_badge.setText(badge[:16])

    def _update_status(self, text: str | None = None, color: str | None = None):
        if text is None:
            if not self.config.is_configured():
                text, color = "● 未配置 API", DANGER
            else:
                text, color = "● 在线", TEAL_DEEP
        self.status_label.setText(text)
        self.status_label.setStyleSheet(f"color:{color or TEAL_DEEP};font-size:10px;")

    def _send_label(self) -> str:
        if self.mode == "image":
            return "织一下" if self.character == "huahua" else "画一下"
        return {"chat": "发送", "img2img": "开始改", "video": "生成视频"}.get(self.mode, "发送")

    def _set_mode_ui(self):
        for key, b in self.tab_buttons.items():
            b.setChecked(key == self.mode)
        label, glyph, hint = MODES[self.mode]
        self.send_btn.setText(self._send_label())
        self.mode_hint.setText(
            {
                "chat": "DeepSeek V4.1",
                "image": "2048×2048 · qwen-image",
                "img2img": "需参考图 · qwen-image",
                "video": "Duix-Avatar",
            }[self.mode]
        )
        self.empty.set_mode(self.mode)
        self.sample_btn.setVisible(self.mode == "video")
        self._refresh_placeholder()

    def set_mode(self, mode: str):
        if mode not in MODES:
            mode = "chat"
        self.mode = mode
        self._set_mode_ui()
        if mode in ("image", "img2img", "video"):
            self.empty.set_pet({"image": "tool", "img2img": "blush", "video": "waiting"}[mode])
            if mode == "img2img" and not any(media.kind_of(p) == "image" for p in self.attachments):
                self.show_toast("先选一张参考图，或直接拖进来")
            if mode == "video" and not self.video_ref:
                self.show_toast("先选一段 5–30 秒的正面人物视频")
        else:
            self.empty.set_pet("idle")
        self.edit.setFocus()

    # ------------------------------------------------------------------
    # Attachments
    def pick_files(self):
        if self.mode == "video":
            filt = "参考视频或配音 (*.mp4 *.mov *.mkv *.webm *.m4v *.mp3 *.wav *.m4a *.aac *.flac)"
            files, _ = QFileDialog.getOpenFileNames(self, "选择参考视频或配音", str(Path.home()), filt)
            if files:
                self.add_paths(files)
            return
        filt = IMAGE_FILTER if self.mode == "img2img" else SUPPORTED_FILTER
        files, _ = QFileDialog.getOpenFileNames(self, "选择文件", str(Path.home()), filt)
        if files:
            self.add_paths(files)

    def pick_ref_video(self):
        f, _ = QFileDialog.getOpenFileName(self, "选择数字人参考视频", str(Path.home()), VIDEO_FILTER)
        if f:
            self.add_paths([f])

    def use_sample_avatar(self):
        sample = theme.ASSETS / "sample_avatar.mp4"
        if not sample.exists():
            self.show_toast("示例视频不见了，换一段自己的吧")
            return
        self.add_paths([sample])
        if not self._current_text():
            self.edit.setPlainText(f"大家好，我是{theme.character_name(self.character)}，很高兴在桌面上认识你。")
        self.show_toast("已放入 AI 合成的示例数字人，可以直接生成")
        self.edit.setFocus()

    def add_paths(self, paths: list[str | Path], auto_analyze: bool = False):
        added = False
        for raw in paths:
            p = Path(raw)
            if not p.exists() or not p.is_file():
                continue
            if p.stat().st_size > 300 * 1024 * 1024:
                self.show_toast(f"{p.name} 超过 300 MB，换个小一点的吧")
                continue
            k = media.kind_of(p)
            if self.mode == "video":
                if k == "video":
                    self.video_ref = p
                elif k == "audio":
                    self.video_audio = p
                else:
                    self.show_toast("数字人模式需要视频或音频，图片可以用「图生图」")
                    continue
            elif self.mode == "img2img":
                if k != "image":
                    self.show_toast("图生图只接受图片参考")
                    continue
                if len([x for x in self.attachments if media.kind_of(x) == "image"]) >= 3:
                    self.show_toast("最多 3 张参考图")
                    continue
                self.attachments.append(p)
            else:
                if p in self.attachments:
                    continue
                if len(self.attachments) >= 8:
                    self.show_toast("一次最多带 8 个附件")
                    break
                self.attachments.append(p)
            added = True
        if added:
            self._rebuild_attachments()
            self._update_status()
        if auto_analyze and added:
            self.set_mode("chat")
            if not self.edit.toPlainText().strip():
                kinds = {media.kind_of(Path(x)) for x in paths}
                if kinds == {"image"}:
                    prompt = "帮我看看这张图里有什么，提炼一下重点，并说说它适合用来做什么。"
                elif "video" in kinds:
                    prompt = "帮我看看这个视频讲了什么，按画面顺序提炼重点。"
                elif kinds and kinds.issubset({"pdf", "doc", "slides", "sheet", "text"}):
                    prompt = "帮我读一下这个文件，提炼关键信息、结论和待办事项。"
                else:
                    prompt = "帮我看看拖进来的这些内容，提炼一下对我有用的信息。"
                self.edit.setPlainText(prompt)
            self.send_current()

    def _rebuild_attachments(self):
        while self.attach_layout.count():
            item = self.attach_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()
        all_paths: list[Path] = []
        if self.video_ref:
            all_paths.append(self.video_ref)
        if self.video_audio:
            all_paths.append(self.video_audio)
        all_paths.extend(self.attachments)
        for p in all_paths:
            chip = AttachmentChip(p, removable=True, on_remove=self._remove_path)
            self.attach_layout.addWidget(chip)
        self.attach_layout.addStretch(1)
        self.attach_host.setVisible(bool(all_paths))

    def _remove_path(self, path: str):
        p = Path(path)
        if self.video_ref == p:
            self.video_ref = None
        if self.video_audio == p:
            self.video_audio = None
        self.attachments = [x for x in self.attachments if x != p]
        QTimer.singleShot(0, self._rebuild_attachments)

    def _paste_image(self, img: QImage):
        if img.isNull():
            return
        folder = self.config.output_dir / "缓存"
        folder.mkdir(parents=True, exist_ok=True)
        p = media.unique_path(folder, "粘贴图片", ".png")
        img.save(str(p), "PNG")
        self.add_paths([p])
        self.show_toast("图片已放进输入框")

    def take_screenshot(self):
        self.hide()
        QTimer.singleShot(180, self._do_screenshot)

    def _do_screenshot(self):
        self._screenshot = ScreenshotOverlay()
        self._screenshot.captured.connect(self._screenshot_done)
        self._screenshot.cancelled.connect(self.show_panel)
        self._screenshot.start()

    def _screenshot_done(self, pm: QPixmap):
        folder = self.config.output_dir / "缓存"
        folder.mkdir(parents=True, exist_ok=True)
        p = media.unique_path(folder, "截图", ".png")
        pm.save(str(p), "PNG")
        self.show()
        self.raise_()
        self.activateWindow()
        self.add_paths([p])
        self.edit.setFocus()
        self.show_toast("截图已放进输入框，想问什么？")

    # ------------------------------------------------------------------
    def _use_prompt(self, mode: str, text: str):
        self.set_mode(mode)
        self.edit.setPlainText(text)
        self.edit.setFocus()
        self.edit.moveCursor(self.edit.textCursor().MoveOperation.End)

    # ------------------------------------------------------------------
    def _current_text(self) -> str:
        return self.edit.toPlainText().strip()

    def _make_bubble(self, role: str, text: str, mode: str = "chat", msg_id: str = "", time_text: str = "") -> MessageBubble:
        b = MessageBubble(role, text, mode=mode, time_text=time_text, character=self.character)
        b.set_id(msg_id)
        b.regenerate_requested.connect(self.regenerate)
        b.setParent(self.timeline)
        self.tl.insertWidget(self.tl.count() - 1, b)
        if msg_id:
            self._bubbles[msg_id] = b
        self.empty.hide()
        QTimer.singleShot(30, self.scroll_bottom)
        return b

    def scroll_bottom(self):
        bar = self.scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _cleanup_bubble(self, mid: str):
        b = self._bubbles.pop(mid, None)
        if b:
            self.tl.removeWidget(b)
            b.deleteLater()

    # ------------------------------------------------------------------
    def send_current(self):
        if self._busy:
            self.show_toast(f"{theme.character_name(self.character)}还在忙，等这一件做完～")
            return
        if self.mode == "chat":
            self._send_chat()
        elif self.mode == "image":
            self._send_image(ref=False)
        elif self.mode == "img2img":
            self._send_image(ref=True)
        else:
            self._send_video()

    def _require_key(self) -> bool:
        if self.config.is_configured():
            return True
        self.show_toast("还没有配置 API Key，右键 → 设置里填一下")
        self.settings_requested.emit()
        return False

    def _send_chat(self):
        text = self._current_text()
        if not text and not self.attachments:
            return
        if not self._require_key():
            return
        if not text:
            text = "帮我看看这些内容，提炼一下重点。"
        paths = list(self.attachments)
        self.edit.clear()
        self.attachments = []
        self._rebuild_attachments()

        ts = time.strftime("%H:%M")
        msg_id = uuid.uuid4().hex[:12]
        user_msg = {"id": msg_id, "role": "user", "text": text, "mode": "chat", "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "attachments": [str(p) for p in paths]}
        self.history.append(user_msg, self.session)
        ub = self._make_bubble("user", text, "chat", msg_id, ts)
        if paths:
            ub.add_attachments(paths)

        context = [{"role": "system", "content": PERSONAS[self.character]}]
        context += self.history.messages_for_api(self.session, 16)[:-1]
        content = self._build_content(text, paths)
        context.append({"role": "user", "content": content})

        aid = uuid.uuid4().hex[:12]
        amsg = {"id": aid, "role": "assistant", "text": "", "mode": "chat", "kind": "progress", "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}
        self.history.append(amsg, self.session)
        ab = self._make_bubble("assistant", "", "chat", aid, time.strftime("%H:%M"))
        ab.add_progress(f"{theme.character_name(self.character)}正在想…")
        self._chat_bubble = ab
        self._chat_msg = amsg
        self._stream_buffer = ""
        self._stream_dirty = False
        self._set_busy(True, "● 正在想…")
        self.pet_state.emit("thinking")
        self._stream_timer.start()

        worker = ChatWorker(self.config.active_profile(), self.config.api_key(), context, self.config.get("behavior.deep_think", False))
        self._chat_worker = worker
        worker.delta.connect(self._on_delta)
        worker.completed.connect(self._on_chat_done)
        worker.failed.connect(self._on_chat_failed)
        worker.finished.connect(lambda: self._worker_finished(worker))
        self._workers.append(worker)
        worker.start()
        self.title_changed.emit(self.session.get("title", ""))

    def _build_content(self, text: str, paths: list[Path]):
        images: list[str] = []
        doc_parts: list[str] = []
        for p in paths[:8]:
            try:
                ctx, imgs = media.file_prompt_payload(p)
            except Exception as e:
                ctx, imgs = f"[附件 {p.name} 读取失败：{e}]", []
            if ctx:
                doc_parts.append(ctx)
            for u in imgs:
                if len(images) < 5:
                    images.append(u)
        full = text
        if doc_parts:
            full = text + "\n\n" + "\n\n".join(doc_parts)
        full = full[:70000]
        if not images:
            return full
        content: list[dict[str, Any]] = [{"type": "text", "text": full}]
        for u in images:
            content.append({"type": "image_url", "image_url": {"url": u, "detail": "auto"}})
        return content

    def _on_delta(self, piece: str):
        self._stream_buffer += piece
        self._stream_dirty = True

    def _flush_stream(self):
        if not self._stream_dirty or not self._chat_bubble:
            return
        self._stream_dirty = False
        text = self._stream_buffer
        if len(text) > 4:
            self._chat_bubble.set_text(text)
            self.scroll_bottom()

    def _on_chat_done(self, text: str):
        self._stream_timer.stop()
        self._stream_buffer = text or self._stream_buffer
        if not self._chat_bubble or not self._chat_msg:
            return
        final = self._stream_buffer.strip() or "嗯…这次没想出来，再试一次？"
        self._chat_bubble.finish_progress()
        self._chat_bubble.finalize(final)
        self._chat_msg["text"] = final
        self._chat_msg["kind"] = "normal"
        self.history.update(self._chat_msg, self.session)
        self._set_busy(False)
        self.pet_state.emit("success")
        QTimer.singleShot(1500, lambda: self.pet_state.emit("idle"))
        if not self.isVisible() or not self.isActiveWindow():
            snippet = re.sub(r"\s+", " ", final)[:34]
            self.notify_requested.emit("回答好啦", snippet, "", f"session:{self.session['id']}")
        QTimer.singleShot(100, self.scroll_bottom)

    def _mark_error_status(self, err: str):
        if any(k in err for k in ("401", "403", "API Key", "权限", "额度")):
            self._update_status("● 检查 API 设置", DANGER)
        else:
            self._update_status("● 稍后再试", DANGER)

    def _on_chat_failed(self, err: str):
        self._stream_timer.stop()
        if not self._chat_bubble or not self._chat_msg:
            return
        self._chat_bubble.finish_progress()
        self._chat_bubble.finish_progress("唔，遇到一点问题：\n\n" + err, error=True)
        self._chat_msg["text"] = "唔，遇到一点问题：" + err
        self._chat_msg["kind"] = "error"
        self.history.update(self._chat_msg, self.session)
        self._set_busy(False)
        self._mark_error_status(err)
        self.pet_state.emit("failure")
        QTimer.singleShot(1700, lambda: self.pet_state.emit("idle"))
        self.scroll_bottom()

    # ------------------------------------------------------------------
    def _send_image(self, ref: bool):
        text = self._current_text()
        images = [p for p in self.attachments if media.kind_of(p) == "image"]
        if ref and not images:
            self.show_toast("图生图需要一张参考图，先选一张吧")
            self.pick_files()
            return
        if not text and not images:
            self.show_toast("先写一句画面描述，或者拖一张参考图进来")
            return
        if not self._require_key():
            return
        if not text:
            text = "参考这张图，保持主体不变，做一点温柔的改编。"
        data_urls: list[str] = []
        for p in images[:3]:
            try:
                data_urls.append(media.image_data_url(p, 1600))
            except Exception:
                pass
        self.edit.clear()
        self.attachments = []
        self._rebuild_attachments()
        ts = time.strftime("%H:%M")
        uid = uuid.uuid4().hex[:12]
        umsg = {"id": uid, "role": "user", "text": text, "mode": "img2img" if ref else "image", "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "attachments": [str(p) for p in images]}
        self.history.append(umsg, self.session)
        ub = self._make_bubble("user", text, "img2img" if ref else "image", uid, ts)
        if images:
            ub.add_attachments(images)

        aid = uuid.uuid4().hex[:12]
        amsg = {"id": aid, "role": "assistant", "text": "", "mode": "img2img" if ref else "image", "kind": "progress", "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}
        self.history.append(amsg, self.session)
        ab = self._make_bubble("assistant", "", "img2img" if ref else "image", aid, time.strftime("%H:%M"))
        verb = "织" if self.character == "huahua" else "画"
        progress = ab.add_progress(f"正在把灵感{verb}成画面…")
        self._set_busy(True, f"● 正在{verb}图…")
        self.pet_state.emit("tool")
        worker = ImageWorker(
            self.config.active_profile(), self.config.api_key(), text, self.config.output_dir,
            images=data_urls, n=1,
        )
        worker.progress.connect(lambda s: (progress.set_text(s), self._update_status(s, PEACH_DEEP)))
        worker.completed.connect(lambda paths: self._on_image_done(paths, ab, amsg, text))
        worker.failed.connect(lambda e: self._on_image_failed(e, ab, amsg))
        worker.finished.connect(lambda: self._worker_finished(worker))
        self._workers.append(worker)
        worker.start()
        self.title_changed.emit(self.session.get("title", ""))

    def _on_image_done(self, paths: list[Path], bubble: MessageBubble, msg: dict[str, Any], prompt: str):
        verb = "织" if self.character == "huahua" else "画"
        bubble.finish_progress()
        bubble.finalize(f"{verb}好啦，看看这张。")
        bubble.add_media(paths, "image")
        msg["text"] = f"{verb}好啦，看看这张。"
        msg["kind"] = "normal"
        msg["results"] = [{"kind": "image", "path": str(p)} for p in paths]
        self.history.update(msg, self.session)
        self._set_busy(False)
        self.pet_state.emit("success")
        QTimer.singleShot(1700, lambda: self.pet_state.emit("idle"))
        QTimer.singleShot(160, self.scroll_bottom)
        if paths and self.config.get("storage.auto_open", False):
            QTimer.singleShot(250, lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(paths[0]))))
        if paths:
            self.notify_requested.emit(f"图{verb}好啦", "点我看看这张小画", str(paths[0]), f"session:{self.session['id']}")

    def _on_image_failed(self, err: str, bubble: MessageBubble, msg: dict[str, Any]):
        verb = "织" if self.character == "huahua" else "画"
        bubble.finish_progress()
        bubble.finish_progress(f"这次没{verb}成：\n\n" + err, error=True)
        msg["text"] = f"这次没{verb}成：" + err
        msg["kind"] = "error"
        self.history.update(msg, self.session)
        self._set_busy(False)
        self._mark_error_status(err)
        self.pet_state.emit("failure")
        QTimer.singleShot(1700, lambda: self.pet_state.emit("idle"))
        self.scroll_bottom()

    # ------------------------------------------------------------------
    def _send_video(self):
        if not self.video_ref:
            self.show_toast("数字人需要一个参考视频，先选一段吧")
            self.pick_ref_video()
            return
        text = self._current_text()
        if not text and not self.video_audio:
            self.show_toast("写一段口播文案，或者带一个配音音频")
            return
        if len(text) > 600:
            self.show_toast("口播文案先控制在 600 字以内，成片会更稳")
            return
        if not self._require_key():
            return
        script = text or "（使用上传的配音）"
        ref = self.video_ref
        audio = self.video_audio
        attachments = [p for p in (ref, audio) if p]
        self.edit.clear()
        self.video_ref = None
        self.video_audio = None
        self._rebuild_attachments()
        ts = time.strftime("%H:%M")
        uid = uuid.uuid4().hex[:12]
        umsg = {"id": uid, "role": "user", "text": script, "mode": "video", "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "attachments": [str(p) for p in attachments]}
        self.history.append(umsg, self.session)
        ub = self._make_bubble("user", script, "video", uid, ts)
        ub.add_attachments(attachments)

        aid = uuid.uuid4().hex[:12]
        amsg = {"id": aid, "role": "assistant", "text": "", "mode": "video", "kind": "progress", "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}
        self.history.append(amsg, self.session)
        ab = self._make_bubble("assistant", "", "video", aid, time.strftime("%H:%M"))
        progress = ab.add_progress("正在准备数字人…")
        self._set_busy(True, "● 数字人准备中…")
        self.pet_state.emit("waiting")
        worker = VideoWorker(
            self.config.active_profile(), self.config.api_key(), ref, script,
            self.config.output_dir, audio=audio,
        )
        worker.progress.connect(lambda s: (progress.set_text(s), self._update_status(s, PEACH_DEEP)))
        worker.completed.connect(lambda d: self._on_video_done(d, ab, amsg))
        worker.failed.connect(lambda e: self._on_video_failed(e, ab, amsg))
        worker.finished.connect(lambda: self._worker_finished(worker))
        self._workers.append(worker)
        worker.start()
        self.title_changed.emit(self.session.get("title", ""))

    def _on_video_done(self, data: dict[str, str], bubble: MessageBubble, msg: dict[str, Any]):
        video = Path(data.get("video", ""))
        bubble.finish_progress()
        bubble.finalize("成片出来啦！点封面就能播放。")
        bubble.add_media([video], "video", ["Duix-Avatar · 数字人口播"])
        msg["text"] = "成片出来啦！点封面就能播放。"
        msg["kind"] = "normal"
        msg["results"] = [{"kind": "video", "path": str(video)}]
        if data.get("audio"):
            msg["results"].append({"kind": "audio", "path": data["audio"]})
        self.history.update(msg, self.session)
        self._set_busy(False)
        self.pet_state.emit("success")
        QTimer.singleShot(1900, lambda: self.pet_state.emit("idle"))
        QTimer.singleShot(200, self.scroll_bottom)
        if self.config.get("storage.auto_open", False):
            QTimer.singleShot(300, lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(video))))
        self.notify_requested.emit("数字人视频做好啦", "点我看看成片", str(video), f"session:{self.session['id']}")

    def _on_video_failed(self, err: str, bubble: MessageBubble, msg: dict[str, Any]):
        bubble.finish_progress()
        bubble.finish_progress("这次视频没合成成功：\n\n" + err, error=True)
        msg["text"] = "这次视频没合成成功：" + err
        msg["kind"] = "error"
        self.history.update(msg, self.session)
        self._set_busy(False)
        self._mark_error_status(err)
        self.pet_state.emit("failure")
        QTimer.singleShot(1800, lambda: self.pet_state.emit("idle"))
        self.scroll_bottom()

    # ------------------------------------------------------------------
    def _set_busy(self, busy: bool, status: str | None = None):
        self._busy = busy
        self.send_btn.setEnabled(not busy)
        self.send_btn.setText("处理中…" if busy else self._send_label())
        if busy:
            self._update_status(status or "● 正在处理…", PEACH_DEEP)
            self.avatar.set_online(False)
        else:
            self._update_status()
            self.avatar.set_online(True)

    def _worker_finished(self, worker):
        try:
            if worker in self._workers:
                self._workers.remove(worker)
            worker.deleteLater()
        except Exception:
            pass
        if worker is self._chat_worker:
            self._chat_worker = None

    # ------------------------------------------------------------------
    def regenerate(self, mid: str):
        if self._busy:
            self.show_toast("等这一件做完再重答吧")
            return
        msgs = self.session.get("messages", [])
        idx = next((i for i, m in enumerate(msgs) if m.get("id") == mid), -1)
        if idx < 0:
            return
        if idx != len(msgs) - 1 or msgs[idx].get("role") != "assistant":
            self.show_toast("只能重答最后一条回答")
            return
        prev_user = next((m for m in reversed(msgs[:idx]) if m.get("role") == "user"), None)
        if not prev_user:
            return
        self.history.delete_message(mid, self.session)
        self.session["messages"] = [m for m in self.session.get("messages", []) if m.get("id") != mid]
        self._cleanup_bubble(mid)
        self.set_mode("chat")
        self.edit.setPlainText(prev_user.get("text", ""))
        self.send_current()

    # ------------------------------------------------------------------
    def new_chat(self):
        if self._busy:
            self.show_toast(f"等{theme.character_name(self.character)}做完手上的事再开新对话")
            return
        self.session = self.history.new_session()
        self.config.set("ui.last_session", self.session["id"])
        self.config.save()
        self._render_session()
        self.show_toast("开了一页新的织布机")
        self.title_changed.emit(self.session.get("title", ""))

    def _show_history(self):
        menu = QMenu(self)
        menu.setStyleSheet(theme.qss())
        a = menu.addAction("＋  新对话")
        a.triggered.connect(self.new_chat)
        menu.addSeparator()
        recent = self.history.recent(10)
        if not recent:
            a = menu.addAction("还没有历史对话")
            a.setEnabled(False)
        for s in recent:
            title = s.get("title") or "未命名"
            mark = "● " if s.get("id") == self.session.get("id") else ""
            a = menu.addAction(f"{mark}{title}")
            a.triggered.connect(lambda _=False, sid=s["id"]: self.load_session(sid))
        menu.addSeparator()
        a = menu.addAction("清空当前对话")
        a.triggered.connect(self.clear_current)
        a = menu.addAction("清空全部历史")
        a.triggered.connect(self.clear_all)
        menu.exec(self.history_btn.mapToGlobal(QPoint(0, self.history_btn.height() + 5)))

    def load_session(self, sid: str):
        if self._busy:
            self.show_toast("等这一件做完再切换对话")
            return
        s = self.history.switch(sid)
        if s:
            self.session = s
            self.config.set("ui.last_session", sid)
            self.config.save()
            self._render_session()
            self.title_changed.emit(s.get("title", ""))

    def clear_current(self):
        if self._busy:
            return
        self.session["messages"] = []
        self.session["title"] = "新的对话"
        self.session["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        self.history.save()
        self._render_session()
        self.title_changed.emit("")

    def clear_all(self):
        if QMessageBox.question(self, "清空全部历史", "会把所有对话和本地记录都删掉，作品文件不会被删。继续吗？") == QMessageBox.StandardButton.Yes:
            self.history.clear()
            self.session = self.history.new_session()
            self._render_session()
            self.title_changed.emit("")

    def _render_session(self):
        for b in list(self._bubbles.values()):
            self.tl.removeWidget(b)
            b.deleteLater()
        self._bubbles.clear()
        # remove non-empty-state widgets
        for i in reversed(range(self.tl.count())):
            w = self.tl.itemAt(i).widget()
            if w and w is not self.empty:
                self.tl.removeWidget(w)
                w.deleteLater()
        msgs = self.session.get("messages", [])
        if not msgs:
            self.empty.show()
            self.empty.set_mode(self.mode)
            return
        self.empty.hide()
        for m in msgs:
            if m.get("kind") == "progress":
                continue
            text = m.get("text", "")
            if not text and not m.get("results"):
                continue
            role = m.get("role", "assistant")
            b = MessageBubble(
                role, text, mode=m.get("mode", "chat"), time_text=self._time_of(m), character=self.character
            )
            b.set_id(m.get("id", ""))
            b.regenerate_requested.connect(self.regenerate)
            b.setParent(self.timeline)
            self.tl.insertWidget(self.tl.count() - 1, b)
            self._bubbles[m.get("id", "")] = b
            atts = [Path(p) for p in m.get("attachments", []) if Path(p).exists()]
            if atts:
                b.add_attachments(atts)
            results = m.get("results", [])
            for r in results:
                if r.get("kind") in ("image", "video") and Path(r.get("path", "")).exists():
                    b.add_media([r["path"]], r["kind"])
                elif r.get("kind") == "audio" and Path(r.get("path", "")).exists():
                    pass
            if m.get("kind") == "error":
                b.bubble.setStyleSheet(
                    "QFrame{background:#FFF1EF;border:1px solid #F2C9C3;border-radius:16px;}"
                )
        QTimer.singleShot(40, self.scroll_bottom)

    def _time_of(self, m: dict[str, Any]) -> str:
        ts = m.get("ts") or ""
        try:
            return ts.split("T")[1][:5]
        except Exception:
            return time.strftime("%H:%M")

    # ------------------------------------------------------------------
    def show_toast(self, text: str, ms: int = 2600):
        if self.toast:
            self.toast.show_text(text, ms)

    def show_panel(self):
        if not self.isVisible():
            self.show()
        self.raise_()
        self.activateWindow()
        QTimer.singleShot(80, lambda: self.edit.setFocus())

    # ------------------------------------------------------------------
    def eventFilter(self, obj, event):
        if obj is self.edit and event.type() == QEvent.Type.KeyPress:
            pass
        if event.type() == QEvent.Type.MouseButtonPress and isinstance(event, QEvent) and hasattr(event, "globalPosition"):
            if isinstance(obj, (QLabel, Avatar)) or obj is self.header:
                try:
                    if event.button() == Qt.MouseButton.LeftButton:
                        self._header_drag = event.globalPosition().toPoint()
                        self._header_origin = self.pos()
                except Exception:
                    pass
        elif event.type() == QEvent.Type.MouseMove and self._header_drag is not None:
            try:
                gp = event.globalPosition().toPoint()
                self.move(self._header_origin + (gp - self._header_drag))
            except Exception:
                pass
        elif event.type() == QEvent.Type.MouseButtonRelease:
            if self._header_drag is not None:
                self._header_drag = None
                self.config.set("ui.chat_pos", [self.x(), self.y()])
                self.config.save()
        return super().eventFilter(obj, event)

    # ------------------------------------------------------------------
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
            if paths:
                self._drag_inside = True
                self.drop_overlay.setGeometry(self.rect())
                self.drop_overlay.show()
                self.drop_overlay.raise_()
                e.acceptProposedAction()
                return
        e.ignore()

    def dragLeaveEvent(self, e):
        self._drag_inside = False
        self.drop_overlay.hide()
        e.accept()

    def dropEvent(self, e):
        self._drag_inside = False
        self.drop_overlay.hide()
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if paths:
            e.acceptProposedAction()
            self.handle_dropped(paths)

    def handle_dropped(self, paths: list[str]):
        self.show_panel()
        self.set_mode("chat")
        self.add_paths(paths, auto_analyze=True)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.drop_overlay.setGeometry(self.rect())
        if self.toast and self.toast.isVisible():
            self.toast.move((self.width() - self.toast.width()) // 2, self.height() - self.toast.height() - 24)

    def closeEvent(self, e):
        self.hide()
        e.ignore()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.hide()
        else:
            super().keyPressEvent(e)

    def shutdown(self):
        self._stream_timer.stop()
        for w in list(self._workers):
            try:
                if hasattr(w, "stop"):
                    w.stop()
                if not w.wait(1800):
                    # The window is going away anyway; don't let a blocked HTTP
                    # request keep a Python thread alive during interpreter exit.
                    w.terminate()
                    w.wait(500)
            except Exception:
                pass
        self.config.set("ui.chat_pos", [self.x(), self.y()])
        self.config.save()
