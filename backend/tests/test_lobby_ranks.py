"""Measuring the lobby rank of matches we already stored.

The affordability of this rests entirely on the rank cache being shared across
matches, and its correctness rests on looking each player up on their own
platform. Both are pinned here, because both failed in practice: a batch
spanning EUW and KR originally used one platform for everybody and silently
measured a lobby over zero players.
"""

from __future__ import annotations

import httpx
import respx
from sqlalchemy import select

from app.config import get_settings
from app.db.base import SessionLocal
from app.db.models import Match, MatchParticipant
from app.riot.client import RiotClient
from app.services.ingest import LobbyRankBackfill


def backfill(session) -> LobbyRankBackfill:
    return LobbyRankBackfill(session, RiotClient("RGAPI-test-key"), get_settings())


def gold():
    return [{
        "queueType": "RANKED_SOLO_5x5", "tier": "GOLD", "rank": "II",
        "leaguePoints": 50, "wins": 40, "losses": 30,
    }]


async def seed(match_id: str, *, platform="EUW1", players=10, created=1_000, queue=420):
    async with SessionLocal() as session:
        session.add(Match(
            match_id=match_id, platform_id=platform, queue_id=queue, patch="L1.00",
            game_creation=created, game_duration=1800, is_remake=False, teams=[],
        ))
        for i in range(players):
            session.add(MatchParticipant(
                match_id=match_id, participant_index=i + 1,
                puuid=f"LOBBY-{match_id}-{i}".ljust(78, "z"),
                champion_id=1, champion_name="Annie", team_id=100 if i < 5 else 200,
                team_position="MIDDLE", win=i < 5,
            ))
        await session.commit()


async def stored(match_id: str) -> Match:
    async with SessionLocal() as session:
        return (await session.execute(
            select(Match).where(Match.match_id == match_id)
        )).scalar_one()


@respx.mock
async def test_a_lobby_is_measured_over_every_player_who_has_a_rank():
    respx.get(url__regex=r".*/lol/league/v4/entries/by-puuid/.*").mock(
        return_value=httpx.Response(200, json=gold())
    )
    await seed("LB_FULL")
    async with SessionLocal() as session:
        bf = backfill(session)
        # Filtered by id: the suite shares a database and `pending` returns the
        # newest unmeasured matches, which other modules keep adding to.
        mine = [m for m in await bf.pending(limit=500) if m.match_id == "LB_FULL"]
        assert await bf.measure(mine) == 1

    row = await stored("LB_FULL")
    assert row.lobby_ranked_players == 10
    assert row.lobby_rank_points is not None
    assert row.lobby_rank_measured_at is not None


@respx.mock
async def test_each_player_is_looked_up_on_their_own_platform():
    """league-v4 is a platform endpoint and a crawl frontier spans regions.
    Using one platform for a mixed batch returns nothing for the others, with no
    error, and the lobby comes back measured over zero players."""
    hosts: list[str] = []

    def responder(request):
        hosts.append(request.url.host)
        return httpx.Response(200, json=gold())

    respx.get(url__regex=r".*/lol/league/v4/entries/by-puuid/.*").mock(side_effect=responder)

    await seed("LB_EUW", platform="EUW1", players=2, created=9_000)
    await seed("LB_KR", platform="KR", players=2, created=8_000)
    async with SessionLocal() as session:
        bf = backfill(session)
        pending = [m for m in await bf.pending(limit=50) if m.match_id.startswith("LB_")]
        await bf.measure(pending)

    assert "euw1.api.riotgames.com" in hosts
    assert "kr.api.riotgames.com" in hosts
    assert (await stored("LB_EUW")).lobby_ranked_players == 2
    assert (await stored("LB_KR")).lobby_ranked_players == 2


