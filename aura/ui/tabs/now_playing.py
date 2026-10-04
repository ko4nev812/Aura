"""«Сейчас играет» — orb, транспорт, прогресс, лайки, контекст (ТЗ §4.1.1)."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from ...audio.engine import gain_from_percent
from ...audio.state import PlayerState
from ...core.service import AuraService
from ...library.manager import TrackInfo
from ...scheduler.base import Context
from ..theme import transport_icon
from ..widgets import Badge, PulseOrb, format_duration

STATE_DOTS = {
    PlayerState.PLAYING: "#4ade80",
    PlayerState.LOADING: "#818cf8",
    PlayerState.FADING_OUT: "#818cf8",
    PlayerState.PAUSED: "#facc15",
    PlayerState.SILENCE: "#eab308",
    PlayerState.IDLE: "#94a3b8",
}


class NowPlayingTab(QWidget):
    def __init__(self, service: AuraService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.service = service
        self.playlist = service.playlist
        self._seeking = False

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 18)
        root.setSpacing(16)

        hero = QHBoxLayout()
        hero.setSpacing(24)
        self.orb = PulseOrb(170)
        hero.addWidget(self.orb, 0, Qt.AlignmentFlag.AlignTop)

        info = QVBoxLayout()
        info.setSpacing(6)

        header = QHBoxLayout()
        header.setSpacing(10)
        self.dot = QLabel()
        self.dot.setFixedSize(11, 11)
        header.addWidget(self.dot, 0, Qt.AlignmentFlag.AlignVCenter)
        self.state_label = QLabel(PlayerState.IDLE.label)
        self.state_label.setObjectName("meta")
        header.addWidget(self.state_label, 0, Qt.AlignmentFlag.AlignVCenter)
        header.addStretch()
        info.addLayout(header)

        self.title_label = QLabel("Ничего не играет")
        self.title_label.setObjectName("title")
        self.title_label.setWordWrap(False)
        info.addWidget(self.title_label)

        self.artist_label = QLabel("Импортируйте музыку во вкладке «Библиотека»")
        self.artist_label.setObjectName("subtitle")
        info.addWidget(self.artist_label)

        self.pack_label = QLabel("—")
        self.pack_label.setObjectName("meta")
        info.addWidget(self.pack_label)

        self.analysis_label = QLabel("")
        self.analysis_label.setObjectName("meta")
        self.analysis_label.setWordWrap(True)
        info.addWidget(self.analysis_label)

        badges = QHBoxLayout()
        badges.setSpacing(8)
        self.context_badge = Badge("контекст: —")
        self.scheduler_badge = Badge(f"scheduler: {service.scheduler_name}")
        self.duck_badge = Badge("тишина")
        self.duck_badge.hide()
        badges.addWidget(self.context_badge)
        badges.addWidget(self.scheduler_badge)
        badges.addWidget(self.duck_badge)
        badges.addStretch()
        info.addLayout(badges)

        queue_box = QVBoxLayout()
        queue_box.setSpacing(2)
        queue_title = QLabel("Дальше:")
        queue_title.setObjectName("meta")
        self.queue_label = QLabel("—")
        self.queue_label.setObjectName("subtitle")
        self.queue_label.setWordWrap(True)
        self.queue_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        queue_box.addWidget(queue_title)
        queue_box.addWidget(self.queue_label)
        info.addLayout(queue_box)
        info.addStretch()

        hero.addLayout(info, 1)
        root.addLayout(hero, 1)

        progress = QVBoxLayout()
        progress.setSpacing(2)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 0)
        self.slider.setSingleStep(1000)
        self.slider.setCursor(Qt.CursorShape.PointingHandCursor)
        self.slider.sliderPressed.connect(lambda: setattr(self, "_seeking", True))
        self.slider.sliderReleased.connect(self._commit_seek)
        self.slider.sliderMoved.connect(self._preview_seek)
        times = QHBoxLayout()
        self.position_label = QLabel("0:00")
        self.position_label.setObjectName("meta")
        self.duration_label = QLabel("0:00")
        self.duration_label.setObjectName("meta")
        times.addWidget(self.position_label)
        times.addStretch()
        times.addWidget(self.duration_label)
        progress.addWidget(self.slider)
        progress.addLayout(times)
        root.addLayout(progress)

        root.addWidget(self._build_controls())

        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        root.addWidget(divider)

        self.context_line = QLabel("Активно: — · activity: unknown")
        self.context_line.setObjectName("hint")
        root.addWidget(self.context_line)

        playlist = self.playlist
        playlist.track_changed.connect(lambda _track: self.refresh())
        playlist.state_changed.connect(lambda _state: self.refresh())
        playlist.position_changed.connect(self._on_position)
        playlist.context_changed.connect(self._on_context)
        playlist.error.connect(self._on_error)

        self.refresh()
        self._on_context(playlist.context)

    # ------------------------------------------------------------------ build

    def _build_controls(self) -> QWidget:
        bar = QWidget()
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(9)

        layout.addWidget(self._transport("prev", "Предыдущий", self.playlist.play_previous))
        self.play_button = self._transport("play", "Play / Pause (Ctrl+Alt+P)", self.playlist.toggle_playback)
        layout.addWidget(self.play_button)
        layout.addWidget(self._transport("next", "Следующий (Ctrl+Alt+Right)", self.playlist.play_next))
        layout.addSpacing(14)
        self.like_button = self._transport("like", "Лайк (Ctrl+Alt+L)", lambda: self.rate(1))
        self.dislike_button = self._transport("dislike", "Дизлайк (Ctrl+Alt+D)", lambda: self.rate(-1))
        for button in (self.like_button, self.dislike_button):
            button.setCheckable(True)
        layout.addWidget(self.like_button)
        layout.addWidget(self.dislike_button)
        layout.addStretch()

        self.autoplay_box = QCheckBox("Автоплей")
        self.autoplay_box.setChecked(self.playlist.auto_advance)
        self.autoplay_box.setToolTip("Автоматически переходить к следующему треку")
        self.autoplay_box.toggled.connect(self._set_autoplay)
        layout.addWidget(self.autoplay_box)

        self.mute_button = self._transport("volume", "Выключить звук", self._toggle_mute)
        self.mute_button.setCheckable(True)
        layout.addWidget(self.mute_button)

        layout.addWidget(QLabel("Громкость"))
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setFixedWidth(128)
        self.volume.setValue(self.service.settings.volume)
        self.volume.valueChanged.connect(self._set_volume)
        layout.addWidget(self.volume)
        return bar

    def _transport(self, kind: str, tip: str, handler) -> QPushButton:
        button = QPushButton(transport_icon(kind, 22), "")
        button.setObjectName("transport")
        button.setToolTip(tip)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(handler)
        return button

    # ----------------------------------------------------------------- refresh

    def refresh(self) -> None:
        snapshot = self.playlist.snapshot()
        track = snapshot.track
        state = snapshot.state

        self.state_label.setText(state.label)
        self.dot.setStyleSheet(f"background: {STATE_DOTS.get(state, '#94a3b8')}; border-radius: 6px;")
        self.play_button.setIcon(
            transport_icon("pause" if state is PlayerState.PLAYING else "play", 22)
        )
        self.orb.set_active(state is PlayerState.PLAYING)
        self.duck_badge.setVisible(snapshot.ducked)
        self.scheduler_badge.setText(f"scheduler: {self.playlist.scheduler_name}")
        self.mute_button.setChecked(self.playlist.engine.muted)

        if track is None:
            self.title_label.setText("Ничего не играет")
            self.artist_label.setText("Импортируйте музыку во вкладке «Библиотека»")
            self.pack_label.setText("—")
            self.analysis_label.setText("")
            self._set_feedback_buttons(None)
        else:
            self.title_label.setText(track.title)
            self.artist_label.setText(track.artist or "неизвестный исполнитель")
            self.pack_label.setText(f"пак: {self._pack_name(track.pack_id)} · {format_duration(track.duration_sec)} · {track.format.upper() or '?'}")
            self.analysis_label.setText(self._analysis_text(track))
            self._set_feedback_buttons(track.id)

        self.queue_label.setText(self._queue_text())
        self._on_position(snapshot.position_ms, snapshot.duration_ms)

    def _queue_text(self) -> str:
        if self.playlist.current is None and not self.playlist.queued_tracks:
            return "— (включите воспроизведение)"
        upcoming = self.playlist.upcoming[:4]
        if not upcoming:
            return "— (нет включённых треков)"
        return "\n".join(f"{index + 1}. {track.display_title}" for index, track in enumerate(upcoming))

    def _pack_name(self, pack_id: str) -> str:
        pack = self.service.library.get_pack(pack_id)
        return pack.name if pack else "—"

    def _analysis_text(self, track: TrackInfo) -> str:
        if not track.analyzed:
            return "анализ: ещё не выполнен (фаза 2)"
        chunks: list[str] = []
        if track.bpm:
            chunks.append(f"{int(round(track.bpm))} BPM")
        if track.energy is not None:
            chunks.append(f"energy {track.energy:.2f}")
        if track.valence is not None:
            chunks.append(f"valence {track.valence:.2f}")
        if track.mood_tags:
            chunks.append(" · ".join(track.mood_tags[:4]))
        return "анализ: " + (" | ".join(chunks) if chunks else "—")

    def _set_feedback_buttons(self, track_id: str | None) -> None:
        rating = self.service.library.latest_feedback(track_id) if track_id else None
        for button, value in ((self.like_button, 1), (self.dislike_button, -1)):
            button.setEnabled(track_id is not None)
            button.blockSignals(True)
            button.setChecked(rating == value)
            button.blockSignals(False)

    # ------------------------------------------------------------------ events

    def rate(self, rating: int) -> None:
        track = self.playlist.current
        if track is None:
            return
        snapshot = self.playlist.snapshot()
        self.service.record_feedback(
            track.id,
            rating,
            context=track_context(self.playlist.context),
            position_sec=snapshot.position_ms / 1000.0,
            session_id=self.playlist.session_id,
        )
        self._set_feedback_buttons(track.id)

    def _on_position(self, position_ms: int, total_ms: int) -> None:
        if self._seeking:
            return
        self.slider.blockSignals(True)
        self.slider.setMaximum(max(0, int(total_ms)))
        self.slider.setValue(min(int(position_ms), int(total_ms)))
        self.slider.blockSignals(False)
        self.position_label.setText(format_duration(position_ms / 1000))
        self.duration_label.setText(format_duration(total_ms / 1000))
        self.orb.set_progress(position_ms / total_ms if total_ms else 0.0)

    def _preview_seek(self, value: int) -> None:
        total = self.slider.maximum()
        if total:
            self.position_label.setText(format_duration(value / 1000))
            self.orb.set_progress(value / total)

    def _commit_seek(self) -> None:
        self._seeking = False
        total = self.slider.maximum()
        if total:
            self.playlist.seek_to_fraction(self.slider.value() / total)

    def _set_volume(self, percent: int) -> None:
        self.service.settings.volume = percent
        self.playlist.engine.set_volume(gain_from_percent(percent))

    def _toggle_mute(self) -> None:
        self.playlist.engine.set_muted(self.mute_button.isChecked())

    def _set_autoplay(self, enabled: bool) -> None:
        self.playlist.auto_advance = enabled
        if enabled and self.playlist.current is None:
            self.playlist.start()

    def _on_context(self, context: Context) -> None:
        self.context_badge.setText(f"контекст: {context.time_of_day} · {context.activity_level}")
        self.context_line.setText(
            f"Активно: {context.process_name or 'неизвестно (монитор — фаза 3)'} · "
            f"activity: {context.activity_level} · {context.time_of_day}"
        )

    def _on_error(self, message: str) -> None:
        self.state_label.setText(f"ошибка: {message}")
        self.state_label.setStyleSheet("color: #f87171;")


def track_context(context: Context) -> dict[str, object]:
    """Снапшот контекста для фидбека — обезличенный (ТЗ §8)."""
    return {
        "activity_level": context.activity_level,
        "time_of_day": context.time_of_day,
        "foreign_audio": context.foreign_audio,
    }
