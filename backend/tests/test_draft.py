"""The draft advisor: candidate selection, bracket isolation, matchup shrinkage.

These work directly against seeded rollup rows rather than through a crawl, so
they exercise the advisor's own logic without depending on what a corpus happens
to contain.
"""

from __future__ import annotations

import pytest

from app.db.base import SessionLocal
from app.db.models import ChampionStat, MatchupStat
from app.services.aggregate import ALL_BRACKETS
from app.services.draft import MATCHUP_SHRINKAGE, DraftAdvisor, DraftContext

PATCH = "D1.00"
POSITION = "BOTTOM"


async def seed_stat(champion_id, games, wins, *, patch=PATCH, bracket=ALL_BRACKETS):
    async with SessionLocal() as session:
        session.add(
            ChampionStat(
                patch=patch, queue_id=420, rank_bracket=bracket,
                team_position=POSITION, champion_id=champion_id,
                games=games, wins=wins, bans=0, pool_games=max(games, 100),
                avg_kills=6.0, avg_deaths=5.0, avg_assists=9.0,
                avg_cs_per_min=8.0, avg_gold=12000, avg_damage=20000, avg_vision=20,
                timeline_games=0,
            )
        )
        await session.commit()


async def seed_matchup(champion_id, enemy_id, games, wins, *,
                       patch=PATCH, bracket=ALL_BRACKETS, scope="LANE"):
    async with SessionLocal() as session:
        session.add(
            MatchupStat(
                patch=patch, queue_id=420, rank_bracket=bracket, scope=scope,
                team_position=POSITION, champion_id=champion_id,
                enemy_champion_id=enemy_id, games=games, wins=wins,
                timeline_games=0,
            )
        )
        await session.commit()


async def suggest(**kw):
    ctx = DraftContext(position=POSITION, patch=kw.pop("patch", PATCH), min_games=1, **kw)
    async with SessionLocal() as session:
        return await DraftAdvisor(session).suggest(ctx)


async def test_a_champion_in_two_brackets_is_suggested_once():
    """ALL overlaps every per-tier slice, so an unfiltered query returns the
    same champion once per bracket it appears in."""
    patch = "D2.00"
    await seed_stat(501, 100, 55, patch=patch, bracket=ALL_BRACKETS)
    await seed_stat(501, 98, 54, patch=patch, bracket="CHALLENGER")

    picks = await suggest(patch=patch)
    assert [s.champion_id for s in picks] == [501]


async def test_the_bracket_asked_for_is_the_bracket_scored():
    patch = "D3.00"
    await seed_stat(502, 100, 90, patch=patch, bracket=ALL_BRACKETS)
    await seed_stat(502, 100, 10, patch=patch, bracket="IRON")

    high = await suggest(patch=patch, rank_bracket=ALL_BRACKETS)
    low = await suggest(patch=patch, rank_bracket="IRON")
    assert high[0].base_win_rate > 0.8
    assert low[0].base_win_rate < 0.2


async def test_allies_enemies_and_bans_are_off_the_table():
    patch = "D4.00"
    for champion in (510, 511, 512, 513):
        await seed_stat(champion, 50, 30, patch=patch)

    picks = await suggest(patch=patch, allies=[510], enemies=[511], bans=[512])
    assert [s.champion_id for s in picks] == [513]


async def test_a_thin_matchup_barely_moves_the_baseline():
    """Two games against someone is not evidence. Without shrinkage a 2-0 would
    top the list over a champion with a hundred games behind it."""
    patch = "D5.00"
    await seed_stat(520, 200, 100, patch=patch)       # dead even baseline
    await seed_matchup(520, 999, games=2, wins=2, patch=patch)

    picks = await suggest(patch=patch, enemy_laner=999)
    pick = picks[0]
    assert pick.matchup_games == 2
    assert pick.matchup_win_rate == 1.0

    weight = 2 / (2 + MATCHUP_SHRINKAGE)
    expected = pick.base_win_rate + weight * (1.0 - pick.base_win_rate)
    assert pick.adjusted_win_rate == pytest.approx(expected)
    # The point of the shrinkage: nowhere near the observed 100%.
    assert pick.adjusted_win_rate < 0.65


async def test_team_scope_matchups_do_not_leak_into_the_lane_adjustment():
    """A TEAM row says 'this champion was somewhere on the enemy side', which is
    a different question from 'you laned against them'."""
    patch = "D6.00"
    await seed_stat(530, 200, 100, patch=patch)
    await seed_matchup(530, 998, games=60, wins=60, patch=patch, scope="TEAM")

    pick = (await suggest(patch=patch, enemy_laner=998))[0]
    assert pick.matchup_games == 0
    assert pick.adjusted_win_rate == pytest.approx(pick.base_win_rate)


async def test_min_games_keeps_a_one_game_champion_out_of_the_draft():
    patch = "D7.00"
    await seed_stat(540, 1, 1, patch=patch)
    await seed_stat(541, 40, 22, patch=patch)

    ctx = DraftContext(position=POSITION, patch=patch, min_games=20)
    async with SessionLocal() as session:
        picks = await DraftAdvisor(session).suggest(ctx)
    assert [s.champion_id for s in picks] == [541]


async def test_an_unadjusted_pick_does_not_restate_its_own_score():
    """The row prints the score; a reason line printing the identical figure
    underneath reads as a template filling itself in."""
    patch = "D9.00"
    await seed_stat(560, 100, 48, patch=patch)

    pick = (await suggest(patch=patch))[0]
    assert pick.adjusted_win_rate == pick.base_win_rate
    assert pick.reasons[0] == "baseline over 100 games"


async def test_an_adjusted_pick_still_shows_what_the_baseline_was():
    """Here the two numbers genuinely differ, so the baseline has to be named.

    The figure is read back off the suggestion rather than written out: it is a
    Wilson lower bound, not wins over games, so a literal here would be
    asserting the confidence maths a second time and in the wrong place.
    """
    patch = "D10.00"
    await seed_stat(561, 200, 100, patch=patch)
    await seed_matchup(561, 998, games=40, wins=30, patch=patch)

    pick = (await suggest(patch=patch, enemy_laner=998))[0]
    assert pick.adjusted_win_rate != pick.base_win_rate
    assert pick.reasons[0] == (
        f"{pick.base_win_rate * 100:.1f}% baseline over 200 games"
    )
