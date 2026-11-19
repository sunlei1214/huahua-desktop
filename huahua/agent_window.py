"""Agent task window: MothX ACP as the execution backend."""
from __future__ import annotations

import html
import json
import time
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QEvent, QPoint, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QIcon, QKeyEvent, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from . import theme
from .config import Config
from .mothx import AgentController, MODEL_CHOICES, MothXRuntime, find_runtime
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
)
from .widgets import (
    AttachmentChip,
    Avatar,
    Chip,
    FlowLayout,
    IconButton,
    NoWheelTextBrowser,
    SegmentedControl,
    ToastLabel,
    md_to_html,
)

DEFAULT_WORKSPACE_NAME = "桌面工作区"


def workspace_path(raw: str | None = None) -> Path:
    """The one canonical path used by both the header and MothX session/new."""
    p = Path(raw).expanduser() if raw else Path.home() / DEFAULT_WORKSPACE_NAME
    if not p.is_absolute():
        p = Path.cwd() / p
    return p.resolve()


# ----------------------------------------------------------------------
class ToolRow(QFrame):
    def __init__(self, info: dict[str, Any], parent=None):
        super().__init__(parent)
        self.info = info
        self.setObjectName("ToolRow")
        self.setStyleSheet(
            f"QFrame#ToolRow{{background:white;border:1px solid {LINE};border-radius:11px;}}"
        )
        lay = QHBoxLayout(self)
        lay.setContentsMargins(9, 6, 9, 6)
        lay.setSpacing(7)
        self.dot = QLabel("●")
        self.dot.setStyleSheet("color:#C7B8B0;font-size:9px;")
        lay.addWidget(self.dot)
        self.title = QLabel()
        self.title.setFont(font(10, QFont.Weight.DemiBold))
        self.title.setStyleSheet(f"color:{INK_SOFT};")
        lay.addWidget(self.title, 1)
        self.meta = QLabel()
        self.meta.setObjectName("Tiny")
        lay.addWidget(self.meta)
        self.update_info(info)

    def update_info(self, info: dict[str, Any]):
        self.info = info
        title = info.get("title") or "工具"
        kind = info.get("kind") or ""
        raw = info.get("raw_input") or {}
        kind_label = {
            "execute": "运行命令", "bash": "运行命令", "read": "读取文件",
            "edit": "修改文件", "write": "写入文件", "delete": "删除文件",
            "search": "搜索", "fetch": "抓取", "web": "联网",
        }.get(kind, kind)
        if title.lower() in ("bash", "shell", "execute"):
            title = kind_label or "运行命令"
        elif kind_label and kind_label not in title and not title.startswith(kind_label[:2]):
            title = f"{title} · {kind_label}"
        self.title.setText(title)
        status = info.get("status") or "pending"
        color = {
            "completed": "#4FAE86",
            "failed": "#D96A5D",
            "in_progress": PEACH_DEEP,
            "pending": "#B9A9A2",
        }.get(status, "#B9A9A2")
        self.dot.setStyleSheet(f"color:{color};font-size:9px;")
        self.meta.setText(
            {"completed": "完成", "failed": "失败", "in_progress": "进行中", "pending": "等待"}
            .get(status, status)
        )
        detail = ""
        if isinstance(raw, dict):
            for key in ("command", "path", "file_path", "pattern", "query", "url"):
                if raw.get(key):
                    detail = f"{key}: {raw[key]}"
                    break
        self.setToolTip(detail or json.dumps(raw, ensure_ascii=False)[:800])


class PlanCard(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("TintCard")
        self.setMaximumWidth(500)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 9, 12, 9)
        lay.setSpacing(4)
        title = QLabel("计划")
        title.setFont(font(10, QFont.Weight.Bold))
        title.setStyleSheet(f"color:{PEACH_DEEP};")
        lay.addWidget(title)
        self.body = QLabel("")
        self.body.setWordWrap(True)
        self.body.setStyleSheet(f"color:{INK_SOFT};font-size:11px;line-height:1.5;")
        lay.addWidget(self.body)

    def set_entries(self, entries: list[dict[str, Any]]):
        lines = []
        for e in entries:
            status = e.get("status") or "pending"
            mark = {"completed": "✓", "in_progress": "●", "failed": "×"}.get(status, "○")
            color = {"completed": "#4FAE86", "in_progress": PEACH_DEEP, "failed": DANGER}.get(status, MUTED)
            lines.append(
                f"<span style='color:{color};font-weight:600'>{mark}</span> "
                f"{html.escape(str(e.get('content') or ''))}"
            )
        self.body.setText("<br>".join(lines))


