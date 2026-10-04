"""SQLAlchemy models for the Aura database (ТЗ §3.1, §3.4, §3.7).

The whole schema is created in phase 1 so that later phases (YouTube import,
activity rules, feedback, bandits) only add behaviour, not migrations.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from typing import Any, Iterable

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

PACK_SOURCES = ("local", "youtube", "generated")
RULE_MODES = ("pause", "duck", "ignore", "custom")


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Pack(Base):
    """Плейлист/пак треков (ТЗ §3.1)."""

    __tablename__ = "packs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="local")
    source_url: Mapped[str | None] = mapped_column(String(1024))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False, default=utcnow)

    tracks: Mapped[list["Track"]] = relationship(
        back_populates="pack", cascade="all, delete-orphan", passive_deletes=True
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Pack {self.name!r} enabled={self.enabled} tracks={len(self.tracks)}>"


class Track(Base):
    __tablename__ = "tracks"
    __table_args__ = (
        UniqueConstraint("file_path", name="uq_tracks_file_path"),
        Index("ix_tracks_pack_enabled", "pack_id", "enabled"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    pack_id: Mapped[str] = mapped_column(
        ForeignKey("packs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    artist: Mapped[str | None] = mapped_column(String(512))
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    duration_sec: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    format: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    file_size: Mapped[int | None] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False, default=utcnow)

    pack: Mapped["Pack"] = relationship(back_populates="tracks")
    analysis: Mapped["TrackAnalysis | None"] = relationship(
        back_populates="track", cascade="all, delete-orphan", passive_deletes=True, lazy="joined"
    )
    feedback: Mapped[list["Feedback"]] = relationship(
        back_populates="track", cascade="all, delete-orphan", passive_deletes=True
    )

    @property
    def is_playable(self) -> bool:
        return bool(self.enabled and self.file_path)

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Track {self.title!r} ({self.duration_sec}s)>"


class TrackAnalysis(Base):
    """Аудио-признаки трека (ТЗ §3.1/§3.3). Заполняется в фазе 2."""

    __tablename__ = "track_analysis"

    track_id: Mapped[str] = mapped_column(
        ForeignKey("tracks.id", ondelete="CASCADE"), primary_key=True
    )
    bpm: Mapped[float | None] = mapped_column(Float)
    energy: Mapped[float | None] = mapped_column(Float)
    valence: Mapped[float | None] = mapped_column(Float)
    danceability: Mapped[float | None] = mapped_column(Float)
    acousticness: Mapped[float | None] = mapped_column(Float)
    instrumentalness: Mapped[float | None] = mapped_column(Float)
    loudness_db: Mapped[float | None] = mapped_column(Float)
    key: Mapped[str | None] = mapped_column(String(16))
    mood_tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    analyzed_at: Mapped[dt.datetime | None] = mapped_column(DateTime)

    track: Mapped["Track"] = relationship(back_populates="analysis")

    @property
    def mood_set(self) -> set[str]:
        tags = self.mood_tags or []
        return {str(t) for t in tags} if isinstance(tags, Iterable) else set()


class AppRule(Base):
    """Black/white список приложений (ТЗ §3.4). Используется в фазе 3."""

    __tablename__ = "app_rules"
    __table_args__ = (Index("ix_app_rules_process", "process_name", "priority"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    process_name: Mapped[str] = mapped_column(String(255), nullable=False)
    title_pattern: Mapped[str | None] = mapped_column(String(512))
    mode: Mapped[str] = mapped_column(String(32), nullable=False, default="pause")
    custom_pack_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    pause_behavior: Mapped[str] = mapped_column(String(32), nullable=False, default="pause")
    duck_level: Mapped[float] = mapped_column(Float, nullable=False, default=0.2)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Feedback(Base):
    """Лайки/дизлайки (ТЗ §3.7). Используется в фазе 4."""

    __tablename__ = "feedback"
    __table_args__ = (Index("ix_feedback_track_time", "track_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    track_id: Mapped[str] = mapped_column(
        ForeignKey("tracks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_id: Mapped[str | None] = mapped_column(String(36), index=True)
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    context_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    position_in_track_sec: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False, default=utcnow)

    track: Mapped["Track"] = relationship(back_populates="feedback")


class PlayEvent(Base):
    """История воспроизведений — источник признаков для Scheduler/аналитики."""

    __tablename__ = "play_events"
    __table_args__ = (
        Index("ix_play_events_context", "process_name", "activity_level", "time_of_day"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    track_id: Mapped[str] = mapped_column(
        ForeignKey("tracks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_id: Mapped[str | None] = mapped_column(String(36), index=True)
    context_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    process_name: Mapped[str | None] = mapped_column(String(255))
    activity_level: Mapped[str | None] = mapped_column(String(32))
    time_of_day: Mapped[str | None] = mapped_column(String(32))
    started_at: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    position_sec: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    skipped: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class BanditArm(Base):
    """Состояние контекстного бандита по треку (ТЗ §3.6, вариант A). Фаза 4."""

    __tablename__ = "bandit_arms"

    track_id: Mapped[str] = mapped_column(
        ForeignKey("tracks.id", ondelete="CASCADE"), primary_key=True
    )
    context_key: Mapped[str] = mapped_column(String(128), primary_key=True, default="*")
    alpha: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    beta: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    plays: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_played_at: Mapped[dt.datetime | None] = mapped_column(DateTime)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False, default="")

    @staticmethod
    def encode(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False)

    def decoded(self) -> Any:
        try:
            return json.loads(self.value)
        except (TypeError, ValueError):  # pragma: no cover - corrupted row
            return self.value


def dump(obj: Base) -> dict[str, Any]:
    """Сериализация записи в plain dict (для UI/отладки)."""
    data: dict[str, Any] = {}
    for column in obj.__table__.columns:
        value = getattr(obj, column.name)
        if isinstance(value, dt.datetime):
            value = value.isoformat()
        data[column.name] = value
    return data
