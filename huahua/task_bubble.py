"""Compact pet-level HUD for a minimized MothX task.

The normal chat/task windows are too large to keep visible while the user is
doing something else.  When a task is minimized to the pet, a small translucent
thinking bubble stays above its head.  If MothX needs a decision, one bubble per
option is shown instead, so the user can answer without reopening the window.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QGuiApplication, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

from .theme import INK, PEACH_DEEP, font

BUBBLE_BG = QColor(255, 251, 247, 226)


class ThinkingBubble(QWidget):
    activated = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(94, 50)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("任务进行中，点击打开任务窗口")
        self._phase = 0
        self._tail_down = True
        self._timer = QTimer(self)
        self._timer.setInterval(360)
        self._timer.timeout.connect(self._tick)
        self.hide()

    def _tick(self):
        self._phase = (self._phase + 1) % 3
        self.update()

    def show_at(self, anchor: QRect):
        screen = QGuiApplication.screenAt(anchor.center()) or QGuiApplication.primaryScreen()
        geo = screen.availableGeometry()
        x = anchor.center().x() - self.width() // 2
        x = max(geo.left() + 8, min(x, geo.right() - self.width() - 8))
        above = anchor.top() - self.height() - 5
        if above >= geo.top() + 8:
            self._tail_down = True
            y = above
        else:
            self._tail_down = False
            y = anchor.bottom() + 5
        self.move(x, y)
        self.show()
        self.raise_()
        self._timer.start()

    def hide_bubble(self):
        self._timer.stop()
        self.hide()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.activated.emit()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._tail_down:
            card = QRectF(3, 3, self.width() - 6, self.height() - 14)
        else:
            card = QRectF(3, 11, self.width() - 6, self.height() - 14)
        # soft shadow
        for i in range(9, 0, -2):
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(76, 45, 34, int(12 * (1 - i / 11))))
            p.drawRoundedRect(card.adjusted(-i / 2, -i / 2 + 3, i / 2, i / 2 + 3), 16 + i / 2, 16 + i / 2)
        p.setBrush(BUBBLE_BG)
        p.setPen(QPen(QColor("#E8CDBE"), 1))
        p.drawRoundedRect(card, 16, 16)
        # tail
        cx = card.center().x()
        if self._tail_down:
            y = card.bottom() - 1
            tri = QPolygonF([QPointF(cx - 9, y), QPointF(cx + 9, y), QPointF(cx, y + 11)])
            cover = QRectF(cx - 8, y - 2, 16, 3)
        else:
            y = card.top() + 1
            tri = QPolygonF([QPointF(cx - 9, y), QPointF(cx + 9, y), QPointF(cx, y - 11)])
            cover = QRectF(cx - 8, y - 1, 16, 3)
        p.setBrush(BUBBLE_BG)
        p.setPen(QPen(QColor("#E8CDBE"), 1))
        p.drawPolygon(tri)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(BUBBLE_BG)
        p.drawRect(cover)

        # three pulsing dots
        cy = card.center().y()
        for i in range(3):
            active = i == self._phase
            alpha = 235 if active else 105
            radius = 3.4 if active else 2.8
            p.setBrush(QColor(196, 106, 78, alpha))
            p.drawEllipse(QPointF(cx + (i - 1) * 13, cy), radius, radius)


class ChoiceBubble(QWidget):
    chosen = Signal(str)

    def __init__(self, label: str, value: str, tail: bool = False, parent=None):
        super().__init__(parent)
        self.label = label
        self.value = value
        self.tail = tail
        self._hover = False
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        fm = QFontMetrics(font(10, QFont.Weight.DemiBold))
        w = max(116, min(248, fm.horizontalAdvance(label) + 34))
        self.setFixedSize(w, 42)
        self.setToolTip(label)

    def show_at(self, x: int, y: int):
        self.move(x, y)
        self.show()
        self.raise_()

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.chosen.emit(self.value)
            self.hide()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.tail:
            card = QRectF(2, 2, self.width() - 4, self.height() - 13)
        else:
            card = QRectF(2, 2, self.width() - 4, self.height() - 4)
        for i in range(7, 0, -2):
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(76, 45, 34, int(10 * (1 - i / 9))))
            p.drawRoundedRect(card.adjusted(-i / 2, -i / 2 + 2, i / 2, i / 2 + 2), 14 + i / 2, 14 + i / 2)
        p.setBrush(QColor(255, 250, 245, 246 if self._hover else 232))
        p.setPen(QPen(QColor(PEACH_DEEP if self._hover else "#E8CDBE"), 1))
        p.drawRoundedRect(card, 14, 14)
        if self.tail:
            cx = card.center().x()
            y = card.bottom() - 1
            tri = QPolygonF([QPointF(cx - 8, y), QPointF(cx + 8, y), QPointF(cx, y + 10)])
            p.setBrush(QColor(255, 250, 245, 246 if self._hover else 232))
            p.setPen(QPen(QColor(PEACH_DEEP if self._hover else "#E8CDBE"), 1))
            p.drawPolygon(tri)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 250, 245, 246 if self._hover else 232))
            p.drawRect(QRectF(cx - 7, y - 2, 14, 3))
        p.setPen(QColor(PEACH_DEEP if self._hover else INK))
        p.setFont(font(10, QFont.Weight.DemiBold))
        p.drawText(card, Qt.AlignmentFlag.AlignCenter, self.label)
