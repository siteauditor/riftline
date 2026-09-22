"""The win-chance model: fitting, grading, the publish gate, and one game's story.

The model's pure parts (state replay, the fit, the grading, a game's effects
and moments) run here against hand-built games, with no database and no
network. What it predicts on real games is measured by `scripts.ingest
winmodel`, not asserted here: a test that pinned an accuracy would pin a
corpus.
"""

from __future__ import annotations

import random

import numpy as np

from app.services.timelines import BLUE, RED
from app.services.winchance import (
    FEATURES,
    MIN_SKILL,
    MIN_TRAIN_GAMES,
    TrainingGame,
    WinModel,
    cross_validate,
    describe,
    design,
    evaluate,
    fit,
    frame_rows,
    gate,
    moments,
)

GOLD = FEATURES.index("gold")
BARON = FEATURES.index("baron")


def game(minutes: int, gold_lead_per_minute: float, events: list | None = None) -> dict:
    """An extract with even levels and CS, and blue's gold lead growing steadily."""
    tf = []
    for m in range(minutes + 1):
        lead = gold_lead_per_minute * m
        tf.append([m * 60_000, 2500 * m + lead, 2500 * m, 5 * m, 5 * m, 30 * m, 30 * m])
    return {"v": 2, "tf": tf, "ev": events or []}


def synthetic(count: int, seed: int = 7) -> list[TrainingGame]:
    """Games where the side ahead on gold usually wins, as in the real thing."""
    rng = random.Random(seed)
    games = []
    for i in range(count):
        slope = rng.gauss(0, 150)
        # Ahead on gold wins four times in five; a model should find that.
        blue_won = (slope > 0) == (rng.random() < 0.8)
        extracted = game(25, slope)
        games.append(TrainingGame(f"SYN_{seed}_{i}", "C1.00", blue_won, frame_rows(extracted)))
    return games


def model_from(coef: dict[str, float] | None = None) -> WinModel:
    """A hand-set model: weights at both ends of the clock, nothing standardised."""
    width = 2 + 2 * len(FEATURES)
    w = np.zeros(width)
    for name, value in (coef or {}).items():
        i = FEATURES.index(name)
        w[2 + i] = value
        w[2 + len(FEATURES) + i] = value
    from app.services.winchance import Fitted

    fitted = Fitted(w, np.zeros(width), np.ones(width))
    return WinModel(version=1, published=True, withheld=None, fitted=fitted, payload={})


# ---------------------------------------------------------------- fitting


def test_a_gold_lead_that_wins_games_is_found_and_graded_on_held_out_games():
    games = synthetic(400)
    cv = cross_validate(games)

    assert cv["overall"]["skill"] > MIN_SKILL
    assert cv["overall"]["brier"] < cv["overall"]["baseline_brier"]
    # Every row is predicted exactly once, by a model that never saw its game.
    assert cv["overall"]["rows"] == sum(len(g.rows) for g in games)

    x = np.vstack([design(np.asarray([m for m, _ in g.rows]), np.asarray([f for _, f in g.rows])) for g in games])
    y = np.concatenate([np.full(len(g.rows), 1.0 if g.blue_won else 0.0) for g in games])
    fitted = fit(x, y)
    # Here a lead is worth less as the game goes on, so the weight at minute
    # 40 may rest at zero; it may not go below it.
    assert fitted.coef[2 + GOLD] > 0
    assert fitted.coef[2 + len(FEATURES) + GOLD] >= 0


def test_a_game_never_sits_on_both_sides_of_a_fold():
    a = TrainingGame("EUW1_1", None, True, [(1.0, [0.0] * len(FEATURES))])
    b = TrainingGame("EUW1_1", None, False, [(2.0, [0.0] * len(FEATURES))])
    assert a.fold == b.fold, "the fold is a function of the match alone"


def test_no_feature_is_allowed_to_count_against_the_team_holding_it():
    """Fitted freely on 1,678 games, a tower at 10 minutes read -2.9 points."""
    rng = np.random.default_rng(3)
    n = 4000
    minutes = rng.uniform(1, 35, n)
    features = np.zeros((n, len(FEATURES)))
    features[:, GOLD] = rng.normal(0, 3, n)
    # A feature that, holding gold equal, goes with losing.
    features[:, FEATURES.index("towers")] = rng.integers(-3, 4, n)
    logit = 0.6 * features[:, GOLD] - 0.5 * features[:, FEATURES.index("towers")]
    y = (rng.random(n) < 1 / (1 + np.exp(-logit))).astype(float)

    fitted = fit(design(minutes, features), y)
    feature_weights = fitted.coef[2:]
    assert (feature_weights >= 0).all()
    assert fitted.coef[2 + GOLD] > 0


