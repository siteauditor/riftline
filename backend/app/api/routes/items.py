"""The item guide: every item on Summoner's Rift, and how each one is used.

What an item is comes from Riot's item file, read in `static_data` (stats from
the description, because the file's own `stats` object is incomplete). How it
is used comes from `item_stats` and `item_champion_stats`, which the nightly
aggregate builds from stored games. Nothing here calls Riot.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, computed_field
from sqlalchemy import select

from app.api.deps import DbDep, StaticDep
from app.api.schemas import ChampionRef
from app.db.models import ItemChampionStat, ItemStat
from app.services.aggregate import ALL_BRACKETS, ITEM_SLOTS, aggregated_slices, default_patch
from app.services.static_data import GUIDE_GROUPS, ItemInfo, StaticDataService, static_data

router = APIRouter(prefix="/api/items", tags=["items"])

SECTION_LABELS = {
    "finished": "Finished items",
    "boots": "Boots",
    "starter": "Starters",
    "support": "Support items",
    "component": "Components",
    "consumable": "Consumables",
    "trinket": "Trinkets",
}

# What one item of each section is called, for the item's own page.
ITEM_LABELS = {
    "finished": "Finished item",
    "boots": "Boots",
    "starter": "Starter",
    "support": "Support item",
    "component": "Component",
    "consumable": "Consumable",
    "trinket": "Trinket",
    "transformed": "Grown item",
}

# Below these, a figure against the same slot is withheld. 196 of 295 item and
# slot combinations clear 30 on the corpus (measured 2026-09-22); under it one
# game moves the figure by three points or more.
SLOT_MIN_GAMES = 30
CHAMPION_MIN_BUYERS = 20
CHAMPION_LIMIT = 15


class StatLine(BaseModel):
    value: str
    label: str


class ItemEffectOut(BaseModel):
    # "passive", "active", "unique", or "note" for text Riot did not name.
    kind: str
    name: str | None = None
    text: str


class ItemRefOut(BaseModel):
    id: int
    name: str
    icon_url: str | None = None
    cost: int = 0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def slug(self) -> str | None:
        return static_data.item_slug(self.id)


class ItemSummary(BaseModel):
    id: int
    name: str
    icon_url: str | None = None
    cost: int
    plaintext: str = ""
    tags: list[str] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def slug(self) -> str | None:
        return static_data.item_slug(self.id)
    stats: list[StatLine] = Field(default_factory=list)
    # Share of players with a purchase order who bought it, on the newest
    # patch. Null when there are no figures yet.
    bought_share: float | None = None


class ItemSection(BaseModel):
    key: str
    label: str
    items: list[ItemSummary] = Field(default_factory=list)


class ItemList(BaseModel):
    version: str | None = None
    # The slice the shares were read from.
    patch: str | None = None
    sections: list[ItemSection] = Field(default_factory=list)


class ItemSlotOut(BaseModel):
    # 1, 2, 3, or 4 for "4th or later".
    slot: int
    games: int
    # Share of this item's purchases made in this slot.
    share: float
    win_rate: float
    # Points against the same champions' other items in this slot, as a
    # fraction (0.021 is +2.1). Null below SLOT_MIN_GAMES.
    delta: float | None = None


class ItemChampionOut(BaseModel):
    champion: ChampionRef
    buyers: int
    # Share of that champion's players, with a purchase order, who bought it.
    share: float
    win_rate: float
    # Finished items only, and only from CHAMPION_MIN_BUYERS.
    delta: float | None = None
    minute: float | None = None
    # The slot this champion most often buys it in. Finished items only.
    usual_slot: int | None = None


class ItemFigures(BaseModel):
    patch: str
    queue_id: int
    rank_bracket: str
    players: int
    holders: int
    held_share: float
    ordered_players: int
    buyers: int
    bought_share: float
    # The plain win rate of players who bought it, shown small and labelled:
    # it mostly measures how late an item is bought.
    buyer_win_rate: float | None = None
    timed: int = 0
    minute_p25: float | None = None
    minute_p50: float | None = None
    minute_p75: float | None = None
    slots: list[ItemSlotOut] = Field(default_factory=list)
    # Weighted over every slot shown, as the page's headline.
    delta: float | None = None
    delta_games: int = 0
    slot_min_games: int = SLOT_MIN_GAMES
    champion_min_buyers: int = CHAMPION_MIN_BUYERS
    champions: list[ItemChampionOut] = Field(default_factory=list)


class ItemDetail(BaseModel):
    id: int
    name: str
    icon_url: str | None = None
    plaintext: str = ""
    cost: int
    combine_cost: int

    @computed_field  # type: ignore[prop-decorator]
    @property
    def slug(self) -> str | None:
        return static_data.item_slug(self.id)

    sell: int
    purchasable: bool
    tags: list[str] = Field(default_factory=list)
    # A section key, "transformed", or null for an item the guide does not list.
    group: str | None = None
    group_label: str | None = None
    on_rift: bool
    stats: list[StatLine] = Field(default_factory=list)
    effects: list[ItemEffectOut] = Field(default_factory=list)
    builds_from: list[ItemRefOut] = Field(default_factory=list)
    builds_into: list[ItemRefOut] = Field(default_factory=list)
    grows_from: ItemRefOut | None = None
    grows_into: list[ItemRefOut] = Field(default_factory=list)
    figures: ItemFigures | None = None
    # Why there are no figures, when there are none.
    figures_note: str | None = None


def _ref(sd: StaticDataService, item_id: int) -> ItemRefOut:
    info = sd.item_info(item_id)
    return ItemRefOut(
        id=item_id,
        name=info.name if info else f"Item {item_id}",
        icon_url=sd.item_icon(item_id),
        cost=info.cost if info else 0,
    )


def _recipe(sd: StaticDataService, item: ItemInfo, ids: list[int]) -> list[ItemRefOut]:
    """Recipe links a reader can follow. Riot's `into` lists other modes' copies
    and champion-only upgrades beside the real items, which showed Long Sword
    building into Manamune twice; a Rift item links only to what the guide
    itself shows, once each."""
    out: list[ItemRefOut] = []
    for item_id in dict.fromkeys(ids):
        target = sd.item_info(item_id)
        if target is None:
            continue
        if item.on_rift and target.group not in (*GUIDE_GROUPS, "transformed"):
            continue
        out.append(_ref(sd, item_id))
    return out


def _stats(info: ItemInfo) -> list[StatLine]:
    return [StatLine(value=v, label=label) for v, label in info.stats]


async def _newest_patch(db, queue_id: int) -> str | None:
    return default_patch(await aggregated_slices(db), queue_id)


@router.get("", response_model=ItemList)
async def list_items(db: DbDep, sd: StaticDep) -> ItemList:
    """Every item the guide lists, in sections."""
    patch = await _newest_patch(db, 420)
    shares: dict[int, float] = {}
    if patch:
        for row in (
            await db.execute(
                select(ItemStat).where(
                    ItemStat.patch == patch,
                    ItemStat.queue_id == 420,
                    ItemStat.rank_bracket == ALL_BRACKETS,
                )
            )
        ).scalars():
            if row.ordered_players:
                shares[row.item_id] = row.buyers / row.ordered_players

    by_group: dict[str, list[ItemSummary]] = {g: [] for g in GUIDE_GROUPS}
    for info in sd.guide_items():
        by_group[info.group].append(
            ItemSummary(
                id=info.id,
                name=info.name,
                icon_url=sd.item_icon(info.id),
                cost=info.cost,
                plaintext=info.plaintext,
                tags=info.tags,
                stats=_stats(info),
                bought_share=shares.get(info.id, 0.0 if shares else None),
            )
        )
    sections = []
    for key in GUIDE_GROUPS:
        items = by_group[key]
        if key == "finished":
            # How often it is bought, because that is the question the list is
            # opened with; cost breaks ties, and the name after that.
            items.sort(key=lambda i: (-(i.bought_share or 0), -i.cost, i.name))
        else:
            items.sort(key=lambda i: (i.cost, i.name))
        sections.append(ItemSection(key=key, label=SECTION_LABELS[key], items=items))
    return ItemList(version=sd.version, patch=patch, sections=sections)


@router.get("/{item}", response_model=ItemDetail)
async def get_item(
    item: str,
    db: DbDep,
    sd: StaticDep,
    patch: str | None = Query(None, description="Defaults to the newest patch held."),
    queue_id: int = Query(420),
    bracket: str = Query(ALL_BRACKETS, description="Crawl provenance, not a measured rank."),
) -> ItemDetail:
    # A slug ("blade-of-the-ruined-king") or, from older links, an id.
    info = sd.item_by_ref(item)
    if info is None:
        raise HTTPException(404, f"No item called {item!r}.")
    item_id = info.id

    detail = ItemDetail(
        id=info.id,
        name=info.name,
        icon_url=sd.item_icon(info.id),
        plaintext=info.plaintext,
        cost=info.cost,
        combine_cost=info.combine_cost,
        sell=info.sell,
        purchasable=info.purchasable,
        tags=info.tags,
        group=info.group,
        group_label=ITEM_LABELS.get(info.group or ""),
        on_rift=info.on_rift,
        stats=_stats(info),
        effects=[ItemEffectOut(kind=e.kind, name=e.name, text=e.text) for e in info.effects],
        # Built from keeps repeats: Berserker's Greaves takes two Daggers.
        builds_from=[_ref(sd, i) for i in info.builds_from],
        builds_into=sorted(_recipe(sd, info, info.builds_into), key=lambda r: (r.cost, r.name)),
        grows_from=_ref(sd, info.grows_from) if info.grows_from else None,
        grows_into=[_ref(sd, i) for i in info.grows_into],
    )

    if not info.on_rift:
        detail.figures_note = "Not sold on Summoner's Rift, so there are no figures for it."
        return detail
    if info.group == "transformed" and info.grows_from:
        parent = sd.item_info(info.grows_from)
        detail.figures_note = (
            f"Nobody buys this: it grows out of {parent.name if parent else 'another item'}, "
            "and its figures are counted there."
        )
        return detail

    bracket = (bracket or ALL_BRACKETS).upper()
    patch = patch or await _newest_patch(db, queue_id)
    if patch is None:
        detail.figures_note = "No games are stored yet."
        return detail
    where = (
        ItemStat.patch == patch,
        ItemStat.queue_id == queue_id,
        ItemStat.rank_bracket == bracket,
    )
    row = (await db.execute(select(ItemStat).where(*where, ItemStat.item_id == item_id))).scalar_one_or_none()
    # Any row in the slice carries its totals, so an item nobody bought still
    # gets its honest zero against a real denominator.
    totals = row or (await db.execute(select(ItemStat).where(*where).limit(1))).scalar_one_or_none()
    if totals is None:
        detail.figures_note = (
            f"The figures for patch {patch} have not been computed yet. "
            "They are rebuilt every night from the games we store."
        )
        return detail

    figures = ItemFigures(
        patch=patch,
        queue_id=queue_id,
        rank_bracket=bracket,
        players=totals.players,
        holders=row.holders if row else 0,
        held_share=(row.holders / totals.players) if row and totals.players else 0.0,
        ordered_players=totals.ordered_players,
        buyers=row.buyers if row else 0,
        bought_share=(row.buyers / totals.ordered_players) if row and totals.ordered_players else 0.0,
        buyer_win_rate=(row.buyer_wins / row.buyers) if row and row.buyers else None,
        timed=row.timed if row else 0,
        minute_p25=row.minute_p25 if row else None,
        minute_p50=row.minute_p50 if row else None,
        minute_p75=row.minute_p75 if row else None,
    )
    if row and row.slot_games:
        completions = sum(row.slot_games) or 1
        shown_games = shown_gain = 0.0
        for index in range(ITEM_SLOTS):
            games = row.slot_games[index]
            if not games:
                continue
            wins, expected = row.slot_wins[index], row.slot_expected[index]
            enough = games >= SLOT_MIN_GAMES
            figures.slots.append(
                ItemSlotOut(
                    slot=index + 1,
                    games=games,
                    share=games / completions,
                    win_rate=wins / games,
                    delta=(wins - expected) / games if enough else None,
                )
            )
            if enough:
                shown_games += games
                shown_gain += wins - expected
        if shown_games:
            figures.delta = shown_gain / shown_games
            figures.delta_games = int(shown_games)

    pairs = (
        await db.execute(
            select(ItemChampionStat)
            .where(
                ItemChampionStat.patch == patch,
                ItemChampionStat.queue_id == queue_id,
                ItemChampionStat.rank_bracket == bracket,
                ItemChampionStat.item_id == item_id,
            )
            .order_by(ItemChampionStat.buyers.desc())
            .limit(CHAMPION_LIMIT)
        )
    ).scalars()
    for p in pairs:
        slots = p.slot_games or []
        figures.champions.append(
            ItemChampionOut(
                champion=ChampionRef(
                    id=p.champion_id,
                    name=sd.champion_name(p.champion_id),
                    icon_url=sd.champion_icon(p.champion_id),
                ),
                buyers=p.buyers,
                share=p.buyers / p.champion_players if p.champion_players else 0.0,
                win_rate=p.buyer_wins / p.buyers if p.buyers else 0.0,
                delta=(
                    (p.buyer_wins - p.expected_wins) / p.buyers
                    if p.expected_wins is not None and p.buyers >= CHAMPION_MIN_BUYERS
                    else None
                ),
                minute=p.minute_p50,
                usual_slot=(slots.index(max(slots)) + 1) if slots and max(slots) else None,
            )
        )
    detail.figures = figures
    return detail
