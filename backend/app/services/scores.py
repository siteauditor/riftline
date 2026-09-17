"""The Riftline score: a per-player, per-game performance rating.

This is the one number in the app that Riot does not give us and no competitor
will explain. op.gg's OP Score is proprietary; itero at least publishes its
draft model. We publish ours, because a rating nobody can audit is a rating
nobody should trust.

How it works
------------

Six components, each measuring a different thing a player can contribute. Every
one is converted to a **percentile within its own (queue, role) distribution**
over the matches we hold, then combined with per-role weights into 0 to 10.

The role-relative step is what makes the number mean anything. A support with
1.2k gold a minute is not failing at economy, they are playing support, so they
are measured against supports. It is also what makes cross-role placement
legitimate: with every player scored against their own role, the ten numbers in
a lobby sit on one scale, and "1st in this game" is a claim rather than a
restatement of "played mid".

Percentiles rather than z-scores: damage and gold per minute have long right
tails, so a mean and standard deviation let one forty-minute stomp dominate the
scale. A percentile is also directly sayable, which matters because the UI says
it: "better than 78% of mid laners in our corpus".

Validated before it was written. Over 1,200 ranked games, the winning team
averaged 5.69 against the losers' 4.23, the lobby's top scorer was on the
winning team 87.8% of the time, the bottom scorer was on the losing team 84.2%
of the time, and every role's mean landed between 4.93 and 4.97.

What it is not
--------------

It is not a skill rating. It describes one game against our corpus, which is
EUW-heavy and seeded from the Challenger ladder. It is withheld rather than
guessed wherever that corpus cannot carry it, following the rule
``MIN_RANKED_FOR_LOBBY_RANK`` already sets for the lobby tier.
"""

from __future__ import annotations

import bisect
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Match, MatchParticipant, RoleMetricStat, utcnow
from app.services.aggregate import POSITIONS

log = logging.getLogger(__name__)

# Bump when a weight, a component or a percentile rule changes. Scores carry the
# version they were computed under, so a change makes old rows visibly stale
# instead of quietly inconsistent with new ones.
WEIGHTS_VERSION = 1

# Six components. The keys are stored in `performance_detail` and shipped to the
# UI, so they are short but readable rather than indices.
COMPONENTS = ("kill_part", "damage", "economy", "survival", "objectives", "vision")

# What each one is called where a person reads it, and what it measures. Shipped
# with the score so the explanation cannot drift from the code.
COMPONENT_LABELS: dict[str, tuple[str, str]] = {
    "kill_part": ("Kill participation", "Share of the team's kills you took part in"),
    "damage": ("Damage share", "Share of the team's damage to champions"),
    "economy": ("Economy", "Gold earned per minute"),
    "survival": ("Survival", "Share of the game spent alive"),
    "objectives": ("Objectives", "Towers, plates and epic monsters taken"),
    "vision": ("Vision", "Vision score per minute"),
}

# Per-role weights, each row summing to 1.0. These are the values the validation
# in the module docstring was measured with.
#
# The shape of the table is the argument: a support is weighted on vision and
# participation and barely on farm, a jungler on objectives, a marksman on
# damage. Without that, every role-neutral rating quietly ranks supports last.
WEIGHTS: dict[str, dict[str, float]] = {
    "TOP":     {"kill_part": 0.20, "damage": 0.22, "economy": 0.18,
                "survival": 0.18, "objectives": 0.14, "vision": 0.08},
    "JUNGLE":  {"kill_part": 0.24, "damage": 0.16, "economy": 0.14,
                "survival": 0.16, "objectives": 0.22, "vision": 0.08},
    "MIDDLE":  {"kill_part": 0.22, "damage": 0.26, "economy": 0.18,
                "survival": 0.16, "objectives": 0.10, "vision": 0.08},
    "BOTTOM":  {"kill_part": 0.20, "damage": 0.28, "economy": 0.20,
                "survival": 0.16, "objectives": 0.10, "vision": 0.06},
    "UTILITY": {"kill_part": 0.26, "damage": 0.10, "economy": 0.08,
                "survival": 0.16, "objectives": 0.08, "vision": 0.32},
}

# A percentile over fewer games than this describes our corpus, not the player.
MIN_GAMES_FOR_SCORE = 200

# 101 breakpoints: index i is the value at the i-th percentile.
QUANTILES = 101

