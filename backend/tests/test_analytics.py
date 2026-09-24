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


# ------------------------------------------------------------ queue scopes

SCOPED = "scoped-analytics".ljust(78, "0")


def mock_scoped_identity():
    respx.get(url__regex=r".*/riot/account/v1/.*").mock(
        return_value=httpx.Response(
            200, json={"puuid": SCOPED, "gameName": "Scoper", "tagLine": "EUW"}
        )
    )
    respx.get(url__regex=r".*/lol/summoner/v4/.*").mock(
        return_value=httpx.Response(
            200, json={"puuid": SCOPED, "profileIconId": 1, "summonerLevel": 30, "revisionDate": 1}
        )
    )
    respx.get(url__regex=r".*/lol/league/v4/.*").mock(return_value=httpx.Response(200, json=[]))


def _mine(champion, position, *, win=True):
    me = participant(champion, position, 100, win)
    me["puuid"] = SCOPED
    return me


@pytest.fixture
async def scoped_games():
    """Twelve solo games, three flex, four ARAM, and one old solo game that
    was reviewed: nineteen ranked and ARAM games in all, twenty with it."""
    from app.db.base import SessionLocal
    from app.db.models import ParticipantReview

    await _seed_once("SC0.00", [[_mine(AHRI, "MIDDLE")]], queue_id=420, game_creation=500)
    await _seed_once("SC1.00", [[_mine(AHRI, "MIDDLE")] for _ in range(8)], queue_id=420, game_creation=1000)
    await _seed_once("SC1.01", [[_mine(AHRI, "MIDDLE")] for _ in range(3)], queue_id=420, game_creation=2000)
    await _seed_once("SC2.00", [[_mine(LEE_SIN, "JUNGLE")] for _ in range(3)], queue_id=440, game_creation=1500)
    await _seed_once("SC3.00", [[_mine(THRESH, "")] for _ in range(4)], queue_id=450, game_creation=1200)
    async with SessionLocal() as session:
        if await session.get(ParticipantReview, 1_000_001) is None:
            session.add(
                ParticipantReview(
                    id=1_000_001, match_id="TSC0.00_0", participant_index=1, puuid=SCOPED,
                    queue_id=420, team_position="MIDDLE", minutes=30.0, deaths=4, untraded=2,
                )
            )
            await session.commit()


@respx.mock
async def test_the_numbers_open_on_ranked_and_say_which_games(client, scoped_games):
    """A profile pooled every queue and read 62% and a 4.47 KDA where the
    ranked games said 50% and 3.85. Ranked now, named on the answer."""
    mock_scoped_identity()
    body = (await client.get("/api/summoner/euw1/Scoper/EUW/analytics")).json()

    assert (body["scope"], body["queues"]) == ("ranked", [420, 440])
    assert body["games_analysed"] == body["stored_total"] == 15
    assert body["window"] == 1000
    assert (body["game_name"], body["tag_line"], body["platform"]) == ("Scoper", "EUW", "euw1")
    held = {s["scope"]: s["games"] for s in body["scope_games"]}
    assert held == {
        "ranked": 15, "solo": 12, "flex": 3, "normal": 0, "swiftplay": 0, "aram": 4, "all": 19,
    }
    assert {r["position"] for r in body["roles"]} == {"MIDDLE", "JUNGLE"}


@respx.mock
async def test_every_queue_one_scope_or_one_queue(client, scoped_games):
    mock_scoped_identity()
    every = (await client.get("/api/summoner/euw1/Scoper/EUW/analytics?scope=all")).json()
    assert (every["scope"], every["queues"], every["games_analysed"]) == ("all", [], 19)

    aram = (await client.get("/api/summoner/euw1/Scoper/EUW/analytics?scope=aram")).json()
    assert (aram["games_analysed"], aram["stored_total"]) == (4, 4)
    assert aram["roles"] == [], "ARAM has no lane roles to share"

    one = (await client.get("/api/summoner/euw1/Scoper/EUW/analytics?queue=440")).json()
    assert (one["scope"], one["queues"], one["games_analysed"]) == (None, [440], 3)


@respx.mock
async def test_every_panel_reads_the_same_window(client, scoped_games):
    """The review read its own newest games, the lanes theirs and the table
    another 300, so one page's panels described different games. The old
    reviewed game is inside a window of every game, and outside the newest ten."""
    mock_scoped_identity()
    wide = (await client.get("/api/summoner/euw1/Scoper/EUW/analytics?scope=solo")).json()
    assert wide["games_analysed"] == 12
    assert [r["games"] for r in wide["review"]] == [1]

    narrow = (await client.get("/api/summoner/euw1/Scoper/EUW/analytics?scope=solo&limit=10")).json()
    assert (narrow["games_analysed"], narrow["stored_total"], narrow["window"]) == (10, 12, 10)
    assert narrow["review"] == []

