"""The death and kill review.

Every death is traded or not, every takedown converted or not, and each is
weighed by what it did to the team's chance to win.

**Traded**: the dying player's team gains a kill, an epic monster, a tower, an
inhibitor or a plate within a minute after the death. Measured on 600 stored
ranked games, 74.0% of deaths are; the rest are the deaths the team got nothing
back for. It is a rule, not a model, so it needs no model to be right, and it
follows PandaSkill's "worthless death" (a death with no enemy kill or team
objective within a minute), which a 2025 study of 37,388 professional games
found among the measures that best separated players.

**Converted**: the player's team takes an epic monster or a building within a
minute after a takedown the player was part of.

**Cost and gain**: the win-chance model's reading of the event itself: blue's
chance just after minus just before, holding gold where it was except for the
kill's own bounty. The same event is a loss to the victim's team and a gain to
the takers'. Maymin (2020) found kills and deaths weighed this way track team
results far more closely than a plain K/D.

**Contested objective**: an epic monster whose killer and assisters include
both teams. On 400 stored timelines, 359 of 3,339 were.

A player's rates are compared with their role as a percentile per game,
averaged, the way the Riftline score is: a per-game rate against the spread of
per-game rates. Below 10 reviewed games in a role, or a role whose spread rests
on fewer than 200 games, the figure is withheld and the count shown.
"""

from __future__ import annotations

import logging
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import (
    Match,
    MatchTimeline,
    ParticipantReview,
    RoleMetricStat,
    utcnow,
)
from app.services.aggregate import POSITIONS
from app.services.scores import MIN_GAMES_FOR_SCORE, percentile, quantile_breakpoints
from app.services.timelines import (
    ATAKHAN,
    BARON,
    BLUE,
    DRAGON,
    ELDER,
    EPIC_MONSTERS,
    EXTRACT_VERSION,
    GRUBS,
    HERALD,
    INHIBITOR,
    KILL,
    PLATE,
    RED,
    TOWER,
    backfill_extracts,
)
from app.services.winchance import MODEL_QUEUES, Effect, WinModel, current_model, evaluate

log = logging.getLogger(__name__)

TRADE_MS = 60_000
TRADE_KINDS = frozenset({KILL, DRAGON, ELDER, GRUBS, HERALD, BARON, ATAKHAN, TOWER, INHIBITOR, PLATE})
CONVERT_KINDS = frozenset({DRAGON, ELDER, GRUBS, HERALD, BARON, ATAKHAN, TOWER, INHIBITOR})
EPIC = frozenset(EPIC_MONSTERS)

MIN_PROFILE_GAMES = 10
# Win chance lost or gained is summed over a game, so it is put per 30 minutes
# before two games of different lengths are compared.
PER_MINUTES = 30

UNTRADED, LOST, CONVERTED, GAINED = (
    "review_untraded", "review_lost", "review_converted", "review_gained",
)
REVIEW_METRICS = (UNTRADED, LOST, CONVERTED, GAINED)
# For these, a lower rate is the better one, so "better than X%" flips.
LOWER_IS_BETTER = frozenset({UNTRADED, LOST})
METRIC_LABELS = {
    UNTRADED: ("Untraded deaths", "Share of deaths the team got nothing back for within a minute"),
    LOST: ("Win chance lost", "Win chance the deaths took, per 30 minutes"),
    CONVERTED: ("Converted takedowns", "Share of takedowns turned into an objective within a minute"),
    GAINED: ("Win chance gained", "Win chance the takedowns added, per 30 minutes"),
}


# ------------------------------------------------------------------ one game


@dataclass(slots=True)
class Death:
    ms: int
    killer: int
    assisters: int
    x: int
    y: int
    traded: bool
    # Win chance, 0 to 1, the death took from the team. None without a model.
    cost: float | None


@dataclass(slots=True)
class Takedown:
    ms: int
    victim: int
    # True for the kill itself, False for an assist.
    killed: bool
    converted: bool
    gain: float | None


