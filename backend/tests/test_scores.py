"""The Riftline score, its placement, and its badges.

The score is the one number in this app that nobody else computes, so these
tests are mostly about the claims it makes rather than the arithmetic: that it
is withheld wherever the sample cannot carry it, that a placement always ranks
the whole lobby, and that every badge rule fires on its own case and not on the
case next to it.

Each test works in its own private match ids and puuids. The suite shares one
database, and a lobby is scored as a whole, so a stray participant from another
test would change a placement rather than fail cleanly.
"""

from __future__ import annotations

import pytest

from app.db.base import SessionLocal
from app.db.models import Match, MatchParticipant, RoleMetricStat, utcnow
from app.services.scores import (
    BADGES,
    COMPONENTS,
    DEATHLESS_MINIMUM_SECONDS,
    DUELIST_SOLO_KILLS,
    LANE_LEAD_GOLD,
    LIFELINE_FLOOR,
    MIN_GAMES_FOR_SCORE,
    QUANTILES,
    SHARE_FLOOR,
    WEIGHTS,
    WEIGHTS_VERSION,
    ScoreService,
    combine,
    lifted_fields,
    percentile,
)

ROLES = ("TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY")


# --------------------------------------------------------------- unit level


def test_every_role_weights_to_exactly_one():
    """A weight vector that does not sum to 1 silently rescales that role, so
    two roles would be scored on different ceilings."""
    for role, weights in WEIGHTS.items():
        assert set(weights) == set(COMPONENTS), role
        assert sum(weights.values()) == pytest.approx(1.0), role


def test_damage_per_gold_is_the_players_own_and_not_a_team_share():
    """Version 2's component: a player on a team that deals little cannot look
    good on it by dealing little, as they can on damage share."""
    from types import SimpleNamespace

    from app.services.scores import component_values

    player = SimpleNamespace(
        time_dead=0, kills=2, assists=3, damage_to_champions=24_000, gold_earned=12_000,
        vision_score=30, turret_takedowns=1, turret_plates=0, epic_takedowns=0,
    )
    low_team = component_values(player, duration_seconds=1800, team_damage=30_000, team_kills=10)
    high_team = component_values(player, duration_seconds=1800, team_damage=90_000, team_kills=10)

    assert low_team["efficiency"] == pytest.approx(2000.0)
    assert high_team["efficiency"] == low_team["efficiency"]
    assert low_team["damage"] > high_team["damage"], "the share moves with the team"


def test_a_median_game_in_every_component_scores_five():
    """5.0 is the corpus median by construction. The UI's neutral band sits
    there, so this is load-bearing rather than cosmetic."""
    for role in ROLES:
        assert combine({c: 0.5 for c in COMPONENTS}, role) == pytest.approx(5.0)


def test_the_scale_cannot_be_left():
    for role in ROLES:
        assert combine({c: 0.0 for c in COMPONENTS}, role) == pytest.approx(0.0)
        assert combine({c: 1.0 for c in COMPONENTS}, role) == pytest.approx(10.0)


def test_percentile_bounds_and_midpoint():
    breakpoints = [float(i) for i in range(QUANTILES)]  # 0..100
    assert percentile(breakpoints, -5) == 0.0
    assert percentile(breakpoints, 500) == 1.0
    assert percentile(breakpoints, 50) == pytest.approx(0.5, abs=0.01)


def test_percentile_splits_a_tied_band_rather_than_topping_it():
    """Forty per cent of supports take no objective at all. Handing every one of
    them the top of that band would score a zero as the 40th percentile."""
    breakpoints = [0.0] * 40 + [float(i) for i in range(61)]
    assert percentile(breakpoints, 0.0) == pytest.approx(0.20, abs=0.02)


def test_percentile_of_an_unmeasured_distribution_is_zero_not_a_crash():
    assert percentile([], 7) == 0.0


def test_badges_are_ordered_rarest_first():
    """The match row shows two badges, picked off the front of this list, so the
    order is the difference between showing Steal and showing Duelist."""
    rates = [b.rate for b in BADGES]
    assert rates == sorted(rates)
    assert len({b.id for b in BADGES}) == len(BADGES)


