"""Ranked ladders.

Its own router rather than a path under ``/api/champions``, because that one
owns ``/{champion_id}`` typed as ``int`` and a literal sibling segment would be
rejected as a bad integer instead of routed.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.deps import LadderServiceDep
from app.api.schemas import QUEUE_LABELS, epoch_ms, numeric_rank
from app.riot.routing import resolve_platform
from app.services.ladders import APEX_TIERS, DIVISIONS, QUEUE_BY_ID, STANDARD_TIERS

router = APIRouter(prefix="/api/leaderboard", tags=["leaderboard"])

ALL_TIERS = (*APEX_TIERS, *STANDARD_TIERS)


class LeaderboardRow(BaseModel):
    position: int
    puuid: str
    # None where we have never seen this account. league-v4 carries no display
    # name at all, so a region we have not crawled is genuinely a list of
    # anonymous ids until somebody pays an account-v1 call each to name it.
    riot_id: str | None = None
    # Riot has no account for this entry, so no name is coming.
    no_riot_id: bool = False
    tier: str
    division: str | None = None
    league_points: int = 0
    wins: int = 0
    losses: int = 0
    games: int = 0
    win_rate: float = 0.0
    hot_streak: bool = False
    veteran: bool = False
    fresh_blood: bool = False
    inactive: bool = False
    numeric_rank: int = 0


class LeaderboardResponse(BaseModel):
    platform: str
    platform_label: str
    queue_id: int
    queue_label: str
    tier: str
    division: str | None = None
    page: int
    per_page: int
    # How many rows we hold and can page through.
    total: int
    # The ladder's real size, and null when we genuinely do not know it. The
    # apex endpoints return a whole league in one response so it is exact there;
    # the paged endpoint gives no total and we scan only a few pages, so making
    # one up from the rows we happened to see would be a fabricated denominator.
    total_on_ladder: int | None = None
    # True when the ladder continues past what we store, either because the row
    # cap bit or because we stopped paging.
    truncated: bool = False
    has_more: bool = False
    # How many rows on *this page* we could name. Reported rather than hidden:
    # coverage is a property of which ladders we have crawled, and a table full
    # of unnamed rows should say why.
    named_on_page: int = 0
    # True when names were left for later so the key keeps a reserve for
    # player searches. The rest are waiting on Riot, not unknown.
    names_held_back: bool = False
    # With it, seconds until the key has room to name the rest.
    names_retry_after: float | None = None
    fetched_at: int | None = None
    rows: list[LeaderboardRow] = Field(default_factory=list)


class PlatformOptionOut(BaseModel):
    id: str
    label: str


class QueueOptionOut(BaseModel):
    id: int
    label: str


class LeaderboardSlices(BaseModel):
    platforms: list[PlatformOptionOut]
    queues: list[QueueOptionOut]
    tiers: list[str]
    divisions: list[str]
    apex_tiers: list[str]


@router.get("/slices", response_model=LeaderboardSlices)
async def get_slices() -> LeaderboardSlices:
    """What can be asked for. Apex tiers take no division."""
    from app.riot.routing import PLATFORMS

    return LeaderboardSlices(
        # Every platform the route will actually serve. Filtering one out
        # here while `/{platform}` still accepts it meant a URL could request a
        # ladder the filter bar refused to offer, and the select then showed a
        # different region than the table.
        platforms=[
            {"id": p.id, "label": p.label} for p in dict.fromkeys(PLATFORMS.values())
        ],
        queues=[
            {"id": qid, "label": QUEUE_LABELS.get(qtype, qtype)}
            for qid, qtype in QUEUE_BY_ID.items()
        ],
        tiers=list(ALL_TIERS),
        divisions=list(DIVISIONS),
        apex_tiers=list(APEX_TIERS),
    )


@router.get("/{platform}", response_model=LeaderboardResponse)
async def get_leaderboard(
    platform: str,
    ladders: LadderServiceDep,
    queue_id: int = Query(420, description="420 solo/duo, 440 flex."),
    tier: str = Query("CHALLENGER"),
    division: str = Query("I", description="Ignored for the apex tiers."),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
) -> LeaderboardResponse:
    """One page of a ranked ladder, from a cached snapshot.

    The snapshot refreshes itself when stale. If that refresh fails and we
    already hold a snapshot, the stale one is served rather than failing the
    page: a ladder that is fifteen minutes old is worth far more than an error.
    """
    tier = tier.upper()
    if tier not in ALL_TIERS:
        raise HTTPException(400, f"tier must be one of {', '.join(ALL_TIERS)}")
    division = division.upper()
    if tier not in APEX_TIERS and division not in DIVISIONS:
        raise HTTPException(400, f"division must be one of {', '.join(DIVISIONS)}")
    if queue_id not in QUEUE_BY_ID:
        raise HTTPException(
            400, f"queue_id must be one of {', '.join(str(q) for q in QUEUE_BY_ID)}"
        )

    resolved = resolve_platform(platform)
    result = await ladders.page(
        resolved, queue_id=queue_id, tier=tier, division=division,
        page=page, per_page=per_page,
    )

    return LeaderboardResponse(
        platform=result.platform,
        platform_label=resolved.label,
        queue_id=result.queue_id,
        queue_label=QUEUE_LABELS.get(result.queue_type, result.queue_type),
        tier=result.tier,
        division=result.division,
        page=result.page,
        per_page=result.per_page,
        total=result.total_stored,
        total_on_ladder=result.total_entries,
        truncated=result.truncated,
        has_more=result.page * result.per_page < result.total_stored,
        named_on_page=result.named_on_page,
        names_held_back=result.names_held_back,
        names_retry_after=result.names_retry_after,
        fetched_at=epoch_ms(result.fetched_at),
        rows=[
            LeaderboardRow(
                position=r.position,
                puuid=r.puuid,
                riot_id=(
                    f"{r.game_name}#{r.tag_line}" if r.game_name and r.tag_line else None
                ),
                no_riot_id=r.no_riot_id,
                tier=r.tier,
                division=None if r.tier in APEX_TIERS else r.division,
                league_points=r.league_points,
                wins=r.wins,
                losses=r.losses,
                games=r.wins + r.losses,
                win_rate=(
                    r.wins / (r.wins + r.losses) if (r.wins + r.losses) else 0.0
                ),
                hot_streak=r.hot_streak,
                veteran=r.veteran,
                fresh_blood=r.fresh_blood,
                inactive=r.inactive,
                numeric_rank=numeric_rank(r.tier, r.division, r.league_points),
            )
            for r in result.rows
        ],
    )