# Deaths are only remarkable in a game long enough to have had some.
DEATHLESS_MINIMUM_SECONDS = 900

# Thresholds swept against the corpus rather than guessed. See the plan: a
# 1,200 gold lane floor fires in 89.7% of games and says nothing; 2,000 fires in
# 57.7%. A 2,000 healing floor fires 0.81 times a game against a median of zero;
# 5,000 fires 0.52.
LANE_LEAD_GOLD = 2000
LIFELINE_FLOOR = 5000
SHARE_FLOOR = 0.30
DUELIST_SOLO_KILLS = 3


@dataclass(frozen=True, slots=True)
class Badge:
    """One badge and the rule that earns it.

    ``rate`` is how often it was measured to fire per game over 1,400 ranked
    games, and it is not decoration: the match row has space for two badges, so
    the rarest earned badge is the one that gets shown.
    """

    id: str
    label: str
    rule: str
    rate: float


# Ordered rarest first, which is the order the UI picks from.
BADGES: tuple[Badge, ...] = (
    Badge("steal", "Steal", "Stole a dragon, herald or baron from the enemy", 0.14),
    Badge("deathless", "Deathless",
          "Finished a game of 15 minutes or more without dying", 0.29),
    Badge("frontline", "Frontline",
          "Took the largest share of the team's damage, and at least 30% of it", 0.39),
    Badge("lifeline", "Lifeline",
          "Most healing and shielding that landed on an ally in the lobby", 0.52),
    Badge("lane_lead", "Lane lead",
          "Biggest gold lead at 14 minutes in the lobby, and at least 2,000 gold", 0.58),
    Badge("mvp", "MVP", "Highest Riftline score on the winning team", 1.00),
    Badge("ace", "ACE", "Highest Riftline score on the losing team", 1.00),
    Badge("damage_carry", "Damage carry",
          "Largest share of the team's damage to champions, and at least 30% of it",
          1.00),
    Badge("duelist", "Duelist", "Three or more solo kills", 1.41),
)

BADGES_BY_ID = {b.id: b for b in BADGES}


@dataclass
class ScoreStats:
    """Progress for the scoring pass, which touches no network at all."""

    lifted: int = 0
    scored: int = 0
    withheld: int = 0
    distributions: int = 0
    errors: int = 0
    reasons: dict[str, int] = field(default_factory=dict)

    def withhold(self, reason: str) -> None:
        self.withheld += 1
        self.reasons[reason] = self.reasons.get(reason, 0) + 1

    def line(self) -> str:
        parts = [
            f"lifted={self.lifted}",
            f"scored={self.scored}",
            f"withheld={self.withheld}",
        ]
        if self.distributions:
            parts.append(f"distributions={self.distributions}")
        if self.errors:
            parts.append(f"errors={self.errors}")
        if self.reasons:
            why = ", ".join(f"{k} {v}" for k, v in sorted(self.reasons.items()))
            parts.append(f"({why})")
        return " ".join(parts)


# ------------------------------------------------------------------- lifting


def _int(value: Any) -> int:
    """Riot sends absent counters as missing keys and occasionally as null."""
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def lifted_fields(participant: dict) -> dict[str, int]:
    """The columns we keep from a raw match-v5 participant.

    Every one of these is in `matches.raw` already; the ingest simply never
    mapped them. Reading them from storage is why this whole feature costs no
    Riot calls.
    """
    ch = participant.get("challenges") or {}
    return {
        "time_dead": _int(participant.get("totalTimeSpentDead")),
        "turret_takedowns": _int(ch.get("turretTakedowns")),
        "turret_plates": _int(ch.get("turretPlatesTaken")),
        # One objective term: the three epic monsters are never shown apart.
        "epic_takedowns": (
            _int(ch.get("dragonTakedowns"))
            + _int(ch.get("baronTakedowns"))
            + _int(ch.get("riftHeraldTakedowns"))
        ),
        "objectives_stolen": _int(ch.get("epicMonsterSteals")),
        "solo_kills": _int(ch.get("soloKills")),
        "heal_and_shield": _int(ch.get("effectiveHealAndShielding")),
        "wards_placed": _int(participant.get("wardsPlaced")),
        "wards_killed": _int(participant.get("wardsKilled")),
        "control_wards": _int(ch.get("controlWardsPlaced")),
    }


# ------------------------------------------------------------- the components


