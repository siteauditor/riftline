"""Ladder snapshots, ordering, and the name coverage the UI has to admit to.

league-v4 returns no display name at all, so how many rows a leaderboard can
name is a property of which ladders we happen to have crawled: measured at 99.3%
for EUW Challenger and 0% for NA. These pin that the response reports that
honestly rather than rendering a table of anonymous ids without explanation.
"""

from __future__ import annotations

import httpx
import respx
from sqlalchemy import select

from app.config import get_settings
from app.db.base import SessionLocal
from app.db.models import LadderEntry, Match, MatchParticipant, Player
from app.riot.client import RiotClient
from app.services.ladders import (
    MAX_ROWS_PER_SLICE,
    LadderService,
    normalise_entries,
)

PLATFORM = "euw1"


def service(session) -> LadderService:
    return LadderService(session, RiotClient("RGAPI-test-key"), get_settings())


def apex_entry(puuid: str, lp: int, wins=100, losses=90):
    return {
        "puuid": puuid, "leaguePoints": lp, "rank": "I", "wins": wins,
        "losses": losses, "hotStreak": False, "veteran": True,
        "freshBlood": False, "inactive": False,
    }


def mock_apex(entries, tier="CHALLENGER"):
    return respx.get(url__regex=r".*/lol/league/v4/challengerleagues/.*").mock(
        return_value=httpx.Response(
            200, json={"tier": tier, "queue": "RANKED_SOLO_5x5", "entries": entries}
        )
    )


# -------------------------------------------------------------- normalising


def test_the_two_riot_payload_shapes_normalise_to_one():
    """Apex puts the tier on the league object; the paged endpoint puts it on
    every row. Downstream should never have to know which it was."""
    apex = {"tier": "CHALLENGER", "entries": [apex_entry("a" * 78, 900)]}
    paged = [dict(apex_entry("b" * 78, 40), tier="GOLD", queueType="RANKED_SOLO_5x5")]

    assert normalise_entries(apex, "CHALLENGER", "I")[0]["tier"] == "CHALLENGER"
    assert normalise_entries(paged, "GOLD", "II")[0]["tier"] == "GOLD"


def test_entries_without_a_puuid_are_dropped():
    assert normalise_entries({"entries": [{"leaguePoints": 10}]}, "GOLD", "I") == []


# ----------------------------------------------------------------- snapshot


@respx.mock
async def test_positions_come_from_our_own_sort():
    """Riot does not promise an order for these endpoints. Trusting it would
    leave the ladder subtly shuffled with nothing ever failing."""
    mock_apex([
        apex_entry("LAD-low".ljust(78, "z"), 100),
        apex_entry("LAD-high".ljust(78, "z"), 4724),
        apex_entry("LAD-mid".ljust(78, "z"), 900),
    ])
    async with SessionLocal() as session:
        await service(session).refresh(PLATFORM, tier="CHALLENGER")

    async with SessionLocal() as session:
        rows = list((await session.execute(
            select(LadderEntry)
            .where(LadderEntry.platform == PLATFORM, LadderEntry.tier == "CHALLENGER")
            .order_by(LadderEntry.position)
        )).scalars())
    assert [r.position for r in rows] == [1, 2, 3]
    assert [r.league_points for r in rows] == [4724, 900, 100]


@respx.mock
async def test_a_refresh_replaces_the_snapshot_rather_than_appending():
    mock_apex([apex_entry(f"LAD-r{i}".ljust(78, "z"), 1000 - i) for i in range(4)])
    async with SessionLocal() as session:
        first = await service(session).refresh(PLATFORM, tier="CHALLENGER")
    mock_apex([apex_entry(f"LAD-r{i}".ljust(78, "z"), 1000 - i) for i in range(2)])
    async with SessionLocal() as session:
        second = await service(session).refresh(PLATFORM, tier="CHALLENGER")

    assert (first, second) == (4, 2)
    async with SessionLocal() as session:
        total = len(list((await session.execute(
            select(LadderEntry).where(
                LadderEntry.platform == PLATFORM, LadderEntry.tier == "CHALLENGER"
            )
        )).scalars()))
    assert total == 2, "a stale tail would leave phantom players on the ladder"


