"""SQLite connection/session management for Aura."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .models import Base


class Database:
    """Owned by the app; sessions are short-lived and created on demand."""

    def __init__(self, path: str | Path, *, echo: bool = False) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.engine: Engine = create_engine(
            f"sqlite:///{self.path.as_posix()}",
            echo=echo,
            future=True,
            connect_args={"check_same_thread": False, "timeout": 10.0},
        )
        _attach_pragmas(self.engine)
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False, future=True)

    def create_schema(self) -> None:
        Base.metadata.create_all(self.engine)

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = self.session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    @contextmanager
    def new_session(self) -> Iterator[Session]:
        """Alias kept for callers that manage commit themselves."""
        session = self.session_factory()
        try:
            yield session
        finally:
            session.close()

    def scalar(self, sql: str, **params: object) -> object:
        with self.session() as session:
            return session.execute(text(sql), params).scalar()

    def close(self) -> None:
        self.engine.dispose()


def _attach_pragmas(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def _configure(dbapi_connection: object, _record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        for statement in (
            "PRAGMA journal_mode=WAL",
            "PRAGMA synchronous=NORMAL",
            "PRAGMA foreign_keys=ON",
            "PRAGMA busy_timeout=10000",
        ):
            cursor.execute(statement)
        cursor.close()
