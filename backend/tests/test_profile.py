"""The profile page's backend: scores at fetch, the per-role breakdown, champion
rows, ladder position, the refresh floor and rank history.

The suite shares one database, so everything here uses queues 7401 and up,
platform tr1 for ladders, and puuids named ``qzp-...``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.db.base import SessionLocal
from app.db.models import (
    LadderEntry,
    Match,
    MatchParticipant,
    Player,
    RankedEntry,
    RankHistory,
)
from app.riot.client import RiotClient
from app.services.ladders import LadderService
from app.services.matches import MatchService, PlayedRow
from app.services.players import PlayerService
from app.services.profile_stats import (
    MIN_SCORED_FOR_PROFILE,
    champion_totals,
    score_profile,
)
from app.services.ranks import apply_league_entries
from app.services.scores import COMPONENTS, ScoreService
from tests import fixtures as fx
from tests.test_integration import mock_riot
from tests.test_scores import seed_distributions
from tests.test_timeline_storage import mock_timeline, paired_match, timeline_payload
from tests.test_timeline_storage import service as timeline_service


async def load(match_id: str) -> Match:
    async with SessionLocal() as session:
        return (
            await session.execute(
                select(Match)
                .where(Match.match_id == match_id)
                .options(selectinload(Match.participants))
            )
        ).scalars().one()


async def fetch_page(client, match_id: str) -> dict:
    response = await client.get("/api/summoner/euw1/Caps/EUW/matches?count=1")
    assert response.status_code == 200, response.text
    [match] = [m for m in response.json()["matches"] if m["match_id"] == match_id]
    return match


# ----------------------------------------------------------- score at fetch


@respx.mock
async def test_a_fetched_game_is_scored_before_the_page_returns(client):
    await seed_distributions(7401)
    match_id = "EUW1_7401000001"
    mock_riot(matches=[fx.match(match_id, queue=7401)], match_ids=[match_id])

    match = await fetch_page(client, match_id)

    assert match["score"] is not None
    assert match["placement"] is not None
    stored = await load(match_id)
    assert all(p.time_dead is not None for p in stored.participants)
    assert all(p.performance_scored_at is not None for p in stored.participants)


@respx.mock
async def test_a_game_in_a_thin_queue_is_lifted_and_stamped_but_not_scored(client):
    match_id = "EUW1_7402000001"
    mock_riot(matches=[fx.match(match_id, queue=7402)], match_ids=[match_id])

    match = await fetch_page(client, match_id)

    assert match["score"] is None
    stored = await load(match_id)
    assert all(p.time_dead is not None for p in stored.participants)
    # Considered, so the nightly pass does not offer it again.
    assert all(p.performance_scored_at is not None for p in stored.participants)
    assert all(p.performance_score is None for p in stored.participants)


@respx.mock
async def test_an_old_unlifted_game_is_lifted_and_scored_when_its_page_is_viewed(client):
    """The backlog left by fetches before scoring moved to fetch time."""
    match_id = "EUW1_7403000001"
    async with SessionLocal() as session:
        MatchService(session, RiotClient("RGAPI-test-key"), get_settings())._store(
            fx.match(match_id, queue=7403)
        )
        await session.commit()
        for p in (await load(match_id)).participants:
            row = await session.get(MatchParticipant, p.id)
            row.time_dead = None
            row.performance_scored_at = None
        await session.commit()
    await seed_distributions(7403)
    # Only the id list is mocked: the match is stored, so fetching its detail
    # again would hit an unmocked route and drop it from the page.
    mock_riot(match_ids=[match_id])

    match = await fetch_page(client, match_id)

    assert match["score"] is not None


@respx.mock
async def test_a_scoring_failure_still_returns_the_page(client, monkeypatch):
    await seed_distributions(7405)
    match_id = "EUW1_7405000001"
    mock_riot(matches=[fx.match(match_id, queue=7405)], match_ids=[match_id])

    async def explode(self, matches):
        raise RuntimeError("scoring broke")

    monkeypatch.setattr(ScoreService, "score_and_stamp", explode)
    match = await fetch_page(client, match_id)

    assert match["score"] is None
    assert match["match_id"] == match_id


@respx.mock
async def test_a_timeline_arriving_after_the_score_brings_the_lane_lead_badge(client):
    await seed_distributions(7404)
    match_id = "EUW1_7404000001"
    payload = paired_match(match_id)
    payload["info"]["queueId"] = 7404
    mock_riot(matches=[payload], match_ids=[match_id])
    await fetch_page(client, match_id)
    before = await load(match_id)
    assert all("lane_lead" not in (p.performance_detail or {}).get("badges", [])
               for p in before.participants)

    mock_timeline(timeline_payload())
    async with SessionLocal() as session:
        stored = list((await session.execute(
            select(Match).where(Match.match_id == match_id))).scalars())
        await timeline_service(session).ensure_timelines(stored)

    cleared = await load(match_id)
    assert all(p.performance_scored_at is None for p in cleared.participants)

    # Only this lobby: the suite shares a database, and the batch would score
    # every other test's rows too.
    async with SessionLocal() as session:
        match = (await session.execute(
            select(Match).where(Match.match_id == match_id)
            .options(selectinload(Match.participants)))).scalars().one()
        await ScoreService(session).score_and_stamp([match])
        await session.commit()

    after = await load(match_id)
    blue_mid = next(p for p in after.participants if p.participant_index == 1)
    assert "lane_lead" in blue_mid.performance_detail["badges"]
    assert blue_mid.performance_score == next(
        p.performance_score for p in before.participants if p.participant_index == 1
    )


# ------------------------------------------------------- score profile


def played(position: str, score: float | None, *, rank: int = 3, badges=(),
           components=None, champion_id: int = 1, gold: int | None = None,
           win: bool = True, created: int = 0) -> PlayedRow:
    detail = None
    if score is not None:
        detail = {
            "components": components or {
                "kill_part": 0.5, "damage": 0.5, "efficiency": 0.5, "economy": 0.5,
                "survival": 0.5, "objectives": 0.5, "vision": 0.9,
            },
            "badges": list(badges),
            "sample": 2800,
        }
    return PlayedRow(
        champion_id=champion_id, team_position=position, win=win, kills=4, deaths=2,
        assists=6, total_minions=180, vision_score=20, damage_to_champions=18_000,
        queue_id=420, game_creation=created, game_duration=1800,
        performance_score=score, performance_rank=rank if score is not None else None,
        performance_detail=detail, gold_diff_14=gold,
    )


def test_the_score_profile_averages_each_role_and_withholds_thin_ones():
    rows = [played("JUNGLE", 6.0, rank=2, badges=["mvp"]) for _ in range(9)]
    rows.append(played("JUNGLE", 8.0, rank=1, badges=["mvp", "deathless"]))
    rows += [played("UTILITY", 4.0, rank=7, badges=["ace"]) for _ in range(3)]
    rows.append(played("JUNGLE", None))  # withheld games do not count

    jungle, support = score_profile(rows)

    assert (jungle.position, jungle.scored_games, jungle.enough) == ("JUNGLE", 10, True)
    assert jungle.avg_score == pytest.approx(6.2)
    assert jungle.avg_placement == pytest.approx(1.9)
    assert (jungle.mvp, jungle.ace, jungle.sample) == (10, 0, 2800)
    # Highest first.
    assert jungle.components[0].id == "vision"
    assert jungle.components[0].avg_percentile == pytest.approx(0.9)
    assert (support.scored_games, support.enough, support.ace) == (3, False, 3)
    assert MIN_SCORED_FOR_PROFILE == 10


def test_champion_rows_carry_their_own_counts():
    rows = [
        played("MIDDLE", 7.0, champion_id=103, gold=500, created=3),
        played("MIDDLE", 5.0, champion_id=103, created=2, win=False),
        played("TOP", None, champion_id=103, created=1),
        played("MIDDLE", None, champion_id=64, created=4),
    ]

    ahri, lee = champion_totals(rows)

    assert (ahri.champion_id, ahri.games, ahri.wins) == (103, 3, 2)
    assert (ahri.scored_games, ahri.score_total) == (2, 12.0)
    assert (ahri.timeline_games, ahri.gold_diff_total) == (1, 500)
    assert (ahri.main_position, ahri.last_played) == ("MIDDLE", 3)
    assert (lee.games, lee.scored_games) == (1, 0)


@respx.mock
async def test_analytics_carries_the_score_profile_and_scored_champion_rows(client):
    await seed_distributions(7406)
    match_id = "EUW1_7406000001"
    mock_riot(matches=[fx.match(match_id, queue=7406)], match_ids=[match_id])
    await fetch_page(client, match_id)

    body = (await client.get("/api/summoner/euw1/Caps/EUW/analytics?queue=7406")).json()

    [ahri] = body["champions"]
    assert (ahri["games"], ahri["scored_games"]) == (1, 1)
    assert ahri["avg_score"] is not None
    [mid] = body["score_profile"]
    assert (mid["position"], mid["scored_games"], mid["enough"]) == ("MIDDLE", 1, False)
    assert mid["min_scored"] == MIN_SCORED_FOR_PROFILE
    assert len(mid["components"]) == len(COMPONENTS)


# ----------------------------------------------------------- ladder position


LADDER_PLATFORM = "tr1"


async def seed_ladder(tier: str, puuid: str, position: int, *, total: int | None,
                      age: timedelta = timedelta(hours=1)) -> None:
    async with SessionLocal() as session:
        service = LadderService(session, RiotClient("RGAPI-test-key"), get_settings())
        session.add(LadderEntry(
            platform=LADDER_PLATFORM, queue_type="RANKED_SOLO_5x5", tier=tier,
            division="I", puuid=puuid, position=position, league_points=900,
            fetched_at=datetime.now(UTC) - age,
        ))
        await service._record_meta(LADDER_PLATFORM, "RANKED_SOLO_5x5", tier, "I",
                                   total=total, stored=1, truncated=False)
        await session.commit()


async def position(puuid: str, tier: str):
    async with SessionLocal() as session:
        service = LadderService(session, RiotClient("RGAPI-test-key"), get_settings())
        return await service.position_of(puuid, LADDER_PLATFORM, tier)


async def test_the_region_rank_counts_everyone_in_the_tiers_above():
    await seed_ladder("CHALLENGER", "qzp-chall".ljust(78, "0"), 12, total=200)
    await seed_ladder("GRANDMASTER", "qzp-gm".ljust(78, "0"), 57, total=500)

    gm = await position("qzp-gm".ljust(78, "0"), "GRANDMASTER")

    assert (gm.tier, gm.tier_position, gm.position) == ("GRANDMASTER", 57, 257)
    assert gm.platform == LADDER_PLATFORM


async def test_no_position_from_a_stale_snapshot_or_a_tier_they_left():
    stale = "qzp-stale".ljust(78, "0")
    await seed_ladder("MASTER", stale, 3, total=4000, age=timedelta(days=3))
    promoted = "qzp-promoted".ljust(78, "0")
    await seed_ladder("MASTER", promoted, 1, total=4000)

    assert await position(stale, "MASTER") is None
    # Promoted since the snapshot: the Master position is no longer theirs.
    assert await position(promoted, "GRANDMASTER") is None
    assert await position(promoted, "DIAMOND") is None


async def test_a_tier_position_without_a_region_rank_when_a_total_is_unknown():
    puuid = "qzp-master".ljust(78, "0")
    async with SessionLocal() as session:
        session.add(LadderEntry(
            platform="me1", queue_type="RANKED_SOLO_5x5", tier="MASTER", division="I",
            puuid=puuid, position=40, league_points=300, fetched_at=datetime.now(UTC),
        ))
        await session.commit()
    async with SessionLocal() as session:
        service = LadderService(session, RiotClient("RGAPI-test-key"), get_settings())
        found = await service.position_of(puuid, "me1", "MASTER")

    assert (found.tier_position, found.position) == (40, None)


# ---------------------------------------------------------------- refresh


def mock_player(puuid: str, name: str):
    respx.get(url__regex=r".*/riot/account/v1/accounts/by-riot-id/.*").mock(
        return_value=httpx.Response(200, json={"puuid": puuid, "gameName": name,
                                               "tagLine": "EUW"})
    )
    respx.get(url__regex=r".*/lol/summoner/v4/summoners/by-puuid/.*").mock(
        return_value=httpx.Response(200, json={"puuid": puuid, "profileIconId": 1,
                                               "summonerLevel": 30, "revisionDate": 1})
    )
    return respx.get(url__regex=r".*/lol/league/v4/entries/by-puuid/.*").mock(
        return_value=httpx.Response(200, json=fx.league_entries())
    )


@respx.mock
async def test_a_refresh_inside_a_minute_is_served_from_the_cache():
    league = mock_player("qzp-floor".ljust(78, "0"), "Floorer")
    # The suite zeroes every TTL; the floor only means anything under a real one.
    settings = get_settings().model_copy(update={"ttl_league": 300})
    client = RiotClient("RGAPI-test-key")
    async with SessionLocal() as session:
        players = PlayerService(session, client, settings)
        player = await players.resolve("euw1", "Floorer", "EUW")
        await players.ranks(player, refresh=True)
        await players.ranks(player, refresh=True)
        assert league.call_count == 1

        player.league_fetched_at = datetime.now(UTC) - timedelta(minutes=2)
        await session.commit()
        await players.ranks(player, refresh=True)
        assert league.call_count == 2


# ---------------------------------------------------------- rank history


def solo(tier: str, lp: int, wins: int = 50, losses: int = 40) -> dict:
    return {"queueType": "RANKED_SOLO_5x5", "tier": tier, "rank": "II",
            "leaguePoints": lp, "wins": wins, "losses": losses}


async def history_rows(puuid: str) -> list[RankHistory]:
    async with SessionLocal() as session:
        return list((await session.execute(
            select(RankHistory).where(RankHistory.puuid == puuid)
            .order_by(RankHistory.taken_at))).scalars())


async def apply(puuid: str, entries: list[dict]) -> None:
    async with SessionLocal() as session:
        current = list((await session.execute(
            select(RankedEntry).where(RankedEntry.puuid == puuid))).scalars())
        await apply_league_entries(session, puuid, entries, current, platform="euw1")
        await session.commit()


async def test_a_reading_is_kept_only_when_the_rank_changed():
    puuid = "qzp-history".ljust(78, "0")
    async with SessionLocal() as session:
        session.add(Player(puuid=puuid, platform="euw1"))
        await session.commit()

    await apply(puuid, [solo("GOLD", 50)])
    await apply(puuid, [solo("GOLD", 50)])
    await apply(puuid, [solo("GOLD", 71, wins=51)])

    rows = await history_rows(puuid)
    assert [(r.tier, r.league_points, r.platform) for r in rows] == [
        ("GOLD", 50, "euw1"), ("GOLD", 71, "euw1"),
    ]


@respx.mock
async def test_a_rank_stored_before_history_existed_gets_a_first_reading():
    """Otherwise a rank that sits still after this shipped never starts a graph."""
    puuid = "qzp-baseline".ljust(78, "0")
    mock_player(puuid, "Baseliner")
    async with SessionLocal() as session:
        players = PlayerService(session, RiotClient("RGAPI-test-key"), get_settings())
        player = await players.resolve("euw1", "Baseliner", "EUW")
        await players.ranks(player)
        await session.execute(delete(RankHistory).where(RankHistory.puuid == puuid))
        await session.commit()

        await players.ranks(player)  # unchanged, but nothing on record
        await players.ranks(player)  # unchanged, and now on record

    # One reading per queue in the fixture (solo and flex), then nothing.
    assert len(await history_rows(puuid)) == 2


@respx.mock
async def test_the_rank_history_endpoint_returns_readings_oldest_first(client):
    puuid = "qzp-graph".ljust(78, "0")
    mock_player(puuid, "Grapher")
    await client.get("/api/summoner/euw1/Grapher/EUW")
    async with SessionLocal() as session:
        session.add(RankHistory(puuid=puuid, platform="euw1",
                                queue_type="RANKED_SOLO_5x5", tier="PLATINUM",
                                division="IV", league_points=10,
                                taken_at=datetime.now(UTC) - timedelta(days=5)))
        await session.commit()

    body = (await client.get("/api/summoner/euw1/Grapher/EUW/rank-history")).json()

    points = body["points"]
    assert len(points) >= 2
    assert points[0]["tier"] == "PLATINUM"
    assert [p["at"] for p in points] == sorted(p["at"] for p in points)
    assert body["tracking_since"] == points[0]["at"]
    assert points[-1]["numeric_rank"] > points[0]["numeric_rank"]
