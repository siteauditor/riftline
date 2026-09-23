"""The shared reading of a matchup or ally record: one posterior for the number
and the label."""

from __future__ import annotations

import pytest

from app.services.aggregate import poolable_patches
from app.services.evidence import (
    LANE_STRENGTH,
    TEAM_STRENGTH,
    RecordPart,
    read_records,
)


def read(wins, games, own, strength=LANE_STRENGTH):
    return read_records([RecordPart(wins, games, own)], strength)


def test_a_record_at_the_champions_own_rate_moves_nothing():
    """The old reading measured against the Wilson lower bound, so a record
    exactly at the champion's usual rate lifted it by several points."""
    record = read(54, 100, 0.54)
    assert record.lift == pytest.approx(0.0)
    assert record.call == "level"


def test_wins_and_losses_move_a_pick_by_the_same_amount():
    """A 2-0 added 1.2 points and an 0-2 took off 0.3 under the old reading."""
    assert read(2, 2, 0.5).lift == pytest.approx(-read(0, 2, 0.5).lift)


def test_two_games_move_a_pick_under_a_point_and_are_called_level():
    """Cassiopeia's 2-0 against Yasuo moved her from fifth to fourth."""
    record = read(2, 2, 0.527)
    assert 0 < record.lift < 0.01
    assert record.call == "level"
    assert read(4, 4, 0.5).call == "level"


def test_the_live_page_cases_keep_their_meaning():
    """3-2 is level; 40-20 is favoured as a lane record and level as a team
    record, which has to be bigger to say the same thing."""
    assert read(3, 5, 0.5).call == "level"
    assert read(40, 60, 0.5).call == "favoured"
    assert read(40, 60, 0.5, TEAM_STRENGTH).call == "level"
    assert read(20, 60, 0.5).call == "unfavoured"


def test_a_team_strength_record_moves_less_than_a_lane_one():
    assert 0 < read(40, 60, 0.5, TEAM_STRENGTH).lift < read(40, 60, 0.5).lift


def test_each_patch_is_centred_on_its_own_rate():
    """A champion buffed from 48% to 53%, with every record at its rate on the
    patch it came from, has no deviation to find when the patches are pooled."""
    parts = [RecordPart(53, 100, 0.53), RecordPart(29, 60, 0.4833)]
    pooled = read_records(parts, LANE_STRENGTH)
    assert pooled.lift == pytest.approx(0.0, abs=1e-3)
    assert pooled.games == 160
    assert pooled.wins == 82


def test_no_games_and_extreme_rates_do_not_break_the_reading():
    empty = read_records([], LANE_STRENGTH)
    assert (empty.games, empty.lift, empty.call) == (0, 0.0, "level")
    assert read(5, 5, 1.0).call == "level"
    assert read(0, 5, 0.0).call == "level"


def test_a_pool_is_the_patch_and_a_close_older_one():
    held = ["16.20", "16.18", "16.17", "16.14", "15.24"]
    assert poolable_patches(held, "16.18") == ("16.18", "16.17")
    # Newer patches are never pooled into an older anchor.
    assert poolable_patches(held, "16.14") == ("16.14",)
    # A season boundary is not crossed, and a gap over two minors is not closed.
    assert poolable_patches(["16.1", "15.24"], "16.1") == ("16.1",)
    assert poolable_patches(["16.9", "16.5"], "16.9") == ("16.9",)
    # A patch that is not numbers is never ordered against another.
    assert poolable_patches(["D29.00", "AGG.done"], "D29.00") == ("D29.00",)
    assert poolable_patches(["16.18", "AGG.done"], "16.18") == ("16.18",)
