"""Timeline parsing: checkpoints, skill order, purchase replay, laning score.

``extract`` and ``laning_scores`` are pure functions, so these run against
hand-written payloads with no database and no network. That is deliberate: the
parsing rules are where the bugs live, and a rule you can only exercise through
a live fetch is a rule nobody tests.
"""

from __future__ import annotations

import gzip
import json

import pytest

from app.services.timelines import (
    CS_FLOOR,
    EXTRACT_VERSION,
    Lane,
    extract,
    laning_scores,
    skill_priority,
)

# --------------------------------------------------------------------- builders

ITEM_A, ITEM_B, ITEM_C = 1001, 1002, 1003


def pframe(gold: int, xp: int, cs: int, level: int = 6) -> dict:
    return {
        "totalGold": gold,
        "xp": xp,
        "minionsKilled": cs,
        "jungleMinionsKilled": 0,
        "level": level,
    }


def timeline(frames: list[dict]) -> dict:
    return {"info": {"frameInterval": 60000, "frames": frames}}


def frame(participants: dict[int, dict], events: list[dict] | None = None) -> dict:
    return {
        "participantFrames": {str(k): v for k, v in participants.items()},
        "events": events or [],
    }


def flat(count: int, **kw) -> list[dict]:
    """`count` identical frames, so a test can reach a given minute cheaply."""
    people = {i: pframe(1000, 1000, 50) for i in range(1, 11)}
    return [frame(people) for _ in range(count)]


# ------------------------------------------------------------------- extraction


def test_extract_snapshots_only_the_minutes_the_game_reached():
    tl = timeline(flat(12))
    out = extract(tl, duration_seconds=11 * 60)
    # Minute 14 never happened, so it must not appear.
    assert sorted(out["cp"], key=int) == ["5", "10"]
    assert out["frames"] == 12


def test_extract_clamps_the_laning_mark_to_a_short_game():
    """A twelve minute game has no minute-14 measurement to report."""
    out = extract(timeline(flat(12)), duration_seconds=11 * 60)
    assert out["laning_minute"] == 10
    long_game = extract(timeline(flat(40)), duration_seconds=39 * 60)
    assert long_game["laning_minute"] == 14


def test_extract_survives_an_empty_timeline():
    out = extract({"info": {"frames": []}}, duration_seconds=0)
    assert out["frames"] == 0 and out["laning_minute"] is None


def test_skill_order_records_normal_level_ups_in_sequence():
    events = [
        {"type": "SKILL_LEVEL_UP", "participantId": 1, "skillSlot": s, "levelUpType": "NORMAL"}
        for s in (1, 2, 1, 3, 1)
    ]
    # An evolution is not a level-up choice and must not enter the order.
    events.append(
        {"type": "SKILL_LEVEL_UP", "participantId": 1, "skillSlot": 2, "levelUpType": "EVOLVE"}
    )
    out = extract(timeline([frame({1: pframe(0, 0, 0)}, events)]), duration_seconds=600)
    assert out["skills"]["1"] == [1, 2, 1, 3, 1]


def test_item_undo_cancels_the_item_it_names_not_the_last_purchase():
    """The whole reason purchases are replayed rather than filtered.

    Buying A then B and undoing A must leave B. A naive "drop the most recent
    entry" would leave A instead, which is exactly backwards, and real games
    contain a dozen of these.
    """
    events = [
        {"type": "ITEM_PURCHASED", "participantId": 1, "itemId": ITEM_A},
        {"type": "ITEM_PURCHASED", "participantId": 1, "itemId": ITEM_B},
        {"type": "ITEM_UNDO", "participantId": 1, "beforeId": ITEM_A, "afterId": 0},
    ]
    out = extract(timeline([frame({1: pframe(0, 0, 0)}, events)]), duration_seconds=600)
    assert out["buys"]["1"] == [ITEM_B]


def test_item_undo_removes_only_the_most_recent_copy():
    events = [
        {"type": "ITEM_PURCHASED", "participantId": 1, "itemId": ITEM_A},
        {"type": "ITEM_PURCHASED", "participantId": 1, "itemId": ITEM_B},
        {"type": "ITEM_PURCHASED", "participantId": 1, "itemId": ITEM_A},
        {"type": "ITEM_UNDO", "participantId": 1, "beforeId": ITEM_A, "afterId": 0},
    ]
    out = extract(timeline([frame({1: pframe(0, 0, 0)}, events)]), duration_seconds=600)
    assert out["buys"]["1"] == [ITEM_A, ITEM_B]


