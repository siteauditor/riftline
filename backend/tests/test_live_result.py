"""Resolving a finished live game into its stored match.

This is the only Riot call the live page spends beyond the lookup itself, and
the only new write path, so every test here is about bounding that spend: the
storage hit costs nothing, the cooldown holds off the second tab, and the cap
stops a match id that will never publish from costing anything more.
"""

from __future__ import annotations

import httpx
import pytest
import respx

import tests.fixtures as fx
from app.api.routes.summoner import clear_resolve_cache
from app.config import get_settings

MATCH = "EUW1_9300000001"
UNPUBLISHED = "EUW1_9300000002"


@pytest.fixture(autouse=True)
def _clear_attempts():
    """The attempt counts are process global, so a test must not inherit the
    previous one's. Cleared on both sides, like the mastery cache."""
    clear_resolve_cache()
    yield
    clear_resolve_cache()


def mock_account() -> None:
    respx.get(url__regex=r".*/riot/account/v1/accounts/by-riot-id/.*").mock(
        return_value=httpx.Response(200, json=fx.account())
    )
    respx.get(url__regex=r".*/lol/summoner/v4/summoners/by-puuid/.*").mock(
        return_value=httpx.Response(200, json=fx.summoner())
    )


def mock_match(match_id: str, *, found: bool = True):
    payload = fx.match(match_id)
    return respx.get(url__regex=rf".*/lol/match/v5/matches/{match_id}$").mock(
        return_value=httpx.Response(200, json=payload)
        if found
        else httpx.Response(404, json={"status": {"status_code": 404}})
    )


@respx.mock
async def test_a_match_riot_has_not_published_yet_is_pending_not_an_error(client):
    """200 with a status, never a 404: the match will exist, and "no such match"
    would be a different and false claim."""
    mock_account()
    riot = mock_match(UNPUBLISHED, found=False)

    response = await client.get(f"/api/summoner/euw1/Caps/EUW/live/result/{UNPUBLISHED}")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "pending"
    assert body["attempted"] is True
    assert body["retry_after"] > 0
    assert riot.call_count == 1


@respx.mock
async def test_a_published_match_is_stored_and_then_costs_nothing(client):
    mock_account()
    riot = mock_match(MATCH)

    first = (await client.get(f"/api/summoner/euw1/Caps/EUW/live/result/{MATCH}")).json()
    second = (await client.get(f"/api/summoner/euw1/Caps/EUW/live/result/{MATCH}")).json()

    assert first["status"] == "stored"
    assert first["attempted"] is True
    assert first["game_duration"] > 0
    # Their own line, so the page can say "you won" rather than "it exists".
    assert first["win"] in (True, False)
    assert second["win"] == first["win"]
    # The steady state: every later request, from anyone, reads storage.
    assert second["status"] == "stored"
    assert second["attempted"] is False
    assert riot.call_count == 1
    # And it arrives through the ordinary match page, already scored.
    detail = await client.get(f"/api/matches/{MATCH}")
    assert detail.status_code == 200


@respx.mock
async def test_a_second_request_inside_the_cooldown_spends_nothing(client):
    """The cooldown is not for one client: it is for the hand refreshed page,
    the second tab, and the other viewer watching the same game."""
    mock_account()
    riot = mock_match(UNPUBLISHED, found=False)

    first = (await client.get(f"/api/summoner/euw1/Caps/EUW/live/result/{UNPUBLISHED}")).json()
    second = (await client.get(f"/api/summoner/euw1/Caps/EUW/live/result/{UNPUBLISHED}")).json()

    assert first["attempted"] is True
    assert second["attempted"] is False
    assert second["status"] == "pending"
    assert riot.call_count == 1


@respx.mock
async def test_the_attempt_cap_stops_the_spend(client, monkeypatch):
    """Three calls per match id, whatever the number of open tabs. Without the
    cap a forgotten tab would keep asking for a game that never published."""
    settings = get_settings()
    monkeypatch.setattr(settings, "live_result_cooldown_seconds", 0.0)
    mock_account()
    riot = mock_match(UNPUBLISHED, found=False)

    answers = [
        (await client.get(f"/api/summoner/euw1/Caps/EUW/live/result/{UNPUBLISHED}")).json()
        for _ in range(settings.live_result_max_attempts + 2)
    ]

    assert riot.call_count == settings.live_result_max_attempts
    assert answers[-1]["status"] == "gave_up"
    assert answers[-1]["retry_after"] is None
    assert answers[-1]["attempted"] is False


@respx.mock
async def test_a_malformed_match_id_costs_nothing(client):
    account = respx.get(url__regex=r".*/riot/account/v1/accounts/by-riot-id/.*")
    riot = respx.get(url__regex=r".*/lol/match/v5/matches/.*")

    bad = await client.get("/api/summoner/euw1/Caps/EUW/live/result/not-a-match-id")
    unknown_shard = await client.get("/api/summoner/euw1/Caps/EUW/live/result/ZZ9_123")

    assert bad.status_code == 400
    assert unknown_shard.status_code == 400
    assert account.call_count == 0
    assert riot.call_count == 0


@respx.mock
async def test_the_disabled_flag_short_circuits_before_any_riot_call(client, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "enable_spectator", False)
    account = respx.get(url__regex=r".*/riot/account/v1/accounts/by-riot-id/.*")

    response = await client.get(f"/api/summoner/euw1/Caps/EUW/live/result/{MATCH}")

    assert response.status_code == 403
    assert account.call_count == 0


@respx.mock
async def test_the_live_response_carries_the_match_id_to_ask_about(client, monkeypatch):
    """Built on the server. This codebase does not hand assemble Riot ids in
    React, and the page needs one the moment the game ends."""
    from tests.test_integration import mock_riot
    from tests.test_live import full_roster, lane_priors, mock_spectator, spectator_game

    monkeypatch.setattr("app.services.live.load_priors", lane_priors)
    mock_riot()
    mock_spectator(spectator_game(full_roster("result"), queue_id=420))

    game = (await client.get("/api/summoner/euw1/Caps/EUW/live")).json()["game"]

    assert game["match_id"] == f"{game['platform_id']}_{game['game_id']}"
