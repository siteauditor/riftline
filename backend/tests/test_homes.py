"""A player's home shard, and what a view of another shard may do.

On 2026-09-24 one view of ``/summoner/na1/Dekap/EUW`` (a EUW Challenger with a
level 30 NA record) moved the player's row to na1, deleted the EUW rank, made
the stored profile a 404 and moved the prerendered page to the NA path. The
home is now the shard Riot's active-region lookup names, only the home's
record, ranks and mastery are stored, and a view of any other shard reads it
live and writes nothing. See ``app/services/homes.py``.

Every test here mocks the active-region endpoint itself (the suite answers it
with "no answer" otherwise; see ``conftest.py``), and every player has its own
named puuid, because the suite shares one database.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from sqlalchemy import func, select

from app.config import get_settings
from app.db.base import SessionLocal
from app.db.models import (
    ChampionMastery,
    GroupMember,
    Match,
    MatchParticipant,
    Player,
    PlayerGroup,
    RankedEntry,
    RankHistory,
    utcnow,
)
from app.riot.client import RiotClient
from app.services.flight import Flights, flights
from app.services.groups import add_member
from app.services.homes import repair_homes
from app.services.players import PlayerService, normalize_riot_name
from app.services.profile_stats import MIN_SCORED_FOR_PROFILE
from app.services.ranks import RankCache
from app.services.seo import profile_pages
from app.services.suggest import clear_suggest_cache, load_index

pytestmark = pytest.mark.riot_region

ACCOUNT = r".*/riot/account/v1/accounts/by-riot-id/.*"
REGION = r".*/riot/account/v1/region/by-game/lol/by-puuid/.*"


def on(platform: str, path: str) -> str:
    """A route regex for one platform host."""
    return rf".*{platform}\.api\.riotgames\.com{path}"


LEAGUE = "/lol/league/v4/entries/by-puuid/.*"
SUMMONER = "/lol/summoner/v4/summoners/by-puuid/.*"
MASTERY = "/lol/champion-mastery/v4/champion-masteries/by-puuid/.*"


def solo(tier: str, lp: int, division: str = "I") -> list[dict]:
    return [
        {
            "queueType": "RANKED_SOLO_5x5", "tier": tier, "rank": division,
            "leaguePoints": lp, "wins": 300, "losses": 250,
        }
    ]


def record(level: int, icon: int = 4794) -> dict:
    return {"profileIconId": icon, "revisionDate": 1_726_000_000_000, "summonerLevel": level}


def mock_account(puuid: str, name: str, tag: str):
    return respx.get(url__regex=ACCOUNT).mock(
        return_value=httpx.Response(200, json={"puuid": puuid, "gameName": name, "tagLine": tag})
    )


def mock_region(region: str):
    return respx.get(url__regex=REGION).mock(
        return_value=httpx.Response(200, json={"puuid": "x", "game": "lol", "region": region})
    )


async def seed_player(
    puuid: str,
    name: str | None,
    tag: str | None,
    platform: str,
    *,
    searched: bool = True,
    rank: tuple[str, int] | None = None,
    league_platform: str | None = None,
    level: int | None = None,
    summoner_platform: str | None = None,
    account_at: datetime | None = None,
) -> None:
    async with SessionLocal() as session:
        session.add(
            Player(
                puuid=puuid,
                game_name=name,
                tag_line=tag,
                search_name=normalize_riot_name(name) if searched and name else None,
                platform=platform,
                account_fetched_at=account_at,
                summoner_level=level,
                profile_icon_id=1 if level is not None else None,
                summoner_platform=summoner_platform,
                summoner_fetched_at=utcnow() if summoner_platform else None,
                league_platform=league_platform,
                league_fetched_at=utcnow() if league_platform or rank else None,
            )
        )
        if rank is not None:
            session.add(
                RankedEntry(
                    puuid=puuid, queue_type="RANKED_SOLO_5x5", tier=rank[0], division="I",
                    league_points=rank[1], wins=300, losses=250,
                )
            )
        await session.commit()


async def seed_reading(puuid: str, platform: str, tier: str, lp: int, *, taken_at: datetime) -> None:
    async with SessionLocal() as session:
        session.add(
            RankHistory(
                puuid=puuid, platform=platform, queue_type="RANKED_SOLO_5x5", tier=tier,
                division="I", league_points=lp, wins=300, losses=250, taken_at=taken_at,
            )
        )
        await session.commit()


async def seed_games(
    puuid: str,
    platform_id: str,
    count: int,
    *,
    prefix: str,
    creation: int = 1_780_000_000_000,
    remake: bool = False,
    scored: bool = True,
) -> None:
    async with SessionLocal() as session:
        for i in range(count):
            match_id = f"{platform_id}_{prefix}{i}"
            session.add(
                Match(
                    match_id=match_id, platform_id=platform_id, queue_id=420, patch="HOMES",
                    game_creation=creation + i * 1000, game_duration=60 if remake else 1800,
                    is_remake=remake, teams=[],
                )
            )
            session.add(
                MatchParticipant(
                    match_id=match_id, participant_index=1, puuid=puuid, champion_id=103,
                    team_id=100, team_position="MIDDLE", win=True,
                    performance_score=60.0 if scored else None,
                )
            )
        await session.commit()


async def row(puuid: str) -> Player:
    async with SessionLocal() as session:
        return await session.get(Player, puuid)


async def entries(puuid: str) -> list[tuple[str, str | None, int]]:
    async with SessionLocal() as session:
        found = (
            await session.execute(select(RankedEntry).where(RankedEntry.puuid == puuid))
        ).scalars()
        return sorted((e.queue_type, e.tier, e.league_points) for e in found)


async def readings(puuid: str) -> list[tuple[str | None, str | None, int]]:
    async with SessionLocal() as session:
        found = (
            await session.execute(
                select(RankHistory).where(RankHistory.puuid == puuid).order_by(RankHistory.id)
            )
        ).scalars()
        return [(r.platform, r.tier, r.league_points) for r in found]


def service(session, riot, **ttls) -> PlayerService:
    settings = get_settings().model_copy(update=ttls) if ttls else get_settings()
    return PlayerService(session, riot, settings)


# ------------------------------------------------------ the Dekap regression


@respx.mock
async def test_a_view_of_another_shard_leaves_the_home_intact(client):
    """The review's case: a EUW Challenger holding a level 30 NA record, opened
    under na1. The page is answered with the EUW data and told to move there,
    and the row, its rank, its history, its stored profile and its page in the
    manifest are exactly as they were."""
    puuid = "homes-dekap".ljust(78, "0")
    await seed_player(
        puuid, "Dekapper", "EUW", "euw1", rank=("CHALLENGER", 1204), league_platform="euw1",
        level=612, summoner_platform="euw1",
    )
    await seed_reading(puuid, "euw1", "CHALLENGER", 1204, taken_at=utcnow() - timedelta(days=1))
    await seed_games(puuid, "EUW1", MIN_SCORED_FOR_PROFILE, prefix="HD")

    mock_account(puuid, "Dekapper", "EUW")
    mock_region("euw1")
    na_league = respx.get(url__regex=on("na1", LEAGUE)).mock(
        return_value=httpx.Response(200, json=[])
    )
    na_record = respx.get(url__regex=on("na1", SUMMONER)).mock(
        return_value=httpx.Response(200, json=record(30))
    )
    respx.get(url__regex=on("euw1", LEAGUE)).mock(
        return_value=httpx.Response(200, json=solo("CHALLENGER", 1204))
    )
    respx.get(url__regex=on("euw1", SUMMONER)).mock(
        return_value=httpx.Response(200, json=record(612))
    )
    europe_ids = respx.get(url__regex=r".*europe\.api\.riotgames\.com/lol/match/v5/.*/ids.*").mock(
        return_value=httpx.Response(200, json=[])
    )
    americas_ids = respx.get(
        url__regex=r".*americas\.api\.riotgames\.com/lol/match/v5/.*/ids.*"
    ).mock(return_value=httpx.Response(200, json=[]))

    profile = await client.get("/api/summoner/na1/Dekapper/EUW")
    assert profile.status_code == 200, profile.text[:300]
    body = profile.json()
    assert body["shard"] == "absent"
    assert (body["platform"], body["plays_on"], body["home_platform"]) == ("na1", "euw1", "euw1")
    assert [(r["tier"], r["league_points"]) for r in body["ranks"]] == [("CHALLENGER", 1204)]
    assert body["summoner_level"] == 612
    assert na_league.call_count == 1
    assert not na_record.called, "the NA record is not what the page shows"

    # The games come from the home's regional route, not the URL's.
    games = await client.get("/api/summoner/na1/Dekapper/EUW/matches")
    assert games.status_code == 200
    assert europe_ids.called and not americas_ids.called

    stored = await row(puuid)
    assert (stored.platform, stored.league_platform, stored.summoner_platform) == (
        "euw1", "euw1", "euw1"
    )
    assert stored.summoner_level == 612
    assert await entries(puuid) == [("RANKED_SOLO_5x5", "CHALLENGER", 1204)]
    assert all(platform == "euw1" for platform, _, _ in await readings(puuid))

    page = await client.get("/api/summoner/euw1/Dekapper/EUW?source=stored")
    assert page.status_code == 200
    assert page.json()["ranks"][0]["tier"] == "CHALLENGER"
    async with SessionLocal() as session:
        paths = [p.path for p in await profile_pages(session)]
    assert "/summoner/euw1/Dekapper/EUW" in paths
    assert not any(p.startswith("/summoner/na1/Dekapper") for p in paths)


@respx.mock
async def test_a_region_riot_will_not_name_keeps_the_home_the_row_has(client):
    """The active-region lookup failing is not a reason to move anybody."""
    puuid = "homes-noregion".ljust(78, "0")
    await seed_player(puuid, "Unnamed Home", "EUW", "euw1", rank=("GOLD", 40), league_platform="euw1")
    mock_account(puuid, "Unnamed Home", "EUW")
    respx.get(url__regex=REGION).mock(return_value=httpx.Response(400))
    respx.get(url__regex=on("na1", LEAGUE)).mock(return_value=httpx.Response(200, json=[]))
    respx.get(url__regex=on("euw1", LEAGUE)).mock(
        return_value=httpx.Response(200, json=solo("GOLD", 40))
    )
    respx.get(url__regex=on("euw1", SUMMONER)).mock(
        return_value=httpx.Response(200, json=record(80))
    )

    body = (await client.get("/api/summoner/na1/Unnamed Home/EUW")).json()

    assert (body["shard"], body["plays_on"]) == ("absent", "euw1")
    assert (await row(puuid)).platform == "euw1"
    assert await entries(puuid) == [("RANKED_SOLO_5x5", "GOLD", 40)]


@respx.mock
async def test_a_new_player_is_stored_on_the_shard_riot_names(client):
    puuid = "homes-newcomer".ljust(78, "0")
    mock_account(puuid, "Newcomer", "EUW")
    mock_region("euw1")
    respx.get(url__regex=on("na1", LEAGUE)).mock(return_value=httpx.Response(200, json=[]))
    respx.get(url__regex=on("euw1", LEAGUE)).mock(return_value=httpx.Response(200, json=[]))
    respx.get(url__regex=on("euw1", SUMMONER)).mock(
        return_value=httpx.Response(200, json=record(31))
    )

    body = (await client.get("/api/summoner/na1/Newcomer/EUW")).json()

    assert (body["shard"], body["plays_on"]) == ("absent", "euw1")
    assert (await row(puuid)).platform == "euw1"


@respx.mock
async def test_without_a_region_a_new_row_takes_its_newest_games_shard():
    puuid = "homes-guess".ljust(78, "0")
    await seed_games(puuid, "EUW1", 2, prefix="HG")
    mock_account(puuid, "Guessed", "EUW")
    respx.get(url__regex=REGION).mock(return_value=httpx.Response(404))
    async with SessionLocal() as session, RiotClient("RGAPI-test-key") as riot:
        player = await service(session, riot).resolve("na1", "Guessed", "EUW")
        assert player.platform == "euw1"


# ------------------------------------------------------------ presence


@respx.mock
async def test_which_shard_a_view_shows():
    """Home costs nothing; a stored game there is free; a rank there is one
    call; neither is ``absent``; a failure is ``absent`` and is asked again.
    PH2 games count for SG2, which Riot folded PH2 into, and a remake is not
    a game played there."""
    puuid = "homes-presence".ljust(78, "0")
    await seed_player(puuid, "Presence", "OCE", "oc1")
    await seed_games(puuid, "PH2", 1, prefix="HP")
    await seed_games(puuid, "TR1", 1, prefix="HR", remake=True)
    sg2_league = respx.get(url__regex=on("sg2", LEAGUE)).mock(
        return_value=httpx.Response(200, json=[])
    )
    kr_league = respx.get(url__regex=on("kr", LEAGUE)).mock(
        return_value=httpx.Response(200, json=solo("DIAMOND", 20))
    )
    na_league = respx.get(url__regex=on("na1", LEAGUE)).mock(
        return_value=httpx.Response(200, json=[])
    )
    tr_league = respx.get(url__regex=on("tr1", LEAGUE)).mock(
        return_value=httpx.Response(200, json=[])
    )
    eune_league = respx.get(url__regex=on("eun1", LEAGUE)).mock(return_value=httpx.Response(400))

    async with SessionLocal() as session, RiotClient("RGAPI-test-key") as riot:
        players = service(session, riot)
        player = await session.get(Player, puuid)

        assert (await players.view(player, "oc1")).role == "home"
        assert (await players.view(player, "oce")).role == "home", "an alias of the home"

        on_sg2 = await players.view(player, "sg2")
        assert (on_sg2.role, on_sg2.shown.id) == ("second", "sg2")
        assert on_sg2.platform_ids == frozenset({"SG2", "PH2", "TH2"})
        assert not sg2_league.called

        on_kr = await players.view(player, "kr")
        assert (on_kr.role, on_kr.shown.id) == ("second", "kr")
        assert on_kr.league is not None and on_kr.league[0]["tier"] == "DIAMOND"
        assert kr_league.call_count == 1

        on_na = await players.view(player, "na1")
        assert (on_na.role, on_na.shown.id, on_na.platform_ids) == ("absent", "oc1", None)
        assert na_league.call_count == 1

        assert (await players.view(player, "tr1")).role == "absent"
        assert tr_league.call_count == 1

        assert (await players.view(player, "eun1")).role == "absent"
        assert (await players.view(player, "eun1")).role == "absent"
        assert eune_league.call_count == 2, "a failure is not remembered"

        # The prerender's view asks nothing.
        assert (await players.view(player, "na1", live=False)).role == "absent"
        assert na_league.call_count == 1


@respx.mock
async def test_a_second_shard_is_read_and_nothing_is_stored(client):
    """A EUW player with a KR account of their own: the KR page shows KR's rank
    and record, and the row, the EUW rank and the history are untouched."""
    puuid = "homes-second".ljust(78, "0")
    await seed_player(
        puuid, "Twice", "EUW", "euw1", rank=("GOLD", 40), league_platform="euw1",
        level=200, summoner_platform="euw1",
    )
    await seed_reading(puuid, "euw1", "GOLD", 40, taken_at=utcnow() - timedelta(days=1))
    await seed_games(puuid, "KR", 1, prefix="HS")
    mock_account(puuid, "Twice", "EUW")
    mock_region("euw1")
    respx.get(url__regex=on("kr", LEAGUE)).mock(
        return_value=httpx.Response(200, json=solo("DIAMOND", 20, "II"))
    )
    respx.get(url__regex=on("kr", SUMMONER)).mock(return_value=httpx.Response(200, json=record(45)))
    kr_mastery = respx.get(url__regex=on("kr", MASTERY)).mock(
        return_value=httpx.Response(
            200, json=[{"championId": 103, "championLevel": 7, "championPoints": 50_000}]
        )
    )
    asia_ids = respx.get(url__regex=r".*asia\.api\.riotgames\.com/lol/match/v5/.*/ids.*").mock(
        return_value=httpx.Response(200, json=["JP1_900001"])
    )
    jp_match = respx.get(url__regex=r".*/lol/match/v5/matches/JP1_900001$").mock(
        return_value=httpx.Response(404)
    )

    body = (await client.get("/api/summoner/kr/Twice/EUW")).json()
    assert body["shard"] == "second"
    assert (body["platform"], body["home_platform"], body["plays_on"]) == ("kr", "euw1", None)
    assert body["summoner_level"] == 45
    assert [(r["tier"], r["division"]) for r in body["ranks"]] == [("DIAMOND", "II")]
    assert body["updated_at"] is not None

    mastery = (await client.get("/api/summoner/kr/Twice/EUW/mastery")).json()
    assert kr_mastery.called
    assert mastery["platform"] == "kr"
    assert [e["champion"]["id"] for e in mastery["entries"]] == [103]

    # The regional route lists other shards' games too; a JP game is neither
    # shown on the KR page nor fetched for it.
    games = (await client.get("/api/summoner/kr/Twice/EUW/matches")).json()
    assert asia_ids.called and not jp_match.called
    assert games["matches"] == []
    stored_games = (await client.get("/api/summoner/kr/Twice/EUW/matches?source=stored")).json()
    assert [m["match_id"] for m in stored_games["matches"]] == ["KR_HS0"]

    stored = await row(puuid)
    assert (stored.platform, stored.league_platform) == ("euw1", "euw1")
    assert (stored.summoner_level, stored.summoner_platform) == (200, "euw1")
    assert stored.mastery_platform is None
    assert await entries(puuid) == [("RANKED_SOLO_5x5", "GOLD", 40)]
    assert [p for p, _, _ in await readings(puuid)] == ["euw1"]
    async with SessionLocal() as session:
        held = (
            await session.execute(
                select(func.count()).select_from(ChampionMastery).where(
                    ChampionMastery.puuid == puuid
                )
            )
        ).scalar()
    assert held == 0


@respx.mock
async def test_when_riot_moves_the_home_what_was_read_on_the_old_one_goes():
    """An account that transferred: the rank, record and mastery read on the
    old shard describe another shard and are dropped; the history keeps every
    reading, each naming its own shard; group members follow."""
    puuid = "homes-transfer".ljust(78, "0")
    await seed_player(
        puuid, "Mover", "EUW", "euw1", rank=("GOLD", 40), league_platform="euw1",
        level=200, summoner_platform="euw1",
    )
    await seed_reading(puuid, "euw1", "GOLD", 40, taken_at=utcnow() - timedelta(days=3))
    async with SessionLocal() as session:
        session.add(ChampionMastery(puuid=puuid, champion_id=103, champion_points=10))
        player = await session.get(Player, puuid)
        player.mastery_platform = "euw1"
        player.mastery_fetched_at = utcnow()
        group = PlayerGroup(slug="homesmover1", name="Movers", edit_key_hash="x")
        session.add(group)
        await session.flush()
        session.add(GroupMember(group_id=group.id, puuid=puuid, platform="euw1"))
        await session.commit()

    mock_account(puuid, "Mover", "EUW")
    mock_region("na1")
    async with SessionLocal() as session, RiotClient("RGAPI-test-key") as riot:
        player = await service(session, riot).resolve("euw1", "Mover", "EUW")
        assert player.platform == "na1"

    moved = await row(puuid)
    assert (moved.platform, moved.league_platform, moved.summoner_platform) == ("na1", None, None)
    assert (moved.summoner_level, moved.mastery_platform) == (None, None)
    assert await entries(puuid) == []
    assert await readings(puuid) == [("euw1", "GOLD", 40)]
    async with SessionLocal() as session:
        member = (
            await session.execute(select(GroupMember).where(GroupMember.puuid == puuid))
        ).scalar_one()
        masteries = (
            await session.execute(select(ChampionMastery).where(ChampionMastery.puuid == puuid))
        ).scalars().all()
    assert member.platform == "na1"
    assert masteries == []


@respx.mock
async def test_a_group_member_is_stored_on_the_home():
    puuid = "homes-member".ljust(78, "0")
    mock_account(puuid, "Member", "OCE")
    mock_region("sg2")
    respx.get(url__regex=on("sg2", SUMMONER)).mock(return_value=httpx.Response(200, json=record(64)))
    async with SessionLocal() as session, RiotClient("RGAPI-test-key") as riot:
        group = PlayerGroup(slug="homesmember1", name="Members", edit_key_hash="x")
        session.add(group)
        await session.commit()
        member, player = await add_member(session, service(session, riot), group, "Member#OCE", "oc1")
        assert member.platform == "sg2"
        assert (player.summoner_level, player.summoner_platform) == (64, "sg2")


# ----------------------------------------------------- one call per question


@respx.mock
async def test_parallel_lookups_ask_riot_once_each():
    """A profile page sends its requests together, and each resolved the player
    on its own: 6 of 29 calls on one view on 2026-09-24 were repeats. The
    answers are slowed so that all four are inside each question at once."""
    puuid = "homes-parallel".ljust(78, "0")

    def slow(payload):
        async def answer(request):
            await asyncio.sleep(0.05)
            return httpx.Response(200, json=payload)
        return answer

    account = respx.get(url__regex=ACCOUNT).mock(
        side_effect=slow({"puuid": puuid, "gameName": "Parallel", "tagLine": "EUW"})
    )
    region = respx.get(url__regex=REGION).mock(
        side_effect=slow({"puuid": puuid, "game": "lol", "region": "euw1"})
    )
    summoner = respx.get(url__regex=on("euw1", SUMMONER)).mock(side_effect=slow(record(90)))
    league = respx.get(url__regex=on("euw1", LEAGUE)).mock(side_effect=slow(solo("GOLD", 10)))
    mastery = respx.get(url__regex=on("euw1", MASTERY)).mock(
        side_effect=slow([{"championId": 103, "championLevel": 7, "championPoints": 50_000}])
    )
    ttls = {"ttl_account": 300, "ttl_summoner": 300, "ttl_league": 300, "ttl_mastery": 300}

    async def one_request() -> None:
        async with SessionLocal() as session, RiotClient("RGAPI-test-key") as riot:
            players = service(session, riot, **ttls)
            player = await players.resolve("euw1", "Parallel", "EUW")
            await players.ensure_summoner(player)
            await players.ranks(player)
            await players.masteries(player)

    await asyncio.gather(*(one_request() for _ in range(4)))

    assert [r.call_count for r in (account, region, summoner, league, mastery)] == [1] * 5
    assert len(flights) == 0, "no lock outlives its question"


async def test_a_cancelled_waiter_leaves_no_lock_behind():
    own = Flights()
    release = asyncio.Event()

    async def holder() -> None:
        async with own.hold("question"):
            await release.wait()

    async def waiter() -> None:
        async with own.hold("question"):
            pass

    held = asyncio.create_task(holder())
    await asyncio.sleep(0)
    waiting = asyncio.create_task(waiter())
    await asyncio.sleep(0)
    assert len(own) == 1
    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting
    release.set()
    await held
    assert len(own) == 0


# --------------------------------------------------------------- lobbies


@respx.mock
async def test_a_lobby_on_another_shard_does_not_replace_the_home_rank():
    """A live lobby or a stored match on KR reads each player's KR rank. For a
    player whose home is EUW that answer is shown and not stored; a stub made
    for the KR lobby is at home there and is stored."""
    home_euw = "homes-lobby-euw".ljust(78, "0")
    stranger = "homes-lobby-kr".ljust(78, "0")
    await seed_player(home_euw, "Visitor", "EUW", "euw1", rank=("GOLD", 40), league_platform="euw1")
    respx.get(url__regex=on("kr", LEAGUE)).mock(
        return_value=httpx.Response(200, json=solo("DIAMOND", 20))
    )
    async with SessionLocal() as session, RiotClient("RGAPI-test-key") as riot:
        snapshots = await RankCache(session, riot, get_settings()).get_many(
            [home_euw, stranger], "kr"
        )
    assert [(e.tier, e.league_points) for e in snapshots[home_euw].entries] == [("DIAMOND", 20)]
    assert snapshots[home_euw].known and snapshots[stranger].known

    assert await entries(home_euw) == [("RANKED_SOLO_5x5", "GOLD", 40)]
    assert (await row(home_euw)).league_platform == "euw1"
    assert await readings(home_euw) == []
    assert await entries(stranger) == [("RANKED_SOLO_5x5", "DIAMOND", 20)]
    assert ((await row(stranger)).platform, (await row(stranger)).league_platform) == ("kr", "kr")


# ------------------------------------------------------------ suggestions


async def test_one_suggestion_per_riot_id_with_the_homes_rank():
    """A Riot ID names one account, so it is one suggestion, the newest claim;
    and a rank read on another shard is not shown beside the home's link."""
    old = "homes-suggest-old".ljust(78, "0")
    new = "homes-suggest-new".ljust(78, "0")
    elsewhere = "homes-suggest-away".ljust(78, "0")
    await seed_player(old, "Suggested", "HOME", "euw1", account_at=utcnow() - timedelta(days=9))
    await seed_player(new, "Suggested", "HOME", "kr", account_at=utcnow())
    await seed_player(
        elsewhere, "Suggestaway", "HOME", "euw1", rank=("MASTER", 90), league_platform="na1"
    )
    clear_suggest_cache()
    async with SessionLocal() as session:
        index = await load_index(session)
    hits = index.suggest("Suggested#HOME")
    assert [(h.puuid, h.platform) for h in hits] == [(new, "kr")]
    away = index.suggest("Suggestaway")
    assert [(h.puuid, h.tier) for h in away] == [(elsewhere, None)]
    clear_suggest_cache()