def test_purchase_times_stay_in_step_with_purchases_through_an_undo():
    """The item guide reads "when was this finished" from the time beside each
    purchase, so an undo has to take its time with it, from the right place."""
    events = [
        {"type": "ITEM_PURCHASED", "participantId": 1, "itemId": ITEM_A, "timestamp": 61_000},
        {"type": "ITEM_PURCHASED", "participantId": 1, "itemId": ITEM_B, "timestamp": 62_500},
        {"type": "ITEM_PURCHASED", "participantId": 1, "itemId": ITEM_A, "timestamp": 700_000},
        {"type": "ITEM_UNDO", "participantId": 1, "beforeId": ITEM_B, "afterId": 0},
        {"type": "ITEM_PURCHASED", "participantId": 1, "itemId": ITEM_C, "timestamp": 1_260_900},
    ]
    out = extract(timeline([frame({1: pframe(0, 0, 0)}, events)]), duration_seconds=1800)
    assert out["buys"]["1"] == [ITEM_A, ITEM_A, ITEM_C]
    assert out["buy_times"]["1"] == [61, 700, 1260], "seconds, one per purchase"


def test_selling_an_item_does_not_erase_it_from_the_build():
    """A build path that hides the item you sold describes a game nobody played."""
    events = [
        {"type": "ITEM_PURCHASED", "participantId": 1, "itemId": ITEM_A},
        {"type": "ITEM_SOLD", "participantId": 1, "itemId": ITEM_A},
        {"type": "ITEM_PURCHASED", "participantId": 1, "itemId": ITEM_C},
    ]
    out = extract(timeline([frame({1: pframe(0, 0, 0)}, events)]), duration_seconds=600)
    assert out["buys"]["1"] == [ITEM_A, ITEM_C]


def test_objectives_capture_time_kind_and_team():
    """A building's ``teamId`` is the side that lost it. Measured on a stored
    game: participant 4, on blue, killed a tower whose event says 200, at red's
    bottom outer position. So that tower is blue's."""
    events = [
        {"type": "ELITE_MONSTER_KILL", "timestamp": 600_000, "monsterType": "DRAGON", "killerTeamId": 100},
        {"type": "BUILDING_KILL", "timestamp": 900_000, "buildingType": "TOWER_BUILDING", "teamId": 200},
    ]
    out = extract(timeline([frame({1: pframe(0, 0, 0)}, events)]), duration_seconds=1200)
    assert out["obj"] == [
        [600, "monster", "DRAGON", 100],
        [900, "building", "TOWER_BUILDING", 100],
    ]


def test_team_frames_sum_each_side_at_every_frame():
    people = {pid: pframe(1000 * pid, 0, 10, level=pid) for pid in range(1, 11)}
    frames = [frame(people) for _ in range(3)]
    for minute, f in enumerate(frames):
        f["timestamp"] = minute * 60_000
    out = extract(timeline(frames), duration_seconds=3 * 60)

    # Blue is 1 to 5, red 6 to 10: gold 15k against 40k, levels 15 against 40.
    assert out["tf"][2] == [120_000, 15_000, 40_000, 15, 40, 50, 50]
    assert len(out["tf"]) == 3
    assert out["v"] == EXTRACT_VERSION


def test_state_events_credit_the_team_that_gained():
    events = [
        # Red's 7 kills blue's 2 with 8 assisting, for a bounty and a shutdown.
        {"type": "CHAMPION_KILL", "timestamp": 61_000, "killerId": 7, "victimId": 2,
         "assistingParticipantIds": [8], "bounty": 300, "shutdownBounty": 150,
         "position": {"x": 100, "y": 200}},
        # A turret finishes blue's 3: nobody killed them, red still gained.
        {"type": "CHAMPION_KILL", "timestamp": 62_000, "killerId": 0, "victimId": 3},
        {"type": "ELITE_MONSTER_KILL", "timestamp": 63_000, "monsterType": "DRAGON",
         "monsterSubType": "FIRE_DRAGON", "killerTeamId": 100, "killerId": 1,
         "assistingParticipantIds": [2, 7]},
        {"type": "ELITE_MONSTER_KILL", "timestamp": 64_000, "monsterType": "DRAGON",
         "monsterSubType": "ELDER_DRAGON", "killerTeamId": 200, "killerId": 6},
        {"type": "ELITE_MONSTER_KILL", "timestamp": 65_000, "monsterType": "HORDE",
         "killerTeamId": 200, "killerId": 7},
        {"type": "ELITE_MONSTER_KILL", "timestamp": 66_000, "monsterType": "SOMETHING_NEW",
         "killerTeamId": 200},
        {"type": "BUILDING_KILL", "timestamp": 67_000, "buildingType": "TOWER_BUILDING",
         "teamId": 200, "killerId": 4},
        {"type": "BUILDING_KILL", "timestamp": 68_000, "buildingType": "INHIBITOR_BUILDING",
         "teamId": 100, "killerId": 9},
        {"type": "TURRET_PLATE_DESTROYED", "timestamp": 69_000, "teamId": 100, "killerId": 8},
    ]
    out = extract(timeline([frame({1: pframe(0, 0, 0)}, events)]), duration_seconds=1200)
    rows = [(r[1], r[2], r[3], r[4], r[5], r[8]) for r in out["ev"]]

    assert rows == [
        ("kill", 200, 7, 2, [8], 450),
        ("kill", 200, 0, 3, [], 0),
        # Assisters from both teams: a contested dragon, kept as Riot sent it.
        ("dragon", 100, 1, 0, [2, 7], 0),
        ("elder", 200, 6, 0, [], 0),
        ("grubs", 200, 7, 0, [], 0),
        # The unknown monster is dropped rather than guessed at.
        ("tower", 100, 4, 0, [], 0),
        ("inhib", 200, 9, 0, [], 0),
        ("plate", 200, 8, 0, [], 0),
    ]
    assert out["ev"][0][6:8] == [100, 200], "the position is kept for the death map"