@respx.mock
async def test_a_huge_ladder_is_capped_and_says_so():
    """Master is ten thousand entries and we have a name for almost none of
    them, so the tail is never stored. Reporting the stored count as the ladder
    size would under-state it by an order of magnitude, silently."""
    mock_apex(
        [apex_entry(f"LAD-big{i}".ljust(78, "z"), 5000 - i) for i in range(1200)]
    )
    async with SessionLocal() as session:
        stored = await service(session).refresh(PLATFORM, tier="CHALLENGER")
        page = await service(session).page(
            PLATFORM, tier="CHALLENGER", resolve_names=False
        )
    assert stored == MAX_ROWS_PER_SLICE
    assert page.total_stored == MAX_ROWS_PER_SLICE
    assert page.total_entries == 1200, "an apex response is the whole league"
    assert page.truncated is True


@respx.mock
async def test_a_paged_ladder_never_invents_a_total():
    """The paged endpoint gives no total and we scan only a few pages, so the
    rows we happened to see are not the ladder size. Claiming they were would
    be a fabricated denominator that reads as authoritative."""
    full_page = [
        dict(apex_entry(f"LAD-pgd{p}-{i}".ljust(78, "z"), 99), tier="DIAMOND")
        for p in range(3)
        for i in range(10)
    ]
    pages = iter([full_page[0:10], full_page[10:20], full_page[20:30]])
    respx.get(url__regex=r".*/lol/league/v4/entries/RANKED_SOLO_5x5/.*").mock(
        side_effect=lambda request: httpx.Response(200, json=next(pages, []))
    )
    async with SessionLocal() as session:
        await service(session).refresh(
            PLATFORM, tier="DIAMOND", division="I", pages=3
        )
        page = await service(session).page(
            PLATFORM, tier="DIAMOND", division="I", resolve_names=False
        )
    assert page.total_stored == 30
    assert page.total_entries is None, "we do not know how big Diamond I is"
    assert page.truncated is True, "but we do know we stopped early"


@respx.mock
async def test_a_paged_ladder_that_runs_out_does_know_its_total():
    """If a page comes back empty we have reached the end, so the count is real."""
    pages = iter([
        [dict(apex_entry(f"LAD-end{i}".ljust(78, "z"), 99), tier="IRON")
         for i in range(4)],
        [],
    ])
    respx.get(url__regex=r".*/lol/league/v4/entries/RANKED_SOLO_5x5/.*").mock(
        side_effect=lambda request: httpx.Response(200, json=next(pages, []))
    )
    async with SessionLocal() as session:
        await service(session).refresh(PLATFORM, tier="IRON", division="IV", pages=5)
        page = await service(session).page(
            PLATFORM, tier="IRON", division="IV", resolve_names=False
        )
    assert page.total_entries == 4
    assert page.truncated is False


@respx.mock
async def test_an_empty_ladder_is_still_cached():
    """Deriving the snapshot age from the stored rows meant a ladder that
    legitimately comes back empty had no rows to derive it from, so it was
    re-fetched on every single page view."""
    # Its own platform: the suite shares a database and the freshness cursor
    # another test wrote for this slice would make the first view a cache hit.
    route = mock_apex([])
    async with SessionLocal() as session:
        svc = service(session)
        for _ in range(3):
            page = await svc.page("kr", tier="CHALLENGER", resolve_names=False)
    assert route.call_count == 1, "three views of an empty ladder, one Riot call"
    assert page.total_stored == 0


# --------------------------------------------------------------------- page


@respx.mock
async def test_a_page_is_served_from_the_snapshot_without_touching_riot():
    route = mock_apex(
        [apex_entry(f"LAD-p{i}".ljust(78, "z"), 900 - i) for i in range(5)]
    )
    async with SessionLocal() as session:
        await service(session).refresh(PLATFORM, tier="CHALLENGER")
    calls_after_refresh = route.call_count

    async with SessionLocal() as session:
        page = await service(session).page(
            PLATFORM, tier="CHALLENGER", per_page=3, resolve_names=False
        )
    assert route.call_count == calls_after_refresh, "a fresh snapshot costs nothing"
    assert [r.position for r in page.rows] == [1, 2, 3]
    assert page.total_stored == 5


@respx.mock
async def test_paging_is_stable_and_does_not_repeat_rows():
    mock_apex([apex_entry(f"LAD-pg{i}".ljust(78, "z"), 900 - i) for i in range(5)])
    async with SessionLocal() as session:
        await service(session).refresh(PLATFORM, tier="CHALLENGER")
        svc = service(session)
        first = await svc.page(
            PLATFORM, tier="CHALLENGER", page=1, per_page=2, resolve_names=False
        )
        second = await svc.page(
            PLATFORM, tier="CHALLENGER", page=2, per_page=2, resolve_names=False
        )
    assert [r.position for r in first.rows] == [1, 2]
    assert [r.position for r in second.rows] == [3, 4]
    assert not ({r.puuid for r in first.rows} & {r.puuid for r in second.rows})


