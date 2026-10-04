"""Фаза 1: плейлист-контроллер и состояния плеера (ТЗ §3.5, §3.6) на подставном движке."""

from __future__ import annotations

import random
from pathlib import Path

import pytest
from PyQt6.QtCore import QObject, pyqtSignal

from aura.audio.state import PlayerState
from aura.config import Settings
from aura.core.playlist import PlaylistController
from aura.library.manager import TrackInfo
from aura.scheduler.base import Context, RandomScheduler, SchedulerFactory, time_of_day


class FakeEngine(QObject):
    """Записывающая замена AudioEngine: те же сигналы, без реального декодирования."""

    state_changed = pyqtSignal(object)
    position_changed = pyqtSignal(int, int)
    track_finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__()
        self._state = PlayerState.IDLE
        self._duration_ms = 0
        self.loaded: list[str] = []
        self.crossfaded: list[tuple[str, int]] = []
        self.faded: list[int] = []
        self.volume = 0.5
        self.duck = 1.0
        self.muted = False
        self.fade_in_ms = 0
        self.silence_marks = 0
        self.seek_fractions: list[float] = []

    # -------------------------------------------------------- наблюдаемое состояние
    @property
    def state(self) -> PlayerState:
        return self._state

    @property
    def position_ms(self) -> int:
        return 0

    @property
    def duration_ms(self) -> int:
        return self._duration_ms

    @property
    def source_path(self) -> str:
        return self.loaded[-1] if self.loaded else ""

    def volume_percent(self) -> int:
        return int(self.volume * 100)

    def is_playing(self) -> bool:
        return self._state is PlayerState.PLAYING

    # ------------------------------------------------------------------ транспорт
    def _set(self, state: PlayerState) -> None:
        self._state = state
        self.state_changed.emit(state)

    def load(self, path, *, autoplay: bool = True, fade_in_ms=None) -> bool:  # noqa: ANN001, ARG001
        if not Path(str(path)).is_file():
            self.error.emit(f"Файл не найден: {path}")
            self._set(PlayerState.IDLE)
            return False
        self.loaded.append(str(path))
        self._duration_ms = 60_000
        self._set(PlayerState.LOADING)
        if autoplay:
            self._set(PlayerState.PLAYING)
        return True

    def play(self) -> None:
        if self.loaded:
            self._set(PlayerState.PLAYING)

    def pause(self) -> None:
        self._set(PlayerState.PAUSED)

    def stop(self) -> None:
        self._duration_ms = 0
        self._set(PlayerState.IDLE)

    def toggle(self) -> None:
        self.pause() if self._state is PlayerState.PLAYING else self.play()

    def seek_fraction(self, fraction: float) -> None:
        self.seek_fractions.append(fraction)
        self.position_changed.emit(int(self._duration_ms * fraction), self._duration_ms)

    # ---------------------------------------------------------------------- гейн
    def set_volume(self, gain: float) -> None:
        self.volume = gain

    def apply_settings(self, volume_percent: int, fade_ms: int) -> None:
        self.volume = volume_percent / 100.0
        self.fade_in_ms = fade_ms

    def set_duck(self, factor: float) -> None:
        self.duck = factor

    def ducked(self, active: bool, factor: float) -> None:
        self.set_duck(factor if active else 1.0)

    def set_muted(self, muted: bool) -> None:
        self.muted = muted

    def toggle_mute(self) -> bool:
        self.muted = not self.muted
        return self.muted

    def set_fade_in_ms(self, ms: int) -> None:
        self.fade_in_ms = ms

    def mark_silence(self) -> None:
        self.silence_marks += 1
        self._set(PlayerState.SILENCE)

    def fade_out(self, fade_ms: int, on_done=None) -> None:  # noqa: ANN001
        self.faded.append(fade_ms)
        if on_done is not None:
            on_done()

    def set_gain(self, gain: float, *, fade_ms: int = 0) -> None:  # noqa: ARG002
        self.volume = gain

    def crossfade_to(self, path, fade_ms: int) -> bool:  # noqa: ANN001
        if not Path(str(path)).is_file():
            return False
        self.crossfaded.append((str(path), fade_ms))
        return self.load(path)

    def finish(self) -> None:
        """Эмуляция EndOfMedia."""
        self.track_finished.emit()


@pytest.fixture
def engine(qapp) -> FakeEngine:  # noqa: ARG001 - нужен экземпляр QApplication
    return FakeEngine()


@pytest.fixture
def library_with_music(service, music_dir):  # noqa: ARG001
    service.import_directory(music_dir)
    return service.library


