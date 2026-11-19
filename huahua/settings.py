"""The right-click settings centre."""
from __future__ import annotations

import copy
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from . import __version__, secrets, theme
from .config import Config, default_output_dir, new_profile, set_autostart
from .history import HistoryStore
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
from .widgets import Avatar, IconButton, ToastLabel
from .workers import TestWorker


class PetPreview(QWidget):
    def __init__(self, size: int = 280, character: str = "huahua", parent=None):
        super().__init__(parent)
        self._size = size
        self._sprite = "idle"
        self.character = theme.character_key(character)
        self.setFixedSize(190, 230)

    def set_state(self, size: int, sprite: str = "idle", character: str | None = None):
        self._size = size
        self._sprite = sprite
        if character:
            self.character = theme.character_key(character)
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        pm = theme.pixmap(self._sprite, self.character)
        w = min(self.width() - 20, int(self._size * 0.62))
        h = int(w * pm.height() / max(1, pm.width()))
        if h > self.height() - 24:
            h = self.height() - 24
            w = int(h * pm.width() / max(1, pm.height()))
        p.setBrush(QColor(255, 232, 220, 100))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QRect((self.width() - w) // 2, 2, w, int(h * 0.96)))
        p.drawPixmap(
            QRect((self.width() - w) // 2, 8 + (self.height() - h) // 2, w, h),
            pm,
            pm.rect(),
        )


class CharacterCard(QFrame):
    clicked = Signal(str)

    def __init__(self, key: str, parent=None):
        super().__init__(parent)
        self.key = key
        meta = theme.CHARACTERS[key]
        self.setObjectName("CharacterCard")
        self.setFixedHeight(76)
        self.setToolTip(meta["description"])
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 7, 12, 7)
        lay.setSpacing(10)
        self.avatar = QLabel()
        self.avatar.setFixedSize(56, 56)
        self.avatar.setPixmap(theme.avatar_pixmap(56, key))
        lay.addWidget(self.avatar)
        col = QVBoxLayout()
        col.setSpacing(2)
        name = QLabel(meta["name"])
        name.setFont(font(12, QFont.Weight.Bold))
        tag = QLabel(meta["tagline"])
        tag.setStyleSheet(f"color:{meta['accent']};font-size:10px;font-weight:600;")
        hint = QLabel("点一下切换")
        hint.setObjectName("Tiny")
        col.addWidget(name)
        col.addWidget(tag)
        col.addWidget(hint)
        lay.addLayout(col, 1)
        self.dot = QLabel("")
        self.dot.setFixedSize(16, 16)
        lay.addWidget(self.dot, 0, Qt.AlignmentFlag.AlignTop)
        # Let a click anywhere on the card reach the card itself.
        for child in self.findChildren(QWidget):
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.set_selected(False)

    def set_selected(self, on: bool):
        meta = theme.CHARACTERS[self.key]
        if on:
            self.setStyleSheet(
                f"QFrame#CharacterCard{{background:{meta['soft']};border:2px solid {meta['accent']};border-radius:16px;}}"
            )
            self.dot.setStyleSheet(
                f"background:{meta['accent']};border-radius:8px;border:3px solid white;"
            )
        else:
            self.setStyleSheet(
                f"QFrame#CharacterCard{{background:white;border:1px solid {LINE};border-radius:16px;}}"
            )
            self.dot.setStyleSheet("background:transparent;border-radius:8px;border:1px solid #E4CFC5;")

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.key)
        super().mouseReleaseEvent(e)


