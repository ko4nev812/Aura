"""Фаза 1: аудиодвижок (ТЗ §3.5) — состояния, гейн, фейды, кроссфейд."""

from __future__ import annotations

import pytest

from aura.audio.engine import AudioEngine, gain_from_percent, percent_from_gain
from aura.audio.state import PlayerState


def test_gain_mapping_is_perceptual():
    assert gain_from_percent(0) == 0.0
    assert gain_from_percent(100) == pytest.approx(1.0)
    assert gain_from_percent(50) == pytest.approx(0.25)
    assert gain_from_percent(150) == pytest.approx(1.0)  # клампим сверху
    assert percent_from_gain(gain_from_percent(70)) == 70
    assert percent_from_gain(gain_from_percent(0)) >= 0


def test_state_labels_and_activity():
    assert PlayerState.PLAYING.label == "Играет"
    assert PlayerState.IDLE.label == "Остановлен"
    assert PlayerState.PLAYING.is_active and not PlayerState.PAUSED.is_active


def test_engine_initial_state(qapp):  # noqa: ARG001
    engine = AudioEngine()
    assert engine.state is PlayerState.IDLE
    assert engine.duration_ms == 0
    assert engine.position_ms == 0
    assert engine.volume_percent() == percent_from_gain(engine.volume)
    engine.deleteLater()


def test_load_missing_file_emits_error(qapp):  # noqa: ARG001
    engine = AudioEngine()
    errors: list[str] = []
    engine.error.connect(errors.append)
    assert engine.load("C:/definitely/not/here.wav") is False
    assert errors and "не найден" in errors[0]
    assert engine.state is PlayerState.IDLE
    engine.deleteLater()


def test_load_real_file_reaches_playing(qapp, tmp_path):  # noqa: ARG001
    from .helpers import wait_until, write_tone

    tone = write_tone(tmp_path / "beep.wav", seconds=5.0)
    engine = AudioEngine()
    errors: list[str] = []
    engine.error.connect(errors.append)

    assert engine.load(tone) is True
    assert wait_until(lambda: engine.duration_ms > 0), "медиа не загрузилось"
    assert errors == []
    assert wait_until(lambda: engine.state is PlayerState.PLAYING)
    assert engine.duration_ms == pytest.approx(5000, abs=400)
    assert wait_until(lambda: engine.active_gain > 0.95), "fade-in не доехал до максимума"

    engine.pause()
    assert engine.state is PlayerState.PAUSED
    engine.play()
    assert engine.state is PlayerState.PLAYING
    assert wait_until(lambda: engine.position_ms > 0), "позиция не движется"
    engine.stop()
    assert engine.state is PlayerState.IDLE


def test_volume_and_duck_compose(qapp):  # noqa: ARG001
    engine = AudioEngine()
    engine.set_volume(0.5)
    engine.set_duck(0.4)
    assert engine.volume == pytest.approx(0.5)
    assert engine.duck == pytest.approx(0.4)
    assert engine.effective_gain == pytest.approx(0.2)
    engine.set_duck(1.0)
    assert engine.effective_gain == pytest.approx(0.5)
    engine.set_muted(True)
    assert engine.effective_gain == 0.0
    engine.set_muted(False)
    assert engine.toggle_mute() is True
    assert engine.volume_percent() == percent_from_gain(0.5)
    engine.deleteLater()


def test_ramp_animates_in_steps(qapp):  # noqa: ARG001
    from PyQt6.QtTest import QTest

    engine = AudioEngine()
    engine.set_gain(1.0, fade_ms=300)
    assert engine.ramp_running is True

    observed: list[float] = []
    for _ in range(60):
        observed.append(engine.active_gain)
        if not engine.ramp_running:
            break
        QTest.qWait(25)
    observed.append(engine.active_gain)

    assert observed[0] < 1.0
    assert engine.active_gain == pytest.approx(1.0)
    assert len({round(value, 2) for value in observed}) >= 4, "гейн должен меняться плавно"
    engine.deleteLater()


def test_fade_out_calls_back(qapp):  # noqa: ARG001
    from .helpers import wait_until

    engine = AudioEngine()
    engine.set_gain(1.0)
    assert engine.active_gain == pytest.approx(1.0)

    done: list[bool] = []
    engine.fade_out(300, on_done=lambda: done.append(True))
    assert wait_until(lambda: bool(done))
    assert engine.active_gain == pytest.approx(0.0, abs=0.01)
    engine.deleteLater()


def test_crossfade_swaps_slots(qapp, tmp_path):  # noqa: ARG001
    from .helpers import wait_until, write_tone

    first = write_tone(tmp_path / "a.wav", seconds=6.0, freq=300)
    second = write_tone(tmp_path / "b.wav", seconds=6.0, freq=600)
    engine = AudioEngine()
    assert engine.load(first) is True
    assert wait_until(lambda: engine.active_gain > 0.95)

    assert engine.crossfade_to(second, 300) is True
    assert wait_until(lambda: engine.source_path.endswith("b.wav"))
    assert engine.state is PlayerState.PLAYING
    assert engine.active_gain == pytest.approx(1.0, abs=0.02)
    assert engine.standby_gain == pytest.approx(0.0)

    engine.stop()
    engine.deleteLater()


def test_mark_silence_state(qapp):  # noqa: ARG001
    engine = AudioEngine()
    seen = []
    engine.state_changed.connect(seen.append)
    engine.mark_silence()
    assert seen == [PlayerState.SILENCE]
    engine.mark_silence()  # без дубля сигнала
    assert len(seen) == 1
    engine.deleteLater()


def test_apply_settings_and_adjust_volume(qapp):  # noqa: ARG001
    engine = AudioEngine()
    engine.apply_settings(30, 250)
    assert engine.volume == pytest.approx(gain_from_percent(30))
    assert engine._fade_in_ms == 250
    percent = engine.adjust_volume(+20)
    assert percent > 30
    engine.deleteLater()
