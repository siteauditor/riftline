"""What the corpus says about the players in a live lobby, rather than about
their champions.

Measured 2026-09-21: a median of 9 of 10 players in a recent stored lobby have
three or more other stored games, every one of them scored. So these records
are populated for almost everyone in a crawled bracket, and the interesting
cases are the edges: the player we hold two games for, the one we hold none
for, and the one whose usual role cannot be named.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
import respx

from app.config import get_settings
from app.db.base import SessionLocal
from app.db.models import Match, MatchParticipant
from app.riot.client import RiotClient
from app.services.live import (
    MAIN_ROLE_SHARE,
    MIN_GAMES_FOR_MAIN_ROLE,
    MIN_GAMES_FOR_WIN_RATE,
    MIN_RECORD_GAMES,
    LiveGameService,
    _main_position,
)
from tests.test_live import mock_spectator, spectator_game, spectator_participant

# Unique to this file: the suite shares one database.
QUEUE = 99902


def puuid(name: str) -> str:
    return f"rec-{name}".ljust(78, "0")


async def seed(
    player: str,
    *,
    games: int,
    wins: int,
    champion_id: int = 103,
    position: str = "MIDDLE",
    scored: bool = True,
    queue_id: int = QUEUE,
    start: int = 0,
) -> None:
    """`games` stored games for one player, in one role on one champion."""
    async with SessionLocal() as session:
        for i in range(games):
            match_id = f"REC1_{start + 9200000000 + i}"
            session.add(
                Match(
                    match_id=match_id,
                    platform_id="REC1",
                    queue_id=queue_id,
                    game_mode="CLASSIC",
                    game_type="MATCHED_GAME",
                    game_version="16.18.1",
                    patch="16.18",
                    map_id=11,
                    game_creation=1_789_000_000_000 + i * 3_600_000,
                    game_duration=1_700,
                    is_remake=False,
                    teams=[],
                    raw={},
                    # Stamped as measured so the lobby rank backfill, which
                    # walks every stored match with no reading, does not adopt
                    # these rows and change what its own tests see.
                    lobby_rank_measured_at=datetime(2026, 9, 21, tzinfo=UTC),
                )
            )
            session.add(
                MatchParticipant(
                    match_id=match_id,
                    participant_index=0,
                    puuid=player,
                    champion_id=champion_id,
                    champion_name="Ahri",
                    team_id=100,
                    team_position=position,
                    individual_position=position,
                    win=i < wins,
                    kills=8,
                    deaths=3,
                    assists=9,
                    champ_level=17,
                    gold_earned=13_000,
                    total_minions=200,
                    vision_score=20,
                    damage_to_champions=22_000,
                    damage_taken=18_000,
                    time_played=1_700,
                    performance_score=6.0 if scored else None,
                )
            )
        await session.commit()


async def records_for(player: str, *, queue_id: int = QUEUE, champion_id: int = 103):
    """Drive the service directly, which is how cache and floor rules are tested
    here: a request level test cannot tell a withheld record from a cold one."""
    async with SessionLocal() as session:
        service = LiveGameService(session, RiotClient("RGAPI-test-key"), get_settings())
        participants = [
            spectator_participant_to_live(player, champion_id=champion_id, position="MIDDLE")
        ]
        basis, scoped_queue = await service._attach_player_records(participants, queue_id)
        return participants[0], basis, scoped_queue


def spectator_participant_to_live(player: str, *, champion_id: int, position: str):
    from app.services.live import LiveParticipant

    return LiveParticipant(
        puuid=player,
        champion_id=champion_id,
        team_id=100,
        spell1_id=4,
        spell2_id=14,
        keystone_id=8008,
        secondary_style_id=8300,
        profile_icon_id=1,
        game_name="Rec",
        tag_line="EUW",
        state="ranked",
        position=position,
    )


async def test_a_player_we_hold_nothing_for_reads_as_nothing():
    """Not as a weak record. A zeroed one renders as somebody who loses."""
    p, _, _ = await records_for(puuid("empty"))
    assert p.stored_games == 0
    assert p.record is None


async def test_a_record_under_the_floor_is_withheld_but_its_size_is_not():
    player = puuid("thin")
    await seed(player, games=MIN_RECORD_GAMES - 1, wins=1, start=100)
    p, _, _ = await records_for(player)
    assert p.stored_games == MIN_RECORD_GAMES - 1
    assert p.record is None


async def test_the_record_carries_its_sample_and_both_dates():
    player = puuid("dated")
    await seed(player, games=4, wins=3, start=200)
    p, _, _ = await records_for(player)
    assert p.record is not None
    overall = p.record.overall
    assert (overall.games, overall.wins, overall.losses) == (4, 3, 1)
    assert overall.first_played == 1_789_000_000_000
    assert overall.last_played == 1_789_000_000_000 + 3 * 3_600_000


async def test_a_win_rate_is_withheld_under_ten_games_but_the_record_is_not():
    thin, thick = puuid("wr-thin"), puuid("wr-thick")
    await seed(thin, games=MIN_GAMES_FOR_WIN_RATE - 1, wins=6, start=300)
    await seed(thick, games=MIN_GAMES_FOR_WIN_RATE, wins=6, start=400)

    p_thin, _, _ = await records_for(thin)
    p_thick, _, _ = await records_for(thick)

    assert p_thin.record.overall.win_rate is None
    assert p_thin.record.overall.wins == 6
    assert p_thick.record.overall.win_rate == pytest.approx(0.6)


async def test_an_average_score_says_how_many_games_it_is_over():
    player = puuid("scored")
    await seed(player, games=5, wins=3, scored=True, start=500)
    p, _, _ = await records_for(player)
    assert p.record.overall.scored_games == 5
    assert p.record.overall.avg_score == pytest.approx(6.0)


async def test_an_unscored_record_has_no_average_rather_than_a_zero():
    player = puuid("unscored")
    await seed(player, games=4, wins=2, scored=False, start=600)
    p, _, _ = await records_for(player)
    assert p.record.overall.scored_games == 0
    assert p.record.overall.avg_score is None


async def test_off_role_needs_a_usual_role_to_be_off():
    """A two role player has no usual role, so they are never off it. Measured:
    of 712 players with eight or more positioned games the top role holds a
    median 76%, and at a 50% floor a genuine flex player would be mislabelled."""
    flex, main = puuid("flex"), puuid("main")
    half = MIN_GAMES_FOR_MAIN_ROLE // 2
    await seed(flex, games=half, wins=2, position="TOP", start=700)
    await seed(flex, games=half, wins=2, position="MIDDLE", start=800)
    await seed(main, games=MIN_GAMES_FOR_MAIN_ROLE, wins=4, position="MIDDLE", start=900)

    p_flex, _, _ = await records_for(flex)
    p_main, _, _ = await records_for(main)

    assert p_flex.record.main_position is None
    assert p_flex.record.on_main_position is None
    assert p_main.record.main_position == "MIDDLE"
    # The live participant above is placed MIDDLE, so this one is on their role.
    assert p_main.record.on_main_position is True


async def test_a_player_out_of_their_lane_is_marked_off_role():
    player = puuid("offrole")
    await seed(player, games=MIN_GAMES_FOR_MAIN_ROLE, wins=4, position="UTILITY", start=1000)
    p, _, _ = await records_for(player)
    assert p.record.main_position == "UTILITY"
    assert p.record.on_main_position is False


async def test_the_champion_record_is_for_the_champion_they_are_on():
    player = puuid("champs")
    await seed(player, games=4, wins=3, champion_id=103, start=1100)
    await seed(player, games=3, wins=0, champion_id=64, start=1200)

    on_ahri, _, _ = await records_for(player, champion_id=103)
    on_lee, _, _ = await records_for(player, champion_id=64)
    never_played, _, _ = await records_for(player, champion_id=777)

    assert on_ahri.record.on_champion.games == 4
    assert on_lee.record.on_champion.games == 3
    assert on_lee.record.on_champion.wins == 0
    # Null, not a zeroed record: mastery is what says they never played it.
    assert never_played.record.on_champion is None


async def test_the_record_is_read_from_the_queue_being_played_when_it_is_solo():
    player = puuid("queues")
    await seed(player, games=4, wins=4, queue_id=420, start=1300)
    await seed(player, games=6, wins=0, queue_id=450, start=1400)

    solo, basis, scoped = await records_for(player, queue_id=420)
    aram, aram_basis, aram_scoped = await records_for(player, queue_id=450)

    assert (basis, scoped) == ("queue", 420)
    assert solo.record.overall.games == 4
    # ARAM and flex fall back to every queue: the crawl is nearly all solo, so
    # scoping them to themselves would blank every card in the lobby.
    assert (aram_basis, aram_scoped) == ("all_queues", None)
    assert aram.record.overall.games == 10


def test_the_usual_role_breaks_ties_the_same_way_every_run():
    """A set iteration tiebreak has shipped in this codebase before."""
    even = {"TOP": 5, "JUNGLE": 5}
    assert _main_position(even) == _main_position(dict(reversed(list(even.items()))))
    assert _main_position({"TOP": 9, "MIDDLE": 1})[0] == "TOP"
    assert _main_position({"TOP": 2}) == (None, 0)
    # Exactly at the share floor counts as a usual role.
    at_floor = {"TOP": 6, "MIDDLE": 4}
    assert sum(at_floor.values()) >= MIN_GAMES_FOR_MAIN_ROLE
    assert at_floor["TOP"] / sum(at_floor.values()) == MAIN_ROLE_SHARE
    assert _main_position(at_floor)[0] == "TOP"


@respx.mock
async def test_the_records_reach_the_wire_and_cost_no_riot_call(client):
    """The two queries are storage only. The spectator call is the live
    lookup's own and nothing here adds to it."""
    from tests.test_integration import mock_riot

    player = puuid("wire")
    await seed(player, games=5, wins=4, queue_id=420, start=1500)
    mock_riot()
    respx.get(url__regex=r".*/riot/account/v1/accounts/by-riot-id/.*").mock(
        return_value=httpx.Response(
            200, json={"puuid": player, "gameName": "Rec", "tagLine": "EUW"}
        )
    )
    mock_spectator(
        spectator_game(
            [spectator_participant(puuid=player, riot_id="Rec#EUW", champion_id=103)],
            queue_id=420,
        )
    )

    body = (await client.get("/api/summoner/euw1/Rec/EUW/live")).json()

    game = body["game"]
    assert game["record_basis"] == "queue"
    assert game["record_queue_id"] == 420
    row = next(p for p in game["participants"] if p["puuid"] == player)
    assert row["stored_games"] == 5
    assert row["record"]["overall"]["wins"] == 4
    assert row["record"]["overall"]["win_rate"] is None  # five games is under the floor
    assert row["record"]["min_games"] == MIN_RECORD_GAMES