def test_lifted_fields_reads_riot_shapes_without_inventing_zeroes():
    """Riot omits counters that never happened and occasionally sends null."""
    fields = lifted_fields(
        {
            "totalTimeSpentDead": 120,
            "wardsPlaced": 14,
            "wardsKilled": None,
            "challenges": {
                "turretTakedowns": 3,
                "dragonTakedowns": 2,
                "baronTakedowns": 1,
                "riftHeraldTakedowns": 1,
                "soloKills": 4,
            },
        }
    )
    assert fields["time_dead"] == 120
    assert fields["wards_placed"] == 14
    assert fields["wards_killed"] == 0
    # The three epic monsters are summed into one objective term.
    assert fields["epic_takedowns"] == 4
    assert fields["solo_kills"] == 4
    # Absent entirely, which is a zero in Riot's own reading.
    assert fields["heal_and_shield"] == 0


def test_lifting_an_empty_participant_is_all_zeroes_not_an_error():
    assert set(lifted_fields({}).values()) == {0}


# ------------------------------------------------------------- the database


# The range each metric actually occupies. A single 0..100 ramp for all seven
# would put kill participation (0..1) inside one breakpoint and make every
# player's participation identical, which is a property of the fixture rather
# than of the score.
METRIC_RANGE = {
    "kill_part": 1.0,
    "damage": 1.0,
    # Damage to champions per 1,000 gold earned.
    "efficiency": 4000.0,
    "economy": 1000.0,
    "survival": 1.0,
    "objectives": 15.0,
    "vision": 3.0,
}


async def seed_distributions(queue_id: int, *, games: int = MIN_GAMES_FOR_SCORE) -> None:
    """Even distributions spanning each metric's own range."""
    async with SessionLocal() as session:
        await session.execute(
            RoleMetricStat.__table__.delete().where(
                RoleMetricStat.queue_id == queue_id
            )
        )
        rows = [
            {
                "queue_id": queue_id,
                "team_position": role,
                "metric": metric,
                "breakpoints": [
                    METRIC_RANGE[metric] * i / (QUANTILES - 1)
                    for i in range(QUANTILES)
                ],
                "games": games,
                "computed_at": utcnow(),
            }
            for role in ROLES
            for metric in COMPONENTS
        ]
        await session.execute(RoleMetricStat.__table__.insert(), rows)
        await session.commit()


async def seed_match(
    match_id: str,
    *,
    queue_id: int,
    players: int = 10,
    positions: bool = True,
    remake: bool = False,
    duration: int = 1800,
    overrides: dict[int, dict] | None = None,
) -> None:
    """One lobby. `overrides` patches a participant by its index."""
    async with SessionLocal() as session:
        session.add(
            Match(
                match_id=match_id,
                platform_id="EUW1",
                queue_id=queue_id,
                patch="S1.00",
                game_creation=1,
                game_duration=duration,
                is_remake=remake,
                teams=[],
            )
        )
        for slot in range(players):
            role = ROLES[slot % 5] if positions else None
            fields = dict(
                match_id=match_id,
                participant_index=slot + 1,
                puuid=f"{match_id}_p{slot}",
                champion_id=100 + slot,
                team_id=100 if slot < players // 2 else 200,
                team_position=role,
                win=slot < players // 2,
                kills=5,
                deaths=5,
                assists=5,
                gold_earned=10_000,
                total_minions=200,
                vision_score=20,
                damage_to_champions=20_000,
                damage_taken=20_000,
                time_dead=100,
                turret_takedowns=1,
                turret_plates=1,
                epic_takedowns=1,
                objectives_stolen=0,
                solo_kills=0,
                heal_and_shield=0,
                wards_placed=10,
                wards_killed=2,
                control_wards=2,
            )
            fields.update((overrides or {}).get(slot, {}))
            session.add(MatchParticipant(**fields))
        await session.commit()


async def score(match_id: str) -> tuple[list[MatchParticipant], ScoreService]:
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    async with SessionLocal() as session:
        service = ScoreService(session)
        match = (
            await session.execute(
                select(Match)
                .where(Match.match_id == match_id)
                .options(selectinload(Match.participants))
            )
        ).scalars().first()
        await service.score_match(match)
        await session.commit()
        return list(match.participants), service


