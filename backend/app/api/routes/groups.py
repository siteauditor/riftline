"""Groups: made without an account, read by link, changed with the edit key.

The key travels in the ``X-Group-Key`` header. It never appears in a URL the
server sees: the page's edit link carries it after the ``#``, which browsers
keep to themselves, so it cannot land in an access log.

Reading a group never calls Riot. Filling it in does, through ``POST .../warm``,
which the page calls in the background while players are still loading: a few
seconds a pass, stopping at the key's reserve for searches.
"""

from __future__ import annotations

import asyncio
import logging
import time

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response

from app.api.deps import DbDep, PlayerServiceDep, RiotDep, SettingsDep, StaticDep
from app.api.schemas import (
    GroupCreatedResponse,
    GroupCreateRequest,
    GroupKeyResponse,
    GroupMemberAddedResponse,
    GroupMemberAddRequest,
    GroupMemberLabelRequest,
    GroupRenameRequest,
    GroupResponse,
    GroupWarmResponse,
)
from app.db.models import PlayerGroup, utcnow
from app.riot.limiter import SEARCH_RESERVE
from app.riot.routing import resolve_platform
from app.services.group_table import QUEUE_FILTERS, group_table, pending_count
from app.services.groups import (
    ADDS,
    CREATES,
    AddressThrottle,
    AlreadyMember,
    BadRiotId,
    Budget,
    GroupFull,
    add_member,
    create_group,
    delete_group,
    find_group,
    find_member,
    key_matches,
    members_of,
    remove_member,
    rename_group,
    rotate_key,
    set_label,
    warm_group,
)
from app.services.ranks import is_fresh

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/groups", tags=["groups"])

KEY_HEADER = "X-Group-Key"
# How long one warming pass may run. The page asks again as soon as a pass
# ends, so this bounds how long one request holds a connection, not how long
# filling a group takes.
WARM_SECONDS = 5.0
# One pass at a time in the process: two open groups, or two tabs of one, would
# otherwise fetch the same players twice and race on their history cursors.
_warm_lock = asyncio.Lock()
# Riot refused the key on the last pass (a development key lasts 24 hours).
# Pages stop asking until this passes, rather than every few seconds all night.
DEAD_KEY_BACKOFF = 600.0
_dead_until = 0.0


def _address(request: Request) -> str:
    """The visitor's address, as far as it can be trusted.

    Not ``request.client.host`` alone. uvicorn trusts every proxy here
    (``--forwarded-allow-ips *``) and so takes the left-most X-Forwarded-For
    entry, which is whatever the visitor sent: Cloudflare appends the real
    address after it rather than replacing it. Cloudflare does overwrite
    CF-Connecting-IP, and the origin answers only Cloudflare
    (deploy/cloudflare-only-web), so that header is the visitor.
    """
    forwarded = request.headers.get("cf-connecting-ip", "").strip()
    if forwarded:
        return forwarded
    return request.client.host if request.client else "unknown"


def _throttle(throttle: AddressThrottle, request: Request, settings, what: str) -> None:
    wait = throttle.check(_address(request), settings)
    if wait is not None:
        raise HTTPException(
            429,
            detail=f"Too many {what} from this address in an hour. Try again later.",
            headers={"Retry-After": str(int(wait))},
        )


def _can_fetch(settings) -> bool:
    return settings.has_key and time.monotonic() >= _dead_until


async def _group(db, slug: str) -> PlayerGroup:
    group = await find_group(db, slug)
    if group is None:
        raise HTTPException(404, "No group at this link. It may have been deleted.")
    return group


def _require_key(group: PlayerGroup, key: str | None) -> None:
    if not key_matches(group, key):
        raise HTTPException(403, "Changing a group needs its edit link.")


@router.post("", response_model=GroupCreatedResponse, status_code=201)
async def create(
    body: GroupCreateRequest, request: Request, db: DbDep, settings: SettingsDep
) -> GroupCreatedResponse:
    _throttle(CREATES, request, settings, "new groups")
    group, key = await create_group(db, body.name)
    return GroupCreatedResponse(slug=group.slug, name=group.name, key=key)


@router.get("/{slug}", response_model=GroupResponse)
async def get_group(
    slug: str,
    db: DbDep,
    sd: StaticDep,
    settings: SettingsDep,
    queue: str = Query("all", description="all, solo, flex, normal, swiftplay, aram, arena"),
    key: str | None = Header(None, alias=KEY_HEADER),
) -> GroupResponse:
    """The table and "played together", from storage only."""
    if queue not in QUEUE_FILTERS:
        raise HTTPException(400, f"Unknown queue {queue!r}. Valid: {', '.join(QUEUE_FILTERS)}")
    group = await _group(db, slug)
    members = await members_of(db, group.id)
    # For the nightly stage's order. At most once a minute: the page asks
    # again every few seconds while players load, and each stamp is a write.
    if not is_fresh(group.viewed_at, 60):
        group.viewed_at = utcnow()
        await db.commit()
    response = await group_table(
        db, settings, sd, group, members, queue_key=queue, can_edit=key_matches(group, key)
    )
    response.fetching = _can_fetch(settings)
    return response


