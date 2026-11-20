"""Agent task window: MothX ACP as the execution backend."""
from __future__ import annotations

import html
import json
import os
import time
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QEvent, QPoint, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QFont,
    QIcon,
    QKeyEvent,
    QPixmap,
    QTextCharFormat,
    QTextCursor,
)
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
    DropOverlay,
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
class AgentComposerEdit(QPlainTextEdit):
    """Composer that treats dropped files as task attachments, not text."""

    files_dropped = Signal(list)
    drop_state = Signal(bool)

    def _paths(self, event) -> list[str]:
        if not event.mimeData().hasUrls():
            return []
        return [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]

    def dragEnterEvent(self, event):
        paths = self._paths(event)
        if paths:
            self.drop_state.emit(True)
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if self._paths(event):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dragLeaveEvent(self, event):
        self.drop_state.emit(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        paths = self._paths(event)
        self.drop_state.emit(False)
        if paths:
            self.files_dropped.emit(paths)
            event.acceptProposedAction()
            return
        super().dropEvent(event)


# ----------------------------------------------------------------------
class ArtifactsCard(QFrame):
    """Files created or changed by the last task, with direct open actions."""

    def __init__(self, workspace: Path, files: list[Path], parent=None):
        super().__init__(parent)
        self.workspace = workspace
        self.files = files
        self.setObjectName("ArtifactsCard")
        self.setStyleSheet(
            f"QFrame#ArtifactsCard{{background:#FFF9F5;border:1px solid #EFD5C7;"
            f"border-radius:14px;}}"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(5)
        title = QLabel("本次任务产物")
        title.setFont(font(10, QFont.Weight.Bold))
        title.setStyleSheet(f"color:{PEACH_DEEP};")
        lay.addWidget(title)
        sub = QLabel(f"工作区 · {workspace}")
        sub.setObjectName("Tiny")
        sub.setWordWrap(True)
        sub.setToolTip(str(workspace))
        lay.addWidget(sub)
        for path in files[:8]:
            try:
                rel = path.relative_to(workspace)
            except ValueError:
                rel = path
            b = QPushButton("📄  " + str(rel))
            b.setObjectName("Chip")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setToolTip(str(path))
            b.clicked.connect(lambda _=False, p=path: QDesktopServices.openUrl(QUrl.fromLocalFile(str(p))))
            lay.addWidget(b)
        if len(files) > 8:
            more = QLabel(f"还有 {len(files) - 8} 个文件，打开工作区查看")
            more.setObjectName("Tiny")
            lay.addWidget(more)
        row = QHBoxLayout()
        row.setSpacing(6)
        open_ws = QPushButton("打开工作区")
        open_ws.setObjectName("Ghost")
        open_ws.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.workspace)))
        )
        row.addWidget(open_ws)
        row.addStretch(1)
        lay.addLayout(row)


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
        if not detail and isinstance(raw, dict):
            # rawOutput can be a whole terminal transcript.  Never serialize
            # all of it just to build a 800-char tooltip.
            parts = []
            for key, value in list(raw.items())[:4]:
                text = str(value)
                parts.append(f"{key}: {text[:160]}")
            detail = "\n".join(parts)
        self.setToolTip(detail[:800])


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
        self._thought_raw = ""
        self._pending_text = ""
        self._pending_thought = ""
        self._thought_open = False
        self._streaming = True
        self._last_height_update = 0.0
        self._stream_timer = QTimer(self)
        self._stream_timer.setSingleShot(True)
        self._stream_timer.setInterval(33)
        self._stream_timer.timeout.connect(self._flush_streams)
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

        self.thought_btn = QPushButton("▸ 思考过程")
        self.thought_btn.setObjectName("ThoughtToggle")
        self.thought_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.thought_btn.clicked.connect(self.toggle_thought)
        self.thought_btn.hide()
        root.addWidget(self.thought_btn)
        self.thoughtb = NoWheelTextBrowser()
        self.thoughtb.setFrameShape(QFrame.Shape.NoFrame)
        self.thoughtb.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.thoughtb.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.thoughtb.setStyleSheet(
            "QTextBrowser{background:#FBF3ED;border:1px solid #F0DFD4;"
            "border-radius:10px;padding:7px;color:#826C62;}"
        )
        self.thoughtb.setFixedWidth(466)
        self.thoughtb.setFont(font(9))
        self.thoughtb.document().setDocumentMargin(0)
        self.thoughtb.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.LinksAccessibleByMouse
        )
        self.thoughtb.hide()
        root.addWidget(self.thoughtb)
        self._thought_fmt = QTextCharFormat()
        self._thought_fmt.setForeground(QColor("#826C62"))
        self._thought_fmt.setFont(font(9))

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

    def append_thought(self, text: str):
        if not text:
            return
        # Open on the first reasoning delta so the process is visible by
        # default; the user can collapse it with one click.
        if not self._thought_raw and not self._pending_thought and not self._thought_open:
            self._thought_open = True
            self.thoughtb.show()
        self._pending_thought += text
        self.thought_btn.show()
        self.thought_btn.setText("▾ 思考中…" if self._thought_open else "▸ 思考中…")
        if not self._stream_timer.isActive():
            self._stream_timer.start()

    def _flush_streams(self, force: bool = False):
        thought = self._pending_thought
        text = self._pending_text
        self._pending_thought = ""
        self._pending_text = ""
        if thought:
            self._thought_raw += thought
            cursor = QTextCursor(self.thoughtb.document())
            cursor.movePosition(QTextCursor.MoveOperation.End)
            cursor.insertText(thought, self._thought_fmt)
        if text:
            self._raw += text
            self.textb.show()
            cursor = QTextCursor(self.textb.document())
            cursor.movePosition(QTextCursor.MoveOperation.End)
            cursor.insertText(text)
        if thought or text:
            self._update_heights(force=force)
            if self._thought_open:
                bar = self.thoughtb.verticalScrollBar()
                bar.setValue(bar.maximum())

    def _update_heights(self, force: bool = False):
        now = time.monotonic()
        if not force and now - self._last_height_update < 0.08:
            return
        self._last_height_update = now
        if self._thought_raw:
            doc = self.thoughtb.document()
            doc.setTextWidth(450)
            h = max(42, int(doc.size().height() + 16))
            self.thoughtb.setFixedHeight(min(h, 260))
        if self._raw:
            doc = self.textb.document()
            doc.setTextWidth(466)
            h = max(20, int(doc.size().height() + 4))
            self.textb.setFixedHeight(min(h, 1600))

    def toggle_thought(self):
        self._flush_streams(force=True)
        self._thought_open = not self._thought_open
        self.thoughtb.setVisible(self._thought_open)
        if self._streaming:
            self.thought_btn.setText("▾ 思考中…" if self._thought_open else "▸ 思考中…")
        else:
            self.thought_btn.setText("▾ 思考过程" if self._thought_open else "▸ 思考过程")
        QTimer.singleShot(0, lambda: self._update_heights(force=True))

    def append_text(self, text: str):
        if not text:
            return
        self._pending_text += text
        if not self._stream_timer.isActive():
            self._stream_timer.start()

    def finalize(self, text: str | None = None):
        self._stream_timer.stop()
        self._flush_streams(force=True)
        self._streaming = False
        if text is not None:
            self._raw = text
        if self._thought_raw:
            self.thought_btn.setText("▾ 思考过程" if self._thought_open else "▸ 思考过程")
        if self._raw:
            # Markdown rendering is intentionally skipped for very large
            # transcripts; setHtml on a 100k+ document can freeze the pet.
            if len(self._raw) <= 80_000:
                self.textb.setHtml(md_to_html(self._raw))
            else:
                self.textb.setPlainText(self._raw)
            self._update_heights(force=True)
            self.set_status("完成", "#4FAE86")

    def _resize(self):
        self._update_heights(force=True)

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

    def add_artifacts(self, workspace: Path, files: list[Path]):
        card = ArtifactsCard(workspace, files)
        self.extra.addWidget(card)
        self.extra_host.show()
        self._resize()

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
    minimized_changed = Signal(bool)
    choice_requested = Signal(dict)
    choice_resolved = Signal()
    task_finished = Signal(str)
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
        self._minimized = False
        self._last_pet_state = ""
        self._task_token = 0
        self._task_started_at = 0.0
        self._task_workspace = ""
        self._pending_choice: dict[str, Any] | None = None
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
        self._scroll_timer = QTimer(self)
        self._scroll_timer.setSingleShot(True)
        self._scroll_timer.setInterval(60)
        self._scroll_timer.timeout.connect(self._do_scroll_bottom)
        self.drop_overlay = DropOverlay(self)
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
        self.min_btn = IconButton("minimize", "最小化到桌宠，任务继续", 26)
        self.min_btn.clicked.connect(self.minimize_to_pet)
        self.close_btn = IconButton("close", "收起", 28)
        self.close_btn.clicked.connect(self._close_clicked)
        for b in (self.new_btn, self.settings_btn, self.min_btn, self.close_btn):
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
        self.workspace_btn = QLabel("工作区 · 未选择")
        self.workspace_btn.setObjectName("WorkspacePath")
        self.workspace_btn.setMinimumHeight(30)
        self.workspace_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.workspace_btn.setStyleSheet(
            f"QLabel#WorkspacePath{{background:white;border:1px solid {LINE};"
            f"border-radius:14px;padding:6px 11px;color:{INK_SOFT};font-size:12px;}}"
        )
        self.workspace_btn.setToolTip("工作区只读显示；点右侧「打开」查看文件夹")
        ws_row.addWidget(self.workspace_btn, 1)
        self.change_ws_btn = QPushButton("更改")
        self.change_ws_btn.setObjectName("Ghost")
        self.change_ws_btn.setFixedSize(46, 30)
        self.change_ws_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.change_ws_btn.clicked.connect(self.choose_workspace)
        ws_row.addWidget(self.change_ws_btn)
        self.open_ws_btn = QPushButton("打开")
        self.open_ws_btn.setObjectName("Ghost")
        self.open_ws_btn.setFixedSize(46, 30)
        self.open_ws_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_ws_btn.setToolTip("在资源管理器中打开工作区")
        self.open_ws_btn.clicked.connect(self.open_workspace)
        ws_row.addWidget(self.open_ws_btn)
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
            [("执行", "agent"), ("计划", "plan"), ("YOLO", "yolo")],
            active="agent",
            compact=True,
            variant="mode",
        )
        self.mode_switch.setFixedWidth(166)
        self.mode_switch.setToolTip("执行：逐次审批；计划：只读；YOLO：完全放开，不推荐")
        self.mode_switch.changed.connect(self._mode_changed)
        self._last_mode = "agent"
        row.addWidget(self.mode_switch)
        cl.addLayout(row)
        think_row = QHBoxLayout()
        think_row.setSpacing(6)
        think_label = QLabel("思考")
        think_label.setObjectName("Tiny")
        think_row.addWidget(think_label)
        self.thinking_combo = QComboBox()
        self.thinking_combo.addItem("关闭", "off")
        self.thinking_combo.addItem("低", "low")
        self.thinking_combo.addItem("中", "medium")
        self.thinking_combo.addItem("高", "high")
        self.thinking_combo.setFixedWidth(84)
        self.thinking_combo.setToolTip("MothX 思考等级；中/高会显示推理过程，也会更慢")
        self.thinking_combo.currentIndexChanged.connect(self._thinking_changed)
        think_row.addWidget(self.thinking_combo)
        think_hint = QLabel("过程会显示在对话里，可折叠")
        think_hint.setObjectName("Tiny")
        think_row.addWidget(think_hint)
        think_row.addStretch(1)
        cl.addLayout(think_row)
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
        self.attach_host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.attach_layout = FlowLayout(self.attach_host, margin=3, spacing=5)
        self.attach_host.hide()
        ccl.addWidget(self.attach_host)
        self.edit = AgentComposerEdit()
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
        self.hint = QLabel("附件可拖入 · 命令会先问")
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
        tip = QLabel("Enter 发送 · Shift + Enter 换行 · 附件可直接拖进来")
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
        self.edit.files_dropped.connect(self._add_paths)
        self.edit.drop_state.connect(
            lambda active: self._show_drop_overlay() if active else self._hide_drop_overlay()
        )

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
        thinking = str(self.config.get("mothx.thinking", "medium") or "medium")
        self.thinking_combo.blockSignals(True)
        idx = self.thinking_combo.findData(thinking)
        self.thinking_combo.setCurrentIndex(max(0, idx))
        self.thinking_combo.blockSignals(False)
        self._refresh_workspace()

    def _refresh_workspace(self):
        raw = str(self.config.get("mothx.workspace", "") or "").strip()
        p = workspace_path(raw or None)
        self.workspace_btn.setText(f"工作区 · {p}")
        self.workspace_btn.setToolTip(f"{p}\n只读显示；点右侧「打开」查看文件夹")
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

    def open_workspace(self):
        p = self._workspace()
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))

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

    def _thinking_changed(self, _idx: int):
        level = str(self.thinking_combo.currentData() or "medium")
        self.controller.set_thinking(level)
        self.show_toast(f"思考等级：{self.thinking_combo.currentText()}")

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
        self._pet("waiting" if mode == "plan" else "thinking")

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
        self._task_started_at = time.time()
        self._task_workspace = str(ws)
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
        self._task_token += 1
        self._last_pet_state = ""
        self._pending_choice = None
        self.choice_resolved.emit()
        self.send_btn.setEnabled(False)
        self.stop_btn.show()
        self._scroll_bottom()
        self._pet("thinking")

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
            self._add_paths(files)

    def _rebuild_attachments(self):
        while self.attach_layout.count():
            item = self.attach_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not self.attachments:
            self.attach_host.setFixedHeight(0)
            self.attach_host.hide()
            self.attach_host.updateGeometry()
            self.composer.updateGeometry()
            if hasattr(self, "empty"):
                self.empty.setVisible(self._run is None)
            return
        for p in self.attachments:
            self.attach_layout.addWidget(
                AttachmentChip(
                    p, removable=True, on_remove=self._remove_attachment, compact=True
                )
            )
        self.attach_layout.invalidate()
        # Compact task chips are 40px high and at most 160px wide.  The flow
        # layout only knows real widths after its first pass, so use a
        # deterministic row count; otherwise 3+ chips can be clipped.
        width = self.composer.width() - 22 if self.composer.width() > 100 else 480
        per_row = max(1, max(300, width) // 165)
        rows = (len(self.attachments) + per_row - 1) // per_row
        height = rows * 40 + max(0, rows - 1) * 5 + 8
        self.attach_host.setFixedHeight(height)
        self.attach_host.show()
        self.attach_host.updateGeometry()
        self.composer.updateGeometry()
        if hasattr(self, "empty"):
            self.empty.hide()

    def _add_paths(self, paths: list[str]):
        existing = {str(p.resolve()) for p in self.attachments}
        added = 0
        for raw in paths:
            p = Path(raw)
            if not p.is_file():
                continue
            try:
                key = str(p.resolve())
            except Exception:
                key = str(p)
            if key in existing:
                continue
            self.attachments.append(p)
            existing.add(key)
            added += 1
            if len(self.attachments) >= 6:
                break
        if added:
            self._rebuild_attachments()
            self.show_toast(f"已加入 {added} 个附件")

    def _remove_attachment(self, path: str):
        target = str(Path(path).resolve())
        self.attachments = [
            p for p in self.attachments if str(p.resolve()) != target
        ]
        QTimer.singleShot(0, self._rebuild_attachments)

    def stop_task(self):
        self.controller.cancel()
        if self._run:
            self._run.finish("已停止", MUTED)
        self._pending_choice = None
        self.choice_resolved.emit()
        self._finalized = True
        self._end_busy("idle")
        self._pet("idle")

    def new_task(self):
        if self._busy:
            self.controller.cancel()
        self.controller.new_task()
        self._pending_choice = None
        self.choice_resolved.emit()
        for i in reversed(range(self.tl.count())):
            w = self.tl.itemAt(i).widget()
            if w and w is not self.empty:
                self.tl.removeWidget(w)
                w.deleteLater()
        self._run = None
        self._finalized = True
        self.attachments = []
        self._rebuild_attachments()
        self.empty.show()
        self._end_busy("idle")
        self._pet("idle")
        self.show_toast("新任务，工作区不变")

    def _end_busy(self, state: str = "idle"):
        self._busy = False
        self.send_btn.setEnabled(True)
        self.stop_btn.hide()
        self.status_label.setText("● 执行引擎")
        self.status_label.setStyleSheet(f"color:{TEAL_DEEP};font-size:10px;")

    def _schedule_pet_idle(self):
        token = self._task_token
        def settle():
            if token == self._task_token and not self.is_task_running:
                self._pet("idle")
        QTimer.singleShot(1800, settle)

    def _pet(self, state: str):
        if state != self._last_pet_state:
            self._last_pet_state = state
            self.pet_state.emit(state)

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
            self._pet("thinking")
            if self._run:
                self._run.set_status("执行中…", color)
        elif state == "waiting":
            self._pet("waiting")
        elif state == "starting":
            self._pet("thinking")
        elif state == "error":
            self._pet("failure")

    def _on_run_started(self):
        if self._run:
            self._run.set_status("执行中…", PEACH_DEEP)

    def _on_delta(self, text: str):
        if self._run and not self._finalized:
            self._run.append_text(text)
            self._scroll_bottom()

    def _on_thought(self, text: str):
        if self._run and not self._finalized:
            self._run.append_thought(text)
            self._run.set_status("思考中…", MUTED)
            self._pet("thinking")
            self._scroll_bottom()

    def _on_tool(self, info: dict[str, Any]):
        if self._run:
            self._run.add_tool(info)
            self._scroll_bottom()
        self._pet("thinking")

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
            self.answer_choice(data.get("request_id"), "permission", oid)
            self._run.set_status("继续执行…" if oid else "已拒绝", MUTED)
        self._run.add_approval(data, decide)
        self._pending_choice = {
            "kind": "permission",
            "request_id": data.get("request_id"),
            "title": str(data.get("title") or "需要你确认"),
            "options": data.get("options") or [],
        }
        self._scroll_bottom()
        self._pet("waiting")
        self.choice_requested.emit(self._pending_choice)
        self.notify_requested.emit("需要你确认", str(data.get("title") or f"{theme.character_name(self.character)}想执行一个操作"), "", "agent-approval")

    def _on_question(self, data: dict[str, Any]):
        question = data.get("question") or f"{theme.character_name(self.character)}想确认一下"
        options = data.get("options") or []
        self._pending_choice = {
            "kind": "question",
            "request_id": data.get("request_id"),
            "title": question,
            "options": options,
        }
        # While minimized, answer through the pet's choice bubbles instead of
        # forcing a modal dialog to open on top of the task window.
        if self._minimized and options:
            self._pet("waiting")
            self.choice_requested.emit(self._pending_choice)
            return
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
        self._pending_choice = None
        self.choice_resolved.emit()
        self.controller.answer_question(data.get("request_id"), answer)
        self._pet("thinking")

    def answer_choice(self, request_id: Any, kind: str, option_id: str) -> None:
        """Resolve a pending permission/question from the pet HUD."""
        if kind == "permission":
            self.controller.answer_permission(request_id, option_id)
        else:
            self.controller.answer_question(request_id, option_id)
        self._pending_choice = None
        self.choice_resolved.emit()
        self._pet("thinking")
        if self._run:
            self._run.set_status("继续执行…" if option_id else "已拒绝", MUTED)

    def _recent_task_files(self) -> list[Path]:
        if not self._task_workspace:
            return []
        root = Path(self._task_workspace)
        if not root.exists():
            return []
        since = max(0.0, self._task_started_at - 5)
        skip_dirs = {
            ".git", ".mothx", "node_modules", "__pycache__", "缓存",
            "build", "dist", ".venv", "venv", "runtime",
        }
        found: list[Path] = []
        try:
            for base, dirs, names in os.walk(root):
                dirs[:] = [
                    d for d in dirs
                    if d not in skip_dirs and not d.startswith(".")
                ]
                for name in names:
                    if name.startswith("~$"):
                        continue
                    p = Path(base) / name
                    try:
                        if p.is_file() and p.stat().st_mtime >= since:
                            found.append(p)
                    except OSError:
                        continue
                    if len(found) >= 40:
                        break
                if len(found) >= 40:
                    break
        except OSError:
            pass
        found.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return found

    def _show_artifacts(self):
        if not self._run or not self._task_workspace:
            return
        files = self._recent_task_files()
        if files:
            self._run.add_artifacts(Path(self._task_workspace), files)
            self._scroll_bottom()

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
        self._pending_choice = None
        self.choice_resolved.emit()
        if reason != "cancelled":
            self._show_artifacts()
            self.task_finished.emit(reason)
        self._pet("success" if reason != "cancelled" else "idle")
        if reason != "cancelled":
            self.notify_requested.emit(
                "任务完成", f"点我看看{theme.character_name(self.character)}做了什么", "", "agent"
            )
            self._schedule_pet_idle()
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
        self._pending_choice = None
        self.choice_resolved.emit()
        self._end_busy()
        self.status_label.setText("● 出错")
        self.status_label.setStyleSheet(f"color:{DANGER};font-size:10px;")
        self._pet("failure")
        self._finalized = True
        self.task_finished.emit("error")
        self.notify_requested.emit("任务没跑通", message[:50], "", "agent")
        self._schedule_pet_idle()
        self._scroll_bottom()

    def _scroll_bottom(self):
        if not self._scroll_timer.isActive():
            self._scroll_timer.start()

    def _do_scroll_bottom(self):
        bar = self.scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    def show_toast(self, text: str, ms: int = 2400):
        if self.toast:
            self.toast.show_text(text, ms)

    # ------------------------------------------------------------------
    @property
    def is_task_running(self) -> bool:
        return self._busy or self.controller.running

    @property
    def pending_choice(self) -> dict[str, Any] | None:
        return self._pending_choice

    def is_minimized(self) -> bool:
        return self._minimized

    def _close_clicked(self):
        if self.is_task_running or self._pending_choice:
            self.minimize_to_pet()
        else:
            self.hide()

    def minimize_to_pet(self):
        if not self.is_task_running and not self._pending_choice:
            # No active task: keep normal minimize behavior.
            self.showMinimized()
            return
        self._minimized = True
        self.hide()
        self.minimized_changed.emit(True)

    def show_panel(self):
        if self.isMinimized():
            self.showNormal()
        elif not self.isVisible():
            self.show()
        self._minimized = False
        self.minimized_changed.emit(False)
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
        edit_surface = obj is self.edit or obj is self.edit.viewport()
        if edit_surface and event.type() in (QEvent.Type.DragEnter, QEvent.Type.DragMove):
            if event.mimeData().hasUrls():
                self._show_drop_overlay()
                event.acceptProposedAction()
                return True
        if edit_surface and event.type() == QEvent.Type.Drop:
            paths = self._url_paths(event)
            self._hide_drop_overlay()
            if paths:
                self._add_paths(paths)
                event.acceptProposedAction()
                return True
        if edit_surface and event.type() == QEvent.Type.DragLeave:
            self._hide_drop_overlay()
            return False
        if edit_surface and event.type() == QEvent.Type.KeyPress:
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

    @staticmethod
    def _url_paths(e) -> list[str]:
        if not e.mimeData().hasUrls():
            return []
        return [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]

    def _show_drop_overlay(self):
        self.drop_overlay.setGeometry(self.rect())
        self.drop_overlay.show()
        self.drop_overlay.raise_()

    def _hide_drop_overlay(self):
        if hasattr(self, "drop_overlay"):
            self.drop_overlay.hide()

    def dragEnterEvent(self, e):
        paths = self._url_paths(e)
        if paths:
            self._show_drop_overlay()
            e.acceptProposedAction()
            return
        e.ignore()

    def dragLeaveEvent(self, e):
        self._hide_drop_overlay()
        e.accept()

    def dropEvent(self, e):
        paths = self._url_paths(e)
        self._hide_drop_overlay()
        if paths:
            e.acceptProposedAction()
            self._add_paths(paths)
            self.show_toast(
                f"文件已放进任务，发送时会一起交给{theme.character_name(self.character)}"
            )

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if hasattr(self, "drop_overlay"):
            self.drop_overlay.setGeometry(self.rect())
        # Keep the attachment card width honest after a window resize.
        if hasattr(self, "attach_layout") and self.attachments:
            self._rebuild_attachments()

    def shutdown(self):
        self.controller.shutdown()
