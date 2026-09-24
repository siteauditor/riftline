"""Tests for the Riot transport layer: routing, rate limiting, error translation."""

from __future__ import annotations

import asyncio
import time

import httpx
import pytest
import respx

from app.riot.client import RiotClient
from app.riot.errors import RiotNotFound, RiotRateLimited, RiotUnauthorized, RiotUnavailable
from app.riot.limiter import RateLimiter, SlidingWindow, parse_limit_header
from app.riot.routing import Regional, UnknownPlatform, resolve_platform

# --------------------------------------------------------------------- routing


def test_resolve_platform_accepts_what_players_actually_type():
    assert resolve_platform("NA").id == "na1"
    assert resolve_platform("na1").id == "na1"
    assert resolve_platform(" EUW ").id == "euw1"
    assert resolve_platform("kr").id == "kr"


def test_platform_maps_to_correct_regional_route():
    # match-v5 and account-v1 are regional; getting this wrong is a silent 404.
    assert resolve_platform("na1").regional is Regional.AMERICAS
    assert resolve_platform("euw1").regional is Regional.EUROPE
    assert resolve_platform("kr").regional is Regional.ASIA
    assert resolve_platform("oc1").regional is Regional.SEA


def test_sea_collapses_to_asia_for_account_v1():
    # account-v1 does not serve a `sea` host, so SEA shards must route to asia.
    oce = resolve_platform("oc1")
    assert oce.regional is Regional.SEA
    assert oce.account_region is Regional.ASIA


def test_a_shards_games_include_the_shards_folded_into_it():
    from app.riot.routing import platform_ids_for

    assert platform_ids_for("sg2") == frozenset({"SG2", "PH2", "TH2"})
    assert platform_ids_for("th2") == frozenset({"SG2", "PH2", "TH2"})
    assert platform_ids_for("euw") == frozenset({"EUW1"})
    assert platform_ids_for("kr") == frozenset({"KR"})


def test_unknown_platform_is_rejected_with_a_useful_message():
    with pytest.raises(UnknownPlatform) as exc:
        resolve_platform("narnia")
    assert "na1" in str(exc.value)


# --------------------------------------------------------------------- limiter


def test_parse_limit_header():
    assert parse_limit_header("20:1,100:120") == [(20, 1.0), (100, 120.0)]
    assert parse_limit_header("") == []
    assert parse_limit_header(None) == []
    # Garbage degrades to "no limit learned" rather than exploding.
    assert parse_limit_header("nonsense") == []
    assert parse_limit_header("20:1,broken") == [(20, 1.0)]


def test_sliding_window_reports_when_a_slot_frees():
    w = SlidingWindow(limit=2, period=10.0)
    now = 1000.0
    assert w.retry_after(now) == 0.0
    w.record(now)
    w.record(now + 1)
    # Full: must wait until the oldest hit ages out.
    assert w.retry_after(now + 2) == pytest.approx(8.0)
    assert w.retry_after(now + 11) == 0.0


def test_sliding_window_says_when_several_slots_will_be_free():
    w = SlidingWindow(limit=4, period=10.0)
    for t in (1000.0, 1001.0, 1002.0, 1003.0):
        w.record(t)
    now = 1004.0
    assert w.seconds_until_free(0, now) == 0.0
    # Two free once the two oldest age out, the second at 1011.
    assert w.seconds_until_free(2, now) == pytest.approx(7.0)
    # More than the window holds means the whole window.
    assert w.seconds_until_free(9, now) == pytest.approx(9.0)
    assert w.seconds_until_free(2, 1011.0) == 0.0


def test_sliding_window_sync_only_tops_up():
    w = SlidingWindow(limit=10, period=60.0)
    w.record(1000.0)
    w.sync(observed=5, now=1000.0)
    assert len(w.hits) == 5
    # A lower observation must not hand back budget we already spent.
    w.sync(observed=2, now=1000.0)
    assert len(w.hits) == 5


