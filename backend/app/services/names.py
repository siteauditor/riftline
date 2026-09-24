"""Riot IDs confirmed for the players who qualify for a page.

A profile is prerendered for every player with enough scored ranked games in
one role (`profile_floor`), under the Riot ID account-v1 last confirmed for
them (`Player.search_name`, `seo.profile_pages`). Most such players were never
searched: their rows were made from the lobbies they played in and carry the
name they had in those games, which may have changed since and which no lookup
answers to. Measured on 2026-09-24: 515 players met the floor in the local
corpus and 20 had a page, the other 495 rows made from lobbies and never
asked about.

The nightly `names` stage asks account-v1 who holds each such account now, and
the active region where it plays (`PlayerService.confirm_account`, the same two
calls and the same write as a cold search), newest game first, at most
`NAME_CHECKS_NIGHTLY` players a night and never with the calls kept for
searches. The render that follows gives each confirmed player a page. An
account Riot does not know is stamped and asked again after `RECHECK_DAYS`.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Player, utcnow
from app.riot.client import RiotClient
from app.riot.errors import RiotApiError, RiotNotFound, RiotRateLimited, RiotUnauthorized
from app.services.groups import Budget
from app.services.players import PlayerService
from app.services.profile_stats import profile_floor

log = logging.getLogger(__name__)

# How long an unconfirmed name, or an account Riot did not know, waits before
# it is asked about again. A confirmed player is not asked again at all: their
# searches keep the name fresh, and the repair clears the stamp when their
# games move to another shard.
RECHECK_DAYS = 30

# Two calls a player: account-v1, then the active region.
CALLS_PER_PLAYER = 2

EXAMPLES = 8


@dataclass
class NamesReport:
    """What the stage asked and what Riot answered."""

    due: int = 0
    asked: int = 0
    confirmed: int = 0
    renamed: int = 0
    moved: int = 0
    unknown: int = 0
    failed: int = 0
    calls: int = 0
    # Why it ended before its list did: "key" (Riot rate limited it) or
    # "dead" (Riot refused the key). The reserve for searches is waited for.
    stopped: str | None = None
    examples: list[str] = field(default_factory=list)

    def lines(self) -> list[str]:
        return [
            f"floor players to confirm: {self.due}",
            f"asked:                    {self.asked}",
            f"confirmed:                {self.confirmed}",
            f"  under another name:     {self.renamed}",
            f"  on another home:        {self.moved}",
            f"unknown to Riot:          {self.unknown}",
            f"failed:                   {self.failed}",
            f"Riot calls:               {self.calls}",
            f"stopped:                  {self.stopped or 'no'}",
        ]


async def names_due(session: AsyncSession, *, now: datetime | None = None) -> list[str]:
    """Floor players whose Riot ID wants confirming, newest game first.

    Never asked (no stamp), which is every row made from a lobby and a searched
    row the repair flagged; or asked more than ``RECHECK_DAYS`` ago without a
    confirmed name, which is an account Riot did not know then, or a row that
    gave its Riot ID up to another account.
    """
    floor = await profile_floor(session)
    if not floor:
        return []
    cutoff = (now or utcnow()) - timedelta(days=RECHECK_DAYS)
    due = (
        await session.execute(
            select(Player.puuid).where(
                Player.puuid.in_(list(floor)),
                or_(
                    Player.account_fetched_at.is_(None),
                    and_(Player.search_name.is_(None), Player.account_fetched_at < cutoff),
                ),
            )
        )
    ).scalars().all()
    return sorted(due, key=lambda puuid: floor[puuid], reverse=True)


async def _room(budget: Budget) -> bool:
    """Room above the search reserve for one player's calls, waited for."""
    while (granted := await budget.take(CALLS_PER_PLAYER)) and granted < CALLS_PER_PLAYER:
        # One slot free is not enough for both calls; the next frees soon.
        await asyncio.sleep(1.0)
    return granted >= CALLS_PER_PLAYER


async def confirm_names(
    session: AsyncSession,
    client: RiotClient | None,
    settings,
    *,
    players: int,
    dry_run: bool = False,
) -> NamesReport:
    """Confirm the Riot ID and home of up to ``players`` floor players.

    A dry run counts who is due and asks Riot nothing, so it needs no client.
    """
    report = NamesReport()
    due = await names_due(session)
    report.due = len(due)
    picked = due[: max(0, players)]
    if dry_run:
        for puuid in picked[:EXAMPLES]:
            player = await session.get(Player, puuid)
            if player is not None:
                report.examples.append(
                    f"{player.game_name or '?'}#{player.tag_line or '?'} on {player.platform}"
                )
        return report

    assert client is not None, "only a dry run goes without a client"
    budget = Budget(client.limiter, wait=True)
    service = PlayerService(session, client, settings)
    try:
        for puuid in picked:
            if not await _room(budget):
                report.stopped = budget.stopped
                break
            player = await session.get(Player, puuid)
            if player is None:
                continue
            before = (player.game_name, player.tag_line, player.platform)
            report.asked += 1
            try:
                player = await service.confirm_account(player)
            except RiotNotFound:
                # Riot knows no such account now. Stamped, so it waits
                # RECHECK_DAYS rather than costing a call every night.
                await session.rollback()
                player = await session.get(Player, puuid)
                if player is not None:
                    player.account_fetched_at = utcnow()
                    await session.commit()
                report.unknown += 1
                budget.spend(1)
                continue
            except RiotUnauthorized:
                await session.rollback()
                report.stopped = "dead"
                break
            except RiotRateLimited:
                await session.rollback()
                report.stopped = "key"
                break
            except RiotApiError as exc:
                # One account's failure is not the stage's: the next one.
                await session.rollback()
                log.warning("names: confirming %s failed: %s", puuid[:8], exc)
                report.failed += 1
                budget.spend(CALLS_PER_PLAYER)
                continue
            budget.spend(CALLS_PER_PLAYER)
            report.confirmed += 1
            after = (player.game_name, player.tag_line, player.platform)
            renamed = before[:2] != after[:2]
            if renamed:
                report.renamed += 1
            if before[2] != after[2]:
                report.moved += 1
            if len(report.examples) < EXAMPLES and (renamed or before[2] != after[2]):
                report.examples.append(
                    f"{before[0] or '?'}#{before[1] or '?'} on {before[2]} is "
                    f"{after[0]}#{after[1]} on {after[2]}"
                )
    finally:
        report.calls = budget.spent
        log.info(
            "names: %d of %d due asked, %d confirmed, %d unknown, %d failed, stopped: %s",
            report.asked, report.due, report.confirmed, report.unknown, report.failed,
            report.stopped or "no",
        )
    return report


__all__ = ["CALLS_PER_PLAYER", "RECHECK_DAYS", "NamesReport", "confirm_names", "names_due"]