async def test_a_full_lobby_is_scored_and_ranked_one_to_ten():
    queue = 9_001
    await seed_distributions(queue)
    await seed_match("SC_FULL", queue_id=queue)
    participants, _ = await score("SC_FULL")

    assert all(p.performance_score is not None for p in participants)
    assert sorted(p.performance_rank for p in participants) == list(range(1, 11))
    for p in participants:
        detail = p.performance_detail
        assert set(detail["components"]) == set(COMPONENTS)
        assert detail["weights"] == WEIGHTS_VERSION
        # The sample behind this player's own role, which is what the UI claims
        # it is when it says "measured against N games in this role".
        assert detail["sample"] == MIN_GAMES_FOR_SCORE


async def test_a_better_game_outranks_a_worse_one():
    queue = 9_002
    await seed_distributions(queue)
    await seed_match(
        "SC_ORDER",
        queue_id=queue,
        overrides={
            0: {"kills": 20, "assists": 20, "damage_to_champions": 60_000,
                "gold_earned": 30_000, "vision_score": 60, "time_dead": 0,
                "turret_takedowns": 8, "epic_takedowns": 5},
            1: {"kills": 0, "assists": 0, "damage_to_champions": 1_000,
                "gold_earned": 3_000, "vision_score": 2, "time_dead": 600,
                "turret_takedowns": 0, "turret_plates": 0, "epic_takedowns": 0},
        },
    )
    participants, _ = await score("SC_ORDER")
    by_index = {p.participant_index: p for p in participants}
    assert by_index[1].performance_score > by_index[2].performance_score
    assert by_index[1].performance_rank < by_index[2].performance_rank


async def test_ties_break_deterministically():
    """Every player in this lobby is identical, so a rerun must not reshuffle
    the ranking and move someone's placement for no reason."""
    queue = 9_003
    await seed_distributions(queue)
    await seed_match("SC_TIES", queue_id=queue)
    first, _ = await score("SC_TIES")
    ranks = {p.participant_index: p.performance_rank for p in first}

    second, _ = await score("SC_TIES")
    assert {p.participant_index: p.performance_rank for p in second} == ranks
    assert ranks[1] < ranks[10]


@pytest.mark.parametrize(
    "label,kwargs,reason",
    [
        ("a remake", {"remake": True}, "remake"),
        ("an eighteen player lobby", {"players": 18}, "not a ten player lobby"),
        ("a mode with no lanes", {"positions": False}, "no lane roles"),
    ],
)
async def test_an_unmeasurable_lobby_is_withheld_with_a_reason(label, kwargs, reason):
    queue = 9_004
    await seed_distributions(queue)
    match_id = f"SC_WITHHELD_{reason.replace(' ', '_')}"
    await seed_match(match_id, queue_id=queue, **kwargs)
    participants, service = await score(match_id)

    assert all(p.performance_score is None for p in participants), label
    assert service.stats.reasons == {reason: 1}


async def test_a_thin_corpus_withholds_rather_than_guessing():
    """A percentile over 199 games describes our corpus, not the player. The
    same discipline MIN_RANKED_FOR_LOBBY_RANK applies to the lobby tier."""
    queue = 9_005
    await seed_distributions(queue, games=MIN_GAMES_FOR_SCORE - 1)
    await seed_match("SC_THIN", queue_id=queue)
    participants, service = await score("SC_THIN")

    assert all(p.performance_score is None for p in participants)
    assert service.stats.reasons == {"corpus too thin for this queue": 1}


async def test_a_queue_with_no_distribution_at_all_is_withheld():
    await seed_match("SC_NODIST", queue_id=9_006)
    participants, service = await score("SC_NODIST")
    assert all(p.performance_score is None for p in participants)
    assert service.stats.withheld == 1


async def test_a_lobby_whose_fields_are_not_lifted_yet_is_withheld():
    """Null is "we have not read it out of the payload", which is a different
    fact from zero and must not be scored as one."""
    queue = 9_007
    await seed_distributions(queue)
    await seed_match("SC_UNLIFTED", queue_id=queue, overrides={3: {"time_dead": None}})
    participants, service = await score("SC_UNLIFTED")
    assert all(p.performance_score is None for p in participants)
    assert service.stats.reasons == {"fields not lifted": 1}


