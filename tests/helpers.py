"""Helpers for tests: real (tiny) generated audio files."""

from __future__ import annotations

import math
import wave
from collections.abc import Callable
from pathlib import Path

from PyQt6.QtCore import QDeadlineTimer


def write_tone(path: str | Path, seconds: float = 2.0, freq: float = 440.0, sample_rate: int = 8000) -> Path:
    """Write a mono 16-bit WAV so that importing/probing has a real file."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    frames = max(1, int(seconds * sample_rate))
    payload = bytearray()
    for index in range(frames):
        value = int(12000 * math.sin(2 * math.pi * freq * index / sample_rate))
        payload += value.to_bytes(2, byteorder="little", signed=True)
    with wave.open(str(target), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(bytes(payload))
    return target


def make_pack_folder(root: Path, pack: str, tracks: dict[str, str]) -> Path:
    """Create ``root/pack`` filled with ``{filename: Artist - Title}`` tones."""
    folder = root / pack
    for index, name in enumerate(tracks, start=1):
        write_tone(folder / name, freq=200.0 + index * 55)
    return folder


def wait_until(condition: Callable[[], bool], timeout_ms: int = 5000, step_ms: int = 20) -> bool:
    """Крутим Qt-цикл, пока ``condition()`` не станет истинной (для таймеров/медиа)."""
    from PyQt6.QtTest import QTest

    deadline = QDeadlineTimer(timeout_ms)
    while not deadline.hasExpired():
        if condition():
            return True
        QTest.qWait(step_ms)
    return bool(condition())