class ApprovalCard(QFrame):
    decided = Signal(str)

    def __init__(self, data: dict[str, Any], parent=None):
        super().__init__(parent)
        self.data = data
        self.setObjectName("ApprovalCard")
        self.setStyleSheet(
            f"QFrame#ApprovalCard{{background:#FFF8F3;border:1px solid #F0C7B6;border-radius:14px;}}"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)
        title = QLabel("需要你确认")
        title.setFont(font(10, QFont.Weight.Bold))
        title.setStyleSheet(f"color:{DANGER};")
        lay.addWidget(title)
        kind = str(data.get("kind") or "")
        kind_label = {
            "execute": "运行命令",
            "edit": "修改文件",
            "write": "写入文件",
            "read": "读取文件",
            "delete": "删除文件",
            "bash": "运行命令",
        }.get(kind, str(data.get("title") or "工具操作"))
        what = QLabel(kind_label)
        what.setWordWrap(True)
        what.setFont(font(11, QFont.Weight.DemiBold))
        lay.addWidget(what)
        raw = data.get("raw_input") or {}
        detail = ""
        if isinstance(raw, dict):
            for key in ("command", "path", "file_path", "url"):
                if raw.get(key):
                    detail = str(raw[key])
                    break
            if not detail and raw:
                detail = json.dumps(raw, ensure_ascii=False)
        if detail:
            code = QLabel(detail[:500])
            code.setWordWrap(True)
            code.setStyleSheet(
                "background:#F7EDE7;border-radius:7px;padding:6px;color:#6F5A54;"
                "font-family:Consolas;font-size:10px;"
            )
            lay.addWidget(code)
        row = QHBoxLayout()
        row.setSpacing(6)
        row.addStretch(1)
        self.buttons: list[QPushButton] = []
        for opt in data.get("options") or []:
            b = QPushButton(str(opt.get("name") or "允许"))
            b.setObjectName("Primary" if "allow" in str(opt.get("kind") or "").lower() else "Ghost")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, oid=opt.get("id"): self._choose(str(oid)))
            row.addWidget(b)
            self.buttons.append(b)
        lay.addLayout(row)

    def _choose(self, option_id: str):
        for b in self.buttons:
            b.setEnabled(False)
        self.decided.emit(option_id)
        self.setStyleSheet(
            f"QFrame#ApprovalCard{{background:#F1F8F3;border:1px solid #CBE7D4;border-radius:14px;}}"
        )
        label = QLabel("已处理")
        label.setStyleSheet("color:#4FAE86;font-size:10px;font-weight:600;")
        self.layout().addWidget(label)


