"""A small region-screenshot overlay used by '截图问问'."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from .theme import CREAM, INK, PEACH, font


class ScreenshotOverlay(QWidget):
    captured = Signal(QPixmap)
    cancelled = Signal()

    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setWindowTitle("截图问问")
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        self._screen = screen
        self._geo = screen.geometry()
        self.setGeometry(self._geo)
        self._shot = screen.grabWindow(0)
        self._start: QPoint | None = None
        self._end: QPoint | None = None
        self._dragging = False
        self._captured = False

    def start(self):
        self._start = None
        self._end = None
        self._dragging = False
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.drawPixmap(self.rect(), self._shot, self._shot.rect())
        p.fillRect(self.rect(), QColor(24, 17, 14, 118))
        if self._start and self._end:
            r = QRect(self._start, self._end).normalized().intersected(self.rect())
            if r.width() > 2 and r.height() > 2:
                p.drawPixmap(r, self._shot, QRect(r.x(), r.y(), r.width(), r.height()))
                p.setPen(QPen(QColor(PEACH), 1.5))
                p.drawRect(r.adjusted(0, 0, -1, -1))
                # corner marks
                p.setPen(QPen(QColor(CREAM), 2))
                n = 12
                for x, y, dx, dy in (
                    (r.left(), r.top(), 1, 1),
                    (r.right(), r.top(), -1, 1),
                    (r.left(), r.bottom(), 1, -1),
                    (r.right(), r.bottom(), -1, -1),
                ):
                    p.drawLine(x, y, x + dx * n, y)
                    p.drawLine(x, y, x, y + dy * n)
                label = f"{r.width()} × {r.height()}"
                p.setFont(font(9))
                tw = p.fontMetrics().horizontalAdvance(label) + 16
                box = QRect(r.left(), max(4, r.top() - 28), tw, 22)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(38, 28, 24, 220))
                p.drawRoundedRect(box, 7, 7)
                p.setPen(QColor(CREAM))
                p.drawText(box, Qt.AlignmentFlag.AlignCenter, label)
        else:
            p.setPen(QColor(CREAM))
            p.setFont(font(12, 600))
            p.drawText(self.rect().adjusted(0, -80, 0, 0), Qt.AlignmentFlag.AlignCenter, "拖动框选一块区域，让我看看")
            p.setFont(font(9))
            p.setPen(QColor(220, 202, 190))
            p.drawText(self.rect().adjusted(0, -50, 0, 0), Qt.AlignmentFlag.AlignCenter, "Esc 或右键取消")

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.RightButton:
            self.close()
            return
        if e.button() == Qt.MouseButton.LeftButton:
            self._start = e.position().toPoint()
            self._end = self._start
            self._dragging = True
            self.update()

    def mouseMoveEvent(self, e):
        if self._dragging:
            self._end = e.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton or not self._dragging:
            return
        self._dragging = False
        if not self._start or not self._end:
            return
        r = QRect(self._start, self._end).normalized().intersected(self.rect())
        if r.width() < 12 or r.height() < 12:
            self.close()
            return
        pm = self._shot.copy(r)
        self._captured = True
        self.hide()
        self.captured.emit(pm)
        self.close()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(e)

    def closeEvent(self, e):
        if not self._captured:
            self.cancelled.emit()
        super().closeEvent(e)
