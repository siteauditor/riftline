"""What search engines are told the site has: the page manifest and the sitemap.

One list, read two ways. The prerenderer asks for every page, renders each
into HTML, and marks the ones that are not `indexable` noindex; the sitemap
lists only the indexable ones. Because both come from `pages()`, the sitemap
can never name a page that was not rendered, and a rendered page is never
left out of the sitemap by accident.

A page is indexable when the corpus supports what it shows, on the floors
the pages themselves already apply: a champion needs `TIER_MIN_GAMES` in some
role, an item needs enough buyers to be compared with its slot, a player
needs `MIN_SCORED_FOR_PROFILE` scored games. The first two are measured on a
patch that has settled (`index_patch`), not on the newest patch at the moment
it arrives, or every champion page would flip to noindex on patch day and
back a week later.

Profiles are the one kind that is not written for every subject. A page is
listed only for a player with enough scored games in storage, and it is
rendered from storage alone (`?source=stored` on the summoner routes), so a
thousand profile pages cost no Riot call. A profile below the floor is not in
the manifest at all: the shell serves it, noindex, and the page still works.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import quote

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ChampionStat, ItemStat, Match, Player
from app.services.aggregate import ALL_BRACKETS, POSITIONS, SETTLED_MIN_MATCHES, TIER_MIN_GAMES
from app.services.homes import canonical
from app.services.profile_stats import profile_floor
from app.services.static_data import StaticDataService

INDEX_QUEUE = 420

# A role's own page, as its path word: `/champions/pantheon/support`. The words
# are the site's role labels, lower case, so a link reads the way the page does.
ROLE_WORDS: dict[str, str] = {
    "TOP": "top",
    "JUNGLE": "jungle",
    "MIDDLE": "mid",
    "BOTTOM": "bot",
    "UTILITY": "support",
}
# The newest patch is the index patch once it holds this many ranked solo
# games. Below that its per-champion samples are a few games each, which
# would noindex most of the site for the first days of every patch. The same
# floor decides which patch a page shows by default (`default_patch`).
INDEX_PATCH_MIN_MATCHES = SETTLED_MIN_MATCHES
# An item page compares the item with its slot; that figure needs this many
# purchases (SLOT_MIN_GAMES on the item route), and a page without its main
# figure is not one to send a crawler to.
ITEM_MIN_BUYERS = 30

# A Riot ID becomes two path segments, and the prerendered file is named
# after the decoded path, the way nginx matches `$uri` against the disk.
# A segment with a path delimiter, an escape or a character no file system
# takes cannot be that file, so such a player is left out rather than
# written somewhere the URL will never find. Riot allows none of these in a
# game name or tag line, so in practice this excludes nobody.
_UNSAFE_SEGMENT = re.compile(r'[\x00-\x1f/\\%?#:*"<>|]')

FIXED_PAGES: tuple[tuple[str, str], ...] = (
    ("/", "daily"),
    ("/tierlist", "daily"),
    ("/champions", "daily"),
    ("/items", "daily"),
    ("/draft", "weekly"),
    ("/leaderboards", "daily"),
    ("/groups", "monthly"),
    ("/method", "weekly"),
    ("/method/score", "weekly"),
    ("/method/win-chance", "weekly"),
    ("/method/death-review", "weekly"),
    ("/method/lane-labels", "weekly"),
)


@dataclass(slots=True)
class Page:
    path: str
    # fixed, champion, champion_role, item, explainer, profile.
    kind: str
    indexable: bool
    lastmod: datetime | None = None
    changefreq: str = "weekly"
    # A page the prerender must produce, or the build is wrong.
    required: bool = False
    # Why it is not indexable, when it is not.
    reason: str | None = None


def path_safe(segment: str) -> bool:
    return bool(segment) and segment not in (".", "..") and not _UNSAFE_SEGMENT.search(segment)


def encode_path(path: str) -> str:
    """The path as a URL, encoded the way the browser's `encodeURIComponent`
    encodes each segment, so the sitemap's `loc` is the page's canonical to
    the byte. `quote` leaves letters, digits and `_.-~` alone; the five other
    characters `encodeURIComponent` keeps are added."""
    return quote(path, safe="/!*'()")


def patch_key(patch: str) -> tuple[int, ...]:
    """'16.9' before '16.18': patches order by number, not by text."""
    try:
        return tuple(int(part) for part in patch.split("."))
    except ValueError:
        return (0,)


def pick_index_patch(matches_by_patch: dict[str, int], aggregated: set[str]) -> str | None:
    """The newest aggregated patch with enough games, else the newest
    aggregated patch at all: a thin corpus still gets a sitemap."""
    settled = [
        p for p in aggregated if matches_by_patch.get(p, 0) >= INDEX_PATCH_MIN_MATCHES
    ]
    pool = settled or list(aggregated)
    if not pool:
        return None
    return max(pool, key=patch_key)


async def index_patch(session: AsyncSession) -> str | None:
    counts = {
        patch: int(n)
        for patch, n in (
            await session.execute(
                select(Match.patch, func.count())
                .where(Match.queue_id == INDEX_QUEUE, Match.is_remake.is_(False), Match.patch.is_not(None))
                .group_by(Match.patch)
            )
        ).all()
    }
    aggregated = set(
        (
            await session.execute(
                select(ChampionStat.patch)
                .where(ChampionStat.queue_id == INDEX_QUEUE, ChampionStat.rank_bracket == ALL_BRACKETS)
                .distinct()
            )
        ).scalars()
    )
    return pick_index_patch(counts, aggregated)


async def pages(session: AsyncSession, sd: StaticDataService) -> tuple[str | None, list[Page]]:
    """Every page the site can render, with whether each may be indexed."""
    patch = await index_patch(session)
    out: list[Page] = [
        Page(
            path=path,
            kind="explainer" if path.startswith("/method/") else "fixed",
            indexable=True,
            changefreq=freq,
            required=True,
        )
        for path, freq in FIXED_PAGES
    ]

    # Champions: the games in each lane role on the index patch, and the newest
    # time those rows were computed.
    role_games: dict[int, dict[str, int]] = {}
    computed: dict[int, datetime] = {}
    if patch:
        rows = (
            await session.execute(
                select(
                    ChampionStat.champion_id,
                    ChampionStat.team_position,
                    ChampionStat.games,
                    ChampionStat.computed_at,
                ).where(
                    ChampionStat.patch == patch,
                    ChampionStat.queue_id == INDEX_QUEUE,
                    ChampionStat.rank_bracket == ALL_BRACKETS,
                    ChampionStat.team_position.in_(POSITIONS),
                )
            )
        ).all()
        for champion_id, position, games, computed_at in rows:
            role_games.setdefault(champion_id, {})[position] = int(games or 0)
            if computed_at is not None and (
                champion_id not in computed or computed_at > computed[champion_id]
            ):
                computed[champion_id] = computed_at
    best_games = {c: max(roles.values()) for c, roles in role_games.items()}
    for champion in sorted(sd.champions_by_id.values(), key=lambda c: c.name):
        games = best_games.get(champion.id, 0)
        enough = games >= TIER_MIN_GAMES
        slug = sd.champion_slug(champion.id)
        out.append(
            Page(
                path=f"/champions/{slug}",
                kind="champion",
                indexable=enough,
                lastmod=computed.get(champion.id),
                changefreq="daily",
                reason=None if enough else f"{games} games on patch {patch}; needs {TIER_MIN_GAMES}",
            )
        )
        # A page for every role with the tier list's sample, so "Pantheon
        # support build" has one of its own. The main role's page is the bare
        # path; its role path is rendered for the links that name it but
        # points its canonical there and stays out of the index.
        roles = role_games.get(champion.id, {})
        main = max(roles, key=roles.get) if roles else None
        for position in POSITIONS:
            if roles.get(position, 0) < TIER_MIN_GAMES:
                continue
            is_main = position == main
            out.append(
                Page(
                    path=f"/champions/{slug}/{ROLE_WORDS[position]}",
                    kind="champion_role",
                    indexable=not is_main,
                    lastmod=computed.get(champion.id),
                    changefreq="daily",
                    reason=f"the main role, whose page is /champions/{slug}" if is_main else None,
                )
            )

    # Items: buyers on the index patch.
    buyers: dict[int, int] = {}
    item_computed: dict[int, datetime] = {}
    if patch:
        rows = (
            await session.execute(
                select(ItemStat.item_id, ItemStat.buyers, ItemStat.computed_at).where(
                    ItemStat.patch == patch,
                    ItemStat.queue_id == INDEX_QUEUE,
                    ItemStat.rank_bracket == ALL_BRACKETS,
                )
            )
        ).all()
        for item_id, bought, computed_at in rows:
            buyers[item_id] = int(bought or 0)
            if computed_at is not None:
                item_computed[item_id] = computed_at
    for info in sorted(sd.guide_items(), key=lambda i: i.name):
        bought = buyers.get(info.id, 0)
        enough = bought >= ITEM_MIN_BUYERS
        out.append(
            Page(
                path=f"/items/{sd.item_slug(info.id)}",
                kind="item",
                indexable=enough,
                lastmod=item_computed.get(info.id),
                changefreq="daily",
                reason=None if enough else f"{bought} buyers on patch {patch}; needs {ITEM_MIN_BUYERS}",
            )
        )

    out.extend(await profile_pages(session))
    return patch, out


async def profile_pages(session: AsyncSession) -> list[Page]:
    """One page per player with enough scored ranked games in storage.

    The floor is the profile's own (`profile_floor`: `MIN_SCORED_FOR_PROFILE`
    scored ranked games in one role): below it the page withholds its score
    breakdown, and a profile that is a rank and a list of games is what every
    other site already has. `lastmod` is the newest of those games, which is
    when the page's numbers last moved. The path is the player's home shard,
    so a player has one page however many shards they were seen on.

    A row whose `search_name` was retired (the player renamed, someone else
    took the name) is skipped: its URL would not resolve, stored or live.
    """
    floor = await profile_floor(session)
    if not floor:
        return []
    rows = (
        await session.execute(
            select(Player.puuid, Player.platform, Player.game_name, Player.tag_line).where(
                Player.puuid.in_(list(floor)),
                Player.game_name.is_not(None),
                Player.tag_line.is_not(None),
                Player.search_name.is_not(None),
            )
        )
    ).all()
    out: dict[str, Page] = {}
    for puuid, platform, game_name, tag_line in sorted(
        rows, key=lambda r: (r.game_name.casefold(), r.tag_line, -floor[r.puuid])
    ):
        home = canonical(platform)
        if home is None or not (path_safe(game_name) and path_safe(tag_line)):
            continue
        path = f"/summoner/{home}/{game_name}/{tag_line}"
        newest = floor[puuid]
        # One page per address: two rows spelled alike keep the newer.
        out.setdefault(
            path,
            Page(
                path=path,
                kind="profile",
                indexable=True,
                lastmod=datetime.fromtimestamp(newest / 1000, tz=UTC) if newest else None,
                changefreq="daily",
                reason=None,
            ),
        )
    return list(out.values())


def sitemap_xml(origin: str, entries: list[Page]) -> str:
    """The sitemap, indexable pages only. `lastmod` is written only where the
    data behind the page carries a time, so a crawler is never told a page
    changed when it did not."""
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for page in entries:
        if not page.indexable:
            continue
        lines.append("  <url>")
        lines.append(f"    <loc>{origin}{_escape(encode_path(page.path))}</loc>")
        if page.lastmod is not None:
            lines.append(f"    <lastmod>{page.lastmod.date().isoformat()}</lastmod>")
        lines.append(f"    <changefreq>{page.changefreq}</changefreq>")
        lines.append("  </url>")
    lines.append("</urlset>")
    return "\n".join(lines) + "\n"


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