# ------------------------------------------------------------------ badges


async def badges_for(match_id: str) -> dict[int, list[str]]:
    participants, _ = await score(match_id)
    return {
        p.participant_index: (p.performance_detail or {}).get("badges") or []
        for p in participants
    }


async def test_mvp_and_ace_go_to_the_best_game_on_each_side():
    queue = 9_010
    await seed_distributions(queue)
    await seed_match(
        "SC_MVP",
        queue_id=queue,
        overrides={
            0: {"kills": 20, "assists": 20, "damage_to_champions": 60_000},
            5: {"kills": 18, "assists": 18, "damage_to_champions": 55_000},
        },
    )
    badges = await badges_for("SC_MVP")
    assert "mvp" in badges[1] and "ace" not in badges[1]
    assert "ace" in badges[6] and "mvp" not in badges[6]
    # Exactly one of each in the lobby.
    assert sum("mvp" in b for b in badges.values()) == 1
    assert sum("ace" in b for b in badges.values()) == 1


async def test_damage_carry_needs_both_the_lead_and_the_share():
    queue = 9_011
    await seed_distributions(queue)
    # Slot 0 leads its team and clears 30%; slot 5 leads its team on a share
    # just under the floor, which must earn nothing.
    await seed_match(
        "SC_CARRY",
        queue_id=queue,
        overrides={
            0: {"damage_to_champions": 60_000},
            1: {"damage_to_champions": 10_000},
            2: {"damage_to_champions": 10_000},
            3: {"damage_to_champions": 10_000},
            4: {"damage_to_champions": 10_000},
            5: {"damage_to_champions": 29_000},
            6: {"damage_to_champions": 25_000},
            7: {"damage_to_champions": 25_000},
            8: {"damage_to_champions": 10_000},
            9: {"damage_to_champions": 10_000},
        },
    )
    badges = await badges_for("SC_CARRY")
    assert "damage_carry" in badges[1]
    share = 29_000 / (29_000 + 25_000 + 25_000 + 10_000 + 10_000)
    assert share < SHARE_FLOOR
    assert "damage_carry" not in badges[6]


async def test_frontline_is_the_badge_kda_cannot_give():
    """A tank who absorbs a third of the damage looks mediocre in KDA. This is
    two of the nine badges' whole reason for existing."""
    queue = 9_012
    await seed_distributions(queue)
    await seed_match(
        "SC_FRONT",
        queue_id=queue,
        overrides={
            0: {"damage_taken": 60_000, "deaths": 9, "kills": 1, "assists": 2},
            1: {"damage_taken": 10_000},
            2: {"damage_taken": 10_000},
            3: {"damage_taken": 10_000},
            4: {"damage_taken": 10_000},
        },
    )
    badges = await badges_for("SC_FRONT")
    assert "frontline" in badges[1]


async def test_deathless_needs_a_game_long_enough_to_have_died_in():
    queue = 9_013
    await seed_distributions(queue)
    await seed_match(
        "SC_DEATHLESS", queue_id=queue, overrides={0: {"deaths": 0}}
    )
    assert "deathless" in (await badges_for("SC_DEATHLESS"))[1]

    await seed_match(
        "SC_SHORT",
        queue_id=queue,
        duration=DEATHLESS_MINIMUM_SECONDS - 1,
        overrides={0: {"deaths": 0}},
    )
    assert "deathless" not in (await badges_for("SC_SHORT"))[1]


async def test_duelist_at_the_boundary():
    queue = 9_014
    await seed_distributions(queue)
    await seed_match(
        "SC_DUEL", queue_id=queue, overrides={0: {"solo_kills": 3}, 1: {"solo_kills": 2}}
    )
    badges = await badges_for("SC_DUEL")
    assert "duelist" in badges[1]
    assert "duelist" not in badges[2]