def component_values(
    participant: MatchParticipant,
    *,
    duration_seconds: int,
    team_damage: int,
    team_kills: int,
) -> dict[str, float] | None:
    """The six raw component values for one participant.

    ``None`` when the row has not been lifted out of `raw` yet, which is a
    different answer from zero and must not be scored as if it were.
    """
    if participant.time_dead is None:
        return None

    minutes = max(1.0, duration_seconds / 60)
    took_part = participant.kills + participant.assists
    return {
        # Riot computes killParticipation too, but from the team's kills, which
        # we hold: deriving it keeps the score readable from columns alone.
        "kill_part": (took_part / team_kills) if team_kills else 0.0,
        "damage": (
            participant.damage_to_champions / team_damage if team_damage else 0.0
        ),
        "economy": participant.gold_earned / minutes,
        # Time alive, not deaths. A death at minute 4 costs a fraction of what
        # one at minute 34 costs, and Riot gives us the actual dead time.
        "survival": 1.0 - min(1.0, (participant.time_dead or 0) / max(1, duration_seconds)),
        "objectives": (
            (participant.turret_takedowns or 0)
            + (participant.turret_plates or 0)
            + (participant.epic_takedowns or 0)
        ),
        "vision": participant.vision_score / minutes,
    }


def percentile(breakpoints: list[float], value: float) -> float:
    """Where ``value`` falls in a distribution given as 101 breakpoints.

    Returns 0.0 at or below the lowest observed value and 1.0 at or above the
    highest, so the score cannot leave its range however odd the input.
    """
    if not breakpoints:
        return 0.0
    # Midpoint of the tied band, which is the conventional percentile rank.
    # `bisect_right` alone hands every player tied at zero objectives the top
    # of that band, and in a support's distribution that band is 40% wide.
    low = bisect.bisect_left(breakpoints, value)
    high = bisect.bisect_right(breakpoints, value)
    index = (low + high) / 2
    return min(1.0, max(0.0, index / (len(breakpoints) - 1)))


def combine(percentiles: dict[str, float], role: str) -> float:
    """Weighted mean of the six percentiles, on a 0 to 10 scale."""
    weights = WEIGHTS[role]
    return 10.0 * sum(weights[c] * percentiles[c] for c in COMPONENTS)


# ------------------------------------------------------------------- badges


def award_badges(
    scored: list[tuple[MatchParticipant, float, dict[str, float]]],
    *,
    duration_seconds: int,
    team_damage: dict[int, int],
    team_taken: dict[int, int],
) -> dict[int, list[str]]:
    """Which badges each participant earned, keyed by participant index.

    Every rule is a single measurable claim, and every one is evaluated against
    the lobby rather than against a fixed threshold wherever a lobby comparison
    is what the badge is about. The tooltip copy lives on `BADGES`, so a rule
    and its explanation cannot drift apart.
    """
    out: dict[int, list[str]] = {p.participant_index: [] for p, _, _ in scored}

    def give(participant: MatchParticipant, badge_id: str) -> None:
        out[participant.participant_index].append(badge_id)

    # MVP and ACE: the best game on each side.
    for winning in (True, False):
        side = [(p, s) for p, s, _ in scored if p.win is winning]
        if side:
            best, _ = max(side, key=lambda ps: ps[1])
            give(best, "mvp" if winning else "ace")

    for participant, _, _ in scored:
        dealt = team_damage.get(participant.team_id) or 0
        taken = team_taken.get(participant.team_id) or 0
        mates = [p for p, _, _ in scored if p.team_id == participant.team_id]

        share_dealt = participant.damage_to_champions / dealt if dealt else 0.0
        if share_dealt >= SHARE_FLOOR and participant.damage_to_champions == max(
            m.damage_to_champions for m in mates
        ):
            give(participant, "damage_carry")

        share_taken = participant.damage_taken / taken if taken else 0.0
        if share_taken >= SHARE_FLOOR and participant.damage_taken == max(
            m.damage_taken for m in mates
        ):
            give(participant, "frontline")

        if participant.deaths == 0 and duration_seconds >= DEATHLESS_MINIMUM_SECONDS:
            give(participant, "deathless")

        if (participant.solo_kills or 0) >= DUELIST_SOLO_KILLS:
            give(participant, "duelist")

        if (participant.objectives_stolen or 0) >= 1:
            give(participant, "steal")

    # Lobby-wide bests, each with a floor so the badge means something.
    heals = [(p, p.heal_and_shield or 0) for p, _, _ in scored]
    best_heal = max(heals, key=lambda ph: ph[1])
    if best_heal[1] >= LIFELINE_FLOOR:
        give(best_heal[0], "lifeline")

    leads = [(p, p.gold_diff_14) for p, _, _ in scored if p.gold_diff_14 is not None]
    if leads:
        best_lead = max(leads, key=lambda pg: pg[1])
        if best_lead[1] >= LANE_LEAD_GOLD:
            give(best_lead[0], "lane_lead")

    # Rarest first, so a caller showing only one or two shows the interesting
    # ones. `BADGES` is already in that order.
    order = {b.id: i for i, b in enumerate(BADGES)}
    for index in out:
        out[index].sort(key=lambda b: order[b])
    return out