# ----------------------------------------------------------------- laning score


def laned(mine: tuple[int, int, int], theirs: tuple[int, int, int]) -> dict:
    """A 40-frame game where participants 1 and 2 share MIDDLE on opposite teams."""
    frames = flat(40)
    frames[14] = frame({1: pframe(*mine), 2: pframe(*theirs)})
    return extract(timeline(frames), duration_seconds=39 * 60)


LANES = [Lane(1, "MIDDLE", 100), Lane(2, "MIDDLE", 200)]


def test_an_even_lane_scores_fifty_fifty():
    scores = laning_scores(laned((5000, 6000, 100), (5000, 6000, 100)), LANES)
    assert scores[1].score == pytest.approx(0.5)
    assert scores[2].score == pytest.approx(0.5)
    assert scores[1].inputs == 3


def test_a_won_lane_scores_above_half_and_reports_the_gap():
    scores = laning_scores(laned((7000, 8000, 130), (5000, 6000, 90)), LANES)
    me = scores[1]
    assert me.score > 0.5
    assert (me.gold_diff, me.xp_diff, me.cs_diff) == (2000, 2000, 40)
    assert me.opponent_index == 2
    # The two halves of a lane are complementary by construction.
    assert me.score + scores[2].score == pytest.approx(1.0)


def test_supports_drop_cs_from_the_blend():
    """Below the floor a CS share measures noise, not lane control."""
    low = (CS_FLOOR // 2) - 1
    scores = laning_scores(laned((4000, 5000, low), (4000, 5000, low)), LANES)
    assert scores[1].inputs == 2, "CS must be excluded for a non-farming pair"

    scores = laning_scores(laned((4000, 5000, 100), (4000, 5000, 100)), LANES)
    assert scores[1].inputs == 3


def test_a_lane_with_no_opposite_number_scores_nothing():
    """ARAM and Arena have no lane, and inventing one would be worse than silence."""
    solo = [Lane(1, "MIDDLE", 100), Lane(2, "MIDDLE", 100)]  # same team
    assert laning_scores(laned((5000, 6000, 100), (5000, 6000, 100)), solo) == {}
    assert laning_scores(laned((5000, 6000, 100), (5000, 6000, 100)), [Lane(1, None, 100)]) == {}


def test_no_score_when_the_game_ended_before_any_checkpoint():
    tiny = extract(timeline(flat(2)), duration_seconds=90)
    assert laning_scores(tiny, LANES) == {}


# -------------------------------------------------------------- skill priority


@pytest.mark.parametrize(
    ("order", "expected", "why"),
    [
        ([1, 2, 3, 1, 1, 4, 1, 3, 1, 3, 4, 3, 3, 2, 2, 4, 2, 2], [1, 3, 2], "Q then E then W"),
        ([2, 1, 3, 2, 2, 4, 2, 2], [2], "only W reached five points"),
        ([], None, "nothing levelled"),
    ],
)
def test_skill_priority_reports_what_was_maxed_in_order(order, expected, why):
    assert skill_priority(order) == expected, why


def test_skill_priority_ignores_the_ultimate():
    """Slot 4 is on a fixed schedule, so it carries no choice."""
    assert 4 not in (skill_priority([4, 4, 4, 1, 1, 1, 1, 1]) or [])


# --------------------------------------------------------------------- storage


def test_gzip_round_trips_the_payload():
    payload = timeline(flat(30))
    blob = gzip.compress(json.dumps(payload, separators=(",", ":")).encode(), 9)
    assert json.loads(gzip.decompress(blob)) == payload
    # The whole reason we can afford to keep raw payloads at all.
    assert len(blob) < len(json.dumps(payload).encode())
