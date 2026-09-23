"""The two sides of a live lobby, beside each other.

Pure arithmetic over what the other readers attached, so these drive the
function directly with hand built participants. The rules that matter are the
ones that keep it honest: a rank gap that cannot be subtracted across the apex
boundary, a lane that is only favoured when its own sample supports it, a player
we could not measure counting in neither the numerator nor the denominator, and
no win probability anywhere.
"""

from __future__ import annotations

import httpx
import respx

from app.db.models import RankedEntry
from app.services.live import (
    LOW_MASTERY_LEVEL,
    MIN_RANKED_PER_SIDE,
    CorpusRecord,
    LiveMastery,
    LiveParticipant,
    PlayedRecord,
    PlayerRecord,
    side_read,
)
from tests.test_live import mock_spectator, spectator_game

LANES = ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"]


def ranked(tier: str, division: str | None, lp: int) -> RankedEntry:
    return RankedEntry(
        puuid="x" * 78,
        queue_type="RANKED_SOLO_5x5",
        tier=tier,
        division=division,
        league_points=lp,
        wins=10,
        losses=10,
    )


def player(
    team_id: int,
    position: str,
    *,
    tier: str | None = "GOLD",
    division: str | None = "II",
    lp: int = 40,
    state: str = "ranked",
    mastery_level: int | None = 7,
    mastery_known: bool = True,
    main_position: str | None = None,
    on_main: bool | None = None,
    lane: CorpusRecord | None = None,
    champion: CorpusRecord | None = None,
    puuid: str | None = None,
) -> LiveParticipant:
    record = None
    if main_position is not None or on_main is not None:
        record = PlayerRecord(
            overall=PlayedRecord(games=20, wins=10, scored_games=20, score_total=100.0),
            on_champion=None,
            main_position=main_position,
            main_position_games=14,
            positioned_games=20,
            on_main_position=on_main,
        )
    return LiveParticipant(
        puuid=puuid or f"side-{team_id}-{position}".ljust(78, "0"),
        champion_id=103,
        team_id=team_id,
        spell1_id=4,
        spell2_id=14,
        keystone_id=8008,
        secondary_style_id=8300,
        profile_icon_id=1,
        game_name="Side",
        tag_line="EUW",
        state=state,  # type: ignore[arg-type]
        rank=ranked(tier, division, lp) if tier else None,
        position=position,
        mastery=(
            LiveMastery(level=mastery_level, points=10_000, last_play_time=None)
            if mastery_level is not None
            else None
        ),
        mastery_known=mastery_known,
        champion_record=champion,
        lane_record=lane,
        record=record,
    )


def lobby(blue: list[LiveParticipant], red: list[LiveParticipant]):
    return side_read(blue + red, 420, None)


def test_a_side_rank_is_withheld_below_three_of_five_but_the_counts_are_not():
    blue = [player(100, LANES[i]) for i in range(2)] + [
        player(100, LANES[i], state="hidden", tier=None) for i in range(2, 5)
    ]
    red = [player(200, LANES[i]) for i in range(5)]
    compare = lobby(blue, red)

    thin, whole = compare.sides
    assert thin.ranked == 2 < MIN_RANKED_PER_SIDE
    assert thin.tier is None and thin.median_points is None
    assert thin.hidden == 3
    assert whole.tier == "GOLD"


def test_the_gap_is_withheld_across_the_apex_boundary():
    """One point separates Diamond I from Master on `numeric_rank`, and the apex
    stride is 100,000, so a subtraction there is not a rank gap."""
    you = player(100, "TOP", tier="DIAMOND", division="I", lp=100, puuid="you".ljust(78, "0"))
    blue = [you] + [player(100, LANES[i], tier="MASTER", division=None, lp=300) for i in range(1, 5)]
    red = [player(200, LANES[i], tier="MASTER", division=None, lp=300) for i in range(5)]

    compare = side_read(blue + red, 420, "you".ljust(78, "0"))

    red_side = compare.sides[1]
    assert red_side.tier == "MASTER"
    assert red_side.gap_basis == "tiers_only"
    assert red_side.points_gap is None
    assert red_side.tier_gap == 1


def test_the_gap_in_points_is_published_inside_the_ordinary_scale():
    you = player(100, "TOP", tier="GOLD", division="II", lp=40, puuid="you2".ljust(78, "0"))
    blue = [you] + [player(100, LANES[i]) for i in range(1, 5)]
    red = [player(200, LANES[i], tier="PLATINUM", division="IV", lp=10) for i in range(5)]

    compare = side_read(blue + red, 420, "you2".ljust(78, "0"))

    red_side = compare.sides[1]
    assert red_side.gap_basis == "points"
    assert red_side.tier_gap == 1
    assert red_side.points_gap > 0


def test_a_lane_is_only_favoured_when_its_own_sample_supports_it():
    """A 3-2 over five games is not a favoured lane. A 40-20 over sixty is."""
    thin = CorpusRecord(games=5, wins=3, basis="lane")
    strong = CorpusRecord(games=60, wins=40, basis="lane")
    base = CorpusRecord(games=500, wins=250, basis="role")

    thin_lobby = lobby(
        [player(100, LANES[i], lane=thin if i == 0 else None, champion=base) for i in range(5)],
        [player(200, LANES[i]) for i in range(5)],
    )
    strong_lobby = lobby(
        [player(100, LANES[i], lane=strong if i == 0 else None, champion=base) for i in range(5)],
        [player(200, LANES[i]) for i in range(5)],
    )

    assert thin_lobby.lanes_with_record == 1
    assert thin_lobby.lanes_level == 1
    assert thin_lobby.sides[0].lanes_favoured == 0
    assert strong_lobby.sides[0].lanes_favoured == 1
    assert strong_lobby.lanes_level == 0


