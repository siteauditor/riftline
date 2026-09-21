"""A web request never waits on the Riot rate limiter past its budget.

Measured on 2026-09-22: with the development key's two-minute budget spent, a
leaderboard page waited 102 to 108 seconds for the limiter, and production sits
behind Cloudflare, which abandons an origin at 100. These run whole requests
through the app with the shared limiter held shut, so the middleware, the
client and the error handler are all the production code.
"""

from __future__ import annotations

import time

import httpx
import pytest
import respx


@pytest.fixture
async def busy_key(client):
    """The app's own limiter, with no slot for the next sixty seconds."""
    from app.main import app

    limiter = app.state.riot.limiter
    await limiter.penalize("application", 60.0)
    yield limiter
    limiter._penalty.clear()


@respx.mock
async def test_a_lookup_on_a_busy_key_answers_at_once_with_a_retry(client, busy_key):
    riot = respx.get(url__regex=r".*api\.riotgames\.com.*").mock(
        return_value=httpx.Response(200, json={})
    )
    start = time.monotonic()
    response = await client.get("/api/summoner/euw1/WaitBudgetNobody/0000")
    elapsed = time.monotonic() - start

    assert response.status_code == 429
    assert elapsed < 3.0, f"the request waited {elapsed:.1f}s for a slot"
    assert int(response.headers["Retry-After"]) >= 55
    assert response.json()["scope"] == "local"
    assert riot.call_count == 0


async def test_a_page_that_needs_no_riot_call_is_untouched(client, busy_key):
    """The budget only bites where Riot is asked. Stored data still answers."""
    response = await client.get("/api/meta/corpus")
    assert response.status_code == 200


def test_the_budget_sits_inside_the_edge_timeout():
    """Cloudflare gives up at 100 seconds, and a request also spends time on
    the calls themselves, so the waiting budget has to leave room for them."""
    from app.config import get_settings

    assert get_settings().riot_wait_budget_seconds <= 60
