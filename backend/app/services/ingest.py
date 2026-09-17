"""Match ingestion crawler.

Tier lists and draft matchups are aggregates, and aggregates need a corpus. This
walks the ladder to collect one.

The method is a snowball. Seed from a ranked ladder page to get PUUIDs, pull
each player's recent ranked matches, and every match fetched yields ten more
PUUIDs to walk. The frontier is persisted, so a crawl that stops -- key expiry,
a reboot, Ctrl-C -- resumes instead of starting over.

**What a development key can actually do.** The budget is 100 requests per two
minutes, and one match costs one request, so the ceiling is about 3,000 matches
per hour and the key expires after 24. That is enough for a credible sample on
popular champions and not enough for per-matchup tables, which need tens of
thousands of games per patch. The code does not change when you get a
production key; only ``APP_RATE_LIMITS`` does.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    IngestCursor,
    Match,
    MatchParticipant,
    MatchTimeline,
    utcnow,
)
from app.riot.client import RiotClient
from app.riot.errors import RiotApiError, RiotRateLimited
from app.riot.routing import UnknownPlatform, resolve_platform
from app.services.matches import MatchService
from app.services.ranks import RankCache
from app.services.scores import ScoreService
from app.services.timelines import TimelineService

log = logging.getLogger(__name__)

APEX_TIERS = ("challenger", "grandmaster", "master")
STANDARD_TIERS = (
    "DIAMOND", "EMERALD", "PLATINUM", "GOLD", "SILVER", "BRONZE", "IRON",
)
DIVISIONS = ("I", "II", "III", "IV")


@dataclass
class CrawlStats:
    matches_new: int = 0
    matches_seen: int = 0
    players_walked: int = 0
    errors: int = 0
    started: float = field(default_factory=time.monotonic)

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.started

    @property
    def rate_per_hour(self) -> float:
        return self.matches_new / self.elapsed * 3600 if self.elapsed > 0 else 0.0

    def line(self) -> str:
        return (
            f"{self.matches_new} new / {self.matches_seen} seen | "
            f"{self.players_walked} players | {self.errors} errors | "
            f"{self.elapsed / 60:.1f} min | ~{self.rate_per_hour:.0f} matches/h"
        )


class Ingestor:
    def __init__(
        self,
        session: AsyncSession,
        client: RiotClient,
        settings,
        *,
        platform: str = "euw1",
        queue: int = 420,
        seed_tier: str = "challenger",
    ) -> None:
        self.session = session
        self.client = client
        self.settings = settings
        self.platform = resolve_platform(platform)
        self.queue = queue
        self.seed_tier = seed_tier.upper()
        # Stamps every match this crawl stores with the ladder it came from, so
        # aggregates can be sliced by bracket. Provenance, not a measured rank.
        self.matches = MatchService(
            session, client, settings, source_bracket=self.seed_tier
        )
        self.stats = CrawlStats()

    # ------------------------------------------------------------- frontier

    @property
    def _cursor_key(self) -> str:
        return f"frontier:{self.platform.id}:{self.queue}"

    async def _load_frontier(self) -> tuple[list[str], set[str]]:
        row = await self.session.get(IngestCursor, self._cursor_key)
        if row and row.value:
            try:
                data = json.loads(row.value)
                return list(data.get("queue", [])), set(data.get("done", []))
            except (ValueError, AttributeError):
                log.warning("frontier cursor corrupt; starting fresh")
        return [], set()

    async def _save_frontier(self, frontier: list[str], done: set[str]) -> None:
        row = await self.session.get(IngestCursor, self._cursor_key)
        payload = json.dumps(
            {
                # Cap what we persist: the frontier grows far faster than we can
                # drain it, and an unbounded cursor row is its own problem.
                "queue": frontier[:5000],
                "done": list(done)[-20_000:],
            }
        )
        if row is None:
            self.session.add(IngestCursor(key=self._cursor_key, value=payload))
        else:
            row.value = payload
        await self.session.commit()

    # ----------------------------------------------------------------- seed

    async def seed_from_ladder(self, *, tier: str = "challenger", pages: int = 1) -> list[str]:
        """Collect PUUIDs from a ranked ladder.

        Apex tiers come back as one league object; everything else is paged.
        """
        puuids: list[str] = []
        queue_name = "RANKED_SOLO_5x5" if self.queue == 420 else "RANKED_FLEX_SR"

        if tier.lower() in APEX_TIERS:
            league = await self.client.apex_league(queue_name, tier, self.platform)
            for entry in league.get("entries", []):
                if entry.get("puuid"):
                    puuids.append(entry["puuid"])
        else:
            for division in DIVISIONS:
                for page in range(1, pages + 1):
                    entries = await self.client.league_entries(
                        queue_name, tier, division, self.platform, page=page
                    )
                    if not entries:
                        break
                    puuids.extend(e["puuid"] for e in entries if e.get("puuid"))

        log.info("seeded %d players from %s %s", len(puuids), self.platform.label, tier)
        return puuids

    # ---------------------------------------------------------------- crawl

    async def crawl(
        self,
        *,
        target_matches: int = 500,
        matches_per_player: int = 10,
        seed_tier: str | None = None,
        progress_every: int = 25,
    ) -> CrawlStats:
        """Walk the frontier until ``target_matches`` new matches are stored."""
        frontier, done = await self._load_frontier()

        if not frontier:
            seeds = await self.seed_from_ladder(tier=seed_tier or self.seed_tier)
            frontier = [p for p in seeds if p not in done]

        if not frontier:
            log.warning("nothing to crawl: ladder returned no players")
            return self.stats

        last_report = 0
        while frontier and self.stats.matches_new < target_matches:
            puuid = frontier.pop(0)
            if puuid in done:
                continue
            done.add(puuid)
            self.stats.players_walked += 1

            try:
                new_puuids = await self._walk_player(puuid, matches_per_player)
            except RiotRateLimited as exc:
                # The limiter already waited; a 429 that still escapes means the
                # key is in trouble, so back off hard rather than hammering.
                log.warning("rate limited during crawl; pausing %.0fs", exc.retry_after)
                frontier.insert(0, puuid)
                done.discard(puuid)
                await asyncio.sleep(max(5.0, exc.retry_after))
                continue
            except RiotApiError as exc:
                self.stats.errors += 1
                log.warning("player %s failed: %s", puuid[:12], exc)
                continue

            for candidate in new_puuids:
                if candidate not in done and len(frontier) < 10_000:
                    frontier.append(candidate)

            if self.stats.matches_new - last_report >= progress_every:
                last_report = self.stats.matches_new
                log.info("crawl: %s", self.stats.line())
                await self._save_frontier(frontier, done)

        await self._save_frontier(frontier, done)
        log.info("crawl finished: %s", self.stats.line())
        return self.stats

    async def _walk_player(self, puuid: str, count: int) -> set[str]:
        """Fetch one player's recent matches; return the PUUIDs they played with."""
        ids = await self.client.match_ids(
            puuid, self.platform.regional, count=count, queue=self.queue
        )
        if not ids:
            return set()

        known = await self.matches.known_ids(ids)
        self.stats.matches_seen += len(known)
        missing = [m for m in ids if m not in known]
        if missing:
            await self.matches.ensure_matches(missing, self.platform.regional)
            # Count what actually landed by re-checking just these ids. The
            # obvious version -- COUNT(*) on `matches` before and after -- is a
            # full scan twice per player, so the crawler would get slower the
            # more it succeeded. This is an indexed lookup of at most `count`
            # rows, and stays flat as the corpus grows.
            self.stats.matches_new += len(await self.matches.known_ids(missing))

        rows = await self.session.execute(
            select(MatchParticipant.puuid).where(MatchParticipant.match_id.in_(ids))
        )
        return set(rows.scalars())