def test_a_team_basis_record_has_to_be_bigger_to_say_the_same_thing():
    """The prior follows the basis, the way the draft weighs its own evidence:
    a record of two champions merely sharing a game says less per game. A 40-20
    is a favoured lane and, as a team scope record, a level one."""
    same_numbers = dict(games=60, wins=40)
    base = CorpusRecord(games=500, wins=250, basis="role")
    as_lane = CorpusRecord(**same_numbers, basis="lane")
    as_team = CorpusRecord(**same_numbers, basis="team")

    lane_lobby = lobby(
        [player(100, LANES[i], lane=as_lane if i == 0 else None, champion=base) for i in range(5)],
        [player(200, LANES[i]) for i in range(5)],
    )
    team_lobby = lobby(
        [player(100, LANES[i], lane=as_team if i == 0 else None, champion=base) for i in range(5)],
        [player(200, LANES[i]) for i in range(5)],
    )
    assert lane_lobby.sides[0].lanes_favoured == 1
    assert team_lobby.sides[0].lanes_favoured == 0
    assert team_lobby.lanes_level == 1


def test_lanes_without_a_record_are_counted_in_neither_direction():
    compare = lobby(
        [player(100, LANES[i]) for i in range(5)],
        [player(200, LANES[i]) for i in range(5)],
    )
    assert compare.lanes_total == 5
    assert compare.lanes_with_record == 0
    assert compare.sides[0].lanes_favoured == 0
    assert compare.sides[1].lanes_favoured == 0


def test_a_player_we_could_not_measure_is_counted_in_neither_part_of_the_ratio():
    """`mastery_known` False means the lookup did not finish, which says nothing
    about the player, so they leave the denominator as well as the numerator."""
    blue = [
        player(100, LANES[0], mastery_level=1),
        player(100, LANES[1], mastery_level=None, mastery_known=False),
        player(100, LANES[2], mastery_level=12),
        player(100, LANES[3], mastery_level=12),
        player(100, LANES[4], mastery_level=12),
    ]
    compare = lobby(blue, [player(200, LANES[i]) for i in range(5)])

    side = compare.sides[0]
    assert side.off_champion == 1
    assert side.off_champion_known == 4
    assert LOW_MASTERY_LEVEL == 3


def test_off_role_counts_only_players_whose_usual_role_we_know():
    blue = [
        player(100, LANES[0], main_position="UTILITY", on_main=False),
        player(100, LANES[1], main_position="JUNGLE", on_main=True),
        player(100, LANES[2], main_position=None, on_main=None),
        player(100, LANES[3]),
        player(100, LANES[4]),
    ]
    compare = lobby(blue, [player(200, LANES[i]) for i in range(5)])

    side = compare.sides[0]
    assert side.off_role == 1
    assert side.off_role_known == 2


def test_arena_has_no_sides_to_compare():
    """Eight teams of two is not two sides, and inventing a pair would be a
    division we cannot see."""
    players = [player(t, LANES[0]) for t in (100, 200, 300, 400)]
    assert side_read(players, 1700, None) is None


@respx.mock
async def test_there_is_no_win_probability_anywhere_on_the_wire(client, monkeypatch):
    """A rule test. The site holds no model that predicts a game, and about a
    third of every lobby is hidden in a way that is not missing at random."""
    import re

    from tests.test_integration import mock_riot
    from tests.test_live import full_roster, lane_priors

    monkeypatch.setattr("app.services.live.load_priors", lane_priors)
    mock_riot()
    respx.get(url__regex=r".*/riot/account/v1/accounts/by-riot-id/.*").mock(
        return_value=httpx.Response(
            200, json={"puuid": "z" * 78, "gameName": "Caps", "tagLine": "EUW"}
        )
    )
    mock_spectator(spectator_game(full_roster("sides"), queue_id=420))

    body = (await client.get("/api/summoner/euw1/Caps/EUW/live")).json()

    banned = re.compile(r"win_probability|win_chance|odds|predicted|favou?rite", re.I)
    assert body["game"]["sides"] is not None
    assert not banned.search(str(body)), "the live response must not predict the game"


@respx.mock
async def test_the_sides_reach_the_wire_with_their_counts(client, monkeypatch):
    from tests.test_integration import mock_riot
    from tests.test_live import full_roster, lane_priors

    monkeypatch.setattr("app.services.live.load_priors", lane_priors)
    mock_riot()
    respx.get(url__regex=r".*/riot/account/v1/accounts/by-riot-id/.*").mock(
        return_value=httpx.Response(
            200, json={"puuid": "z" * 78, "gameName": "Caps", "tagLine": "EUW"}
        )
    )
    mock_spectator(spectator_game(full_roster("sides2"), queue_id=420))

    sides = (await client.get("/api/summoner/euw1/Caps/EUW/live")).json()["game"]["sides"]

    assert [s["team_id"] for s in sides["sides"]] == [100, 200]
    assert sides["lanes_total"] == 5
    assert sides["min_ranked_per_side"] == MIN_RANKED_PER_SIDE
    # Every side ships its denominators, so a blank panel can say why it is blank.
    for side in sides["sides"]:
        assert {"ranked", "hidden", "unknown", "off_champion_known"} <= side.keys()
