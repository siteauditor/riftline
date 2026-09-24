"""Player lookup: Riot ID -> PUUID -> profile, rank and mastery.

Every request here is rationed. On a development key the binding limit is 100
requests per two minutes, so the cache is not an optimisation, it is what makes
the feature usable at all. A cold profile costs four calls (account, active
region, summoner, league); a warm one inside its TTL costs zero.

A Riot ID belongs to an account, not to a shard, so the row a lookup finds does
not depend on the shard in the URL, and a lookup writes nothing about that
shard. ``Player.platform`` is the home shard, as Riot's active-region lookup
names it, and only the home's summoner record, ranks and mastery are stored.
Which shard's data a page shows is ``view()``'s question; see
``app/services/homes.py`` for the failure that made this the rule.
"""

from __future__ import annotations

import logging
import time
import unicodedata

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    ChampionMastery,
    Match,
    MatchParticipant,
    Player,
    RankedEntry,
    utcnow,
)
from app.riot.client import RiotClient
from app.riot.errors import RiotApiError, RiotNotFound
from app.riot.routing import (
    Platform,
    UnknownPlatform,
    platform_ids_for,
    resolve_platform,
)
from app.services.flight import TtlCache, flights, stamped_since
from app.services.homes import ShardView, canonical, move_home
from app.services.ranks import (
    apply_league_entries,
    is_fresh,
    league_elsewhere,
    puuids_with_history,
    transient_entries,
)

log = logging.getLogger(__name__)


class PlayerNotFound(Exception):
    """No such Riot ID, or none stored."""


def normalize_riot_name(name: str) -> str:
    """Fold a Riot ID name into the form used as a cache key.

    Riot matches Riot IDs loosely. Asking account-v1 for ``Caps#EUW`` returns
    the account that displays as ``Cäps#EUW``, so storing what Riot returns and
    then looking it up by exact match means the cache never hits and every page
    view spends an account-v1 call -- the most expensive mistake you can make on
    a 100-per-2-minutes budget.

    Folding both the query and the stored name through NFKD, dropping combining
    marks, and lowercasing makes ``Caps`` and ``Cäps`` land on the same key.
    Riot IDs are unique under its own folding, so this cannot merge two real
    accounts; and because rows are keyed by PUUID, a wrong guess self-heals on
    the next fetch.
    """
    folded = unicodedata.normalize("NFKD", (name or "").strip())
    without_marks = "".join(c for c in folded if not unicodedata.combining(c))
    # Riot also ignores internal spacing when matching.
    return without_marks.replace(" ", "").casefold()


def _riot_id_key(game_name: str, tag_line: str) -> tuple[str, str]:
    return normalize_riot_name(game_name), (tag_line or "").strip().lstrip("#").lower()


# Shared with `ranks`, which owns it: both modules need the same TTL rule.
_is_fresh = is_fresh

# A refresh goes back to Riot only once the cached answer is at least this old.
# Without a floor `?refresh=true` skipped every TTL, so reloading one public URL
# could spend a development key's 100 requests per two minutes, and the profile's
# Update button makes that one click. Riot's own data does not move faster than
# a game, so a minute loses nothing.
REFRESH_FLOOR_SECONDS = 60


def _cached_is_good(stamp, ttl: int, refresh: bool) -> bool:
    """Whether a cached answer may be served instead of asking Riot again."""
    return _is_fresh(stamp, min(ttl, REFRESH_FLOOR_SECONDS) if refresh else ttl)


# A Riot ID account-v1 does not know, remembered per process for this long. The
# draft board sends the Riot ID with every change, and a mistyped saved one cost
# an account-v1 call for every champion added (measured 2026-09-24: three calls
# for three board changes). Only a 404 is remembered: a rate limit or an outage
# says nothing about whether the account exists. The API runs one worker, so a
# process-local dict is the whole cache.
MISS_TTL_SECONDS = 600
MISS_CACHE_SIZE = 5000
_misses: dict[tuple[str, str], float] = {}


