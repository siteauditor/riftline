"""Match timelines: the laning phase score, skill order, and true build paths.

A timeline is the per-minute record of a match. It is the only source for the
three things the match payload cannot tell us: how the laning phase went, which
order abilities were levelled, and which order items were actually bought.

**The storage decision is the interesting one, and it runs opposite to matches.**
A match payload is 83 KB and we keep it whole, because re-fetching is the
expensive part. A timeline is 1.02 MB, fourteen times larger, and keeping those
whole would take the database from 179 MB to 2 GB now and 117 GB at a hundred
thousand matches. So each timeline is reduced to a small record of what the
features read (about 13 KB since version 2 added the game state, measured over
1,689 stored timelines), and the payload is kept beside it gzipped, measured at
81 KB for a 12.6x saving. That keeps the insurance without the bill.
"""

from __future__ import annotations

import asyncio
import gzip
import json
import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any, NamedTuple

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Match, MatchParticipant, MatchTimeline
from app.riot.client import RiotClient
from app.riot.errors import RiotApiError, RiotNotFound
from app.riot.routing import Regional, resolve_platform

log = logging.getLogger(__name__)

# Minutes we snapshot. 14 is the one that matters -- it is where both op.gg and
# itero measure the laning phase -- but the others make early/late splits and a
# gold-difference graph possible later without another fetch.
CHECKPOINTS: tuple[int, ...] = (5, 10, 14, 20, 25)
LANING_MINUTE = 14

# Below this combined CS, the pair does not farm and a CS share measures nothing
# but noise. Supports sit here; it is why their score blends two inputs, not three.
CS_FLOOR = 40

GZIP_LEVEL = 9

# How many timelines to have in flight. The limiter paces the sends; this bounds
# memory, which matters more here than for matches because each response is ~1 MB.
FETCH_CONCURRENCY = 4

# Bumped when `extract` gains or changes a key. `scripts.ingest reextract`
# rebuilds older rows from `raw_gz`, so a new feature never costs a refetch.
# 2: `tf` and `ev`, the game state the win-chance model and the death review
# read, and towers credited to the team that took them.
EXTRACT_VERSION = 2

# The two sides of Summoner's Rift. Riot numbers participants 1 to 5 on blue
# (team 100) and 6 to 10 on red in every 5v5 queue. `extract` reads only the
# timeline, which carries no team ids, so it relies on that numbering. Arena
# breaks it, and nothing that reads `tf` or `ev` runs for Arena.
BLUE, RED = 100, 200

# The state events kept in `ev`, one short word each.
KILL, DRAGON, ELDER, GRUBS, HERALD, BARON, ATAKHAN = (
    "kill", "dragon", "elder", "grubs", "herald", "baron", "atakhan",
)
TOWER, INHIBITOR, PLATE = "tower", "inhib", "plate"
EPIC_MONSTERS = (DRAGON, ELDER, GRUBS, HERALD, BARON, ATAKHAN)
MONSTER_KINDS = {
    "DRAGON": DRAGON,
    "HORDE": GRUBS,
    "RIFTHERALD": HERALD,
    "BARON_NASHOR": BARON,
    "ATAKHAN": ATAKHAN,
}


class Laning(NamedTuple):
    """One player's laning phase against their opposite number."""

    score: float          # 0..1 share of the pair's resources; 0.48 renders "48 : 52"
    opponent_index: int
    gold: int
    xp: int
    cs: int
    gold_diff: int
    xp_diff: int
    cs_diff: int
    inputs: int           # how many of gold/xp/cs went into the blend


@dataclass(slots=True)
class Lane:
    """Where a participant stood, as far as laning is concerned."""

    index: int
    team_position: str | None
    team_id: int


# ---------------------------------------------------------------- extraction


