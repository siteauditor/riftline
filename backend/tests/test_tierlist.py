"""The tier list's reads: the win-rate range, tiers per role, and the measured
lobby ranks behind a slice.

The suite shares one database, so every row here sits on patch ``Q9.01``, which
nothing else uses.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.api.schemas import APEX_BASE, APEX_STRIDE, numeric_rank
from app.db.base import SessionLocal
from app.db.models import ChampionStat, Match
from app.services.aggregate import (
    APEX_BUCKET,
    lobby_rank_mix,
    wilson_lower_bound,
    wilson_upper_bound,
)

PATCH = "Q9.01"


# --------------------------------------------------------------- the range


@pytest.mark.parametrize("wins,games", [(7, 10), (63, 100), (0, 12), (20, 20), (500, 1000)])
def test_the_upper_bound_mirrors_the_lower_one(wins, games):
    low, high = wilson_lower_bound(wins, games), wilson_upper_bound(wins, games)
    assert low <= wins / games <= high
    assert high == pytest.approx(1 - wilson_lower_bound(games - wins, games))


def test_no_games_is_the_widest_range_there_is():
    assert (wilson_lower_bound(0, 0), wilson_upper_bound(0, 0)) == (0.0, 1.0)


# ------------------------------------------------------------ tiers per role


async def seed_stats() -> None:
    """Twelve top laners who all lose to twelve junglers who all win.

    Pooled, the top of the list would be junglers only; per role, each role
    gets its own S.
    """
    async with SessionLocal() as session:
        seeded = (await session.execute(
            select(ChampionStat.id).where(ChampionStat.patch == PATCH).limit(1)
        )).first()
        if seeded:
            return
        rows = []
        for i in range(12):
            for role, base, champion in (("TOP", 40, 9100), ("JUNGLE", 70, 9200)):
                rows.append(ChampionStat(
                    patch=PATCH, queue_id=420, rank_bracket="ALL",
                    champion_id=champion + i, team_position=role,
                    games=100, wins=base - i, pool_games=1000, bans=0,
                    avg_gold_diff_14=250.0 if (role, i) == ("TOP", 0) else None,
                    timeline_games=90 if (role, i) == ("TOP", 0) else 0,
                ))
        session.add_all(rows)
        await session.commit()


async def test_every_role_gets_its_own_tiers_in_the_all_roles_view(client):
    await seed_stats()

    body = (await client.get(
        "/api/meta/champions", params={"patch": PATCH, "min_games": 1}
    )).json()

    rows = body["rows"]
    by_role = {role: [r for r in rows if r["position"] == role] for role in ("TOP", "JUNGLE")}
    for role, group in by_role.items():
        assert len(group) == 12
        # The best of each role is S, and each role gets the S count it would
        # get on its own: the first 10% of twelve.
        assert group[0]["tier"] == "S", role
        assert [r["tier"] for r in group].count("S") == 2, role
    # The list itself is still ordered by the low end, junglers first.
    assert rows[0]["position"] == "JUNGLE"

    top = by_role["TOP"][0]
    assert top["confidence_win_rate"] <= top["win_rate"] <= top["confidence_high"]
    assert (top["avg_gold_diff_14"], top["timeline_games"]) == (250.0, 90)


# -------------------------------------------------------- lobby rank mix


async def seed_lobbies() -> datetime:
    newest = datetime(2026, 9, 18, 12, tzinfo=UTC)
    lobbies = [
        ("Q9_GM", APEX_BASE + APEX_STRIDE + 500, False, newest),
        ("Q9_MASTER", APEX_BASE + 50, False, newest - timedelta(days=1)),
        ("Q9_DIAMOND", numeric_rank("DIAMOND", "II", 50), False, newest - timedelta(days=2)),
        ("Q9_GOLD", numeric_rank("GOLD", "IV", 10), False, newest - timedelta(days=2)),
        ("Q9_UNMEASURED", None, False, None),
        ("Q9_REMAKE", APEX_BASE + 10, True, newest + timedelta(days=1)),
    ]
    async with SessionLocal() as session:
        if await session.get(Match, "Q9_GM"):
            return newest
        session.add_all(
            Match(
                match_id=match_id, platform_id="EUW1", queue_id=420, patch=PATCH,
                game_creation=1, game_duration=1800 if not remake else 200,
                is_remake=remake, teams=[], lobby_rank_points=points,
                lobby_rank_measured_at=measured,
            )
            for match_id, points, remake, measured in lobbies
        )
        await session.commit()
    return newest


async def test_the_lobby_mix_merges_the_apex_tiers_and_skips_remakes():
    newest = await seed_lobbies()

    async with SessionLocal() as session:
        mix = await lobby_rank_mix(session, PATCH, 420)

    assert (mix.total, mix.measured) == (5, 4)
    assert mix.buckets == [(APEX_BUCKET, 2), ("DIAMOND", 1), ("GOLD", 1)]
    # The remake's later measurement does not count.
    assert mix.as_of.replace(tzinfo=UTC) == newest


async def test_the_tier_list_says_how_its_games_were_ranked(client):
    await seed_stats()
    await seed_lobbies()

    body = (await client.get(
        "/api/meta/champions", params={"patch": PATCH, "min_games": 1}
    )).json()

    lobby = body["lobby_ranks"]
    assert (lobby["total"], lobby["measured"]) == (5, 4)
    assert lobby["buckets"][0] == {"tier": APEX_BUCKET, "games": 2}
    assert lobby["as_of"] is not None


# ------------------------------------------------- letters, counts, floors

FIELD = "Q9.02"


async def seed_field() -> None:
    """Twelve mid laners with 100 games each, three with ten, one with gold at
    14 from nine timelines and one from ten."""
    async with SessionLocal() as session:
        if (await session.execute(
            select(ChampionStat.id).where(ChampionStat.patch == FIELD).limit(1)
        )).first():
            return
        rows = [
            ChampionStat(
                patch=FIELD, queue_id=420, rank_bracket="ALL", champion_id=9300 + i,
                team_position="MIDDLE", games=100, wins=62 - 2 * i, pool_games=1000, bans=0,
                timeline_games=9 if i == 0 else 10 if i == 1 else 0,
                avg_gold_diff_14=150.0 if i in (0, 1) else None,
            )
            for i in range(12)
        ] + [
            ChampionStat(
                patch=FIELD, queue_id=420, rank_bracket="ALL", champion_id=9320 + i,
                team_position="MIDDLE", games=10, wins=8, pool_games=1000, bans=0,
            )
            for i in range(3)
        ]
        session.add_all(rows)
        await session.commit()


async def letters(client, min_games: int) -> dict[int, str | None]:
    body = (await client.get(
        "/api/meta/champions", params={"patch": FIELD, "min_games": min_games}
    )).json()
    return {r["champion"]["id"]: r["tier"] for r in body["rows"]}


async def test_letters_are_places_in_the_twenty_game_field_whatever_the_floor(client):
    """Banded inside whatever the box let in, 81 of 175 rows changed letter at
    5 games instead of 20, and the champion page, always at 20, disagreed."""
    await seed_field()

    at_five, at_twenty, at_fifty = [await letters(client, n) for n in (5, 20, 50)]

    assert at_five.keys() > at_twenty.keys()
    for champion, tier in at_twenty.items():
        assert at_five[champion] == tier == at_fifty[champion], champion
    # Under the field a row is listed without a letter.
    assert [at_five[9320 + i] for i in range(3)] == [None, None, None]


async def test_the_list_counts_what_its_games_separate_from_average(client):
    await seed_field()

    body = (await client.get("/api/meta/champions", params={"patch": FIELD})).json()

    rows = body["rows"]
    assert body["tier_min_games"] == 20
    assert body["separated_above"] == sum(1 for r in rows if r["confidence_win_rate"] >= 0.5)
    assert body["separated_below"] == sum(1 for r in rows if r["confidence_high"] <= 0.5)
    assert body["separated_above"] >= 1 and body["separated_below"] >= 1


async def test_gold_at_fourteen_needs_ten_games_with_a_timeline(client):
    await seed_field()

    body = (await client.get("/api/meta/champions", params={"patch": FIELD})).json()

    gold = {r["champion"]["id"]: r["avg_gold_diff_14"] for r in body["rows"]}
    assert (gold[9300], gold[9301]) == (None, 150.0)


async def test_a_floor_above_the_slice_is_an_answer_with_a_way_out(client):
    """It was a 404 whose text told the reader to ingest more matches."""
    await seed_field()

    response = await client.get("/api/meta/champions", params={"patch": FIELD, "min_games": 500})

    assert response.status_code == 200
    body = response.json()
    assert (body["rows"], body["empty_reason"], body["most_games"]) == ([], "min_games", 100)



async def test_a_row_says_when_its_win_rate_moved_since_the_close_earlier_patch(client):
    """Against the close earlier patch, the champion page's rule: marked only
    where the two ranges stop overlapping, which 2 of 293 big moves did."""
    queue = 4430
    async with SessionLocal() as session:
        if not await session.get(Match, "TREND_8_1"):
            for match_id, patch in (("TREND_8_1", "8.1"), ("TREND_8_2", "8.2")):
                session.add(Match(
                    match_id=match_id, platform_id="EUW1", queue_id=queue, patch=patch,
                    game_creation=1, game_duration=1800, is_remake=False, teams=[],
                ))
            for patch, rows in (("8.1", ((9501, 30), (9502, 50))), ("8.2", ((9501, 70), (9502, 50)))):
                for champion, wins in rows:
                    session.add(ChampionStat(
                        patch=patch, queue_id=queue, rank_bracket="ALL", champion_id=champion,
                        team_position="MIDDLE", games=100, wins=wins, pool_games=1000, bans=0,
                    ))
            await session.commit()

    body = (await client.get(
        "/api/meta/champions", params={"patch": "8.2", "queue_id": queue, "min_games": 1}
    )).json()

    assert body["previous_patch"] == "8.1"
    rows = {r["champion"]["id"]: r for r in body["rows"]}
    assert (rows[9501]["previous_win_rate"], rows[9501]["win_rate_moved"]) == (0.3, True)
    assert (rows[9502]["previous_games"], rows[9502]["win_rate_moved"]) == (100, False)
