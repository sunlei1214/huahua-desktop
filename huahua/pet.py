"""The little desktop weaver: frameless sprite window, reactions, menu, bubble."""
from __future__ import annotations

import math
import random
import time
from pathlib import Path

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QColor,
    QCursor,
    QFont,
    QGuiApplication,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
    QRegion,
)
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QMenu, QVBoxLayout, QWidget

from . import theme
from .config import Config
from .theme import CREAM, INK, INK_SOFT, LINE, MUTED, PAPER, PEACH, PEACH_DEEP, TEAL_DEEP, font, icon_font
from .widgets import IconButton


class SpeechBubble(QWidget):
    activated = Signal(str)

    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedWidth(292)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._tail_down = True
        self._payload = ""
        self._icon: QPixmap | None = None
        self._anim: QPropertyAnimation | None = None

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(16, 13, 16, 22)
        self.layout.setSpacing(5)

        head = QHBoxLayout()
        head.setSpacing(7)
        self.name = QLabel("华华")
        self.name.setFont(font(8, QFont.Weight.Bold))
        self.name.setStyleSheet(f"color:{PEACH_DEEP};")
        head.addWidget(self.name)
        self.kind = QLabel("")
        self.kind.setObjectName("Tiny")
        head.addWidget(self.kind)
        head.addStretch(1)
        self.close_btn = IconButton("close", "收起", 22)
        self.close_btn.setStyleSheet("QPushButton{background:transparent;border:none;color:#BBA79F;}")
        self.close_btn.clicked.connect(self.hide)
        head.addWidget(self.close_btn)
        self.layout.addLayout(head)

        body = QHBoxLayout()
        body.setSpacing(9)
        self.icon_label = QLabel()
        self.icon_label.setFixedSize(54, 54)
        self.icon_label.hide()
        body.addWidget(self.icon_label, 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(2)
        self.message = QLabel("")
        self.message.setWordWrap(True)
        self.message.setFont(font(10, QFont.Weight.DemiBold))
        self.message.setStyleSheet(f"color:{INK};line-height:1.45;")
        self.sub = QLabel("")
        self.sub.setWordWrap(True)
        self.sub.setObjectName("Tiny")
        self.sub.setStyleSheet(f"color:{MUTED};")
        col.addWidget(self.message)
        col.addWidget(self.sub)
        body.addLayout(col, 1)
        self.layout.addLayout(body)

        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._fade_out)

    # ------------------------------------------------------------------
    def show_message(
        self,
        text: str,
        subtitle: str = "",
        anchor: QRect | None = None,
        icon: str | QPixmap | None = None,
        kind: str = "",
        payload: str = "",
        duration: int = 5200,
    ):
        self.message.setText(text)
        self.sub.setText(subtitle)
        self.sub.setVisible(bool(subtitle))
        self.kind.setText(kind)
        self.kind.setVisible(bool(kind))
        self._payload = payload
        if isinstance(icon, QPixmap) and not icon.isNull():
            self._icon = icon
        elif isinstance(icon, (str, Path)) and Path(icon).exists():
            self._icon = QPixmap(str(icon))
        else:
            self._icon = None
        if self._icon and not self._icon.isNull():
            self.icon_label.setPixmap(
                self._icon.scaled(54, 54, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
            )
            self.icon_label.setStyleSheet("border-radius:12px;background:#F7E9E0;")
            self.icon_label.setScaledContents(True)
            self.icon_label.setMask(QRegion(0, 0, 54, 54, QRegion.RegionType.Ellipse))
            self.icon_label.show()
        else:
            self.icon_label.hide()

        self.adjustSize()
        h = self.sizeHint().height()
        self.setFixedHeight(h)
        if anchor is not None:
            screen = QGuiApplication.screenAt(anchor.center()) or QGuiApplication.primaryScreen()
            geo = screen.availableGeometry()
            x = anchor.center().x() - self.width() // 2
            x = max(geo.left() + 8, min(x, geo.right() - self.width() - 8))
            above_y = anchor.top() - self.height() - 6
            if above_y < geo.top() + 8:
                self._tail_down = False
                self.layout.setContentsMargins(16, 22, 16, 13)
                y = anchor.bottom() + 6
            else:
                self._tail_down = True
                self.layout.setContentsMargins(16, 13, 16, 22)
                y = above_y
            self.move(x, y)
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()
        self._anim = QPropertyAnimation(self, b"windowOpacity", self)
        self._anim.setDuration(160)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.start()
        self.timer.start(duration)
        self.update()

    def _fade_out(self):
        self._anim = QPropertyAnimation(self, b"windowOpacity", self)
        self._anim.setDuration(180)
        self._anim.setStartValue(self.windowOpacity())
        self._anim.setEndValue(0.0)
        self._anim.finished.connect(self.hide)
        self._anim.start()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.timer.stop()
            self.hide()
            if self._payload:
                self.activated.emit(self._payload)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(1, 1, self.width() - 2, self.height() - 2)
        if self._tail_down:
            r.setBottom(self.height() - 11)
        else:
            r.setTop(11)
        # shadow
        for i in range(12, 0, -2):
            c = QColor(75, 45, 34, int(16 * (1 - i / 14)))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(c)
            p.drawRoundedRect(r.adjusted(-i / 2, -i / 2 + 4, i / 2, i / 2 + 4), 19 + i / 2, 19 + i / 2)
        # card
        p.setBrush(QColor(255, 252, 248, 252))
        p.setPen(QPen(QColor("#EFD7CA"), 1))
        p.drawRoundedRect(r, 18, 18)
        # tail
        cx = r.center().x()
        if self._tail_down:
            y = r.bottom() - 1
            tri = QPolygonF([QPointF(cx - 11, y), QPointF(cx + 11, y), QPointF(cx, y + 13)])
        else:
            y = r.top() + 1
            tri = QPolygonF([QPointF(cx - 11, y), QPointF(cx + 11, y), QPointF(cx, y - 13)])
        p.setBrush(QColor(255, 252, 248, 252))
        p.setPen(QPen(QColor("#EFD7CA"), 1))
        p.drawPolygon(tri)
        # cover the border seam
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 252, 248, 252))
        if self._tail_down:
            p.drawRect(QRectF(cx - 10, y - 2, 20, 3))
        else:
            p.drawRect(QRectF(cx - 10, y - 1, 20, 3))


