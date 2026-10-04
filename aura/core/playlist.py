"""Playlist controller: queue, history, silence gaps, crossfade (ТЗ §3.5)."""

from __future__ import annotations

import datetime as dt
import random
import uuid
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from ..audio.engine import AudioEngine, gain_from_percent
from ..audio.state import PlayerState
from ..config import Settings
from ..library.manager import LibraryManager, TrackInfo
from ..log import get_logger
from ..scheduler.base import Context, SchedulerBackend

log = get_logger("playlist")

RECENT_LIMIT = 12
QUEUE_PREVIEW = 5


@dataclass(slots=True)
class PlaybackSnapshot:
    track: TrackInfo | None
    state: PlayerState
    position_ms: int
    duration_ms: int
    volume_percent: int
    context_key: str
    ducked: bool


class PlaylistController(QObject):
    """Decides what plays next and drives the engine; owns no widgets."""

    track_changed = pyqtSignal(object)  # TrackInfo | None
    state_changed = pyqtSignal(object)  # PlayerState
    position_changed = pyqtSignal(int, int)
    error = pyqtSignal(str)
    context_changed = pyqtSignal(object)  # Context

    def __init__(
        self,
        library: LibraryManager,
        engine: AudioEngine,
        scheduler: SchedulerBackend,
        settings: Settings,
        *,
        context_provider=None,
        rng: random.Random | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.library = library
        self.engine = engine
        self.scheduler = scheduler
        self.settings = settings
        self._context_provider = context_provider or (lambda: Context.from_clock(_hour()))
        self._rng = rng or random.Random()

        self.current: TrackInfo | None = None
        self.history: deque[str] = deque(maxlen=RECENT_LIMIT)
        self._upcoming: list[TrackInfo] = []
        self._pack_filter: str | None = None
        self._auto = False
        self._session_id = str(uuid.uuid4())

        self._silence_timer = QTimer(self)
        self._silence_timer.setSingleShot(True)
        self._silence_timer.timeout.connect(self._on_silence_over)

        engine.state_changed.connect(self.state_changed.emit)
        engine.position_changed.connect(self.position_changed.emit)
        engine.track_finished.connect(self._on_track_finished)
        engine.error.connect(self.error.emit)
        engine.set_volume(gain_from_percent(settings.volume))
        engine.set_fade_in_ms(settings.fade_ms)

        self._context_timer = QTimer(self)
        self._context_timer.setInterval(5000)
        self._context_timer.timeout.connect(self.refresh_context)
        self._context_timer.start()

    # ----------------------------------------------------------------- context

    @property
    def context(self) -> Context:
        return self._context_provider()

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def auto_advance(self) -> bool:
        return self._auto

    @auto_advance.setter
    def auto_advance(self, enabled: bool) -> None:
        """Отключает автопереход к следующему треку (кнопка «Автоплей»)."""
        self._auto = bool(enabled)
        if not enabled:
            self._silence_timer.stop()

    @property
    def scheduler_name(self) -> str:
        return self.scheduler.name

    def set_scheduler(self, scheduler: SchedulerBackend) -> None:
        """Hot-swap the selection backend (ТЗ §3.6 interface switch)."""
        self.scheduler = scheduler

    def refresh_context(self) -> None:
        self.context_changed.emit(self.context)

    # --------------------------------------------------------------- transport

    def start(self) -> bool:
        """Enable autoplay and start the first track."""
        self._auto = True
        if self.engine.state is PlayerState.PLAYING and self.current is not None:
            return True
        return self.play_next()

    def stop(self) -> None:
        self._auto = False
        self._silence_timer.stop()
        self.engine.stop()
        self.current = None
        self.track_changed.emit(None)
        self.state_changed.emit(self.engine.state)

    def toggle_playback(self) -> None:
        if self.engine.state is PlayerState.PLAYING:
            self.engine.pause()
            return
        if self.engine.state is PlayerState.PAUSED and self.current is not None:
            self.engine.play()
            return
        if self.current is not None and self.engine.state is PlayerState.IDLE:
            self.play(self.current)
            return
        self.start()

    def pause(self) -> None:
        self.engine.pause()

    def resume(self) -> None:
        if self.current is None:
            self.start()
        else:
            self.engine.play()

    def play(self, track: TrackInfo) -> bool:
        """Play ``track`` right now (with a fade-out of the previous one)."""
        self._silence_timer.stop()
        previous_gain_silent = self.engine.state is not PlayerState.PLAYING
        fade = 0 if previous_gain_silent else self.settings.fade_ms

        def load_new() -> None:
            if self.engine.load(track.file_path, fade_in_ms=self.settings.fade_ms):
                self._begin(track)

        if fade > 0:
            self.engine.fade_out(fade, on_done=load_new)
        else:
            load_new()
        return track.exists

    def play_track_id(self, track_id: str) -> bool:
        track = self.library.get_track(track_id)
        if track is None:
            self.error.emit(f"Трек не найден: {track_id}")
            return False
        return self.play(track)

    def play_next(self) -> bool:
        track = self._pick()
        if track is None:
            log.info("нечего играть: библиотека пуста или всё выключено")
            self.stop()
            return False

        previous = self.current
        use_crossfade = (
            previous is not None
            and self.engine.state is PlayerState.PLAYING
            and self.settings.crossfade_enabled
            and self.settings.crossfade_sec > 0
        )
        if previous is not None:
            self.history.append(previous.id)

        if use_crossfade and self.engine.crossfade_to(
            track.file_path, int(self.settings.crossfade_sec * 1000)
        ):
            self._begin(track)
            return True
        return self.play(track)

    def play_previous(self) -> bool:
        """Go back through what has been played (or restart the current track)."""
        if self.current is None:
            return self.play_next()

        previous_id = self._pop_previous_from_history()
        if previous_id is None:
            return self.play(self.current)

        track = self.library.get_track(previous_id)
        if track is None or not track.exists:
            log.debug("history entry %s is gone", previous_id)
            return self.play_previous()

        if self.current is not None:
            self._upcoming.insert(0, self.current)
        return self.play(track)

    def enqueue(self, track: TrackInfo) -> None:
        """Поставить трек в конец пользовательской очереди."""
        self._upcoming.append(track)

    def play_many(self, tracks: Sequence[TrackInfo], *, replace: bool = True) -> bool:
        """Сыграть список по порядку: первый — сразу, остальные — в очередь."""
        playable = [track for track in tracks if track.exists]
        if not playable:
            self.error.emit("Нет доступных файлов для воспроизведения")
            return False
        first, rest = playable[0], playable[1:]
        self._upcoming = list(rest) if replace else self._upcoming + list(rest)
        return self.play(first)

    def set_pack_filter(self, pack_id: str | None) -> None:
        self._pack_filter = pack_id or None
        if self._pack_filter:
            self._upcoming = [t for t in self._upcoming if t.pack_id == self._pack_filter]

    @property
    def pack_filter(self) -> str | None:
        return self._pack_filter

    @property
    def upcoming(self) -> list[TrackInfo]:
        queued = list(self._upcoming)
        if len(queued) < QUEUE_PREVIEW:
            for _ in range(QUEUE_PREVIEW - len(queued)):
                candidate = self._peek_next(exclude=set(queued) | self._playing_ids())
                if candidate is None:
                    break
                queued.append(candidate)
        return queued[:QUEUE_PREVIEW]

    def snapshot(self) -> PlaybackSnapshot:
        return PlaybackSnapshot(
            track=self.current,
            state=self.engine.state,
            position_ms=self.engine.position_ms,
            duration_ms=self.engine.duration_ms,
            volume_percent=self.engine.volume_percent(),
            context_key=self.context.key,
            ducked=self.engine.duck < 1.0,
        )

    @property
    def queued_tracks(self) -> list[TrackInfo]:
        """Треки, явно поставленные в очередь (без предпросмотра выбора)."""
        return list(self._upcoming)

    def skip_silence(self) -> bool:
        """Закончить интервал тишины и играть следующий трек сразу."""
        self._silence_timer.stop()
        return self.play_next()

    def seek_to_fraction(self, fraction: float) -> None:
        self.engine.seek_fraction(fraction)

    # --------------------------------------------------------------- silence

    def _silence_range(self) -> tuple[int, int]:
        low, high = self.settings.silence_min_sec, self.settings.silence_max_sec
        if high <= 0 and low <= 0:
            return (0, 0)
        low = max(0, low)
        high = max(low, high)
        return (low, high)

    def _on_track_finished(self) -> None:
        if not self._auto:
            self.state_changed.emit(self.engine.state)
            return
        if self._silence_timer.isActive():
            # «атмосферный» трек закончился раньше паузы — ждём окончания интервала
            return
        low, high = self._silence_range()
        if high > 0:
            self._enter_silence(low, high)
        else:
            self.play_next()

    def _enter_silence(self, low: int, high: int) -> None:
        """Fade out, play an ambient bed (если есть), затем продолжить после тишины."""
        ambient = self._ambient_track()
        seconds = low if high <= low else self._rng.uniform(low, high)

        def after_fade() -> None:
            if ambient is None or not self._silence_timer.isActive():
                return
            if self.engine.load(ambient.file_path, fade_in_ms=self.settings.fade_ms):
                self._begin(ambient)

        self.engine.mark_silence()
        self.state_changed.emit(PlayerState.SILENCE)
        self._silence_timer.start(max(250, int(seconds * 1000)))
        if self.settings.fade_ms > 0 and not self._is_ambient_track(self.current):
            self.engine.fade_out(self.settings.fade_ms, on_done=after_fade)
        else:
            after_fade()

    def _is_ambient_track(self, track: TrackInfo | None) -> bool:
        if track is None:
            return False
        pack = self.library.get_pack(track.pack_id)
        return bool(pack and self._is_ambient_pack(pack.name))

    def _on_silence_over(self) -> None:
        if self._auto:
            self.play_next()

    def _ambient_track(self) -> TrackInfo | None:
        pack = self.library.find_pack_by_name(self.settings.ambient_pack_name)
        if pack is None or not pack.enabled:
            return None
        playable = [t for t in pack.tracks if t.enabled and t.exists]
        return self._rng.choice(playable) if playable else None

    def _is_ambient_pack(self, name: str) -> bool:
        return name.strip().lower() == str(self.settings.ambient_pack_name).strip().lower()

    # -------------------------------------------------------------- selection

    def candidates(self) -> list[TrackInfo]:
        tracks: list[TrackInfo] = []
        for pack in self.library.list_packs():
            if not pack.enabled or self._is_ambient_pack(pack.name):
                continue
            if self._pack_filter and pack.id != self._pack_filter:
                continue
            tracks.extend(t for t in pack.tracks if t.enabled and t.exists)
        return tracks

    def _pick(self) -> TrackInfo | None:
        if self._upcoming:
            return self._upcoming.pop(0)
        return self._select(exclude=self._playing_ids(), fallback=True)

    def _peek_next(self, exclude: set[str]) -> TrackInfo | None:
        return self._select(exclude=exclude, fallback=False)
    def _select(self, *, exclude: set[str], fallback: bool = True) -> TrackInfo | None:
        """Scheduler/order pick; ``fallback`` разрешает повтор, если всё исключено.

        Фолбэк нужен для маленьких библиотек: если включён один трек, «следующим»
        становится он же, а не тишина. Для предпросмотра очереди фолбэк выключен,
        иначе в списке повторялся бы один и тот же трек.
        """
        pool = self.candidates()
        if not pool:
            return None
        candidates = [track for track in pool if track.id not in exclude]
        if not candidates:
            if not fallback:
                return None
            candidates = pool
        if self.settings.shuffle:
            return self.scheduler.select_next(self.context, candidates, list(self.history))
        return self._next_in_order(candidates)

    def _playing_ids(self) -> set[str]:
        ids = {t.id for t in self._upcoming}
        if self.current is not None:
            ids.add(self.current.id)
        return ids

    def _next_in_order(self, candidates: list[TrackInfo]) -> TrackInfo | None:
        ordered = sorted(candidates, key=lambda t: (t.pack_id, t.title.lower()))
        if not ordered:
            return None
        if self.current is None:
            return ordered[0]
        keys = [(t.pack_id, t.title.lower()) for t in ordered]
        try:
            index = keys.index((self.current.pack_id, self.current.title.lower()))
        except ValueError:
            return ordered[0]
        return ordered[(index + 1) % len(ordered)]

    def _pop_previous_from_history(self) -> str | None:
        """Last finished track id, keeping the history consistent for redo."""
        while self.history:
            candidate = self.history.pop()
            if self.current is not None and candidate == self.current.id:
                continue
            return candidate
        return None

    def _begin(self, track: TrackInfo) -> None:
        self._upcoming = [t for t in self._upcoming if t.id != track.id]
        if not self.history or self.history[-1] != track.id:
            self.history.append(track.id)
        self.current = track
        self.track_changed.emit(track)
        self.state_changed.emit(self.engine.state)
        log.info("играем: %s", track.display_title)


def _hour() -> int:
    return dt.datetime.now().hour