def make_controller(service, engine, settings: Settings | None = None) -> PlaylistController:
    return PlaylistController(
        library=service.library,
        engine=engine,
        scheduler=RandomScheduler(rng=random.Random(11)),
        settings=settings or service.settings,
        context_provider=lambda: Context(time_of_day="day"),
    )


def test_start_plays_enabled_track(service, library_with_music, engine):
    controller = make_controller(service, engine)
    assert controller.start() is True
    assert controller.current is not None
    assert engine.state is PlayerState.PLAYING

    snapshot = controller.snapshot()
    assert snapshot.track.id == controller.current.id
    assert snapshot.state is PlayerState.PLAYING
    assert snapshot.duration_ms == 60_000
    assert snapshot.context_key == "-|unknown|day"
    assert controller.session_id


def test_empty_library_does_not_start(service, engine):
    controller = make_controller(service, engine)
    assert controller.start() is False
    assert controller.current is None
    assert engine.state is PlayerState.IDLE


def test_disabled_packs_are_not_selected(service, library_with_music, engine):
    for pack in service.library.list_packs():
        service.library.set_pack_enabled(pack.id, False)
    controller = make_controller(service, engine)
    assert controller.candidates() == []
    assert controller.play_next() is False
    assert controller.current is None


def test_next_avoids_repeating_and_previous_walks_back(service, library_with_music, engine):
    controller = make_controller(service, engine)
    controller.auto_advance = False
    controller.start()
    first = controller.current.id

    visited = {first}
    for _ in range(6):
        assert controller.play_next() is True
        visited.add(controller.current.id)
    assert len(visited) >= 2  # за 6 шагов вышло больше одного трека

    last = controller.current.id
    assert controller.play_previous() is True
    assert controller.current.id != last
    assert controller.play_next() is True


def test_single_track_loops_instead_of_stopping(service, engine, tmp_path):
    from .helpers import write_tone

    folder = tmp_path / "solo"
    write_tone(folder / "only.wav")
    service.import_directory(folder, pack_name="Solo")
    controller = make_controller(service, engine)
    controller.start()
    only = controller.current.id
    assert controller.play_next() is True
    assert controller.current.id == only
    assert controller.play_previous() is True


def test_queue_and_pack_filter(service, library_with_music, engine):
    tracks = service.library.list_tracks()
    controller = make_controller(service, engine)
    controller.start()
    playing = controller.current.id
    controller.enqueue(tracks[0])
    assert tracks[0].id in {t.id for t in controller.upcoming}
    assert playing not in {t.id for t in controller.upcoming}

    pack_id = tracks[0].pack_id
    controller.set_pack_filter(pack_id)
    assert controller.pack_filter == pack_id

    other = service.library.create_pack("Second").id
    moved = service.library.move_track(tracks[1].id, other)
    assert moved.pack_id == other
    assert all(t.pack_id == pack_id for t in controller.candidates())
    controller.set_pack_filter(None)
    assert any(t.pack_id == other for t in controller.candidates())


def test_track_finished_advances(service, library_with_music, engine):
    controller = make_controller(service, engine)
    controller.start()
    first = controller.current.id
    engine.finish()
    assert controller.current.id != first
    assert engine.state is PlayerState.PLAYING


def test_auto_advance_off_holds_after_finish(service, library_with_music, engine):
    controller = make_controller(service, engine)
    controller.start()
    first = controller.current.id
    controller.auto_advance = False
    engine.finish()
    assert controller.current.id == first
    assert controller.play_next() is True


def test_silence_gap_plays_ambient_bed_then_resumes(service, music_dir, engine, settings, tmp_path):
    from .helpers import write_tone

    ambient = tmp_path / "bed"
    write_tone(ambient / "rain_bed.wav")
    settings.silence_min_sec = 3
    settings.silence_max_sec = 4
    service.import_directory(music_dir)
    service.import_directory(ambient, pack_name=settings.ambient_pack_name)

    controller = make_controller(service, engine, settings)
    controller.start()
    music_pack = service.library.find_pack_by_name("music")
    assert controller.current.pack_id == music_pack.id

    engine.finish()
    assert engine.silence_marks == 1
    assert "rain_bed" in Path(controller.current.file_path).name
    assert controller.queued_tracks == []

    ambient_id = controller.current.id
    engine.finish()  # «атмосфера» кончилась раньше интервала — ждём, не скачем
    assert controller.current.id == ambient_id
    assert engine.silence_marks == 1

    controller.skip_silence()
    assert controller.current.id != ambient_id
    assert controller.current.pack_id == music_pack.id
    assert ambient_id not in {t.id for t in controller.candidates()}


