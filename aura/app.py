"""Qt application bootstrap: theme, single instance, window, tray, shortcuts."""

from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtCore import QLockFile, QStandardPaths
from PyQt6.QtWidgets import QApplication

from .config import AppPaths, Settings, load_settings
from .core.service import AuraService
from .log import get_logger
from .ui.main_window import MainWindow
from .ui.theme import apply_theme
from .ui.tray import TrayController

log = get_logger("app")

LOCK_NAME = "aura.lock"
PREVENT_STYLE = "Fusion"


def acquire_instance_lock() -> QLockFile | None:
    """``None`` means another Aura instance already owns the lock."""
    directory = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.TempLocation)
    lock = QLockFile(str(Path(directory) / LOCK_NAME))
    lock.setStaleLockTime(15_000)
    return lock if lock.tryLock(100) else None


def create_app(argv: list[str] | None = None) -> QApplication:
    app = QApplication.instance() or QApplication(argv if argv is not None else sys.argv)
    app.setStyle(PREVENT_STYLE)
    app.setApplicationName("Aura")
    app.setOrganizationName("Aura")
    app.setApplicationDisplayName("Aura")
    app.setQuitOnLastWindowClosed(False)
    apply_theme(app)
    return app


class AuraApp:
    """Owns the Qt objects for one running session."""

    def __init__(self, service: AuraService, app: QApplication, *, hidden: bool = False) -> None:
        self.app = app
        self.service = service
        self.window = MainWindow(service)
        service.window = self.window
        self.tray = TrayController(service, self.window)
        service.tray = self.tray
        self.tray.show()
        self.window.show_message("Aura готова")
        app.aboutToQuit.connect(self.shutdown)

        if hidden or service.settings.start_minimized:
            log.info("запуск свёрнутым в трей")
        else:
            self.window.show()
        if service.settings.play_on_start:
            service.playlist.start()

    def exec(self) -> int:
        return self.app.exec()

    def shutdown(self) -> None:
        self.service.shutdown()


def bootstrap(
    *,
    data_dir: str | Path | None = None,
    settings: Settings | None = None,
    argv: list[str] | None = None,
) -> AuraApp:
    paths, resolved = load_settings()
    if data_dir:
        paths = AppPaths(Path(data_dir).expanduser()).ensure()
    if settings is not None:
        resolved = settings
    service = AuraService(paths=paths, settings=resolved)
    app = create_app(argv)
    return AuraApp(service, app)