class SettingsDialog(QDialog):
    saved = Signal()
    clear_history_requested = Signal()

    NAV = [
        ("api", "接口与模型", "settings"),
        ("appearance", "桌宠外观", "palette"),
        ("storage", "存储位置", "folder"),
        ("behavior", "互动习惯", "heart"),
        ("about", "关于", "sparkle"),
    ]

    def __init__(self, config: Config, history: HistoryStore, parent=None):
        super().__init__(parent)
        self.config = config
        self.history = history
        self.draft: dict[str, Any] = config.snapshot()
        self._current_profile_id: str | None = None
        self._test_worker: TestWorker | None = None
        self._drag: QPoint | None = None
        self._drag_origin: QPoint | None = None
        self._saved = False

        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle("华华和熙熙 · 设置")
        self.setWindowIcon(QIcon(str(theme.character_icon_path(config.character))))
        self.resize(840, 640)
        self._build()
        self._load_all()

    # ------------------------------------------------------------------
    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        self.panel = QFrame()
        self.panel.setObjectName("Panel")
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(50)
        shadow.setOffset(0, 16)
        shadow.setColor(QColor(68, 40, 30, 62))
        self.panel.setGraphicsEffect(shadow)
        outer.addWidget(self.panel)

        root = QVBoxLayout(self.panel)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        top = QWidget()
        tl = QHBoxLayout(top)
        tl.setContentsMargins(22, 16, 16, 10)
        tl.setSpacing(10)
        logo = QLabel()
        logo.setPixmap(theme.avatar_pixmap(38, self.config.character))
        logo.setFixedSize(38, 38)
        self.logo = logo
        tl.addWidget(logo)
        col = QVBoxLayout()
        col.setSpacing(0)
        title = QLabel("设置")
        title.setFont(font(15, QFont.Weight.Bold))
        sub = QLabel("把华华和熙熙调成你最顺手的样子")
        sub.setObjectName("Hint")
        col.addWidget(title)
        col.addWidget(sub)
        tl.addLayout(col, 1)
        close = IconButton("close", "关闭", 32)
        close.clicked.connect(self.reject)
        tl.addWidget(close)
        root.addWidget(top)
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background:{LINE};")
        root.addWidget(line)

        body = QHBoxLayout()
        body.setContentsMargins(16, 12, 16, 10)
        body.setSpacing(14)

        side = QFrame()
        side.setFixedWidth(174)
        side.setStyleSheet(f"QFrame{{background:{CREAM_2};border:1px solid {LINE};border-radius:16px;}}")
        sl = QVBoxLayout(side)
        sl.setContentsMargins(8, 10, 8, 10)
        sl.setSpacing(3)
        self.nav_group: list[QPushButton] = []
        for i, (key, label, glyph) in enumerate(self.NAV):
            b = QPushButton(label)
            b.setObjectName("NavTab")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setIcon(theme_icon(glyph, INK_SOFT, 16))
            b.setIconSize(QSize(16, 16))
            b.clicked.connect(lambda _=False, n=i: self._show_page(n))
            sl.addWidget(b)
            self.nav_group.append(b)
        self.nav_group[0].setChecked(True)
        sl.addStretch(1)
        version = QLabel(f"华华 & 熙熙  v{__version__}\n模力方舟 · 四模型合体")
        version.setObjectName("Tiny")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sl.addWidget(version)
        body.addWidget(side)

        self.stack = QStackedWidget()
        self.stack.setStyleSheet("QStackedWidget{background:transparent;}")
        self.pages: list[QWidget] = []
        self.pages.append(self._page_api())
        self.pages.append(self._page_appearance())
        self.pages.append(self._page_storage())
        self.pages.append(self._page_behavior())
        self.pages.append(self._page_about())
        for p in self.pages:
            self.stack.addWidget(p)
        body.addWidget(self.stack, 1)
        root.addLayout(body, 1)

        line2 = QFrame()
        line2.setFixedHeight(1)
        line2.setStyleSheet(f"background:{LINE};")
        root.addWidget(line2)
        footer = QWidget()
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(20, 10, 18, 14)
        fl.setSpacing(8)
        reset_pos = QPushButton("重置桌宠位置")
        reset_pos.setObjectName("Ghost")
        reset_pos.clicked.connect(self._reset_pet_pos)
        fl.addWidget(reset_pos)
        fl.addStretch(1)
        cancel = QPushButton("取消")
        cancel.setObjectName("Ghost")
        cancel.setMinimumWidth(72)
        cancel.clicked.connect(self.reject)
        fl.addWidget(cancel)
        save = QPushButton("保存并应用")
        save.setObjectName("Primary")
        save.setMinimumWidth(112)
        save.setFixedHeight(36)
        save.clicked.connect(self._save)
        fl.addWidget(save)
        root.addWidget(footer)

        self.toast = ToastLabel(self)

        # drag window from the top area
        top.installEventFilter(self)
        logo.installEventFilter(self)
        title.installEventFilter(self)
        sub.installEventFilter(self)

    # ------------------------------------------------------------------
    def _scroll_page(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea{background:transparent;} QScrollArea > QWidget > QWidget{background:transparent;}")
        content = QWidget()
        content.setStyleSheet("background:transparent;")
        lay = QVBoxLayout(content)
        lay.setContentsMargins(4, 2, 10, 18)
        lay.setSpacing(12)
        scroll.setWidget(content)
        return scroll, lay

    def _page_header(self, lay, title: str, subtitle: str):
        t = QLabel(title)
        t.setFont(font(17, QFont.Weight.Bold))
        s = QLabel(subtitle)
        s.setObjectName("Hint")
        s.setWordWrap(True)
        lay.addWidget(t)
        lay.addWidget(s)

    def _section(self, lay, title: str):
        l = QLabel(title)
        l.setObjectName("SectionTitle")
        lay.addSpacing(4)
        lay.addWidget(l)

    def _card(self):
        f = QFrame()
        f.setObjectName("SoftCard")
        l = QVBoxLayout(f)
        l.setContentsMargins(14, 12, 14, 12)
        l.setSpacing(9)
        return f, l

    def _row(self, label: str, widget: QWidget, hint: str = "", stretch=True):
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(12)
        l = QLabel(label)
        l.setMinimumWidth(84)
        l.setFont(font(9, QFont.Weight.DemiBold))
        l.setStyleSheet(f"color:{INK_SOFT};")
        h.addWidget(l)
        h.addWidget(widget, 1 if stretch else 0)
        box = QVBoxLayout()
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(2)
        box.addWidget(row)
        if hint:
            hh = QLabel(hint)
            hh.setObjectName("Tiny")
            hh.setWordWrap(True)
            hh.setContentsMargins(96, 0, 0, 0)
            box.addWidget(hh)
        wrap = QWidget()
        wrap.setLayout(box)
        return wrap

    def _check(self, text: str, hint: str = "") -> QCheckBox:
        c = QCheckBox(text)
        c.setCursor(Qt.CursorShape.PointingHandCursor)
        c.setToolTip(hint)
        return c

    # ------------------------------------------------------------------
    def _page_api(self):
        page, lay = self._scroll_page()
        self._page_header(lay, "接口与模型", "小工具的全部能力都走模力方舟（MoArk）的 OpenAI 兼容接口。一个 Key，四个模型。")

        tip = QFrame()
        tip.setObjectName("TealCard")
        tl = QHBoxLayout(tip)
        tl.setContentsMargins(13, 10, 13, 10)
        tl.setSpacing(9)
        i = QLabel("")
        i.setPixmap(theme.avatar_pixmap(26))
        tl.addWidget(i)
        lab = QLabel("对话 DeepSeek-V4.1-Flash-1017 · 生图 qwen-image-2.0-pro · 视频 Duix-Avatar · 配音 Qwen3-TTS")
        lab.setWordWrap(True)
        lab.setStyleSheet(f"color:{TEAL_DEEP};font-size:11px;")
        tl.addWidget(lab, 1)
        lay.addWidget(tip)

        self._section(lay, "接口方案")
        card, cl = self._card()
        top = QHBoxLayout()
        top.setSpacing(7)
        self.profile_combo = QComboBox()
        self.profile_combo.setMinimumWidth(190)
        self.profile_combo.currentIndexChanged.connect(self._profile_changed)
        top.addWidget(self.profile_combo, 1)
        addb = QPushButton("＋ 添加")
        addb.setObjectName("Ghost")
        addb.clicked.connect(self._add_profile)
        top.addWidget(addb)
        delb = QPushButton("删除")
        delb.setObjectName("Ghost")
        delb.clicked.connect(self._delete_profile)
        top.addWidget(delb)
        cl.addLayout(top)

        self.api_name = QLineEdit()
        self.api_name.setPlaceholderText("方案名称，例如：我的模力方舟")
        cl.addWidget(self._row("方案名称", self.api_name))
        self.base_url = QLineEdit()
        self.base_url.setPlaceholderText("https://api.moark.com/v1")
        cl.addWidget(self._row("API 地址", self.base_url, "默认 https://api.moark.com/v1，一般不用改。"))

        key_row = QWidget()
        kh = QHBoxLayout(key_row)
        kh.setContentsMargins(0, 0, 0, 0)
        kh.setSpacing(6)
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key.setPlaceholderText("在模力方舟工作台 → 访问令牌 创建，通常 32 位")
        kh.addWidget(self.api_key, 1)
        self.eye = IconButton("eye", "显示 / 隐藏", 32)
        self.eye.clicked.connect(self._toggle_key)
        kh.addWidget(self.eye)
        cl.addWidget(self._row("API Key", key_row, "只保存在本机，并用 Windows 凭据加密（DPAPI）。"))

        import_row = QHBoxLayout()
        import_row.addStretch(1)
        imp = QPushButton("从工作资料.txt 读取 Key")
        imp.setObjectName("Ghost")
        imp.clicked.connect(self._import_key)
        import_row.addWidget(imp)
        cl.addLayout(import_row)
        lay.addWidget(card)

        self._section(lay, "模型")
        card2, cl2 = self._card()
        self.chat_model = QLineEdit()
        self.image_model = QLineEdit()
        self.video_model = QLineEdit()
        self.tts_model = QLineEdit()
        cl2.addWidget(self._row("对话模型", self.chat_model))
        cl2.addWidget(self._row("生图模型", self.image_model, "支持文生图与图生图（参考图最多 3 张），云端输出 2048×2048。"))
        cl2.addWidget(self._row("视频模型", self.video_model, "Duix-Avatar：需要一段参考人物视频 + 文案或配音。"))
        cl2.addWidget(self._row("配音模型", self.tts_model, "把口播文案合成为声音，再交给 Duix 对口型。"))
        self.speaker = QComboBox()
        self.speaker.addItems(["Vivian", "Serena", "Dylan", "Eric", "Ryan", "Kiki"])
        self.speaker.setEditable(True)
        cl2.addWidget(self._row("默认音色", self.speaker, "Vivian 是温柔清亮的少女音，和桌宠比较搭。"))
        self.tts_instruction = QLineEdit()
        cl2.addWidget(self._row("音色提示", self.tts_instruction))
        lay.addWidget(card2)

        self._section(lay, "连接")
        card3, cl3 = self._card()
        row = QHBoxLayout()
        self.test_btn = QPushButton("测试连接")
        self.test_btn.setObjectName("Teal")
        self.test_btn.clicked.connect(self._test)
        row.addWidget(self.test_btn)
        self.test_label = QLabel("会读取模型列表，确认四个模型是否都在线。")
        self.test_label.setObjectName("Hint")
        self.test_label.setWordWrap(True)
        row.addWidget(self.test_label, 1)
        cl3.addLayout(row)
        trow = QHBoxLayout()
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(30, 600)
        self.timeout_spin.setSuffix(" 秒")
        self.video_timeout = QSpinBox()
        self.video_timeout.setRange(120, 3600)
        self.video_timeout.setSuffix(" 秒")
        trow.addWidget(QLabel("普通请求"))
        trow.addWidget(self.timeout_spin)
        trow.addSpacing(14)
        trow.addWidget(QLabel("视频任务"))
        trow.addWidget(self.video_timeout)
        trow.addStretch(1)
        cl3.addLayout(trow)
        lay.addWidget(card3)

        self._section(lay, "执行引擎（MothX）")
        card4, cl4 = self._card()
        runtime_row = QWidget()
        rh = QHBoxLayout(runtime_row)
        rh.setContentsMargins(0, 0, 0, 0)
        rh.setSpacing(6)
        self.runtime_path = QLineEdit()
        self.runtime_path.setPlaceholderText("runtime/mothx.exe（留空自动查找）")
        rh.addWidget(self.runtime_path, 1)
        rb = QPushButton("选择…")
        rb.setObjectName("Ghost")
        rb.clicked.connect(self._browse_runtime)
        rh.addWidget(rb)
        cl4.addWidget(self._row("MothX 路径", runtime_row, "下载 Windows 版 MothX 后，把 mothx.exe 放到程序目录的 runtime 文件夹。"))
        ws_row = QWidget()
        wh = QHBoxLayout(ws_row)
        wh.setContentsMargins(0, 0, 0, 0)
        wh.setSpacing(6)
        self.workspace_edit = QLineEdit()
        self.workspace_edit.setPlaceholderText("默认：用户目录\\桌面工作区")
        wh.addWidget(self.workspace_edit, 1)
        wb = QPushButton("选择…")
        wb.setObjectName("Ghost")
        wb.clicked.connect(self._browse_workspace)
        wh.addWidget(wb)
        cl4.addWidget(self._row("默认工作区", ws_row, "执行任务时只在这个文件夹里读写；每次写文件/运行命令仍会先询问。"))
        rel = QPushButton("打开 MothX Releases 下载页")
        rel.setObjectName("Ghost")
        rel.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://github.com/oschina/mothx/releases")))
        cl4.addWidget(rel)
        lay.addWidget(card4)
        lay.addStretch(1)
        return page

    def _page_appearance(self):
        page, lay = self._scroll_page()
        self._page_header(lay, "桌宠外观", "华华和熙熙，两种性格轮换陪你。大小和透明度随时可调。")

        self._section(lay, "角色")
        char_card, char_lay = self._card()
        row = QHBoxLayout()
        row.setSpacing(10)
        self.character = "huahua"
        self.char_cards: dict[str, CharacterCard] = {}
        for key in theme.CHARACTER_ORDER:
            c = CharacterCard(key)
            c.clicked.connect(self._select_character)
            self.char_cards[key] = c
            row.addWidget(c, 1)
        char_lay.addLayout(row)
        self.char_desc = QLabel("")
        self.char_desc.setObjectName("Hint")
        self.char_desc.setWordWrap(True)
        char_lay.addWidget(self.char_desc)
        lay.addWidget(char_card)

        card, cl = self._card()
        top = QHBoxLayout()
        self.preview = PetPreview(character=self.character)
        top.addWidget(self.preview, 0, Qt.AlignmentFlag.AlignTop)
        right = QVBoxLayout()
        right.setSpacing(9)
        self.size_slider = QSlider(Qt.Orientation.Horizontal)
        self.size_slider.setRange(160, 340)
        self.size_slider.setSingleStep(10)
        self.size_slider.valueChanged.connect(self._update_size_label)
        self.size_label = QLabel("260 px")
        self.size_label.setObjectName("Badge")
        sr = QHBoxLayout()
        sr.addWidget(QLabel("桌宠大小"))
        sr.addWidget(self.size_slider, 1)
        sr.addWidget(self.size_label)
        right.addLayout(sr)
        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setRange(55, 100)
        self.opacity_label = QLabel("100%")
        self.opacity_label.setObjectName("Badge")
        orow = QHBoxLayout()
        orow.addWidget(QLabel("不透明度"))
        orow.addWidget(self.opacity_slider, 1)
        orow.addWidget(self.opacity_label)
        right.addLayout(orow)
        self.opacity_slider.valueChanged.connect(lambda v: self.opacity_label.setText(f"{v}%"))
        right.addStretch(1)
        top.addLayout(right, 1)
        cl.addLayout(top)
        lay.addWidget(card)

        self._section(lay, "行为")
        card2, cl2 = self._card()
        self.always_top = self._check("始终置顶", "不被其他窗口盖住")
        self.animations = self._check("待机小动作", "呼吸、眨眼、随机小表情")
        self.walk = self._check("偶尔在桌面上散步", "每 1–2 分钟小走一段")
        self.bubble_on = self._check("用气泡跟我说话", "生成完成时弹出提醒气泡")
        for w in (self.always_top, self.animations, self.walk, self.bubble_on):
            cl2.addWidget(w)
        lay.addWidget(card2)
        lay.addStretch(1)
        return page

    def _page_storage(self):
        page, lay = self._scroll_page()
        self._page_header(lay, "存储位置", "生成的图片、视频、配音都会自动归档到本地，不上传到别处。")
        card, cl = self._card()
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        self.output_dir = QLineEdit()
        self.output_dir.setReadOnly(True)
        h.addWidget(self.output_dir, 1)
        browse = QPushButton("选择…")
        browse.setObjectName("Ghost")
        browse.clicked.connect(self._browse_output)
        h.addWidget(browse)
        openb = QPushButton("打开")
        openb.setObjectName("Ghost")
        openb.clicked.connect(self._open_output)
        h.addWidget(openb)
        cl.addWidget(self._row("作品文件夹", row, "会按 图片 / 视频 / 音频 / 缓存 自动分类。"))
        self.storage_usage = QLabel("")
        self.storage_usage.setObjectName("Hint")
        cl.addWidget(self.storage_usage)
        lay.addWidget(card)

        self._section(lay, "保存习惯")
        card2, cl2 = self._card()
        self.auto_open = self._check("生成后自动打开文件", "图片用看图器，视频用系统播放器")
        self.save_history = self._check("保存对话历史", "只保存在本机，可随时清空")
        cl2.addWidget(self.auto_open)
        cl2.addWidget(self.save_history)
        hrow = QHBoxLayout()
        hrow.addWidget(QLabel("最多保留对话"))
        self.max_history = QSpinBox()
        self.max_history.setRange(5, 200)
        self.max_history.setSuffix(" 个")
        hrow.addWidget(self.max_history)
        hrow.addStretch(1)
        cl2.addLayout(hrow)
        lay.addWidget(card2)

        self._section(lay, "清理")
        card3, cl3 = self._card()
        clear = QPushButton("清空全部对话历史")
        clear.setObjectName("Ghost")
        clear.setStyleSheet(f"QPushButton{{color:{DANGER};}}")
        clear.clicked.connect(self._clear_history)
        cl3.addWidget(clear)
        note = QLabel("不会删除已经生成的图片和视频。")
        note.setObjectName("Tiny")
        cl3.addWidget(note)
        lay.addWidget(card3)
        lay.addStretch(1)
        return page

    def _page_behavior(self):
        page, lay = self._scroll_page()
        self._page_header(lay, "互动习惯", "一些让陪伴更舒服的小开关。")
        card, cl = self._card()
        self.notify = self._check("系统通知", "生成完成时同时发一条 Windows 通知")
        self.sound = self._check("完成提示音", "一声很轻的双音铃声")
        self.autostart = self._check("开机自动启动小工具", "在启动文件夹里放一个静默启动项")
        self.deep_think = self._check("默认深度思考", "回答更认真，但会慢一些、消耗更多 Token")
        self.enter_send = self._check("按 Enter 发送", "关掉后 Enter 换行，Ctrl+Enter 发送")
        for w in (self.notify, self.sound, self.autostart, self.deep_think, self.enter_send):
            cl.addWidget(w)
        lay.addWidget(card)

        self._section(lay, "节奏")
        card2, cl2 = self._card()
        srow = QHBoxLayout()
        srow.addWidget(QLabel("多久没互动就困了"))
        self.sleep_minutes = QSpinBox()
        self.sleep_minutes.setRange(0, 60)
        self.sleep_minutes.setSuffix(" 分钟")
        srow.addWidget(self.sleep_minutes)
        srow.addStretch(1)
        cl2.addLayout(srow)
        frow = QHBoxLayout()
        frow.addWidget(QLabel("专注陪伴时长"))
        self.focus_minutes = QSpinBox()
        self.focus_minutes.setRange(5, 120)
        self.focus_minutes.setSingleStep(5)
        self.focus_minutes.setSuffix(" 分钟")
        frow.addWidget(self.focus_minutes)
        frow.addStretch(1)
        cl2.addLayout(frow)
        hint = QLabel("右键桌宠 → 陪我专注，倒计时结束时会提醒你休息。")
        hint.setObjectName("Tiny")
        hint.setWordWrap(True)
        cl2.addWidget(hint)
        lay.addWidget(card2)

        self._section(lay, "快捷键")
        card3, cl3 = self._card()
        for text in (
            "单击 头部 / 肚子 —— 摸摸她，有不同反应",
            "双击 —— 打开对话",
            "右键 —— 快捷菜单",
            "拖文件到桌宠 —— 自动识别并总结",
            "拖文件到对话框 —— 一起发给我",
        ):
            l = QLabel("· " + text)
            l.setStyleSheet(f"color:{INK_SOFT};font-size:11px;")
            cl3.addWidget(l)
        lay.addWidget(card3)
        lay.addStretch(1)
        return page

    def _page_about(self):
        page, lay = self._scroll_page()
        self._page_header(lay, "关于华华和熙熙", "两个住在桌面上的小伙伴，把灵感变成图与影。")
        card, cl = self._card()
        top = QHBoxLayout()
        av = QLabel()
        av.setPixmap(theme.avatar_pixmap(64, "huahua"))
        top.addWidget(av)
        av2 = QLabel()
        av2.setPixmap(theme.avatar_pixmap(64, "xixi"))
        top.addWidget(av2)
        col = QVBoxLayout()
        name = QLabel("华华和熙熙 · 桌面灵感搭子")
        name.setFont(font(15, QFont.Weight.Bold))
        v = QLabel(f"版本 {__version__}  ·  为 Windows 桌面做的 AI 小工具")
        v.setObjectName("Hint")
        brief = QLabel("华华温柔、熙熙元气。聊天、生图、图生图、数字人视频、文件识别、截图提问，还有会眨眼会散步的小桌宠。")
        brief.setWordWrap(True)
        brief.setStyleSheet(f"color:{INK_SOFT};font-size:11px;")
        col.addWidget(name)
        col.addWidget(v)
        col.addWidget(brief)
        top.addLayout(col, 1)
        cl.addLayout(top)
        lay.addWidget(card)

        self._section(lay, "四个模型")
        card2, cl2 = self._card()
        for model, label, desc in (
            ("DeepSeek-V4.1-Flash-1017", "对话 / 图片理解", "DeepSeek 最新 Flash 模型，支持图文输入"),
            ("qwen-image-2.0-pro", "文生图 / 图生图", "千问图像 2.0 Pro，文字渲染与真实质感"),
            ("Duix-Avatar", "数字人视频", "音频 + 参考视频生成口型同步视频"),
            ("Qwen3-TTS", "配音", "把口播文案合成为自然语音"),
        ):
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 2, 0, 2)
            tag = QLabel(label)
            tag.setObjectName("Badge")
            tag.setFixedWidth(112)
            tag.setAlignment(Qt.AlignmentFlag.AlignCenter)
            h.addWidget(tag)
            mid = QVBoxLayout()
            n = QLabel(model)
            n.setFont(font(9, QFont.Weight.DemiBold))
            d = QLabel(desc)
            d.setObjectName("Tiny")
            mid.addWidget(n)
            mid.addWidget(d)
            h.addLayout(mid, 1)
            cl2.addWidget(row)
        lay.addWidget(card2)

        self._section(lay, "隐私与数据")
        card3, cl3 = self._card()
        for text in (
            "API Key 使用 Windows DPAPI 加密，只保存在本机。",
            "对话历史、生成的图片和视频都存放在你的电脑上。",
            "只有你主动发送的文字、图片和文件会传给模力方舟。",
            "本工具是本地客户端，不是在线服务。",
        ):
            l = QLabel("· " + text)
            l.setWordWrap(True)
            l.setStyleSheet(f"color:{INK_SOFT};font-size:11px;")
            cl3.addWidget(l)
        lay.addWidget(card3)

        self._section(lay, "链接")
        card4, cl4 = self._card()
        for text, url in (
            ("模力方舟 · 模型广场与令牌", "https://moark.com/serverless-api"),
            ("模力方舟 · API 文档", "https://moark.com/docs/openapi/v1"),
            ("Duix-Avatar · 开源项目", "https://github.com/duixcom/Duix-Avatar"),
        ):
            b = QPushButton(text)
            b.setObjectName("Ghost")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, u=url: QDesktopServices.openUrl(QUrl(u)))
            b.setStyleSheet(f"QPushButton{{text-align:left;color:{TEAL_DEEP};}}")
            cl4.addWidget(b)
        lay.addWidget(card4)
        lay.addStretch(1)
        return page

    def _show_page(self, index: int):
        index = max(0, min(index, self.stack.count() - 1))
        self.stack.setCurrentIndex(index)
        for i, b in enumerate(self.nav_group):
            b.setChecked(i == index)

    # ------------------------------------------------------------------
    def _load_all(self):
        self._reload_profiles()
        a = self.draft["appearance"]
        self._select_character(a.get("character", "huahua"))
        self.size_slider.setValue(int(a.get("size", 260)))
        self.opacity_slider.setValue(int(a.get("opacity", 100)))
        self.always_top.setChecked(bool(a.get("always_on_top", True)))
        self.animations.setChecked(bool(a.get("animations", True)))
        self.walk.setChecked(bool(a.get("walk", False)))
        self.bubble_on.setChecked(bool(a.get("bubble", True)))
        self._update_size_label(self.size_slider.value())

        s = self.draft["storage"]
        self.output_dir.setText(s.get("output_dir", str(default_output_dir())))
        self.auto_open.setChecked(bool(s.get("auto_open", False)))
        self.save_history.setChecked(bool(s.get("save_history", True)))
        self.max_history.setValue(int(s.get("max_history", 30)))
        self._update_usage()

        m = self.draft.get("mothx", {})
        self.runtime_path.setText(str(m.get("runtime_path", "") or ""))
        self.workspace_edit.setText(str(m.get("workspace", "") or ""))

        b = self.draft["behavior"]
        self.notify.setChecked(bool(b.get("notify", True)))
        self.sound.setChecked(bool(b.get("sound", True)))
        self.autostart.setChecked(bool(b.get("autostart", False)))
        self.deep_think.setChecked(bool(b.get("deep_think", False)))
        self.enter_send.setChecked(bool(b.get("enter_to_send", True)))
        self.sleep_minutes.setValue(int(b.get("sleep_minutes", 8)))
        self.focus_minutes.setValue(int(b.get("focus_minutes", 25)))

    def _reload_profiles(self):
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        for p in self.draft.get("profiles", []):
            self.profile_combo.addItem(p.get("name") or "未命名", p.get("id"))
        active = self.draft.get("active_profile")
        idx = max(0, next((i for i in range(self.profile_combo.count()) if self.profile_combo.itemData(i) == active), 0))
        self.profile_combo.setCurrentIndex(idx)
        self.profile_combo.blockSignals(False)
        self._load_profile(self.profile_combo.currentData())

    def _profile(self, pid: str | None) -> dict[str, Any] | None:
        return next((p for p in self.draft.get("profiles", []) if p.get("id") == pid), None)

    def _load_profile(self, pid: str | None):
        p = self._profile(pid)
        if not p:
            return
        self._current_profile_id = p["id"]
        for field, key in (
            (self.api_name, "name"),
            (self.base_url, "base_url"),
            (self.chat_model, "chat_model"),
            (self.image_model, "image_model"),
            (self.video_model, "video_model"),
            (self.tts_model, "tts_model"),
            (self.tts_instruction, "tts_instruction"),
        ):
            field.setText(str(p.get(key, "")))
        self.api_key.setText(secrets.unprotect(p.get("api_key_enc", "")))
        sp = p.get("tts_speaker", "Vivian")
        idx = self.speaker.findText(sp)
        if idx < 0:
            self.speaker.addItem(sp)
            idx = self.speaker.findText(sp)
        self.speaker.setCurrentIndex(idx)
        self.timeout_spin.setValue(int(p.get("timeout", 180)))
        self.video_timeout.setValue(int(p.get("video_timeout", 1800)))
        self.test_label.setText("会读取模型列表，确认四个模型是否都在线。")
        self.test_label.setStyleSheet(f"color:{MUTED};font-size:11px;")

    def _save_profile_fields(self):
        p = self._profile(self._current_profile_id)
        if not p:
            return
        p["name"] = self.api_name.text().strip() or "我的模力方舟"
        p["base_url"] = self.base_url.text().strip() or "https://api.moark.com/v1"
        p["chat_model"] = self.chat_model.text().strip() or "DeepSeek-V4.1-Flash-1017"
        p["image_model"] = self.image_model.text().strip() or "qwen-image-2.0-pro"
        p["video_model"] = self.video_model.text().strip() or "Duix-Avatar"
        p["tts_model"] = self.tts_model.text().strip() or "Qwen3-TTS"
        p["tts_speaker"] = self.speaker.currentText().strip() or "Vivian"
        p["tts_instruction"] = self.tts_instruction.text().strip()
        p["timeout"] = self.timeout_spin.value()
        p["video_timeout"] = self.video_timeout.value()
        key = self.api_key.text().strip()
        if key:
            p["api_key_enc"] = secrets.protect(key)
        else:
            p["api_key_enc"] = ""
        # keep combo title in sync
        idx = self.profile_combo.currentIndex()
        if idx >= 0:
            self.profile_combo.setItemText(idx, p["name"])

    def _profile_changed(self, idx: int):
        self._save_profile_fields()
        pid = self.profile_combo.itemData(idx)
        self._load_profile(pid)

    def _add_profile(self):
        name, ok = QInputDialog.getText(self, "添加 API 方案", "给这个方案起个名字：", text="我的模力方舟")
        if not ok:
            return
        self._save_profile_fields()
        p = new_profile(name=name.strip() or "我的模力方舟")
        self.draft.setdefault("profiles", []).append(p)
        self.draft["active_profile"] = p["id"]
        self._reload_profiles()
        self.show_toast("已添加，可以填新的 Key 了")

    def _delete_profile(self):
        if len(self.draft.get("profiles", [])) <= 1:
            self.show_toast("至少保留一个接口方案")
            return
        p = self._profile(self._current_profile_id)
        if not p:
            return
        if QMessageBox.question(self, "删除方案", f"删除「{p.get('name')}」？本地保存的 Key 也会一起删掉。") != QMessageBox.StandardButton.Yes:
            return
        self.draft["profiles"] = [x for x in self.draft["profiles"] if x.get("id") != p["id"]]
        self.draft["active_profile"] = self.draft["profiles"][0]["id"]
        self._reload_profiles()

    def _toggle_key(self):
        if self.api_key.echoMode() == QLineEdit.EchoMode.Password:
            self.api_key.setEchoMode(QLineEdit.EchoMode.Normal)
            self.eye.setText(theme.icon_glyph("hide"))
        else:
            self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
            self.eye.setText(theme.icon_glyph("eye"))

    def _import_key(self):
        key = secrets.find_work_key()
        if key:
            self.api_key.setText(key)
            self.show_toast("已读取工作资料里的模力方舟 Key")
        else:
            self.show_toast("没找到可用的 Key，请手动粘贴")

    def _test(self):
        self._save_profile_fields()
        p = self._profile(self._current_profile_id)
        key = self.api_key.text().strip()
        if not key:
            self.test_label.setText("先填 API Key 再测试。")
            self.test_label.setStyleSheet(f"color:{DANGER};font-size:11px;")
            return
        self.test_btn.setEnabled(False)
        self.test_label.setText("正在连接模力方舟…")
        self.test_label.setStyleSheet(f"color:{MUTED};font-size:11px;")
        w = TestWorker(copy.deepcopy(p), key)
        self._test_worker = w
        w.completed.connect(self._test_ok)
        w.failed.connect(self._test_fail)
        w.finished.connect(lambda: self.test_btn.setEnabled(True))
        w.start()

    def _test_ok(self, msg: str):
        self.test_label.setText(msg)
        self.test_label.setStyleSheet(f"color:{TEAL_DEEP};font-size:11px;")

    def _test_fail(self, msg: str):
        self.test_label.setText(msg)
        self.test_label.setStyleSheet(f"color:{DANGER};font-size:11px;")

    def _select_character(self, key: str):
        self.character = theme.character_key(key)
        self.draft.setdefault("appearance", {})["character"] = self.character
        for k, card in self.char_cards.items():
            card.set_selected(k == self.character)
        if hasattr(self, "char_desc"):
            meta = theme.CHARACTERS[self.character]
            self.char_desc.setText(f"{meta['name']}：{meta['description']}")
        if hasattr(self, "logo"):
            self.logo.setPixmap(theme.avatar_pixmap(38, self.character))
        if hasattr(self, "preview"):
            self.preview.set_state(self.size_slider.value(), "greet" if self.character == "xixi" else "idle", self.character)

    def _update_size_label(self, v: int):
        self.size_label.setText(f"{v} px")
        if hasattr(self, "preview"):
            self.preview.set_state(v, "greet" if self.character == "xixi" else "idle", self.character)

    def _browse_runtime(self):
        f, _ = QFileDialog.getOpenFileName(self, "选择 mothx.exe", self.runtime_path.text() or str(Path.home()), "MothX (mothx.exe);;所有文件 (*.*)")
        if f:
            self.runtime_path.setText(f)

    def _browse_workspace(self):
        d = QFileDialog.getExistingDirectory(self, "选择华华的默认工作区", self.workspace_edit.text() or str(Path.home()))
        if d:
            self.workspace_edit.setText(d)

    def _browse_output(self):
        d = QFileDialog.getExistingDirectory(self, "选择作品文件夹", self.output_dir.text() or str(Path.home()))
        if d:
            self.output_dir.setText(d)
            self._update_usage()

    def _open_output(self):
        p = Path(self.output_dir.text())
        p.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))

    def _update_usage(self):
        p = Path(self.output_dir.text())
        total = 0
        count = 0
        try:
            if p.exists():
                for f in p.rglob("*"):
                    if f.is_file():
                        total += f.stat().st_size
                        count += 1
        except Exception:
            pass
        self.storage_usage.setText(f"已经存放 {count} 个文件，共 {format_size(total)}")

    def _clear_history(self):
        if QMessageBox.question(self, "清空历史", "清空全部对话历史？作品文件不会被删除。") == QMessageBox.StandardButton.Yes:
            self.clear_history_requested.emit()
            self.show_toast("对话历史已清空")

    def _reset_pet_pos(self):
        self.draft["appearance"]["position"] = None
        self.show_toast("保存后会回到屏幕右下角")

    # ------------------------------------------------------------------
    def _save(self):
        self._save_profile_fields()
        if not self.draft.get("profiles"):
            self.show_toast("至少需要一个接口方案")
            return
        self.draft["active_profile"] = self._current_profile_id
        a = self.draft["appearance"]
        a["character"] = self.character
        a["size"] = self.size_slider.value()
        a["opacity"] = self.opacity_slider.value()
        a["always_on_top"] = self.always_top.isChecked()
        a["animations"] = self.animations.isChecked()
        a["walk"] = self.walk.isChecked()
        a["bubble"] = self.bubble_on.isChecked()

        m = self.draft.setdefault("mothx", {})
        m["runtime_path"] = self.runtime_path.text().strip()
        raw_ws = self.workspace_edit.text().strip()
        if raw_ws:
            p = Path(raw_ws).expanduser()
            if not p.is_absolute():
                p = Path.cwd() / p
            raw_ws = str(p.resolve())
        m["workspace"] = raw_ws

        s = self.draft["storage"]
        s["output_dir"] = self.output_dir.text().strip() or str(default_output_dir())
        s["auto_open"] = self.auto_open.isChecked()
        s["save_history"] = self.save_history.isChecked()
        s["max_history"] = self.max_history.value()

        b = self.draft["behavior"]
        b["notify"] = self.notify.isChecked()
        b["sound"] = self.sound.isChecked()
        b["autostart"] = self.autostart.isChecked()
        b["deep_think"] = self.deep_think.isChecked()
        b["enter_to_send"] = self.enter_send.isChecked()
        b["sleep_minutes"] = self.sleep_minutes.value()
        b["focus_minutes"] = self.focus_minutes.value()

        old_auto = bool(self.config.get("behavior.autostart", False))
        self.config.data = self.draft
        self.config.ensure_dirs()
        self.config.save()
        if old_auto != b["autostart"]:
            ok, err = set_autostart(b["autostart"])
            if not ok:
                QMessageBox.warning(self, "开机启动设置失败", err)
        self._saved = True
        self.saved.emit()
        self.accept()

    def show_toast(self, text: str, ms: int = 2600):
        self.toast.show_text(text, ms)

    def done(self, r):
        if not self._saved:
            self.draft = self.config.snapshot()
        super().done(r)

    # ------------------------------------------------------------------
    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.MouseButtonPress and hasattr(event, "globalPosition"):
            if event.button() == Qt.MouseButton.LeftButton:
                self._drag = event.globalPosition().toPoint()
                self._drag_origin = self.pos()
        elif event.type() == QEvent.Type.MouseMove and self._drag is not None:
            self.move(self._drag_origin + (event.globalPosition().toPoint() - self._drag))
        elif event.type() == QEvent.Type.MouseButtonRelease and self._drag is not None:
            self._drag = None
        return super().eventFilter(obj, event)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if hasattr(self, "toast") and self.toast.isVisible():
            self.toast.move((self.width() - self.toast.width()) // 2, self.height() - self.toast.height() - 26)


def theme_icon(name: str, color: str, size: int = 16) -> QIcon:
    from .widgets import glyph_icon

    return glyph_icon(name, color, size)


def format_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"
