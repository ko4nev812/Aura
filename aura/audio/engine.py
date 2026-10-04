"""Audio engine backend (ТЗ §3.5).

The spec names ``sounddevice`` + ``pydub``/``ffmpeg``; on this Python 3.12 +
PyQt6 stack we drive ``QtMultimedia`` instead: it decodes MP3/FLAC/OGG/Opus/
M4A/WAV through the platform codecs without an external ffmpeg dependency and
reports events on the Qt loop. The exposed behaviour (player states, fades,
crossfade, ducking) matches the spec and the backend stays swappable.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PyQt6.QtCore import QObject, QTimer, QUrl, pyqtSignal
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer

from ..log import get_logger
from .state import PlayerState

log = get_logger("audio")

TICK_MS = 250
RAMP_STEP_MS = 50
_EPSILON = 1e-4


def gain_from_percent(percent: float) -> float:
    """Map a 0..100 UI value onto a perceptually linear 0..1 gain."""
    return _clamp(percent / 100.0) ** 2


def percent_from_gain(gain: float) -> int:
    return int(round(max(_clamp(gain), 1e-9) ** 0.5 * 100))


class _Ramp(QObject):
    """Animates a float over ``duration_ms`` on a Qt timer, then calls ``on_done``."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.setInterval(RAMP_STEP_MS)
        self._timer.timeout.connect(self._step)
        self._start = 0.0
        self._stop = 1.0
        self._duration = 0
        self._elapsed = 0
        self._apply: Callable[[float], None] = lambda _value: None
        self._on_done: Callable[[], None] | None = None

    @property
    def running(self) -> bool:
        return self._timer.isActive()

    def start(
        self,
        *,
        start: float,
        stop: float,
        duration_ms: int,
        apply: Callable[[float], None],
        on_done: Callable[[], None] | None = None,
    ) -> None:
        self.cancel()
        self._start, self._stop = start, stop
        self._duration = max(0, int(duration_ms))
        self._elapsed = 0
        self._apply = apply
        self._on_done = on_done
        if self._duration <= 0 or abs(stop - start) < _EPSILON:
            apply(stop)
            self._finish()
            return
        apply(start)
        self._timer.start()

    def cancel(self) -> None:
        self._timer.stop()
        self._on_done = None

    def _step(self) -> None:
        self._elapsed += RAMP_STEP_MS
        fraction = min(1.0, self._elapsed / max(1, self._duration))
        eased = fraction * fraction * (3 - 2 * fraction)  # smoothstep
        self._apply(self._start + (self._stop - self._start) * eased)
        if fraction >= 1.0:
            self._finish()

    def _finish(self) -> None:
        self._timer.stop()
        on_done, self._on_done = self._on_done, None
        if on_done is not None:
            on_done()