def test_sync_to_a_full_window_does_not_stall_for_the_whole_period():
    """Regression: Riot reports a full window alongside a 200 response.

    Live behaviour on a development key: ``x-app-rate-limit-count: 100:120``
    arrived with an HTTP 200 on the very first call. Placing those unseen hits
    at ``now`` asserted the window could not free for a further 120 seconds,
    which stalled the next request for two full minutes.

    Spread across the window instead, the wait collapses to the rate the window
    actually sustains.
    """
    w = SlidingWindow(limit=100, period=120.0)
    now = 1000.0
    w.record(now)
    w.sync(observed=100, now=now)

    assert len(w.hits) == 100
    wait = w.retry_after(now)
    # 120s / 100 requests = 1.2s of drip, not a 120s cliff.
    assert 0.0 < wait <= 2.0, f"expected a short drip, waited {wait}s"


def test_sync_keeps_hits_ordered_so_pruning_stays_correct():
    w = SlidingWindow(limit=50, period=60.0)
    w.record(1000.0)
    w.sync(observed=20, now=1000.0)
    hits = list(w.hits)
    assert hits == sorted(hits)
    # Everything ages out once a full period has passed.
    assert w.retry_after(1000.0 + 61) == 0.0
    assert len(w.hits) == 0


async def test_limiter_recovers_quickly_when_riot_reports_a_busy_key():
    """End-to-end version of the same bug, through the limiter."""
    limiter = RateLimiter(app_limits=[(100, 2.0)])
    await limiter.acquire("m")
    await limiter.observe("m", {"X-App-Rate-Limit-Count": "100:2"})

    start = time.monotonic()
    await limiter.acquire("m")
    elapsed = time.monotonic() - start
    # Sustainable pace is 2s/100 = 20ms; the bug made this wait the full 2s.
    assert elapsed < 0.5, f"limiter stalled {elapsed:.2f}s on a busy key"


async def test_limiter_blocks_once_the_window_is_full():
    limiter = RateLimiter(app_limits=[(2, 0.4)])
    start = time.monotonic()
    for _ in range(3):
        await limiter.acquire("m")
    # The third acquire cannot land until the first pair ages out.
    assert time.monotonic() - start >= 0.35


async def test_limiter_learns_method_limits_from_headers():
    limiter = RateLimiter(app_limits=[(1000, 60.0)])
    await limiter.observe("na1:/x", {"X-Method-Rate-Limit": "1:1"})
    start = time.monotonic()
    await limiter.acquire("na1:/x")
    await limiter.acquire("na1:/x")
    assert time.monotonic() - start >= 0.9
    # A different method keeps its own budget and is unaffected.
    other = time.monotonic()
    await limiter.acquire("na1:/y")
    assert time.monotonic() - other < 0.5


async def test_penalty_applies_only_to_its_scope():
    limiter = RateLimiter(app_limits=[(1000, 60.0)])
    await limiter.penalize("na1:/slow", 0.5)
    start = time.monotonic()
    await limiter.acquire("na1:/fast")
    assert time.monotonic() - start < 0.3


# ---------------------------------------------------------------------- client


def _client(**kw) -> RiotClient:
    limiter = RateLimiter(app_limits=[(1000, 60.0)])
    return RiotClient("fake-key", limiter=limiter, max_retries=kw.pop("max_retries", 2), **kw)


@respx.mock
async def test_account_by_riot_id_hits_the_regional_host():
    route = respx.get(
        "https://europe.api.riotgames.com/riot/account/v1/accounts/by-riot-id/Caps/EUW"
    ).mock(return_value=httpx.Response(200, json={"puuid": "P1", "gameName": "Caps", "tagLine": "EUW"}))
    async with _client() as c:
        data = await c.account_by_riot_id("Caps", "EUW", Regional.EUROPE)
    assert route.called
    assert data["puuid"] == "P1"
    assert route.calls[0].request.headers["X-Riot-Token"] == "fake-key"


@pytest.mark.riot_region
@respx.mock
async def test_active_region_names_the_home_shard():
    """The home an account plays on, from any account region: measured on
    2026-09-24, europe and americas both named euw1 for a EUW account."""
    route = respx.get(
        "https://americas.api.riotgames.com/riot/account/v1/region/by-game/lol/by-puuid/P1"
    ).mock(return_value=httpx.Response(200, json={"puuid": "P1", "game": "lol", "region": "EUW1"}))
    async with _client() as c:
        assert await c.active_region("P1", Regional.AMERICAS) == "euw1"
    assert route.called