def _miss_key(game_name: str, tag_line: str) -> tuple[str, str]:
    # By Riot ID alone: account-v1 answers for every account from any of its
    # three regions, so a miss in one is a miss in all of them.
    return _riot_id_key(game_name, tag_line)


def _known_miss(key: tuple[str, str]) -> bool:
    at = _misses.get(key)
    if at is None:
        return False
    if time.monotonic() - at > MISS_TTL_SECONDS:
        _misses.pop(key, None)
        return False
    return True


def _remember_miss(key: tuple[str, str]) -> None:
    _misses.pop(key, None)
    if len(_misses) >= MISS_CACHE_SIZE:
        # Dicts keep insertion order, so the first key is the oldest miss.
        _misses.pop(next(iter(_misses)))
    _misses[key] = time.monotonic()


def clear_miss_cache() -> None:
    """Forget every remembered miss and unconfirmed home. For tests."""
    _misses.clear()
    _home_unconfirmed.clear()


# Accounts whose home the active-region lookup could not confirm, and when it
# last failed. The row keeps the shard it had (a new row takes its newest
# stored game's shard, else the one asked), and the lookup is tried again on a
# later view, at most this often, rather than on every request: a Riot account
# that has never played League may never answer.
HOME_RETRY_SECONDS = 600
HOME_UNCONFIRMED_SIZE = 5000
_home_unconfirmed: dict[str, float] = {}


def _note_unconfirmed(puuid: str) -> None:
    _home_unconfirmed.pop(puuid, None)
    if len(_home_unconfirmed) >= HOME_UNCONFIRMED_SIZE:
        _home_unconfirmed.pop(next(iter(_home_unconfirmed)))
    _home_unconfirmed[puuid] = time.monotonic()


def _home_retry_due(puuid: str) -> bool:
    at = _home_unconfirmed.get(puuid)
    return at is not None and time.monotonic() - at >= HOME_RETRY_SECONDS


# Read-only answers from a shard that is not the player's home: shown, never
# stored. Keyed by (shard, puuid). The league answers share `ranks`' cache, so
# a stranger's rank read for a live lobby also serves their profile there.
_summoner_elsewhere: TtlCache[tuple[str, str], dict | None] = TtlCache()
_mastery_elsewhere: TtlCache[tuple[str, str], tuple[dict, ...]] = TtlCache()


async def claim_riot_id(
    session: AsyncSession, puuid: str, game_name: str | None, tag_line: str | None
) -> int:
    """Make ``puuid`` the only row that answers this Riot ID. Does not commit.

    A rename can leave another row holding the same folded Riot ID: the account
    that gave the name up, still stored under it. Two rows folding to one key
    made a lookup return whichever one the database picked first, so every
    answer from Riot about who holds a Riot ID retires the other claims.
    Returns how many were retired.
    """
    if not game_name or not tag_line:
        return 0
    folded, tag = _riot_id_key(game_name, tag_line)
    result = await session.execute(
        update(Player)
        .where(
            Player.search_name == folded,
            func.lower(Player.tag_line) == tag,
            Player.puuid != puuid,
        )
        .values(search_name=None)
        .execution_options(synchronize_session="fetch")
    )
    retired = result.rowcount or 0
    if retired:
        log.info("riot id %s#%s changed hands; retired %d stale row(s)", game_name, tag_line, retired)
    return retired


def _fill_mastery(mastery: ChampionMastery, raw: dict) -> None:
    mastery.champion_level = raw.get("championLevel") or 0
    mastery.champion_points = raw.get("championPoints") or 0
    mastery.points_since_last_level = raw.get("championPointsSinceLastLevel") or 0
    mastery.points_until_next_level = raw.get("championPointsUntilNextLevel") or 0
    mastery.last_play_time = raw.get("lastPlayTime")
    mastery.tokens_earned = raw.get("tokensEarned") or 0
    mastery.season_milestone = raw.get("championSeasonMilestone")
    mastery.milestone_grades = raw.get("milestoneGrades")
    # `chestGranted` and `markRequiredForNextLevel` are no longer read.
    # Riot removed chests in 2024: measured false on 166 of 166 entries
    # for a real account and on all 789 rows we hold. The marks figure
    # has never reached a response or a test. Their columns stay for
    # now, because `chest_granted` is NOT NULL with no server default
    # and this deploy runs migrations *after* the new code is already
    # serving, so a model without the column would spend that window
    # failing every insert, swallowed by `_commit_tolerating_race` as a
    # concurrent write.