def extract(payload: dict, duration_seconds: int) -> dict:
    """Reduce a ~1 MB timeline to the few KB the features actually read.

    Pure: no session, no client, no clock. Every parsing rule below is therefore
    testable against a hand-written payload, which is the point -- the rules are
    where the bugs live, not the plumbing.
    """
    info = payload.get("info") or {}
    frames = info.get("frames") or []
    if not frames:
        return {
            "cp": {}, "skills": {}, "buys": {}, "buy_times": {}, "obj": [],
            "tf": [], "ev": [], "v": EXTRACT_VERSION,
            "frames": 0, "laning_minute": None,
        }

    last_minute = min(len(frames) - 1, max(0, duration_seconds // 60 - 1))

    checkpoints: dict[str, dict[str, list[int]]] = {}
    for minute in CHECKPOINTS:
        if minute > last_minute:
            continue
        checkpoints[str(minute)] = {
            pid: [
                int(pf.get("totalGold") or 0),
                int(pf.get("xp") or 0),
                int(pf.get("minionsKilled") or 0) + int(pf.get("jungleMinionsKilled") or 0),
                int(pf.get("level") or 0),
            ]
            for pid, pf in (frames[minute].get("participantFrames") or {}).items()
        }

    skills, purchases, purchase_times, objectives = _replay_events(frames)

    return {
        "cp": checkpoints,
        "skills": skills,
        "buys": purchases,
        # Seconds into the game, one per entry in "buys" and in the same order.
        "buy_times": purchase_times,
        "obj": objectives,
        # Per frame: [ms, blue gold, red gold, blue levels, red levels, blue cs,
        # red cs]. Team totals, which is all the win-chance model reads.
        "tf": team_frames(frames),
        # Every event that moves the game state, in order. See `state_events`.
        "ev": state_events(frames),
        "v": EXTRACT_VERSION,
        "frames": len(frames),
        # Short games clamp below 14. Recording which minute was used beats
        # implying a 14-minute measurement we never took.
        "laning_minute": min(LANING_MINUTE, last_minute) if last_minute >= 1 else None,
    }


def _replay_events(frames: list[dict]) -> tuple[dict, dict, dict, list]:
    """Walk the event stream into skill order, purchase order and objectives.

    ``ITEM_UNDO`` is the reason this is a replay rather than a filter. A single
    game contained thirteen of them, and an undo cancels *the purchase of a
    specific item*, not simply the most recent one, so the naive read is wrong.

    ``ITEM_SOLD`` is deliberately **not** replayed. Selling an item does not mean
    it was never built, and a build path that hides the Doran's you sold at forty
    minutes is describing a game nobody played.

    Each purchase keeps its time beside it, and an undo removes both, so the two
    lists stay the same length and in step: the item guide reads "when was this
    finished" from them.
    """
    skills: dict[str, list[int]] = {}
    purchases: dict[str, list[int]] = {}
    purchase_times: dict[str, list[int]] = {}
    objectives: list[list[Any]] = []

    for frame in frames:
        for event in frame.get("events") or []:
            kind = event.get("type")
            actor = event.get("participantId")

            if kind == "SKILL_LEVEL_UP" and event.get("levelUpType") == "NORMAL":
                if actor:
                    skills.setdefault(str(actor), []).append(int(event.get("skillSlot") or 0))

            elif kind == "ITEM_PURCHASED":
                if actor and event.get("itemId"):
                    purchases.setdefault(str(actor), []).append(int(event["itemId"]))
                    purchase_times.setdefault(str(actor), []).append(
                        int(event.get("timestamp") or 0) // 1000
                    )

            elif kind == "ITEM_UNDO":
                bought = event.get("beforeId")
                bucket = purchases.get(str(actor)) if actor else None
                if bucket and bought:
                    times = purchase_times[str(actor)]
                    # Remove the most recent purchase *of that item*.
                    for position in range(len(bucket) - 1, -1, -1):
                        if bucket[position] == bought:
                            del bucket[position]
                            del times[position]
                            break

            elif kind == "ELITE_MONSTER_KILL":
                objectives.append([
                    int(event.get("timestamp") or 0) // 1000,
                    "monster",
                    event.get("monsterType"),
                    event.get("killerTeamId"),
                ])

            elif kind == "BUILDING_KILL":
                objectives.append([
                    int(event.get("timestamp") or 0) // 1000,
                    "building",
                    event.get("buildingType"),
                    _taker(event),
                ])

    return skills, purchases, purchase_times, objectives


def _side(participant_id: Any) -> int | None:
    """Blue or red for a participant id, or None for 0 (a turret or minion)."""
    try:
        number = int(participant_id or 0)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return BLUE if number <= 5 else RED


def _taker(event: dict) -> int | None:
    """The team that took a building or plate.

    ``teamId`` on these events is the team that *lost* it. Checked on a stored
    game: participant 4, on blue, killed a tower whose event says ``teamId:
    200``, at red's bottom outer position. Reading it as the killer credited
    every tower to the side that lost it.
    """
    owner = event.get("teamId")
    if owner in (BLUE, RED):
        return RED if owner == BLUE else BLUE
    return _side(event.get("killerId"))


def team_frames(frames: list[dict]) -> list[list[int]]:
    """Team gold, levels and CS at every frame, blue then red."""
    rows: list[list[int]] = []
    for frame in frames:
        totals = {BLUE: [0, 0, 0], RED: [0, 0, 0]}
        for pid, pf in (frame.get("participantFrames") or {}).items():
            side = _side(pid)
            if side is None:
                continue
            totals[side][0] += int(pf.get("totalGold") or 0)
            totals[side][1] += int(pf.get("level") or 0)
            totals[side][2] += int(pf.get("minionsKilled") or 0) + int(
                pf.get("jungleMinionsKilled") or 0
            )
        rows.append([
            int(frame.get("timestamp") or 0),
            totals[BLUE][0], totals[RED][0],
            totals[BLUE][1], totals[RED][1],
            totals[BLUE][2], totals[RED][2],
        ])
    return rows


def state_events(frames: list[dict]) -> list[list[Any]]:
    """The events that change who is winning, one compact row each.

    ``[ms, kind, team, killer, victim, assists, x, y, gold]``, where ``team`` is
    the team that gained. A kill with no killer (a turret or minions finished
    them) goes to the victim's opponents. ``assists`` is Riot's list as sent:
    on an epic monster it can name players from both teams, which is how a
    contested objective is recognised. ``gold`` is a kill's bounty plus its
    shutdown bounty, the gold the event itself moved.
    """
    rows: list[list[Any]] = []
    for frame in frames:
        for event in frame.get("events") or []:
            kind = event.get("type")
            ms = int(event.get("timestamp") or 0)
            position = event.get("position") or {}
            x, y = int(position.get("x") or 0), int(position.get("y") or 0)
            assists = [int(a) for a in (event.get("assistingParticipantIds") or [])]
            killer = int(event.get("killerId") or 0)

            if kind == "CHAMPION_KILL":
                victim = int(event.get("victimId") or 0)
                victim_side = _side(victim)
                if victim_side is None:
                    continue
                gold = int(event.get("bounty") or 0) + int(event.get("shutdownBounty") or 0)
                team = RED if victim_side == BLUE else BLUE
                rows.append([ms, KILL, team, killer, victim, assists, x, y, gold])

            elif kind == "ELITE_MONSTER_KILL":
                monster = MONSTER_KINDS.get(event.get("monsterType") or "")
                if monster is None:
                    continue
                if monster == DRAGON and event.get("monsterSubType") == "ELDER_DRAGON":
                    monster = ELDER
                team = event.get("killerTeamId")
                if team not in (BLUE, RED):
                    team = _side(killer)
                if team is None:
                    continue
                rows.append([ms, monster, team, killer, 0, assists, x, y, 0])

            elif kind == "BUILDING_KILL":
                building = event.get("buildingType")
                what = (
                    TOWER if building == "TOWER_BUILDING"
                    else INHIBITOR if building == "INHIBITOR_BUILDING"
                    else None
                )
                team = _taker(event)
                if what is None or team is None:
                    continue
                rows.append([ms, what, team, killer, 0, assists, x, y, 0])

            elif kind == "TURRET_PLATE_DESTROYED":
                team = _taker(event)
                if team is None:
                    continue
                rows.append([ms, PLATE, team, killer, 0, [], x, y, 0])
    return rows


# ------------------------------------------------------------- laning phase


def laning_scores(extracted: dict, lanes: Sequence[Lane]) -> dict[int, Laning]:
    """Score each lane as a share of the pair's resources at the laning mark.

    Two players who share a ``team_position`` on opposite teams were, by
    matchmaking's own assignment, in the same lane. Anyone without an opposite
    number gets nothing at all rather than a made-up number: that is ARAM, Arena,
    and the occasional game where the roles do not pair.
    """
    minute = extracted.get("laning_minute")
    frame = (extracted.get("cp") or {}).get(str(minute)) if minute is not None else None
    if not frame:
        return {}

    by_position: dict[str, list[Lane]] = {}
    for lane in lanes:
        if lane.team_position:
            by_position.setdefault(lane.team_position, []).append(lane)

    results: dict[int, Laning] = {}
    for players in by_position.values():
        if len(players) != 2 or players[0].team_id == players[1].team_id:
            continue
        for me, them in ((players[0], players[1]), (players[1], players[0])):
            mine, theirs = frame.get(str(me.index)), frame.get(str(them.index))
            if not mine or not theirs:
                continue
            my_gold, my_xp, my_cs = mine[0], mine[1], mine[2]
            their_gold, their_xp, their_cs = theirs[0], theirs[1], theirs[2]

            shares = [
                my_gold / max(1, my_gold + their_gold),
                my_xp / max(1, my_xp + their_xp),
            ]
            if my_cs + their_cs >= CS_FLOOR:
                shares.append(my_cs / max(1, my_cs + their_cs))

            results[me.index] = Laning(
                score=sum(shares) / len(shares),
                opponent_index=them.index,
                gold=my_gold,
                xp=my_xp,
                cs=my_cs,
                gold_diff=my_gold - their_gold,
                xp_diff=my_xp - their_xp,
                cs_diff=my_cs - their_cs,
                inputs=len(shares),
            )
    return results


def skill_priority(order: Iterable[int] | None) -> list[int] | None:
    """Which abilities were maxed, in the order they were maxed.

    Riot's ultimate is slot 4 and is levelled on a fixed schedule, so it carries
    no choice and is left out. What remains is the real decision: Q first, then E,
    then W.
    """
    if not order:
        return None
    counts: dict[int, int] = {}
    maxed: list[int] = []
    for slot in order:
        if slot == 4:
            continue
        counts[slot] = counts.get(slot, 0) + 1
        if counts[slot] == 5 and slot not in maxed:
            maxed.append(slot)
    # A game can end before anything is maxed; fall back to what was levelled most.
    if not maxed:
        maxed = [s for s, _ in sorted(counts.items(), key=lambda kv: -kv[1])]
    return maxed or None


# ------------------------------------------------------------- purchase times


@dataclass(slots=True)
class BuyTimeStats:
    matches: int = 0
    filled: int = 0
    # Rows whose replayed purchases no longer match the stored order. Left as
    # they are and counted: a time beside the wrong item is worse than none.
    mismatched: int = 0


async def backfill_buy_times(session: AsyncSession, *, batch: int = 100) -> BuyTimeStats:
    """Fill `build_times` for timelines stored before the column existed.

    Reads the raw events kept in `match_timelines.raw_gz`, so it costs no Riot
    call. The cursor is the absence of the data, rows with a purchase order and
    no times, and every match is visited once per run: a mismatched row stays
    empty, and asking again would hand back the same match for ever.
    """
    stats = BuyTimeStats()
    attempted: set[str] = set()
    while True:
        stmt = (
            select(MatchParticipant.match_id)
            .where(
                MatchParticipant.build_order.is_not(None),
                MatchParticipant.build_times.is_(None),
            )
            .distinct()
            .limit(batch)
        )
        if attempted:
            stmt = stmt.where(MatchParticipant.match_id.not_in(attempted))
        ids = list((await session.execute(stmt)).scalars())
        if not ids:
            break
        attempted.update(ids)

        timelines = {
            t.match_id: t
            for t in (
                await session.execute(
                    select(MatchTimeline).where(MatchTimeline.match_id.in_(ids))
                )
            ).scalars()
        }
        rows = (
            await session.execute(
                select(MatchParticipant).where(
                    MatchParticipant.match_id.in_(ids),
                    MatchParticipant.build_order.is_not(None),
                    MatchParticipant.build_times.is_(None),
                )
            )
        ).scalars()
        by_match: dict[str, list[MatchParticipant]] = {}
        for row in rows:
            by_match.setdefault(row.match_id, []).append(row)

        for match_id, players in by_match.items():
            timeline = timelines.get(match_id)
            if timeline is None or not timeline.raw_gz:
                continue
            payload = json.loads(gzip.decompress(timeline.raw_gz))
            frames = (payload.get("info") or {}).get("frames") or []
            _, purchases, times, _ = _replay_events(frames)
            stats.matches += 1
            for row in players:
                key = str(row.participant_index)
                if purchases.get(key) == row.build_order:
                    row.build_times = times.get(key)
                    stats.filled += 1
                else:
                    stats.mismatched += 1
        await session.commit()
        log.info("purchase times: %d players filled so far", stats.filled)
    return stats


# ------------------------------------------------------------ re-extraction


@dataclass(slots=True)
class ReextractStats:
    rows: int = 0
    # Rows whose stored payload has no frames. Left at their old version and
    # counted, never retried within the run.
    skipped: int = 0


async def backfill_extracts(session: AsyncSession, *, batch: int = 50) -> ReextractStats:
    """Rebuild `extracted` from `raw_gz` for rows older than `EXTRACT_VERSION`.

    Reads the raw timelines already on disk, so it costs no Riot call, and it
    is why a feature that needs a new field from a timeline never needs a
    refetch. Only `extracted` is rewritten: the columns `_apply_to_participants`
    fills read keys that no version has changed.
    """
    stats = ReextractStats()
    version = func.json_extract(MatchTimeline.extracted, "$.v")
    last = ""
    while True:
        rows = (
            await session.execute(
                select(MatchTimeline, Match.game_duration)
                .join(Match, Match.match_id == MatchTimeline.match_id)
                .where(
                    MatchTimeline.match_id > last,
                    MatchTimeline.raw_gz.is_not(None),
                    or_(version.is_(None), version < EXTRACT_VERSION),
                )
                .order_by(MatchTimeline.match_id)
                .limit(batch)
            )
        ).all()
        if not rows:
            break
        for timeline, duration in rows:
            last = timeline.match_id
            payload = json.loads(gzip.decompress(timeline.raw_gz))
            extracted = extract(payload, duration or 0)
            if not extracted.get("frames"):
                stats.skipped += 1
                continue
            timeline.extracted = extracted
            stats.rows += 1
        await session.commit()
        log.info("re-extracted %d timelines so far", stats.rows)
    return stats


# -------------------------------------------------------------------- service


class TimelineService:
    """Fetches, reduces and stores timelines, and writes the derived columns."""

    def __init__(self, session: AsyncSession, client: RiotClient, settings) -> None:
        self.session = session
        self.client = client
        self.settings = settings

    async def known_ids(self, match_ids: Sequence[str]) -> set[str]:
        if not match_ids:
            return set()
        stmt = select(MatchTimeline.match_id).where(
            MatchTimeline.match_id.in_(list(match_ids))
        )
        return set((await self.session.execute(stmt)).scalars())

    async def pending(self, *, limit: int = 100, patch: str | None = None) -> list[Match]:
        """Stored matches with no timeline yet, newest first."""
        stmt = (
            select(Match)
            .outerjoin(MatchTimeline, MatchTimeline.match_id == Match.match_id)
            .where(MatchTimeline.match_id.is_(None), Match.is_remake.is_(False))
            .order_by(Match.game_creation.desc())
            .limit(limit)
        )
        if patch:
            stmt = stmt.where(Match.patch == patch)
        return list((await self.session.execute(stmt)).scalars())

    async def ensure_timelines(
        self, matches: Sequence[Match], regional: Regional | str | None = None
    ) -> int:
        """Fetch and store the timelines we do not hold. Returns how many landed."""
        wanted = [m for m in matches if m.match_id]
        if not wanted:
            return 0
        have = await self.known_ids([m.match_id for m in wanted])
        missing = [m for m in wanted if m.match_id not in have]
        if not missing:
            return 0

        semaphore = asyncio.Semaphore(FETCH_CONCURRENCY)

        async def fetch(match: Match) -> tuple[Match, dict | None]:
            route = regional or resolve_platform(match.platform_id or "euw1").regional
            async with semaphore:
                try:
                    return match, await self.client.match_timeline(match.match_id, route)
                except RiotNotFound:
                    # Retention window: the match outlived its timeline.
                    log.info("timeline %s no longer available", match.match_id)
                    return match, None
                except RiotApiError as exc:
                    log.warning("timeline %s failed: %s", match.match_id, exc)
                    return match, None

        stored = 0
        for match, payload in await asyncio.gather(*(fetch(m) for m in missing)):
            if payload and await self._store(match, payload):
                stored += 1
        try:
            await self.session.commit()
        except IntegrityError:
            # Another worker stored some of these first. Timelines are immutable,
            # so whoever won wrote the same bytes.
            await self.session.rollback()
            log.info("timeline write race; retrying individually")
            stored = await self._store_individually(missing, regional)
        return stored

    async def ensure_one(self, match: Match) -> MatchTimeline | None:
        """This match's timeline, fetched now if we do not hold it, and stored.

        For a game's story, opened by someone who is waiting: one Riot call,
        once per game, under the request's wait budget. A busy key surfaces as
        `RiotRateLimited` for the caller to turn into "try again"; a match that
        outlived its timeline is None.
        """
        existing = await self.session.get(MatchTimeline, match.match_id)
        if existing is not None:
            return existing
        route = resolve_platform(match.platform_id or "euw1").regional
        try:
            payload = await self.client.match_timeline(match.match_id, route)
        except RiotNotFound:
            return None
        if not await self._store(match, payload):
            return None
        try:
            await self.session.commit()
        except IntegrityError:
            # Another request stored it first. Timelines are immutable, so
            # theirs is the same as ours.
            await self.session.rollback()
        return await self.session.get(MatchTimeline, match.match_id)

    async def _store_individually(
        self, matches: Sequence[Match], regional: Regional | str | None
    ) -> int:
        stored = 0
        for match in matches:
            if await self.known_ids([match.match_id]):
                continue
            route = regional or resolve_platform(match.platform_id or "euw1").regional
            try:
                payload = await self.client.match_timeline(match.match_id, route)
            except RiotApiError:
                continue
            if not await self._store(match, payload):
                continue
            try:
                await self.session.commit()
                stored += 1
            except IntegrityError:
                await self.session.rollback()
        return stored

    async def _store(self, match: Match, payload: dict) -> bool:
        """Reduce, compress, and write both the timeline row and the derived columns."""
        extracted = extract(payload, match.game_duration or 0)
        if not extracted.get("frames"):
            return False

        # Re-serialised compactly before compressing: whitespace costs nothing to
        # drop and the compressor has less to chew on.
        blob = gzip.compress(
            json.dumps(payload, separators=(",", ":")).encode("utf-8"), GZIP_LEVEL
        )
        self.session.add(
            MatchTimeline(
                match_id=match.match_id,
                extracted=extracted,
                raw_gz=blob,
                frame_count=extracted["frames"],
                laning_minute=extracted.get("laning_minute"),
            )
        )
        await self._apply_to_participants(match.match_id, extracted)
        return True

    async def _apply_to_participants(self, match_id: str, extracted: dict) -> None:
        """Write the derived fields onto this match's participant rows.

        Same transaction as the timeline row, so a participant never ends up with
        half its timeline fields populated.
        """
        rows = list(
            (
                await self.session.execute(
                    select(MatchParticipant).where(MatchParticipant.match_id == match_id)
                )
            ).scalars()
        )
        if not rows:
            return

        by_index = {r.participant_index: r for r in rows}
        lanes = [Lane(r.participant_index, r.team_position, r.team_id) for r in rows]
        scores = laning_scores(extracted, lanes)

        # A game can now be scored the moment it is fetched, before its timeline
        # exists, and the Lane lead badge is judged on the gold lead at 14
        # minutes written below. Clearing the stamp sends the lobby back through
        # the next scoring pass: the scores come out the same, the badges now
        # include the lane.
        if scores and any(r.performance_scored_at is not None for r in rows):
            for row in rows:
                row.performance_scored_at = None

        skills = extracted.get("skills") or {}
        buys = extracted.get("buys") or {}
        buy_times = extracted.get("buy_times") or {}

        for row in rows:
            key = str(row.participant_index)
            row.skill_order = skills.get(key)
            row.build_order = buys.get(key)
            row.build_times = buy_times.get(key)

            lane = scores.get(row.participant_index)
            if lane is None:
                continue
            opponent = by_index.get(lane.opponent_index)
            row.laning_score = lane.score
            row.opponent_champion_id = opponent.champion_id if opponent else None
            row.gold_at_14, row.xp_at_14, row.cs_at_14 = lane.gold, lane.xp, lane.cs
            row.gold_diff_14 = lane.gold_diff
            row.xp_diff_14 = lane.xp_diff
            row.cs_diff_14 = lane.cs_diff
