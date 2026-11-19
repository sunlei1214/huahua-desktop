"""华华 · 桌面灵感搭子 —— entry point."""
from __future__ import annotations

import ctypes
import os
import sys
import traceback
from pathlib import Path

# Keep Qt from creating a separate taskbar icon for the pet.
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")

from PySide6.QtCore import QDir, QLockFile, Qt
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from huahua import APP_TITLE, __version__, theme
from huahua.app import HuaHuaApp
from huahua.config import APP_DIR, LOG_PATH


def install_excepthook():
    def hook(exc_type, exc, tb):
        APP_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write("\n" + "=" * 70 + "\n")
            traceback.print_exception(exc_type, exc, tb, file=f)
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = hook


def main() -> int:
    install_excepthook()
    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("HuaHua.Desktop.Weaver.1")
        except Exception:
            pass

    QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    app.setApplicationName("华华和熙熙")
    app.setApplicationDisplayName(APP_TITLE)
    app.setApplicationVersion(__version__)
    app.setOrganizationName("HuaHua")
    app.setWindowIcon(QIcon(str(theme.ASSETS / "icon.ico")))
    app.setStyle("Fusion")
    app.setFont(theme.font(10))
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet(theme.qss())

    lock = QLockFile(str(QDir.temp().filePath("huahua_desktop.lock")))
    lock.setStaleLockTime(0)
    if not lock.tryLock(120):
        if lock.removeStaleLockFile():
            if not lock.tryLock(120):
                QMessageBox.information(None, "华华和熙熙已经在桌面上", "小工具已经在运行啦，看看屏幕右下角，或者点系统托盘里的小图标。")
                return 0
        else:
            QMessageBox.information(None, "华华和熙熙已经在桌面上", "小工具已经在运行啦，看看屏幕右下角，或者点系统托盘里的小图标。")
            return 0

    controller = HuaHuaApp(app)
    app.aboutToQuit.connect(lambda: lock.unlock())
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
