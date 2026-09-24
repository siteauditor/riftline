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
# The lobby ranks behind a slice are cached for an hour in production; a test
# that seeds lobbies must read them fresh.
os.environ["TTL_LOBBY_RANKS"] = "0"
# The slices held and the corpus summary are cached for five minutes in
# production; a test that aggregates must see what it made.
os.environ["TTL_CORPUS"] = "0"
# Every test shares one client address, so the per-address group limits would
# trip across tests. The test of the limit itself lowers it for its own run.
os.environ["GROUP_CREATES_PER_HOUR"] = "100000"
os.environ["GROUP_ADDS_PER_HOUR"] = "100000"

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


@pytest.fixture(autouse=True)
def _fresh_caches():
    """No cached answer or lock survives from one test into the next.

    The TTLs are zeroed above, but a waiter in a flight accepts an answer put
    during its wait whatever the TTL, and the remembered misses and
    unconfirmed homes are timed in minutes.
    """
    from app.services.flight import clear_all
    from app.services.players import clear_miss_cache

    clear_all()
    clear_miss_cache()
    yield
    clear_all()
    clear_miss_cache()


@pytest.fixture(autouse=True)
def _active_region(request, monkeypatch):
    """Riot's active-region lookup answers "no answer" unless a test asks.

    Every cold Riot ID lookup makes it after account-v1, and most tests are
    about something else, so by default it is answered here rather than
    mocked in every module: the row then keeps its shard, or a new one takes
    the shard of its newest stored game, else the one asked, which is the
    handled path for a region Riot will not name. A test that is about homes
    carries ``@pytest.mark.riot_region`` and mocks the endpoint itself.
    """
    if request.node.get_closest_marker("riot_region"):
        return

    async def no_answer(self, puuid, regional):
        return None

    from app.riot.client import RiotClient

    monkeypatch.setattr(RiotClient, "active_region", no_answer)


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "riot_region: the test mocks the active-region endpoint itself"
    )


@pytest.fixture(scope="session", autouse=True)
def _cleanup_db():
    yield
    for suffix in ("", "-wal", "-shm"):
        path = Path(str(_TMP) + suffix)
        if path.exists():
            with contextlib.suppress(OSError):
                path.unlink()
