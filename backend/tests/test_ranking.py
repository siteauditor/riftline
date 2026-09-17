"""Rank arithmetic and the endpoint-vs-key distinction on a 403.

Both of these are prerequisites for Group C rather than cleanup: a leaderboard
sorts on `numeric_rank`, and a live-game feature built on a deprecated endpoint
has to be able to say "Riot withdrew this" instead of "your key expired".
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.api.schemas import (
    APEX_BASE,
    APEX_STRIDE,
    APEX_TIERS,
    DIVISION_ORDER,
    TIER_ORDER,
    numeric_rank,
)
from app.riot.client import RiotClient
from app.riot.errors import RiotForbidden, RiotUnauthorized

SUB_APEX = [t for t in TIER_ORDER if t not in APEX_TIERS]

# What the function returned before apex got its own scale. Sub-apex values are
# load-bearing (bracket filters, profile queue ordering) and must not move.
def legacy(tier: str, division: str, lp: int) -> int:
    return (
        TIER_ORDER.index(tier) * 400
        + DIVISION_ORDER.index(division) * 100
        + min(lp, 99)
    )


# ------------------------------------------------------------------ numeric_rank


@pytest.mark.parametrize("tier", SUB_APEX)
@pytest.mark.parametrize("division", DIVISION_ORDER)
@pytest.mark.parametrize("lp", [0, 1, 50, 99, 100])
def test_sub_apex_values_are_unchanged(tier, division, lp):
    """The apex fix must not move a single sub-apex value."""
    assert numeric_rank(tier, division, lp) == legacy(tier, division, lp)


def test_the_apex_scale_starts_just_above_the_sub_apex_ceiling():
    ceiling = max(
        numeric_rank(t, d, 100) for t in SUB_APEX for d in DIVISION_ORDER
    )
    assert ceiling == 2799, "Diamond I at 100 LP is the highest sub-apex value"
    assert numeric_rank("MASTER", None, 0) == APEX_BASE == ceiling + 1


def test_an_apex_ladder_can_actually_be_ordered():
    """The bug this replaced: every Challenger scored 3999, so a ladder sorted
    by this value came back in arbitrary order."""
    lps = [0, 99, 500, 1412, 4724]
    scores = [numeric_rank("CHALLENGER", None, lp) for lp in lps]
    assert len(set(scores)) == len(lps), "LP must separate players within a tier"
    assert scores == sorted(scores)


def test_tier_still_outranks_lp_across_tiers():
    """A Challenger scraping the cutoff is above a Master on a heap of LP. The
    stride exists to guarantee this, so it is worth asserting rather than
    trusting the arithmetic."""
    assert numeric_rank("CHALLENGER", None, 0) > numeric_rank("MASTER", None, 5_000)
    assert numeric_rank("GRANDMASTER", None, 0) > numeric_rank("MASTER", None, 5_000)
    assert APEX_STRIDE > 5_000, "the stride has to exceed any attainable LP total"


def test_the_whole_ladder_is_monotonic():
    ordered = [
        numeric_rank(t, d, lp)
        for t in SUB_APEX
        for d in DIVISION_ORDER
        for lp in (0, 50, 99)
    ] + [numeric_rank(t, None, lp) for t in APEX_TIERS for lp in (0, 500, 2_000)]
    assert ordered == sorted(ordered)


@pytest.mark.parametrize(
    ("tier", "division", "lp"),
    [(None, None, 0), ("", "I", 50), ("WOOD", "I", 50), ("CHALLENGER", None, -5)],
)
def test_nonsense_input_never_produces_a_negative_or_a_crash(tier, division, lp):
    assert numeric_rank(tier, division, lp) >= 0


# --------------------------------------------------------------- 403 handling

RATE_LIMIT_HEADERS = {
    "X-App-Rate-Limit": "20:1,100:120",
    "X-App-Rate-Limit-Count": "1:1,1:120",
}


@respx.mock
async def test_a_403_without_rate_limit_headers_is_the_endpoint_not_the_key():
    """Riot refuses an endpoint the key may not call at its edge, before the key
    is evaluated, so no rate-limit headers come back. Measured against the live
    spectator featured-games endpoint with a valid key."""
    respx.get(url__regex=r".*/lol/spectator/v5/featured-games").mock(
        return_value=httpx.Response(403, json={"status": {"message": "Forbidden"}})
    )
    client = RiotClient("RGAPI-test-key")
    with pytest.raises(RiotForbidden) as caught:
        await client.get("https://euw1.api.riotgames.com", "/lol/spectator/v5/featured-games")
    await client.aclose()

    assert "featured-games" in caught.value.message
    assert "key is fine" in caught.value.message
    assert "expire" not in caught.value.message.lower()


@respx.mock
async def test_a_403_with_rate_limit_headers_still_reads_as_an_expired_key():
    """The API itself answered, so the key really is the problem."""
    respx.get(url__regex=r".*").mock(
        return_value=httpx.Response(403, headers=RATE_LIMIT_HEADERS, json={})
    )
    client = RiotClient("RGAPI-test-key")
    with pytest.raises(RiotUnauthorized) as caught:
        await client.summoner_by_puuid("p" * 78, "euw1")
    await client.aclose()
    assert "expire" in caught.value.message.lower()


@respx.mock
async def test_a_401_is_always_a_key_problem():
    respx.get(url__regex=r".*").mock(return_value=httpx.Response(401, json={}))
    client = RiotClient("RGAPI-test-key")
    with pytest.raises(RiotUnauthorized):
        await client.summoner_by_puuid("p" * 78, "euw1")
    await client.aclose()


@respx.mock
async def test_the_forbidden_endpoint_is_not_retried():
    """A refusal is settled. Retrying it burns the rate limit for nothing."""
    route = respx.get(url__regex=r".*").mock(return_value=httpx.Response(403, json={}))
    client = RiotClient("RGAPI-test-key", max_retries=3)
    with pytest.raises(RiotForbidden):
        await client.champion_rotations("euw1")
    await client.aclose()
    assert route.call_count == 1


# ------------------------------------------------------------------ epoch_ms


def test_a_naive_stamp_is_read_as_utc_not_local_time():
    """SQLite returns naive datetimes and `datetime.timestamp()` reads those as
    local time. On a machine seven hours off UTC that reported a snapshot taken
    moments ago as "7h ago", which is what this guards."""
    import time
    from datetime import UTC, datetime

    from app.api.schemas import epoch_ms

    naive_utc = datetime.now(UTC).replace(tzinfo=None)
    drift = abs(epoch_ms(naive_utc) - time.time() * 1000)
    assert drift < 2_000, "a naive stamp must be treated as UTC, not local"


def test_an_aware_stamp_is_unchanged_and_none_passes_through():
    from datetime import UTC, datetime

    from app.api.schemas import epoch_ms

    aware = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)
    assert epoch_ms(aware) == int(aware.timestamp() * 1000)
    assert epoch_ms(None) is None