async def test_steal_fires_on_a_single_stolen_objective():
    queue = 9_015
    await seed_distributions(queue)
    await seed_match("SC_STEAL", queue_id=queue, overrides={7: {"objectives_stolen": 1}})
    badges = await badges_for("SC_STEAL")
    assert "steal" in badges[8]
    assert all("steal" not in b for i, b in badges.items() if i != 8)


async def test_lifeline_is_the_lobby_best_above_a_floor():
    queue = 9_016
    await seed_distributions(queue)
    await seed_match(
        "SC_LIFE",
        queue_id=queue,
        overrides={4: {"heal_and_shield": LIFELINE_FLOOR + 1}, 9: {"heal_and_shield": 4_000}},
    )
    badges = await badges_for("SC_LIFE")
    assert "lifeline" in badges[5]
    assert "lifeline" not in badges[10]

    # A lobby where nobody clears the floor awards it to nobody.
    await seed_match(
        "SC_LIFE_NONE", queue_id=queue, overrides={4: {"heal_and_shield": 100}}
    )
    assert all("lifeline" not in b for b in (await badges_for("SC_LIFE_NONE")).values())


def test_every_badge_rule_states_the_threshold_the_code_applies():
    """The rule text is the tooltip, so a threshold it leaves out is a rule the
    player cannot see.

    Lifeline's text used to stop at "most healing and shielding in the lobby"
    while the code also required 5,000 of it: a support with the most healing,
    short of the floor, got no badge and nothing on the page saying why.
    """
    rules = {b.id: b.rule for b in BADGES}
    assert f"at least {LIFELINE_FLOOR:,}" in rules["lifeline"]
    assert f"at least {LANE_LEAD_GOLD:,} gold" in rules["lane_lead"]
    assert f"at least {SHARE_FLOOR:.0%}" in rules["frontline"]
    assert f"at least {SHARE_FLOOR:.0%}" in rules["damage_carry"]
    assert f"{DEATHLESS_MINIMUM_SECONDS // 60} minutes" in rules["deathless"]
    # Spelled as a word, so pinned by value: changing the constant fails here
    # until the text says the new number too.
    assert DUELIST_SOLO_KILLS == 3
    assert rules["duelist"].startswith("Three or more")


async def test_lane_lead_needs_a_lead_worth_naming():
    queue = 9_017
    await seed_distributions(queue)
    await seed_match(
        "SC_LANE",
        queue_id=queue,
        overrides={2: {"gold_diff_14": LANE_LEAD_GOLD + 500}, 3: {"gold_diff_14": 400}},
    )
    badges = await badges_for("SC_LANE")
    assert "lane_lead" in badges[3]

    await seed_match(
        "SC_LANE_SMALL", queue_id=queue, overrides={2: {"gold_diff_14": 900}}
    )
    assert all(
        "lane_lead" not in b for b in (await badges_for("SC_LANE_SMALL")).values()
    )


async def test_a_lobby_with_no_timeline_awards_no_lane_lead():
    """`gold_diff_14` is null until the timeline backfill has run, and a badge
    for the biggest of no leads would be a badge for nothing."""
    queue = 9_018
    await seed_distributions(queue)
    await seed_match("SC_NOTIMELINE", queue_id=queue)
    assert all(
        "lane_lead" not in b for b in (await badges_for("SC_NOTIMELINE")).values()
    )


# ----------------------------------------------------------------- the pass


async def test_the_pass_is_idempotent_and_records_what_it_withheld():
    queue = 9_020
    await seed_distributions(queue)
    await seed_match("SC_PASS_A", queue_id=queue)
    await seed_match("SC_PASS_B", queue_id=queue, remake=True)

    async with SessionLocal() as session:
        service = ScoreService(session)
        first = await service.score_matches()
        assert first >= 2

    async with SessionLocal() as session:
        again = ScoreService(session)
        # A withheld lobby is stamped, so the second pass must not re-offer it.
        assert await again.score_matches() == 0
        assert again.stats.scored == 0
        assert again.stats.withheld == 0


