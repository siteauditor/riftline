"""The death and kill review: the trade and conversion rules, contests, what
each event cost or gained, and the profile's percentiles and floors.

The rules run against hand-built event lists. The profile runs against rows
inserted directly, on a queue id nothing else in the suite uses, so the rows
other tests leave in the shared database cannot move its percentiles.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.db.base import SessionLocal
from app.db.models import ParticipantReview
from app.services.reviews import (
    CONVERTED,
    GAINED,
    LOST,
    MIN_PROFILE_GAMES,
    TRADE_MS,
    UNTRADED,
    rebuild_review_distributions,
    review_game,
    review_profile,
)
from app.services.timelines import BLUE, RED
from app.services.winchance import FEATURES, Fitted, WinModel, evaluate

QUEUE = 99420


def extract(events: list) -> dict:
    tf = [[m * 60_000, 2500 * m, 2500 * m, 5 * m, 5 * m, 30 * m, 30 * m] for m in range(31)]
    return {"v": 2, "tf": tf, "ev": events}


def kill(ms: int, killer: int, victim: int, assists: list[int] | None = None, gold: int = 300) -> list:
    team = BLUE if killer and killer <= 5 else RED
    if not killer:
        team = RED if victim <= 5 else BLUE
    return [ms, "kill", team, killer, victim, assists or [], 1000, 2000, gold]


def model() -> WinModel:
    width = 2 + 2 * len(FEATURES)
    w = np.zeros(width)
    gold, kills = FEATURES.index("gold"), FEATURES.index("kills")
    for i, value in ((gold, 0.8), (kills, 0.3)):
        w[2 + i] = value
        w[2 + len(FEATURES) + i] = value
    fitted = Fitted(w, np.zeros(width), np.ones(width))
    return WinModel(version=3, published=True, withheld=None, fitted=fitted, payload={})


# ------------------------------------------------------------------- trades


def test_a_death_is_traded_at_exactly_a_minute_and_not_a_second_later():
    t = 5 * 60_000
    on_time = review_game(extract([kill(t, 7, 2), kill(t + TRADE_MS, 1, 8)]))
    late = review_game(extract([kill(t, 7, 2), kill(t + TRADE_MS + 1_000, 1, 8)]))

    assert on_time[2].deaths[0].traded is True
    assert late[2].deaths[0].traded is False
    assert late[2].untraded == 1


def test_a_plate_counts_as_something_back():
    t = 8 * 60_000
    events = [kill(t, 7, 2), [t + 20_000, "plate", BLUE, 3, 0, [], 0, 0, 0]]
    assert review_game(extract(events))[2].deaths[0].traded is True


def test_the_killers_own_later_kill_is_not_a_trade_for_the_victim():
    """Only the dying player's team getting something counts."""
    t = 8 * 60_000
    events = [kill(t, 7, 2), kill(t + 10_000, 8, 3)]
    assert review_game(extract(events))[2].deaths[0].traded is False


# -------------------------------------------------------------- takedowns


def test_a_takedown_converts_when_the_team_takes_an_objective_inside_a_minute():
    t = 20 * 60_000
    events = [
        kill(t, 1, 6, assists=[2, 2, 3]),
        [t + 45_000, "dragon", BLUE, 2, 0, [3], 0, 0, 0],
        kill(t + 5 * 60_000, 1, 7),
    ]
    reviews = review_game(extract(events))

    first, later = reviews[1].takedowns
    assert first.converted and first.killed
    assert not later.converted, "no objective followed the second kill"
    # The killer and each assister once, however often Riot lists them.
    assert [t.ms for t in reviews[2].takedowns] == [t]
    assert reviews[2].takedowns[0].killed is False
    assert reviews[1].converted == 1


def test_an_execution_credits_no_taker_but_is_still_a_death():
    reviews = review_game(extract([kill(6 * 60_000, 0, 4)]))
    assert len(reviews[4].deaths) == 1
    assert all(not r.takedowns for r in reviews.values())


