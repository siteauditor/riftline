"""What a player's stored games say about them: per role, and per champion.

Everything here is arithmetic over rows already in storage, so it costs no Riot
call. Two rules run through it, both from the rest of the app:

* **Every average carries its own count.** A champion played nine times with two
  scored games reports an average score over two, and says two. Folding the
  count away would make the figure look nine games deep.
* **Thin samples are withheld, not guessed.** A role's breakdown needs
  ``MIN_SCORED_FOR_PROFILE`` scored games before it is offered at all.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Match, MatchParticipant
from app.services.aggregate import POSITIONS
from app.services.matches import PlayedRow
from app.services.queues import SCOPE_QUEUES
from app.services.scores import COMPONENT_LABELS, COMPONENTS

# Below this many scored games in a role, an average percentile moves by ten
# points on one game, which describes the last game rather than the player.
MIN_SCORED_FOR_PROFILE = 10


@dataclass(frozen=True, slots=True)
class ComponentAverage:
    id: str
    label: str
    measures: str
    # Mean of this player's per-game percentiles, 0 to 1.
    avg_percentile: float


@dataclass(slots=True)
class RoleScoreProfile:
    position: str
    scored_games: int
    enough: bool
    avg_score: float
    avg_placement: float
    mvp: int
    ace: int
    # Highest first.
    components: list[ComponentAverage] = field(default_factory=list)
    # The smallest corpus any of these percentiles was measured against.
    sample: int | None = None


def score_profile(rows: Iterable[PlayedRow]) -> list[RoleScoreProfile]:
    """Per role: the average score, placement, badges and the seven components."""
    by_role: dict[str, list[PlayedRow]] = {}
    for row in rows:
        detail = row.performance_detail or {}
        if (
            row.performance_score is None
            or row.team_position not in POSITIONS
            or not detail.get("components")
        ):
            continue
        by_role.setdefault(row.team_position, []).append(row)

    out = []
    for position, games in by_role.items():
        n = len(games)
        sums: Counter[str] = Counter()
        badges: Counter[str] = Counter()
        samples = []
        for row in games:
            detail = row.performance_detail or {}
            for component, value in (detail.get("components") or {}).items():
                sums[component] += value
            badges.update(detail.get("badges") or [])
            if detail.get("sample"):
                samples.append(detail["sample"])
        components = [
            ComponentAverage(
                id=c,
                label=COMPONENT_LABELS[c][0],
                measures=COMPONENT_LABELS[c][1],
                avg_percentile=sums[c] / n,
            )
            for c in COMPONENTS
            if c in sums
        ]
        components.sort(key=lambda c: c.avg_percentile, reverse=True)
        placements = [r.performance_rank for r in games if r.performance_rank]
        out.append(
            RoleScoreProfile(
                position=position,
                scored_games=n,
                enough=n >= MIN_SCORED_FOR_PROFILE,
                avg_score=sum(r.performance_score for r in games) / n,
                avg_placement=sum(placements) / len(placements) if placements else 0.0,
                mvp=badges["mvp"],
                ace=badges["ace"],
                components=components,
                sample=min(samples) if samples else None,
            )
        )
    out.sort(key=lambda p: p.scored_games, reverse=True)
    return out


@dataclass(slots=True)
class ChampionTotals:
    """Running sums for one champion. Averages are taken by the caller."""

    champion_id: int
    games: int = 0
    wins: int = 0
    kills: int = 0
    deaths: int = 0
    assists: int = 0
    cs: int = 0
    damage: int = 0
    minutes: float = 0.0
    scored_games: int = 0
    score_total: float = 0.0
    timeline_games: int = 0
    gold_diff_total: int = 0
    last_played: int = 0
    positions: Counter[str] = field(default_factory=Counter)

    @property
    def main_position(self) -> str | None:
        return self.positions.most_common(1)[0][0] if self.positions else None


async def profile_floor(session: AsyncSession) -> dict[str, int]:
    """The players who get a page, each with the time of their newest such game.

    ``MIN_SCORED_FOR_PROFILE`` scored ranked games in one role: the floor the
    page's own score breakdown needs, over the games the page opens on. Scored
    games in any queue and any role used to count, so a player with five games
    in each of two roles, or ten ARAM games, had a page that showed no
    breakdown at all.
    """
    rows = (
        await session.execute(
            select(MatchParticipant.puuid, func.max(Match.game_creation))
            .join(Match, Match.match_id == MatchParticipant.match_id)
            .where(
                MatchParticipant.performance_score.is_not(None),
                MatchParticipant.team_position.in_(POSITIONS),
                Match.is_remake.is_(False),
                Match.queue_id.in_(sorted(SCOPE_QUEUES["ranked"] or ())),
            )
            .group_by(MatchParticipant.puuid, MatchParticipant.team_position)
            .having(func.count() >= MIN_SCORED_FOR_PROFILE)
        )
    ).all()
    out: dict[str, int] = {}
    for puuid, newest in rows:
        out[puuid] = max(out.get(puuid, 0), int(newest or 0))
    return out


def champion_totals(rows: Iterable[PlayedRow]) -> list[ChampionTotals]:
    """Per champion, most played first."""
    by_champion: dict[int, ChampionTotals] = {}
    for row in rows:
        t = by_champion.get(row.champion_id)
        if t is None:
            t = by_champion[row.champion_id] = ChampionTotals(row.champion_id)
        t.games += 1
        t.wins += int(row.win)
        t.kills += row.kills
        t.deaths += row.deaths
        t.assists += row.assists
        t.cs += row.total_minions
        t.damage += row.damage_to_champions
        t.minutes += max(1.0, row.game_duration / 60)
        t.last_played = max(t.last_played, row.game_creation)
        if row.team_position:
            t.positions[row.team_position] += 1
        if row.performance_score is not None:
            t.scored_games += 1
            t.score_total += row.performance_score
        if row.gold_diff_14 is not None:
            t.timeline_games += 1
            t.gold_diff_total += row.gold_diff_14
    return sorted(by_champion.values(), key=lambda t: (-t.games, -t.last_played))


__all__ = [
    "MIN_SCORED_FOR_PROFILE",
    "ChampionTotals",
    "ComponentAverage",
    "RoleScoreProfile",
    "champion_totals",
    "profile_floor",
    "score_profile",
]