class AgentRunView(QFrame):
    def __init__(self, character: str, name: str, parent=None):
        super().__init__(parent)
        self.character = theme.character_key(character)
        self._raw = ""
        self._streaming = True
        self._tools: dict[str, ToolRow] = {}
        self._plan: PlanCard | None = None
        self._approval: ApprovalCard | None = None
        self.setObjectName("Transparent")
        self.setMaximumWidth(500)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)
        head = QHBoxLayout()
        head.setSpacing(7)
        self.avatar = Avatar(28, True, self.character)
        head.addWidget(self.avatar)
        self.name_label = QLabel(name)
        self.name_label.setFont(font(10, QFont.Weight.DemiBold))
        self.name_label.setStyleSheet(f"color:{INK_SOFT};")
        head.addWidget(self.name_label)
        self.status = QLabel("准备中")
        self.status.setObjectName("Tiny")
        head.addWidget(self.status)
        head.addStretch(1)
        root.addLayout(head)
        self.textb = NoWheelTextBrowser()
        self.textb.setFrameShape(QFrame.Shape.NoFrame)
        self.textb.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.textb.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.textb.setStyleSheet("QTextBrowser{background:transparent;border:none;padding:0;}")
        self.textb.setFont(font(10))
        self.textb.document().setDocumentMargin(0)
        self.textb.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.LinksAccessibleByMouse
        )
        self.textb.setOpenExternalLinks(True)
        self.textb.setFixedWidth(466)
        self.textb.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        root.addWidget(self.textb)
        self.extra_host = QWidget()
        self.extra = QVBoxLayout(self.extra_host)
        self.extra.setContentsMargins(0, 0, 0, 0)
        self.extra.setSpacing(6)
        self.extra_host.hide()
        root.addWidget(self.extra_host)
        self.set_status("准备中")

    def set_status(self, text: str, color: str = MUTED):
        self.status.setText(text)
        self.status.setStyleSheet(f"color:{color};font-size:10px;")

    def append_text(self, text: str):
        self._raw += text
        self.textb.show()
        self.textb.setPlainText(self._raw)
        self._resize()

    def finalize(self, text: str | None = None):
        self._streaming = False
        if text is not None:
            self._raw = text
        if self._raw:
            self.textb.setHtml(md_to_html(self._raw))
            self._resize()
            self.set_status("完成", "#4FAE86")

    def _resize(self):
        doc = self.textb.document()
        doc.setTextWidth(466)
        h = max(20, int(doc.size().height() + 4))
        self.textb.setFixedHeight(min(h, 1600))

    def add_tool(self, info: dict[str, Any]):
        tid = info.get("id") or ""
        if tid and tid in self._tools:
            self._tools[tid].update_info(info)
            return
        row = ToolRow(info)
        if tid:
            self._tools[tid] = row
        self.extra.addWidget(row)
        self.extra_host.show()

    def add_plan(self, entries: list[dict[str, Any]]):
        if self._plan is None:
            self._plan = PlanCard()
            self.extra.addWidget(self._plan)
            self.extra_host.show()
        self._plan.set_entries(entries)

    def add_approval(self, data: dict[str, Any], on_decision: Callable[[str], None]) -> ApprovalCard:
        card = ApprovalCard(data)
        card.decided.connect(on_decision)
        self._approval = card
        self.extra.addWidget(card)
        self.extra_host.show()
        self.set_status("等你确认", DANGER)
        return card

    def set_character(self, character: str, name: str):
        self.character = theme.character_key(character)
        self.avatar.set_character(self.character)
        self.name_label.setText(name)

    def finish(self, status: str = "完成", color: str = "#4FAE86"):
        self.set_status(status, color)


