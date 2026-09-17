"""The puuid-first rank cache that the live lobby and the backfill share.

The whole affordability argument for Group C rests on this module: a player
appears in six matches on average, so ranks have to be cached per *player* and
not per lookup. These tests pin that, and pin the distinction between "unranked"
and "we did not find out", which is the difference between a fact and a guess.
"""

from __future__ import annotations

import httpx
import pytest
import respx
from sqlalchemy import select

from app.config import get_settings
from app.db.base import SessionLocal
from app.db.models import Match, MatchParticipant, Player, RankedEntry
from app.riot.client import RiotClient
from app.services.ranks import RankCache, is_fresh

PLATFORM = "euw1"


def puuid_for(label: str) -> str:
    """A PUUID nothing else in the suite can collide with.

    The suite shares one database, and single-letter PUUIDs are already spoken
    for: fixtures.PUUID is puuid_for("cache"), OTHER_PUUID is puuid_for("stale-a"), and
    test_integration uses puuid_for("real"). Namespacing here is the same trick
    test_aggregate uses with its private patch strings.
    """
    return f"RANKS-{label}".ljust(78, "z")


def entry(queue="RANKED_SOLO_5x5", tier="GOLD", division="II", lp=42):
    return {
        "queueType": queue, "tier": tier, "rank": division, "leaguePoints": lp,
        "wins": 30, "losses": 20, "hotStreak": False, "veteran": False,
        "freshBlood": False, "inactive": False,
    }


def cache(session) -> RankCache:
    return RankCache(session, RiotClient("RGAPI-test-key"), get_settings())


# conftest pins every TTL to 0 so the rest of the suite always exercises the
# fetch path. Caching is the thing under test here, so these pass a real one.
TTL = 300


def mock_league(payload=None, *, status=200):
    return respx.get(url__regex=r".*/lol/league/v4/entries/by-puuid/.*").mock(
        return_value=httpx.Response(status, json=payload if payload is not None else [entry()])
    )


async def seed_match_with(puuid: str, name: str, tag: str, *, match_id: str, created: int):
    """A stored match is where free names come from, so tests need real ones."""
    async with SessionLocal() as session:
        session.add(Match(
            match_id=match_id, platform_id="EUW1", queue_id=420, patch="R1.00",
            game_creation=created, game_duration=1800, is_remake=False, teams=[],
        ))
        session.add(MatchParticipant(
            match_id=match_id, participant_index=1, puuid=puuid,
            riot_id_game_name=name, riot_id_tagline=tag,
            champion_id=1, champion_name="Annie", team_id=100,
            team_position="MIDDLE", win=True,
        ))
        await session.commit()


# ----------------------------------------------------------------- players


async def test_a_bare_puuid_gets_a_player_row_so_the_rank_foreign_key_holds():
    """ranked_entries.puuid is an FK to players.puuid. SQLite does not enforce
    it here but Postgres would, and this project stays portable."""
    puuid = puuid_for("fk")
    async with SessionLocal() as session:
        made = await cache(session).ensure_players([puuid], PLATFORM)
        await session.commit()
        assert made[puuid].puuid == puuid

    async with SessionLocal() as session:
        row = await session.get(Player, puuid)
        assert row is not None
        assert row.platform == PLATFORM
        # A stub must stay invisible to Riot ID lookups, which match on
        # search_name. Otherwise it would shadow the real account.
        assert row.search_name is None


async def test_a_stub_is_named_for_free_from_a_stored_match():
    puuid = puuid_for("name")
    await seed_match_with(puuid, "FreeName", "EUW", match_id="R_NAME_1", created=1_000)
    async with SessionLocal() as session:
        await cache(session).ensure_players([puuid], PLATFORM)
        await session.commit()
    async with SessionLocal() as session:
        row = await session.get(Player, puuid)
    assert (row.game_name, row.tag_line) == ("FreeName", "EUW")


async def test_the_newest_name_wins_because_people_rename():
    """riot_id_game_name is the name as of that match. Taking whichever row the
    database happens to return can resurrect a name abandoned years ago."""
    puuid = puuid_for("rename")
    await seed_match_with(puuid, "OldName", "EUW", match_id="R_NAME_2", created=1_000)
    await seed_match_with(puuid, "NewName", "EUW", match_id="R_NAME_3", created=9_000)
    async with SessionLocal() as session:
        names = await cache(session).names_from_matches([puuid])
    assert names[puuid] == ("NewName", "EUW")


