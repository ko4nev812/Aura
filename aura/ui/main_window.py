"""Главное окно Aura: вкладки «Сейчас играет», «Библиотека», «Правила», «Аналитика», «Настройки»."""

from __future__ import annotations

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QCloseEvent, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QLabel,
    QMainWindow,
    QTabWidget,
    QWidget,
)

from ..audio.state import PlayerState
from ..core.service import AuraService
from .tabs.analytics_tab import AnalyticsTab
from .tabs.library_tab import LibraryTab
from .tabs.now_playing import NowPlayingTab
from .tabs.rules_tab import RulesTab
from .tabs.settings_tab import SettingsTab
from .theme import orb_icon

SHORTCUTS: tuple[tuple[str, str], ...] = (
    ("Ctrl+Alt+P", "toggle_playback"),
    ("Ctrl+Alt+Right", "play_next"),
    ("Ctrl+Alt+Left", "play_previous"),
    ("Ctrl+Alt+L", "like"),
    ("Ctrl+Alt+D", "dislike"),
    ("Ctrl+Alt+M", "mute"),
    ("Ctrl+I", "import"),
    ("Ctrl+F", "search"),
)


class MainWindow(QMainWindow):
    def __init__(self, service: AuraService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.service = service
        service.window = self
        self.setWindowTitle("Aura")
        self.setWindowIcon(orb_icon(64))
        self.resize(1060, 700)
        self.setMinimumSize(880, 560)
        self._quit_requested = False
        self._hint_shown = False

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setIconSize(_icon_size())
        self.now_tab = NowPlayingTab(service)
        self.library_tab = LibraryTab(service)
        self.rules_tab = RulesTab(service)
        self.analytics_tab = AnalyticsTab(service)
        self.settings_tab = SettingsTab(service)

        self.tabs.addTab(self.now_tab, orb_icon(20), "Сейчас играет")
        self.tabs.addTab(self.library_tab, orb_icon(20), "Библиотека")
        self.tabs.addTab(self.rules_tab, orb_icon(20), "Правила")
        self.tabs.addTab(self.analytics_tab, orb_icon(20), "Аналитика")
        self.tabs.addTab(self.settings_tab, orb_icon(20), "Настройки")
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.setCentralWidget(self.tabs)

        self.status_message = QLabel("Готов")
        self.statusBar().addWidget(self.status_message, 1)
        self.status_indicator = QLabel("●")
        self.statusBar().addPermanentWidget(self.status_indicator)

        playlist = service.playlist
        playlist.track_changed.connect(self._on_track)
        playlist.state_changed.connect(self._on_state)
        playlist.error.connect(lambda text: self.show_message(f"Ошибка: {text}", warning=True))

        self._install_shortcuts()
        self._on_state(playlist.engine.state)

    # --------------------------------------------------------------- shortcuts

    def _install_shortcuts(self) -> None:
        for sequence, action in SHORTCUTS:
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
            shortcut.activated.connect(lambda name=action: self.trigger(name))

    def trigger(self, action: str) -> None:
        """Global actions, shared with the tray menu."""
        playlist = self.service.playlist
        if action == "toggle_playback":
            playlist.toggle_playback()
        elif action == "play_next":
            playlist.play_next()
        elif action == "play_previous":
            playlist.play_previous()
        elif action == "like":
            self.now_tab.rate(1)
        elif action == "dislike":
            self.now_tab.rate(-1)
        elif action == "mute":
            self.now_tab.mute_button.click()
        elif action == "import":
            self.tabs.setCurrentWidget(self.library_tab)
            self.library_tab.import_folder()
        elif action == "search":
            self.tabs.setCurrentWidget(self.library_tab)
            self.library_tab.focus_search()
        elif action == "quit":
            self.quit()
        elif action == "show":
            self.show_normal()

    # ------------------------------------------------------------------ status

    def show_message(self, text: str, *, warning: bool = False) -> None:
        self.status_message.setText(text)
        self.status_message.setStyleSheet("color: #f87171;" if warning else "")

    def _on_track(self, track) -> None:  # noqa: ANN001 - TrackInfo | None
        if track is None:
            self.setWindowTitle("Aura")
            self.show_message("Остановлено")
            return
        self.setWindowTitle(f"Aura — {track.display_title}")
        self.show_message(f"Играем: {track.display_title}")

    def _on_state(self, state: PlayerState) -> None:
        from .tabs.now_playing import STATE_DOTS

        color = STATE_DOTS.get(state, "#94a3b8")
        self.status_indicator.setText("●")
        self.status_indicator.setStyleSheet(f"color: {color}; font-size: 14px; padding-right: 8px;")
        if state is PlayerState.PAUSED:
            self.show_message("Пауза")
        elif state is PlayerState.SILENCE:
            self.show_message("Тишина между треками")

    def _on_tab_changed(self, index: int) -> None:
        widget = self.tabs.widget(index)
        if widget is self.library_tab:
            self.library_tab.reload(keep_selection=False)
        elif widget is self.analytics_tab:
            self.analytics_tab.reload()
        elif widget is self.settings_tab:
            self.settings_tab.load_values()

    # ---------------------------------------------------------------- lifecycle

    def show_normal(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def quit(self) -> None:
        self._quit_requested = True
        self.close()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt API
        tray = self.service.tray
        if not self._quit_requested and self.service.settings.close_to_tray and tray is not None:
            event.ignore()
            self.hide()
            self.show_message("Aura работает в трее — двойной клик по значку открывает окно")
            if not self._hint_shown:
                self._hint_shown = True
                tray.notify("Aura свёрнута в трей", "Плеер продолжает играть.")
            return
        self._quit_requested = True
        super().closeEvent(event)

    @property
    def quit_requested(self) -> bool:
        return self._quit_requested


def _icon_size() -> QSize:
    return QSize(18, 18)
