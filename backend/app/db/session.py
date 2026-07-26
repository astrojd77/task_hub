"""Engine and session wiring."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

_settings = get_settings()

_connect_args: dict = {}
if _settings.is_sqlite:
    # FastAPI serves requests from a threadpool; SQLite objects are otherwise
    # pinned to their creating thread.
    _connect_args["check_same_thread"] = False

engine = create_engine(
    _settings.database_url,
    echo=_settings.db_echo,
    future=True,
    pool_pre_ping=True,
    connect_args=_connect_args,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a request-scoped session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