async def test_ensure_players_leaves_a_real_player_untouched():
    puuid = puuid_for("real")
    async with SessionLocal() as session:
        session.add(Player(
            puuid=puuid, platform=PLATFORM, game_name="Real",
            search_name="real", tag_line="EUW", summoner_level=300,
        ))
        await session.commit()
    async with SessionLocal() as session:
        await cache(session).ensure_players([puuid], PLATFORM)
        await session.commit()
    async with SessionLocal() as session:
        row = await session.get(Player, puuid)
    assert (row.game_name, row.search_name, row.summoner_level) == ("Real", "real", 300)


# ------------------------------------------------------------------- ranks


@respx.mock
async def test_ranks_are_fetched_once_then_served_from_cache():
    """The entire cost argument for Group C: the second match containing this
    player must be free."""
    puuid = puuid_for("cache")
    route = mock_league()
    async with SessionLocal() as session:
        first = await cache(session).get_many([puuid], PLATFORM, ttl=TTL)
    assert route.call_count == 1
    assert first[puuid].known
    assert first[puuid].entries[0].tier == "GOLD"

    async with SessionLocal() as session:
        second = await cache(session).get_many([puuid], PLATFORM, ttl=TTL)
    assert route.call_count == 1, "a cached player must not be re-fetched"
    assert second[puuid].entries[0].tier == "GOLD"


@respx.mock
async def test_only_the_stale_players_are_fetched():
    cached_puuid, fresh_puuid = puuid_for("stale-a"), puuid_for("stale-b")
    route = mock_league()
    async with SessionLocal() as session:
        await cache(session).get_many([cached_puuid], PLATFORM, ttl=TTL)
    # respx keys routes by pattern, so re-mocking returns the same object and
    # the count keeps accumulating. Measure the delta, not the total.
    after_warmup = route.call_count

    mock_league([entry(tier="DIAMOND", division="IV")])
    async with SessionLocal() as session:
        out = await cache(session).get_many(
            [cached_puuid, fresh_puuid], PLATFORM, ttl=TTL
        )
    assert route.call_count - after_warmup == 1, "only the unknown player costs a call"
    assert out[cached_puuid].entries[0].tier == "GOLD", "served from cache"
    assert out[fresh_puuid].entries[0].tier == "DIAMOND", "freshly fetched"


@respx.mock
async def test_a_player_with_no_ranked_entry_is_known_and_unranked():
    """Empty is an answer. It must not read as a failed lookup."""
    puuid = puuid_for("unranked")
    mock_league([])
    async with SessionLocal() as session:
        out = await cache(session).get_many([puuid], PLATFORM)
    assert out[puuid].known is True
    assert out[puuid].entries == []


@respx.mock
async def test_a_failed_lookup_is_unknown_rather_than_unranked():
    """The distinction the whole dataclass exists for: reporting a 500 as
    'unranked' would be inventing a fact about somebody."""
    puuid = puuid_for("failed")
    respx.get(url__regex=r".*/lol/league/v4/entries/by-puuid/.*").mock(
        return_value=httpx.Response(500, json={})
    )
    async with SessionLocal() as session:
        out = await cache(session).get_many([puuid], PLATFORM)
    assert out[puuid].known is False
    assert out[puuid].entries == []


@respx.mock
async def test_a_queue_the_player_dropped_out_of_is_removed():
    puuid = puuid_for("dropped")
    mock_league([entry(), entry(queue="RANKED_FLEX_SR", tier="SILVER")])
    async with SessionLocal() as session:
        first = await cache(session).get_many([puuid], PLATFORM)
    assert len(first[puuid].entries) == 2

    mock_league([entry()])
    async with SessionLocal() as session:
        out = await cache(session).get_many([puuid], PLATFORM, refresh=True)
    assert [e.queue_type for e in out[puuid].entries] == ["RANKED_SOLO_5x5"]

    async with SessionLocal() as session:
        rows = (await session.execute(
            select(RankedEntry).where(RankedEntry.puuid == puuid)
        )).scalars().all()
    assert len(rows) == 1, "the phantom flex rank must be gone from the table too"