# ----------------------------------------------------------------- contests


def test_an_objective_with_both_teams_on_it_is_a_contest_for_everyone_there():
    t = 25 * 60_000
    contested = [t, "baron", RED, 7, 0, [8, 2, 9], 0, 0, 0]
    clean = [t + 90_000, "dragon", BLUE, 1, 0, [2], 0, 0, 0]
    reviews = review_game(extract([contested, clean]))

    assert (reviews[7].contests, reviews[7].contests_won) == (1, 1)
    assert (reviews[2].contests, reviews[2].contests_won) == (1, 0)
    # The four on the Baron, and nobody from the dragon only blue touched.
    assert sum(r.contests for r in reviews.values()) == 4
    assert 1 not in reviews


# ------------------------------------------------------------ cost and gain


def test_the_victims_cost_is_the_takers_gain():
    extracted = extract([kill(15 * 60_000, 8, 3, assists=[9])])
    story = evaluate(extracted, model())
    reviews = review_game(extracted, story.effects)

    cost = reviews[3].deaths[0].cost
    assert cost is not None and cost > 0
    assert reviews[8].takedowns[0].gain == pytest.approx(cost)
    assert reviews[9].takedowns[0].gain == pytest.approx(cost)
    assert reviews[3].win_lost == pytest.approx(cost)


def test_without_a_model_the_rules_still_read_and_the_numbers_are_empty():
    reviews = review_game(extract([kill(15 * 60_000, 8, 3)]))
    assert reviews[3].deaths[0].cost is None
    assert reviews[3].win_lost == 0.0


# ------------------------------------------------------------------ profile


def row(puuid: str, match: str, *, deaths: int, untraded: int, lost: float, n: int) -> ParticipantReview:
    return ParticipantReview(
        match_id=f"REV_{match}_{n}", participant_index=1, puuid=puuid, queue_id=QUEUE,
        team_position="MIDDLE", minutes=30.0, deaths=deaths, untraded=untraded,
        win_lost=lost, takedowns=10, converted=4, win_gained=0.2,
        contests=1, contests_won=1, model_version=3,
    )


async def test_the_profile_places_a_player_against_their_role_and_withholds_thin_samples():
    player = "review-profile".ljust(78, "0")
    thin = "review-thin".ljust(78, "0")
    async with SessionLocal() as session:
        # A role spread of 220 games, from careful to reckless.
        for n in range(220):
            session.add(row(f"crowd-{n}".ljust(78, "0"), "crowd", deaths=5,
                            untraded=n % 6, lost=0.02 * (n % 10), n=n))
        # A careful player: one untraded death in five, little lost.
        for n in range(MIN_PROFILE_GAMES):
            session.add(row(player, "careful", deaths=5, untraded=1, lost=0.02, n=n))
        for n in range(MIN_PROFILE_GAMES - 1):
            session.add(row(thin, "thin", deaths=5, untraded=1, lost=0.02, n=n))
        await session.commit()
        await rebuild_review_distributions(session)

        (careful,) = await review_profile(session, player, queue_id=QUEUE)
        (withheld,) = await review_profile(session, thin, queue_id=QUEUE)

    by_metric = {m.metric: m for m in careful.metrics}
    assert careful.withheld is None and careful.games == MIN_PROFILE_GAMES
    assert by_metric[UNTRADED].value == pytest.approx(0.2)
    # Lower is better for untraded deaths, so a careful player beats most.
    assert by_metric[UNTRADED].better_than > 0.5
    assert by_metric[LOST].better_than > 0.5
    assert set(by_metric) == {UNTRADED, LOST, CONVERTED, GAINED}
    assert (careful.contests, careful.contests_won) == (MIN_PROFILE_GAMES, MIN_PROFILE_GAMES)

    assert withheld.metrics == []
    assert str(MIN_PROFILE_GAMES) in withheld.withheld