async def corpus_summary(session: AsyncSession) -> dict:
    """What the database actually holds, for the CLI and the meta endpoint."""
    total = (await session.execute(select(func.count(Match.match_id)))).scalar() or 0
    by_patch = (
        await session.execute(
            select(Match.patch, Match.queue_id, func.count(Match.match_id))
            .where(Match.is_remake.is_(False))
            .group_by(Match.patch, Match.queue_id)
            .order_by(func.count(Match.match_id).desc())
        )
    ).all()
    participants = (
        await session.execute(select(func.count(MatchParticipant.id)))
    ).scalar() or 0
    # Timeline coverage belongs here rather than in the caller: "how much of the
    # corpus can answer a laning question" is the thing you check before
    # aggregating, and both the CLI and the meta endpoint want it.
    eligible = (
        await session.execute(
            select(func.count(Match.match_id)).where(Match.is_remake.is_(False))
        )
    ).scalar() or 0
    with_timeline = (
        await session.execute(select(func.count(MatchTimeline.match_id)))
    ).scalar() or 0
    # Score coverage reads the same way and for the same reason: before trusting
    # a placement you want to know how much of the corpus carries one.
    scores = await ScoreService(session).coverage()
    return {
        "matches": total,
        "participants": participants,
        "timelines": with_timeline,
        "timelines_outstanding": max(0, eligible - with_timeline),
        "scores": scores,
        "slices": [
            {"patch": p, "queue_id": q, "matches": n} for p, q, n in by_patch
        ],
    }