@respx.mock
async def test_a_whole_lobby_resolves_in_one_pass():
    puuids = [puuid_for(f"lobby-{i}") for i in range(9)]
    route = mock_league()
    async with SessionLocal() as session:
        out = await cache(session).get_many(puuids, PLATFORM)
    assert route.call_count == 9
    assert all(out[p].known for p in puuids)
    assert len(out) == 9


@respx.mock
async def test_duplicate_puuids_cost_one_call():
    puuid = puuid_for("dupe")
    route = mock_league()
    async with SessionLocal() as session:
        out = await cache(session).get_many([puuid, puuid, puuid], PLATFORM)
    assert route.call_count == 1
    assert len(out) == 1


async def test_an_empty_request_does_no_work():
    async with SessionLocal() as session:
        assert await cache(session).get_many([], PLATFORM) == {}
        assert await cache(session).ensure_players([], PLATFORM) == {}


# ------------------------------------------------------------------ is_fresh


def test_is_fresh_treats_a_missing_stamp_as_stale():
    assert is_fresh(None, 300) is False


def test_is_fresh_handles_the_naive_datetimes_sqlite_returns():
    from datetime import UTC, datetime, timedelta

    naive = datetime.now(UTC).replace(tzinfo=None)
    assert is_fresh(naive, 300) is True
    assert is_fresh(naive - timedelta(seconds=600), 300) is False


@pytest.mark.parametrize("ttl", [0, -1])
def test_a_zero_or_negative_ttl_always_refetches(ttl):
    from datetime import UTC, datetime

    assert is_fresh(datetime.now(UTC), ttl) is False


@respx.mock
async def test_a_lost_race_recreates_the_rows_it_rolled_back():
    """A rollback discards every insert in the transaction, not only the one
    that collided. Re-reading alone recovered whatever the racing request
    happened to create and silently dropped the rest, and `get_many` then raised
    KeyError on the first one missing -- a 500 on the live-game endpoint under
    exactly the concurrency a polling live view creates.
    """
    lobby = [puuid_for(f"race-{i}") for i in range(9)]
    shared = lobby[3]
    mock_league()

    async with SessionLocal() as session:
        cache_ = cache(session)
        real_commit = session.commit
        fired = {"done": False}

        async def racing_commit():
            # Another request commits one shared stub just before ours lands.
            if not fired["done"]:
                fired["done"] = True
                async with SessionLocal() as other:
                    other.add(Player(puuid=shared, platform=PLATFORM))
                    await other.commit()
            return await real_commit()

        session.commit = racing_commit
        out = await cache_.get_many(lobby, PLATFORM, ttl=TTL)

    assert len(out) == 9, "every puuid the caller asked about is answered"
    assert all(snapshot.known for snapshot in out.values())

    async with SessionLocal() as session:
        rows = (await session.execute(
            select(Player).where(Player.puuid.in_(lobby))
        )).scalars().all()
    assert len(rows) == 9, "the rolled-back stubs must be recreated, not lost"


@respx.mock
async def test_one_malformed_response_costs_one_player_not_the_lobby():
    """A 200 carrying an HTML error page raises JSONDecodeError, which is not a
    RiotApiError. Escaping `gather` it failed the whole lobby and left the
    sibling coroutines running as orphans, still spending the rate limit."""
    lobby = [puuid_for(f"malformed-{i}") for i in range(4)]
    bad = lobby[1]

    def responder(request):
        if bad in str(request.url):
            return httpx.Response(200, text="<html>upstream error</html>")
        return httpx.Response(200, json=[entry()])

    respx.get(url__regex=r".*/lol/league/v4/entries/by-puuid/.*").mock(
        side_effect=responder
    )
    async with SessionLocal() as session:
        out = await cache(session).get_many(lobby, PLATFORM, ttl=TTL)

    assert len(out) == 4
    assert out[bad].known is False, "the broken one degrades"
    assert all(out[p].known for p in lobby if p != bad), "the rest still resolve"
