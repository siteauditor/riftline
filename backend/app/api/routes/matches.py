"""One stored match, in full.

Match history serves twenty rows at a time and each row shows one player's
game. This serves the other nine: the whole scoreboard, the objectives both
teams took, and the model behind every Riftline score on it.

Its own endpoint on purpose. Folding this into `MatchHistoryResponse` would put
ten players times twenty matches of items, wards and damage on the wire every
time someone scrolls, to render a panel most of them never open.

Nothing here calls Riot. A match we do not hold is a 404, not a fetch: the
history endpoint is what puts matches in storage, and it is always the page you
arrived from.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Path
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import DbDep, StaticDep
from app.api.schemas import MatchDetailResponse, to_match_detail
from app.db.models import Match

router = APIRouter(prefix="/api/matches", tags=["matches"])


@router.get("/{match_id}", response_model=MatchDetailResponse)
async def get_match(
    db: DbDep,
    sd: StaticDep,
    match_id: str = Path(
        description="Riot match id, which carries its own platform: EUW1_7986353741.",
        min_length=6,
        max_length=32,
    ),
) -> MatchDetailResponse:
    """The full scoreboard for a match we already hold."""
    match = (
        await db.execute(
            select(Match)
            .where(Match.match_id == match_id.upper())
            .options(selectinload(Match.participants))
        )
    ).scalars().first()

    if match is None:
        raise HTTPException(
            404,
            f"{match_id} is not in storage. Open the player's match history first: "
            "that is what fetches a match from Riot.",
        )
    return to_match_detail(match, sd)
