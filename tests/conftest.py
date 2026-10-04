"""Test fixtures: offscreen Qt, temp data dir, generated audio files."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from aura.config import AppPaths, Settings  # noqa: E402
from aura.core.service import AuraService  # noqa: E402

from .helpers import write_tone  # noqa: E402  (re-exported for tests)

__all__ = ["write_tone"]


@pytest.fixture(scope="session", autouse=True)
def qapp() -> QApplication:
    """Сессия-уровня QApplication: QPixmap/QIcon нельзя создавать без него."""
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(scope="session", autouse=True)
def isolated_data_dir():
    """Тесты никогда не читают и не пишут реальный %APPDATA%/Aura."""
    import shutil
    import tempfile

    previous = os.environ.get("AURA_DATA_DIR")
    root = Path(tempfile.mkdtemp(prefix="aura-tests-"))
    os.environ["AURA_DATA_DIR"] = str(root)
    _clear_settings_cache()
    yield root
    _clear_settings_cache()
    if previous is None:
        os.environ.pop("AURA_DATA_DIR", None)
    else:
        os.environ["AURA_DATA_DIR"] = previous
    shutil.rmtree(root, ignore_errors=True)


def _clear_settings_cache() -> None:
    from aura.config import load_settings

    load_settings(use_cache=False)


@pytest.fixture(autouse=True)
def _isolated_settings_cache():
    """Не давать кэшированным Settings утекать между тестами (AURA_DATA_DIR меняется)."""
    _clear_settings_cache()
    yield
    _clear_settings_cache()


@pytest.fixture
def paths(tmp_path) -> AppPaths:
    return AppPaths(tmp_path / "AuraData").ensure()


@pytest.fixture
def settings() -> Settings:
    return Settings(
        volume=50,
        fade_ms=0,
        crossfade_enabled=False,
        crossfade_sec=0.0,
        shuffle=True,
        silence_min_sec=0,
        silence_max_sec=0,
        scheduler_backend="random",
    )


@pytest.fixture
def service(paths, settings, qapp) -> AuraService:  # noqa: ARG001 - qapp ensures a Qt app exists
    instance = AuraService(paths=paths, settings=settings)
    yield instance
    instance.shutdown()


@pytest.fixture
def music_dir(tmp_path) -> str:
    root = tmp_path / "music"
    for name, freq in (
        ("01 - Rain Scope - Driven.mp3", 220.0),
        ("02 - Night Field - Fog.wav", 330.0),
        ("Deep Focus - Slow Motion.flac", 440.0),
    ):
        write_tone(root / "ambient" / name, seconds=3.0, freq=freq)
    ignored = root / "ambient" / "notes.txt"
    ignored.parent.mkdir(parents=True, exist_ok=True)
    ignored.write_text("ignore me", encoding="utf-8")
    return str(root)