# -------------------------------------------------------------------- names


@respx.mock
async def test_a_name_we_already_hold_costs_nothing():
    """The measured case: 298 of EUW's 300 Challengers were already named from
    match data we had stored."""
    puuid = "LAD-known".ljust(78, "z")
    async with SessionLocal() as session:
        session.add(Match(
            match_id="LAD_M1", platform_id="EUW1", queue_id=420, patch="X1.00",
            game_creation=1_000, game_duration=1800, is_remake=False, teams=[],
        ))
        session.add(MatchParticipant(
            match_id="LAD_M1", participant_index=1, puuid=puuid,
            riot_id_game_name="Known", riot_id_tagline="EUW",
            champion_id=1, champion_name="Annie", team_id=100,
            team_position="MIDDLE", win=True,
        ))
        await session.commit()

    mock_apex([apex_entry(puuid, 900)])
    account = respx.get(url__regex=r".*/riot/account/v1/accounts/by-puuid/.*").mock(
        return_value=httpx.Response(200, json={"gameName": "X", "tagLine": "Y"})
    )
    async with SessionLocal() as session:
        await service(session).refresh(PLATFORM, tier="CHALLENGER")
        page = await service(session).page(PLATFORM, tier="CHALLENGER")

    assert page.rows[0].game_name == "Known"
    assert account.call_count == 0, "we already knew this player"
    assert page.named_on_page == 1


@respx.mock
async def test_an_unknown_player_is_resolved_once_and_the_name_is_kept():
    """NA Challenger is 0% named locally, so the first view has to pay for it.
    The second must not."""
    puuid = "LAD-stranger".ljust(78, "z")
    mock_apex([apex_entry(puuid, 900)])
    account = respx.get(url__regex=r".*/riot/account/v1/accounts/by-puuid/.*").mock(
        return_value=httpx.Response(
            200, json={"gameName": "Stranger", "tagLine": "NA1"}
        )
    )
    async with SessionLocal() as session:
        await service(session).refresh(PLATFORM, tier="CHALLENGER")
        first = await service(session).page(PLATFORM, tier="CHALLENGER")
    assert first.rows[0].game_name == "Stranger"
    after_first = account.call_count
    assert after_first == 1

    async with SessionLocal() as session:
        second = await service(session).page(PLATFORM, tier="CHALLENGER")
    assert second.rows[0].game_name == "Stranger"
    assert account.call_count == after_first, "a resolved name is permanent"

    async with SessionLocal() as session:
        stored = await session.get(Player, puuid)
    assert stored.game_name == "Stranger"
    # Confirmed as a search would confirm it, so the nightly names stage,
    # which asks about unconfirmed players, has nothing to ask.
    assert stored.search_name == "stranger" and stored.account_fetched_at is not None


@respx.mock
async def test_name_resolution_is_bounded_so_a_page_never_blocks_for_minutes():
    """account-v1 is one call per player. A 205-row page resolved eagerly would
    take four minutes on a development key."""
    from app.services.ladders import NAME_BUDGET_PER_REQUEST

    entries = [apex_entry(f"LAD-crowd{i}".ljust(78, "z"), 900 - i) for i in range(80)]
    mock_apex(entries)
    account = respx.get(url__regex=r".*/riot/account/v1/accounts/by-puuid/.*").mock(
        return_value=httpx.Response(200, json={"gameName": "N", "tagLine": "T"})
    )
    async with SessionLocal() as session:
        await service(session).refresh(PLATFORM, tier="CHALLENGER")
        page = await service(session).page(PLATFORM, tier="CHALLENGER", per_page=80)

    assert account.call_count == NAME_BUDGET_PER_REQUEST
    assert page.named_on_page == NAME_BUDGET_PER_REQUEST
    assert len(page.rows) == 80, "unnamed rows are still served, just unnamed"


@respx.mock
async def test_an_unresolvable_player_stays_unnamed():
    """No invented names, and no dropped rows either."""
    puuid = "LAD-ghost".ljust(78, "z")
    mock_apex([apex_entry(puuid, 900)])
    respx.get(url__regex=r".*/riot/account/v1/accounts/by-puuid/.*").mock(
        return_value=httpx.Response(404, json={})
    )
    async with SessionLocal() as session:
        await service(session).refresh(PLATFORM, tier="CHALLENGER")
        page = await service(session).page(PLATFORM, tier="CHALLENGER")
    assert page.rows[0].game_name is None
    assert page.named_on_page == 0


