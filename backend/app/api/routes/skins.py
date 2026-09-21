"""The skins players wear, counted from live games.

Its own router rather than a path under ``/api/champions``, because that one
owns ``/{champion_id}`` typed as ``int`` and a literal sibling segment would be
rejected as a bad integer instead of routed.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import DbDep, StaticDep
from app.api.schemas import ChampionRef
from app.services.skins import MIN_BOARD_SKINS, MIN_SKIN_SIGHTINGS, top_skins

router = APIRouter(prefix="/api/skins", tags=["skins"])


class TopSkin(BaseModel):
    champion: ChampionRef
    num: int
    name: str
    tile_url: str | None = None
    sightings: int
    # Every sighting of the same champion, so the count reads as a share.
    champion_sightings: int


class TopSkins(BaseModel):
    # Every sighting held, shown or not.
    total: int = 0
    min_sightings: int = MIN_SKIN_SIGHTINGS
    min_skins: int = MIN_BOARD_SKINS
    # Empty until enough skins clear the floor. Nothing here can be backfilled,
    # so on the day the table is created this is empty, and says so by being so.
    skins: list[TopSkin] = Field(default_factory=list)


@router.get("/top", response_model=TopSkins)
async def get_top_skins(db: DbDep, sd: StaticDep) -> TopSkins:
    total, board = await top_skins(db)
    names = {
        (c.champion_id, c.skin_num): next(
            (s.name for s in sd.champion_skins(c.champion_id) if s.num == c.skin_num),
            None,
        )
        for c in board
    }
    return TopSkins(
        total=total,
        skins=[
            TopSkin(
                champion=ChampionRef(
                    id=c.champion_id,
                    name=sd.champion_name(c.champion_id),
                    icon_url=sd.champion_icon(c.champion_id),
                ),
                num=c.skin_num,
                name=names[(c.champion_id, c.skin_num)]
                or f"{sd.champion_name(c.champion_id)} skin {c.skin_num}",
                tile_url=sd.champion_tile(c.champion_id, c.skin_num),
                sightings=c.sightings,
                champion_sightings=c.champion_sightings,
            )
            for c in board
        ],
    )