class TimelineBackfill:
    """Fetch timelines for matches we already hold.

    Separate from the crawler on purpose. The crawler spends its budget
    discovering new matches; this spends it deepening the ones we have, and the
    two compete for the same key. Keeping them apart means you can choose.

    Resumable in the simplest way available: "which matches lack a timeline" is
    itself the cursor, so an interrupted run just picks up the remainder. No
    bookmark to corrupt.
    """

    def __init__(self, session: AsyncSession, client: RiotClient, settings) -> None:
        self.session = session
        self.timelines = TimelineService(session, client, settings)
        self.stats = CrawlStats()

    async def remaining(self, patch: str | None = None) -> int:
        from app.db.models import MatchTimeline

        stmt = (
            select(func.count(Match.match_id))
            .outerjoin(MatchTimeline, MatchTimeline.match_id == Match.match_id)
            .where(MatchTimeline.match_id.is_(None), Match.is_remake.is_(False))
        )
        if patch:
            stmt = stmt.where(Match.patch == patch)
        return (await self.session.execute(stmt)).scalar() or 0

    async def run(
        self,
        *,
        target: int = 500,
        batch: int = 20,
        patch: str | None = None,
        progress_every: int = 50,
    ) -> CrawlStats:
        log.info("timelines outstanding: %d", await self.remaining(patch))
        last_report = 0

        while self.stats.matches_new < target:
            pending = await self.timelines.pending(limit=batch, patch=patch)
            if not pending:
                log.info("no matches left without a timeline")
                break

            try:
                stored = await self.timelines.ensure_timelines(pending)
            except RiotRateLimited as exc:
                log.warning("rate limited; pausing %.0fs", exc.retry_after)
                await asyncio.sleep(max(5.0, exc.retry_after))
                continue
            except RiotApiError as exc:
                self.stats.errors += 1
                log.warning("timeline batch failed: %s", exc)
                continue

            if stored == 0:
                # Every match in this batch is unfetchable (aged out of Riot's
                # retention). Without this the same batch would be retried for
                # ever, because `pending` would keep handing it back.
                log.warning("batch of %d yielded no timelines; stopping", len(pending))
                break

            self.stats.matches_new += stored
            self.stats.players_walked += len(pending)
            if self.stats.matches_new - last_report >= progress_every:
                last_report = self.stats.matches_new
                log.info("timelines: %s", self.stats.line())

        log.info("timeline backfill finished: %s", self.stats.line())
        return self.stats


