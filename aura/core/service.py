"""Composition root: builds DB, library, engine and playlist controller.

Kept free of widgets so it can be constructed in tests and reused by the taskbar
panel (phase 4) without pulling UI in.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from ..audio.engine import AudioEngine
from ..config import AppPaths, Settings, load_settings, save_settings
from ..db.database import Database
from ..library.manager import LibraryManager
from ..log import get_logger, setup_logging
from ..scheduler.base import SchedulerFactory
from .playlist import PlaylistController, PlaybackSnapshot

log = get_logger("service")


class AuraService:
    def __init__(self, *, paths: AppPaths | None = None, settings: Settings | None = None) -> None:
        cached_paths, cached_settings = load_settings()
        self.paths = paths or cached_paths
        self.settings = settings or cached_settings
        setup_logging(
            self.settings.log_level,
            self.paths.logs if self.settings.file_logging else None,
            file_logging=self.settings.file_logging,
        )
        self.paths.ensure()
        self.db = Database(self.paths.db)
        self.library = LibraryManager(self.db, self.paths)
        self.mark_missing_files()

        self._engine: AudioEngine | None = None
        self._playlist: PlaylistController | None = None
        self._scheduler_name = self.settings.scheduler_backend
        self._closed = False
        self.tray: object | None = None
        self.window: object | None = None

    # ------------------------------------------------------------------ engine

    @property
    def engine(self) -> AudioEngine:
        if self._engine is None:
            self._engine = AudioEngine()
            self._engine.apply_settings(self.settings.volume, self.settings.fade_ms)
        return self._engine

    @property
    def playlist(self) -> PlaylistController:
        if self._playlist is None:
            self._playlist = PlaylistController(
                library=self.library,
                engine=self.engine,
                scheduler=self._build_scheduler(),
                settings=self.settings,
                context_provider=self.current_context,
            )
            self._playlist.track_changed.connect(self._on_track_changed)
        return self._playlist

    def current_context(self):
        """Контекст для выбора трека: активное приложение + время суток.

        Полноценный Activity Monitor (ввод, foreign audio, правила) — фаза 3;
        здесь только имя процесса на переднем плане и time_of_day.
        """
        from ..scheduler.base import Context, time_of_day
        from ..win_util import foreground_window

        process_name, _title = foreground_window()
        return Context(process_name=process_name, time_of_day=time_of_day(dt.datetime.now().hour))

    def _on_track_changed(self, track) -> None:  # noqa: ANN001 - TrackInfo | None
        if track is None:
            return
        try:
            self.library.record_play(track.id, self.playlist.session_id, self.current_context())
        except Exception:  # pragma: no cover - never break playback on logging
            log.exception("failed to store play event")

    def _build_scheduler(self):
        return SchedulerFactory.create(self._scheduler_name)

    @property
    def scheduler_name(self) -> str:
        return self._scheduler_name

    def set_scheduler(self, name: str) -> str:
        """Hot backend switch (ТЗ §3.6) — unknown names fall back to random."""
        self._scheduler_name = name if name in SchedulerFactory.names() else "random"
        if self._playlist is not None:
            self._playlist.set_scheduler(self._build_scheduler())
        return self._scheduler_name

    # ---------------------------------------------------------------- settings

    def apply_settings(self) -> None:
        """Push the current settings object into live components."""
        if self._engine is not None:
            self._engine.apply_settings(self.settings.volume, self.settings.fade_ms)
        if self._playlist is not None:
            self._playlist.settings = self.settings
        self.set_scheduler(self.settings.scheduler_backend)
        setup_logging(
            self.settings.log_level,
            self.paths.logs if self.settings.file_logging else None,
            file_logging=self.settings.file_logging,
        )

    def save_settings(self) -> Path:
        self.settings.scheduler_backend = self._scheduler_name  # type: ignore[assignment]
        return save_settings(self.settings, self.paths)

    # ------------------------------------------------------------- convenience

    def import_directory(self, root: str | Path, *, pack_name: str | None = None, **kwargs):
        result = self.library.import_directory(root, pack_name=pack_name, **kwargs)
        log.info("import %s: %s", root, result.message)
        return result

    def record_feedback(
        self,
        track_id: str,
        rating: int,
        *,
        context: dict[str, object] | None = None,
        position_sec: float = 0.0,
        session_id: str | None = None,
    ) -> bool:
        """Лайк/дизлайк текущего трека; обновляет бандита, если он что-то умеет."""
        stored = self.library.record_feedback(
            track_id,
            rating,
            context=context or {},
            position_sec=position_sec,
            session_id=session_id or (self._playlist.session_id if self._playlist else None),
        )
        if stored is None:
            return False
        if self._playlist is not None:
            self._playlist.scheduler.report_result(track_id, rating)
        log.info("feedback %+d для трека %s", rating, track_id[:8])
        return True

    def snapshot(self) -> PlaybackSnapshot:
        return self.playlist.snapshot()

    def mark_missing_files(self) -> list[str]:
        return self.library.mark_missing_files()

    @property
    def is_shutdown(self) -> bool:
        return self._closed

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._engine is not None:
            self._engine.stop()
        self.db.close()
