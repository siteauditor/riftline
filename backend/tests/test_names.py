"""The nightly names stage: a player who qualifies for a page gets one.

A profile is prerendered only under a Riot ID account-v1 has confirmed, and
most players who met the floor were rows made from lobbies, named by their
games and never asked about: 495 of 515 on the local corpus (2026-09-24). The
stage asks account-v1 and the active region for each, newest game first, within
a nightly cap. See ``app/services/names.py``.

The suite shares one database, so every player here has its own named puuid
and its games are dated after anything another module stores: the stage takes
the newest first, so these are the ones a capped run reaches. Each test's are
newer than the last test's too, since some tests leave players due.
"""

from __future__ import annotations

from datetime import timedelta

import httpx
import pytest
import respx

from app.config import get_settings
from app.db.base import SessionLocal
from app.db.models import utcnow
from app.riot.client import RiotClient
from app.services.names import RECHECK_DAYS, confirm_names, names_due
from app.services.players import normalize_riot_name
from app.services.profile_stats import MIN_SCORED_FOR_PROFILE
from app.services.seo import profile_pages
from tests.test_homes import row, seed_games, seed_player

pytestmark = pytest.mark.riot_region

BY_PUUID = r".*/riot/account/v1/accounts/by-puuid/(?P<puuid>[^/?]+)"
REGION = r".*/riot/account/v1/region/by-game/lol/by-puuid/(?P<puuid>[^/?]+)"

# Later than any game another module stores.
LATE = 2_100_000_000_000


def answer(accounts: dict[str, tuple[str, str] | int], regions: dict[str, str]):
    """Account-v1 and the active region, per puuid. A number is a status."""
    asked: list[str] = []

    def account(request, puuid):
        asked.append(puuid)
        found = accounts.get(puuid, 404)
        if isinstance(found, int):
            return httpx.Response(found, json={"status": {"status_code": found}})
        return httpx.Response(200, json={"puuid": puuid, "gameName": found[0], "tagLine": found[1]})

    def region(request, puuid):
        return httpx.Response(
            200, json={"puuid": puuid, "game": "lol", "region": regions.get(puuid, "euw1")}
        )

    respx.get(url__regex=BY_PUUID).mock(side_effect=account)
    respx.get(url__regex=REGION).mock(side_effect=region)
    return asked


async def floor_stub(puuid: str, name: str, platform: str, *, newest: int, **seed) -> None:
    """A row made from a lobby, with enough scored ranked games for a page."""
    await seed_player(puuid, name, "EUW", platform, searched=False, **seed)
    await seed_games(
        puuid, "EUW1", MIN_SCORED_FOR_PROFILE, prefix=f"NM{puuid[:12]}",
        creation=newest - MIN_SCORED_FOR_PROFILE * 1000,
    )


async def run(players: int):
    async with SessionLocal() as session, RiotClient("RGAPI-test-key") as riot:
        return await confirm_names(session, riot, get_settings(), players=players)


@respx.mock
async def test_a_stub_that_met_the_floor_is_confirmed_and_gets_its_page():
    puuid = "names-confirmed".ljust(78, "0")
    await floor_stub(puuid, "Lobbyname", "euw1", newest=LATE + 1_000_000)
    async with SessionLocal() as session:
        before = {p.path for p in await profile_pages(session)}
    assert "/summoner/euw1/Lobbyname/EUW" not in before

    asked = answer({puuid: ("Lobbyname", "EUW")}, {puuid: "euw1"})
    report = await run(players=1)

    assert asked == [puuid]
    assert (report.asked, report.confirmed, report.unknown) == (1, 1, 0)
    player = await row(puuid)
    assert player.search_name == normalize_riot_name("Lobbyname")
    assert player.account_fetched_at is not None
    async with SessionLocal() as session:
        assert "/summoner/euw1/Lobbyname/EUW" in {p.path for p in await profile_pages(session)}
        # Confirmed, so the next night leaves it alone.
        assert puuid not in await names_due(session)


