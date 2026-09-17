"""Draft suggestions.

Given a role, what is already picked, and what is banned, rank the champions
worth taking.

The scoring is deliberately transparent and every component comes back in the
response. A draft tool that answers "pick Malphite" with no reason is one nobody
trusts on the third pick, so the UI can always show *why*.

Three components:

* **Base** -- how the champion performs in this role on this patch, as a Wilson
  lower bound so thin samples do not float to the top.
* **Matchup** -- the head-to-head record against the enemy laner, blended toward
  the base by sample size. With 4 games on record a 75% matchup means almost
  nothing; with 400 it means a lot. Shrinkage handles both without a cliff.
* **Comfort** -- the player's own mastery. A 51% champion with 200k points beats
  a 54% champion they have never played, and every draft tool that ignores this
  gives advice people cannot execute.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ChampionMastery, ChampionStat, MatchupStat
from app.services.aggregate import ALL_BRACKETS, wilson_lower_bound

log = logging.getLogger(__name__)

# Games at which a matchup record earns half its weight. Below this the estimate
# is pulled toward the champion's own baseline.
MATCHUP_SHRINKAGE = 30.0

# Mastery points that count as "fully comfortable".
COMFORT_CEILING = 100_000.0

# Win-rate points a fully comfortable champion can gain at comfort_weight 1.0.
# Scored in the same units as win rate so the two are directly comparable: at
# the default weight of 0.15 a maxed-out champion pool is worth +1.5pp, enough
# to break a tie between similar picks without letting comfort outrank a
# genuinely better champion.
COMFORT_MAX_BONUS = 0.10


@dataclass
class Suggestion:
    champion_id: int
    base_win_rate: float
    games: int
    matchup_win_rate: float | None = None
    matchup_games: int = 0
    adjusted_win_rate: float = 0.0
    comfort: float = 0.0
    mastery_points: int = 0
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)


@dataclass
class DraftContext:
    position: str
    patch: str
    queue_id: int = 420
    # Rollups are stored per bracket, and ALL overlaps the per-tier slices. A
    # query without this returns the same champion once per bracket it appears
    # in, so it is a filter, not a preference.
    rank_bracket: str = ALL_BRACKETS
    allies: list[int] = field(default_factory=list)
    enemies: list[int] = field(default_factory=list)
    bans: list[int] = field(default_factory=list)
    # The enemy champion actually in this lane, when the client knows it.
    enemy_laner: int | None = None
    puuid: str | None = None
    comfort_weight: float = 0.15
    min_games: int = 20


class DraftAdvisor:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def suggest(self, ctx: DraftContext, *, limit: int = 15) -> list[Suggestion]:
        unavailable = set(ctx.allies) | set(ctx.enemies) | set(ctx.bans)

        stats = list(
            (
                await self.session.execute(
                    select(ChampionStat).where(
                        ChampionStat.patch == ctx.patch,
                        ChampionStat.queue_id == ctx.queue_id,
                        ChampionStat.team_position == ctx.position,
                        ChampionStat.rank_bracket == ctx.rank_bracket,
                        ChampionStat.games >= ctx.min_games,
                    )
                )
            ).scalars()
        )
        if not stats:
            return []

        matchups = await self._matchups(ctx)
        mastery = await self._mastery(ctx)

        suggestions: list[Suggestion] = []
        for stat in stats:
            if stat.champion_id in unavailable:
                continue

            base = wilson_lower_bound(stat.wins, stat.games)
            suggestion = Suggestion(
                champion_id=stat.champion_id,
                base_win_rate=base,
                games=stat.games,
                adjusted_win_rate=base,
            )

            record = matchups.get(stat.champion_id)
            if record:
                wins, games = record
                observed = wins / games
                # Shrink the observed matchup toward this champion's own
                # baseline in proportion to how much evidence there is.
                weight = games / (games + MATCHUP_SHRINKAGE)
                suggestion.matchup_win_rate = observed
                suggestion.matchup_games = games
                suggestion.adjusted_win_rate = base + weight * (observed - base)

            points = mastery.get(stat.champion_id, 0)
            suggestion.mastery_points = points
            suggestion.comfort = min(1.0, points / COMFORT_CEILING)

            suggestion.score = suggestion.adjusted_win_rate + (
                ctx.comfort_weight * suggestion.comfort * COMFORT_MAX_BONUS
            )
            suggestion.reasons = self._explain(suggestion, ctx)
            suggestions.append(suggestion)

        suggestions.sort(key=lambda s: s.score, reverse=True)
        return suggestions[:limit]

    async def _matchups(self, ctx: DraftContext) -> dict[int, tuple[int, int]]:
        """Head-to-head records against the enemy laner, keyed by our champion."""
        if ctx.enemy_laner is None:
            return {}
        rows = (
            await self.session.execute(
                select(
                    MatchupStat.champion_id, MatchupStat.wins, MatchupStat.games
                ).where(
                    MatchupStat.patch == ctx.patch,
                    MatchupStat.queue_id == ctx.queue_id,
                    MatchupStat.team_position == ctx.position,
                    MatchupStat.rank_bracket == ctx.rank_bracket,
                    MatchupStat.enemy_champion_id == ctx.enemy_laner,
                    MatchupStat.scope == "LANE",
                )
            )
        ).all()
        return {champion: (wins, games) for champion, wins, games in rows}

    async def _mastery(self, ctx: DraftContext) -> dict[int, int]:
        if not ctx.puuid:
            return {}
        rows = (
            await self.session.execute(
                select(ChampionMastery.champion_id, ChampionMastery.champion_points).where(
                    ChampionMastery.puuid == ctx.puuid
                )
            )
        ).all()
        return dict(rows)

    @staticmethod
    def _explain(s: Suggestion, ctx: DraftContext) -> list[str]:
        reasons: list[str] = []
        # The row already prints the score. Repeating the same figure underneath
        # it reads as a template filling itself in, so the percentage appears
        # only when the adjustment moved it and the two numbers really differ.
        if s.adjusted_win_rate == s.base_win_rate:
            reasons.append(f"baseline over {s.games} games")
        else:
            reasons.append(
                f"{s.base_win_rate * 100:.1f}% baseline over {s.games} games"
            )

        if s.matchup_win_rate is not None:
            delta = (s.adjusted_win_rate - s.base_win_rate) * 100
            direction = "favoured" if delta >= 0 else "unfavoured"
            confidence = "solid sample" if s.matchup_games >= 30 else "small sample"
            reasons.append(
                f"{direction} into this lane: {s.matchup_win_rate * 100:.0f}% "
                f"over {s.matchup_games} games ({confidence})"
            )
        elif ctx.enemy_laner is not None:
            reasons.append("no head-to-head data for this matchup yet")

        if s.mastery_points >= 10_000:
            reasons.append(f"{s.mastery_points // 1000}k mastery points")
        elif ctx.puuid and s.mastery_points == 0:
            reasons.append("never played on this account")

        return reasons