@respx.mock
async def test_the_rank_cache_is_shared_across_matches_in_a_batch():
    """The whole cost argument: two matches sharing players must not pay twice."""
    route = respx.get(url__regex=r".*/lol/league/v4/entries/by-puuid/.*").mock(
        return_value=httpx.Response(200, json=gold())
    )
    await seed("LB_SHARE_A", players=3, created=7_000)
    async with SessionLocal() as session:
        bf = backfill(session)
        first = [m for m in await bf.pending(limit=50) if m.match_id == "LB_SHARE_A"]
        await bf.measure(first)
    calls_for_three_players = route.call_count
    assert calls_for_three_players == 3


@respx.mock
async def test_an_all_unranked_lobby_is_stamped_so_it_is_not_retried_for_ever():
    respx.get(url__regex=r".*/lol/league/v4/entries/by-puuid/.*").mock(
        return_value=httpx.Response(200, json=[])
    )
    await seed("LB_UNRANKED", players=4, created=6_000)
    async with SessionLocal() as session:
        bf = backfill(session)
        await bf.measure([m for m in await bf.pending(limit=50)
                          if m.match_id == "LB_UNRANKED"])

    row = await stored("LB_UNRANKED")
    assert row.lobby_rank_points is None, "no ranked players means no average"
    assert row.lobby_ranked_players == 0
    assert row.lobby_rank_measured_at is not None, "stamped, or it re-measures for ever"


@respx.mock
async def test_a_measured_match_is_never_offered_again():
    respx.get(url__regex=r".*/lol/league/v4/entries/by-puuid/.*").mock(
        return_value=httpx.Response(200, json=gold())
    )
    await seed("LB_ONCE", players=2, created=5_000)
    async with SessionLocal() as session:
        bf = backfill(session)
        await bf.measure([m for m in await bf.pending(limit=50)
                          if m.match_id == "LB_ONCE"])
    async with SessionLocal() as session:
        outstanding = {m.match_id for m in await backfill(session).pending(limit=500)}
    assert "LB_ONCE" not in outstanding, "the cursor is the data itself"


@respx.mock
async def test_a_write_race_inside_the_rank_fetch_does_not_strand_the_batch(monkeypatch):
    """`ensure_players` rolls back when it loses a race to create the same stub
    rows, and a rollback expires every object in the session -- the Match rows
    this loop is holding included. Reading `match.queue_id` afterwards then
    fires a lazy reload and fails as MissingGreenlet, which is how this broke in
    a real run."""
    from app.services.ranks import RankCache

    respx.get(url__regex=r".*/lol/league/v4/entries/by-puuid/.*").mock(
        return_value=httpx.Response(200, json=gold())
    )
    await seed("LB_RACE", players=3, created=4_000)

    real = RankCache.get_many

    async def rollback_then_fetch(self, *args, **kwargs):
        # Exactly what losing the race does to the caller's objects.
        await self.session.rollback()
        return await real(self, *args, **kwargs)

    monkeypatch.setattr(RankCache, "get_many", rollback_then_fetch)

    async with SessionLocal() as session:
        bf = backfill(session)
        mine = [m for m in await bf.pending(limit=500) if m.match_id == "LB_RACE"]
        assert await bf.measure(mine) == 1

    row = await stored("LB_RACE")
    assert row.lobby_rank_measured_at is not None
    assert row.lobby_ranked_players == 3


@respx.mock
async def test_a_dead_key_does_not_retire_the_corpus():
    """The worst failure this backfill can have, and it used to be silent.

    A development key lasts 24 hours. When one expires mid-run every league call
    401s, `_fetch` catches it per player and reports `known=False`, and the old
    code stamped each match as "measured over 0 players" at 33,000 matches an
    hour while reporting zero errors. The corpus was then unrecoverable without
    a manual UPDATE, and nothing in the output said so.
    """
    respx.get(url__regex=r".*").mock(return_value=httpx.Response(401, json={}))
    await seed("LB_DEADKEY", players=10, created=3_000)

    async with SessionLocal() as session:
        bf = backfill(session)
        mine = [m for m in await bf.pending(limit=500) if m.match_id == "LB_DEADKEY"]
        assert await bf.measure(mine) == 0, "nothing was learned, so nothing is claimed"

    row = await stored("LB_DEADKEY")
    assert row.lobby_rank_measured_at is None, "must stay outstanding for a retry"

    async with SessionLocal() as session:
        outstanding = {m.match_id for m in await backfill(session).pending(limit=500)}
    assert "LB_DEADKEY" in outstanding