@dataclass(slots=True)
class PlayerReview:
    index: int
    deaths: list[Death] = field(default_factory=list)
    takedowns: list[Takedown] = field(default_factory=list)
    contests: int = 0
    contests_won: int = 0

    @property
    def untraded(self) -> int:
        return sum(1 for d in self.deaths if not d.traded)

    @property
    def converted(self) -> int:
        return sum(1 for t in self.takedowns if t.converted)

    @property
    def win_lost(self) -> float:
        return sum(d.cost or 0.0 for d in self.deaths)

    @property
    def win_gained(self) -> float:
        return sum(t.gain or 0.0 for t in self.takedowns)


def _default_side(participant: int) -> int | None:
    if participant <= 0:
        return None
    return BLUE if participant <= 5 else RED


def review_game(
    extracted: dict,
    effects: Sequence[Effect] | None = None,
    sides: dict[int, int] | None = None,
) -> dict[int, PlayerReview]:
    """Every player's deaths, takedowns and contests in one game.

    ``effects`` come from `winchance.evaluate`; without them trades and
    conversions are still read, and costs and gains are None. ``sides`` maps a
    participant index to its team when the caller knows it, and otherwise
    Riot's numbering (1 to 5 blue) is used.
    """
    ev = extracted.get("ev") or []
    by_index = {e.index: e for e in (effects or [])}

    def side(pid: int) -> int | None:
        return (sides or {}).get(pid) or _default_side(pid)

    reviews: dict[int, PlayerReview] = {}

    def of(pid: int) -> PlayerReview:
        return reviews.setdefault(pid, PlayerReview(pid))

    def followed(team: int, after_ms: int, kinds: frozenset[str], skip: int) -> bool:
        return any(
            j != skip and other[2] == team and other[1] in kinds
            and 0 <= other[0] - after_ms <= TRADE_MS
            for j, other in enumerate(ev)
        )

    for i, event in enumerate(ev):
        ms, kind, team = event[0], event[1], event[2]
        if kind == KILL:
            killer, victim, assists = event[3], event[4], event[5]
            effect = by_index.get(i)
            # The takers' gain is the victim's loss: one number, two sides.
            swing = effect.gain(team) if effect else None
            victim_team = side(victim)
            if victim_team is not None:
                of(victim).deaths.append(Death(
                    ms=ms,
                    killer=killer,
                    assisters=len(assists),
                    x=event[6],
                    y=event[7],
                    traded=followed(victim_team, ms, TRADE_KINDS, i),
                    cost=swing,
                ))
            converted = followed(team, ms, CONVERT_KINDS, i)
            takers = ([killer] if killer and side(killer) == team else []) + [
                a for a in assists if side(a) == team
            ]
            for pid in dict.fromkeys(takers):
                of(pid).takedowns.append(Takedown(
                    ms=ms, victim=victim, killed=pid == killer, converted=converted, gain=swing,
                ))
        elif kind in EPIC:
            present = ([event[3]] if event[3] else []) + list(event[5])
            if {side(pid) for pid in present} >= {BLUE, RED}:
                for pid in dict.fromkeys(present):
                    review = of(pid)
                    review.contests += 1
                    if side(pid) == team:
                        review.contests_won += 1
    return reviews


# ------------------------------------------------------------------- storage


async def store_reviews(
    session: AsyncSession, match: Match, reviews: dict[int, PlayerReview], model_version: int
) -> int:
    """Replace this match's review rows. No commit."""
    await session.execute(delete(ParticipantReview).where(ParticipantReview.match_id == match.match_id))
    minutes = max(1.0, (match.game_duration or 0) / 60)
    stored = 0
    for p in match.participants:
        review = reviews.get(p.participant_index) or PlayerReview(p.participant_index)
        session.add(ParticipantReview(
            match_id=match.match_id,
            participant_index=p.participant_index,
            puuid=p.puuid,
            queue_id=match.queue_id,
            team_position=p.team_position,
            minutes=minutes,
            deaths=len(review.deaths),
            untraded=review.untraded,
            win_lost=round(review.win_lost, 5),
            takedowns=len(review.takedowns),
            converted=review.converted,
            win_gained=round(review.win_gained, 5),
            contests=review.contests,
            contests_won=review.contests_won,
            model_version=model_version,
            computed_at=utcnow(),
        ))
        stored += 1
    return stored