# ----------------------------------------------------------------------
class AgentWindow(QWidget):
    pet_state = Signal(str)
    notify_requested = Signal(str, str, str, str)
    settings_requested = Signal()
    chat_requested = Signal()
    hidden = Signal()

    def __init__(self, config: Config):
        super().__init__(None)
        self.config = config
        self.character = config.character
        self.controller = AgentController(config, self)
        self.attachments: list[Path] = []
        self._run: AgentRunView | None = None
        self._busy = False
        self._finalized = False
        self._header_drag: QPoint | None = None
        self._header_origin: QPoint | None = None

        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAcceptDrops(True)
        self.resize(560, 760)
        self.setMinimumSize(480, 620)
        self.setWindowTitle(f"{theme.character_name(self.character)} · 执行")
        self.setWindowIcon(QIcon(str(theme.character_icon_path(self.character))))
        self._build()
        self._connect()
        self.reload_runtime()
        self.apply_character()

    # ------------------------------------------------------------------
    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 18, 18, 18)
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

        header = QFrame()
        header.setFixedHeight(78)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(18, 13, 14, 8)
        hl.setSpacing(10)
        self.avatar = Avatar(46, True, self.character)
        hl.addWidget(self.avatar)
        col = QVBoxLayout()
        col.setSpacing(1)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.name_label = QLabel()
        self.name_label.setFont(font(15, QFont.Weight.Bold))
        row.addWidget(self.name_label)
        badge = QLabel("MOTHX · AGENT")
        badge.setObjectName("Badge")
        row.addWidget(badge)
        row.addStretch(1)
        col.addLayout(row)
        self.status_label = QLabel("● 执行引擎")
        self.status_label.setStyleSheet(f"color:{TEAL_DEEP};font-size:10px;")
        col.addWidget(self.status_label)
        hl.addLayout(col, 1)
        self.view_switch = SegmentedControl(
            [("会话", "chat"), ("任务", "agent")], active="agent", compact=True
        )
        self.view_switch.setFixedWidth(104)
        self.view_switch.changed.connect(self._view_changed)
        hl.addWidget(self.view_switch)
        self.new_btn = IconButton("plus", "新任务", 28)
        self.new_btn.clicked.connect(self.new_task)
        self.settings_btn = IconButton("settings", "设置", 28)
        self.settings_btn.clicked.connect(self.settings_requested.emit)
        self.close_btn = IconButton("close", "收起", 28)
        self.close_btn.clicked.connect(self.hide)
        for b in (self.new_btn, self.settings_btn, self.close_btn):
            hl.addWidget(b)
        root.addWidget(header)
        self._header = header

        # context bar
        ctx_outer = QWidget()
        ol = QVBoxLayout(ctx_outer)
        ol.setContentsMargins(18, 0, 18, 10)
        ol.setSpacing(0)
        self.ctx_card = QFrame()
        self.ctx_card.setObjectName("ContextCard")
        cl = QVBoxLayout(self.ctx_card)
        cl.setContentsMargins(10, 8, 10, 8)
        cl.setSpacing(6)
        ws_row = QHBoxLayout()
        ws_row.setSpacing(6)
        self.workspace_btn = QPushButton("工作区 · 未选择")
        self.workspace_btn.setObjectName("Chip")
        self.workspace_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.workspace_btn.setToolTip("点击更改工作区（只在这个文件夹内读写）")
        self.workspace_btn.clicked.connect(self.choose_workspace)
        ws_row.addWidget(self.workspace_btn, 1)
        self.change_ws_btn = QPushButton("更改")
        self.change_ws_btn.setObjectName("Ghost")
        self.change_ws_btn.setFixedSize(46, 30)
        self.change_ws_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.change_ws_btn.clicked.connect(self.choose_workspace)
        ws_row.addWidget(self.change_ws_btn)
        cl.addLayout(ws_row)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.model_combo = QComboBox()
        self.model_combo.setMinimumWidth(220)
        self.model_combo.setToolTip("MothX 模型")
        self.model_combo.currentIndexChanged.connect(self._model_changed)
        row.addWidget(self.model_combo, 1)
        mode_label = QLabel("模式")
        mode_label.setObjectName("Tiny")
        row.addWidget(mode_label)
        self.mode_switch = SegmentedControl(
            [("执行", "agent"), ("计划", "plan"), ("YOLO", "yolo")], active="agent", compact=True
        )
        self.mode_switch.setFixedWidth(166)
        self.mode_switch.setToolTip("执行：逐次审批；计划：只读；YOLO：完全放开，不推荐")
        self.mode_switch.changed.connect(self._mode_changed)
        self._last_mode = "agent"
        row.addWidget(self.mode_switch)
        cl.addLayout(row)
        ol.addWidget(self.ctx_card)
        root.addWidget(ctx_outer)

        # timeline
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setStyleSheet("QScrollArea{background:transparent;border:none;} QScrollArea > QWidget > QWidget{background:transparent;}")
        self.timeline = QWidget()
        self.tl = QVBoxLayout(self.timeline)
        self.tl.setContentsMargins(18, 4, 18, 10)
        self.tl.setSpacing(10)
        self.tl.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.empty = self._build_empty()
        self.tl.addWidget(self.empty)
        self.tl.addStretch(1)
        self.scroll.setWidget(self.timeline)
        root.addWidget(self.scroll, 1)

        # composer
        cw = QWidget()
        cl2 = QVBoxLayout(cw)
        cl2.setContentsMargins(14, 0, 14, 12)
        cl2.setSpacing(6)
        self.composer = QFrame()
        self.composer.setObjectName("SoftCard")
        self.composer.setStyleSheet(
            f"QFrame#SoftCard{{background:white;border:1px solid {LINE};border-radius:18px;}}"
        )
        ccl = QVBoxLayout(self.composer)
        ccl.setContentsMargins(11, 8, 9, 7)
        ccl.setSpacing(4)
        self.attach_host = QWidget()
        self.attach_layout = QHBoxLayout(self.attach_host)
        self.attach_layout.setContentsMargins(1, 0, 1, 2)
        self.attach_layout.setSpacing(5)
        self.attach_host.hide()
        ccl.addWidget(self.attach_host)
        self.edit = QPlainTextEdit()
        self.edit.setObjectName("Composer")
        self.edit.setPlaceholderText(f"让{theme.character_name(self.character)}做什么？比如：读一下这个项目，找出 3 个可改进的地方…")
        self.edit.setFixedHeight(52)
        self.edit.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.edit.installEventFilter(self)
        self.edit.textChanged.connect(self._autosize)
        ccl.addWidget(self.edit)
        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 0, 0, 0)
        bottom.setSpacing(3)
        self.attach_btn = IconButton("attach", "添加文件", 30)
        self.attach_btn.clicked.connect(self.pick_files)
        bottom.addWidget(self.attach_btn)
        self.hint = QLabel("MothX · 工具 · 多模型")
        self.hint.setObjectName("Tiny")
        bottom.addWidget(self.hint)
        bottom.addStretch(1)
        self.stop_btn = QPushButton("停止")
        self.stop_btn.setObjectName("Ghost")
        self.stop_btn.setFixedHeight(34)
        self.stop_btn.hide()
        self.stop_btn.clicked.connect(self.stop_task)
        bottom.addWidget(self.stop_btn)
        self.send_btn = QPushButton("执行")
        self.send_btn.setObjectName("Primary")
        self.send_btn.setFixedHeight(35)
        self.send_btn.setMinimumWidth(82)
        self.send_btn.clicked.connect(self.send)
        bottom.addWidget(self.send_btn)
        ccl.addLayout(bottom)
        cl2.addWidget(self.composer)
        tip = QLabel("Enter 发送 · Shift + Enter 换行 · 所有写文件和命令都会先问你")
        tip.setObjectName("Tiny")
        tip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cl2.addWidget(tip)
        root.addWidget(cw)
        self.toast = ToastLabel(self)
        for w in (header, self.name_label, self.status_label, self.avatar):
            w.installEventFilter(self)
            try:
                for child in w.findChildren(QWidget):
                    if not isinstance(child, (QPushButton, SegmentedControl)):
                        child.installEventFilter(self)
            except Exception:
                pass

    def _build_empty(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(18, 8, 18, 12)
        lay.setSpacing(10)
        lay.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.empty_art = QLabel()
        self.empty_art.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_art.setFixedHeight(158)
        lay.addWidget(self.empty_art)
        self.empty_title = QLabel()
        self.empty_title.setObjectName("Title")
        self.empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.empty_title)
        self.empty_sub = QLabel()
        self.empty_sub.setObjectName("Hint")
        self.empty_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_sub.setWordWrap(True)
        lay.addWidget(self.empty_sub)
        chips_host = QWidget()
        self.empty_flow = FlowLayout(chips_host, margin=0, spacing=4)
        lay.addWidget(chips_host)
        for text in (
            "读一下这个项目，告诉我它是做什么的",
            "找出 3 个可以改进的地方，先不要改代码",
            "帮我整理当前目录里的文档，列一个清单",
        ):
            b = Chip(text)
            b.clicked.connect(lambda _=False, x=text: self.edit.setPlainText(x))
            self.empty_flow.addWidget(b)
        return w

    # ------------------------------------------------------------------
    def _connect(self):
        c = self.controller
        c.state_changed.connect(self._on_state)
        c.assistant_delta.connect(self._on_delta)
        c.thought_delta.connect(self._on_thought)
        c.tool_started.connect(self._on_tool)
        c.tool_updated.connect(self._on_tool)
        c.plan_updated.connect(self._on_plan)
        c.usage_updated.connect(self._on_usage)
        c.permission_requested.connect(self._on_permission)
        c.question_requested.connect(self._on_question)
        c.run_started.connect(self._on_run_started)
        c.run_finished.connect(self._on_run_finished)
        c.failed.connect(self._on_failed)
        c.session_ready.connect(lambda _r: self._refresh_workspace())

    # ------------------------------------------------------------------
    def reload_runtime(self):
        self.runtime = find_runtime(self.config)
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        for m in self.runtime.models:
            self.model_combo.addItem(str(m.get("name") or m["id"]), m["id"])
            self.model_combo.setItemData(self.model_combo.count() - 1, str(m["id"]), Qt.ItemDataRole.ToolTipRole)
        wanted = str(self.config.get("mothx.model", "") or self.config.active_profile().get("chat_model", ""))
        idx = self.model_combo.findData(wanted)
        if idx >= 0:
            self.model_combo.setCurrentIndex(idx)
        self.model_combo.blockSignals(False)
        mode = str(self.config.get("mothx.mode", "agent") or "agent")
        self.mode_switch.set_active(mode)
        self._last_mode = mode
        self._refresh_workspace()

    def _refresh_workspace(self):
        raw = str(self.config.get("mothx.workspace", "") or "").strip()
        p = workspace_path(raw or None)
        self.workspace_btn.setText(f"工作区 · {p}")
        self.workspace_btn.setToolTip(f"{p}\n点击更改（只在这个文件夹内读写）")
        self.empty_art.setPixmap(
            theme.pixmap("idle", self.character).scaled(
                150, 150, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
            )
        )

    def _workspace(self) -> Path:
        raw = str(self.config.get("mothx.workspace", "") or "").strip()
        p = workspace_path(raw or None)
        p.mkdir(parents=True, exist_ok=True)
        if str(p) != str(self.config.get("mothx.workspace", "")):
            self.config.set("mothx.workspace", str(p))
            self.config.save()
        self._refresh_workspace()
        return p

    def choose_workspace(self):
        start = str(self._workspace())
        d = QFileDialog.getExistingDirectory(self, "选择工作区", start)
        if d:
            self.config.set("mothx.workspace", str(workspace_path(d)))
            self.config.save()
            self.controller.new_task()
            self._refresh_workspace()
            self.show_toast("工作区已切换，开了一个新任务")

    def _model_changed(self, _idx: int):
        model = self.model_combo.currentData()
        if model:
            self.controller.set_model(str(model))

    def _mode_changed(self, mode: str):
        if mode == "yolo" and self._last_mode != "yolo":
            answer = QMessageBox.warning(
                self,
                "开启 YOLO 模式？",
                f"YOLO 会让{theme.character_name(self.character)}直接读写文件、运行命令，不再逐次询问。\n"
                "只在你完全信任这个工作区时使用。",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                self.mode_switch.set_active(self._last_mode)
                return
        self._last_mode = mode
        self.controller.set_mode(mode)
        self.pet_state.emit("waiting" if mode == "plan" else "tool")

    # ------------------------------------------------------------------
    def _view_changed(self, view: str):
        if view == "chat":
            self.chat_requested.emit()
            QTimer.singleShot(0, lambda: self.view_switch.set_active("agent"))

    def apply_character(self):
        self.character = self.config.character
        name = theme.character_name(self.character)
        self.avatar.set_character(self.character)
        self.name_label.setText(name)
        self.setWindowTitle(f"{name} · 任务")
        self.setWindowIcon(QIcon(str(theme.character_icon_path(self.character))))
        self.empty_title.setText(f"让{name}帮你干点活")
        self.empty_sub.setText(f"{name}会读文件、查资料、改代码、跑测试；每一步都先经过你。")
        self.edit.setPlaceholderText(f"让{name}做什么？比如：读一下这个项目，找出 3 个可改进的地方…")
        for run in self.findChildren(AgentRunView):
            run.set_character(self.character, name)
        self._refresh_workspace()

    def apply_config(self):
        self.apply_character()
        if not self._busy:
            # Pick up a new API key / runtime path on the next task.
            self.controller.shutdown()
        self.reload_runtime()

    # ------------------------------------------------------------------
    def send(self):
        if self._busy:
            self.show_toast(f"{theme.character_name(self.character)}还在执行，先等一下或点停止")
            return
        text = self.edit.toPlainText().strip()
        if not text:
            return
        ws = self._workspace()
        if self.attachments:
            text = text
        paths = list(self.attachments)
        self.edit.clear()
        self.attachments = []
        self._rebuild_attachments()
        ts = time.strftime("%H:%M")
        ub = QFrame()
        ub.setObjectName("AgentUser")
        ub.setMaximumWidth(488)
        ub.setStyleSheet(f"QFrame#AgentUser{{background:{PEACH_SOFT};border:1px solid #F6D0BF;border-radius:15px;}}")
        ul = QVBoxLayout(ub)
        ul.setContentsMargins(12, 8, 12, 8)
        ul.setSpacing(4)
        lab = QLabel(text)
        lab.setWordWrap(True)
        lab.setStyleSheet(f"color:{INK};font-size:12px;")
        ul.addWidget(lab)
        for p in paths:
            ch = AttachmentChip(p)
            ul.addWidget(ch)
        wrap = QWidget()
        wl = QHBoxLayout(wrap)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.addStretch(1)
        wl.addWidget(ub)
        self.tl.insertWidget(self.tl.count() - 1, wrap)
        self.empty.hide()
        self._run = AgentRunView(self.character, theme.character_name(self.character))
        self.tl.insertWidget(self.tl.count() - 1, self._run)
        self._run.set_status("正在启动 MothX…", PEACH_DEEP)
        self._busy = True
        self._finalized = False
        self.send_btn.setEnabled(False)
        self.stop_btn.show()
        self._scroll_bottom()
        self.pet_state.emit("thinking")

        def go(session_result: dict[str, Any] | None, err: str):
            if err:
                self._fail_run(err)
                return
            self.controller.send(text, paths)

        if not self.controller.session_id:
            self.controller.new_session(str(ws), go)
        else:
            go({"sessionId": self.controller.session_id}, "")

    def _autosize(self):
        doc = self.edit.document()
        h = doc.documentLayout().documentSize().height()
        self.edit.setFixedHeight(max(52, min(140, int(h) + 16)))

    def pick_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "选择文件",
            str(Path.home()),
            "支持的文件 (*.png *.jpg *.jpeg *.webp *.pdf *.docx *.pptx *.xlsx *.txt *.md *.csv *.json *.py *.ts *.tsx);;所有文件 (*.*)",
        )
        if files:
            self.attachments = [Path(x) for x in files if Path(x).is_file()][:6]
            self._rebuild_attachments()

    def _rebuild_attachments(self):
        while self.attach_layout.count():
            item = self.attach_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not self.attachments:
            self.attach_host.hide()
            return
        for p in self.attachments:
            self.attach_layout.addWidget(AttachmentChip(p, removable=True, on_remove=self._remove_attachment))
        self.attach_layout.addStretch(1)
        self.attach_host.show()

    def _remove_attachment(self, path: str):
        self.attachments = [p for p in self.attachments if str(p) != path]
        QTimer.singleShot(0, self._rebuild_attachments)

    def stop_task(self):
        self.controller.cancel()
        if self._run:
            self._run.finish("已停止", MUTED)
        self._finalized = True
        self._end_busy("idle")
        self.pet_state.emit("idle")

    def new_task(self):
        if self._busy:
            self.controller.cancel()
        self.controller.new_task()
        for i in reversed(range(self.tl.count())):
            w = self.tl.itemAt(i).widget()
            if w and w is not self.empty:
                self.tl.removeWidget(w)
                w.deleteLater()
        self._run = None
        self._finalized = True
        self.empty.show()
        self._end_busy("idle")
        self.pet_state.emit("idle")
        self.show_toast("新任务，工作区不变")

    def _end_busy(self, state: str = "idle"):
        self._busy = False
        self.send_btn.setEnabled(True)
        self.stop_btn.hide()
        self.status_label.setText("● 执行引擎")
        self.status_label.setStyleSheet(f"color:{TEAL_DEEP};font-size:10px;")

    # ------------------------------------------------------------------
    def _on_state(self, state: str, message: str):
        mapping = {
            "starting": ("● 启动中", PEACH_DEEP),
            "ready": ("● 就绪", TEAL_DEEP),
            "working": ("● 执行中", PEACH_DEEP),
            "waiting": ("● 等你确认", DANGER),
            "idle": ("● 就绪", TEAL_DEEP),
            "error": ("● 出错", DANGER),
        }
        text, color = mapping.get(state, ("● 执行引擎", MUTED))
        self.status_label.setText(text)
        self.status_label.setStyleSheet(f"color:{color};font-size:10px;")
        if state == "working":
            self.pet_state.emit("tool")
            if self._run:
                self._run.set_status("执行中…", color)
        elif state == "waiting":
            self.pet_state.emit("waiting")
        elif state == "starting":
            self.pet_state.emit("thinking")
        elif state == "error":
            self.pet_state.emit("failure")

    def _on_run_started(self):
        if self._run:
            self._run.set_status("执行中…", PEACH_DEEP)

    def _on_delta(self, text: str):
        if self._run and not self._finalized:
            self._run.append_text(text)
            self._scroll_bottom()

    def _on_thought(self, _text: str):
        if self._run and not self._finalized:
            self._run.set_status("思考中…", MUTED)

    def _on_tool(self, info: dict[str, Any]):
        if self._run:
            self._run.add_tool(info)
            self._scroll_bottom()
        self.pet_state.emit("tool")

    def _on_plan(self, entries: list[dict[str, Any]]):
        if self._run:
            self._run.add_plan(entries)
            self._scroll_bottom()

    def _on_usage(self, usage: dict[str, Any]):
        used = int(usage.get("used") or 0)
        size = int(usage.get("size") or 0)
        self.hint.setText(f"上下文 {used / 1000:.1f}k / {size / 1000:.0f}k" if size else "MothX · 工具 · 多模型")

    def _on_permission(self, data: dict[str, Any]):
        if not self._run:
            self._run = AgentRunView(self.character, theme.character_name(self.character))
            self.tl.insertWidget(self.tl.count() - 1, self._run)
        def decide(oid: str):
            self.controller.answer_permission(data.get("request_id"), oid)
            self.pet_state.emit("tool")
            self._run.set_status("继续执行…" if oid else "已拒绝", MUTED)
        self._run.add_approval(data, decide)
        self._scroll_bottom()
        self.pet_state.emit("waiting")
        self.notify_requested.emit("需要你确认", str(data.get("title") or f"{theme.character_name(self.character)}想执行一个操作"), "", "agent-approval")

    def _on_question(self, data: dict[str, Any]):
        question = data.get("question") or f"{theme.character_name(self.character)}想确认一下"
        options = data.get("options") or []
        answer = ""
        if options:
            labels = [o["label"] for o in options]
            choice, ok = QInputDialog.getItem(self, f"{theme.character_name(self.character)}在问你", question, labels, 0, False)
            if ok and choice:
                answer = next((o["id"] for o in options if o["label"] == choice), choice)
        else:
            answer, ok = QInputDialog.getText(self, f"{theme.character_name(self.character)}在问你", question)
            if not ok:
                answer = ""
        self.controller.answer_question(data.get("request_id"), answer)
        self.pet_state.emit("tool")

    def _on_run_finished(self, reason: str):
        if self._finalized:
            return
        if reason == "error":
            self._fail_run("任务执行失败")
            return
        if self._run:
            self._run.finalize()
            self._run.finish("完成" if reason != "cancelled" else "已停止",
                             "#4FAE86" if reason != "cancelled" else MUTED)
        self._end_busy()
        self.pet_state.emit("success" if reason != "cancelled" else "idle")
        if reason != "cancelled":
            self.notify_requested.emit(
                "任务完成", f"点我看看{theme.character_name(self.character)}做了什么", "", "agent"
            )
            QTimer.singleShot(1800, lambda: self.pet_state.emit("idle"))
        self._finalized = True
        self._scroll_bottom()

    def _on_failed(self, message: str):
        if self._busy:
            self._fail_run(message)

    def _fail_run(self, message: str):
        if not self._run:
            self._run = AgentRunView(self.character, theme.character_name(self.character))
            self.tl.insertWidget(self.tl.count() - 1, self._run)
        self._run.finalize(f"这次没执行成功：\n\n{message}")
        self._run.finish("失败", DANGER)
        self._end_busy()
        self.status_label.setText("● 出错")
        self.status_label.setStyleSheet(f"color:{DANGER};font-size:10px;")
        self.pet_state.emit("failure")
        self._finalized = True
        self.notify_requested.emit("任务没跑通", message[:50], "", "agent")
        QTimer.singleShot(1800, lambda: self.pet_state.emit("idle"))
        self._scroll_bottom()

    def _scroll_bottom(self):
        bar = self.scroll.verticalScrollBar()
        QTimer.singleShot(40, lambda: bar.setValue(bar.maximum()))

    def show_toast(self, text: str, ms: int = 2400):
        if self.toast:
            self.toast.show_text(text, ms)

    # ------------------------------------------------------------------
    def show_panel(self):
        if not self.isVisible():
            self.show()
        self.raise_()
        self.activateWindow()
        QTimer.singleShot(80, lambda: self.edit.setFocus())

    def closeEvent(self, e):
        self.hide()
        e.ignore()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.hide()
        else:
            super().keyPressEvent(e)

    def eventFilter(self, obj, event):
        if obj is self.edit and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (
                event.modifiers() & Qt.KeyboardModifier.ShiftModifier
            ):
                self.send()
                return True
        if event.type() == QEvent.Type.MouseButtonPress and hasattr(event, "globalPosition"):
            if event.button() == Qt.MouseButton.LeftButton and (
                obj is self._header or isinstance(obj, QLabel)
            ):
                self._header_drag = event.globalPosition().toPoint()
                self._header_origin = self.pos()
        elif event.type() == QEvent.Type.MouseMove and self._header_drag is not None:
            self.move(self._header_origin + (event.globalPosition().toPoint() - self._header_drag))
        elif event.type() == QEvent.Type.MouseButtonRelease and self._header_drag is not None:
            self._header_drag = None
        return super().eventFilter(obj, event)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
            if paths:
                e.acceptProposedAction()
                return
        e.ignore()

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if paths:
            e.acceptProposedAction()
            self.attachments = [Path(p) for p in paths if Path(p).is_file()][:6]
            self._rebuild_attachments()
            self.show_toast(f"文件已放进任务，发送时会一起交给{theme.character_name(self.character)}")

    def shutdown(self):
        self.controller.shutdown()
