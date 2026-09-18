"""Which lane each player in a live game is playing.

spectator-v5 does not say. Checked field by field against a live ranked game on
2026-09-19, a participant is a champion, two summoner spells, a keystone and two
rune trees, a skin, an icon and a name: there is no position, lane or role field
anywhere in the payload. So the lanes are inferred, and the inference was
measured before anything showed it.

The model is small on purpose, two counts from the stored corpus:

* P(position | champion), over every stored game where Riot recorded the
  position, and
* P(spell | position), for each of the two summoner spells,

scored for every way of giving a team's five players the five positions (120 of
them). An assignment that puts a team's only Smite anywhere but the jungle is
discarded outright. The best assignment is the answer, and a player's
confidence is the share of probability, across all the assignments that
survive, that puts them where the answer does.

Measured on stored ranked games, training on the older 80% and testing on the
newest 20%, so no game was scored by counts it helped build (1,778 lobbies,
3,560 held-out players, 2026-09-19):

    placed correctly    92.9% of players, whole team right 83.0%
    by role             jungle 100%, support 99.4%, bottom 93.1%,
                        top 88.2%, middle 83.7%

Top and middle are the weak pair because flex picks are played in both. The
spell counts are worth their keep but not much: champion alone scores 92.1%.
"""

from __future__ import annotations

import itertools
import math
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import MatchParticipant
from app.services.aggregate import POSITIONS

SMITE_SPELL_ID = 11
SUMMONERS_RIFT_MAP_ID = 11

# Laplace smoothing. A champion the corpus has never seen gets a flat prior
# rather than a zero that would veto every assignment it appears in.
ALPHA = 0.5
# Roughly how many distinct summoner spells exist, for the spell smoothing.
SPELL_VOCABULARY = 20

# The counts move nightly, not per request, and rebuilding them is two GROUP BYs
# over every stored participant. An hour keeps them fresh enough to be honest.
PRIORS_TTL_SECONDS = 3600

# Published with every inferred position, so the page can say how far to trust
# it. From the backtest in the module docstring.
MEASURED_ACCURACY = 0.929
MEASURED_PLAYERS = 3560

# At or above this, a position is shown plainly; below it, as "likely". The
# confidence is calibrated, measured on the same held-out players:
#
#     confidence >= 0.90   86% of players   right 98.1% of the time
#     0.70 to 0.90          9%              right 68.5%
#     below 0.70            6%              right 51.2%
CONFIDENT_AT = 0.9

RoleBasis = Literal["smite", "inferred"]


@dataclass(frozen=True, slots=True)
class RolePriors:
    """Counts, not probabilities: smoothing is applied when they are read."""

    champion: dict[int, dict[str, int]]
    spell: dict[str, dict[int, int]]
    participants: int


@dataclass(frozen=True, slots=True)
class RoleCall:
    position: str
    # The share of probability, over every surviving assignment, that puts this
    # player in `position`. 1.0 for a lone Smite in the jungle.
    confidence: float
    basis: RoleBasis


def _log_p_position(priors: RolePriors, champion_id: int, position: str) -> float:
    counts = priors.champion.get(champion_id, {})
    total = sum(counts.values())
    return math.log((counts.get(position, 0) + ALPHA) / (total + ALPHA * len(POSITIONS)))


def _log_p_spell(priors: RolePriors, spell_id: int, position: str) -> float:
    counts = priors.spell.get(position, {})
    total = sum(counts.values())
    return math.log((counts.get(spell_id, 0) + ALPHA) / (total + ALPHA * SPELL_VOCABULARY))


def assign_team(
    team: Sequence[tuple[int, int | None, int | None]], priors: RolePriors
) -> list[RoleCall] | None:
    """Positions for one team, as (champion_id, spell1_id, spell2_id) triples.

    ``None`` unless the team has exactly five players: a lane is only a lane on
    Summoner's Rift with five a side, and guessing roles for ARAM or Arena would
    invent structure those modes do not have.
    """
    if len(team) != len(POSITIONS):
        return None

    smiters = [i for i, (_, s1, s2) in enumerate(team) if SMITE_SPELL_ID in (s1, s2)]
    # Only a lone Smite is decisive. Two means a lane is running it as well, and
    # none means nobody is jungling at all; either way the counts decide.
    lone_smite = smiters[0] if len(smiters) == 1 else None
    jungle = POSITIONS.index("JUNGLE")

    # Each player's log-likelihood for each position. An assignment's score is
    # the sum of one entry per player, so this is computed once, not 120 times.
    fit = [
        [
            _log_p_position(priors, champion, position)
            + sum(_log_p_spell(priors, s, position) for s in (s1, s2) if s)
            for position in POSITIONS
        ]
        for champion, s1, s2 in team
    ]

    surviving: list[tuple[float, tuple[int, ...]]] = []
    for perm in itertools.permutations(range(len(POSITIONS))):
        if lone_smite is not None and any(
            (perm[i] == jungle) != (i == lone_smite) for i in range(len(team))
        ):
            continue
        surviving.append((sum(fit[i][perm[i]] for i in range(len(team))), perm))

    best_score, best = max(surviving)
    # Softmax over the surviving assignments, shifted by the best score so the
    # exponentials cannot overflow.
    weighted = [(math.exp(score - best_score), perm) for score, perm in surviving]
    mass = sum(w for w, _ in weighted)

    calls: list[RoleCall] = []
    for i in range(len(team)):
        chosen = best[i]
        agree = sum(w for w, perm in weighted if perm[i] == chosen)
        basis: RoleBasis = "smite" if lone_smite == i else "inferred"
        calls.append(RoleCall(POSITIONS[chosen], agree / mass, basis))
    return calls


_cache: tuple[float, RolePriors] | None = None


def clear_priors_cache() -> None:
    """For tests, which share one database and must not inherit counts."""
    global _cache
    _cache = None


async def load_priors(session: AsyncSession) -> RolePriors:
    """The two sets of counts, rebuilt at most once an hour per process."""
    global _cache
    now = time.monotonic()
    if _cache is not None and now - _cache[0] < PRIORS_TTL_SECONDS:
        return _cache[1]

    positioned = MatchParticipant.team_position.in_(POSITIONS)
    champion: dict[int, dict[str, int]] = {}
    participants = 0
    for champion_id, position, n in await session.execute(
        select(MatchParticipant.champion_id, MatchParticipant.team_position, func.count())
        .where(positioned)
        .group_by(MatchParticipant.champion_id, MatchParticipant.team_position)
    ):
        champion.setdefault(champion_id, {})[position] = n
        participants += n

    spell: dict[str, dict[int, int]] = {}
    for column in (MatchParticipant.summoner1_id, MatchParticipant.summoner2_id):
        for position, spell_id, n in await session.execute(
            select(MatchParticipant.team_position, column, func.count())
            .where(positioned, column.is_not(None))
            .group_by(MatchParticipant.team_position, column)
        ):
            bucket = spell.setdefault(position, {})
            bucket[spell_id] = bucket.get(spell_id, 0) + n

    priors = RolePriors(champion=champion, spell=spell, participants=participants)
    _cache = (now, priors)
    return priors


__all__ = [
    "CONFIDENT_AT",
    "MEASURED_ACCURACY",
    "MEASURED_PLAYERS",
    "RoleCall",
    "RolePriors",
    "SUMMONERS_RIFT_MAP_ID",
    "assign_team",
    "clear_priors_cache",
    "load_priors",
]