@pytest.mark.riot_region
@respx.mock
async def test_active_region_without_an_answer_is_none():
    respx.get(url__regex=r".*/region/by-game/lol/by-puuid/P1$").mock(
        side_effect=[
            httpx.Response(404),
            httpx.Response(200, json={"puuid": "P1", "game": "lol"}),
            httpx.Response(200, json={"puuid": "P1", "game": "lol", "region": "  "}),
        ]
    )
    async with _client() as c:
        for _ in range(3):
            assert await c.active_region("P1", Regional.EUROPE) is None


@respx.mock
async def test_404_raises_not_found():
    respx.get(url__regex=r".*by-riot-id.*").mock(return_value=httpx.Response(404))
    async with _client() as c:
        with pytest.raises(RiotNotFound):
            await c.account_by_riot_id("Nope", "0000", Regional.EUROPE)


@respx.mock
async def test_allow_404_returns_none_for_no_live_game():
    respx.get(url__regex=r".*spectator.*").mock(return_value=httpx.Response(404))
    async with _client() as c:
        assert await c.active_game("P1", "euw1") is None


@respx.mock
async def test_401_explains_the_expired_dev_key():
    """Measured against the live API: a dead or absent key gets 401, not 403.

    This test used to assert 403, which was wrong. Probing euw1 on 2026-09-17
    with a well-formed but dead key returned 401 on a working endpoint, and so
    did sending no key at all. 403 is what a *valid* key gets from an endpoint
    it may not call, which is a different problem with a different fix.
    """
    respx.get(url__regex=r".*").mock(return_value=httpx.Response(401))
    async with _client() as c:
        with pytest.raises(RiotUnauthorized) as exc:
            await c.summoner_by_puuid("P1", "euw1")
    assert "24 hours" in str(exc.value)


@respx.mock
async def test_429_is_retried_after_the_server_supplied_delay():
    calls = {"n": 0}

    def responder(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(
                429, headers={"Retry-After": "0.2", "X-Rate-Limit-Type": "method"}
            )
        return httpx.Response(200, json={"puuid": "P1"})

    respx.get(url__regex=r".*summoners.*").mock(side_effect=responder)
    async with _client() as c:
        start = time.monotonic()
        data = await c.summoner_by_puuid("P1", "euw1")
    assert data == {"puuid": "P1"}
    assert calls["n"] == 2
    # The retry waited out the penalty rather than hammering.
    assert time.monotonic() - start >= 0.15


@respx.mock
async def test_429_gives_up_and_surfaces_retry_after():
    respx.get(url__regex=r".*").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "0.05"})
    )
    async with _client(max_retries=1) as c:
        with pytest.raises(RiotRateLimited) as exc:
            await c.summoner_by_puuid("P1", "euw1")
    assert exc.value.retry_after == pytest.approx(0.05)


@respx.mock
async def test_5xx_is_retried_then_reported_as_unavailable():
    route = respx.get(url__regex=r".*").mock(return_value=httpx.Response(503))
    async with _client(max_retries=1) as c:
        with pytest.raises(RiotUnavailable):
            await c.match("EUW1_1", Regional.EUROPE)
    assert route.call_count == 2


@respx.mock
async def test_match_ids_passes_paging_and_queue_filters():
    route = respx.get(url__regex=r".*by-puuid/P1/ids.*").mock(
        return_value=httpx.Response(200, json=["EUW1_1", "EUW1_2"])
    )
    async with _client() as c:
        ids = await c.match_ids("P1", Regional.EUROPE, start=10, count=5, queue=420)
    assert ids == ["EUW1_1", "EUW1_2"]
    q = route.calls[0].request.url.params
    assert q["start"] == "10" and q["count"] == "5" and q["queue"] == "420"


@respx.mock
async def test_count_is_clamped_to_riots_maximum_of_100():
    route = respx.get(url__regex=r".*ids.*").mock(return_value=httpx.Response(200, json=[]))
    async with _client() as c:
        await c.match_ids("P1", Regional.EUROPE, count=500)
    assert route.calls[0].request.url.params["count"] == "100"


@respx.mock
async def test_method_key_is_shared_across_ids_but_split_across_regions():
    """The limiter must bucket by endpoint template, not concrete URL."""
    respx.get(url__regex=r".*matches/.*").mock(
        return_value=httpx.Response(200, json={}, headers={"X-Method-Rate-Limit": "50:10"})
    )
    async with _client() as c:
        await c.match("EUW1_1", Regional.EUROPE)
        await c.match("EUW1_2", Regional.EUROPE)
        await c.match("NA1_1", Regional.AMERICAS)
        keys = set(c.limiter._method)
    assert keys == {
        "europe:/lol/match/v5/matches/{matchId}",
        "americas:/lol/match/v5/matches/{matchId}",
    }