# ------------------------------------------------------------------ the gate


def test_the_gate_withholds_a_model_that_has_not_earned_the_page():
    good = {"overall": {"skill": 0.28}, "ece": 0.01}
    assert gate(MIN_TRAIN_GAMES, good) is None
    assert "needs" in gate(MIN_TRAIN_GAMES - 1, good)
    assert "skill" in gate(MIN_TRAIN_GAMES, {"overall": {"skill": 0.05}, "ece": 0.01})
    assert "calibration" in gate(MIN_TRAIN_GAMES, {"overall": {"skill": 0.28}, "ece": 0.09})


# ----------------------------------------------------------------- one game


def test_baron_raises_the_taking_teams_chance():
    extracted = game(30, 0, [[25 * 60_000 + 30_000, "baron", RED, 7, 0, [8, 9], 0, 0, 0]])
    story = evaluate(extracted, model_from({"baron": 1.0}))

    (effect,) = story.effects
    assert effect.gain(RED) > 0
    assert effect.gain(BLUE) == -effect.gain(RED)
    # The curve steps at the Baron, not at the next minute.
    assert any(ms == 25 * 60_000 + 30_000 and not frame for ms, _, frame in story.curve)


def test_a_kill_carries_its_bounty_into_its_effect():
    kill = [10 * 60_000, "kill", BLUE, 3, 8, [], 0, 0, 700]
    story = evaluate(game(20, 0, [kill]), model_from({"gold": 1.0}))
    assert story.effects[0].gain(BLUE) > 0, "700 gold moved to blue with the kill"


def test_events_fourteen_seconds_apart_chain_and_sixteen_do_not():
    t = 12 * 60_000
    events = [
        [t, "kill", BLUE, 1, 6, [], 0, 0, 300],
        [t + 14_000, "kill", BLUE, 2, 7, [], 0, 0, 300],
        [t + 30_000, "kill", RED, 8, 3, [], 0, 0, 300],
    ]
    story = evaluate(game(20, 0, events), model_from({"gold": 1.0, "kills": 0.2}))
    assert [len(s.effects) for s in story.sequences] == [2, 1]


def test_the_top_moments_come_biggest_first_and_say_what_happened():
    t = 20 * 60_000
    events = [
        [t, "kill", RED, 8, 3, [], 0, 0, 300],
        [t + 5_000, "kill", RED, 9, 4, [], 0, 0, 300],
        [t + 8_000, "kill", BLUE, 1, 6, [], 0, 0, 300],
        [t + 10_000, "kill", RED, 7, 5, [], 0, 0, 300],
        [t + 20_000, "baron", RED, 7, 0, [], 0, 0, 0],
        [30 * 60_000, "kill", BLUE, 2, 9, [], 0, 0, 300],
    ]
    story = evaluate(game(35, 0, events), model_from({"gold": 0.5, "kills": 0.3, "baron": 1.5}))
    found = moments(story.sequences)

    assert [abs(m.swing) for m in found] == sorted((abs(m.swing) for m in found), reverse=True)
    assert found[0].text == "Red won a fight 3 for 1 and took Baron"
    assert found[0].swing < 0, "blue's chance fell"


def test_a_moment_describes_itself_from_the_side_that_gained():
    assert describe(-0.2, {BLUE: 1, RED: 3}, {BLUE: [], RED: ["baron"]}) == (
        "Red won a fight 3 for 1 and took Baron"
    )
    assert describe(0.1, {BLUE: 0, RED: 0}, {BLUE: ["tower", "tower", "inhib"], RED: []}) == (
        "Blue took 2 towers and an inhibitor"
    )
    assert describe(0.05, {BLUE: 1, RED: 1}, {BLUE: [], RED: []}) == "Blue traded 1 for 1"


def test_an_effect_is_left_out_where_the_games_never_had_the_feature():
    """The table once read an Elder buff at 10 minutes, which cannot happen."""
    from app.services.winchance import effects_table

    games = synthetic(60)
    x = np.vstack([design(np.asarray([m for m, _ in g.rows]), np.asarray([f for _, f in g.rows])) for g in games])
    y = np.concatenate([np.full(len(g.rows), 1.0 if g.blue_won else 0.0) for g in games])
    table = {e["feature"]: e["points"] for e in effects_table(fit(x, y), games)}

    assert table["elder"] == {"10": None, "20": None, "30": None}
    assert table["gold"]["10"] is not None
