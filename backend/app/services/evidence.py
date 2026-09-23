"""What one record says about a pick: the arithmetic the draft and the live page share.

A record is a champion's wins and games in one context (against one lane
opponent, against one enemy anywhere on the map, beside one ally), possibly
over two patches. The question is always the same: how far does this context
move the champion from its own win rate, and is that far enough to say so.

**Measured 2026-09-24, not chosen.** For the same champion pair on patches 16.17
and 16.18, a lane record's deviation from the champion's own rate repeats across
patches (r = +0.23 over 112 pairs with five or more games, 95% interval +0.05 to
+0.42), which puts the real spread of lane matchups at a prior worth 24 to 53
games (plausible 10 to 146). Enemy-team and ally records do not measurably
repeat (r between -0.13 and +0.07, every interval spanning zero): on this
corpus they vary no more than chance. Within 16.18 alone the spread of lane and
enemy-team records is no larger than binomial noise. `python -m scripts.ingest
draftpriors` re-measures all of this as the corpus grows.

So a record is read as a posterior: the context's true deviation has a prior
centred on zero worth ``strength`` games, and the record's games are evidence
against it. Both the number and the label come from that one posterior:

* ``lift`` is the posterior mean deviation, ``sum(n_i d_i) / (n + strength)``,
  where ``d_i`` is each patch's record minus the champion's own rate on that
  patch. Symmetric: a 2-0 and an 0-2 move a pick by the same amount.
* ``call`` is favoured or unfavoured only when the posterior puts 90% on that
  side (``z >= 1.28``). A 3-2 is level, a 40-20 lane record is favoured, the
  same 40-20 as a team-scope record (strength 500) is level, and 2-0 or 4-0 is
  level at any strength.

The old rule measured records against the champion's Wilson lower bound and
subtracted a margin sized on one proportion from another. Ekko (53.7% at mid)
took +3.3 points from one 7-1 record over eight games while his other three
records (8-13) counted nothing, and a 2-0 lane record moved Cassiopeia from
fifth to fourth (both measured 2026-09-24).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

# The prior's weight in games, by the kind of record. Lane: the careful end of
# the measured 24 to 146. Team and ally: large enough that a hundred-game
# record counts for a sixth, because no repeatable effect was found at all;
# the draft shows those records without scoring them.
LANE_STRENGTH = 100.0
TEAM_STRENGTH = 500.0
ALLY_STRENGTH = 500.0

# A 90% posterior on one side before a record is called either way.
CALL_Z = 1.28

# The variance term uses the champion's own rate; kept off 0 and 1 so a
# thin champion at 100% does not make every record infinitely significant.
_RATE_FLOOR = 0.02
_RATE_CEILING = 0.98

Call = Literal["favoured", "unfavoured", "level"]


@dataclass(frozen=True, slots=True)
class RecordPart:
    """One patch of a record, and the champion's own rate on that patch."""

    wins: int
    games: int
    own_rate: float


@dataclass(frozen=True, slots=True)
class RecordRead:
    games: int
    wins: int
    # The champion's own rate over the same games, the record's reference.
    own_rate: float
    lift: float
    z: float
    call: Call


def read_records(parts: Sequence[RecordPart], strength: float) -> RecordRead:
    """The posterior reading of a record over one or more patches.

    Each patch is centred on the champion's own rate on that patch, so a
    champion buffed from 48% to 53% between patches does not invent a
    deviation out of the buff when two patches are pooled.
    """
    games = sum(p.games for p in parts)
    wins = sum(p.wins for p in parts)
    if games <= 0:
        return RecordRead(0, 0, 0.0, 0.0, 0.0, "level")
    excess = sum(p.wins - p.games * p.own_rate for p in parts)
    own = sum(p.games * p.own_rate for p in parts) / games
    spread = min(_RATE_CEILING, max(_RATE_FLOOR, own))
    lift = excess / (games + strength)
    z = excess / math.sqrt(spread * (1 - spread) * (games + strength))
    call: Call = "favoured" if z >= CALL_Z else "unfavoured" if z <= -CALL_Z else "level"
    return RecordRead(games=games, wins=wins, own_rate=own, lift=lift, z=z, call=call)


__all__ = [
    "ALLY_STRENGTH",
    "CALL_Z",
    "LANE_STRENGTH",
    "TEAM_STRENGTH",
    "Call",
    "RecordPart",
    "RecordRead",
    "read_records",
]