@router.post("/{slug}/warm", response_model=GroupWarmResponse)
async def warm(slug: str, db: DbDep, riot: RiotDep, settings: SettingsDep) -> GroupWarmResponse:
    """One bounded pass of fetching what the group's players still lack."""
    global _dead_until
    group = await _group(db, slug)
    # Held as a plain int: a rollback inside the pass expires every loaded row,
    # and reading an expired one under asyncio raises instead of reloading.
    group_id = group.id
    members = await members_of(db, group_id)
    cap = int(settings.group_history_cap)
    if not members:
        return GroupWarmResponse(pending=0, fetching=_can_fetch(settings))
    if not _can_fetch(settings):
        return GroupWarmResponse(pending=await pending_count(db, members, cap), fetching=False)
    if _warm_lock.locked():
        # Another page is fetching. Its pass ends within WARM_SECONDS.
        return GroupWarmResponse(
            pending=await pending_count(db, members, cap), retry_after=WARM_SECONDS
        )

    budget = Budget(riot.limiter, deadline=time.monotonic() + WARM_SECONDS)
    games = 0
    async with _warm_lock:
        try:
            games = await warm_group(db, riot, settings, members, budget)
        except Exception:  # noqa: BLE001 -- a failed pass must not fail the page
            log.exception("groups: warming %s failed", slug)
            await db.rollback()
    if budget.stopped == "dead":
        _dead_until = time.monotonic() + DEAD_KEY_BACKOFF
    key_busy = budget.stopped == "key"
    members = await members_of(db, group_id)
    return GroupWarmResponse(
        pending=await pending_count(db, members, cap),
        fetching=_can_fetch(settings),
        key_busy=key_busy,
        retry_after=(
            round(max(1.0, riot.limiter.seconds_until_free(SEARCH_RESERVE + 10)), 1)
            if key_busy else None
        ),
        calls=budget.spent,
        games=games,
    )


@router.patch("/{slug}", status_code=204, response_class=Response)
async def rename(
    slug: str,
    body: GroupRenameRequest,
    db: DbDep,
    key: str | None = Header(None, alias=KEY_HEADER),
) -> Response:
    group = await _group(db, slug)
    _require_key(group, key)
    await rename_group(db, group, body.name)
    return Response(status_code=204)


@router.delete("/{slug}", status_code=204, response_class=Response)
async def delete(
    slug: str, db: DbDep, key: str | None = Header(None, alias=KEY_HEADER)
) -> Response:
    group = await _group(db, slug)
    _require_key(group, key)
    await delete_group(db, group)
    return Response(status_code=204)


@router.post("/{slug}/key", response_model=GroupKeyResponse)
async def new_edit_key(
    slug: str, db: DbDep, key: str | None = Header(None, alias=KEY_HEADER)
) -> GroupKeyResponse:
    """A new edit key. The old one, and every edit link carrying it, stops working."""
    group = await _group(db, slug)
    _require_key(group, key)
    return GroupKeyResponse(key=await rotate_key(db, group))


@router.post("/{slug}/members", response_model=GroupMemberAddedResponse, status_code=201)
async def add(
    slug: str,
    body: GroupMemberAddRequest,
    request: Request,
    db: DbDep,
    players: PlayerServiceDep,
    settings: SettingsDep,
    key: str | None = Header(None, alias=KEY_HEADER),
) -> GroupMemberAddedResponse:
    group = await _group(db, slug)
    _require_key(group, key)
    # Counted before the lookup: the limit is on Riot lookups, typos included.
    _throttle(ADDS, request, settings, "players added")
    try:
        member, player = await add_member(
            db, players, group, body.riot_id, body.platform, body.label
        )
    except (GroupFull, AlreadyMember) as exc:
        raise HTTPException(409, str(exc)) from None
    except BadRiotId as exc:
        raise HTTPException(400, str(exc)) from None
    return GroupMemberAddedResponse(
        puuid=member.puuid,
        riot_id=player.riot_id,
        platform=member.platform,
        platform_label=resolve_platform(member.platform).label,
    )


@router.patch("/{slug}/members/{puuid}", status_code=204, response_class=Response)
async def label(
    slug: str,
    puuid: str,
    body: GroupMemberLabelRequest,
    db: DbDep,
    key: str | None = Header(None, alias=KEY_HEADER),
) -> Response:
    group = await _group(db, slug)
    _require_key(group, key)
    member = await find_member(db, group, puuid)
    if member is None:
        raise HTTPException(404, "That player is not in this group.")
    await set_label(db, group, member, body.label)
    return Response(status_code=204)


@router.delete("/{slug}/members/{puuid}", status_code=204, response_class=Response)
async def remove(
    slug: str, puuid: str, db: DbDep, key: str | None = Header(None, alias=KEY_HEADER)
) -> Response:
    group = await _group(db, slug)
    _require_key(group, key)
    member = await find_member(db, group, puuid)
    if member is None:
        raise HTTPException(404, "That player is not in this group.")
    await remove_member(db, group, member)
    return Response(status_code=204)