def sides_of(match: Match) -> dict[int, int]:
    return {p.participant_index: p.team_id for p in match.participants}


async def review_match(session: AsyncSession, match: Match, model: WinModel) -> bool:
    """Evaluate and store one match's reviews. No commit. False if it has no
    usable timeline."""
    # The extract only: loading the row would bring its 81 KB raw payload
    # along for every game, about 240 MB a night on 3,000 games.
    extracted = (
        await session.execute(
            select(MatchTimeline.extracted).where(MatchTimeline.match_id == match.match_id)
        )
    ).scalar_one_or_none()
    if not extracted or (extracted.get("v") or 0) < EXTRACT_VERSION:
        return False
    story = evaluate(extracted, model)
    reviews = review_game(extracted, story.effects, sides_of(match))
    await store_reviews(session, match, reviews, model.version)
    return True


@dataclass(slots=True)
class ReviewStats:
    matches: int = 0
    skipped: int = 0
    withheld: str | None = None


async def rebuild_reviews(session: AsyncSession, *, batch: int = 50) -> ReviewStats:
    """Review every stored game the current model has not. Storage only."""
    stats = ReviewStats()
    model = await current_model(session)
    if model is None or not model.published:
        stats.withheld = (
            "no win-chance model yet" if model is None
            else f"the win-chance model is withheld: {model.withheld}"
        )
        return stats

    # Old extracts first: a review reads keys only version 2 has.
    await backfill_extracts(session)

    current = set(
        (
            await session.execute(
                select(ParticipantReview.match_id)
                .where(ParticipantReview.model_version == model.version)
                .distinct()
            )
        ).scalars()
    )
    candidates = [
        match_id
        for match_id in (
            await session.execute(
                select(MatchTimeline.match_id)
                .join(Match, Match.match_id == MatchTimeline.match_id)
                .where(Match.queue_id.in_(MODEL_QUEUES), Match.is_remake.is_(False))
            )
        ).scalars()
        if match_id not in current
    ]
    for start in range(0, len(candidates), batch):
        ids = candidates[start:start + batch]
        matches = (
            await session.execute(
                select(Match).where(Match.match_id.in_(ids)).options(selectinload(Match.participants))
            )
        ).scalars().all()
        for match in matches:
            if await review_match(session, match, model):
                stats.matches += 1
            else:
                stats.skipped += 1
        await session.commit()
        log.info("reviews: %d games so far", stats.matches)
    await rebuild_review_distributions(session)
    return stats


# --------------------------------------------------------------- percentiles


def game_rates(row: ParticipantReview) -> dict[str, float]:
    """The four per-game rates, each only where it means something."""
    rates: dict[str, float] = {}
    minutes = max(1.0, row.minutes or 0.0)
    if row.deaths:
        rates[UNTRADED] = row.untraded / row.deaths
    rates[LOST] = row.win_lost / minutes * PER_MINUTES
    if row.takedowns:
        rates[CONVERTED] = row.converted / row.takedowns
    rates[GAINED] = row.win_gained / minutes * PER_MINUTES
    return rates


async def rebuild_review_distributions(session: AsyncSession) -> int:
    """Per (queue, role) breakpoints of the four per-game rates."""
    rows = (
        await session.execute(
            select(ParticipantReview).where(ParticipantReview.team_position.in_(POSITIONS))
        )
    ).scalars().all()
    samples: dict[tuple[int, str, str], list[float]] = {}
    for row in rows:
        for metric, value in game_rates(row).items():
            samples.setdefault((row.queue_id, row.team_position, metric), []).append(value)

    await session.execute(
        RoleMetricStat.__table__.delete().where(RoleMetricStat.metric.in_(REVIEW_METRICS))
    )
    payload = [
        {
            "queue_id": queue_id,
            "team_position": position,
            "metric": metric,
            "breakpoints": quantile_breakpoints(values),
            "games": len(values),
            "computed_at": utcnow(),
        }
        for (queue_id, position, metric), values in samples.items()
    ]
    if payload:
        await session.execute(RoleMetricStat.__table__.insert(), payload)
    await session.commit()
    return len(payload)


