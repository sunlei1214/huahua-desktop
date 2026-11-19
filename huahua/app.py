"""Application controller: tray, pet, chat, focus timer, notifications."""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QObject, QPoint, QRect, QTimer, Qt, QUrl
from PySide6.QtGui import QAction, QColor, QCursor, QDesktopServices, QGuiApplication, QIcon
from PySide6.QtMultimedia import QSoundEffect
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from . import __version__, media, theme
from .agent_window import AgentWindow
from .chat import ChatWindow
from .config import Config, LOG_PATH, default_output_dir
from .history import HistoryStore
from .pet import PetWindow
from .settings import SettingsDialog
from .task_bubble import ChoiceBubble, ThinkingBubble


class HuaHuaApp(QObject):
    def __init__(self, app: QApplication):
        super().__init__()
        self.app = app
        self.config = Config()
        self.config.ensure_dirs()
        self.history = HistoryStore(
            max_sessions=max(5, int(self.config.get("storage.max_history", 30))),
            enabled=bool(self.config.get("storage.save_history", True)),
        )
        last = self.config.get("ui.last_session")
        if last and self.history.get(last):
            self.history.switch(last)

        self.pet = PetWindow(self.config)
        self.chat = ChatWindow(self.config, self.history)
        self.agent = AgentWindow(self.config)
        self.thinking_bubble = ThinkingBubble()
        self.choice_bubbles: list[ChoiceBubble] = []
        self.settings_dialog: SettingsDialog | None = None
        self._quitting = False
        self._focus_timer: QTimer | None = None
        self._focus_deadline = 0.0
        self._focus_tick: QTimer | None = None

        self._init_sound()
        self._init_tray()
        self._wire()
        self._apply_chat_flags()
        self.pet.show()
        self._apply_character_ui()
        self._update_tray_tip()

        QTimer.singleShot(700, self._greet)
        QTimer.singleShot(1600, self._first_run_hint)

    # ------------------------------------------------------------------
    def _wire(self):
        self.pet.chat_requested.connect(lambda: self.open_chat())
        self.pet.agent_requested.connect(self.open_agent)
        self.pet.mode_requested.connect(lambda m: self.open_chat(m))
        self.pet.settings_requested.connect(self.open_settings)
        self.pet.hide_requested.connect(self.hide_pet)
        self.pet.quit_requested.connect(self.quit)
        self.pet.files_dropped.connect(self._files_dropped)
        self.pet.focus_requested.connect(self.start_focus)
        self.pet.screenshot_requested.connect(self._screenshot_from_pet)
        self.pet.bubble_activated.connect(self._bubble_clicked)
        self.pet.config_changed.connect(self._config_changed)
        self.pet.moved.connect(self._update_tray_tip)
        self.pet.moved.connect(self._reposition_task_bubbles)

        self.chat.pet_state.connect(self._pet_state)
        self.chat.notify_requested.connect(self._notify)
        self.chat.settings_requested.connect(self.open_settings)
        self.chat.agent_requested.connect(self.open_agent)
        self.chat.title_changed.connect(lambda _t: self._update_tray_tip())

        self.agent.pet_state.connect(self._pet_state)
        self.agent.notify_requested.connect(self._notify)
        self.agent.settings_requested.connect(self.open_settings)
        self.agent.chat_requested.connect(lambda: self.open_chat())
        self.agent.minimized_changed.connect(self._agent_minimized)
        self.agent.choice_requested.connect(self._agent_choice_requested)
        self.agent.choice_resolved.connect(self._hide_task_bubbles)
        self.thinking_bubble.activated.connect(self.open_agent)

    @property
    def character(self) -> str:
        return self.config.character

    @property
    def character_name(self) -> str:
        return theme.character_name(self.character)

    def _apply_character_ui(self):
        key = self.character
        name = theme.character_name(key)
        icon = QIcon(str(theme.character_icon_path(key)))
        self.app.setApplicationDisplayName(f"{name} · 桌面灵感搭子")
        self.app.setWindowIcon(icon)
        self.chat.apply_character()
        self.chat.setWindowIcon(icon)
        self.chat.setWindowTitle(name)
        self.agent.apply_character()
        self.agent.setWindowIcon(icon)
        self.tray.setIcon(icon)
        self.tray.setToolTip(f"{name} · 桌面灵感搭子")
        self.pet.setToolTip(f"点我聊天 · {name} · 右键更多")
        self._build_tray_menu()

    def _apply_chat_flags(self):
        self.chat.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        if self.chat.isVisible():
            self.chat.show()

    # ------------------------------------------------------------------
    def _init_sound(self):
        self.sound = QSoundEffect(self)
        self.sound.setSource(QUrl.fromLocalFile(str(theme.ASSETS / "sounds" / "chime.wav")))
        self.sound.setVolume(0.32)

    def _play_chime(self):
        if self.config.get("behavior.sound", True):
            try:
                self.sound.play()
            except Exception:
                pass

    def _init_tray(self):
        self.tray = QSystemTrayIcon(QIcon(str(theme.character_icon_path(self.character))), self)
        self.tray.setToolTip(f"{self.character_name} · 桌面灵感搭子")
        self.tray.activated.connect(self._tray_activated)
        self._build_tray_menu()
        self.tray.show()

    def _build_tray_menu(self):
        menu = QMenu()
        menu.setStyleSheet(theme.qss())
        a = menu.addAction(f"打开{self.character_name}")
        a.triggered.connect(lambda: self.open_chat())
        a = menu.addAction(f"让{self.character_name}干活…")
        a.triggered.connect(self.open_agent)
        a = menu.addAction("画一张图")
        a.triggered.connect(lambda: self.open_chat("image"))
        a = menu.addAction("做个数字人视频")
        a.triggered.connect(lambda: self.open_chat("video"))
        menu.addSeparator()
        a = menu.addAction("结束专注" if self._focus_timer else "陪我专注")
        a.triggered.connect(self.toggle_focus)
        a = menu.addAction("显示 / 隐藏桌宠")
        a.triggered.connect(self.toggle_pet)
        a = menu.addAction("设置…")
        a.triggered.connect(self.open_settings)
        menu.addSeparator()
        a = menu.addAction("退出小工具")
        a.triggered.connect(self.quit)
        self.tray.setContextMenu(menu)
        self._tray_menu = menu

    def _tray_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.open_chat()

    def _update_tray_tip(self):
        tip = f"{self.character_name} · 桌面灵感搭子"
        if self._focus_timer and self._focus_deadline:
            left = max(0, int(self._focus_deadline - time.time()))
            tip += f"\n专注中 {left // 60:02d}:{left % 60:02d}"
        if self.chat.session.get("title"):
            tip += f"\n{self.chat.session['title']}"
        self.tray.setToolTip(tip[:120])

    # ------------------------------------------------------------------
    def _greet(self):
        hour = time.localtime().tm_hour
        if 5 <= hour < 11:
            hi = "早上好呀"
        elif 11 <= hour < 14:
            hi = "中午好呀"
        elif 14 <= hour < 18:
            hi = "下午好呀"
        elif 18 <= hour < 23:
            hi = "晚上好呀"
        else:
            hi = "夜深啦"
        self.pet.set_state("greet", 1900)
        line = {
            "huahua": f"{hi}，我是华华。",
            "xixi": f"{hi}，熙熙来啦！",
        }[self.character]
        self.pet.show_bubble(line, "点我聊天，拖文件给我也可以", duration=4200)
        QTimer.singleShot(2000, lambda: self.pet.set_state("idle"))

    def _first_run_hint(self):
        if not self.config.is_configured():
            self.pet.show_bubble("还差一把钥匙。", "右键 → 设置，填入模力方舟 API Key", duration=7000)
        elif not self.config.get("ui.onboarded", False):
            self.config.set("ui.onboarded", True)
            self.config.save()

    # ------------------------------------------------------------------
    def open_chat(self, mode: str | None = None, session_id: str | None = None):
        if not self.pet.isVisible():
            self.pet.show()
        self.agent.hide()
        if session_id and session_id != self.chat.session.get("id"):
            self.chat.load_session(session_id)
        if mode:
            self.chat.set_mode(mode)
        if not self.chat.isVisible():
            self._position_chat()
        self.chat.show_panel()
        self._update_tray_tip()

    def open_agent(self):
        if not self.pet.isVisible():
            self.pet.show()
        self.chat.hide()
        if not self.agent.isVisible():
            self._position_agent()
        self.agent.show_panel()
        self._update_tray_tip()

    def _position_agent(self):
        screen = QGuiApplication.screenAt(self.pet.geometry().center()) or QGuiApplication.primaryScreen()
        g = screen.availableGeometry()
        w, h = self.agent.width(), self.agent.height()
        w = min(w, g.width() - 16)
        h = min(h, g.height() - 16)
        self.agent.resize(w, h)
        x = self.pet.x() - w - 4
        if x < g.left() + 8:
            x = max(g.left() + 8, min(self.pet.x() + self.pet.width() + 4, g.right() - w - 8))
        if x + w > g.right() - 8:
            x = max(g.left() + 8, g.right() - w - 8)
        y = max(g.top() + 8, min(self.pet.y() + self.pet.height() - h + 20, g.bottom() - h - 8))
        self.agent.move(x, y)

    def _position_chat(self):
        screen = QGuiApplication.screenAt(self.pet.geometry().center()) or QGuiApplication.primaryScreen()
        g = screen.availableGeometry()
        cw, ch = self.chat.width(), self.chat.height()
        if self.pet.geometry().center().x() > g.center().x():
            x = self.pet.x() - cw - 4
        else:
            x = self.pet.x() + self.pet.width() + 4
        if x < g.left() + 8:
            x = max(g.left() + 8, self.pet.x() + self.pet.width() + 4)
        if x + cw > g.right() - 8:
            x = max(g.left() + 8, g.right() - cw - 8)
        y = self.pet.y() + self.pet.height() - ch + 20
        y = max(g.top() + 8, min(y, g.bottom() - ch - 8))
        self.chat.move(x, y)

    def _pet_state(self, state: str):
        self.pet.set_state(state)
        if not self.agent.is_minimized():
            return
        if state in ("thinking", "tool", "starting"):
            if self.agent.is_task_running and not self.agent.pending_choice:
                self._show_thinking_bubble()
        elif state in ("waiting", "success", "failure", "idle"):
            if state != "waiting":
                self._hide_task_bubbles()
            elif self.agent.pending_choice:
                self._hide_thinking_bubble()

    def _agent_choice_requested(self, data: dict):
        if self.agent.is_minimized():
            self._show_choice_bubbles(data)

    def _agent_minimized(self, minimized: bool):
        if not minimized:
            self._hide_task_bubbles()
            return
        if self.agent.pending_choice:
            self._show_choice_bubbles(self.agent.pending_choice)
        elif self.agent.is_task_running:
            self._show_thinking_bubble()
        else:
            self._hide_task_bubbles()

    def _show_thinking_bubble(self):
        if not self.pet.isVisible() or not self.config.get("appearance.bubble", True):
            return
        if self.agent.pending_choice:
            return
        self.pet.bubble.hide()
        self.thinking_bubble.show_at(self.pet.geometry())

    def _hide_thinking_bubble(self):
        self.thinking_bubble.hide_bubble()

    def _show_choice_bubbles(self, data: dict):
        self.pet.bubble.hide()
        self._hide_thinking_bubble()
        self._clear_choice_bubbles()
        options = data.get("options") or []
        if not options:
            return
        for i, opt in enumerate(options):
            b = ChoiceBubble(
                str(opt.get("name") or opt.get("label") or "确定"),
                str(opt.get("id") or ""),
                tail=(i == len(options) - 1),
            )
            b.chosen.connect(lambda oid, d=data: self._choose_task_option(d, oid))
            self.choice_bubbles.append(b)
        self._layout_choice_bubbles()

    def _layout_choice_bubbles(self):
        if not self.choice_bubbles:
            return
        anchor = self.pet.geometry()
        screen = QGuiApplication.screenAt(anchor.center()) or QGuiApplication.primaryScreen()
        geo = screen.availableGeometry()
        gap = 6
        total_h = sum(b.height() for b in self.choice_bubbles) + gap * (len(self.choice_bubbles) - 1)
        bottom = anchor.top() - 10
        top = bottom - total_h
        if top < geo.top() + 8:
            top = geo.top() + 8
        y = top
        for b in self.choice_bubbles:
            x = anchor.center().x() - b.width() // 2
            x = max(geo.left() + 8, min(x, geo.right() - b.width() - 8))
            b.show_at(int(x), int(y))
            y += b.height() + gap

    def _choose_task_option(self, data: dict, option_id: str):
        self._hide_task_bubbles()
        self.agent.answer_choice(data.get("request_id"), str(data.get("kind") or "permission"), option_id)
        QTimer.singleShot(200, lambda: self._pet_state("thinking"))

    def _clear_choice_bubbles(self):
        for b in self.choice_bubbles:
            b.hide()
            b.deleteLater()
        self.choice_bubbles = []

    def _hide_task_bubbles(self):
        self._hide_thinking_bubble()
        self._clear_choice_bubbles()

    def _reposition_task_bubbles(self):
        if self.thinking_bubble.isVisible():
            self.thinking_bubble.show_at(self.pet.geometry())
        if self.choice_bubbles:
            self._layout_choice_bubbles()

    def _files_dropped(self, paths: list):
        self.open_chat()
        self.chat.handle_dropped(paths)

    def _screenshot_from_pet(self):
        self.open_chat()
        QTimer.singleShot(120, self.chat.take_screenshot)

    def _bubble_clicked(self, payload: str):
        if payload.startswith("session:"):
            sid = payload.split(":", 1)[1]
            self.open_chat(session_id=sid)
        elif payload.startswith("agent"):
            self.open_agent()
        else:
            self.open_chat()

    def _notify(self, title: str, subtitle: str, icon_path: str, payload: str):
        if self.config.get("behavior.notify", True):
            try:
                self.tray.showMessage(title, subtitle, QSystemTrayIcon.MessageIcon.Information, 5000)
            except Exception:
                pass
        icon = icon_path
        if icon and Path(icon).suffix.lower() in media.VIDEO_EXTS:
            try:
                src = Path(icon)
                thumb = self.config.output_dir / "缓存" / (src.stem + "_bubble.jpg")
                if not thumb.exists():
                    media.video_thumb(src, thumb)
                icon = str(thumb) if thumb.exists() else ""
            except Exception:
                icon = ""
        self._play_chime()
        approval = payload.startswith("agent-approval")
        if approval and self.agent.is_minimized():
            # The pet HUD shows one bubble per option; don't stack a second
            # generic approval bubble on top of it.
            return
        if self.pet.isVisible():
            self.pet.notify(
                title, subtitle, icon=icon, payload=payload,
                kind="确认" if approval else "完成", duration=9000 if approval else 7200,
            )
            if (
                not approval
                and not self.agent.is_task_running
                and self.pet.state not in ("sleep",)
            ):
                self.pet.set_state("success", 1700)
                QTimer.singleShot(
                    1800,
                    lambda: None if self.agent.is_task_running else self.pet.set_state("idle"),
                )

    # ------------------------------------------------------------------
    def open_settings(self):
        if self.settings_dialog is not None and self.settings_dialog.isVisible():
            self.settings_dialog.raise_()
            self.settings_dialog.activateWindow()
            return
        dlg = SettingsDialog(self.config, self.history, None)
        self.settings_dialog = dlg
        dlg.saved.connect(self._settings_saved)
        dlg.clear_history_requested.connect(self._clear_history)
        self._hide_task_bubbles()
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()
        QTimer.singleShot(0, lambda: (dlg.raise_(), dlg.activateWindow()))
        dlg.exec()
        self.settings_dialog = None
        if self.agent.is_minimized():
            self._agent_minimized(True)
        elif self.agent.isVisible():
            self.agent.show_panel()
        elif self.chat.isVisible():
            self.chat.show_panel()

    def _settings_saved(self):
        old_character = self.pet.character
        self.pet.apply_config()
        self.pet.config = self.config
        self.chat.config = self.config
        self.agent.config = self.config
        self.agent.apply_config()
        self.chat.edit.set_enter_send(self.config.get("behavior.enter_to_send", True))
        self.chat._refresh_profile_badge()
        self.chat._update_status()
        self._apply_character_ui()
        self.history.max_sessions = max(5, int(self.config.get("storage.max_history", 30)))
        self.history.enabled = bool(self.config.get("storage.save_history", True))
        if self.history.enabled:
            self.history.save()
        self._apply_chat_flags()
        self.config.ensure_dirs()
        self.chat.show_toast("设置已经生效")
        if old_character != self.character:
            self.pet.show_bubble(f"换我陪你啦，我是{self.character_name}。", "右键 → 设置里随时可以换回来", duration=4200)
        self._update_tray_tip()

    def _clear_history(self):
        self.history.clear()
        self.history.new_session()
        self.chat.session = self.history.current()
        self.chat._render_session()

    def _config_changed(self):
        self.chat._refresh_profile_badge()
        self.chat._update_status()
        self._update_tray_tip()

    # ------------------------------------------------------------------
    def toggle_pet(self):
        if self.pet.isVisible():
            self.pet.bubble.hide()
            self.pet.hide()
        else:
            self.pet.show()
            self.pet.set_state("greet", 1200)

    def hide_pet(self):
        self._hide_task_bubbles()
        self.pet.bubble.hide()
        self.pet.hide()
        self.tray.showMessage(f"{self.character_name}躲起来了", "点托盘图标就能叫出来。", QSystemTrayIcon.MessageIcon.Information, 2500)

    # ------------------------------------------------------------------
    def toggle_focus(self):
        if self._focus_timer:
            self._stop_focus(cancelled=True)
        else:
            self.start_focus()

    def start_focus(self):
        if self._focus_timer:
            self.pet.show_bubble("已经在专注啦。", "做完这一轮再开始新的吧", duration=2600)
            return
        minutes = max(5, int(self.config.get("behavior.focus_minutes", 25) or 25))
        self._focus_deadline = time.time() + minutes * 60
        t = QTimer(self)
        t.setSingleShot(True)
        t.timeout.connect(self._focus_done)
        t.start(minutes * 60 * 1000)
        self._focus_timer = t
        tick = QTimer(self)
        tick.setInterval(30000)
        tick.timeout.connect(self._update_tray_tip)
        tick.start()
        self._focus_tick = tick
        self.pet.set_state("tool", 2600)
        self.pet.show_bubble(f"{minutes} 分钟，我陪你。", "先把手边这一件事做好", duration=4200)
        self._play_chime()
        self._build_tray_menu()
        self._update_tray_tip()

    def _focus_done(self):
        self._stop_focus(cancelled=False)
        self.pet.set_state("success", 2800)
        self.pet.show_bubble("时间到啦，休息一下。", "站起来走两步，喝口水吧", duration=8000)
        self._play_chime()
        if self.config.get("behavior.notify", True):
            self.tray.showMessage("专注完成", "该休息一下啦。", QSystemTrayIcon.MessageIcon.Information, 6000)

    def _stop_focus(self, cancelled: bool):
        if self._focus_timer:
            self._focus_timer.stop()
            self._focus_timer.deleteLater()
        if self._focus_tick:
            self._focus_tick.stop()
            self._focus_tick.deleteLater()
        self._focus_timer = None
        self._focus_tick = None
        self._focus_deadline = 0.0
        if cancelled:
            self.pet.show_bubble("好，那先休息。", "想专注的时候再叫我", duration=2400)
        self._build_tray_menu()
        self._update_tray_tip()

    # ------------------------------------------------------------------
    def quit(self):
        if self._quitting:
            return
        self._quitting = True
        try:
            self.config.set("appearance.position", [self.pet.x(), self.pet.y()])
            self.config.set("ui.last_session", self.chat.session.get("id"))
            self.config.save()
            self.chat.shutdown()
            self.agent.shutdown()
            self._hide_task_bubbles()
            self.history.save()
            self.pet.close()
            self.tray.hide()
        except Exception:
            pass
        self.app.quit()
