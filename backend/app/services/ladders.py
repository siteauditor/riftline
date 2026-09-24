"""Ranked ladders, cached as snapshots and named from what we already hold.

Two measurements shaped this, both taken against the live API on 2026-09-17.

**A ladder page is one Riot call.** EUW Challenger is 300 entries in a single
68 KB response, 0.81 s. Grandmaster is 700, Master is 10,000, and everything
below apex is paged at 205 a time. So fetching a ladder is cheap; it is naming
one that costs.

**Names are corpus-shaped, and that is visible from the outside.** Of EUW's 300
Challenger PUUIDs we already knew 298 from ``match_participants``, because the
crawler seeded there. Grandmaster was 87%, Master 14%, Diamond I 0%, and NA
Challenger 0%. league-v4 returns no display name at all, so a ladder in a region
we never crawled really is a list of anonymous PUUIDs until somebody pays one
``account-v1`` call each to name it.

The response therefore never pretends otherwise: it reports how many rows on the
page are named, and resolves a bounded handful per request so that browsing
warms the cache instead of blocking on it. A resolved name is permanent, so the
cost of a ladder trends to zero the more it is looked at.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import IngestCursor, LadderEntry, Player, utcnow
from app.riot.client import RiotClient
from app.riot.errors import RiotApiError, RiotNotFound
from app.riot.limiter import SEARCH_RESERVE, wait_deadline
from app.riot.routing import Platform, resolve_platform
from app.services.players import claim_riot_id, normalize_riot_name
from app.services.ranks import RankCache, is_fresh

log = logging.getLogger(__name__)

APEX_TIERS = ("MASTER", "GRANDMASTER", "CHALLENGER")
STANDARD_TIERS = ("DIAMOND", "EMERALD", "PLATINUM", "GOLD", "SILVER", "BRONZE", "IRON")
DIVISIONS = ("I", "II", "III", "IV")
QUEUE_BY_ID = {420: "RANKED_SOLO_5x5", 440: "RANKED_FLEX_SR"}

# Master is ten thousand rows. Nobody pages to rank 8,000, we have a name for
# almost none of them, and storing the tail would make every refresh slow for
# a part of the ladder that is never read. The total is reported regardless, so
# the cap is visible rather than hidden.
MAX_ROWS_PER_SLICE = 1000

# A snapshot older than this is not offered as a player's position. The nightly
# job refreshes the apex ladders, so anything older means that stage stopped
# running, and last week's position would read as today's.
POSITION_MAX_AGE = timedelta(hours=48)


@dataclass(frozen=True, slots=True)
class LadderPosition:
    tier: str
    # Place within the tier's ladder, 1 = top.
    tier_position: int
    # Place on the whole region's ladder: the tier position plus everyone in
    # the tiers above. None when a higher tier's size is not known, rather than
    # a number that quietly assumes it.
    position: int | None
    platform: str
    as_of: datetime


# How many unnamed rows one page view will resolve. Bounded because
# `account_by_puuid` is one call per player and a 205-row page would otherwise
# block for four minutes on a development key.
NAME_BUDGET_PER_REQUEST = 25
NAME_CONCURRENCY = 4
# And how long it may spend doing so. The count alone was not a bound on time:
# with the key's two-minute budget spent, 25 names waited on the limiter for
# 102 to 108 seconds (measured 2026-09-22). A name is a nicety; whatever lands
# in time is kept, so the next view of the page starts better named.
NAME_BUDGET_SECONDS = 4.0
# How long refreshing a stale slice may wait for the limiter when a snapshot is
# already held and could be served instead.
REFRESH_WAIT_SECONDS = 5.0
# Calls in the key's two-minute window that naming never touches, kept for the
# lookups a visitor is actually waiting on. Shared with a game's story.
NAME_RESERVE = SEARCH_RESERVE
# How long a "no such account" from account-v1 is believed. Some ladder entries
# have no account behind them: on 2026-09-22, two of the first 200 EUW Bronze IV rows
# answered 404 for every lookup, and each view of their page paid for both
# again. A week, rather than for good, in case the account comes back.
NO_ACCOUNT_RECHECK_SECONDS = 7 * 24 * 3600


@dataclass(slots=True)
class LadderRow:
    position: int
    puuid: str
    tier: str
    division: str
    league_points: int
    wins: int
    losses: int
    hot_streak: bool
    veteran: bool
    fresh_blood: bool
    inactive: bool
    game_name: str | None = None
    tag_line: str | None = None
    # Riot has no account for this entry, so it will never have a name, and
    # the page should stop waiting for one.
    no_riot_id: bool = False


@dataclass(slots=True)
class LadderPage:
    platform: str
    queue_id: int
    queue_type: str
    tier: str
    division: str | None
    page: int
    per_page: int
    total_stored: int
    # The ladder's true size, and only when we actually know it. An apex
    # endpoint returns the whole league in one response, so there it is exact.
    # The paged endpoint gives no total at all and we stop after a few pages,
    # so there it is None: reporting how many rows we happened to scan as the
    # ladder size would be a made-up denominator that looks authoritative.
    total_entries: int | None
    named_on_page: int
    fetched_at: datetime | None
    # True when the ladder continues past what we store, whether because the
    # row cap bit or because we stopped paging.
    truncated: bool = False
    # True when naming stopped to leave the key's reserve alone, so the page
    # can say the rest are waiting on Riot rather than unknown.
    names_held_back: bool = False
    # When held back: seconds until the key has room for the next batch, so
    # the page can ask again then instead of guessing. A call frees two
    # minutes after it was made, which is longer than any fixed retry that
    # still feels live.
    names_retry_after: float | None = None
    rows: list[LadderRow] = field(default_factory=list)


def normalise_entries(payload, tier: str, division: str) -> list[dict]:
    """One shape out of Riot's two.

    ``apex_league`` returns ``{queue, tier, entries: [...]}`` with the tier on
    the league object and ``rank`` per entry; ``league_entries`` returns a flat
    list carrying ``tier`` and ``queueType`` on every row. Normalising here
    keeps the difference out of everything downstream.
    """
    entries = payload.get("entries", []) if isinstance(payload, dict) else (payload or [])
    league_tier = payload.get("tier") if isinstance(payload, dict) else None
    out = []
    for raw in entries:
        if not raw.get("puuid"):
            continue
        out.append(
            {
                "puuid": raw["puuid"],
                "tier": (raw.get("tier") or league_tier or tier).upper(),
                "division": (raw.get("rank") or division or "I").upper(),
                "league_points": raw.get("leaguePoints") or 0,
                "wins": raw.get("wins") or 0,
                "losses": raw.get("losses") or 0,
                "hot_streak": bool(raw.get("hotStreak")),
                "veteran": bool(raw.get("veteran")),
                "fresh_blood": bool(raw.get("freshBlood")),
                "inactive": bool(raw.get("inactive")),
            }
        )
    return out


class LadderService:
    """Snapshot, page and progressively name a ranked ladder."""

    # One lock per slice so two simultaneous first views of the same ladder do
    # not both spend the fetch. Mirrors StaticDataService.ensure_loaded.
    _locks: dict[str, asyncio.Lock] = {}

    def __init__(self, session: AsyncSession, client: RiotClient, settings) -> None:
        self.session = session
        self.client = client
        self.settings = settings
        self.ranks = RankCache(session, client, settings)
        # Set by `_resolve_names` when the key's reserve stopped it, with when
        # trying again will get somewhere.
        self.names_held_back = False
        self.names_retry_after: float | None = None

    # ------------------------------------------------------------- fetching

    def ttl_for(self, tier: str) -> int:
        # Master is a multi-megabyte transfer and moves slowly at the tail, so
        # it is refreshed far less often than the 300-row ladders.
        if tier.upper() == "MASTER":
            return self.settings.ttl_ladder_master
        return self.settings.ttl_ladder

    @staticmethod
    def _cursor_key(platform: str, queue_type: str, tier: str, division: str) -> str:
        return f"ladder:{platform}:{queue_type}:{tier}:{division}"

    async def _meta(
        self, platform: str, queue_type: str, tier: str, division: str
    ) -> tuple[datetime | None, int | None, bool]:
        """When this slice was last fetched, and how many entries Riot reported.

        Kept in ``IngestCursor`` rather than derived from the stored rows, for
        two reasons that both bit in practice:

        * **An empty slice has no rows to derive a timestamp from**, so deriving
          it meant a ladder that legitimately comes back empty was never
          considered cached and re-fetched on every single page view.
        * **The row count is not the ladder size.** Master is ten thousand
          entries and we store a thousand, so reporting the stored count as the
          total quietly under-reports the ladder by an order of magnitude.
        """
        row = await self.session.get(
            IngestCursor, self._cursor_key(platform, queue_type, tier, division)
        )
        if row is None:
            return None, None, False
        try:
            data = json.loads(row.value or "{}")
            raw_total = data.get("total")
            total = int(raw_total) if raw_total is not None else None
            truncated = bool(data.get("truncated"))
        except (ValueError, TypeError):
            total, truncated = None, False
        return row.updated_at, total, truncated

    async def _record_meta(
        self,
        platform: str,
        queue_type: str,
        tier: str,
        division: str,
        *,
        total: int | None,
        stored: int,
        truncated: bool,
    ) -> None:
        key = self._cursor_key(platform, queue_type, tier, division)
        payload = json.dumps(
            {"total": total, "stored": stored, "truncated": truncated}
        )
        row = await self.session.get(IngestCursor, key)
        if row is None:
            self.session.add(IngestCursor(key=key, value=payload))
        else:
            row.value = payload
            # `updated_at` has onupdate=utcnow, but only fires when a column
            # actually changes. An identical refresh has to be stamped too, or
            # an unchanging ladder looks permanently stale.
            row.updated_at = utcnow()

    async def refresh(
        self,
        platform: Platform | str,
        *,
        queue_id: int = 420,
        tier: str = "CHALLENGER",
        division: str = "I",
        pages: int = 5,
    ) -> int:
        """Re-fetch one slice from Riot and replace the stored snapshot."""
        resolved = resolve_platform(platform)
        queue_type = QUEUE_BY_ID.get(queue_id, "RANKED_SOLO_5x5")
        tier, division = tier.upper(), division.upper()

        rows: list[dict] = []
        exact_total: int | None = None
        stopped_early = False

        if tier in APEX_TIERS:
            # One response is the entire league, so the count is authoritative.
            payload = await self.client.apex_league(queue_type, tier.lower(), resolved)
            rows = normalise_entries(payload, tier, "I")
            exact_total = len(rows)
            division = "I"
        else:
            # The paged endpoint never says how big the ladder is, and Diamond
            # alone runs to tens of thousands, so we scan a few pages and admit
            # that is all we did.
            for page in range(1, pages + 1):
                payload = await self.client.league_entries(
                    queue_type, tier, division, resolved, page=page
                )
                batch = normalise_entries(payload, tier, division)
                rows.extend(batch)
                # Derived from "this page came back empty", not from a page-size
                # constant: 205 is what Riot happens to send today, not a
                # contract.
                if not batch:
                    # Ran out of ladder, so what we have *is* all of it.
                    exact_total = len(rows)
                    break
                if len(rows) >= MAX_ROWS_PER_SLICE:
                    stopped_early = True
                    break
            else:
                stopped_early = True

        # Riot does not promise an order, so assign our own from an LP sort.
        # Trusting the response order is a silent bug: the ladder would look
        # subtly shuffled and nothing would ever fail.
        rows.sort(key=lambda r: (-r["league_points"], -r["wins"], r["puuid"]))

        # Dedupe by PUUID. The paged endpoint reads a ladder that is *moving*:
        # a player can be on page 1 when it is fetched and page 2 a second
        # later, so the same person legitimately comes back twice. Seen against
        # live EUW Diamond I. Keeping the first occurrence keeps the higher LP
        # reading, which is the one the sort above already preferred.
        seen: set[str] = set()
        deduped = []
        for row in rows:
            if row["puuid"] in seen:
                continue
            seen.add(row["puuid"])
            deduped.append(row)
        if len(deduped) != len(rows):
            log.info(
                "ladder %s %s %s: %d duplicate rows across pages",
                tier, division, resolved.id, len(rows) - len(deduped),
            )
        kept = deduped[:MAX_ROWS_PER_SLICE]
        if len(deduped) > len(kept):
            stopped_early = True
        if exact_total is not None:
            exact_total = len(deduped)

        stamp = utcnow()
        await self.session.execute(
            delete(LadderEntry).where(
                LadderEntry.platform == resolved.id,
                LadderEntry.queue_type == queue_type,
                LadderEntry.tier == tier,
                LadderEntry.division == division,
            )
        )
        self.session.add_all(
            LadderEntry(
                platform=resolved.id,
                queue_type=queue_type,
                tier=tier,
                division=division,
                puuid=row["puuid"],
                position=index + 1,
                league_points=row["league_points"],
                wins=row["wins"],
                losses=row["losses"],
                hot_streak=row["hot_streak"],
                veteran=row["veteran"],
                fresh_blood=row["fresh_blood"],
                inactive=row["inactive"],
                fetched_at=stamp,
            )
            for index, row in enumerate(kept)
        )
        await self._record_meta(
            resolved.id, queue_type, tier, division,
            total=exact_total, stored=len(kept), truncated=stopped_early,
        )
        await self.session.commit()
        log.info(
            "ladder %s %s %s %s: stored %d of %s",
            resolved.id, queue_type, tier, division, len(kept),
            exact_total if exact_total is not None else "an unknown total",
        )
        return len(kept)

    # ------------------------------------------------------------ position

    async def position_of(
        self,
        puuid: str,
        platform: Platform | str,
        tier: str | None,
        *,
        queue_type: str = "RANKED_SOLO_5x5",
    ) -> LadderPosition | None:
        """Where this player stands on the stored ladder. Never calls Riot.

        Read in the tier the player holds *now*: a snapshot can be a day old,
        and a player promoted since then is also still listed in the tier below,
        where their old position is no longer true.
        """
        tier = (tier or "").upper()
        if tier not in APEX_TIERS:
            return None
        resolved = resolve_platform(platform)
        entry = (
            await self.session.execute(
                select(LadderEntry).where(
                    LadderEntry.platform == resolved.id,
                    LadderEntry.queue_type == queue_type,
                    LadderEntry.tier == tier,
                    LadderEntry.puuid == puuid,
                )
            )
        ).scalars().first()
        if entry is None:
            return None
        as_of = entry.fetched_at
        if as_of.tzinfo is None:  # SQLite hands back naive datetimes
            as_of = as_of.replace(tzinfo=UTC)
        if datetime.now(UTC) - as_of > POSITION_MAX_AGE:
            return None

        # Everyone in the tiers above counts ahead of this player. An apex
        # league arrives whole, so those totals are exact when we hold them.
        above: int | None = 0
        for higher in APEX_TIERS[APEX_TIERS.index(tier) + 1:]:
            _, total, _ = await self._meta(resolved.id, queue_type, higher, "I")
            if total is None:
                above = None
                break
            above += total
        return LadderPosition(
            tier=tier,
            tier_position=entry.position,
            position=entry.position + above if above is not None else None,
            platform=resolved.id,
            as_of=as_of,
        )

    # --------------------------------------------------------------- paging

    async def page(
        self,
        platform: Platform | str,
        *,
        queue_id: int = 420,
        tier: str = "CHALLENGER",
        division: str = "I",
        page: int = 1,
        per_page: int = 50,
        resolve_names: bool = True,
    ) -> LadderPage:
        resolved = resolve_platform(platform)
        queue_type = QUEUE_BY_ID.get(queue_id, "RANKED_SOLO_5x5")
        tier = tier.upper()
        division = "I" if tier in APEX_TIERS else division.upper()

        age, ladder_total, truncated = await self._meta(
            resolved.id, queue_type, tier, division
        )
        if not is_fresh(age, self.ttl_for(tier)):
            key = self._cursor_key(resolved.id, queue_type, tier, division)
            lock = self._locks.setdefault(key, asyncio.Lock())
            async with lock:
                # Re-check: another request may have refreshed while we waited.
                age, ladder_total, truncated = await self._meta(
                    resolved.id, queue_type, tier, division
                )
                if not is_fresh(age, self.ttl_for(tier)):
                    # Holding a snapshot, a refresh may barely wait for the
                    # limiter: a ladder a few minutes old beats a page that
                    # hangs for the key. With nothing held there is no
                    # alternative, and the request's own deadline applies.
                    token = (
                        wait_deadline.set(
                            min(
                                wait_deadline.get() or float("inf"),
                                time.monotonic() + REFRESH_WAIT_SECONDS,
                            )
                        )
                        if age is not None
                        else None
                    )
                    try:
                        await self.refresh(
                            resolved, queue_id=queue_id, tier=tier, division=division
                        )
                        age, ladder_total, truncated = await self._meta(
                            resolved.id, queue_type, tier, division
                        )
                    except RiotApiError as exc:
                        # Serve the stale snapshot rather than failing the page.
                        # Only a slice we have never held is worth an error.
                        if age is None:
                            raise
                        log.warning("ladder refresh failed, serving stale: %s", exc)
                    finally:
                        if token is not None:
                            wait_deadline.reset(token)

        base = select(LadderEntry).where(
            LadderEntry.platform == resolved.id,
            LadderEntry.queue_type == queue_type,
            LadderEntry.tier == tier,
            LadderEntry.division == division,
        )
        total = (
            await self.session.execute(
                select(func.count()).select_from(base.subquery())
            )
        ).scalar() or 0

        offset = max(0, (page - 1) * per_page)
        entries = list(
            (
                await self.session.execute(
                    base.order_by(LadderEntry.position).offset(offset).limit(per_page)
                )
            ).scalars()
        )

        names, nameless = await self._names_for(
            [e.puuid for e in entries], resolve_names, resolved
        )
        rows = [
            LadderRow(
                position=e.position,
                puuid=e.puuid,
                tier=e.tier,
                division=e.division,
                league_points=e.league_points,
                wins=e.wins,
                losses=e.losses,
                hot_streak=e.hot_streak,
                veteran=e.veteran,
                fresh_blood=e.fresh_blood,
                inactive=e.inactive,
                game_name=names.get(e.puuid, (None, None))[0],
                tag_line=names.get(e.puuid, (None, None))[1],
                no_riot_id=e.puuid in nameless,
            )
            for e in entries
        ]
        return LadderPage(
            platform=resolved.id,
            queue_id=queue_id,
            queue_type=queue_type,
            tier=tier,
            division=None if tier in APEX_TIERS else division,
            page=page,
            per_page=per_page,
            total_stored=total,
            total_entries=ladder_total,
            truncated=truncated,
            # Both halves: the route only renders a Riot ID when it has a
            # tag line too, so counting a name without one would claim a
            # row was named while it renders blank.
            named_on_page=sum(1 for r in rows if r.game_name and r.tag_line),
            fetched_at=age,
            names_held_back=self.names_held_back,
            names_retry_after=self.names_retry_after,
            rows=rows,
        )

    # ---------------------------------------------------------------- names

    async def _names_for(
        self, puuids: list[str], resolve: bool, platform: Platform
    ) -> tuple[dict[str, tuple[str | None, str | None]], set[str]]:
        """Names for the rows on this page, resolving a bounded few if asked.

        Also the rows Riot recently said have no account, which are not asked
        about again until `NO_ACCOUNT_RECHECK_SECONDS` has passed.
        """
        if not puuids:
            return {}, set()

        known = {
            p.puuid: (p.game_name, p.tag_line)
            for p in (
                await self.session.execute(
                    select(Player).where(
                        Player.puuid.in_(puuids), Player.game_name.isnot(None)
                    )
                )
            ).scalars()
        }
        # Free: anyone who has appeared in a match we stored is already named.
        for puuid, pair in (await self.ranks.names_from_matches(puuids)).items():
            known.setdefault(puuid, pair)

        nameless = {
            row.puuid
            for row in (
                await self.session.execute(
                    select(Player.puuid, Player.account_fetched_at).where(
                        Player.puuid.in_(puuids),
                        Player.game_name.is_(None),
                        Player.account_fetched_at.isnot(None),
                    )
                )
            )
            if row.puuid not in known
            and is_fresh(row.account_fetched_at, NO_ACCOUNT_RECHECK_SECONDS)
        }

        missing = [p for p in puuids if p not in known and p not in nameless]
        if resolve and missing:
            resolved, absent = await self._resolve_names(
                missing[:NAME_BUDGET_PER_REQUEST], platform
            )
            known.update(resolved)
            nameless |= absent
        return known, nameless

    async def _resolve_names(
        self, puuids: list[str], platform: Platform
    ) -> tuple[dict[str, tuple[str | None, str | None]], set[str]]:
        """Spend account-v1 calls to name PUUIDs nothing else could.

        Writes what it learns onto ``Player``, so the cost is paid once per
        player for the life of the database, not once per page view.

        Never with the key's last few calls. A name is a nicety and a Riot ID
        lookup is the site's front door: a Bronze page names nobody from our
        stored games, so it can spend 25 calls a view, and with the page now
        asking again while unnamed rows remain, it would otherwise take the
        whole two-minute budget and answer the next search with a rate limit.
        Sets `names_held_back` when the reserve stopped it. Returns the names
        found and the entries Riot has no account for; those are stamped too,
        so the next view does not pay for them again.
        """
        semaphore = asyncio.Semaphore(NAME_CONCURRENCY)
        found: dict[str, tuple[str | None, str | None]] = {}
        absent: set[str] = set()

        async def one(puuid: str) -> None:
            async with semaphore:
                if self.client.limiter.spare() <= NAME_RESERVE:
                    self.names_held_back = True
                    return
                try:
                    # account-v1 is a *regional* endpoint, and `account_region`
                    # is the one that collapses SEA onto ASIA. Hardcoding
                    # "europe" here would return nothing for KR and NA, which
                    # are exactly the ladders with no local names.
                    account = await self.client.account_by_puuid(
                        puuid, platform.account_region
                    )
                except RiotNotFound:
                    absent.add(puuid)
                    return
                except RiotApiError:
                    return
                name, tag = account.get("gameName"), account.get("tagLine")
                if name:
                    found[puuid] = (name, tag)

        try:
            async with asyncio.timeout(NAME_BUDGET_SECONDS):
                await asyncio.gather(*(one(p) for p in puuids))
        except TimeoutError:
            log.info(
                "ladder name budget of %.0fs expired with %d of %d named",
                NAME_BUDGET_SECONDS, len(found), len(puuids),
            )
        if self.names_held_back:
            # Room for everything this page still wants, not just one more
            # call: a single freed slot names one row and costs a poll.
            wanted = len(puuids) - len(found) - len(absent)
            self.names_retry_after = round(
                self.client.limiter.seconds_until_free(NAME_RESERVE + wanted), 1
            )
        if not found and not absent:
            return found, absent

        players = await self.ranks.ensure_players([*found, *absent], platform)
        for puuid, (name, tag) in found.items():
            player = players.get(puuid)
            if player is not None and not player.game_name:
                player.game_name, player.tag_line = name, tag
                # `search_name` too, or a Riot ID lookup for this player will
                # not find the row and will pay for the same account-v1 call a
                # second time. That is the whole "paid once per player" claim.
                player.search_name = normalize_riot_name(name)
                # Riot just said this account holds the name, so a row left
                # holding it from before a rename stops answering for it.
                await claim_riot_id(self.session, puuid, name, tag)
        for puuid in absent:
            player = players.get(puuid)
            if player is not None and not player.game_name:
                # A stub with a lookup stamp and no name: nothing else reads
                # that pair, because a Riot ID search matches on
                # `search_name` and suggestions need a name.
                player.account_fetched_at = utcnow()
        await self.session.commit()
        return found, absent


__all__ = [
    "APEX_TIERS",
    "DIVISIONS",
    "MAX_ROWS_PER_SLICE",
    "QUEUE_BY_ID",
    "STANDARD_TIERS",
    "LadderPage",
    "LadderRow",
    "LadderService",
    "normalise_entries",
]
