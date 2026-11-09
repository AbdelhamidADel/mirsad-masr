"""Database engine and session helpers for alerts."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from egxdesk.alerts.models import Base
from egxdesk.config import settings

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def _normalize_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return "sqlite+pysqlite:///:memory:"
    # Render / Heroku sometimes provide postgres://
    if raw.startswith("postgres://"):
        return "postgresql+psycopg://" + raw.removeprefix("postgres://")
    if raw.startswith("postgresql://") and "+psycopg" not in raw:
        return "postgresql+psycopg://" + raw.removeprefix("postgresql://")
    return raw


def get_engine(url: str | None = None) -> Engine:
    global _engine, _SessionLocal
    resolved = _normalize_url(url if url is not None else settings.database_url)
    if _engine is not None and url is None:
        return _engine
    connect_args: dict[str, object] = {}
    if resolved.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    engine = create_engine(resolved, future=True, connect_args=connect_args)
    if resolved.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_connection: object, _connection_record: object) -> None:
            cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    if url is None:
        _engine = engine
        _SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    return engine


def reset_engine() -> None:
    """Drop process-global engine (tests)."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None


def init_db(url: str | None = None) -> Engine:
    engine = get_engine(url)
    Base.metadata.create_all(bind=engine)
    if url is None and _SessionLocal is None:
        get_engine()  # ensure session factory bound
    return engine


@contextmanager
def session_scope(url: str | None = None) -> Iterator[Session]:
    if url is not None:
        engine = get_engine(url)
        factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
        session = factory()
    else:
        if _SessionLocal is None:
            init_db()
        assert _SessionLocal is not None
        session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
