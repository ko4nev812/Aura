"""Library Manager: packs, tracks and local imports (ТЗ §3.1).

Read APIs return frozen DTOs instead of ORM rows, so the UI never touches a
detached session and the ORM stays an implementation detail.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

from ..config import AppPaths
from ..db.database import Database
from ..db.models import RULE_MODES, AppRule, Feedback, Pack, PlayEvent, Track, TrackAnalysis
from ..log import get_logger
from . import scanner

log = get_logger("library")

ProgressCallback = Callable[[int, int, Path], bool]


@dataclass(frozen=True, slots=True)
class RuleInfo:
    id: str
    process_name: str
    title_pattern: str | None
    mode: str
    custom_pack_ids: tuple[str, ...]
    duck_level: float
    priority: int
    enabled: bool

    @property
    def label(self) -> str:
        scope = f" · {self.title_pattern}" if self.title_pattern else ""
        return f"{self.process_name}{scope} → {self.mode}"


@dataclass(frozen=True, slots=True)
class TrackInfo:
    id: str
    pack_id: str
    title: str
    artist: str | None
    file_path: str
    duration_sec: int
    format: str
    enabled: bool
    exists: bool = True
    bpm: float | None = None
    energy: float | None = None
    valence: float | None = None
    mood_tags: tuple[str, ...] = ()
    analyzed: bool = False

    @property
    def display_title(self) -> str:
        return f"{self.artist} — {self.title}" if self.artist else self.title


@dataclass(frozen=True, slots=True)
class PackInfo:
    id: str
    name: str
    source: str
    source_url: str | None
    enabled: bool
    created_at: datetime
    tracks: tuple[TrackInfo, ...] = field(default_factory=tuple)

    @property
    def track_count(self) -> int:
        return len(self.tracks)

    @property
    def enabled_count(self) -> int:
        return sum(1 for track in self.tracks if track.enabled)


@dataclass(slots=True)
class ImportResult:
    scanned: int = 0
    imported: int = 0
    skipped_existing: int = 0
    skipped_unreadable: int = 0
    errors: list[str] = field(default_factory=list)
    cancelled: bool = False

    @property
    def message(self) -> str:
        parts = [f"найдено {self.scanned}", f"добавлено {self.imported}"]
        if self.skipped_existing:
            parts.append(f"уже в библиотеке {self.skipped_existing}")
        if self.skipped_unreadable:
            parts.append(f"без звука {self.skipped_unreadable}")
        if self.cancelled:
            parts.append("отменено")
        return ", ".join(parts)


class LibraryManager:
    def __init__(self, db: Database, paths: AppPaths) -> None:
        self.db = db
        self.paths = paths
        self.db.create_schema()

    # ------------------------------------------------------------------ packs

    def create_pack(
        self, name: str, *, source: str = "local", source_url: str | None = None
    ) -> PackInfo:
        name = (name or "").strip()
        if not name:
            raise ValueError("Имя пака не может быть пустым")
        with self.db.session() as session:
            existing = session.scalar(select(Pack).where(func.lower(Pack.name) == name.lower()))
            pack = existing or Pack(name=name, source=source, source_url=source_url)
            if existing is None:
                session.add(pack)
            session.flush()
            return _pack_info(pack)

    def rename_pack(self, pack_id: str, name: str) -> PackInfo:
        name = (name or "").strip()
        if not name:
            raise ValueError("Имя пака не может быть пустым")
        with self.db.session() as session:
            pack = session.get(Pack, pack_id)
            if pack is None:
                raise KeyError(f"Пак не найден: {pack_id}")
            pack.name = name
            session.flush()
            return _pack_info(pack)

    def delete_pack(self, pack_id: str, *, delete_files: bool = False) -> int:
        with self.db.session() as session:
            pack = session.get(Pack, pack_id)
            if pack is None:
                return 0
            paths = [track.file_path for track in pack.tracks]
            session.delete(pack)
            session.flush()
        if delete_files:
            for raw in paths:
                try:
                    Path(raw).unlink(missing_ok=True)
                except OSError as exc:  # pragma: no cover - fs specific
                    log.warning("cannot delete %s: %s", raw, exc)
        return len(paths)

    def set_pack_enabled(self, pack_id: str, enabled: bool) -> None:
        with self.db.session() as session:
            pack = session.get(Pack, pack_id)
            if pack is not None:
                pack.enabled = enabled

    def get_pack(self, pack_id: str | None) -> PackInfo | None:
        if not pack_id:
            return None
        with self.db.new_session() as session:
            pack = session.get(Pack, pack_id)
            return _pack_info(pack) if pack else None

    def list_packs(self, *, with_tracks: bool = True) -> list[PackInfo]:
        with self.db.new_session() as session:
            packs = session.scalars(select(Pack).order_by(Pack.name)).all()
            if not with_tracks:
                return [_pack_info(pack, tracks=()) for pack in packs]
            return [_pack_info(pack) for pack in packs]

    def find_pack_by_name(self, name: str) -> PackInfo | None:
        with self.db.new_session() as session:
            pack = session.scalar(select(Pack).where(func.lower(Pack.name) == name.lower()))
            return _pack_info(pack) if pack else None

    # ----------------------------------------------------------------- tracks

    def list_tracks(
        self, pack_id: str | None = None, *, enabled_only: bool = False
    ) -> list[TrackInfo]:
        with self.db.new_session() as session:
            stmt = select(Track).join(Pack)
            if pack_id:
                stmt = stmt.where(Track.pack_id == pack_id)
            if enabled_only:
                stmt = stmt.where(Track.enabled.is_(True), Pack.enabled.is_(True))
            stmt = stmt.order_by(Pack.name, Track.title)
            return [_track_info(track) for track in session.scalars(stmt).unique()]

    def get_track(self, track_id: str) -> TrackInfo | None:
        with self.db.new_session() as session:
            track = session.get(Track, track_id)
            return _track_info(track) if track else None

    def set_track_enabled(self, track_id: str, enabled: bool) -> None:
        with self.db.session() as session:
            track = session.get(Track, track_id)
            if track is not None:
                track.enabled = enabled

    def delete_track(self, track_id: str, *, delete_files: bool = False) -> bool:
        with self.db.session() as session:
            track = session.get(Track, track_id)
            if track is None:
                return False
            path = track.file_path
            session.delete(track)
            session.flush()
        if delete_files:
            try:
                Path(path).unlink(missing_ok=True)
            except OSError as exc:  # pragma: no cover
                log.warning("cannot delete %s: %s", path, exc)
        return True

    def move_track(self, track_id: str, target_pack_id: str) -> TrackInfo | None:
        with self.db.session() as session:
            track = session.get(Track, track_id)
            target = session.get(Pack, target_pack_id)
            if track is None or target is None:
                return None
            track.pack_id = target_pack_id
            session.flush()
            return _track_info(track)

    def has_file(self, file_path: str | Path) -> bool:
        resolved = str(Path(file_path).resolve()).lower()
        with self.db.new_session() as session:
            for (stored,) in session.execute(select(Track.file_path)):
                try:
                    if str(Path(stored).resolve()).lower() == resolved:
                        return True
                except OSError:  # pragma: no cover - unreadable path
                    continue
        return False

    def add_local_file(
        self, path: str | Path, pack_id: str, *, copy_files: bool = False
    ) -> TrackInfo | None:
        """Register one audio file in a pack. Returns ``None`` if already known."""
        source = Path(path)
        if not source.is_file() or not scanner.is_audio_file(source):
            raise ValueError(f"Не аудиофайл или отсутствует: {source}")

        with self.db.new_session() as session:
            row = session.get(Pack, pack_id)
            pack_name = row.name if row is not None else None
        if pack_name is None:
            raise KeyError(f"Пак не найден: {pack_id}")

        stored = source
        if copy_files:
            stored = scanner.copy_into_library(source, self.paths.library, pack_name=pack_name)

        if self.has_file(stored):
            return None

        meta = scanner.probe(stored)
        with self.db.session() as session:
            track = Track(
                pack_id=pack_id,
                title=meta.title,
                artist=meta.artist,
                file_path=str(stored),
                duration_sec=meta.duration_sec,
                format=meta.format,
                file_size=meta.file_size,
                enabled=True,
            )
            session.add(track)
            session.flush()
            session.refresh(track)
            return _track_info(track)

    def import_directory(
        self,
        root: str | Path,
        *,
        pack_id: str | None = None,
        pack_name: str | None = None,
        copy_files: bool = False,
        recursive: bool = True,
        on_progress: ProgressCallback | None = None,
    ) -> ImportResult:
        """Recursively import a folder into a pack (created from the folder name)."""
        root_path = Path(root).expanduser()
        result = ImportResult()
        files = scanner.iter_audio_files(root_path, recursive=recursive)
        result.scanned = len(files)
        if not files:
            result.errors.append("В выбранной папке аудиозаписи не найдены")
            return result

        if pack_id is None:
            name = pack_name or (
                root_path.name if root_path.is_dir() else "Импорт"
            )
            pack_id = self.create_pack(name).id

        total = len(files)
        existing: set[str] = self._known_paths()
        for index, path in enumerate(files, start=1):
            if on_progress is not None and on_progress(index, total, path) is False:
                result.cancelled = True
                break
            try:
                stored = path
                if copy_files:
                    stored = scanner.copy_into_library(
                        path, self.paths.library, pack_name=self._pack_name(pack_id)
                    )
                if str(stored.resolve()).lower() in existing:
                    result.skipped_existing += 1
                    continue
                meta = scanner.probe(stored)
                if not meta.duration_sec and stored.suffix.lower() not in (".flac", ".wav"):
                    log.debug("zero duration, keeping anyway: %s", stored)
                with self.db.session() as session:
                    track = Track(
                        pack_id=pack_id,
                        title=meta.title,
                        artist=meta.artist,
                        file_path=str(stored),
                        duration_sec=meta.duration_sec,
                        format=meta.format,
                        file_size=meta.file_size,
                        enabled=True,
                    )
                    session.add(track)
                existing.add(str(stored.resolve()).lower())
                result.imported += 1
            except OSError as exc:
                result.skipped_unreadable += 1
                result.errors.append(f"{path.name}: {exc}")
            except Exception as exc:  # pragma: no cover - defensive, keeps import resilient
                log.exception("import failed for %s", path)
                result.errors.append(f"{path.name}: {exc}")
        return result

    # ------------------------------------------------------------------ rules

    def list_rules(self) -> list[RuleInfo]:
        with self.db.new_session() as session:
            rules = session.scalars(select(AppRule).order_by(AppRule.priority.desc(), AppRule.process_name)).all()
            return [_rule_info(rule) for rule in rules]

    def add_rule(
        self,
        process_name: str,
        *,
        title_pattern: str | None = None,
        mode: str = "pause",
        custom_pack_ids: Sequence[str] = (),
        priority: int = 0,
        duck_level: float = 0.2,
    ) -> RuleInfo:
        process_name = (process_name or "").strip()
        if not process_name:
            raise ValueError("Укажите имя процесса (например, chrome.exe)")
        if mode not in RULE_MODES:
            raise ValueError(f"Неизвестный режим: {mode}")
        with self.db.session() as session:
            rule = AppRule(
                process_name=process_name.lower(),
                title_pattern=(title_pattern or None),
                mode=mode,
                custom_pack_ids=list(custom_pack_ids),
                pause_behavior=mode if mode in ("pause", "duck", "ignore") else "pause",
                duck_level=float(duck_level),
                priority=int(priority),
            )
            session.add(rule)
            session.flush()
            return _rule_info(rule)

    def update_rule(self, rule_id: str, **changes: Any) -> RuleInfo | None:
        allowed = {"process_name", "title_pattern", "mode", "custom_pack_ids", "priority", "duck_level", "enabled"}
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError(f"Неизвестные поля правила: {', '.join(sorted(unknown))}")
        with self.db.session() as session:
            rule = session.get(AppRule, rule_id)
            if rule is None:
                return None
            for key, value in changes.items():
                setattr(rule, key, value)
            session.flush()
            return _rule_info(rule)

    def delete_rule(self, rule_id: str) -> bool:
        with self.db.session() as session:
            rule = session.get(AppRule, rule_id)
            if rule is None:
                return False
            session.delete(rule)
            return True

    # ------------------------------------------------------------- maintenance

    def record_play(self, track_id: str, session_id: str | None = None, context=None) -> str | None:  # noqa: ANN001 - Context | None
        """История воспроизведений (ТЗ §3.5/§3.6: признаки для scheduler'а)."""
        with self.db.session() as session:
            if session.get(Track, track_id) is None:
                return None
            snapshot = _context_dict(context)
            event = PlayEvent(
                track_id=track_id,
                session_id=session_id,
                context_snapshot=snapshot,
                process_name=snapshot.get("process_name"),  # type: ignore[arg-type]
                activity_level=snapshot.get("activity_level"),  # type: ignore[arg-type]
                time_of_day=snapshot.get("time_of_day"),  # type: ignore[arg-type]
            )
            session.add(event)
            session.flush()
            return event.id

    def record_feedback(
        self,
        track_id: str,
        rating: int,
        *,
        context: dict[str, object] | None = None,
        position_sec: float = 0.0,
        session_id: str | None = None,
    ) -> str | None:
        """Лайк/дизлайк (ТЗ §3.7). Контекст сохраняется как срез без заголовков окон."""
        if rating not in (-1, 0, 1):
            raise ValueError("rating должен быть -1, 0 или 1")
        with self.db.session() as session:
            if session.get(Track, track_id) is None:
                return None
            feedback = Feedback(
                track_id=track_id,
                rating=rating,
                context_snapshot=dict(context or {}),
                position_in_track_sec=float(position_sec),
                session_id=session_id,
            )
            session.add(feedback)
            session.flush()
            return feedback.id

    def latest_feedback(self, track_id: str) -> int | None:
        with self.db.new_session() as session:
            return session.scalar(
                select(Feedback.rating)
                .where(Feedback.track_id == track_id)
                .order_by(Feedback.created_at.desc())
                .limit(1)
            )

    def feedback_totals(self) -> dict[str, int]:
        with self.db.new_session() as session:
            rows = session.execute(
                select(Feedback.rating, func.count(Feedback.id)).group_by(Feedback.rating)
            ).all()
        totals = {"likes": 0, "dislikes": 0, "total": 0}
        for rating, count in rows:
            totals["total"] += int(count)
            if rating > 0:
                totals["likes"] = int(count)
            elif rating < 0:
                totals["dislikes"] = int(count)
        return totals

    def mark_missing_files(self) -> list[str]:
        """Disable tracks whose files disappeared; returns affected paths."""
        missing: list[str] = []
        with self.db.session() as session:
            for track in session.scalars(select(Track).where(Track.enabled.is_(True))):
                if not Path(track.file_path).exists():
                    track.enabled = False
                    missing.append(track.file_path)
        if missing:
            log.info("disabled %d tracks with missing files", len(missing))
        return missing

    def tracks_needing_analysis(self) -> list[TrackInfo]:
        with self.db.new_session() as session:
            stmt = (
                select(Track)
                .outerjoin(TrackAnalysis, TrackAnalysis.track_id == Track.id)
                .where(TrackAnalysis.track_id.is_(None))
                .order_by(Track.created_at)
            )
            return [_track_info(track) for track in session.scalars(stmt).unique()]

    def stats(self) -> dict[str, int]:
        with self.db.new_session() as session:
            packs = session.scalar(select(func.count(Pack.id))) or 0
            tracks = session.scalar(select(func.count(Track.id))) or 0
            enabled = session.scalar(
                select(func.count(Track.id))
                .join(Pack)
                .where(Track.enabled.is_(True), Pack.enabled.is_(True))
            ) or 0
            analyzed = session.scalar(select(func.count(TrackAnalysis.track_id))) or 0
            duration = session.scalar(
                select(func.coalesce(func.sum(Track.duration_sec), 0))
            ) or 0
        return {
            "packs": int(packs),
            "tracks": int(tracks),
            "playable": int(enabled),
            "analyzed": int(analyzed),
            "duration_sec": int(duration),
        }

    # ---------------------------------------------------------------- internal

    def _pack_name(self, pack_id: str) -> str:
        pack = self.get_pack(pack_id)
        return pack.name if pack else "import"

    def _known_paths(self) -> set[str]:
        paths: set[str] = set()
        with self.db.new_session() as session:
            for (stored,) in session.execute(select(Track.file_path)):
                try:
                    paths.add(str(Path(stored).resolve()).lower())
                except OSError:  # pragma: no cover
                    paths.add(str(stored).lower())
        return paths


def _track_info(track: Track) -> TrackInfo:
    analysis = track.analysis
    tags: Sequence[str] = tuple(analysis.mood_tags or ()) if analysis else ()
    return TrackInfo(
        id=track.id,
        pack_id=track.pack_id,
        title=track.title,
        artist=track.artist,
        file_path=track.file_path,
        duration_sec=track.duration_sec,
        format=track.format,
        enabled=track.enabled,
        exists=Path(track.file_path).exists(),
        bpm=analysis.bpm if analysis else None,
        energy=analysis.energy if analysis else None,
        valence=analysis.valence if analysis else None,
        mood_tags=tuple(tags),
        analyzed=bool(analysis and analysis.analyzed_at),
    )


def _pack_info(pack: Pack, tracks: tuple[TrackInfo, ...] | None = None) -> PackInfo:
    if tracks is None:
        tracks = tuple(_track_info(track) for track in sorted(pack.tracks, key=lambda t: t.title.lower()))
    return PackInfo(
        id=pack.id,
        name=pack.name,
        source=pack.source,
        source_url=pack.source_url,
        enabled=pack.enabled,
        created_at=pack.created_at,
        tracks=tracks,
    )


def _rule_info(rule: AppRule) -> RuleInfo:
    return RuleInfo(
        id=rule.id,
        process_name=rule.process_name,
        title_pattern=rule.title_pattern,
        mode=rule.mode,
        custom_pack_ids=tuple(rule.custom_pack_ids or ()),
        duck_level=rule.duck_level,
        priority=rule.priority,
        enabled=rule.enabled,
    )


def _context_dict(context: object) -> dict[str, Any]:
    """Обезличенный снапшот контекста: процесс не сохраняется в заголовках окон (ТЗ §8)."""
    if context is None:
        return {}
    data = getattr(context, "__dict__", None)
    if not isinstance(data, dict):
        getters = ("process_name", "activity_level", "time_of_day", "foreign_audio")
        return {name: getattr(context, name, None) for name in getters}
    allowed = {"process_name", "activity_level", "time_of_day", "foreign_audio"}
    snapshot = {key: value for key, value in data.items() if key in allowed}
    extra = data.get("extra")
    if isinstance(extra, dict):
        snapshot.update({str(k): v for k, v in extra.items() if k in allowed})
    return snapshot
