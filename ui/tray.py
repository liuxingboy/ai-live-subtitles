"""Tray controls use the same icon and source registry as the application."""
from PySide6.QtCore import Signal
from PySide6.QtGui import QActionGroup
from PySide6.QtWidgets import QMenu, QSystemTrayIcon
from audio.sources import SOURCE_REGISTRY
from app.preferences import SPEED_MODES, TARGET_LANGUAGES, discover_hotwords
from pathlib import Path


class SubtitleTray(QSystemTrayIcon):
    source_selected = Signal(str)
    speed_selected = Signal(str)
    language_selected = Signal(str)
    hotwords_toggled = Signal(bool)
    hotword_selected = Signal(str)
    lock_requested = Signal()
    exit_requested = Signal()

    def __init__(self, icon, selected='chrome', parent=None):
        super().__init__(icon, parent)
        self.menu = QMenu()
        self.source_menu = self.menu.addMenu('声源选择')
        self.group = QActionGroup(self)
        self.group.setExclusive(True)
        self.actions = {}
        for key, (label, _) in SOURCE_REGISTRY.items():
            action = self.source_menu.addAction(label)
            action.setCheckable(True)
            action.setData(key)
            self.group.addAction(action)
            self.actions[key] = action
        self.group.triggered.connect(lambda action: self.source_selected.emit(action.data()))
        self.speed_menu = self.menu.addMenu('速度与准度')
        self.speed_group = QActionGroup(self)
        self.speed_group.setExclusive(True)
        self.speed_actions = {}
        for key, label in SPEED_MODES.items():
            action = self.speed_menu.addAction(label)
            action.setCheckable(True)
            action.setData(key)
            self.speed_group.addAction(action)
            self.speed_actions[key] = action
        self.speed_group.triggered.connect(lambda action: self.speed_selected.emit(action.data()))
        self.speed_actions['fast'].setToolTip('更早断句，译文可能更碎或更频繁修订')
        self.speed_actions['normal'].setChecked(True)
        self.language_menu = self.menu.addMenu('目标语言')
        self.language_group = QActionGroup(self)
        self.language_group.setExclusive(True)
        self.language_actions = {}
        for key, label in TARGET_LANGUAGES.items():
            action = self.language_menu.addAction(label)
            action.setCheckable(True)
            action.setData(key)
            self.language_group.addAction(action)
            self.language_actions[key] = action
        self.language_group.triggered.connect(lambda action: self.language_selected.emit(action.data()))
        self.language_actions['zh'].setChecked(True)
        self.hotword_menu = self.menu.addMenu('热词')
        self.hotword_enable_action = self.hotword_menu.addAction('启用热词')
        self.hotword_enable_action.setCheckable(True)
        self.hotword_enable_action.triggered.connect(lambda checked: self.hotwords_toggled.emit(checked))
        self.hotword_note = self.hotword_menu.addAction('仅适用于中文目标；当前暂不应用')
        self.hotword_note.setEnabled(False)
        self.hotword_note.setVisible(False)
        self.hotword_menu.addSeparator()
        self.hotword_group = QActionGroup(self)
        self.hotword_group.setExclusive(True)
        self.hotword_actions = {}
        for path, label in discover_hotwords().items():
            self._add_hotword_action(path, label)
        self.hotword_group.triggered.connect(lambda action: self.hotword_selected.emit(action.data()))
        self.menu.addSeparator()
        self.lock_action = self.menu.addAction('锁定并点击穿透')
        self.lock_action.setCheckable(True)
        self.lock_action.setEnabled(False)
        self.lock_action.triggered.connect(lambda checked: self.lock_requested.emit())
        self.menu.addAction('退出', self.exit_requested.emit)
        self.setContextMenu(self.menu)
        self.select(selected)

    def select(self, key):
        self.actions[key].setChecked(True)
        self._update_tooltip()

    def select_speed(self, key):
        self.speed_actions[key].setChecked(True)
        self._update_tooltip()

    def select_language(self, key):
        self.language_actions[key].setChecked(True)
        self._update_tooltip()

    def _add_hotword_action(self, path, label):
        action = self.hotword_menu.addAction(label)
        action.setCheckable(True)
        action.setData(path)
        self.hotword_group.addAction(action)
        self.hotword_actions[path] = action

    def set_hotwords_state(self, enabled, path, *, applicable=True, available=True):
        key = str(Path(path).resolve())
        if key not in self.hotword_actions and Path(path).is_file():
            self._add_hotword_action(key, Path(path).stem)
        action = self.hotword_actions.get(key)
        if action:
            action.setChecked(True)
        self.hotword_enable_action.setChecked(enabled)
        self.hotword_enable_action.setEnabled(available and applicable and bool(self.hotword_actions))
        self.hotword_note.setVisible(not applicable)
        for action in self.hotword_actions.values():
            action.setEnabled(available and applicable)

    def set_lock_state(self, locked, enabled, shortcut_prefix):
        self.lock_action.setChecked(locked)
        self.lock_action.setEnabled(enabled)
        self.lock_action.setText(f'锁定并点击穿透\t{shortcut_prefix}+L')
        self.lock_action.setToolTip('勾选后固定字幕窗口并让鼠标穿透；再次点击解除')

    def _update_tooltip(self):
        source = self.group.checkedAction().text()
        speed = self.speed_group.checkedAction().text()
        language = self.language_group.checkedAction().text()
        self.setToolTip(f'实时双语字幕 · {source} · {speed} · {language}')

    def shutdown(self):
        self.hide()
        self.menu.close()
        self.menu.deleteLater()
