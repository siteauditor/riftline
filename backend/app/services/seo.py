"""What search engines are told the site has: the page manifest and the sitemap.

One list, read two ways. The prerenderer asks for every page, renders each
into HTML, and marks the ones that are not `indexable` noindex; the sitemap
lists only the indexable ones. Because both come from `pages()`, the sitemap
can never name a page that was not rendered, and a rendered page is never
left out of the sitemap by accident.

A page is indexable when the corpus supports what it shows, on the floors
the pages themselves already apply: a champion needs `TIER_MIN_GAMES` in some
role, an item needs enough buyers to be compared with its slot. Those floors
are measured on a patch that has settled (`index_patch`), not on the newest
patch at the moment it arrives, or every champion page would flip to noindex
on patch day and back a week later.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ChampionStat, ItemStat, Match
from app.services.aggregate import ALL_BRACKETS, POSITIONS, TIER_MIN_GAMES
from app.services.static_data import StaticDataService

INDEX_QUEUE = 420
# The newest patch is the index patch once it holds this many ranked solo
# games. Below that its per-champion samples are a few games each, which
# would noindex most of the site for the first days of every patch.
INDEX_PATCH_MIN_MATCHES = 500
# An item page compares the item with its slot; that figure needs this many
# purchases (SLOT_MIN_GAMES on the item route), and a page without its main
# figure is not one to send a crawler to.
ITEM_MIN_BUYERS = 30

FIXED_PAGES: tuple[tuple[str, str], ...] = (
    ("/", "daily"),
    ("/tierlist", "daily"),
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
    # fixed, champion, item, explainer.
    kind: str
    indexable: bool
    lastmod: datetime | None = None
    changefreq: str = "weekly"
    # A page the prerender must produce, or the build is wrong.
    required: bool = False
    # Why it is not indexable, when it is not.
    reason: str | None = None


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

    # Champions: the most games in any lane role on the index patch, and the
    # newest time those rows were computed.
    best_games: dict[int, int] = {}
    computed: dict[int, datetime] = {}
    if patch:
        rows = (
            await session.execute(
                select(
                    ChampionStat.champion_id,
                    func.max(ChampionStat.games),
                    func.max(ChampionStat.computed_at),
                )
                .where(
                    ChampionStat.patch == patch,
                    ChampionStat.queue_id == INDEX_QUEUE,
                    ChampionStat.rank_bracket == ALL_BRACKETS,
                    ChampionStat.team_position.in_(POSITIONS),
                )
                .group_by(ChampionStat.champion_id)
            )
        ).all()
        for champion_id, games, computed_at in rows:
            best_games[champion_id] = int(games or 0)
            if computed_at is not None:
                computed[champion_id] = computed_at
    for champion in sorted(sd.champions_by_id.values(), key=lambda c: c.name):
        games = best_games.get(champion.id, 0)
        enough = games >= TIER_MIN_GAMES
        out.append(
            Page(
                path=f"/champions/{sd.champion_slug(champion.id)}",
                kind="champion",
                indexable=enough,
                lastmod=computed.get(champion.id),
                changefreq="daily",
                reason=None if enough else f"{games} games on patch {patch}; needs {TIER_MIN_GAMES}",
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
    return patch, out


def sitemap_xml(origin: str, entries: list[Page]) -> str:
    """The sitemap, indexable pages only. `lastmod` is written only where the
    data behind the page carries a time, so a crawler is never told a page
    changed when it did not."""
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for page in entries:
        if not page.indexable:
            continue
        lines.append("  <url>")
        lines.append(f"    <loc>{origin}{_escape(page.path)}</loc>")
        if page.lastmod is not None:
            lines.append(f"    <lastmod>{page.lastmod.date().isoformat()}</lastmod>")
        lines.append(f"    <changefreq>{page.changefreq}</changefreq>")
        lines.append("  </url>")
    lines.append("</urlset>")
    return "\n".join(lines) + "\n"


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
