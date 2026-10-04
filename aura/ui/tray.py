"""Трей-иконка с меню и индикатором состояния (ТЗ §4.1, §4.2 базовый слой).

Отдельное окно, приклеенное к панели задач (ITaskbarList3) и hover-панель с
кнопками — фаза 4; здесь тот же набор действий живёт в меню трея.
"""

from __future__ import annotations

from PyQt6.QtCore import QObject
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon, QWidget

from ..audio.state import PlayerState
from ..core.service import AuraService
from ..library.manager import TrackInfo
from ..log import get_logger
from .theme import badge_icon, orb_icon, state_color, transport_icon

log = get_logger("tray")

TOOLTIP_LINES = 2


class TrayController(QObject):
    """System-tray presence: icon, tooltip, context menu, activation handling."""

    def __init__(self, service: AuraService, window: QWidget | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.service = service
        self.window = window
        self.icon = QSystemTrayIcon(badge_icon("idle", 32), parent or window)

        self.menu = QMenu()
        self.now_action = self.menu.addAction("Aura — ничего не играет")
        self.now_action.setEnabled(False)
        self.menu.addSeparator()

        self.play_action = QAction(transport_icon("play", 18), "Play / Pause", self.menu)
        self.play_action.triggered.connect(lambda: self.service.playlist.toggle_playback())
        self.menu.addAction(self.play_action)

        self.next_action = QAction(transport_icon("next", 18), "Следующий трек", self.menu)
        self.next_action.triggered.connect(lambda: self.service.playlist.play_next())
        self.menu.addAction(self.next_action)

        self.prev_action = QAction(transport_icon("prev", 18), "Предыдущий трек", self.menu)
        self.prev_action.triggered.connect(lambda: self.service.playlist.play_previous())
        self.menu.addAction(self.prev_action)

        self.menu.addSeparator()
        self.like_action = QAction(transport_icon("like", 18), "Лайк (Ctrl+Alt+L)", self.menu)
        self.like_action.triggered.connect(lambda: self._rate(1))
        self.menu.addAction(self.like_action)
        self.dislike_action = QAction(transport_icon("dislike", 18), "Дизлайк (Ctrl+Alt+D)", self.menu)
        self.dislike_action.triggered.connect(lambda: self._rate(-1))
        self.menu.addAction(self.dislike_action)

        self.menu.addSeparator()
        self.packs_menu = QMenu("Играть пак", self.menu)
        self.packs_menu.aboutToShow.connect(self._rebuild_pack_filter)
        self.menu.addMenu(self.packs_menu)

        self.mute_action = QAction("Без звука", self.menu)
        self.mute_action.setCheckable(True)
        self.mute_action.toggled.connect(self.service.engine.set_muted)
        self.menu.addAction(self.mute_action)

        self.autoplay_action = QAction("Автоплей", self.menu)
        self.autoplay_action.setCheckable(True)
        self.autoplay_action.setChecked(True)
        self.autoplay_action.toggled.connect(self._set_autoplay)
        self.menu.addAction(self.autoplay_action)

        self.menu.addSeparator()
        show_action = QAction(orb_icon(18), "Открыть Aura", self.menu)
        show_action.triggered.connect(self.show_window)
        self.menu.addAction(show_action)
        quit_action = QAction("Выход", self.menu)
        quit_action.triggered.connect(self.quit)
        self.menu.addAction(quit_action)

        self.icon.setContextMenu(self.menu)
        self.icon.activated.connect(self._on_activated)
        service.playlist.track_changed.connect(self._on_track)
        service.playlist.state_changed.connect(self._on_state)
        self._on_state(service.engine.state)

    # ------------------------------------------------------------------ public

    def show(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            log.warning("системный трей недоступен — иконка не показана")
            return
        self.icon.show()

    def hide(self) -> None:
        self.icon.hide()

    def notify(self, title: str, message: str, ms: int = 4000) -> None:
        if QSystemTrayIcon.supportsMessages():
            self.icon.showMessage(title, message, QSystemTrayIcon.MessageIcon.Information, ms)

    # ----------------------------------------------------------------- handlers

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.show_window()

    def show_window(self) -> None:
        if self.window is None:
            return
        if self.window.isVisible() and not self.window.isMinimized():
            self.window.hide()
            return
        self.window.showNormal()
        self.window.raise_()
        self.window.activateWindow()

    def quit(self) -> None:
        self.service.shutdown()
        self.icon.hide()
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _set_autoplay(self, enabled: bool) -> None:
        self.service.playlist.auto_advance = enabled
        if enabled and self.service.playlist.current is None:
            self.service.playlist.start()

    def _rate(self, rating: int) -> None:
        track = self.service.playlist.current
        if track is None:
            return
        snapshot = self.service.playlist.snapshot()
        self.service.record_feedback(
            track.id,
            rating,
            context={
                "time_of_day": self.service.current_context().time_of_day,
                "activity_level": "unknown",
            },
            position_sec=snapshot.position_ms / 1000.0,
            session_id=self.service.playlist.session_id,
        )

    def _rebuild_pack_filter(self) -> None:
        self.packs_menu.clear()
        playlist = self.service.playlist
        current_filter = playlist.pack_filter
        all_action = self.packs_menu.addAction("Все включённые паки")
        all_action.setCheckable(True)
        all_action.setChecked(current_filter is None)
        all_action.triggered.connect(lambda: playlist.set_pack_filter(None))
        self.packs_menu.addSeparator()
        for pack in self.service.library.list_packs(with_tracks=False):
            action = self.packs_menu.addAction(("● " if pack.id == current_filter else "   ") + pack.name)
            action.setToolTip(
                f"{pack.enabled_count} из {pack.track_count} треков включено"
                + ("" if pack.enabled else " · пак выключен")
            )
            action.triggered.connect(lambda _checked=False, pid=pack.id: playlist.set_pack_filter(pid))

    # ------------------------------------------------------------------ visuals

    def _on_track(self, track: TrackInfo | None) -> None:
        if track is None:
            self.now_action.setText("Aura — ничего не играет")
        else:
            self.now_action.setText(f"{track.display_title}")
        self._refresh_tooltip()

    def _on_state(self, state: PlayerState) -> None:
        snapshot = self.service.playlist.snapshot()
        key = "paused" if state is PlayerState.PAUSED else state.value
        if snapshot.ducked and state is PlayerState.PLAYING:
            key = "ducked"
        self.icon.setIcon(badge_icon(state_color(key), 32))
        self.play_action.setIcon(transport_icon("pause" if state is PlayerState.PLAYING else "play", 18))
        self.play_action.setText("Пауза" if state is PlayerState.PLAYING else "Играть")
        self.mute_action.setChecked(self.service.engine.muted)
        has_track = self.service.playlist.current is not None
        self.like_action.setEnabled(has_track)
        self.dislike_action.setEnabled(has_track)
        self._refresh_tooltip()

    def _refresh_tooltip(self) -> None:
        snapshot = self.service.playlist.snapshot()
        lines = ["Aura"]
        if snapshot.track is not None:
            lines.insert(0, f"{snapshot.track.display_title}")
            pack = self.service.library.get_pack(snapshot.track.pack_id)
            if pack:
                lines.append(f"пак: {pack.name}")
        lines.append(f"состояние: {snapshot.state.label} · {snapshot.volume_percent}%")
        lines.append("двойной клик — открыть окно")
        self.icon.setToolTip("\n".join(lines[: TOOLTIP_LINES + 3]))
