"""The live page when nobody is in a game, which is almost always.

Measured on 2026-09-21: 31 live lookups against production, covering the active
EUW and NA challengers and everyone in that week's best games, found nobody in a
game. So the idle branch of this endpoint is the one people actually see, and it
carries what we hold rather than an empty box.

Nothing here may cost a Riot call beyond the ones the live lookup already makes:
these reads are over stored rows.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import respx

from app.db.base import SessionLocal
from app.db.models import Match, MatchParticipant
from tests.test_live import mock_spectator

# Unique to this file. The suite shares one database, so a puuid reused from
# another test surfaces as a UNIQUE failure a long way from the cause.
IDLE_PUUID = "idle-player".ljust(78, "0")
EMPTY_PUUID = "idle-empty".ljust(78, "0")


async def seed_games(puuid: str, *, count: int, newest_at: int) -> None:
    """`count` stored games for one player, newest first, one day apart."""
    async with SessionLocal() as session:
        for i in range(count):
            match_id = f"IDLE1_{9100000000 + i}"
            session.add(
                Match(
                    match_id=match_id,
                    platform_id="IDLE1",
                    queue_id=420,
                    game_mode="CLASSIC",
                    game_type="MATCHED_GAME",
                    game_version="16.18.1",
                    patch="16.18",
                    map_id=11,
                    game_creation=newest_at - i * 86_400_000,
                    game_duration=1_800 + i,
                    is_remake=False,
                    teams=[],
                    raw={},
                    # Stamped as measured so the lobby rank backfill, which
                    # walks every stored match with no reading, does not adopt
                    # these rows and change what its own tests see.
                    lobby_rank_measured_at=datetime(2026, 9, 21, tzinfo=UTC),
                )
            )
            session.add(
                MatchParticipant(
                    match_id=match_id,
                    participant_index=0,
                    puuid=puuid,
                    champion_id=103 + i,
                    champion_name="Ahri",
                    team_id=100,
                    team_position="MIDDLE",
                    individual_position="MIDDLE",
                    win=i % 2 == 0,
                    kills=10 + i,
                    deaths=2,
                    assists=7,
                    champ_level=18,
                    gold_earned=14_000,
                    total_minions=210,
                    vision_score=22,
                    damage_to_champions=24_000,
                    damage_taken=19_000,
                    time_played=1_800,
                    performance_score=6.5,
                )
            )
        await session.commit()


def mock_player(puuid: str) -> None:
    """Riot's answers for one player, with our own puuid rather than the shared
    fixture's, so the stored rows above are the ones found."""
    respx.get(url__regex=r".*/riot/account/v1/accounts/by-riot-id/.*").mock(
        return_value=httpx.Response(
            200, json={"puuid": puuid, "gameName": "Idle", "tagLine": "EUW"}
        )
    )
    respx.get(url__regex=r".*/lol/summoner/v4/summoners/by-puuid/.*").mock(
        return_value=httpx.Response(
            200,
            json={
                "puuid": puuid,
                "profileIconId": 4567,
                "summonerLevel": 402,
                "revisionDate": 1_700_000_000_000,
            },
        )
    )
    respx.get(url__regex=r".*/lol/league/v4/entries/by-puuid/.*").mock(
        return_value=httpx.Response(200, json=[])
    )
    respx.get(url__regex=r".*/lol/match/v5/matches/by-puuid/.*/ids.*").mock(
        return_value=httpx.Response(200, json=[])
    )


@respx.mock
async def test_an_idle_player_gets_the_newest_game_we_hold(client):
    mock_player(IDLE_PUUID)
    mock_spectator(None, status=404)
    await seed_games(IDLE_PUUID, count=3, newest_at=1_789_000_000_000)

    body = (await client.get("/api/summoner/euw1/Idle/EUW/live")).json()

    assert body["in_game"] is False
    idle = body["idle"]
    assert idle["stored_games"] == 3
    assert idle["basis"] == "stored_matches"
    last = idle["last_game"]
    assert last["match_id"] == "IDLE1_9100000000"
    assert last["game_creation"] == 1_789_000_000_000
    assert last["champion"]["name"] == "Ahri"
    assert last["kills"] == 10
    assert last["performance_score"] == 6.5


@respx.mock
async def test_a_player_we_hold_nothing_for_gets_a_null_not_a_zeroed_game(client):
    """"We hold nothing" and "they played badly" are different claims, and a
    zeroed game would render as the second one."""
    mock_player(EMPTY_PUUID)
    mock_spectator(None, status=404)

    body = (await client.get("/api/summoner/euw1/Idle/EUW/live")).json()

    assert body["idle"]["stored_games"] == 0
    assert body["idle"]["last_game"] is None


@respx.mock
async def test_a_live_game_does_not_pay_for_the_idle_read(client):
    """The two storage reads are on the branch that shows them. A lobby in
    progress is the expensive path already."""
    from tests.test_live import spectator_game, spectator_participant

    mock_player(IDLE_PUUID)
    mock_spectator(
        spectator_game(
            [spectator_participant(puuid=IDLE_PUUID, riot_id="Idle#EUW", champion_id=103)]
        )
    )
    respx.get(url__regex=r".*/lol/champion-mastery/v4/champion-masteries/by-puuid/.*").mock(
        return_value=httpx.Response(200, json=[])
    )

    body = (await client.get("/api/summoner/euw1/Idle/EUW/live")).json()

    assert body["in_game"] is True
    assert body["idle"] is None


@respx.mock
async def test_the_idle_read_costs_no_riot_call_of_its_own(client):
    """Storage only. The account, summoner and spectator calls are the live
    lookup's own, and nothing here adds to them."""
    mock_player(IDLE_PUUID)
    spectator = mock_spectator(None, status=404)
    history = respx.get(url__regex=r".*/lol/match/v5/matches/by-puuid/.*/ids.*")

    await client.get("/api/summoner/euw1/Idle/EUW/live")

    assert spectator.call_count == 1
    # The idle summary reads stored rows; it never reaches for history.
    assert history.call_count == 0