@respx.mock
async def test_a_renamed_player_is_listed_under_the_name_they_hold_now_on_their_home():
    puuid = "names-renamed".ljust(78, "0")
    await floor_stub(puuid, "Oldname", "kr", newest=LATE + 2_000_000)
    # Another row still answers to the new name: it gave it up.
    stale = "names-renamed-stale".ljust(78, "0")
    await seed_player(stale, "Newname", "EUW", "euw1", account_at=utcnow() - timedelta(days=90))

    answer({puuid: ("Newname", "EUW")}, {puuid: "euw1"})
    report = await run(players=1)

    assert (report.renamed, report.moved) == (1, 1)
    player = await row(puuid)
    assert (player.game_name, player.platform) == ("Newname", "euw1")
    assert (await row(stale)).search_name is None
    async with SessionLocal() as session:
        paths = {p.path for p in await profile_pages(session)}
    assert "/summoner/euw1/Newname/EUW" in paths
    assert not any(p.endswith("/Oldname/EUW") for p in paths)


@respx.mock
async def test_an_account_riot_does_not_know_waits_rather_than_costing_a_call_a_night():
    puuid = "names-unknown".ljust(78, "0")
    await floor_stub(puuid, "Ghost", "euw1", newest=LATE + 3_000_000)

    asked = answer({puuid: 404}, {})
    report = await run(players=1)

    assert (report.asked, report.unknown, report.confirmed) == (1, 1, 0)
    player = await row(puuid)
    assert player.search_name is None and player.account_fetched_at is not None
    async with SessionLocal() as session:
        assert puuid not in await names_due(session)
        later = utcnow() + timedelta(days=RECHECK_DAYS + 1)
        assert puuid in await names_due(session, now=later)
    assert asked == [puuid]


@respx.mock
async def test_a_refused_key_stops_the_stage_and_asks_nobody_else():
    first = "names-dead-first".ljust(78, "0")
    second = "names-dead-second".ljust(78, "0")
    await floor_stub(first, "Deadkey", "euw1", newest=LATE + 5_000_000)
    await floor_stub(second, "Neverasked", "euw1", newest=LATE + 4_000_000)

    # 401: the key itself. A 403 without rate-limit headers is Riot refusing
    # the endpoint, which is one account's failure, not the key's.
    asked = answer({first: 401, second: ("Neverasked", "EUW")}, {})
    report = await run(players=2)

    assert report.stopped == "dead"
    assert asked == [first]
    assert (await row(first)).account_fetched_at is None
    assert (await row(second)).search_name is None


@respx.mock
async def test_the_cap_takes_the_newest_games_first_and_leaves_the_floor_alone():
    newer = "names-cap-newer".ljust(78, "0")
    older = "names-cap-older".ljust(78, "0")
    await floor_stub(newer, "Capnewer", "euw1", newest=LATE + 7_000_000)
    await floor_stub(older, "Capolder", "euw1", newest=LATE + 6_000_000)
    # Nine scored games in the role: under the floor, so never asked.
    below = "names-cap-below".ljust(78, "0")
    await seed_player(below, "Capbelow", "EUW", "euw1", searched=False)
    await seed_games(
        below, "EUW1", MIN_SCORED_FOR_PROFILE - 1, prefix="NMBELOW", creation=LATE + 7_500_000
    )
    async with SessionLocal() as session:
        due = await names_due(session)
    assert newer in due and older in due and below not in due
    assert due.index(newer) < due.index(older)

    asked = answer({newer: ("Capnewer", "EUW"), older: ("Capolder", "EUW")}, {})
    await run(players=1)

    assert asked == [newer]
    assert (await row(older)).search_name is None


@respx.mock
async def test_a_searched_row_the_repair_flagged_is_asked_again():
    """The repair clears the stamp when a player's games moved shard."""
    puuid = "names-flagged".ljust(78, "0")
    await seed_player(puuid, "Flagged", "EUW", "kr", account_at=None)
    await seed_games(
        puuid, "EUW1", MIN_SCORED_FOR_PROFILE, prefix="NMFLAG", creation=LATE + 8_000_000
    )
    answer({puuid: ("Flagged", "EUW")}, {puuid: "euw1"})
    report = await run(players=1)

    assert (report.confirmed, report.moved) == (1, 1)
    assert (await row(puuid)).platform == "euw1"
