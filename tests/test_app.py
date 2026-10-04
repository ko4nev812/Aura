"""Фаза 1: сборка приложения целиком — bootstrap, трей, выход по «Выход»."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from aura.app import acquire_instance_lock, bootstrap

PROJECT_ROOT = Path(__file__).resolve().parents[1]

EXIT_SCRIPT = """
import sys
from PyQt6.QtCore import QTimer
from aura.app import bootstrap

app = bootstrap(data_dir=sys.argv[1])
app.window.show()
QTimer.singleShot(200, app.tray.quit)
QTimer.singleShot(20_000, app.app.quit)
code = app.app.exec()
print("RESULT", code, app.service.is_shutdown)
"""


def test_bootstrap_builds_window_tray_and_quits(tmp_path, qapp):  # noqa: ARG001
    app = bootstrap(data_dir=tmp_path / "AuraData")
    try:
        service = app.service
        assert app.window is not None
        assert app.tray is not None
        assert service.window is app.window
        assert service.tray is app.tray
        assert app.window.tabs.count() == 5

        lock = acquire_instance_lock()
        assert lock is not None, "второй экземпляр не должен захватывать lock"
        lock.unlock()
    finally:
        app.shutdown()

    assert service.is_shutdown
    app.shutdown()  # идемпотентно: повторный выход не должен падать


def test_tray_quit_shuts_service_down(tmp_path, qapp):  # noqa: ARG001
    app = bootstrap(data_dir=tmp_path / "AuraDataQuit")
    app.tray.quit()
    assert app.service.is_shutdown


def test_close_to_tray_hides_window_and_quit_closes_it(service):
    from aura.ui.main_window import MainWindow
    from aura.ui.tray import TrayController

    service.settings.close_to_tray = True
    window = MainWindow(service)
    service.tray = TrayController(service, window)
    window.show()
    window.close()
    assert window.isHidden() is True
    assert window.quit_requested is False

    other = MainWindow(service)
    other.quit()
    assert other.quit_requested is True
    assert other.isHidden() is True


def test_instance_lock_is_exclusive(tmp_path, qapp):  # noqa: ARG001
    first = acquire_instance_lock()
    assert first is not None
    assert acquire_instance_lock() is None, "второй экземпляр не должен запускаться"
    first.unlock()


@pytest.mark.parametrize("hidden", [False, True])
def test_bootstrap_respects_start_minimized(tmp_path, qapp, hidden):  # noqa: ARG001
    from aura.config import Settings

    settings = Settings(play_on_start=False, start_minimized=hidden)
    app = bootstrap(settings=settings, data_dir=tmp_path / f"Aura{hidden}")
    try:
        assert app.window.isHidden() is hidden
    finally:
        app.shutdown()


def test_gui_process_exits_on_tray_quit(tmp_path):
    """Настоящий event loop в отдельном процессе: трей → «Выход» → процесс завершается."""
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    result = subprocess.run(
        [sys.executable, "-c", EXIT_SCRIPT, str(tmp_path / "AuraExit")],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert "RESULT 0 True" in result.stdout, (result.stdout, result.stderr)
    assert result.returncode == 0