@respx.mock
async def test_concurrent_callers_share_one_budget():
    respx.get(url__regex=r".*").mock(return_value=httpx.Response(200, json={}))
    limiter = RateLimiter(app_limits=[(5, 0.5)])
    async with RiotClient("k", limiter=limiter) as c:
        start = time.monotonic()
        await asyncio.gather(*(c.summoner_by_puuid(f"P{i}", "euw1") for i in range(10)))
        elapsed = time.monotonic() - start
    # 10 requests through a 5-per-0.5s window needs at least one window rollover.
    assert elapsed >= 0.45


# ----------------------------------------------------------- waiting budget


async def test_a_caller_with_a_deadline_is_told_rather_than_kept_waiting():
    """Measured on 2026-09-22: with the key's budget spent, a leaderboard page
    waited 102 to 108 seconds on this limiter, and Cloudflare abandons an
    origin at 100. A web request now carries a deadline and gets an answer."""
    from app.riot.limiter import WaitTooLong, wait_deadline

    limiter = RateLimiter(app_limits=[(1000, 60.0)])
    await limiter.penalize("application", 30.0)
    token = wait_deadline.set(time.monotonic() + 1.0)
    try:
        start = time.monotonic()
        with pytest.raises(WaitTooLong) as exc:
            await limiter.acquire("m")
        assert time.monotonic() - start < 0.2, "it must not sleep first and fail later"
        assert exc.value.retry_after == pytest.approx(30.0, abs=0.5)
    finally:
        wait_deadline.reset(token)


async def test_a_wait_that_fits_the_deadline_still_waits():
    from app.riot.limiter import wait_deadline

    limiter = RateLimiter(app_limits=[(1000, 60.0)])
    await limiter.penalize("application", 0.2)
    token = wait_deadline.set(time.monotonic() + 5.0)
    try:
        start = time.monotonic()
        await limiter.acquire("m")
        assert time.monotonic() - start >= 0.15
    finally:
        wait_deadline.reset(token)


async def test_without_a_deadline_the_limiter_waits_for_the_key():
    """The ingest CLI sets no deadline, and must keep waiting as it always has."""
    limiter = RateLimiter(app_limits=[(1000, 60.0)])
    await limiter.penalize("application", 0.3)
    start = time.monotonic()
    await limiter.acquire("m")
    assert time.monotonic() - start >= 0.25


@respx.mock
async def test_a_missed_deadline_reaches_the_caller_as_a_rate_limit_and_sends_nothing():
    from app.riot.limiter import wait_deadline

    route = respx.get(url__regex=r".*").mock(return_value=httpx.Response(200, json={}))
    async with _client() as c:
        await c.limiter.penalize("application", 45.0)
        token = wait_deadline.set(time.monotonic() + 2.0)
        try:
            with pytest.raises(RiotRateLimited) as exc:
                await c.summoner_by_puuid("P1", "euw1")
        finally:
            wait_deadline.reset(token)
    assert exc.value.scope == "local"
    assert exc.value.retry_after == pytest.approx(45.0, abs=0.5)
    assert route.call_count == 0, "nothing is sent when the answer is 'not now'"


@respx.mock
async def test_a_riot_id_is_quoted_segment_by_segment():
    """A searched name is user input. Unquoted, "abc?x" became a query string
    and the lookup asked Riot for the account "abc"."""
    route = respx.get(url__regex=r".*by-riot-id/.*").mock(
        return_value=httpx.Response(200, json={"puuid": "P1"})
    )
    async with _client() as c:
        await c.account_by_riot_id("abc?x", "EUW", Regional.EUROPE)
        await c.account_by_riot_id("Some Name", "EUW", Regional.EUROPE)
        await c.account_by_riot_id("a/b", "EUW", Regional.EUROPE)
    paths = [call.request.url.raw_path.decode() for call in route.calls]
    assert paths[0].endswith("/by-riot-id/abc%3Fx/EUW")
    assert paths[1].endswith("/by-riot-id/Some%20Name/EUW")
    assert paths[2].endswith("/by-riot-id/a%2Fb/EUW")
