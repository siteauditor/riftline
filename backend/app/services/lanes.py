"""Lane labels: won, even, lost, won big, lost big.

The laning score is a share of the lane pair's gold, experience and CS at
minute 14 (0.54 renders "54 : 46"). How far a share has to be from even to mean
anything differs by role: a support's lane moves less than a top laner's.
Measured on our ranked games, the distance from even at the 30th percentile is
0.018 to 0.026 depending on role, and at the 90th 0.077 to 0.106.

So the label is a percentile of that distance within the role, with STRATZ's
split for Dota's lanes: the closest 30% are even, the widest 10% are won or lost
big, the rest won or lost. A role with fewer than 200 measured lanes gets no
label, the same floor as the Riftline score.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Match, MatchParticipant, RoleMetricStat, utcnow
from app.services.aggregate import POSITIONS
from app.services.scores import MIN_GAMES_FOR_SCORE, percentile, quantile_breakpoints

log = logging.getLogger(__name__)

METRIC = "lane_margin"
EVEN_BELOW = 0.30
BIG_FROM = 0.90

WON_BIG, WON, EVEN, LOST, LOST_BIG = "won_big", "won", "even", "lost", "lost_big"
LABELS = {
    WON_BIG: "Won big",
    WON: "Won lane",
    EVEN: "Even lane",
    LOST: "Lost lane",
    LOST_BIG: "Lost big",
}


def label(laning_score: float | None, breakpoints: list[float] | None) -> str | None:
    """The label for one lane, or None when there is nothing to measure against."""
    if laning_score is None or not breakpoints:
        return None
    share = percentile(breakpoints, abs(laning_score - 0.5))
    if share < EVEN_BELOW:
        return EVEN
    ahead = laning_score > 0.5
    if share >= BIG_FROM:
        return WON_BIG if ahead else LOST_BIG
    return WON if ahead else LOST


async def rebuild_lane_distributions(session: AsyncSession) -> int:
    """Per (queue, role) breakpoints of the distance from an even lane."""
    rows = (
        await session.execute(
            select(Match.queue_id, MatchParticipant.team_position, MatchParticipant.laning_score)
            .join(Match, Match.match_id == MatchParticipant.match_id)
            .where(
                Match.is_remake.is_(False),
                MatchParticipant.team_position.in_(POSITIONS),
                MatchParticipant.laning_score.is_not(None),
            )
        )
    ).all()
    samples: dict[tuple[int, str], list[float]] = {}
    for queue_id, position, score in rows:
        samples.setdefault((queue_id, position), []).append(abs(score - 0.5))

    await session.execute(
        RoleMetricStat.__table__.delete().where(RoleMetricStat.metric == METRIC)
    )
    payload = [
        {
            "queue_id": queue_id,
            "team_position": position,
            "metric": METRIC,
            "breakpoints": quantile_breakpoints(values),
            "games": len(values),
            "computed_at": utcnow(),
        }
        for (queue_id, position), values in samples.items()
    ]
    if payload:
        await session.execute(RoleMetricStat.__table__.insert(), payload)
    await session.commit()
    log.info("lane labels: %d role distributions", len(payload))
    return len(payload)


@dataclass(slots=True)
class LaneLabeler:
    """The lane breakpoints, read once per request."""

    breakpoints: dict[tuple[int, str], list[float]]

    def __call__(self, queue_id: int | None, position: str | None, laning_score: float | None) -> str | None:
        if queue_id is None or position is None:
            return None
        return label(laning_score, self.breakpoints.get((queue_id, position)))


async def lane_labeler(session: AsyncSession) -> LaneLabeler:
    rows = (
        await session.execute(select(RoleMetricStat).where(RoleMetricStat.metric == METRIC))
    ).scalars()
    return LaneLabeler({
        (r.queue_id, r.team_position): r.breakpoints
        for r in rows
        if r.games >= MIN_GAMES_FOR_SCORE
    })