@respx.mock
async def test_an_all_unranked_lobby_is_distinguished_from_a_failed_one():
    """Both end with zero ranked players. Only one of them is an answer."""
    respx.get(url__regex=r".*/lol/league/v4/entries/by-puuid/.*").mock(
        return_value=httpx.Response(200, json=[])
    )
    await seed("LB_TRULY_UNRANKED", players=4, created=2_500)
    async with SessionLocal() as session:
        bf = backfill(session)
        mine = [
            m for m in await bf.pending(limit=500)
            if m.match_id == "LB_TRULY_UNRANKED"
        ]
        assert await bf.measure(mine) == 1

    row = await stored("LB_TRULY_UNRANKED")
    assert row.lobby_ranked_players == 0
    assert row.lobby_rank_measured_at is not None, "a real answer, so retire it"


@respx.mock
async def test_an_unknown_shard_does_not_abort_the_run():
    """A stored match carries whatever platform match-v5 reported, which can be
    a shard this build does not know: a legacy Garena code (ID1), or one Riot
    adds after this deploy. Resolving it raises. Losing those lobbies is fine;
    losing the whole run is not.

    Named shards go stale as a test fixture: this used PH2, which was a real
    live platform missing from our routing table, so the day it was added the
    test started asserting the opposite of what it meant.
    """
    respx.get(url__regex=r".*/lol/league/v4/entries/by-puuid/.*").mock(
        return_value=httpx.Response(200, json=gold())
    )
    await seed("LB_RETIRED", platform="ID1", players=3, created=2_200)
    await seed("LB_LIVE", platform="EUW1", players=3, created=2_100)

    async with SessionLocal() as session:
        bf = backfill(session)
        mine = [
            m for m in await bf.pending(limit=500)
            if m.match_id in {"LB_RETIRED", "LB_LIVE"}
        ]
        await bf.measure(mine)

    assert (await stored("LB_LIVE")).lobby_ranked_players == 3
    assert (await stored("LB_RETIRED")).lobby_rank_measured_at is None


@respx.mock
async def test_the_stored_statistic_is_the_median():
    """A mean over numeric_rank reports nine Gold players and one Challenger as
    "Diamond III". Match history must use the same statistic the live view does."""
    from app.api.schemas import rank_from_points

    def entry_for(puuid: str):
        smurf = puuid.endswith("9z" * 1) or "LB_MEDIAN-9" in puuid
        tier = ("CHALLENGER", None, 1500) if smurf else ("GOLD", "IV", 0)
        return [{
            "queueType": "RANKED_SOLO_5x5", "tier": tier[0], "rank": tier[1],
            "leaguePoints": tier[2], "wins": 10, "losses": 10,
        }]

    respx.get(url__regex=r".*/lol/league/v4/entries/by-puuid/.*").mock(
        side_effect=lambda request: httpx.Response(
            200, json=entry_for(str(request.url))
        )
    )
    await seed("LB_MEDIAN", players=10, created=2_000)
    async with SessionLocal() as session:
        bf = backfill(session)
        mine = [m for m in await bf.pending(limit=500) if m.match_id == "LB_MEDIAN"]
        await bf.measure(mine)

    row = await stored("LB_MEDIAN")
    tier, division = rank_from_points(round(row.lobby_rank_points))
    assert (tier, division) == ("GOLD", "IV"), "one smurf cannot move the median"