@dataclass(slots=True)
class MetricProfile:
    metric: str
    # The player's pooled rate over their games, in the metric's own unit.
    value: float
    # Share of the role this player's games did better than, averaged per game.
    # None when the role's spread rests on too few games.
    better_than: float | None
    games: int


@dataclass(slots=True)
class RoleReviewProfile:
    position: str
    games: int
    withheld: str | None
    metrics: list[MetricProfile]
    contests: int
    contests_won: int


async def review_profile(
    session: AsyncSession,
    puuid: str,
    queue_id: int | None = None,
    *,
    queues: Collection[int] | None = None,
    match_ids: Collection[str] | None = None,
) -> list[RoleReviewProfile]:
    """A player's review rates per role, against the role, from stored games.

    ``match_ids`` limits it to one window of games, so a profile's review
    covers the games its other panels do.
    """
    stmt = select(ParticipantReview).where(
        ParticipantReview.puuid == puuid, ParticipantReview.team_position.in_(POSITIONS)
    )
    if queue_id is not None:
        stmt = stmt.where(ParticipantReview.queue_id == queue_id)
    if queues is not None:
        stmt = stmt.where(ParticipantReview.queue_id.in_(list(queues)))
    if match_ids is not None:
        stmt = stmt.where(ParticipantReview.match_id.in_(list(match_ids)))
    rows = (await session.execute(stmt)).scalars().all()
    if not rows:
        return []
    dists = {
        (d.queue_id, d.team_position, d.metric): d
        for d in (
            await session.execute(
                select(RoleMetricStat).where(RoleMetricStat.metric.in_(REVIEW_METRICS))
            )
        ).scalars()
    }

    by_role: dict[str, list[ParticipantReview]] = {}
    for row in rows:
        by_role.setdefault(row.team_position, []).append(row)

    out = []
    for position, games in sorted(by_role.items(), key=lambda kv: -len(kv[1])):
        contests = sum(g.contests for g in games)
        contests_won = sum(g.contests_won for g in games)
        if len(games) < MIN_PROFILE_GAMES:
            out.append(RoleReviewProfile(
                position, len(games),
                f"{len(games)} reviewed games in this role; the review needs {MIN_PROFILE_GAMES}",
                [], contests, contests_won,
            ))
            continue
        deaths = sum(g.deaths for g in games)
        takedowns = sum(g.takedowns for g in games)
        minutes = sum(max(1.0, g.minutes or 0.0) for g in games)
        pooled = {
            UNTRADED: (sum(g.untraded for g in games) / deaths) if deaths else 0.0,
            LOST: sum(g.win_lost for g in games) / minutes * PER_MINUTES,
            CONVERTED: (sum(g.converted for g in games) / takedowns) if takedowns else 0.0,
            GAINED: sum(g.win_gained for g in games) / minutes * PER_MINUTES,
        }
        metrics = []
        for metric in REVIEW_METRICS:
            placed = []
            for g in games:
                value = game_rates(g).get(metric)
                dist = dists.get((g.queue_id, position, metric))
                if value is None or dist is None or dist.games < MIN_GAMES_FOR_SCORE:
                    continue
                share = percentile(dist.breakpoints, value)
                placed.append(1 - share if metric in LOWER_IS_BETTER else share)
            metrics.append(MetricProfile(
                metric=metric,
                value=round(pooled[metric], 4),
                better_than=round(sum(placed) / len(placed), 4) if len(placed) >= MIN_PROFILE_GAMES else None,
                games=len(placed),
            ))
        out.append(RoleReviewProfile(position, len(games), None, metrics, contests, contests_won))
    return out


def described(review: PlayerReview) -> dict[str, Any]:
    """The summary line a page shows above one player's lists."""
    return {
        "deaths": len(review.deaths),
        "untraded": review.untraded,
        "win_lost": round(review.win_lost, 4),
        "takedowns": len(review.takedowns),
        "converted": review.converted,
        "win_gained": round(review.win_gained, 4),
        "contests": review.contests,
        "contests_won": review.contests_won,
    }