# ----------------------------------------------------------------- repair


async def test_the_repair_puts_rows_back_and_restores_what_a_view_deleted():
    """What the old rule left behind, repaired from storage alone."""
    # A searched row a view of NA moved: rank deleted, history intact.
    moved = "homes-repair-moved".ljust(78, "0")
    await seed_player(
        moved, "Repaired", "EUW", "na1", league_platform="na1", level=30,
        summoner_platform="na1", account_at=utcnow(),
    )
    taken = datetime(2026, 9, 20, 12, tzinfo=UTC)
    await seed_reading(moved, "euw1", "CHALLENGER", 1204, taken_at=taken)
    await seed_reading(moved, "na1", "CHALLENGER", 1100, taken_at=taken - timedelta(days=30))
    await seed_games(moved, "EUW1", 2, prefix="RM")
    # A stub from a KR batch whose games are all on EUW, with the KR answer.
    stub = "homes-repair-stub".ljust(78, "0")
    await seed_player(stub, "Stubbed", "EUW", "kr", searched=False, rank=("SILVER", 5),
                      league_platform="kr")
    await seed_games(stub, "EUW1", 1, prefix="RS")
    # A rank read before the stamps existed, on the row's shard.
    legacy = "homes-repair-legacy".ljust(78, "0")
    await seed_player(legacy, "Legacy", "EUW", "euw1", rank=("GOLD", 12))
    # A row under a merged shard's old id.
    alias = "homes-repair-alias".ljust(78, "0")
    await seed_player(alias, "Aliased", "TH2", "th2")
    # Two rows claiming one Riot ID: the older confirmation gives it up.
    stale = "homes-repair-stale".ljust(78, "0")
    fresh = "homes-repair-fresh".ljust(78, "0")
    await seed_player(stale, "Claimed", "EUW", "euw1", account_at=utcnow() - timedelta(days=40))
    await seed_player(fresh, "Claimed", "EUW", "euw1", account_at=utcnow())
    # A group member left on the old shard.
    async with SessionLocal() as session:
        group = PlayerGroup(slug="homesrepair1", name="Repairs", edit_key_hash="x")
        session.add(group)
        await session.flush()
        session.add(GroupMember(group_id=group.id, puuid=moved, platform="na1"))
        await session.commit()
    scope = [moved, stub, legacy, alias, stale, fresh]

    async with SessionLocal() as session:
        before = await _counts(session)
        dry = await repair_homes(session, dry_run=True, puuids=scope)
    assert (dry.searched_moved, dry.stubs_moved, dry.rechecks) == (1, 1, 1)
    assert (dry.ranks_restored, dry.ranks_adopted, dry.aliases) == (1, 1, 1)
    assert (dry.claims_retired, dry.members_synced) == (1, 1)
    assert (await row(moved)).platform == "na1", "a dry run writes nothing"

    async with SessionLocal() as session:
        report = await repair_homes(session, puuids=scope)
        after = await _counts(session)
    assert report.searched_moved == 1 and report.stubs_moved == 1

    repaired = await row(moved)
    assert (repaired.platform, repaired.league_platform) == ("euw1", "euw1")
    assert repaired.account_fetched_at is None, "the next view asks Riot to confirm"
    assert (repaired.summoner_level, repaired.summoner_platform) == (None, None)
    assert await entries(moved) == [("RANKED_SOLO_5x5", "CHALLENGER", 1204)]
    restored_at = repaired.league_fetched_at.replace(tzinfo=UTC)
    assert restored_at == taken, "the restored rank says how old it is"

    moved_stub = await row(stub)
    assert (moved_stub.platform, moved_stub.league_platform) == ("euw1", None)
    assert await entries(stub) == []
    assert (await row(legacy)).league_platform == "euw1"
    assert await entries(legacy) == [("RANKED_SOLO_5x5", "GOLD", 12)]
    assert (await row(alias)).platform == "sg2"
    assert ((await row(stale)).search_name, (await row(fresh)).search_name) == (None, "claimed")
    async with SessionLocal() as session:
        member = (
            await session.execute(select(GroupMember).where(GroupMember.puuid == moved))
        ).scalar_one()
    assert member.platform == "euw1"

    # It may not delete a player or touch history, matches or scores.
    assert after == before

    async with SessionLocal() as session:
        again = await repair_homes(session, puuids=scope)
    assert again.lines() == type(again)(players=len(scope)).lines(), "idempotent"


async def _counts(session) -> tuple[int, int, int, int]:
    async def count(model) -> int:
        return (await session.execute(select(func.count()).select_from(model))).scalar()

    scored = (
        await session.execute(
            select(func.count()).select_from(MatchParticipant).where(
                MatchParticipant.performance_score.is_not(None)
            )
        )
    ).scalar()
    return (await count(Player), await count(RankHistory), await count(Match), scored)
