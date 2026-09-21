"""Whether the people in a live lobby have met before.

Measured 2026-09-21 over the thirty most recent stored lobbies: 313 of 1,350
pairs (23%) share an earlier stored match, at least one pair had met in every
one of the thirty, and 55 pairs sit on the same side in two or more.

The figures are counts, never percentages, and nothing in the payload calls two
players a duo: they are pairs that keep landing on the same side in games we
happen to hold, and the crawler walks outward from stored matches, so that is an
upper bound rather than a census.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.config import get_settings
from app.db.base import SessionLocal
from app.db.models import Match, MatchParticipant
from app.riot.client import RiotClient
from app.services.live import (
    MIN_SAME_TEAM_GAMES,
    LiveGameService,
    LiveParticipant,
)

# Unique to this file: the suite shares one database.
ALICE = "shared-alice".ljust(78, "0")
BOB = "shared-bob".ljust(78, "0")
CARA = "shared-cara".ljust(78, "0")
DAN = "shared-dan".ljust(78, "0")
# Their own pair, so an earlier test's stored game cannot be the meeting.
ERIN = "shared-erin".ljust(78, "0")
FRED = "shared-fred".ljust(78, "0")
WATCHED_MATCH = "SHR1_7777777777"


async def seed_match(
    match_id: str,
    sides: dict[str, int],
    *,
    winner: int = 100,
    at: int = 1_789_000_000_000,
    remake: bool = False,
) -> None:
    """One stored game: `sides` maps a puuid to the team it was on."""
    async with SessionLocal() as session:
        session.add(
            Match(
                match_id=match_id,
                platform_id="SHR1",
                queue_id=420,
                game_mode="CLASSIC",
                game_type="MATCHED_GAME",
                game_version="16.18.1",
                patch="16.18",
                map_id=11,
                game_creation=at,
                game_duration=1_700,
                is_remake=remake,
                teams=[],
                raw={},
                lobby_rank_measured_at=datetime(2026, 9, 21, tzinfo=UTC),
            )
        )
        for i, (puuid, team) in enumerate(sides.items()):
            session.add(
                MatchParticipant(
                    match_id=match_id,
                    participant_index=i,
                    puuid=puuid,
                    champion_id=103,
                    champion_name="Ahri",
                    team_id=team,
                    team_position="MIDDLE",
                    individual_position="MIDDLE",
                    win=team == winner,
                    kills=5,
                    deaths=5,
                    assists=5,
                    champ_level=16,
                    gold_earned=12_000,
                    total_minions=180,
                    vision_score=18,
                    damage_to_champions=18_000,
                    damage_taken=17_000,
                    time_played=1_700,
                )
            )
        await session.commit()


def live(puuid: str, team_id: int) -> LiveParticipant:
    return LiveParticipant(
        puuid=puuid,
        champion_id=103,
        team_id=team_id,
        spell1_id=4,
        spell2_id=14,
        keystone_id=8008,
        secondary_style_id=8300,
        profile_icon_id=1,
        game_name="Shared",
        tag_line="EUW",
        state="ranked",
        position="MIDDLE",
    )


async def shared_for(participants: list[LiveParticipant], you: str):
    async with SessionLocal() as session:
        service = LiveGameService(session, RiotClient("RGAPI-test-key"), get_settings())
        pairs = await service._attach_shared_games(participants, you, WATCHED_MATCH)
    return {p.puuid: p.shared_games for p in participants}, pairs


async def test_two_players_who_never_met_carry_nothing():
    people = [live(ALICE, 100), live(DAN, 200)]
    shared, pairs = await shared_for(people, ALICE)
    assert shared[DAN] is None
    assert pairs == []


async def test_a_shared_game_is_split_by_side_and_counts_your_wins():
    # Beside each other and winning, beside each other and losing, then against.
    await seed_match("SHR1_1000000001", {ALICE: 100, BOB: 100}, winner=100)
    await seed_match("SHR1_1000000002", {ALICE: 100, BOB: 100}, winner=200)
    await seed_match("SHR1_1000000003", {ALICE: 100, BOB: 200}, winner=200)

    shared, _ = await shared_for([live(ALICE, 100), live(BOB, 200)], ALICE)

    row = shared[BOB]
    assert row.games == 3
    assert row.same_side == 2
    assert row.same_side_wins == 1
    assert row.opposite_side == 1
    assert row.opposite_side_wins == 0


async def test_the_searched_player_can_be_on_either_side_of_the_pair():
    """`a.puuid < b.puuid` dedupes the mirror row, so the searcher lands on
    either half and the wins against them have to be flipped for the second.
    Wrong, this produces plausible numbers and nothing complains."""
    await seed_match("SHR1_1000000004", {ALICE: 100, CARA: 200}, winner=100)

    from_alice, _ = await shared_for([live(ALICE, 100), live(CARA, 200)], ALICE)
    from_cara, _ = await shared_for([live(ALICE, 100), live(CARA, 200)], CARA)

    assert from_alice[CARA].opposite_side == 1
    assert from_alice[CARA].opposite_side_wins == 1
    assert from_cara[ALICE].opposite_side == 1
    assert from_cara[ALICE].opposite_side_wins == 0


async def test_the_game_being_watched_is_never_a_previous_meeting():
    """It cannot be in storage yet, but it will be the moment the result is
    fetched, and then a reload would report this game as a meeting."""
    await seed_match(WATCHED_MATCH, {ALICE: 100, DAN: 200}, winner=100)

    shared, _ = await shared_for([live(ALICE, 100), live(DAN, 200)], ALICE)

    assert shared[DAN] is None


async def test_a_pair_on_the_same_side_twice_is_reported_and_once_is_not():
    await seed_match("SHR1_1000000005", {BOB: 100, CARA: 100}, winner=100)
    await seed_match("SHR1_1000000006", {BOB: 100, CARA: 100}, winner=200)
    await seed_match("SHR1_1000000007", {ALICE: 100, DAN: 100}, winner=100)

    people = [live(ALICE, 100), live(BOB, 100), live(CARA, 100), live(DAN, 200)]
    _, pairs = await shared_for(people, ALICE)

    together = {tuple(sorted((p.puuid_a, p.puuid_b))): p for p in pairs}
    assert tuple(sorted((BOB, CARA))) in together
    assert tuple(sorted((ALICE, DAN))) not in together
    pair = together[tuple(sorted((BOB, CARA)))]
    assert pair.games == MIN_SAME_TEAM_GAMES
    assert pair.wins == 1


async def test_a_hidden_player_cannot_appear_in_the_overlap():
    """They have no puuid at all, so there is nothing to look up. The same
    reason they have no rank."""
    hidden = LiveParticipant(
        puuid=None,
        champion_id=64,
        team_id=200,
        spell1_id=4,
        spell2_id=11,
        keystone_id=8008,
        secondary_style_id=8300,
        profile_icon_id=1,
        game_name=None,
        tag_line=None,
        state="hidden",
    )
    people = [live(ALICE, 100), hidden]
    shared, pairs = await shared_for(people, ALICE)

    assert hidden.shared_games is None
    assert all(p.puuid_a and p.puuid_b for p in pairs)
    assert shared[ALICE] is None


async def test_remakes_are_not_meetings():
    await seed_match("SHR1_1000000008", {ERIN: 100, FRED: 200}, remake=True)
    shared, _ = await shared_for([live(ERIN, 100), live(FRED, 200)], ERIN)
    assert shared[FRED] is None
