"""Lane labels: the cut points, the floor, the rebuild, and the match row."""

from __future__ import annotations

import respx
from sqlalchemy import delete, select

from app.db.base import SessionLocal
from app.db.models import RoleMetricStat
from app.services.lanes import (
    EVEN,
    LOST,
    LOST_BIG,
    METRIC,
    WON,
    WON_BIG,
    label,
    lane_labeler,
    rebuild_lane_distributions,
)
from app.services.scores import MIN_GAMES_FOR_SCORE, quantile_breakpoints
from tests.test_timeline_storage import (
    mock_timeline,
    seed_match,
    service,
    stored_matches,
    timeline_payload,
)

# Distances from even of 0.000 to 0.100: the 30th percentile sits at 0.03 and
# the 90th at 0.09.
SPREAD = quantile_breakpoints([i / 1000 for i in range(101)])


def test_the_closest_thirty_percent_are_even_and_the_widest_ten_are_big():
    assert label(0.51, SPREAD) == EVEN
    assert label(0.55, SPREAD) == WON
    assert label(0.45, SPREAD) == LOST
    assert label(0.595, SPREAD) == WON_BIG
    assert label(0.405, SPREAD) == LOST_BIG


def test_no_label_without_a_lane_or_a_spread():
    assert label(None, SPREAD) is None
    assert label(0.6, None) is None


async def test_a_role_below_the_floor_gets_no_label():
    async with SessionLocal() as session:
        await session.execute(delete(RoleMetricStat).where(RoleMetricStat.queue_id == 99421))
        for position, games in (("TOP", MIN_GAMES_FOR_SCORE - 1), ("MIDDLE", MIN_GAMES_FOR_SCORE)):
            session.add(RoleMetricStat(
                queue_id=99421, team_position=position, metric=METRIC,
                breakpoints=SPREAD, games=games,
            ))
        await session.commit()
        labeler = await lane_labeler(session)

    assert labeler(99421, "TOP", 0.6) is None
    assert labeler(99421, "MIDDLE", 0.6) == WON_BIG


@respx.mock
async def test_the_match_row_carries_the_label_once_the_role_has_a_spread(client):
    match_id = "EUW1_6000000061"
    await seed_match(client, match_id)
    mock_timeline(timeline_payload())
    async with SessionLocal() as session:
        await service(session).ensure_timelines(await stored_matches(session, match_id))
        await session.execute(
            delete(RoleMetricStat).where(
                RoleMetricStat.metric == METRIC, RoleMetricStat.queue_id == 420,
                RoleMetricStat.team_position == "MIDDLE",
            )
        )
        session.add(RoleMetricStat(
            queue_id=420, team_position="MIDDLE", metric=METRIC,
            breakpoints=SPREAD, games=MIN_GAMES_FOR_SCORE,
        ))
        await session.commit()

    response = await client.get("/api/summoner/euw1/Caps/EUW/matches?count=1")
    row = response.json()["matches"][0]
    # Blue mid led 6,000 to 4,000 gold at 14: a share of 0.594, the widest tenth.
    assert row["laning_score"] > 0.59
    assert row["laning_label"] == WON_BIG

    detail = (await client.get(f"/api/matches/{match_id}")).json()
    blue_mid = next(p for team in detail["teams"] for p in team if p["position"] == "MIDDLE" and p["win"] == row["win"])
    assert blue_mid["laning_label"] == WON_BIG


async def test_the_rebuild_measures_every_role_with_lanes_and_leaves_other_metrics():
    async with SessionLocal() as session:
        session.add(RoleMetricStat(
            queue_id=99422, team_position="TOP", metric="review_untraded",
            breakpoints=SPREAD, games=5,
        ))
        await session.commit()
        written = await rebuild_lane_distributions(session)
        rows = (
            await session.execute(select(RoleMetricStat).where(RoleMetricStat.metric == METRIC))
        ).scalars().all()
        other = (
            await session.execute(select(RoleMetricStat).where(RoleMetricStat.queue_id == 99422))
        ).scalars().all()

    assert written == len(rows) >= 1
    assert all(len(r.breakpoints) == 101 for r in rows)
    assert len(other) == 1, "a lane rebuild leaves the review's breakpoints alone"
