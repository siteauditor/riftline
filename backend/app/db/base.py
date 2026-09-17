"""Database engine and session management.

SQLite by default so the project runs with nothing installed. Every model and
query here is portable, so moving to Postgres is a ``DATABASE_URL`` change plus
``pip install asyncpg`` -- no schema rewrite.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from app.config import get_settings

# backend/app/db/base.py -> project root
PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Base(DeclarativeBase):
    pass


def normalize_database_url(url: str) -> str:
    """Anchor relative SQLite paths to the project root.

    SQLAlchemy resolves relative SQLite paths against the process CWD, which
    silently produces a different database depending on where you launched the
    server from. Anchoring removes that whole class of confusion.
    """
    prefix = "sqlite+aiosqlite:///"
    if not url.startswith(prefix):
        return url
    raw = url[len(prefix) :]
    if raw.startswith(":memory:") or raw == "":
        return url
    path = Path(raw)
    if not path.is_absolute():
        path = (PROJECT_ROOT / path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"{prefix}{path.as_posix()}"


_settings = get_settings()
DATABASE_URL = normalize_database_url(_settings.database_url)

_IS_SQLITE = DATABASE_URL.startswith("sqlite")

# SQLite connections are local file handles: pooling them buys nothing and
# actively hurts, because a pooled aiosqlite connection carries the event loop
# it was created on. Hand it to a different loop -- a test, a worker, a reload
# -- and SQLAlchemy raises MissingGreenlet. NullPool sidesteps that entirely.
# Postgres keeps a real pool, where pre-ping does useful work.
engine = create_async_engine(
    DATABASE_URL,
    future=True,
    poolclass=NullPool if _IS_SQLITE else None,
    pool_pre_ping=not _IS_SQLITE,
)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

# How long a writer waits for the lock before giving up. SQLite allows exactly
# one writer at a time even under WAL, and this project runs the API alongside
# ingestion jobs that write in long batches. Without a timeout the loser of a
# collision fails instantly with "database is locked"; with one it simply waits
# its turn, which is what anybody would expect.
SQLITE_BUSY_TIMEOUT_MS = 15_000

if _IS_SQLITE:

    @event.listens_for(engine.sync_engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record):
        """Apply per-connection pragmas to *every* connection.

        `journal_mode` is stored in the database file and survives, but
        `busy_timeout` and `synchronous` are per-connection and reset on each
        new one. Since SQLite runs on NullPool here, every session opens a fresh
        connection, so setting them once at startup set them for exactly one
        connection that was then thrown away.
        """
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
            cursor.execute("PRAGMA synchronous=NORMAL")
        finally:
            cursor.close()


async def init_db() -> None:
    """Create tables and apply SQLite pragmas that matter for concurrent reads."""
    from app.db import models  # noqa: F401  (registers the mappers)

    async with engine.begin() as conn:
        if DATABASE_URL.startswith("sqlite"):
            from sqlalchemy import text

            # WAL is stored in the database file, so this one call is
            # enough; the per-connection pragmas are set by the connect
            # listener above. WAL lets ingestion write while the API reads.
            await conn.execute(text("PRAGMA journal_mode=WAL"))
        await conn.run_sync(Base.metadata.create_all)
