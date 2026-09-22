"""The score audit: how well the Riftline score tracks wins, in public.

OP.GG's article on its score gives no inputs, weights or comparison group and
calls the score beta; Mobalytics lists sub-metrics but no weights or ranges. The
Riftline score publishes its weights already. This goes one step further and
publishes how well they work, per role, on our own ranked games:

* the mean score of winners and of losers, and how often the lobby's top scorer
  was on the winning team;
* the AUC: the chance a random winner outscored a random loser in the same
  role, where 0.5 is a coin and 1.0 is perfect;
* win rate by score decile;
* each component's own AUC;
* a logistic fit of winning on the component percentiles, set beside the
  hand-set weights, and how the components correlate.

The caveat is printed with it and belongs here too: a fit to wins partly
measures who won. Winners take more objectives and die less because they are
winning, so the fitted weights reward being on the winning team, which is why
the site keeps hand-set weights and shows this as a check, not a replacement.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Match, MatchParticipant, ModelReport, utcnow
from app.services.aggregate import POSITIONS
from app.services.scores import COMPONENTS, WEIGHTS, WEIGHTS_VERSION
from app.services.winchance import fit

log = logging.getLogger(__name__)

KIND = "score_audit"
AUDIT_QUEUE = 420
DECILES = 10


def auc(scores: np.ndarray, won: np.ndarray) -> float | None:
    """The chance a random winner scored above a random loser, ties halved."""
    positives = int(won.sum())
    negatives = len(won) - positives
    if not positives or not negatives:
        return None
    order = np.argsort(scores, kind="mergesort")
    ordered = scores[order]
    ranks = np.empty(len(scores))
    i = 0
    while i < len(ordered):
        j = i
        while j + 1 < len(ordered) and ordered[j + 1] == ordered[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2 + 1
        i = j + 1
    return float((ranks[won == 1].sum() - positives * (positives + 1) / 2) / (positives * negatives))


def deciles(scores: np.ndarray, won: np.ndarray) -> list[dict[str, float]]:
    order = np.argsort(scores, kind="mergesort")
    out = []
    for chunk in np.array_split(order, DECILES):
        if not len(chunk):
            continue
        out.append({
            "low": round(float(scores[chunk].min()), 2),
            "high": round(float(scores[chunk].max()), 2),
            "win_rate": round(float(won[chunk].mean()), 4),
            "games": int(len(chunk)),
        })
    return out


def fitted_weights(percentiles: np.ndarray, won: np.ndarray) -> dict[str, Any]:
    """Win on the component percentiles, and those weights put on the site's scale.

    Unconstrained: a component that goes with losing once the others are held
    equal is a finding, and hiding it would be the opposite of an audit.
    """
    x = np.column_stack([np.ones(len(won)), percentiles])
    # `fit` holds columns from index 2 up; with the constraint lifted, none.
    model = fit(x, won, non_negative=False)
    raw = model.coef[1:] / model.scale[1:]
    positive = np.clip(raw, 0, None)
    total = float(positive.sum())
    return {
        # Log-odds for 10 percentile points of each component, the others equal.
        "per_ten_points": {c: round(float(r) / 10, 4) for c, r in zip(COMPONENTS, raw, strict=True)},
        # The positive part, scaled to sum to 1 like the hand-set weights.
        "normalised": {
            c: round(float(p) / total, 4) if total else 0.0
            for c, p in zip(COMPONENTS, positive, strict=True)
        },
    }


async def score_audit(session: AsyncSession, queue_id: int = AUDIT_QUEUE) -> dict[str, Any]:
    rows = (
        await session.execute(
            select(
                MatchParticipant.match_id,
                MatchParticipant.team_position,
                MatchParticipant.win,
                MatchParticipant.performance_score,
                MatchParticipant.performance_rank,
                MatchParticipant.performance_detail,
            )
            .join(Match, Match.match_id == MatchParticipant.match_id)
            .where(
                Match.queue_id == queue_id,
                Match.is_remake.is_(False),
                MatchParticipant.performance_score.is_not(None),
                MatchParticipant.team_position.in_(POSITIONS),
            )
        )
    ).all()
    # Only scores from the current weights: an audit of a mixture describes
    # neither version.
    rows = [
        r for r in rows
        if (r.performance_detail or {}).get("weights") == WEIGHTS_VERSION
        and all(c in ((r.performance_detail or {}).get("components") or {}) for c in COMPONENTS)
    ]
    matches = {r.match_id for r in rows}
    top = [r for r in rows if r.performance_rank == 1]
    bottom = [r for r in rows if r.performance_rank == 10]
    won_all = np.asarray([1.0 if r.win else 0.0 for r in rows])
    scores_all = np.asarray([r.performance_score for r in rows], dtype=float)

    report: dict[str, Any] = {
        "weights_version": WEIGHTS_VERSION,
        "queue_id": queue_id,
        "games": len(matches),
        "players": len(rows),
        "overall": {
            "winners_mean": round(float(scores_all[won_all == 1].mean()), 2) if won_all.any() else None,
            "losers_mean": round(float(scores_all[won_all == 0].mean()), 2) if (won_all == 0).any() else None,
            "auc": _round(auc(scores_all, won_all)) if len(rows) else None,
            "top_on_winning_team": round(sum(1 for r in top if r.win) / len(top), 4) if top else None,
            "bottom_on_losing_team": round(sum(1 for r in bottom if not r.win) / len(bottom), 4) if bottom else None,
        },
        "roles": [],
    }
    for position in POSITIONS:
        mine = [r for r in rows if r.team_position == position]
        if len(mine) < 50:
            continue
        won = np.asarray([1.0 if r.win else 0.0 for r in mine])
        scores = np.asarray([r.performance_score for r in mine], dtype=float)
        pcts = np.asarray(
            [[r.performance_detail["components"][c] for c in COMPONENTS] for r in mine], dtype=float
        )
        correlation = np.corrcoef(pcts, rowvar=False)
        report["roles"].append({
            "position": position,
            "players": len(mine),
            "winners_mean": round(float(scores[won == 1].mean()), 2),
            "losers_mean": round(float(scores[won == 0].mean()), 2),
            "auc": _round(auc(scores, won)),
            "deciles": deciles(scores, won),
            "components": {c: _round(auc(pcts[:, i], won)) for i, c in enumerate(COMPONENTS)},
            "set_weights": dict(WEIGHTS[position]),
            "fitted": fitted_weights(pcts, won),
            "correlation": {
                a: {b: round(float(correlation[i, j]), 3) for j, b in enumerate(COMPONENTS)}
                for i, a in enumerate(COMPONENTS)
            },
        })
    return report


def _round(value: float | None) -> float | None:
    return round(value, 4) if value is not None else None


async def store_audit(session: AsyncSession) -> ModelReport:
    """Run the audit and keep it as the current `score_audit` report."""
    report = await score_audit(session)
    row = (
        await session.execute(select(ModelReport).where(ModelReport.kind == KIND))
    ).scalar_one_or_none()
    if row is None:
        row = ModelReport(kind=KIND, version=WEIGHTS_VERSION, payload=report, trained_games=report["games"])
        session.add(row)
    else:
        row.version = WEIGHTS_VERSION
        row.payload = report
        row.trained_games = report["games"]
    row.computed_at = utcnow()
    await session.commit()
    log.info("score audit: %d games under weights v%d", report["games"], WEIGHTS_VERSION)
    return row
