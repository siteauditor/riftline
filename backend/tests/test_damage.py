"""The team damage mix: the three lifted damage types, their backfill, each
champion's profile, and what the draft says with them.

Each test keeps to its own patch and champion ids: the suite shares one
database, and a profile is a GROUP BY over every stored game of a patch.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select

from app.db.base import SessionLocal
from app.db.models import ChampionStat, Match, MatchParticipant
from app.services import damage
from app.services.aggregate import ALL_BRACKETS
from app.services.damage import (
    MIN_PROFILE_GAMES,
    Profile,
    Profiles,
    load_profiles,
    read_draft,
    team_mix,
)
from app.services.scores import ScoreService, lifted_fields


@pytest.fixture(autouse=True)
def _fresh_profiles():
    damage.clear_profile_cache()
    yield
    damage.clear_profile_cache()


async def seed_game(match_id: str, patch: str, players, *, queue: int = 420, raw=None) -> None:
    """One stored game. players: (champion, position, physical, magic, true)."""
    async with SessionLocal() as session:
        session.add(
            Match(
                match_id=match_id, platform_id="EUW1", queue_id=queue, patch=patch,
                game_creation=1, game_duration=1800, is_remake=False, teams=[], raw=raw,
            )
        )
        for index, (champion, position, physical, magic, true) in enumerate(players, start=1):
            session.add(
                MatchParticipant(
                    match_id=match_id, participant_index=index, puuid=f"{match_id}-{index}",
                    champion_id=champion, team_id=100, team_position=position, win=True,
                    time_dead=60,
                    physical_damage_to_champions=physical,
                    magic_damage_to_champions=magic,
                    true_damage_to_champions=true,
                )
            )
        await session.commit()


async def seed_games(prefix: str, patch: str, count: int, player) -> None:
    for i in range(count):
        await seed_game(f"{prefix}_{i}", patch, [player])


# ------------------------------------------------------------------ lifting


def test_lifted_fields_carry_the_three_damage_types():
    fields = lifted_fields(
        {
            "physicalDamageDealtToChampions": 18_250,
            "magicDamageDealtToChampions": 3_100,
            "trueDamageDealtToChampions": 950,
        }
    )
    assert fields["physical_damage_to_champions"] == 18_250
    assert fields["magic_damage_to_champions"] == 3_100
    assert fields["true_damage_to_champions"] == 950


async def test_the_backfill_reaches_rows_lifted_before_the_damage_types_and_stops():
    """`time_dead` was the whole cursor, and every stored row had it, so the new
    columns would never have been filled. A row whose participant is missing
    from the payload stays null, and the run still ends."""
    raw = {
        "info": {
            "participants": [
                {"participantId": 1, "totalTimeSpentDead": 60, "physicalDamageDealtToChampions": 12_000,
                 "magicDamageDealtToChampions": 800, "trueDamageDealtToChampions": 400},
                {"participantId": 2, "totalTimeSpentDead": 90, "physicalDamageDealtToChampions": 1_500,
                 "magicDamageDealtToChampions": 14_000, "trueDamageDealtToChampions": 0},
            ]
        }
    }
    # Three rows lifted before the damage types existed: time_dead set, damage
    # null. The third has no participant in the stored payload.
    await seed_game(
        "DMG_LIFT_1", "DL1.00",
        [(9001, "TOP", None, None, None), (9002, "MIDDLE", None, None, None), (9003, "JUNGLE", None, None, None)],
        raw=raw,
    )

    async with SessionLocal() as session:
        service = ScoreService(session)
        assert await service.lift_remaining() >= 3
        await asyncio.wait_for(service.lift_fields(), timeout=60)
        # Again: the row that cannot be filled must not trap a second run either.
        await asyncio.wait_for(ScoreService(session).lift_fields(), timeout=60)

    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(MatchParticipant)
                .where(MatchParticipant.match_id == "DMG_LIFT_1")
                .order_by(MatchParticipant.participant_index)
            )
        ).scalars().all()
    top, mid, missing = rows
    assert (top.physical_damage_to_champions, top.magic_damage_to_champions, top.true_damage_to_champions) == (
        12_000, 800, 400,
    )
    assert (mid.physical_damage_to_champions, mid.magic_damage_to_champions) == (1_500, 14_000)
    assert missing.physical_damage_to_champions is None


# ----------------------------------------------------------------- profiles


async def test_a_profile_needs_ten_games_and_reads_the_role_before_the_rest():
    patch = "DP1.00"
    # Mid: magic. Bot: physical, in too few games to be read on its own.
    await seed_games("DMG_P_MID", patch, MIN_PROFILE_GAMES, (9101, "MIDDLE", 1_000, 19_000, 0))
    await seed_games("DMG_P_BOT", patch, 3, (9101, "BOTTOM", 17_000, 3_000, 0))
    await seed_games("DMG_P_THIN", patch, MIN_PROFILE_GAMES - 1, (9102, "TOP", 10_000, 0, 0))

    async with SessionLocal() as session:
        profiles = await load_profiles(session, [patch])

    mid = profiles.get(9101, "MIDDLE")
    assert mid is not None and mid.games == MIN_PROFILE_GAMES
    assert mid.shares().magic == pytest.approx(0.95)
    # Three bot games are not a profile: the champion's games in every role are.
    bot = profiles.get(9101, "BOTTOM")
    assert bot is not None and bot.games == MIN_PROFILE_GAMES + 3
    assert bot.shares().physical == pytest.approx((10 * 1_000 + 3 * 17_000) / (13 * 20_000))
    assert profiles.get(9102, "TOP") is None
    assert profiles.get(9102) is None


async def test_a_game_from_another_patch_or_a_remake_is_not_in_the_profile():
    patch = "DP2.00"
    await seed_games("DMG_Q_IN", patch, MIN_PROFILE_GAMES, (9111, "TOP", 10_000, 0, 0))
    await seed_games("DMG_Q_OTHER", "DP3.00", 5, (9111, "TOP", 0, 10_000, 0))
    async with SessionLocal() as session:
        session.add(
            Match(match_id="DMG_Q_REMAKE", platform_id="EUW1", queue_id=420, patch=patch,
                  game_creation=1, game_duration=200, is_remake=True, teams=[])
        )
        session.add(
            MatchParticipant(match_id="DMG_Q_REMAKE", participant_index=1, puuid="DMG_Q_REMAKE-1",
                             champion_id=9111, team_id=100, team_position="TOP", win=False,
                             physical_damage_to_champions=0, magic_damage_to_champions=900,
                             true_damage_to_champions=0)
        )
        await session.commit()
        profiles = await load_profiles(session, [patch])

    profile = profiles.get(9111, "TOP")
    assert profile is not None and profile.games == MIN_PROFILE_GAMES
    assert profile.shares().physical == pytest.approx(1.0)


# ------------------------------------------------------------- mixing a side


def _profiles(**by_champion: tuple[float, float, float]) -> Profiles:
    """Profiles from champion "c<id>" -> (physical, magic, true) a game."""
    return Profiles(
        overall={
            int(name[1:]): Profile(MIN_PROFILE_GAMES, *values) for name, values in by_champion.items()
        }
    )


def test_a_side_is_mixed_by_the_damage_each_champion_deals():
    # A carry dealing 20,000 physical and a support dealing 5,000 magic: the
    # side is 80% physical, not the 50% an even vote would say.
    profiles = _profiles(c1=(20_000, 0, 0), c2=(0, 5_000, 0))
    mix = team_mix(profiles, [(1, None), (2, None)])
    assert mix.shares is not None
    assert mix.shares.physical == pytest.approx(0.8)
    assert mix.leaning == "physical"


def test_one_champion_is_a_pick_and_not_a_one_sided_team():
    mix = team_mix(_profiles(c1=(20_000, 0, 0)), [(1, None)])
    assert mix.shares is not None and mix.shares.physical == pytest.approx(1.0)
    assert mix.leaning is None


def test_a_side_under_the_threshold_leans_nowhere():
    mix = team_mix(_profiles(c1=(13_000, 0, 0), c2=(0, 7_000, 0)), [(1, None), (2, None)])
    assert mix.shares is not None and mix.shares.physical == pytest.approx(0.65)
    assert mix.leaning is None


def test_an_unmeasured_champion_is_named_and_left_out_of_the_mix():
    mix = team_mix(_profiles(c1=(10_000, 0, 0), c2=(0, 10_000, 0)), [(1, None), (2, None), (3, None)])
    assert mix.measured == [1, 2]
    assert mix.missing == [3]
    assert mix.shares is not None and mix.shares.physical == pytest.approx(0.5)


def test_a_side_with_nobody_measured_has_no_shares():
    mix = team_mix(_profiles(), [(1, None)])
    assert mix.shares is None
    assert mix.leaning is None


def test_a_pick_balances_a_one_sided_team_only_when_it_deals_mostly_another_type():
    profiles = _profiles(
        c1=(18_000, 1_000, 1_000),  # ally
        c2=(15_000, 2_000, 1_000),  # ally
        c3=(1_000, 17_000, 500),  # a mage
        c4=(16_000, 1_000, 500),  # a marksman
        c5=(9_000, 8_000, 500),  # a hybrid, just over half physical
    )
    read = read_draft(profiles, "MIDDLE", allies=[(1, None), (2, None)], enemies=[], picks=[3, 4, 5])
    assert read.allies is not None and read.allies.leaning == "physical"
    mage, marksman, hybrid = read.picks[3], read.picks[4], read.picks[5]
    assert mage.balances == "physical"
    assert mage.team_after is not None
    assert mage.team_after.physical < read.allies.shares.physical
    assert marksman.balances is None
    # 51% physical is not "mostly another type".
    assert hybrid.own.physical > 0.5 and hybrid.balances is None


def test_with_no_allies_a_pick_has_its_own_mix_and_no_team_after():
    read = read_draft(_profiles(c3=(1_000, 17_000, 500)), "MIDDLE", allies=[], enemies=[], picks=[3])
    assert read.allies is None
    assert read.picks[3].team_after is None
    assert read.picks[3].balances is None


def test_an_empty_table_says_the_mix_is_not_measured_yet():
    assert read_draft(Profiles(), "MIDDLE", allies=[(1, None)], enemies=[], picks=[]).available is False


# ------------------------------------------------------------------ the API


async def seed_stat(champion_id: int, patch: str, position: str, games: int = 100, wins: int = 50) -> None:
    async with SessionLocal() as session:
        session.add(
            ChampionStat(
                patch=patch, queue_id=420, rank_bracket=ALL_BRACKETS, team_position=position,
                champion_id=champion_id, games=games, wins=wins, bans=0, pool_games=games,
                avg_kills=6.0, avg_deaths=5.0, avg_assists=9.0, avg_cs_per_min=8.0,
                avg_gold=12000, avg_damage=20000, avg_vision=20,
            )
        )
        await session.commit()


async def test_the_draft_response_carries_both_sides_damage_and_what_each_pick_does(client):
    patch = "DA1.00"
    # Two physical allies, one magic enemy, and a mage and a marksman to pick from.
    for champion, position, figures in (
        (9301, "TOP", (18_000, 1_000, 1_000)),
        (9302, "JUNGLE", (15_000, 2_000, 1_000)),
        (9303, "MIDDLE", (1_000, 17_000, 500)),
        (9304, "MIDDLE", (500, 16_000, 500)),
        (9305, "MIDDLE", (16_000, 1_000, 500)),
    ):
        await seed_stat(champion, patch, position)
        await seed_games(f"DMG_API_{champion}", patch, MIN_PROFILE_GAMES, (champion, position, *figures))

    response = await client.post(
        "/api/draft/suggest",
        json={"position": "MIDDLE", "patch": patch, "min_games": 1, "allies": [9301, 9302], "enemies": [9303]},
    )

    assert response.status_code == 200, response.text[:300]
    body = response.json()
    mixes = body["team_damage"]
    assert mixes["available"] is True
    assert (mixes["min_games"], mixes["one_sided_share"]) == (MIN_PROFILE_GAMES, 0.7)
    assert mixes["allies"]["leaning"] == "physical"
    assert mixes["allies"]["measured"] == 2
    assert mixes["enemies"]["shares"]["magic"] > 0.9
    picks = {s["champion"]["id"]: s["damage"] for s in body["suggestions"]}
    assert picks[9304]["balances"] == "physical"
    assert picks[9304]["team_after"]["physical"] < mixes["allies"]["shares"]["physical"]
    assert picks[9304]["games"] == MIN_PROFILE_GAMES
    assert picks[9305]["balances"] is None


# --------------------------------------------------------------- draftpriors


async def test_the_priors_report_counts_how_one_sided_teams_fared():
    from app.services.draft_priors import _damage_mix

    patch = "DR1.00"
    physical = [(9401 + i, position) for i, position in enumerate(("TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"))]
    mixed = [(9411 + i, position) for i, position in enumerate(("TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"))]
    async with SessionLocal() as session:
        for game in range(MIN_PROFILE_GAMES):
            match_id = f"DMG_R_{game}"
            session.add(
                Match(match_id=match_id, platform_id="EUW1", queue_id=420, patch=patch,
                      game_creation=1, game_duration=1800, is_remake=False, teams=[])
            )
            for index, (champion, position) in enumerate(physical + mixed, start=1):
                ours = index <= 5
                session.add(
                    MatchParticipant(
                        match_id=match_id, participant_index=index, puuid=f"{match_id}-{index}",
                        champion_id=champion, team_id=100 if ours else 200, team_position=position,
                        win=ours, time_dead=60,
                        physical_damage_to_champions=15_000 if ours else (15_000 if index % 2 else 1_000),
                        magic_damage_to_champions=500 if ours else (1_000 if index % 2 else 15_000),
                        true_damage_to_champions=0,
                    )
                )
        await session.commit()
        report = await _damage_mix(session, 420, (patch,))

    assert (report.teams, report.unmeasured) == (2 * MIN_PROFILE_GAMES, 0)
    by_low = {b.low: b for b in report.buckets}
    # The all-physical side: 97% one type, and it won every game.
    assert (by_low[0.8].teams, by_low[0.8].wins) == (MIN_PROFILE_GAMES, MIN_PROFILE_GAMES)
    # The mixed side sits under 60% and lost them all.
    assert (by_low[0.0].teams, by_low[0.0].wins) == (MIN_PROFILE_GAMES, 0)
