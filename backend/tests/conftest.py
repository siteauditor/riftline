"""Test configuration.

The database engine is built at import time from settings, so the environment
has to be redirected to a throwaway database *before* any app module loads.
conftest is imported first by pytest, which makes this the right place.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
import uuid
from pathlib import Path

_TMP = Path(tempfile.gettempdir()) / f"lol-test-{uuid.uuid4().hex}.db"

os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP.as_posix()}"
os.environ["RIOT_API_KEY"] = "RGAPI-test-key"
os.environ["APP_RATE_LIMITS"] = "1000:1"  # never throttle the suite
os.environ["TTL_ACCOUNT"] = "0"
os.environ["TTL_SUMMONER"] = "0"
os.environ["TTL_LEAGUE"] = "0"
os.environ["TTL_MASTERY"] = "0"
# Bulk rank lookups cache for 15 minutes in production. Zeroed here so a
# rank stored by one test cannot silently serve another.
os.environ["TTL_LEAGUE_BULK"] = "0"

import httpx  # noqa: E402
import pytest  # noqa: E402
from asgi_lifespan import LifespanManager  # noqa: E402


@pytest.fixture
async def client():
    """The FastAPI app with its lifespan run, ready for requests.

    Shared by every API test module. Riot is mocked per-test at the transport
    layer with respx; everything above it is production code.
    """
    from app.main import app

    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            yield http


@pytest.fixture(autouse=True)
async def _schema():
    """Make sure the tables exist.

    The integration tests get this from the app's lifespan, but unit tests that
    talk to the database directly never boot the app. ``create_all`` checks
    first, so after the initial call this is a couple of PRAGMA queries.
    """
    from app.db.base import init_db

    await init_db()


@pytest.fixture(scope="session", autouse=True)
def _cleanup_db():
    yield
    for suffix in ("", "-wal", "-shm"):
        path = Path(str(_TMP) + suffix)
        if path.exists():
            with contextlib.suppress(OSError):
                path.unlink()
