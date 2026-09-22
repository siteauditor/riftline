"""The profile from storage alone, and the players the sitemap lists.

`?source=stored` is what the prerenderer asks for: a page for every player
with enough scored games, none of them costing a Riot call. Riot is mocked
with no routes at all here, so any call would fail the request outright.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import UTC, datetime

import pytest
import respx

from app.db.base import SessionLocal
from app.db.models import Player, RankedEntry
from app.services.players import normalize_riot_name
from app.services.profile_stats import MIN_SCORED_FOR_PROFILE
from tests.test_aggregate import participant, seed

DEEP = "stored-seo".ljust(78, "0")
THIN = "thin-seo".ljust(78, "0")
AHRI = 103
OLDER_MS = 1_700_000_000_000
NEWEST_MS = 1_700_000_100_000


async def _seed_player(puuid: str, game_name: str) -> None:
    async with SessionLocal() as session:
        if await session.get(Player, puuid):
            return
        session.add(
            Player(
                puuid=puuid,
                game_name=game_name,
                tag_line="SEO",
                search_name=normalize_riot_name(game_name),
                platform="euw1",
                profile_icon_id=1,
                summoner_level=120,
                summoner_platform="euw1",
                summoner_fetched_at=datetime(2026, 9, 20, tzinfo=UTC),
                league_platform="euw1",
                league_fetched_at=datetime(2026, 9, 20, tzinfo=UTC),
            )
        )
        session.add(
            RankedEntry(
                puuid=puuid, queue_type="RANKED_SOLO_5x5", tier="GOLD", division="II",
                league_points=40, wins=30, losses=20,
            )
        )
        await session.commit()


def _scored_game(puuid: str) -> list[dict]:
    me = participant(AHRI, "MIDDLE", 100, True, performance_score=61.0)
    me["puuid"] = puuid
    return [me]


@pytest.fixture
async def players():
    """One player at the floor, one below it. The deep player's newest game
    is on its own patch so the two seed calls can give it a later time."""
    await _seed_player(DEEP, "Stored Player")
    await _seed_player(THIN, "Thin Player")
    from sqlalchemy import func, select

    from app.db.models import Match

    async with SessionLocal() as session:
        seeded = (await session.execute(
            select(func.count(Match.match_id)).where(Match.patch == "SP1.00")
        )).scalar()
    if not seeded:
        await seed(
            "SP1.00",
            [_scored_game(DEEP) for _ in range(MIN_SCORED_FOR_PROFILE - 1)]
            + [_scored_game(THIN) for _ in range(3)],
            game_creation=OLDER_MS,
        )
        await seed("SP1.01", [_scored_game(DEEP)], game_creation=NEWEST_MS)


@respx.mock
async def test_a_stored_profile_costs_no_riot_call(client, players):
    profile = await client.get("/api/summoner/euw1/Stored Player/SEO?source=stored")
    assert profile.status_code == 200, profile.text[:300]
    body = profile.json()
    assert body["riot_id"] == "Stored Player#SEO"
    assert body["summoner_level"] == 120
    assert [(r["tier"], r["division"]) for r in body["ranks"]] == [("GOLD", "II")]
    assert body["plays_on"] is None

    matches = await client.get("/api/summoner/euw1/Stored Player/SEO/matches?source=stored")
    assert matches.status_code == 200, matches.text[:300]
    page = matches.json()
    assert page["source"] == "stored"
    assert page["stored_total"] == MIN_SCORED_FOR_PROFILE
    assert len(page["matches"]) == MIN_SCORED_FOR_PROFILE
    assert page["matches"][0]["match_id"] == "TSP1.01_0", "newest first"
    assert page["has_more"] is False

    analytics = await client.get("/api/summoner/euw1/Stored Player/SEO/analytics?source=stored")
    assert analytics.status_code == 200, analytics.text[:300]
    assert analytics.json()["games_analysed"] == MIN_SCORED_FOR_PROFILE

    assert len(respx.calls) == 0, "stored means stored: not one Riot call"


@respx.mock
async def test_a_stored_lookup_of_an_unknown_riot_id_is_a_404_without_riot(client):
    response = await client.get("/api/summoner/euw1/Nobody Stored/SEO?source=stored")
    assert response.status_code == 404
    assert len(respx.calls) == 0


async def test_the_source_switch_takes_two_values_only(client):
    response = await client.get("/api/summoner/euw1/Stored Player/SEO?source=riot")
    assert response.status_code == 422


async def test_the_manifest_lists_players_with_enough_scored_games(client, players):
    body = (await client.get("/api/meta/pages")).json()
    by_path = {p["path"]: p for p in body["pages"]}

    deep = by_path["/summoner/euw1/Stored Player/SEO"]
    assert deep["kind"] == "profile"
    assert deep["indexable"] is True
    assert deep["required"] is False
    assert deep["lastmod"] == NEWEST_MS, "the newest stored game"
    assert "/summoner/euw1/Thin Player/SEO" not in by_path

    # The manifest path is the decoded one, which is what nginx matches a
    # file against; the sitemap carries the URL, encoded as the page's own
    # canonical link encodes it.
    sitemap = ET.fromstring((await client.get("/api/meta/sitemap.xml")).text)
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    locs = {u.find("s:loc", ns).text for u in sitemap.findall("s:url", ns)}
    assert f"{body['origin']}/summoner/euw1/Stored%20Player/SEO" in locs
    assert not any("Thin" in loc for loc in locs)