async def test_a_stale_weights_version_is_cleared_for_rescoring():
    queue = 9_021
    await seed_distributions(queue)
    await seed_match("SC_STALE", queue_id=queue)
    await score("SC_STALE")

    async with SessionLocal() as session:
        rows = (
            await session.execute(
                MatchParticipant.__table__.select().where(
                    MatchParticipant.match_id == "SC_STALE"
                )
            )
        ).mappings().all()
        assert all(r["performance_score"] is not None for r in rows)
        await session.execute(
            MatchParticipant.__table__.update()
            .where(MatchParticipant.match_id == "SC_STALE")
            .values(performance_detail={"weights": WEIGHTS_VERSION - 1})
        )
        await session.commit()

        cleared = await ScoreService(session).rescore_stale()
        assert cleared >= 10
        rows = (
            await session.execute(
                MatchParticipant.__table__.select().where(
                    MatchParticipant.match_id == "SC_STALE"
                )
            )
        ).mappings().all()
        assert all(r["performance_score"] is None for r in rows)
        assert all(r["performance_scored_at"] is None for r in rows)


async def test_distributions_are_measured_from_the_corpus_and_replaced_wholesale():
    queue = 9_022
    await seed_match("SC_DIST", queue_id=queue)
    async with SessionLocal() as session:
        service = ScoreService(session)
        first = await service.rebuild_distributions()
        assert first > 0
        # Rebuilding must not accumulate: these are a measurement, not a log.
        assert await service.rebuild_distributions() == first


# --------------------------------------------------------------------- API


async def test_the_detail_endpoint_serves_the_whole_lobby(client):
    """The row shows one player's game; this is the other nine, which is the
    only place a lobby-wide placement can actually be checked."""
    queue = 9_030
    await seed_distributions(queue)
    await seed_match("SC_API", queue_id=queue, overrides={0: {"deaths": 0}})
    await score("SC_API")

    async with SessionLocal() as session:
        await session.execute(
            Match.__table__.update()
            .where(Match.match_id == "SC_API")
            .values(
                teams=[
                    {
                        "teamId": 100,
                        "win": True,
                        "bans": [{"championId": 103, "pickTurn": 1},
                                 {"championId": -1, "pickTurn": 2}],
                        "objectives": {
                            "champion": {"first": True, "kills": 30},
                            "baron": {"first": True, "kills": 1},
                            "dragon": {"first": False, "kills": 3},
                            "riftHerald": {"first": True, "kills": 1},
                            "tower": {"first": True, "kills": 9},
                            "inhibitor": {"first": True, "kills": 2},
                        },
                    },
                    {"teamId": 200, "win": False, "bans": [], "objectives": {}},
                ]
            )
        )
        await session.commit()

    response = await client.get("/api/matches/SC_API")
    assert response.status_code == 200
    body = response.json()

    assert [len(t) for t in body["teams"]] == [5, 5]
    assert body["score_withheld"] is None
    everyone = [p for team in body["teams"] for p in team]
    assert sorted(p["placement"] for p in everyone) == list(range(1, 11))
    assert all(p["score"] is not None for p in everyone)

    # The scoreboard's own columns, which the history payload does not carry.
    first = body["teams"][0][0]
    assert first["wards_placed"] == 10
    assert first["control_wards"] == 2
    assert first["damage_taken"] == 20_000
    assert 0 < first["kill_participation"] <= 1

    blue = next(o for o in body["objectives"] if o["team_id"] == 100)
    # Kills and gold are summed from the five players the scoreboard shows, not
    # read from the team object, which claimed 30. The two agree in a real 5v5
    # and disagree in Arena, so the players are the source.
    assert blue["kills"] == 25
    assert blue["gold"] == 50_000  # five players at 10,000 each
    # The counts with no participant to sum come from the team object, and are
    # published because its ids line up with the sides on the scoreboard.
    assert blue["objectives_known"] is True
    assert (blue["baron"], blue["dragon"], blue["tower"]) == (1, 3, 9)
    # -1 is Riot's "no ban", from a dodge or a timeout.
    assert len(blue["bans"]) == 1

    # The model travels with the scoreboard, weights and sample included.
    model = body["model"]
    assert model["version"] == WEIGHTS_VERSION
    assert len(model["components"]) == len(COMPONENTS)
    assert model["weights"]["UTILITY"]["vision"] > model["weights"]["BOTTOM"]["vision"]
    assert model["samples"]["MIDDLE"] == MIN_GAMES_FOR_SCORE
    assert "not Riot's" in model["note"]