class AudioEngine(QObject):
    """Two-slot crossfading engine; only one slot is audible at a time.

    Signals
    -------
    state_changed(PlayerState)
    position_changed(position_ms, total_ms)
    track_finished()
    error(str)
    """

    state_changed = pyqtSignal(object)
    position_changed = pyqtSignal(int, int)
    track_finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._players: list[QMediaPlayer] = []
        self._outputs: list[QAudioOutput] = []
        for _ in range(2):
            output = QAudioOutput(self)
            player = QMediaPlayer(self)
            player.setAudioOutput(output)
            player.mediaStatusChanged.connect(self._on_media_status)
            player.playbackStateChanged.connect(self._on_playback_state)
            player.errorOccurred.connect(self._on_error)
            output.setVolume(0.0)
            self._players.append(player)
            self._outputs.append(output)

        self._active = 0
        self._gains = [0.0, 0.0]
        self._volume = gain_from_percent(70)
        self._duck = 1.0
        self._muted = False
        self._state = PlayerState.IDLE
        self._duration_ms = 0
        self._fade_in_ms = 400
        self._ramp = _Ramp(self)
        self._tick = QTimer(self)
        self._tick.setInterval(TICK_MS)
        self._tick.timeout.connect(self._emit_position)

    # ------------------------------------------------------------------ state

    @property
    def state(self) -> PlayerState:
        return self._state

    @property
    def position_ms(self) -> int:
        return int(self._players[self._active].position())

    @property
    def duration_ms(self) -> int:
        return int(self._duration_ms or self._players[self._active].duration() or 0)

    @property
    def volume(self) -> float:
        return self._volume

    @property
    def duck(self) -> float:
        return self._duck

    @property
    def source_path(self) -> str:
        return self._players[self._active].source().toLocalFile()

    # --------------------------------------------------------------- transport

    def load(
        self,
        path: str | Path,
        *,
        autoplay: bool = True,
        fade_in_ms: int | None = None,
    ) -> bool:
        """Replace the current source. ``False`` when the file is unreadable."""
        resolved = Path(path)
        if not resolved.is_file():
            self.error.emit(f"Файл не найден: {resolved}")
            self._set_state(PlayerState.IDLE)
            return False

        self._ramp.cancel()
        self._stop_slot(1 - self._active)
        self._stop_slot(self._active)
        self._duration_ms = 0
        self._set_state(PlayerState.LOADING)

        player = self._players[self._active]
        player.setSource(QUrl.fromLocalFile(str(resolved)))
        self._assign_gain(self._active, 0.0)
        if autoplay:
            player.play()
            self._fade_in(fade_in_ms)
        return True

    def play(self) -> None:
        player = self._players[self._active]
        if player.source().isEmpty():
            return
        was_silent = self._gains[self._active] <= _EPSILON
        if was_silent:
            self._assign_gain(self._active, 0.0)
        player.play()
        self._set_state(PlayerState.PLAYING)
        if was_silent:
            self._fade_in()

    def pause(self) -> None:
        self._players[self._active].pause()
        self._set_state(PlayerState.PAUSED)

    def toggle(self) -> None:
        if self.state is PlayerState.PLAYING:
            self.pause()
        else:
            self.play()

    def stop(self) -> None:
        self._ramp.cancel()
        for slot in range(2):
            self._stop_slot(slot)
        self._gains = [0.0, 0.0]
        self._duration_ms = 0
        self._set_state(PlayerState.IDLE)

    def seek_fraction(self, fraction: float) -> None:
        total = self.duration_ms
        if not total:
            return
        self._players[self._active].setPosition(int(total * _clamp(fraction)))
        self._emit_position()

    # ------------------------------------------------------------------ gains

    def set_volume(self, gain: float) -> None:
        self._volume = _clamp(gain)
        self._refresh_outputs()

    def adjust_volume(self, percent: float) -> int:
        self.set_volume(self._volume + percent / 100.0)
        return percent_from_gain(self._volume)

    def set_duck(self, factor: float) -> None:
        """Gain multiplier applied while foreign audio is active (1.0 = none)."""
        self._duck = _clamp(factor)
        self._refresh_outputs()

    def ducked(self, active: bool, factor: float) -> None:
        self.set_duck(factor if active else 1.0)

    def set_muted(self, muted: bool) -> None:
        """Silence output without losing the volume slider position."""
        self._muted = bool(muted)
        self._refresh_outputs()

    def toggle_mute(self) -> bool:
        self.set_muted(not self._muted)
        return self._muted

    @property
    def muted(self) -> bool:
        return self._muted

    def set_fade_in_ms(self, ms: int) -> None:
        self._fade_in_ms = max(0, int(ms))

    def apply_settings(self, volume_percent: int, fade_ms: int) -> None:
        """Push volume/fade prefs from ``Settings`` without importing config."""
        self.set_volume(gain_from_percent(volume_percent))
        self.set_fade_in_ms(fade_ms)

    def is_playing(self) -> bool:
        return self._state is PlayerState.PLAYING

    def fade_out(self, fade_ms: int, on_done: Callable[[], None] | None = None) -> None:
        """Ramp the audible slot to silence, then run ``on_done``."""
        slot = self._active
        self._ramp.start(
            start=max(self._gains[slot], _EPSILON),
            stop=0.0,
            duration_ms=fade_ms,
            apply=lambda value, target=slot: self._assign_gain(target, value),
            on_done=on_done,
        )

    def mark_silence(self) -> None:
        """Announce the silence gap between tracks (ТЗ §3.5 ``SILENCE``)."""
        self._set_state(PlayerState.SILENCE)

    def set_gain(self, gain: float, *, fade_ms: int = 0) -> None:
        slot = self._active
        target = _clamp(gain)
        if fade_ms > 0 and abs(self._gains[slot] - target) > _EPSILON:
            self._ramp.start(
                start=self._gains[slot],
                stop=target,
                duration_ms=fade_ms,
                apply=lambda value, dest=slot: self._assign_gain(dest, value),
            )
        else:
            self._ramp.cancel()
            self._assign_gain(slot, target)

    def _fade_in(self, fade_ms: int | None = None) -> None:
        duration = self._fade_in_ms if fade_ms is None else fade_ms
        self.set_gain(1.0, fade_ms=duration)

    def _assign_gain(self, slot: int, value: float) -> None:
        self._gains[slot] = value
        self._outputs[slot].setVolume(_clamp(value) * self._effective())

    def _effective(self) -> float:
        if self._muted:
            return 0.0
        return self._volume * self._duck

    def _refresh_outputs(self) -> None:
        for slot, gain in enumerate(self._gains):
            self._outputs[slot].setVolume(gain * self._effective())

    def volume_percent(self) -> int:
        return percent_from_gain(self._volume)

    @property
    def effective_gain(self) -> float:
        """Master volume × duck × mute, без учёта флейв-гейна слота."""
        return self._effective()

    @property
    def active_gain(self) -> float:
        return self._gains[self._active]

    @property
    def standby_gain(self) -> float:
        return self._gains[1 - self._active]

    @property
    def ramp_running(self) -> bool:
        return self._ramp.running

    # -------------------------------------------------------------- crossfade

    def crossfade_to(self, path: str | Path, fade_ms: int) -> bool:
        """Start ``path`` on the standby slot and swap slots over ``fade_ms``."""
        resolved = Path(path)
        if not resolved.is_file():
            self.error.emit(f"Файл не найден: {resolved}")
            return False
        if fade_ms <= 0:
            return self.load(resolved)

        incoming = 1 - self._active
        outgoing = self._active
        self._set_state(PlayerState.FADING_OUT)
        self._ramp.cancel()
        self._stop_slot(incoming)

        standby = self._players[incoming]
        standby.setSource(QUrl.fromLocalFile(str(resolved)))
        standby.play()

        def finalize() -> None:
            self._stop_slot(outgoing)
            self._active = incoming
            self._duration_ms = int(self._players[incoming].duration() or 0)
            self._set_state(PlayerState.PLAYING)
            self._tick.start()
            self.position_changed.emit(int(self._players[incoming].position()), self.duration_ms)

        self._ramp.start(
            start=max(self._gains[outgoing], _EPSILON),
            stop=0.0,
            duration_ms=fade_ms,
            apply=lambda value: self._apply_pair(incoming, outgoing, value),
            on_done=finalize,
        )
        return True

    def _apply_pair(self, incoming: int, outgoing: int, outgoing_gain: float) -> None:
        self._assign_gain(outgoing, outgoing_gain)
        self._assign_gain(incoming, _clamp(1.0 - outgoing_gain))

    # -------------------------------------------------------------- internals

    def _stop_slot(self, slot: int) -> None:
        player = self._players[slot]
        try:
            player.stop()
        except RuntimeError:  # pragma: no cover - wrapped C++ object deleted
            pass
        self._gains[slot] = 0.0
        self._outputs[slot].setVolume(0.0)

    def _set_state(self, state: PlayerState) -> None:
        if state is self._state:
            return
        self._state = state
        log.debug("state -> %s", state.value)
        self.state_changed.emit(state)
        if state in (PlayerState.IDLE, PlayerState.PAUSED, PlayerState.SILENCE):
            self._tick.stop()

    def _emit_position(self) -> None:
        player = self._players[self._active]
        total = int(player.duration() or self._duration_ms or 0)
        if total:
            self._duration_ms = total
        self.position_changed.emit(int(player.position()), total)

    def _on_media_status(self, status: QMediaPlayer.MediaStatus) -> None:
        if status == QMediaPlayer.MediaStatus.LoadedMedia:
            duration = int(self._players[self._active].duration() or 0)
            if duration:
                self._duration_ms = duration
        elif status == QMediaPlayer.MediaStatus.EndOfMedia:
            self._tick.stop()
            log.debug("end of media")
            self.track_finished.emit()

    def _on_playback_state(self, qt_state: QMediaPlayer.PlaybackState) -> None:
        if qt_state == QMediaPlayer.PlaybackState.PlayingState:
            if self._state in (PlayerState.LOADING, PlayerState.PAUSED, PlayerState.IDLE):
                self._set_state(PlayerState.PLAYING)
                self._tick.start()
        elif qt_state == QMediaPlayer.PlaybackState.PausedState:
            if self._state is PlayerState.PLAYING:
                self._set_state(PlayerState.PAUSED)
        elif qt_state == QMediaPlayer.PlaybackState.StoppedState:
            if self._state in (PlayerState.PLAYING, PlayerState.LOADING):
                self._set_state(PlayerState.IDLE)

    def _on_error(self, _error: QMediaPlayer.Error, text: str) -> None:
        message = text or "Не удалось воспроизвести файл"
        log.warning("player error: %s", message)
        self._tick.stop()
        self.error.emit(message)
        self._set_state(PlayerState.IDLE)


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))
