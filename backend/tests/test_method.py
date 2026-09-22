"""The score audit's measures, and the method page's endpoint."""

from __future__ import annotations

import numpy as np
import pytest

from app.db.base import SessionLocal
from app.services.audit import auc, deciles, fitted_weights, store_audit
from app.services.scores import COMPONENTS, WEIGHTS_VERSION


def test_auc_is_the_chance_a_winner_outscored_a_loser():
    won = np.array([0.0, 0.0, 1.0, 1.0])
    assert auc(np.array([1.0, 2.0, 3.0, 4.0]), won) == 1.0
    assert auc(np.array([4.0, 3.0, 2.0, 1.0]), won) == 0.0
    # Ties count half: a score that cannot tell anyone apart is a coin.
    assert auc(np.array([5.0, 5.0, 5.0, 5.0]), won) == 0.5
    assert auc(np.array([1.0, 2.0]), np.array([1.0, 1.0])) is None


def test_win_rate_rises_through_the_deciles_when_the_score_tracks_wins():
    rng = np.random.default_rng(11)
    scores = rng.uniform(0, 10, 5000)
    won = (rng.random(5000) < 1 / (1 + np.exp(-(scores - 5)))).astype(float)
    bands = deciles(scores, won)

    assert len(bands) == 10 and sum(b["games"] for b in bands) == 5000
    assert bands[0]["win_rate"] < 0.2 < 0.8 < bands[-1]["win_rate"]


def test_fitted_weights_keep_their_sign_and_sum_to_one_where_positive():
    rng = np.random.default_rng(5)
    n = 6000
    pcts = rng.uniform(0, 1, (n, len(COMPONENTS)))
    logit = 3 * (pcts[:, 0] - 0.5) - 2 * (pcts[:, 1] - 0.5)
    won = (rng.random(n) < 1 / (1 + np.exp(-logit))).astype(float)
    fitted = fitted_weights(pcts, won)

    first, second = COMPONENTS[0], COMPONENTS[1]
    assert fitted["per_ten_points"][first] > 0
    # Unconstrained: the audit reports a weight that goes with losing.
    assert fitted["per_ten_points"][second] < 0
    assert fitted["normalised"][second] == 0
    assert sum(fitted["normalised"].values()) == pytest.approx(1.0, abs=1e-3)


async def test_the_method_page_publishes_the_weights_the_audit_and_the_rules(client):
    async with SessionLocal() as session:
        await store_audit(session)

    body = (await client.get("/api/method")).json()
    assert body["score"]["version"] == WEIGHTS_VERSION
    assert [c["id"] for c in body["score"]["components"]] == list(COMPONENTS)
    assert body["score"]["audit"]["weights_version"] == WEIGHTS_VERSION
    assert body["review"]["trade_seconds"] == 60
    assert "plate" in body["review"]["trade_kinds"]
    assert body["lanes"]["even_below"] == 0.3
