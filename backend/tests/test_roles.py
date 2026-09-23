"""The lane model behind the live tab's positions.

spectator-v5 carries no position, so these pin the rules that make an inferred
one honest: a lone Smite is certain, a flex pick is not presented as if it were,
and a mode without lanes gets no lanes.
"""

from __future__ import annotations

import pytest

from app.db.base import SessionLocal
from app.services.roles import (
    CONFIDENT_AT,
    RolePriors,
    assign_partial,
    assign_team,
    clear_priors_cache,
    load_priors,
    usual_share,
)

FLASH, TELEPORT, SMITE, IGNITE, HEAL, EXHAUST = 4, 12, 11, 14, 7, 3

# One champion per role, each played only there.
ROLE_OF = {266: "TOP", 64: "JUNGLE", 103: "MIDDLE", 22: "BOTTOM", 412: "UTILITY"}
USUAL_SPELLS = {
    "TOP": (FLASH, TELEPORT), "JUNGLE": (FLASH, SMITE), "MIDDLE": (FLASH, IGNITE),
    "BOTTOM": (FLASH, HEAL), "UTILITY": (FLASH, EXHAUST),
}


def priors(extra: dict[int, dict[str, int]] | None = None) -> RolePriors:
    champion = {c: {role: 100} for c, role in ROLE_OF.items()}
    champion.update(extra or {})
    spell: dict[str, dict[int, int]] = {}
    for role, spells in USUAL_SPELLS.items():
        for s in spells:
            spell.setdefault(role, {})[s] = spell.get(role, {}).get(s, 0) + 100
    return RolePriors(champion=champion, spell=spell, participants=500)


def team(*champions: int, spells: dict[int, tuple[int, int]] | None = None):
    spells = spells or {}
    return [
        (c, *spells.get(c, USUAL_SPELLS.get(ROLE_OF.get(c, "MIDDLE"), (FLASH, IGNITE))))
        for c in champions
    ]


def test_each_player_lands_where_their_champion_is_played():
    # Listed out of lane order: the model must not lean on roster order.
    calls = assign_team(team(412, 103, 266, 22, 64), priors())
    assert [c.position for c in calls] == ["UTILITY", "MIDDLE", "TOP", "BOTTOM", "JUNGLE"]


def test_a_lone_smite_is_the_jungler_whatever_the_champion():
    """Smite is the one signal that is certain, so it outranks every prior."""
    # The top laner carries Smite; the jungler has none.
    spells = {266: (FLASH, SMITE), 64: (FLASH, IGNITE)}
    calls = assign_team(team(266, 64, 103, 22, 412, spells=spells), priors())
    by_champion = {c: call for c, call in zip((266, 64, 103, 22, 412), calls, strict=True)}
    assert by_champion[266].position == "JUNGLE"
    assert by_champion[266].basis == "smite"
    assert by_champion[266].confidence == 1.0


def test_two_smites_decide_nothing():
    """A laner running Smite too means Smite no longer identifies the jungler."""
    spells = {266: (FLASH, SMITE), 64: (FLASH, SMITE)}
    calls = assign_team(team(266, 64, 103, 22, 412, spells=spells), priors())
    assert all(call.basis == "inferred" for call in calls)
    assert [c.position for c in calls] == ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"]


def test_a_coin_flip_is_not_presented_as_a_fact():
    """Two flex picks with identical spells cannot be told apart, and must say so.

    This is the case the "likely" label exists for: measured on held-out games,
    a position below CONFIDENT_AT is right about half the time.
    """
    flex = {500: {"TOP": 50, "MIDDLE": 50}, 501: {"TOP": 50, "MIDDLE": 50}}
    same = {500: (FLASH, IGNITE), 501: (FLASH, IGNITE)}
    calls = assign_team(team(500, 501, 64, 22, 412, spells=same), priors(flex))
    flexed = calls[:2]
    assert {c.position for c in flexed} == {"TOP", "MIDDLE"}
    assert all(c.confidence < CONFIDENT_AT for c in flexed)
    # The three unambiguous players stay confident.
    assert all(c.confidence >= CONFIDENT_AT for c in calls[2:])


def test_an_unseen_champion_gets_a_flat_prior_not_a_veto():
    """A release the corpus has never stored must not break the whole team."""
    calls = assign_team(team(266, 64, 9999, 22, 412), priors())
    assert calls is not None
    assert calls[2].position == "MIDDLE", "the only lane left over"


def test_confidence_is_a_probability():
    for call in assign_team(team(266, 64, 103, 22, 412), priors()):
        assert 0.0 < call.confidence <= 1.0


def test_no_lanes_without_five_a_side():
    """ARAM and Arena have no lanes; inventing them would be worse than none."""
    assert assign_team(team(266, 64, 103), priors()) is None
    assert assign_team(team(266, 64, 103, 22, 412, 1), priors()) is None


async def test_the_counts_are_cached_and_can_be_dropped():
    clear_priors_cache()
    async with SessionLocal() as session:
        first = await load_priors(session)
        assert await load_priors(session) is first
        clear_priors_cache()
        assert await load_priors(session) is not first
    clear_priors_cache()


# ---------------------------------------------------- a team still being drafted


def test_a_partial_team_is_placed_one_pick_at_a_time():
    one = assign_partial([22], priors())
    assert [c.position for c in one.calls] == ["BOTTOM"]
    assert one.probabilities[0]["BOTTOM"] > 0.9
    assert sum(one.probabilities[0].values()) == pytest.approx(1.0)


def test_a_filled_position_is_not_offered_again():
    """Your allies are placed around you: with mid taken, Ahri is not mid."""
    allies = assign_partial([103, 22], priors(), exclude=["MIDDLE"])
    assert "MIDDLE" not in allies.probabilities[0]
    assert allies.calls[1].position == "BOTTOM"


def test_five_champions_are_placed_as_a_full_team_is_without_spells():
    full = assign_partial([266, 64, 103, 22, 412], priors())
    assert [c.position for c in full.calls] == [ROLE_OF[c] for c in (266, 64, 103, 22, 412)]


def test_a_flex_pick_splits_its_chance_between_its_roles():
    flex = 999
    split = assign_partial([flex], priors({flex: {"TOP": 50, "MIDDLE": 50}}))
    assert split.probabilities[0]["TOP"] == pytest.approx(split.probabilities[0]["MIDDLE"], abs=0.01)
    assert split.calls[0].confidence < CONFIDENT_AT


def test_more_champions_than_open_positions_is_no_answer():
    assert assign_partial([266, 64, 103, 22, 412, 1], priors()).calls == []
    assert assign_partial([], priors()).calls == []


def test_a_champions_usual_share_of_a_position():
    share, games = usual_share(priors({77: {"MIDDLE": 94, "TOP": 6}}), 77, "MIDDLE")
    assert (share, games) == (0.94, 100)
