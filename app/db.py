"""Engine, session, dan Base SQLAlchemy."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings


def _prepare_sqlite_path(url: str) -> None:
    """Pastikan direktori database SQLite sudah ada sebelum engine menyambung."""
    prefix = "sqlite:///"
    if not url.startswith(prefix):
        return
    raw = url[len(prefix):]
    if not raw or raw == ":memory:":
        return
    Path(raw).parent.mkdir(parents=True, exist_ok=True)


_prepare_sqlite_path(settings.database_url)

_connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}

engine = create_engine(
    settings.database_url,
    connect_args=_connect_args,
    pool_pre_ping=True,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    """Base deklaratif untuk semua model."""


def get_db():
    """FastAPI dependency: sesi database per-request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