async def test_a_withheld_lobby_says_why_and_publishes_no_model(client):
    """A scoreboard of dashes with no explanation is worse than no scoreboard."""
    queue = 9_031
    await seed_distributions(queue)
    await seed_match("SC_API_ARAM", queue_id=queue, positions=False)
    await score("SC_API_ARAM")

    body = (await client.get("/api/matches/SC_API_ARAM")).json()
    assert body["model"] is None
    assert "no lane roles" in body["score_withheld"]
    assert all(p["score"] is None for team in body["teams"] for p in team)


async def test_a_match_we_do_not_hold_is_a_404_not_a_fetch(client):
    """This endpoint never calls Riot: match history is what puts a match in
    storage, and it is always the page you arrived from."""
    response = await client.get("/api/matches/EUW1_0000000000")
    assert response.status_code == 404
    assert "match history" in response.json()["detail"]


async def test_badges_reach_the_api_with_their_rule_and_the_players_figure(client):
    queue = 9_032
    await seed_distributions(queue)
    await seed_match(
        "SC_API_BADGE",
        queue_id=queue,
        overrides={0: {"deaths": 0, "solo_kills": 4}},
    )
    await score("SC_API_BADGE")

    body = (await client.get("/api/matches/SC_API_BADGE")).json()
    first = body["teams"][0][0]
    by_id = {b["id"]: b for b in first["badges"]}
    assert "deathless" in by_id
    # The rule, then the player's own number for it.
    assert by_id["deathless"]["label"] == "Deathless"
    assert "without dying" in by_id["deathless"]["detail"]
    assert "0 deaths in 30 minutes" in by_id["deathless"]["detail"]
    assert "4 solo kills" in by_id["duelist"]["detail"]


async def test_objective_counts_are_withheld_when_riot_s_teams_do_not_line_up(client):
    """Arena sends team ids 100 and 0 while its players sit on 100 and 200, and
    the object for 100 claims 42 kills where those nine players have 72. Half of
    them describe nobody, so the counts that cannot be summed from the players
    are not published at all.
    """
    queue = 9_033
    await seed_distributions(queue)
    await seed_match("SC_API_ARENA", queue_id=queue, players=18, positions=False)
    async with SessionLocal() as session:
        await session.execute(
            Match.__table__.update()
            .where(Match.match_id == "SC_API_ARENA")
            .values(
                teams=[
                    {"teamId": 100, "win": True, "bans": [],
                     "objectives": {"champion": {"kills": 42},
                                    "tower": {"kills": 7}}},
                    {"teamId": 0, "win": False, "bans": [], "objectives": {}},
                ]
            )
        )
        await session.commit()

    body = (await client.get("/api/matches/SC_API_ARENA")).json()
    # Both sides are present, because both have players on the scoreboard.
    assert sorted(o["team_id"] for o in body["objectives"]) == [100, 200]
    for side in body["objectives"]:
        assert side["objectives_known"] is False
        assert (side["baron"], side["dragon"], side["tower"]) == (0, 0, 0)
        # Kills still reported: summed from that side's own nine players.
        assert side["kills"] == 45


async def test_a_component_with_no_breakpoints_means_the_distributions_need_a_rebuild():
    """Version 2 added a component. Any row at all used to count as measured,
    so the first run after the release scored nothing: every lobby was withheld
    for want of the new component's breakpoints."""
    from sqlalchemy import delete, select

    await seed_distributions(99430)
    async with SessionLocal() as session:
        service = ScoreService(session)
        assert await service.has_distributions()

        kept = [
            {c: getattr(r, c) for c in ("queue_id", "team_position", "metric", "breakpoints", "games")}
            for r in (
                await session.execute(
                    select(RoleMetricStat).where(RoleMetricStat.metric == "efficiency")
                )
            ).scalars()
        ]
        await session.execute(delete(RoleMetricStat).where(RoleMetricStat.metric == "efficiency"))
        await session.commit()
        try:
            assert not await service.has_distributions()
        finally:
            await session.execute(RoleMetricStat.__table__.insert(), kept)
            await session.commit()
        assert await service.has_distributions()