def transient_masteries(puuid: str, raw_list) -> list[ChampionMastery]:
    """A mastery answer as rows that are never added to a session."""
    out = []
    for raw in raw_list or []:
        champion_id = raw.get("championId")
        if champion_id is None:
            continue
        mastery = ChampionMastery(puuid=puuid, champion_id=champion_id)
        _fill_mastery(mastery, raw)
        out.append(mastery)
    return out


class PlayerService:
    def __init__(self, session: AsyncSession, client: RiotClient, settings) -> None:
        self.session = session
        self.client = client
        self.settings = settings

    # ----------------------------------------------------------------- lookup

    async def resolve(
        self,
        platform_name: str,
        game_name: str,
        tag_line: str,
        *,
        refresh: bool = False,
        remember_miss: bool = False,
    ) -> Player:
        """Find a player by Riot ID, asking Riot only when the cache is cold.

        A cold lookup is two calls made once for every request that wants
        them: account-v1 for the Riot ID, and the active region, which names
        the home shard. ``platform_name`` only picks the account-v1 region to
        ask and the guess for a new row whose region Riot would not name;
        nothing here reads or writes anything about that shard.

        Riot IDs are case- and space-insensitive for lookup but we store them as
        Riot returns them, so the UI shows the player's own capitalisation.

        ``remember_miss`` answers a Riot ID account-v1 has just said it does not
        know from memory for ``MISS_TTL_SECONDS``. The draft board opts in; the
        profile search does not, so an account made a minute ago is found the
        moment somebody searches for it.
        """
        asked = resolve_platform(platform_name)
        tag_line = tag_line.strip().lstrip("#")
        ttl = self.settings.ttl_account

        player = await self._find_cached(game_name, tag_line)
        if player is not None and _cached_is_good(player.account_fetched_at, ttl, refresh):
            await self._confirm_home_if_due(player)
            return player

        miss = _miss_key(game_name, tag_line) if remember_miss else None
        if player is None and miss is not None and _known_miss(miss):
            raise PlayerNotFound(f"No Riot account is called {game_name}#{tag_line}.")

        started = utcnow()
        async with flights.hold(("account", *_riot_id_key(game_name, tag_line))):
            # Another request may have answered while this one waited.
            player = await self._find_cached(game_name, tag_line, reload=True)
            if player is not None and (
                stamped_since(player.account_fetched_at, started)
                or _cached_is_good(player.account_fetched_at, ttl, refresh)
            ):
                return player
            if player is None and miss is not None and _known_miss(miss):
                raise PlayerNotFound(f"No Riot account is called {game_name}#{tag_line}.")
            try:
                account = await self.client.account_by_riot_id(
                    game_name, tag_line, asked.account_region
                )
            except RiotNotFound:
                if player is not None:
                    # Riot is unsure but we have a cached hit: a rename, most
                    # likely. Serve what we have rather than 404ing the user.
                    log.info("account-v1 miss for %s#%s; serving cache", game_name, tag_line)
                    return player
                if miss is not None:
                    _remember_miss(miss)
                raise PlayerNotFound(f"No Riot account is called {game_name}#{tag_line}.") from None
            home = await self._active_region(account["puuid"], asked)
            return await self._upsert_from_account(account, asked, home)

    async def resolve_stored(self, platform_name: str, game_name: str, tag_line: str) -> Player:
        """The row we hold for a Riot ID, and nothing from Riot.

        For the prerendered profile: a page is written for every player with
        enough scored games, and a thousand pages each spending an account-v1
        call would be the whole key's budget for twenty minutes. Nothing here
        is refreshed either, so the answer is whatever the last visit left,
        which is what the page says it is. The platform is checked, and does
        not choose the row: a Riot ID names one account.
        """
        resolve_platform(platform_name)
        player = await self._find_cached(game_name, tag_line.lstrip("#"))
        if player is None:
            raise PlayerNotFound(f"{game_name}#{tag_line} is not stored.")
        return player

    async def _find_cached(
        self, game_name: str, tag_line: str, *, reload: bool = False
    ) -> Player | None:
        folded, tag = _riot_id_key(game_name, tag_line)
        stmt = (
            select(Player)
            .where(Player.search_name == folded, func.lower(Player.tag_line) == tag)
            # Newest confirmation first. `claim_riot_id` keeps one row per Riot
            # ID, and this keeps a lookup from turning into a 500 or a coin toss
            # if a row from before that rule still shares the key.
            .order_by(Player.account_fetched_at.desc().nulls_last())
            .limit(1)
        )
        if reload:
            stmt = stmt.execution_options(populate_existing=True)
        return (await self.session.execute(stmt)).scalars().first()

    async def _active_region(self, puuid: str, asked: Platform) -> Platform | None:
        """The home shard Riot names for this account, or None if it will not.

        None is noted, so a later view asks again (``HOME_RETRY_SECONDS``);
        an answer clears the note.
        """
        try:
            region = await self.client.active_region(puuid, asked.account_region)
        except RiotApiError as exc:
            log.warning("active region lookup failed for %s: %s", puuid[:8], exc)
            _note_unconfirmed(puuid)
            return None
        try:
            home = resolve_platform(region) if region else None
        except UnknownPlatform:
            log.warning("active region named an unknown shard %r", region)
            home = None
        if home is None:
            _note_unconfirmed(puuid)
        else:
            _home_unconfirmed.pop(puuid, None)
        return home

    async def _confirm_home_if_due(self, player: Player) -> None:
        """Ask for the active region again when an earlier lookup failed."""
        if not _home_retry_due(player.puuid):
            return
        async with flights.hold(("region", player.puuid)):
            if not _home_retry_due(player.puuid):
                return  # confirmed, or tried, by the request this one waited for
            home = await self._active_region(player.puuid, self.home_of(player))
            if home is None:
                return
            await self.session.refresh(player)
            if home.id != player.platform:
                log.info("home of %s confirmed as %s", player.puuid[:8], home.id)
                await move_home(self.session, player, home)
                await self._commit_tolerating_race(player)

    async def _upsert_from_account(
        self, account: dict, asked: Platform, home: Platform | None
    ) -> Player:
        puuid = account["puuid"]
        player = await self.session.get(Player, puuid)
        if player is None:
            guess = home or await self._newest_game_shard(puuid) or asked
            player = Player(puuid=puuid, platform=guess.id)
            self.session.add(player)
        elif home is not None and home.id != player.platform:
            # Riot names a different home: the account moved, or the row was
            # a guess. Caches read on the old one describe another shard.
            log.info("home of %s is %s, not %s", puuid[:8], home.id, player.platform)
            await move_home(self.session, player, home)
        elif canonical(player.platform) not in (None, player.platform):
            player.platform = canonical(player.platform)

        # gameName/tagLine are optional in the DTO for accounts without a Riot ID.
        player.game_name = account.get("gameName") or player.game_name
        player.tag_line = account.get("tagLine") or player.tag_line
        player.search_name = normalize_riot_name(player.game_name or "")
        player.account_fetched_at = utcnow()
        await claim_riot_id(self.session, puuid, player.game_name, player.tag_line)

        try:
            await self.session.commit()
        except IntegrityError:
            # Two processes created the same new player at once. They carry
            # identical data, so the loser simply adopts the winner's row
            # rather than failing a page load over it.
            await self.session.rollback()
            player = await self.session.get(Player, puuid)
            if player is None:
                raise
        return player

    async def _newest_game_shard(self, puuid: str) -> Platform | None:
        stored = (
            await self.session.execute(
                select(Match.platform_id)
                .join(MatchParticipant, MatchParticipant.match_id == Match.match_id)
                .where(MatchParticipant.puuid == puuid, Match.is_remake.is_(False))
                .order_by(Match.game_creation.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        try:
            return resolve_platform(stored.lower()) if stored else None
        except UnknownPlatform:
            return None

    # ------------------------------------------------------------------ shards

    def home_of(self, player: Player) -> Platform:
        return resolve_platform(player.platform)

    async def view(self, player: Player, asked: Platform | str, *, live: bool = True) -> ShardView:
        """Which shard's data a request that names ``asked`` shows.

        The home when ``asked`` is the home. Otherwise ``second`` when the
        account holds stored games on the asked shard (free) or a rank there
        (one league call, cached and shared by the page's parallel requests),
        and ``absent`` when it holds neither: a level 30 record on another
        shard is not a second home, and on 2026-09-24 treating one as the
        profile's shard deleted a Challenger's rank. With ``live=False`` only
        the stored games are asked. A failed league call answers ``absent``,
        and is not cached, so the next view asks again.
        """
        asked = resolve_platform(asked)
        home = self.home_of(player)
        if asked.id == home.id:
            return ShardView(asked, home, "home")
        if await self.has_games_on(player.puuid, asked):
            return ShardView(asked, home, "second")
        if not live:
            return ShardView(asked, home, "absent")
        try:
            league = await self.league_on(player.puuid, asked)
        except RiotApiError as exc:
            log.info("could not read %s ranks for %s: %s", asked.id, player.puuid[:8], exc)
            return ShardView(asked, home, "absent")
        return ShardView(asked, home, "second" if league else "absent", league=league or None)

    async def has_games_on(self, puuid: str, platform: Platform) -> bool:
        found = (
            await self.session.execute(
                select(Match.match_id)
                .join(MatchParticipant, MatchParticipant.match_id == Match.match_id)
                .where(
                    MatchParticipant.puuid == puuid,
                    Match.platform_id.in_(sorted(platform_ids_for(platform))),
                    Match.is_remake.is_(False),
                )
                .limit(1)
            )
        ).first()
        return found is not None

    async def league_on(
        self, puuid: str, platform: Platform, *, refresh: bool = False
    ) -> tuple[dict, ...]:
        """league-v4 on a shard that is not the home. Read only, never stored."""
        key = (platform.id, puuid)
        ttl = self.settings.ttl_league
        if refresh:
            ttl = min(ttl, REFRESH_FLOOR_SECONDS)
        hit, value = league_elsewhere.get(key, ttl)
        if hit:
            return value or ()
        started = time.monotonic()
        async with flights.hold(("league", *key)):
            hit, value = league_elsewhere.get(key, ttl, since=started)
            if hit:
                return value or ()
            value = tuple(await self.client.league_entries_by_puuid(puuid, platform) or ())
            league_elsewhere.put(key, value)
            return value

    async def ranks_on(
        self,
        puuid: str,
        platform: Platform,
        *,
        known: tuple[dict, ...] | None = None,
        refresh: bool = False,
    ) -> list[RankedEntry]:
        """The ranks on a shard that is not the home, as rows never stored.

        ``known`` is the answer ``view()`` already read, when it read one.
        """
        raw = (
            known
            if known is not None
            else await self.league_on(puuid, platform, refresh=refresh)
        )
        return transient_entries(puuid, raw)

    def league_read_at(self, puuid: str, platform: Platform) -> int | None:
        """Epoch ms of the held league answer from a shard that is not the home."""
        age = league_elsewhere.age((platform.id, puuid))
        return None if age is None else int((time.time() - age) * 1000)

    async def summoner_on(self, puuid: str, platform: Platform) -> dict | None:
        """summoner-v4 on a shard that is not the home. Read only, never stored.

        None for no record there. A failure is None too and is not cached: a
        level and an icon are a nicety, never a page failure.
        """
        key = (platform.id, puuid)
        ttl = self.settings.ttl_summoner
        hit, value = _summoner_elsewhere.get(key, ttl)
        if hit:
            return value
        started = time.monotonic()
        async with flights.hold(("summoner-elsewhere", *key)):
            hit, value = _summoner_elsewhere.get(key, ttl, since=started)
            if hit:
                return value
            try:
                value = await self.client.summoner_by_puuid(puuid, platform)
            except RiotNotFound:
                value = None
            except RiotApiError as exc:
                log.warning("could not read %s record for %s: %s", platform.id, puuid[:8], exc)
                return None
            _summoner_elsewhere.put(key, value)
            return value

    async def masteries_on(self, puuid: str, platform: Platform) -> list[ChampionMastery]:
        """champion-mastery-v4 on a shard that is not the home, as rows that are
        never stored."""
        key = (platform.id, puuid)
        ttl = self.settings.ttl_mastery
        hit, value = _mastery_elsewhere.get(key, ttl)
        if not hit:
            started = time.monotonic()
            async with flights.hold(("mastery-elsewhere", *key)):
                hit, value = _mastery_elsewhere.get(key, ttl, since=started)
                if not hit:
                    value = tuple(await self.client.champion_masteries(puuid, platform) or ())
                    _mastery_elsewhere.put(key, value)
        return transient_masteries(puuid, value)

    # --------------------------------------------------------------- summoner

    async def ensure_summoner(self, player: Player, *, refresh: bool = False) -> Player:
        """Top up level and profile icon from the home shard.

        summoner-v4 no longer returns a name. Only the home's record is stored:
        the row holds one level and one icon, and another shard's record
        written into it made two shards overwrite each other on every view.
        """
        home = self.home_of(player)
        ttl = self.settings.ttl_summoner
        if player.summoner_platform == home.id and _cached_is_good(
            player.summoner_fetched_at, ttl, refresh
        ):
            return player
        started = utcnow()
        async with flights.hold(("summoner", player.puuid)):
            await self.session.refresh(player)
            home = self.home_of(player)
            if player.summoner_platform == home.id and (
                stamped_since(player.summoner_fetched_at, started)
                or _cached_is_good(player.summoner_fetched_at, ttl, refresh)
            ):
                return player
            try:
                data = await self.client.summoner_by_puuid(player.puuid, home)
            except RiotNotFound:
                # No record on the home shard: a Riot account that has never
                # played League, or a home that is still a guess because the
                # active region did not answer. The blanks are the truth about
                # this shard, stamped so the next view does not ask again at
                # once; the region is asked again on a later view.
                data = {}
            player.profile_icon_id = data.get("profileIconId")
            player.summoner_level = data.get("summonerLevel")
            player.revision_date = data.get("revisionDate")
            player.summoner_platform = home.id
            player.summoner_fetched_at = utcnow()
            await self.session.commit()
            return player

    # ------------------------------------------------------------------ ranks

    async def _entries(self, puuid: str) -> list[RankedEntry]:
        stmt = (
            select(RankedEntry)
            .where(RankedEntry.puuid == puuid)
            .execution_options(populate_existing=True)
        )
        return list((await self.session.execute(stmt)).scalars())

    async def stored_ranks(self, player: Player) -> list[RankedEntry]:
        """The home ranks as last read, from storage only.

        Rows stamped for another shard are not the home's rank and are not
        shown. Rows with no stamp were read before the stamps existed
        (2026-09-17), on the shard the row named, and the ``homes`` repair
        adopts them.
        """
        if player.league_platform not in (None, canonical(player.platform)):
            return []
        return await self._entries(player.puuid)

    async def ranks(self, player: Player, *, refresh: bool = False) -> list[RankedEntry]:
        """The home ranks, read from Riot when the stored ones are stale."""
        home = self.home_of(player)
        ttl = self.settings.ttl_league
        if player.league_platform == home.id and _cached_is_good(
            player.league_fetched_at, ttl, refresh
        ):
            return await self._entries(player.puuid)
        started = utcnow()
        async with flights.hold(("ranks", player.puuid)):
            await self.session.refresh(player)
            home = self.home_of(player)
            current = await self._entries(player.puuid)
            if player.league_platform == home.id and (
                stamped_since(player.league_fetched_at, started)
                or _cached_is_good(player.league_fetched_at, ttl, refresh)
            ):
                return current

            entries = await self.client.league_entries_by_puuid(player.puuid, home)
            # Shared with RankCache so the two rank paths cannot drift on which
            # queues to write and which to drop.
            tracked = await puuids_with_history(self.session, [player.puuid])
            await apply_league_entries(
                self.session, player.puuid, entries, current,
                platform=home.id, baseline=player.puuid not in tracked,
            )
            player.league_platform = home.id
            player.league_fetched_at = utcnow()
            await self._commit_tolerating_race(player)
            return await self._entries(player.puuid)

    # ---------------------------------------------------------------- mastery

    async def masteries(self, player: Player, *, refresh: bool = False) -> list[ChampionMastery]:
        """The home mastery table, read from Riot when the stored one is stale.

        Scoped to the home like the summoner and league caches, and for the
        same reason: mastery on the wrong shard is an empty 200, and stamping
        that as fresh hid the real table until the TTL ran out (Veystrix#999,
        whose account is on SG2 and who holds 100 champions there and none on
        the OCE route).
        """
        stmt = (
            select(ChampionMastery)
            .where(ChampionMastery.puuid == player.puuid)
            .execution_options(populate_existing=True)
        )
        home = self.home_of(player)
        ttl = self.settings.ttl_mastery
        if player.mastery_platform == home.id and _cached_is_good(
            player.mastery_fetched_at, ttl, refresh
        ):
            return list((await self.session.execute(stmt)).scalars())
        started = utcnow()
        async with flights.hold(("mastery", player.puuid)):
            await self.session.refresh(player)
            home = self.home_of(player)
            current = list((await self.session.execute(stmt)).scalars())
            if player.mastery_platform == home.id and (
                stamped_since(player.mastery_fetched_at, started)
                or _cached_is_good(player.mastery_fetched_at, ttl, refresh)
            ):
                return current

            raw_list = await self.client.champion_masteries(player.puuid, home)
            existing = {m.champion_id: m for m in current}
            for raw in raw_list or []:
                champion_id = raw.get("championId")
                if champion_id is None:
                    continue
                mastery = existing.get(champion_id) or ChampionMastery(
                    puuid=player.puuid, champion_id=champion_id
                )
                _fill_mastery(mastery, raw)
                if champion_id not in existing:
                    self.session.add(mastery)

            player.mastery_platform = home.id
            player.mastery_fetched_at = utcnow()
            await self._commit_tolerating_race(player)
            return list((await self.session.execute(stmt)).scalars())

    async def _commit_tolerating_race(self, player: Player) -> None:
        """Commit, treating a concurrent identical write as success.

        ``ranked_entries`` and ``champion_masteries`` are uniquely keyed per
        player, so two requests that arrive together both try to insert the same
        rows and one loses. Both read the same upstream data, so the loser can
        simply adopt what landed.

        The refresh is not optional. ``rollback()`` expires *every* object in the
        session, the caller's ``player`` included, and the next attribute access
        on it would emit a lazy SELECT -- which under asyncio surfaces as
        MissingGreenlet from somewhere far away. Repopulating it here keeps the
        service from handing its caller a landmine.
        """
        # Read the key while the object is still usable. A failed flush leaves
        # the session refusing every read until it is rolled back, so even
        # `player.puuid` would raise PendingRollbackError from inside the
        # handler -- including from the log line meant to describe the problem.
        puuid = player.puuid
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            log.info("concurrent write for %s; adopting the committed rows", puuid[:12])
            await self.session.refresh(player)