def test_silence_without_ambient_pack_stays_quiet(service, library_with_music, engine):
    from aura.config import Settings as S

    settings = service.settings.model_copy(update={"silence_min_sec": 6, "silence_max_sec": 6})
    controller = make_controller(service, engine, settings)
    controller.start()
    engine.finish()
    assert engine.silence_marks == 1
    assert engine.state is PlayerState.SILENCE
    assert controller.current is not None
    assert controller.skip_silence() is True
    assert engine.state is PlayerState.PLAYING


def test_crossfade_used_only_when_playing(service, library_with_music, engine, settings):
    settings.crossfade_enabled = True
    settings.crossfade_sec = 2.5
    settings.silence_min_sec = 0
    settings.silence_max_sec = 0
    controller = make_controller(service, engine, settings)
    assert controller.play_next() is True
    assert engine.crossfaded == []  # сначала не с чего кроссфейдить

    assert controller.play_next() is True
    assert len(engine.crossfaded) == 1
    assert engine.crossfaded[0][1] == 2500


def test_missing_file_is_not_becoming_current(service, music_dir, engine):
    service.import_directory(music_dir)
    track = service.library.list_tracks()[0]
    Path(track.file_path).unlink()
    service.library.mark_missing_files()
    stale = service.library.get_track(track.id)
    assert stale is not None and stale.exists is False
    controller = make_controller(service, engine)
    assert controller.play(stale) is False
    assert engine.loaded == []
    assert controller.current is None


def test_transport_controls_forward_to_engine(service, library_with_music, engine):
    controller = make_controller(service, engine)
    controller.start()
    controller.pause()
    assert engine.state is PlayerState.PAUSED
    controller.toggle_playback()
    assert engine.state is PlayerState.PLAYING
    positions = []
    engine.position_changed.connect(lambda pos, total: positions.append((pos, total)))
    controller.seek_to_fraction(0.5)
    assert positions[-1] == (30_000, 60_000)


def test_stop_clears_track_and_autoplay(service, library_with_music, engine):
    controller = make_controller(service, engine)
    controller.start()
    changes = []
    controller.track_changed.connect(lambda track: changes.append(track))
    controller.stop()
    assert controller.current is None
    assert engine.state is PlayerState.IDLE
    assert changes[-1] is None
    engine.finish()
    assert controller.current is None


def test_hot_swap_scheduler_and_settings(service, engine):
    controller = make_controller(service, engine)
    assert controller.scheduler_name == "random"
    controller.set_scheduler(SchedulerFactory.create("thompson"))
    assert controller.scheduler_name == "random"  # фолбэк для нереализованных бэкендов
    unknown = SchedulerFactory.create("does_not_exist")
    assert isinstance(unknown, RandomScheduler)


def test_track_id_lookup_and_errors(service, library_with_music, engine):
    controller = make_controller(service, engine)
    track = service.library.list_tracks()[0]
    assert controller.play_track_id(track.id) is True
    assert controller.current.id == track.id
    errors = []
    controller.error.connect(errors.append)
    assert controller.play_track_id("no-such-id") is False
    assert errors and "не найден" in errors[0]


def test_time_of_day_and_context_key():
    assert time_of_day(7) == "morning"
    assert time_of_day(13) == "day"
    assert time_of_day(19) == "evening"
    assert time_of_day(3) == "night"
    context = Context(process_name="code.exe", activity_level="high", time_of_day="day")
    assert context.key == "code.exe|high|day"
    assert Context.from_clock(23).time_of_day == "night"


def test_random_scheduler_penalises_repeats():
    def track(index: int) -> TrackInfo:
        return TrackInfo(
            id=f"id-{index}",
            pack_id="p",
            title=f"track {index}",
            artist=None,
            file_path=f"C:/t{index}.mp3",
            duration_sec=10,
            format="mp3",
            enabled=True,
        )

    scheduler = RandomScheduler(history=4, rng=random.Random(7))
    candidates = [track(index) for index in range(6)]
    assert scheduler.select_next(Context(), [], []) is None

    picks = [scheduler.select_next(Context(), candidates, ["id-0"] * 8).id for _ in range(6)]
    assert "id-0" not in picks
    assert len(set(picks)) > 1

    solo = scheduler.select_next(Context(), [candidates[0]], [candidates[0].id])
    assert solo.id == "id-0"
