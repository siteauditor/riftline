"""Player play-style analytics.

Reads stored matches only, so the interesting behaviour is arithmetic over rows
we control plus the one thing it does call Riot for: resolving the Riot ID.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from tests.test_aggregate import participant, seed

PUUID = "A" * 78
# Ahri (Mage), Lee Sin (Fighter/Assassin), Thresh (Support/Fighter). Real ids, so
# the class mix comes from live Data Dragon tags rather than a stub.
AHRI, LEE_SIN, THRESH = 103, 64, 412

# 14:30 UTC, as epoch milliseconds.
AFTERNOON_MS = ((14 * 3600) + 1800) * 1000


def mock_identity():
    respx.get(url__regex=r".*/riot/account/v1/.*").mock(
        return_value=httpx.Response(
            200, json={"puuid": PUUID, "gameName": "Styler", "tagLine": "EUW"}
        )
    )
    respx.get(url__regex=r".*/lol/summoner/v4/.*").mock(
        return_value=httpx.Response(
            200, json={"puuid": PUUID, "profileIconId": 1, "summonerLevel": 30,
                       "revisionDate": 1}
        )
    )
    respx.get(url__regex=r".*/lol/league/v4/.*").mock(return_value=httpx.Response(200, json=[]))


async def _seed_once(patch: str, specs, **kw):
    """Idempotent, because the fixture runs per test but rows are shared."""
    from sqlalchemy import func, select

    from app.db.base import SessionLocal
    from app.db.models import Match

    async with SessionLocal() as session:
        if (await session.execute(
            select(func.count(Match.match_id)).where(Match.patch == patch)
        )).scalar():
            return
    await seed(patch, specs, **kw)


@pytest.fixture
async def games():
    """Six games: four mid on Ahri, one jungle, one support. 1800s each."""
    plan = [
        (AHRI, "MIDDLE", True), (AHRI, "MIDDLE", True),
        (AHRI, "MIDDLE", False), (AHRI, "MIDDLE", False),
        (LEE_SIN, "JUNGLE", True),
        (THRESH, "UTILITY", False),
    ]
    specs = []
    for champion, position, win in plan:
        me = participant(champion, position, 100, win)
        me["puuid"] = PUUID
        me["kills"], me["deaths"], me["assists"] = 6, 3, 9
        me["total_minions"] = 180
        me["vision_score"] = 20
        me["damage_to_champions"] = 18_000
        specs.append([me])
    await _seed_once("AN1.00", specs, game_creation=AFTERNOON_MS, duration=1800)


@respx.mock
async def test_analytics_summarises_role_class_and_activity(client, games):
    mock_identity()
    response = await client.get("/api/summoner/euw1/Styler/EUW/analytics")
    assert response.status_code == 200, response.text[:300]
    body = response.json()

    # States what it is measuring, rather than implying a whole season.
    assert body["basis"] == "stored_matches"
    assert body["games_analysed"] == 6

    roles = {r["position"]: r for r in body["roles"]}
    assert roles["MIDDLE"]["games"] == 4
    assert roles["MIDDLE"]["share"] == pytest.approx(4 / 6)
    assert roles["MIDDLE"]["win_rate"] == pytest.approx(0.5)
    assert sum(r["share"] for r in body["roles"]) == pytest.approx(1.0)

    # Classes come from Data Dragon tags, and a champion can carry several, so
    # these are shares of tag mentions rather than of games.
    tags = {c["tag"] for c in body["classes"]}
    assert "Mage" in tags
    assert sum(c["share"] for c in body["classes"]) == pytest.approx(1.0)

    assert len(body["activity_utc"]) == 24
    assert body["activity_utc"][14] == 6, "all six games were played at 14:30 UTC"
    assert sum(body["activity_utc"]) == 6


@respx.mock
async def test_analytics_champion_table_and_totals(client, games):
    mock_identity()
    body = (await client.get("/api/summoner/euw1/Styler/EUW/analytics")).json()

    top = body["champions"][0]
    assert top["champion"]["name"] == "Ahri"
    assert (top["games"], top["wins"]) == (4, 2)
    # 6 kills + 9 assists over 3 deaths.
    assert top["kda"] == pytest.approx(5.0)
    # 180 CS in a 30 minute game.
    assert top["cs_per_min"] == pytest.approx(6.0)

    totals = body["totals"]
    assert totals["win_rate"] == pytest.approx(3 / 6)
    assert totals["cs_per_min"] == pytest.approx(6.0)
    assert totals["vision_per_game"] == pytest.approx(20.0)


@respx.mock
async def test_a_player_with_nothing_stored_is_not_an_error(client):
    """Analytics are a view over what we hold; holding nothing is normal."""
    empty = "B" * 78
    respx.get(url__regex=r".*/riot/account/v1/.*").mock(
        return_value=httpx.Response(
            200, json={"puuid": empty, "gameName": "Fresh", "tagLine": "EUW"}
        )
    )
    respx.get(url__regex=r".*/lol/summoner/v4/.*").mock(
        return_value=httpx.Response(
            200, json={"puuid": empty, "profileIconId": 1, "summonerLevel": 3,
                       "revisionDate": 1}
        )
    )
    respx.get(url__regex=r".*/lol/league/v4/.*").mock(return_value=httpx.Response(200, json=[]))

    response = await client.get("/api/summoner/euw1/Fresh/EUW/analytics")
    assert response.status_code == 200
    body = response.json()
    assert body["games_analysed"] == 0
    assert body["roles"] == [] and body["champions"] == []


@respx.mock
async def test_queue_filter_narrows_the_sample(client, games):
    mock_identity()
    # The seeded games are queue 420; asking for ARAM must find none of them.
    body = (await client.get("/api/summoner/euw1/Styler/EUW/analytics?queue=450")).json()
    assert body["games_analysed"] == 0