@respx.mock
async def test_an_entry_riot_has_no_account_for_is_not_asked_about_again():
    """Measured on EUW Bronze IV: two of the first 200 rows answer 404 to every
    lookup, and each view of their page paid for both again while the page
    kept waiting for names that were never coming."""
    from datetime import timedelta

    from app.db.models import utcnow
    from app.services.ladders import NO_ACCOUNT_RECHECK_SECONDS

    puuid = "LAD-no-account".ljust(78, "z")
    mock_apex([apex_entry(puuid, 900)])
    account = respx.get(url__regex=r".*/riot/account/v1/accounts/by-puuid/.*").mock(
        return_value=httpx.Response(404, json={})
    )
    async with SessionLocal() as session:
        await service(session).refresh(PLATFORM, tier="CHALLENGER")
        first = await service(session).page(PLATFORM, tier="CHALLENGER")
    async with SessionLocal() as session:
        second = await service(session).page(PLATFORM, tier="CHALLENGER")

    assert account.call_count == 1, "a 404 is remembered"
    assert first.rows[0].no_riot_id and second.rows[0].no_riot_id
    assert second.rows[0].game_name is None
    assert not second.names_held_back

    # Believed for a while, not for good.
    async with SessionLocal() as session:
        stored = await session.get(Player, puuid)
        stored.account_fetched_at = utcnow() - timedelta(
            seconds=NO_ACCOUNT_RECHECK_SECONDS + 60
        )
        await session.commit()
        await service(session).page(PLATFORM, tier="CHALLENGER")
    assert account.call_count == 2


@respx.mock
async def test_a_failed_lookup_that_is_not_a_404_is_tried_again():
    """Only "no such account" is remembered. Anything else says nothing about
    the player, so the next view asks again."""
    puuid = "LAD-forbidden".ljust(78, "z")
    mock_apex([apex_entry(puuid, 900)])
    account = respx.get(url__regex=r".*/riot/account/v1/accounts/by-puuid/.*").mock(
        return_value=httpx.Response(403, json={})
    )
    async with SessionLocal() as session:
        await service(session).refresh(PLATFORM, tier="CHALLENGER")
        first = await service(session).page(PLATFORM, tier="CHALLENGER")
    async with SessionLocal() as session:
        await service(session).page(PLATFORM, tier="CHALLENGER")

    assert account.call_count == 2
    assert not first.rows[0].no_riot_id


@respx.mock
async def test_a_player_returned_on_two_pages_is_stored_once():
    """The paged endpoint reads a ladder that is moving: a player on page 1 when
    it is fetched can be on page 2 a second later. Seen live on EUW Diamond I,
    where it broke the insert outright."""
    duplicate = "LAD-dup".ljust(78, "z")
    pages = iter([
        [dict(apex_entry(duplicate, 95), tier="DIAMOND"),
         dict(apex_entry("LAD-other".ljust(78, "z"), 90), tier="DIAMOND")],
        [dict(apex_entry(duplicate, 95), tier="DIAMOND")],
        [],
    ])
    respx.get(url__regex=r".*/lol/league/v4/entries/RANKED_SOLO_5x5/.*").mock(
        side_effect=lambda request: httpx.Response(200, json=next(pages, []))
    )
    async with SessionLocal() as session:
        stored = await service(session).refresh(
            PLATFORM, tier="DIAMOND", division="I", pages=3
        )
    assert stored == 2, "three rows came back, two distinct players"

    async with SessionLocal() as session:
        rows = list((await session.execute(
            select(LadderEntry).where(
                LadderEntry.platform == PLATFORM, LadderEntry.tier == "DIAMOND"
            )
        )).scalars())
    assert len({r.puuid for r in rows}) == len(rows) == 2


# ------------------------------------------------------------ time budgets


