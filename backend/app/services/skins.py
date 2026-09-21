"""Skin sightings: which skins players wear, as the live tab sees them.

Riot publishes no skin for a finished game (see ``SkinSighting``), so the only
way to say which skins are worn is to count them in live games as they are
looked up. This module does the counting and the reading back, and every figure
it hands out carries the number of sightings behind it.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.db.base import SessionLocal
from app.db.models import SkinSighting

log = logging.getLogger(__name__)

# Below this many sightings of one champion, per skin counts are withheld: with
# a dozen sightings the "most worn skin" is whoever happened to be looked up.
MIN_CHAMPION_SIGHTINGS = 20
# A skin needs this many sightings of its own to be listed on the site wide
# board, and the board needs this many skins before it is drawn at all.
MIN_SKIN_SIGHTINGS = 5
MIN_BOARD_SKINS = 3


async def record_sightings(
    *,
    platform: str,
    game_id: int,
    queue_id: int,
    in_progress: bool,
    participants: Iterable[Any],
    chroma_parent: dict[int, int],
) -> int:
    """Count what each player in a live game is wearing. Returns rows written.

    Only once the game is under way: a skin chosen in champion select can still
    change before loading, and champion select is where the live page spends
    its first minute. Bots are skipped. A chroma is recorded as the skin it
    recolours, so the board ranks skins and every entry on it has art.

    Runs in a session of its own and swallows its own failures. A lost sighting
    costs one row of a board that says how many rows it stands on; a failed
    write inside the request's session would roll back and expire objects the
    live response is still being built from.
    """
    if not in_progress or not game_id:
        return 0
    rows = []
    # The spectator's own order, which nothing downstream reorders, so the
    # index is the same on every poll of the same game.
    for index, p in enumerate(participants):
        skin, champion_id = getattr(p, "skin_index", None), getattr(p, "champion_id", 0)
        if getattr(p, "state", None) == "bot" or skin is None or not champion_id:
            continue
        parent = chroma_parent.get(champion_id * 1000 + skin)
        if parent is not None:
            skin = parent % 1000
        rows.append(
            {
                "platform": platform.lower(),
                "game_id": game_id,
                "participant_index": index,
                "champion_id": champion_id,
                "skin_num": skin,
                "queue_id": queue_id,
            }
        )
    if not rows:
        return 0
    try:
        async with SessionLocal() as session:
            # Read first rather than lean on ON CONFLICT, which is a dialect
            # extension this schema otherwise avoids. After the first poll of
            # a game every row is already here and this is the whole cost.
            seen = set(
                (
                    await session.execute(
                        select(SkinSighting.participant_index).where(
                            SkinSighting.platform == rows[0]["platform"],
                            SkinSighting.game_id == game_id,
                        )
                    )
                ).scalars()
            )
            fresh = [r for r in rows if r["participant_index"] not in seen]
            if not fresh:
                return 0
            session.add_all(SkinSighting(**r) for r in fresh)
            try:
                await session.commit()
            except IntegrityError:
                # Two polls of the same game raced and the other one wrote
                # these rows. Nothing is lost.
                await session.rollback()
                return 0
            return len(fresh)
    except Exception as exc:  # noqa: BLE001 -- never fail a live lookup over this
        log.warning("could not record skin sightings for game %s: %s", game_id, exc)
        return 0


@dataclass(slots=True)
class ChampionSkinCounts:
    # Every sighting of this champion, whether or not the counts are shown.
    total: int
    # skin number -> sightings. Empty below MIN_CHAMPION_SIGHTINGS.
    by_skin: dict[int, int]


async def champion_skin_counts(session, champion_id: int) -> ChampionSkinCounts:
    rows = (
        await session.execute(
            select(SkinSighting.skin_num, func.count())
            .where(SkinSighting.champion_id == champion_id)
            .group_by(SkinSighting.skin_num)
        )
    ).all()
    total = sum(count for _, count in rows)
    if total < MIN_CHAMPION_SIGHTINGS:
        return ChampionSkinCounts(total=total, by_skin={})
    return ChampionSkinCounts(total=total, by_skin={num: count for num, count in rows})


@dataclass(slots=True)
class SkinCount:
    champion_id: int
    skin_num: int
    sightings: int
    # Every sighting of the same champion, so a count can be read as a share.
    champion_sightings: int


async def top_skins(session, limit: int = 12) -> tuple[int, list[SkinCount]]:
    """The most worn skins site wide, and the total they were counted from."""
    total = (await session.execute(select(func.count()).select_from(SkinSighting))).scalar() or 0
    per_champion = dict(
        (
            await session.execute(
                select(SkinSighting.champion_id, func.count()).group_by(SkinSighting.champion_id)
            )
        ).all()
    )
    rows = (
        await session.execute(
            select(SkinSighting.champion_id, SkinSighting.skin_num, func.count().label("n"))
            # The base skin is what a player wears by not choosing one. It
            # would top this board on every champion and say nothing; the
            # per champion counts keep it, as the share wearing no skin at all.
            .where(SkinSighting.skin_num != 0)
            .group_by(SkinSighting.champion_id, SkinSighting.skin_num)
            .having(func.count() >= MIN_SKIN_SIGHTINGS)
            .order_by(func.count().desc(), SkinSighting.champion_id, SkinSighting.skin_num)
            .limit(limit)
        )
    ).all()
    board = [
        SkinCount(
            champion_id=champion_id,
            skin_num=skin_num,
            sightings=n,
            champion_sightings=per_champion.get(champion_id, n),
        )
        for champion_id, skin_num, n in rows
    ]
    return total, board if len(board) >= MIN_BOARD_SKINS else []