class PetWindow(QWidget):
    chat_requested = Signal()
    mode_requested = Signal(str)
    settings_requested = Signal()
    hide_requested = Signal()
    quit_requested = Signal()
    files_dropped = Signal(list)
    focus_requested = Signal()
    screenshot_requested = Signal()
    config_changed = Signal()
    bubble_activated = Signal(str)
    moved = Signal()

    SIZES = (170, 220, 260, 300, 340)

    def __init__(self, config: Config):
        super().__init__(None)
        self.config = config
        self.character = config.character
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.NoDropShadowWindowHint
        )
        if config.get("appearance.always_on_top", True):
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("点我聊天 · 拖文件给我 · 右键更多")

        self.state = "idle"
        self.base_state = "idle"
        self._temporary_until = 0.0
        self._busy = False
        self._hover = False
        self._dragging = False
        self._drag_origin = QPoint()
        self._win_origin = QPoint()
        self._press_pos = QPoint()
        self._press_time = 0.0
        self._phase = 0.0
        self._last_interaction = time.time()
        self._walk_anim: QPropertyAnimation | None = None
        self._sleeping = False
        self._alpha_image: QImage | None = None
        self._sprite = QPixmap()

        self.bubble = SpeechBubble()
        self.bubble.name.setText(theme.character_name(self.character))
        self.bubble.activated.connect(self.bubble_activated.emit)

        self._apply_size(config.get("appearance.size", 260), center=False)
        self.setWindowOpacity(max(0.35, config.get("appearance.opacity", 100) / 100.0))
        self._restore_position()

        self._frame_timer = QTimer(self)
        self._frame_timer.timeout.connect(self._on_frame)
        self._frame_timer.start(33)
        self._blink_timer = QTimer(self)
        self._blink_timer.timeout.connect(self._maybe_blink)
        self._blink_timer.start(7600)
        self._pose_timer = QTimer(self)
        self._pose_timer.timeout.connect(self._maybe_pose)
        self._pose_timer.start(46000)
        self._idle_timer = QTimer(self)
        self._idle_timer.timeout.connect(self._check_idle)
        self._idle_timer.start(15000)
        self._walk_timer = QTimer(self)
        self._walk_timer.timeout.connect(self._maybe_walk)
        self._walk_timer.start(105000)

        self._set_state("idle")

    # ------------------------------------------------------------------
    def _apply_size(self, size: int, center: bool = True):
        size = max(140, min(420, int(size)))
        old_center = self.geometry().center()
        self.setFixedSize(size, size)
        self.config.set("appearance.size", size)
        if center:
            self.move(old_center - QPoint(size // 2, size // 2))
            self._clamp_to_screen()
        self._sprite = theme.pixmap(self.state, self.character).scaled(
            size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
        )
        self._alpha_image = self._sprite.toImage().convertToFormat(QImage.Format.Format_ARGB32)
        self.update()

    def apply_config(self):
        new_character = self.config.character
        if new_character != self.character:
            self.character = new_character
            self._sleeping = False
            self.bubble.name.setText(theme.character_name(self.character))
            self._set_state("greet", 1400)
        self._apply_size(self.config.get("appearance.size", 260), center=True)
        if self.config.get("appearance.position") is None:
            screen = QGuiApplication.screenAt(self.geometry().center()) or QGuiApplication.primaryScreen()
            g = screen.availableGeometry()
            self.move(g.right() - self.width() - 30, g.bottom() - self.height() - 8)
        self.setWindowOpacity(max(0.35, self.config.get("appearance.opacity", 100) / 100.0))
        top = bool(self.config.get("appearance.always_on_top", True))
        if bool(self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint) != top:
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, top)
            self.show()
        self.update()

    def _restore_position(self):
        pos = self.config.get("appearance.position")
        screen = QGuiApplication.primaryScreen().availableGeometry()
        if isinstance(pos, (list, tuple)) and len(pos) == 2:
            self.move(int(pos[0]), int(pos[1]))
            self._clamp_to_screen()
        else:
            self.move(screen.right() - self.width() - 30, screen.bottom() - self.height() - 8)

    def _clamp_to_screen(self):
        screen = QGuiApplication.screenAt(self.geometry().center()) or QGuiApplication.primaryScreen()
        g = screen.availableGeometry()
        x = max(g.left() - self.width() // 3, min(self.x(), g.right() - self.width() * 2 // 3))
        y = max(g.top(), min(self.y(), g.bottom() - 40))
        self.move(x, y)

    # ------------------------------------------------------------------
    def _sprite_for(self, state: str) -> QPixmap:
        return theme.pixmap(state, self.character).scaled(
            self.width(), self.height(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
        )

    def _set_state(self, state: str, revert_ms: int | None = None):
        self.state = state
        self._sprite = self._sprite_for(state)
        self._alpha_image = self._sprite.toImage().convertToFormat(QImage.Format.Format_ARGB32)
        self.update()
        if revert_ms:
            self._temporary_until = time.time() + revert_ms / 1000
        else:
            self._temporary_until = 0.0

    def set_state(self, state: str, revert_ms: int | None = None):
        """Public state switch used by the app (thinking/success/failure...)."""
        if state in ("thinking", "tool", "waiting"):
            self._busy = True
        elif state in ("success", "failure"):
            self._busy = False
        elif state == "idle":
            self._busy = False
        self._set_state(state, revert_ms)

    def set_busy(self, busy: bool):
        self._busy = busy
        if busy:
            self._set_state("thinking")
        elif self.state in ("thinking", "tool", "waiting"):
            self._set_state("idle")

    def react(self, kind: str = "head"):
        self._touch()
        state = "react-head" if kind == "head" else "react-belly"
        self._set_state(state, 1700 if kind == "head" else 1100)
        lines = {
            "huahua": {
                "head": ("唔……摸头会变聪明哦。", "再摸一下也不是不行"),
                "belly": ("呀，痒！别戳肚子啦～", "华华怕痒，换个别的地方嘛"),
            },
            "xixi": {
                "head": ("摸头就摸头，别弄乱我的刘海！", "好吧，看在你夸我的份上"),
                "belly": ("哈哈哈哈，别戳！兔子要笑醒了。", "熙熙的肚子是禁区啦"),
            },
        }
        text, sub = lines[self.character][kind]
        self.bubble.show_message(text, sub, self.geometry(), duration=2400)
        self._set_state("heart", 900)
        QTimer.singleShot(900, lambda: self._set_state(state, 900))

    def play_pose(self, touch: bool = True):
        state = random.choice(["wink", "peace", "heart", "blush", "shades"])
        self._set_state(state, 2600)
        if touch:
            self._touch()

    def notify(self, text: str, subtitle: str = "", icon=None, payload: str = "", kind: str = "", duration: int = 6200):
        if not self.config.get("appearance.bubble", True):
            return
        self.bubble.show_message(text, subtitle, self.geometry(), icon=icon, kind=kind, payload=payload, duration=duration)

    def show_bubble(self, text: str, subtitle: str = "", duration: int = 3600):
        if self.isVisible() and self.config.get("appearance.bubble", True):
            self.bubble.show_message(text, subtitle, self.geometry(), duration=duration)

    # ------------------------------------------------------------------
    def _touch(self):
        self._last_interaction = time.time()
        if self._sleeping:
            self._sleeping = False
            self._set_state("idle")

    def _on_frame(self):
        self._phase += 0.05
        if self._temporary_until and time.time() > self._temporary_until:
            self._temporary_until = 0.0
            self._set_state("hover" if self._hover else "idle")
        if self.config.get("appearance.animations", True):
            self.update()

    def _maybe_blink(self):
        if self._busy or self._sleeping or self._hover or self._dragging:
            return
        if self.state != "idle":
            return
        self._set_state("wink", 190)

    def _maybe_pose(self):
        if self._busy or self._sleeping or self._hover or self._dragging:
            return
        if self.state != "idle":
            return
        if random.random() < 0.55:
            self.play_pose(touch=False)

    def _check_idle(self):
        mins = int(self.config.get("behavior.sleep_minutes", 8) or 8)
        if mins <= 0 or self._busy or self._dragging or self._hover:
            return
        if time.time() - self._last_interaction > mins * 60 and not self._sleeping:
            self._sleeping = True
            self._set_state("sleep")

    def _maybe_walk(self):
        if not self.config.get("appearance.walk", False):
            return
        if self._busy or self._sleeping or self._dragging or self._hover or self.bubble.isVisible():
            return
        screen = QGuiApplication.screenAt(self.geometry().center()) or QGuiApplication.primaryScreen()
        g = screen.availableGeometry()
        target_x = random.randint(g.left() + 10, max(g.left() + 10, g.right() - self.width() - 10))
        target = QPoint(target_x, self.y())
        if abs(target.x() - self.x()) < 60:
            return
        self._set_state("greet", 900)
        anim = QPropertyAnimation(self, b"pos", self)
        anim.setDuration(random.randint(1800, 3200))
        anim.setStartValue(self.pos())
        anim.setEndValue(target)
        anim.setEasingCurve(QEasingCurve.Type.InOutSine)
        anim.finished.connect(lambda: self._set_state("idle"))
        anim.start()
        self._walk_anim = anim

    # ------------------------------------------------------------------
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        w, h = self.width(), self.height()
        anim = self.config.get("appearance.animations", True)
        bob = math.sin(self._phase) * (3.0 if anim else 0.0)
        if self._sleeping:
            bob = math.sin(self._phase * 0.45) * 2.0
        hover_scale = 1.025 if self._hover and not self._dragging else 1.0

        # warm halo
        cx, cy = w / 2, h * 0.48
        glow = QLinearGradient(0, 0, 0, h)
        glow.setColorAt(0, QColor(255, 238, 220, 0))
        glow.setColorAt(0.55, QColor(255, 218, 190, 30))
        glow.setColorAt(1, QColor(255, 205, 180, 0))
        p.setBrush(glow)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QRectF(w * 0.09, h * 0.07, w * 0.82, h * 0.9))

        # ground shadow
        alpha = 44 - int(min(18, abs(bob) * 4))
        p.setBrush(QColor(107, 70, 52, max(12, alpha)))
        p.drawEllipse(QRectF(w * 0.21, h * 0.89, w * 0.58, h * 0.075))

        # sparkles
        if anim and not self._sleeping:
            pts = [(0.18, 0.31, 7), (0.80, 0.24, 5), (0.87, 0.58, 8), (0.10, 0.64, 4)]
            for i, (px, py, s) in enumerate(pts):
                a = int(80 + 65 * (0.5 + 0.5 * math.sin(self._phase * 1.4 + i * 1.9)))
                star = QColor(255, 206, 104, a)
                self._draw_sparkle(p, QPointF(w * px, h * py + math.sin(self._phase + i) * 2), s, star)

        # character
        draw_w = w * hover_scale
        draw_h = h * hover_scale
        target = QRectF((w - draw_w) / 2, (h - draw_h) / 2 + bob, draw_w, draw_h)
        p.drawPixmap(target, self._sprite, QRectF(self._sprite.rect()))

        if self._sleeping:
            p.setPen(QColor(129, 105, 94, 170))
            p.setFont(font(10, QFont.Weight.Bold))
            zx, zy = w * 0.69, h * 0.28 + math.sin(self._phase * 0.8) * 2
            p.drawText(QPointF(zx, zy), "z")
            p.setFont(font(8, QFont.Weight.Bold))
            p.drawText(QPointF(zx + 9, zy - 11), "z")

    def _draw_sparkle(self, p: QPainter, c: QPointF, s: float, color: QColor):
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        path = QPainterPath()
        path.moveTo(c.x(), c.y() - s)
        path.quadTo(c.x() + s * 0.18, c.y() - s * 0.18, c.x() + s, c.y())
        path.quadTo(c.x() + s * 0.18, c.y() + s * 0.18, c.x(), c.y() + s)
        path.quadTo(c.x() - s * 0.18, c.y() + s * 0.18, c.x() - s, c.y())
        path.quadTo(c.x() - s * 0.18, c.y() - s * 0.18, c.x(), c.y() - s)
        p.drawPath(path)

    # ------------------------------------------------------------------
    def _alpha_at(self, global_pos: QPoint) -> bool:
        if self._alpha_image is None or self._alpha_image.isNull():
            return True
        local = self.mapFromGlobal(global_pos)
        bob = math.sin(self._phase) * (3.0 if self.config.get("appearance.animations", True) else 0.0)
        hover_scale = 1.025 if self._hover and not self._dragging else 1.0
        draw_w = self.width() * hover_scale
        draw_h = self.height() * hover_scale
        x = (self.width() - draw_w) / 2
        y = (self.height() - draw_h) / 2 + bob
        ix = int((local.x() - x) / draw_w * self._alpha_image.width())
        iy = int((local.y() - y) / draw_h * self._alpha_image.height())
        if 0 <= ix < self._alpha_image.width() and 0 <= iy < self._alpha_image.height():
            return self._alpha_image.pixelColor(ix, iy).alpha() > 24
        return False

    def enterEvent(self, e):
        self._touch()
        self._hover = True
        if not self._busy and not self._sleeping and self.state == "idle":
            self._set_state("hover")
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        if not self._busy and not self._sleeping and self.state in ("hover", "idle"):
            self._set_state("idle")
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._touch()
            self._dragging = False
            self._press_pos = e.globalPosition().toPoint()
            self._drag_origin = self._press_pos
            self._win_origin = self.pos()
            self._press_time = time.time()
            e.accept()
        elif e.button() == Qt.MouseButton.RightButton:
            self._touch()
            self._show_menu(e.globalPosition().toPoint())
            e.accept()

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.MouseButton.LeftButton:
            gp = e.globalPosition().toPoint()
            if not self._dragging and (gp - self._press_pos).manhattanLength() > 5:
                self._dragging = True
                self._set_state("drag")
            if self._dragging:
                self.move(self._win_origin + (gp - self._drag_origin))
                self.bubble.hide()
            e.accept()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return
        if self._dragging:
            self._dragging = False
            self._clamp_to_screen()
            self._set_state("idle")
            self.config.set("appearance.position", [self.x(), self.y()])
            self.config.save()
            self.moved.emit()
        else:
            gp = e.globalPosition().toPoint()
            if self._alpha_at(gp):
                local_y = self.mapFromGlobal(gp).y()
                kind = "head" if local_y < self.height() * 0.43 else "belly"
                self.react(kind)
            # A click on the pet is the primary "open the dialog" gesture.
            QTimer.singleShot(90, self.chat_requested.emit)
        e.accept()

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._touch()
            self._set_state("greet", 1500)
            self.chat_requested.emit()
            e.accept()

    # ------------------------------------------------------------------
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
            if paths:
                self._touch()
                self._set_state("drag", 60000)
                self.show_bubble("松手，我看看这个～", "图片、文档、视频都能读", 2400)
                e.acceptProposedAction()
                return
        e.ignore()

    def dragLeaveEvent(self, e):
        self._set_state("idle")
        e.accept()

    def dropEvent(self, e):
        self._set_state("idle")
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if paths:
            e.acceptProposedAction()
            self.files_dropped.emit(paths)
            self._set_state("waiting", 1200)

    # ------------------------------------------------------------------
    def _show_menu(self, gp: QPoint):
        menu = QMenu(self)
        menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        menu.setWindowFlags(menu.windowFlags() | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint)
        menu.setStyleSheet(
            theme.qss()
            + """
            QMenu { background: #FFFCF8; border: 1px solid #E9C9BA; border-radius: 14px; padding: 7px; }
            QMenu::item { padding: 8px 28px 8px 30px; border-radius: 8px; }
            QMenu::item:selected { background: #FFE5D7; color: #E98F73; }
            """
        )
        a = menu.addAction("和我聊聊")
        a.triggered.connect(self.chat_requested.emit)
        a = menu.addAction("画一张图")
        a.triggered.connect(lambda: self.mode_requested.emit("image"))
        a = menu.addAction("截图问问")
        a.triggered.connect(self.screenshot_requested.emit)
        a = menu.addAction("做个数字人视频")
        a.triggered.connect(lambda: self.mode_requested.emit("video"))
        menu.addSeparator()
        a = menu.addAction("换个表情")
        a.triggered.connect(self.play_pose)
        a = menu.addAction("陪我专注 %d 分钟" % int(self.config.get("behavior.focus_minutes", 25) or 25))
        a.triggered.connect(self.focus_requested.emit)
        a = menu.addAction("投喂一颗星星")
        a.triggered.connect(self._feed_star)
        menu.addSeparator()

        size_menu = menu.addMenu("桌宠大小")
        group = QActionGroup(size_menu)
        group.setExclusive(True)
        labels = {170: "小", 220: "中", 260: "标准", 300: "大", 340: "特大"}
        for s in self.SIZES:
            act = size_menu.addAction(f"{labels.get(s, str(s))}  ·  {s}px")
            act.setCheckable(True)
            act.setChecked(abs(self.width() - s) < 4)
            act.triggered.connect(lambda _=False, n=s: self._change_size(n))
            group.addAction(act)
        pin = menu.addAction("始终置顶")
        pin.setCheckable(True)
        pin.setChecked(bool(self.config.get("appearance.always_on_top", True)))
        pin.triggered.connect(self._toggle_pin)
        walk = menu.addAction("偶尔散散步")
        walk.setCheckable(True)
        walk.setChecked(bool(self.config.get("appearance.walk", False)))
        walk.triggered.connect(self._toggle_walk)
        mute = menu.addAction("静音")
        mute.setCheckable(True)
        mute.setChecked(not bool(self.config.get("behavior.sound", True)))
        mute.triggered.connect(self._toggle_mute)
        menu.addSeparator()

        a = menu.addAction("设置…")
        a.triggered.connect(self.settings_requested.emit)
        a = menu.addAction("隐藏到托盘")
        a.triggered.connect(self.hide_requested.emit)
        a = menu.addAction("退出小工具")
        a.triggered.connect(self.quit_requested.emit)
        menu.exec(gp)

    def _feed_star(self):
        self._set_state("heart", 1800)
        self.bubble.show_message("嗷呜——星星是甜的！", "亲密度 +1，今天也一起加油", self.geometry(), duration=3000)
        self._touch()

    def _change_size(self, size: int):
        self._apply_size(size, center=True)
        self.config.set("appearance.position", [self.x(), self.y()])
        self.config.save()
        self.config_changed.emit()

    def _toggle_pin(self, checked: bool):
        self.config.set("appearance.always_on_top", checked)
        self.config.save()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, checked)
        self.show()
        self.config_changed.emit()

    def _toggle_walk(self, checked: bool):
        self.config.set("appearance.walk", checked)
        self.config.save()
        self.config_changed.emit()

    def _toggle_mute(self, checked: bool):
        self.config.set("behavior.sound", not checked)
        self.config.save()
        self.config_changed.emit()

    # ------------------------------------------------------------------
    def closeEvent(self, e):
        self.config.set("appearance.position", [self.x(), self.y()])
        self.config.save()
        self.bubble.close()
        super().closeEvent(e)