def badge_detail(badge_id: str, participant: MatchParticipant, match: Match) -> str:
    """The tooltip: the rule, and this player's own figure for it.

    Generated at read time rather than stored so the copy can improve without
    rescoring eighteen thousand rows.
    """
    badge = BADGES_BY_ID[badge_id]
    mates = [p for p in match.participants if p.team_id == participant.team_id]
    facts: dict[str, str] = {
        "deathless": f"{participant.deaths} deaths in {match.game_duration // 60} minutes",
        "duelist": f"{participant.solo_kills} solo kills",
        "steal": f"{participant.objectives_stolen} stolen",
        "lifeline": f"{participant.heal_and_shield or 0:,} healed and shielded",
        "lane_lead": (
            f"{participant.gold_diff_14:+,} gold at 14 minutes"
            if participant.gold_diff_14 is not None
            else ""
        ),
    }
    dealt = sum(p.damage_to_champions for p in mates)
    taken = sum(p.damage_taken for p in mates)
    if badge_id == "damage_carry" and dealt:
        facts[badge_id] = f"{participant.damage_to_champions / dealt:.0%} of the team's damage"
    if badge_id == "frontline" and taken:
        facts[badge_id] = f"{participant.damage_taken / taken:.0%} of the damage the team took"
    if badge_id in ("mvp", "ace") and participant.performance_score is not None:
        facts[badge_id] = f"scored {participant.performance_score:.1f}"

    fact = facts.get(badge_id)
    if not fact:
        return f"{badge.rule}."
    # The fragments are written lower case because most read as a measurement
    # ("37% of the team's damage"), but they land after a full stop.
    return f"{badge.rule}. {fact[0].upper()}{fact[1:]}."


# ------------------------------------------------------------------ service


