"""The measurements behind the priors the pages use: pure arithmetic, no corpus."""

from __future__ import annotations

import random

import pytest

from app.services.draft_priors import rate_spread, score_prior


def test_rates_that_differ_only_by_chance_have_no_spread():
    """A thousand rows all truly at 50%: their spread is binomial noise, and
    no prior strength follows from it."""
    rng = random.Random(7)
    rows = [(sum(rng.random() < 0.5 for _ in range(100)), 100) for _ in range(1000)]

    spread, strength = rate_spread(rows)

    assert spread is None or spread < 0.01
    assert strength is None or strength > 2500


def test_a_real_spread_is_recovered_with_its_prior():
    """True rates spread by 3 points around 50%, a hundred games each: the
    measured spread lands near 3 points, so a record needs about 280 games."""
    rng = random.Random(11)
    rows = []
    for _ in range(3000):
        rate = min(0.99, max(0.01, rng.gauss(0.5, 0.03)))
        rows.append((sum(rng.random() < rate for _ in range(100)), 100))

    spread, strength = rate_spread(rows)

    assert spread == pytest.approx(0.03, abs=0.004)
    assert strength == pytest.approx(0.25 / 0.03**2, rel=0.3)


def test_player_scores_give_the_strength_the_board_uses():
    """Games vary by 1.66 around a player's average and players by 0.55, the
    local corpus's figures: the board's prior of nine games comes back."""
    rng = random.Random(3)
    groups = []
    for _ in range(2000):
        mean = rng.gauss(5.5, 0.55)
        groups.append([rng.gauss(mean, 1.66) for _ in range(rng.randint(5, 20))])

    within, between, strength = score_prior(groups)

    assert within == pytest.approx(1.66, abs=0.05)
    assert between == pytest.approx(0.55, abs=0.06)
    assert strength == pytest.approx(9.1, abs=2.0)


def test_too_few_players_measure_nothing():
    assert score_prior([[5.0, 6.0]]) == (None, None, None)
    assert rate_spread([]) == (None, None)