class LobbyRankBackfill:
    """Measure the average rank of the players in matches we already hold.

    **This is a late measurement, and the distinction is the whole design.**
    ``Match.source_bracket`` records which ladder the crawler was seeded from,
    which is provenance and not a claim about anybody. This records the mean
    rank of the ten players who actually played, which is a measurement -- but
    of their rank *today*, because Riot exposes no historical rank anywhere. For
    a game from three months ago that gap can be a whole tier, so the
    measurement date is stored beside the number and travels with it into the
    UI.

    The cost is per *player*, not per match, which is what makes it affordable.
    The corpus holds 1,695 matches but only 2,830 distinct players, a 6.0x reuse
    factor, so the naive "ten calls a match" estimate of 16,950 is really about
    2,830 and the rank cache absorbs the rest.

    Resumable the same way the timeline backfill is: "which match has no
    measurement" is itself the cursor.
    """

    def __init__(self, session: AsyncSession, client: RiotClient, settings) -> None:
        self.session = session
        self.ranks = RankCache(session, client, settings)
        self.settings = settings
        self.stats = CrawlStats()

    async def remaining(self, patch: str | None = None) -> int:
        stmt = select(func.count(Match.match_id)).where(
            Match.lobby_rank_measured_at.is_(None), Match.is_remake.is_(False)
        )
        if patch:
            stmt = stmt.where(Match.patch == patch)
        return (await self.session.execute(stmt)).scalar() or 0

    async def pending(self, *, limit: int = 20, patch: str | None = None) -> list[Match]:
        stmt = (
            select(Match)
            .where(Match.lobby_rank_measured_at.is_(None), Match.is_remake.is_(False))
            .order_by(Match.game_creation.desc())
            .limit(limit)
        )
        if patch:
            stmt = stmt.where(Match.patch == patch)
        return list((await self.session.execute(stmt)).scalars())

    async def measure(self, matches: Sequence[Match]) -> int:
        """Measure a batch, sharing one rank lookup across every match in it."""
        # Imported here rather than at module scope: `app.api.schemas` imports
        # the models, and the ingest service is loaded by scripts that have no
        # API layer to speak of.
        from app.api.schemas import RANKED_QUEUE_BY_ID
        from app.services.live import median_entry, rank_points

        if not matches:
            return 0
        match_ids = [m.match_id for m in matches]
        rows = list(
            (
                await self.session.execute(
                    select(
                        MatchParticipant.match_id,
                        MatchParticipant.puuid,
                    ).where(MatchParticipant.match_id.in_(match_ids))
                )
            ).all()
        )
        by_match: dict[str, list[str]] = {m.match_id: [] for m in matches}
        for match_id, puuid in rows:
            if puuid:
                by_match[match_id].append(puuid)

        if not any(by_match.values()):
            return 0

        # Read every scalar we need *before* the rank fetch.
        #
        # `get_many` can hit a write race and roll back, and a rollback expires
        # every object in the session, these `Match` rows included. Touching
        # `match.queue_id` afterwards then fires a lazy reload, which under
        # asyncio surfaces as MissingGreenlet from somewhere unrelated. The same
        # defence is documented on `PlayerService._commit_tolerating_race`.
        plan = [
            {
                "match": m,
                "queue_type": RANKED_QUEUE_BY_ID.get(m.queue_id, "RANKED_SOLO_5x5"),
                "platform": (m.platform_id or "euw1").lower(),
                "puuids": by_match[m.match_id],
            }
            for m in matches
        ]

        # Grouped by platform, because league-v4 is a *platform* endpoint and a
        # crawl frontier happily spans regions. Looking a KR player up on the
        # EUW host returns nothing at all, silently, and the lobby comes back
        # measured over zero players.
        by_platform: dict[str, set[str]] = {}
        for item in plan:
            by_platform.setdefault(item["platform"], set()).update(item["puuids"])

        # Pre-merge shards (PH2, TH2, ID1) still appear in old stored matches and
        # are not in PLATFORMS, so resolving one raises. Dropping the slice loses
        # those lobbies; letting it raise loses the entire run.
        for platform in list(by_platform):
            try:
                resolve_platform(platform)
            except UnknownPlatform:
                log.info("skipping retired shard %s", platform)
                by_platform.pop(platform)

        # One call per player we do not already hold, shared across every match
        # in the batch. This is where the 6x reuse factor is cashed in.
        snapshots: dict = {}
        for platform, puuids in by_platform.items():
            snapshots.update(await self.ranks.get_many(sorted(puuids), platform))

        measured = 0
        for item in plan:
            match = item["match"]
            ranked: list = []
            answered = 0
            for puuid in item["puuids"]:
                snapshot = snapshots.get(puuid)
                if snapshot is None or not snapshot.known:
                    continue
                answered += 1
                entry = next(
                    (e for e in snapshot.entries if e.queue_type == item["queue_type"]),
                    None,
                )
                if entry and entry.tier:
                    ranked.append(entry)

            if item["puuids"] and answered == 0:
                # We learned nothing about this lobby, so stamping it would
                # retire it for ever on the strength of a failure.
                #
                # This is not hypothetical. A development key expires after 24
                # hours; when it does, every league call 401s, `_fetch` catches
                # it per player and reports `known=False`, and the old code
                # stamped every match as "measured over 0 players" at 33,000
                # matches an hour while reporting zero errors. The corpus was
                # then unrecoverable without a manual UPDATE.
                continue

            match.lobby_ranked_players = len(ranked)
            # The same statistic the live view uses, from the same helper. A
            # mean over numeric_rank reports nine Gold players and one
            # Challenger as "Diamond III"; the median is a rank somebody in the
            # lobby actually holds.
            match.lobby_rank_points = (
                float(rank_points(median_entry(ranked))) if ranked else None
            )
            # Stamped even when nothing was ranked, so an all-unranked lobby is
            # not re-measured for ever. The count says what it was over.
            match.lobby_rank_measured_at = utcnow()
            measured += 1

        await self.session.commit()
        return measured

    async def run(
        self,
        *,
        target: int = 500,
        batch: int = 20,
        patch: str | None = None,
        progress_every: int = 50,
    ) -> CrawlStats:
        log.info("lobby ranks outstanding: %d", await self.remaining(patch))
        last_report = 0

        while self.stats.matches_new < target:
            pending = await self.pending(limit=batch, patch=patch)
            if not pending:
                log.info("no matches left without a lobby rank")
                break
            try:
                measured = await self.measure(pending)
            except RiotRateLimited as exc:
                log.warning("rate limited; pausing %.0fs", exc.retry_after)
                await asyncio.sleep(max(5.0, exc.retry_after))
                continue
            except RiotApiError as exc:
                self.stats.errors += 1
                log.warning("lobby rank batch failed: %s", exc)
                continue

            if measured == 0:
                # Either every match aged out of what we can answer, or the key
                # has stopped working. Both mean continuing is pointless, and
                # continuing quietly was how a dead key used to eat the corpus.
                log.warning(
                    "batch of %d produced no measurement; stopping. If this is "
                    "unexpected, check the API key is still valid.",
                    len(pending),
                )
                break

            self.stats.matches_new += measured
            self.stats.players_walked += len(pending)
            if self.stats.matches_new - last_report >= progress_every:
                last_report = self.stats.matches_new
                log.info("lobby ranks: %s", self.stats.line())

        log.info("lobby rank backfill finished: %s", self.stats.line())
        return self.stats