@respx.mock
async def test_naming_stops_at_its_time_budget_and_keeps_what_landed(monkeypatch):
    """The count bound alone did not bound time: with the key's budget spent,
    25 names waited on the limiter for over 100 seconds (2026-09-22)."""
    import asyncio
    import time

    monkeypatch.setattr("app.services.ladders.NAME_BUDGET_SECONDS", 0.5)
    fast = [f"LAD-fast{i}".ljust(78, "q") for i in range(3)]
    slow = [f"LAD-slow{i}".ljust(78, "q") for i in range(5)]
    mock_apex([apex_entry(p, 900 - i) for i, p in enumerate(fast + slow)])

    async def account(request):
        if "LAD-slow" in str(request.url):
            await asyncio.sleep(10)
        return httpx.Response(200, json={"gameName": "Quick", "tagLine": "Q1"})

    respx.get(url__regex=r".*/riot/account/v1/accounts/by-puuid/.*").mock(side_effect=account)
    async with SessionLocal() as session:
        await service(session).refresh(PLATFORM, tier="CHALLENGER")
        start = time.monotonic()
        page = await service(session).page(PLATFORM, tier="CHALLENGER")
        elapsed = time.monotonic() - start

    assert elapsed < 2.0, f"a ladder page waited {elapsed:.1f}s for names"
    assert page.named_on_page == len(fast)
    assert len(page.rows) == len(fast) + len(slow)


@respx.mock
async def test_a_busy_key_serves_the_ladder_we_hold_instead_of_waiting():
    import time

    puuid = "LAD-held".ljust(78, "q")
    mock_apex([apex_entry(puuid, 950)])
    async with SessionLocal() as session:
        await service(session).refresh(PLATFORM, tier="CHALLENGER")

        busy = service(session)
        # A minute until the next slot: the refresh this stale slice wants
        # would otherwise sit out the whole of it.
        await busy.client.limiter.penalize("application", 60.0)
        start = time.monotonic()
        page = await busy.page(PLATFORM, tier="CHALLENGER", resolve_names=False)
        elapsed = time.monotonic() - start

    assert elapsed < 2.0, f"waited {elapsed:.1f}s for a refresh it could skip"
    assert [r.puuid for r in page.rows][:1] == [puuid]


@respx.mock
async def test_naming_leaves_the_keys_last_calls_for_player_searches():
    """A Bronze page names nobody from stored games, so it can spend 25 calls a
    view, and the page now asks again while rows are unnamed. Past the reserve
    it stops and says so, rather than answering the next search with a limit."""
    from app.services.ladders import NAME_RESERVE

    puuids = [f"LAD-reserve{i}".ljust(78, "r") for i in range(5)]
    mock_apex([apex_entry(p, 900 - i) for i, p in enumerate(puuids)])
    account = respx.get(url__regex=r".*/riot/account/v1/accounts/by-puuid/.*").mock(
        return_value=httpx.Response(200, json={"gameName": "N", "tagLine": "T"})
    )
    async with SessionLocal() as session:
        await service(session).refresh(PLATFORM, tier="CHALLENGER")

        busy = service(session)
        # Riot reports the two-minute window as all but the reserve spent.
        await busy.client.limiter.observe(
            "x", {"X-App-Rate-Limit-Count": f"{100 - NAME_RESERVE}:120"}
        )
        held = await busy.page(PLATFORM, tier="CHALLENGER")

        free = service(session)
        named = await free.page(PLATFORM, tier="CHALLENGER")

    assert account.call_count == len(puuids), "only the page with headroom spent calls"
    assert (held.named_on_page, held.names_held_back) == (0, True)
    assert (named.named_on_page, named.names_held_back) == (len(puuids), False)
    assert named.names_retry_after is None


@respx.mock
async def test_a_held_back_page_says_when_to_ask_again():
    """A call frees two minutes after it was made, longer than any fixed
    retry that still feels live, so the page is told when the key will have
    room for the names it still wants instead of guessing."""
    from app.services.ladders import NAME_RESERVE

    puuids = [f"LAD-retry{i}".ljust(78, "r") for i in range(5)]
    mock_apex([apex_entry(p, 900 - i) for i, p in enumerate(puuids)])
    account = respx.get(url__regex=r".*/riot/account/v1/accounts/by-puuid/.*").mock(
        return_value=httpx.Response(200, json={"gameName": "N", "tagLine": "T"})
    )
    async with SessionLocal() as session:
        await service(session).refresh(PLATFORM, tier="CHALLENGER")
        busy = service(session)
        await busy.client.limiter.observe(
            "x", {"X-App-Rate-Limit-Count": f"{100 - NAME_RESERVE}:120"}
        )
        held = await busy.page(PLATFORM, tier="CHALLENGER")

    assert account.call_count == 0
    assert held.names_held_back
    # The key needs NAME_RESERVE + 5 free: 5 of the 80 spread hits aging out,
    # the fifth at 5 * 120 / 80 = 7.5 s from now.
    assert held.names_retry_after is not None
    assert 6.0 <= held.names_retry_after <= 7.5