class ScoreService:
    """Lifts fields out of `raw`, measures the corpus, and scores matches.

    Every read is local. This is the only backfill in the app that touches no
    Riot endpoint, so it runs at disk speed and needs no rate limiter, no
    concurrency ceiling and no resume bookmark beyond "which rows are null".
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.stats = ScoreStats()
        self._dists: dict[tuple[int, str, str], RoleMetricStat] | None = None

    # ------------------------------------------------------------- lifting

    async def lift_remaining(self) -> int:
        stmt = select(func.count(MatchParticipant.id)).where(
            MatchParticipant.time_dead.is_(None)
        )
        return (await self.session.execute(stmt)).scalar() or 0

    async def lift_fields(self, *, batch: int = 200) -> int:
        """Copy the unmapped Riot fields from `matches.raw` into columns.

        The cursor is the absence of the data, the same as timelines, with one
        difference that matters: a stored payload can be short a participant,
        and that row then stays null however many times it is visited. Asking
        the same question again would hand back the same match for ever, so the
        ids already attempted in this run are excluded. Measured before the
        fix: 505 passes over the same nine rows in four seconds.
        """
        total = 0
        attempted: set[str] = set()
        while True:
            stmt = (
                select(MatchParticipant.match_id)
                .where(MatchParticipant.time_dead.is_(None))
                .distinct()
                .limit(batch)
            )
            if attempted:
                stmt = stmt.where(MatchParticipant.match_id.not_in(attempted))
            ids = (await self.session.execute(stmt)).scalars().all()
            if not ids:
                break
            attempted.update(ids)

            matches = (
                await self.session.execute(
                    select(Match)
                    .where(Match.match_id.in_(list(ids)))
                    .options(selectinload(Match.participants))
                )
            ).scalars().all()

            for match in matches:
                raw = match.raw
                if isinstance(raw, str):  # SQLite can hand JSON back as text
                    raw = json.loads(raw)
                participants = ((raw or {}).get("info") or {}).get("participants") or []
                by_index = {
                    _int(p.get("participantId")): p for p in participants
                }
                for participant in match.participants:
                    source = by_index.get(participant.participant_index)
                    if source is None:
                        # No raw payload for this row. Zeroes would be a claim;
                        # leaving it null keeps it out of every score, and the
                        # `attempted` set above keeps it out of the next pass.
                        self.stats.errors += 1
                        log.warning(
                            "%s participant %d is absent from the stored payload",
                            match.match_id,
                            participant.participant_index,
                        )
                        continue
                    for key, value in lifted_fields(source).items():
                        setattr(participant, key, value)
                    total += 1
                    self.stats.lifted += 1

            await self.session.commit()
            log.info("lifted %d participant rows", self.stats.lifted)
        return total

    # ------------------------------------------------------- distributions

    async def rebuild_distributions(self) -> int:
        """Measure the corpus: 101 breakpoints per (queue, role, metric).

        Pooled across patches deliberately. What a jungler's objective count
        looks like does not move the way a champion's win rate does, and slicing
        by patch would put every role under the sample floor.
        """
        rows = (
            await self.session.execute(
                select(
                    Match.queue_id,
                    MatchParticipant.team_position,
                    MatchParticipant.kills,
                    MatchParticipant.assists,
                    MatchParticipant.damage_to_champions,
                    MatchParticipant.gold_earned,
                    MatchParticipant.vision_score,
                    MatchParticipant.time_dead,
                    MatchParticipant.turret_takedowns,
                    MatchParticipant.turret_plates,
                    MatchParticipant.epic_takedowns,
                    Match.game_duration,
                    MatchParticipant.match_id,
                    MatchParticipant.team_id,
                )
                .join(Match, Match.match_id == MatchParticipant.match_id)
                .where(
                    Match.is_remake.is_(False),
                    MatchParticipant.team_position.in_(POSITIONS),
                    MatchParticipant.time_dead.is_not(None),
                )
            )
        ).all()

        # Only whole lobbies. Two of the six components are shares of a team
        # total, and that total is summed from the rows this query returned: a
        # 5v5 with one position missing would contribute nine inflated shares to
        # the yardstick every other game is then measured against. The scorer
        # already refuses such a lobby, so this keeps the two agreeing on what
        # counts as measurable.
        per_match: dict[str, int] = {}
        for r in rows:
            per_match[r.match_id] = per_match.get(r.match_id, 0) + 1
        whole = {mid for mid, n in per_match.items() if n == 10}
        skipped = len(per_match) - len(whole)
        if skipped:
            log.info("distributions skip %d partial lobbies", skipped)
        rows = [r for r in rows if r.match_id in whole]

        # Team totals for the two share components, keyed by (match, team).
        team_damage: dict[tuple[str, int], int] = {}
        team_kills: dict[tuple[str, int], int] = {}
        for r in rows:
            key = (r.match_id, r.team_id)
            team_damage[key] = team_damage.get(key, 0) + r.damage_to_champions
            team_kills[key] = team_kills.get(key, 0) + r.kills

        samples: dict[tuple[int, str, str], list[float]] = {}
        for r in rows:
            key = (r.match_id, r.team_id)
            minutes = max(1.0, r.game_duration / 60)
            kills = team_kills.get(key) or 0
            damage = team_damage.get(key) or 0
            values = {
                "kill_part": ((r.kills + r.assists) / kills) if kills else 0.0,
                "damage": (r.damage_to_champions / damage) if damage else 0.0,
                "economy": r.gold_earned / minutes,
                "survival": 1.0
                - min(1.0, (r.time_dead or 0) / max(1, r.game_duration)),
                "objectives": (
                    (r.turret_takedowns or 0)
                    + (r.turret_plates or 0)
                    + (r.epic_takedowns or 0)
                ),
                "vision": r.vision_score / minutes,
            }
            for metric, value in values.items():
                samples.setdefault(
                    (r.queue_id, r.team_position, metric), []
                ).append(float(value))

        await self.session.execute(RoleMetricStat.__table__.delete())
        payload = []
        for (queue_id, position, metric), values in samples.items():
            values.sort()
            last = len(values) - 1
            breakpoints = [
                values[round(i * last / (QUANTILES - 1))] for i in range(QUANTILES)
            ]
            payload.append(
                {
                    "queue_id": queue_id,
                    "team_position": position,
                    "metric": metric,
                    "breakpoints": breakpoints,
                    "games": len(values),
                    "computed_at": utcnow(),
                }
            )
        if payload:
            await self.session.execute(RoleMetricStat.__table__.insert(), payload)

        # Every existing score was a percentile against the distributions this
        # call just replaced, so it now describes a corpus that no longer
        # exists. Clearing them is what makes "rebuild" mean what it says; the
        # whole corpus rescores in seconds because nothing here touches Riot.
        cleared = (
            await self.session.execute(
                MatchParticipant.__table__.update()
                .where(MatchParticipant.performance_scored_at.is_not(None))
                .values(
                    performance_score=None,
                    performance_rank=None,
                    performance_detail=None,
                    performance_scored_at=None,
                )
            )
        ).rowcount
        await self.session.commit()
        self.stats.distributions = len(payload)
        self._dists = None
        log.info(
            "rebuilt %d role metric distributions, cleared %d scores measured "
            "against the old ones",
            len(payload),
            cleared or 0,
        )
        return len(payload)

    async def _distributions(self) -> dict[tuple[int, str, str], RoleMetricStat]:
        if self._dists is None:
            rows = (await self.session.execute(select(RoleMetricStat))).scalars().all()
            self._dists = {
                (r.queue_id, r.team_position, r.metric): r for r in rows
            }
        return self._dists

    # ------------------------------------------------------------- scoring

    async def unscored(self) -> int:
        """Matches with fields lifted that have not been through scoring.

        Not "matches without a score": a withheld lobby has no score and never
        will, and counting it here would report work that does not exist. The
        stamp is what says it has been considered.
        """
        stmt = select(func.count(func.distinct(MatchParticipant.match_id))).where(
            MatchParticipant.performance_scored_at.is_(None),
            MatchParticipant.time_dead.is_not(None),
        )
        return (await self.session.execute(stmt)).scalar() or 0

    async def score_match(self, match: Match) -> int:
        """Score one lobby, or withhold and say why.

        Returns the number of participants scored, which is 0 or the whole
        lobby: a score is a placement within the ten, so scoring some of them
        would produce a ranking of a subset dressed up as a ranking of the game.
        """
        participants = list(match.participants)
        if match.is_remake:
            self.stats.withhold("remake")
            return 0
        if len(participants) != 10:
            self.stats.withhold("not a ten player lobby")
            return 0
        if any(p.team_position not in POSITIONS for p in participants):
            # ARAM and Arena report no position, so there is no role to be
            # relative to. Better nothing than a number from the wrong scale.
            self.stats.withhold("no lane roles")
            return 0
        if any(p.time_dead is None for p in participants):
            self.stats.withhold("fields not lifted")
            return 0

        dists = await self._distributions()
        thin = [
            p.team_position
            for p in participants
            if any(
                (dists.get((match.queue_id, p.team_position, c)) is None)
                or (dists[(match.queue_id, p.team_position, c)].games
                    < MIN_GAMES_FOR_SCORE)
                for c in COMPONENTS
            )
        ]
        if thin:
            self.stats.withhold("corpus too thin for this queue")
            return 0

        team_damage: dict[int, int] = {}
        team_taken: dict[int, int] = {}
        team_kills: dict[int, int] = {}
        for p in participants:
            team_damage[p.team_id] = team_damage.get(p.team_id, 0) + p.damage_to_champions
            team_taken[p.team_id] = team_taken.get(p.team_id, 0) + p.damage_taken
            team_kills[p.team_id] = team_kills.get(p.team_id, 0) + p.kills

        scored: list[tuple[MatchParticipant, float, dict[str, float]]] = []
        for p in participants:
            raw_values = component_values(
                p,
                duration_seconds=match.game_duration,
                team_damage=team_damage.get(p.team_id) or 0,
                team_kills=team_kills.get(p.team_id) or 0,
            )
            if raw_values is None:
                self.stats.withhold("fields not lifted")
                return 0
            pcts = {
                c: percentile(
                    dists[(match.queue_id, p.team_position, c)].breakpoints,
                    raw_values[c],
                )
                for c in COMPONENTS
            }
            scored.append((p, combine(pcts, p.team_position), pcts))

        badges = award_badges(
            scored,
            duration_seconds=match.game_duration,
            team_damage=team_damage,
            team_taken=team_taken,
        )

        # Placement. Ties break on the participant index so a rerun produces
        # the same ranking rather than shuffling equal scores.
        order = sorted(scored, key=lambda t: (-t[1], t[0].participant_index))
        stamped = utcnow()
        for placement, (p, score, pcts) in enumerate(order, start=1):
            p.performance_score = round(score, 2)
            p.performance_rank = placement
            p.performance_detail = {
                "components": {c: round(pcts[c], 4) for c in COMPONENTS},
                "badges": badges[p.participant_index],
                # This player's own role, because that is what the UI says it
                # is: "measured against N games in this role". A lobby-wide
                # minimum would be a different number under the same sentence.
                "sample": min(
                    dists[(match.queue_id, p.team_position, c)].games
                    for c in COMPONENTS
                ),
                "weights": WEIGHTS_VERSION,
            }
            p.performance_scored_at = stamped
            self.stats.scored += 1
        return len(order)

    async def score_matches(self, *, target: int | None = None, batch: int = 100) -> int:
        """Score every match that has no score, or a score from old weights."""
        done = 0
        while target is None or done < target:
            limit = batch if target is None else min(batch, target - done)
            ids = (
                await self.session.execute(
                    select(MatchParticipant.match_id)
                    .where(
                        MatchParticipant.performance_scored_at.is_(None),
                        MatchParticipant.time_dead.is_not(None),
                    )
                    .distinct()
                    .limit(limit)
                )
            ).scalars().all()
            if not ids:
                break

            matches = (
                await self.session.execute(
                    select(Match)
                    .where(Match.match_id.in_(list(ids)))
                    .options(selectinload(Match.participants))
                )
            ).scalars().all()
            for match in matches:
                if await self.score_match(match) == 0:
                    # Withheld. Stamp the timestamp so the same lobby is not
                    # offered again on every pass, exactly as the lobby-rank
                    # backfill learned to do.
                    for p in match.participants:
                        p.performance_scored_at = utcnow()
                done += 1
            await self.session.commit()
            log.info("scores: %s", self.stats.line())
        return done

    async def rescore_stale(self) -> int:
        """Clear scores computed under older weights so they are recomputed."""
        rows = (
            await self.session.execute(
                select(MatchParticipant).where(
                    MatchParticipant.performance_score.is_not(None)
                )
            )
        ).scalars().all()
        cleared = 0
        for p in rows:
            detail = p.performance_detail or {}
            if detail.get("weights") != WEIGHTS_VERSION:
                p.performance_score = None
                p.performance_rank = None
                p.performance_detail = None
                p.performance_scored_at = None
                cleared += 1
        if cleared:
            await self.session.commit()
            log.info("cleared %d scores from older weights", cleared)
        return cleared

    # ------------------------------------------------------------ reporting

    async def has_distributions(self) -> bool:
        stmt = select(func.count(RoleMetricStat.id))
        return bool((await self.session.execute(stmt)).scalar())

    async def coverage(self) -> dict[str, Any]:
        """What share of the corpus carries a score, and what was withheld.

        Reported rather than inferred: "scored" and "considered but withheld"
        are different facts, and a single percentage would hide the second.
        """
        participants = (
            await self.session.execute(select(func.count(MatchParticipant.id)))
        ).scalar() or 0
        scored = (
            await self.session.execute(
                select(func.count(MatchParticipant.id)).where(
                    MatchParticipant.performance_score.is_not(None)
                )
            )
        ).scalar() or 0
        withheld = (
            await self.session.execute(
                select(func.count(func.distinct(MatchParticipant.match_id))).where(
                    MatchParticipant.performance_scored_at.is_not(None),
                    MatchParticipant.performance_score.is_(None),
                )
            )
        ).scalar() or 0
        distributions = (
            await self.session.execute(select(func.count(RoleMetricStat.id)))
        ).scalar() or 0
        return {
            "participants": participants,
            "scored": scored,
            "percent": (scored / participants * 100) if participants else 0.0,
            "withheld_matches": withheld,
            "distributions": distributions,
        }
