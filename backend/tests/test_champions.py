"""Champion detail endpoint.

Seeds a private patch, aggregates it, then reads the page back through HTTP.
No Riot calls are involved at any point: the whole feature is rollups.
"""

from __future__ import annotations

import pytest

from app.db.base import SessionLocal
from app.services.aggregate import (
    ALL_BRACKETS,
    rebuild_champion_stats,
    rebuild_facet_stats,
    rebuild_matchup_stats,
    rebuild_synergy_stats,
)
from tests.test_aggregate import BOOTS, LEGENDARY_A, LEGENDARY_B, participant, seed, taxonomy

PATCH = "C1.00"
# Ahri, so the response can be checked against real Data Dragon metadata.
SUBJECT = 103
BLUE = [SUBJECT, 64, 157, 22, 412]
RED = [238, 121, 245, 51, 555]


async def _build_corpus(matches: int = 12) -> None:
    """One repeated matchup, enough times to clear every min_games floor.

    Idempotent: the fixture runs per test but the rows are shared, so seeding
    twice would collide on the match primary key.
    """
    from sqlalchemy import func, select

    from app.db.models import Match

    async with SessionLocal() as session:
        already = (
            await session.execute(
                select(func.count(Match.match_id)).where(Match.patch == PATCH)
            )
        ).scalar()
    if already:
        return

    positions = ("MIDDLE", "JUNGLE", "TOP", "BOTTOM", "UTILITY")
    build = [LEGENDARY_A, LEGENDARY_B, BOOTS, 0, 0, 0, 3340]

    specs = []
    for index in range(matches):
        blue_wins = index % 2 == 0
        blue = [
            participant(c, p, 100, blue_wins, items=build)
            for c, p in zip(BLUE, positions, strict=True)
        ]
        red = [
            participant(c, p, 200, not blue_wins, items=build)
            for c, p in zip(RED, positions, strict=True)
        ]
        specs.append(blue + red)
    await seed(PATCH, specs)

    async with SessionLocal() as session:
        kwargs = {"patch": PATCH, "queue_id": 420, "rank_bracket": ALL_BRACKETS}
        await rebuild_champion_stats(session, **kwargs)
        await rebuild_matchup_stats(session, **kwargs, min_games=1)
        await rebuild_synergy_stats(session, **kwargs, min_games=1)
        await rebuild_facet_stats(session, **kwargs, min_games=1, taxonomy=taxonomy())


@pytest.fixture
async def corpus():
    await _build_corpus()


async def test_champion_detail_assembles_the_whole_page(client, corpus):
    response = await client.get(
        f"/api/champions/{SUBJECT}?patch={PATCH}&min_games=1"
    )
    assert response.status_code == 200, response.text[:300]
    body = response.json()

    # Identity comes from Data Dragon, not from the match rows.
    assert body["champion"]["name"] == "Ahri"
    assert body["champion"]["icon_url"].endswith("/Ahri.png")
    # Defaults to where the champion is actually played.
    assert body["position"] == "MIDDLE"
    assert body["positions"][0]["position"] == "MIDDLE"
    assert body["positions"][0]["share"] == pytest.approx(1.0)

    overview = body["overview"]
    assert overview["games"] == 12
    assert overview["win_rate"] == pytest.approx(0.5)
    # Wilson always sits at or below the raw rate.
    assert overview["confidence_win_rate"] <= overview["win_rate"]


async def test_builds_are_declared_as_final_inventories(client, corpus):
    """The UI must never imply a purchase order we did not measure."""
    body = (await client.get(f"/api/champions/{SUBJECT}?patch={PATCH}&min_games=1")).json()
    builds = body["builds"]

    assert builds["basis"] == "final_inventory"
    complete = builds["complete"][0]
    # Sorted ids, so the same two items in any slot order are one entry.
    assert complete["ids"] == sorted([LEGENDARY_A, LEGENDARY_B])
    assert complete["games"] == 12
    assert [i["name"] for i in complete["items"]] == ["Infinity Edge", "Runaan's Hurricane"]
    assert {b["ids"][0] for b in builds["boots"]} == {BOOTS}
    assert {i["ids"][0] for i in builds["items"]} == {LEGENDARY_A, LEGENDARY_B}


async def test_runes_and_spells_are_resolved_for_rendering(client, corpus):
    body = (await client.get(f"/api/champions/{SUBJECT}?patch={PATCH}&min_games=1")).json()

    keystone = body["runes"]["keystones"][0]
    assert keystone["ids"] == [8005]
    assert keystone["runes"][0]["icon_url"], "keystone must carry an icon"

    page = body["runes"]["pages"][0]
    # style + 4 primary + style + 2 sub + 3 shards
    assert len(page["ids"]) == 11

    spells = body["spells"][0]
    assert [s["name"] for s in spells["spells"]] == ["Flash", "Teleport"]


async def test_lane_and_team_counters_answer_different_questions(client, corpus):
    body = (await client.get(f"/api/champions/{SUBJECT}?patch={PATCH}&min_games=1")).json()
    lane = {p["champion"]["id"] for p in body["counters"]["lane"]}
    team = {p["champion"]["id"] for p in body["counters"]["team"]}

    # Ahri is MIDDLE, so her lane opponent is the enemy MIDDLE only...
    enemy_mid = RED[0]
    assert lane == {enemy_mid}
    # ...while the whole enemy team is what decides the game.
    assert team == set(RED)
    # Worst first: "weak against" is the question people arrive with.
    rates = [p["confidence_win_rate"] for p in body["counters"]["team"]]
    assert rates == sorted(rates)


async def test_synergies_list_allies_best_first(client, corpus):
    body = (await client.get(f"/api/champions/{SUBJECT}?patch={PATCH}&min_games=1")).json()
    allies = {p["champion"]["id"] for p in body["synergies"]}

    assert allies == set(BLUE) - {SUBJECT}
    assert SUBJECT not in allies
    # Each synergy says which lane the ally was in.
    assert all(p["position"] for p in body["synergies"])
    rates = [p["confidence_win_rate"] for p in body["synergies"]]
    assert rates == sorted(rates, reverse=True)


async def test_unknown_position_for_this_champion_is_an_honest_404(client, corpus):
    response = await client.get(
        f"/api/champions/{SUBJECT}?patch={PATCH}&position=UTILITY&min_games=1"
    )
    assert response.status_code == 404
    assert "UTILITY" in response.json()["detail"]


async def test_invalid_position_is_rejected(client, corpus):
    response = await client.get(f"/api/champions/{SUBJECT}?patch={PATCH}&position=BANANA")
    assert response.status_code == 400


async def test_champion_with_no_data_says_so(client, corpus):
    response = await client.get(f"/api/champions/999999?patch={PATCH}&min_games=1")
    assert response.status_code == 404
    assert PATCH in response.json()["detail"]


async def test_min_games_filters_builds_as_well_as_matchups(client, corpus):
    """The control is labelled "min games"; it must mean the whole page.

    Builds were previously floored only at aggregation time, so raising the
    filter narrowed the counters while the build panel silently ignored it.
    """
    generous = (
        await client.get(f"/api/champions/{SUBJECT}?patch={PATCH}&min_games=1")
    ).json()
    assert generous["builds"]["items"], "sanity: builds exist at a low floor"

    # Every facet in this corpus has exactly 12 games.
    strict = (
        await client.get(f"/api/champions/{SUBJECT}?patch={PATCH}&min_games=13")
    ).json()
    assert strict["builds"]["items"] == []
    assert strict["builds"]["complete"] == []
    assert strict["runes"]["keystones"] == []
    assert strict["counters"]["lane"] == []


# --------------------------------------------------- timeline-derived sections


async def test_build_basis_stays_final_inventory_without_timelines(client, corpus):
    """The disclaimer is only removable once we have measured purchase order."""
    body = (await client.get(f"/api/champions/{SUBJECT}?patch={PATCH}&min_games=1")).json()
    assert body["builds"]["basis"] == "final_inventory"
    assert body["builds"]["path"] == []
    assert body["laning"]["games"] == 0
    assert body["laning"]["avg_score"] is None
    assert body["skills"]["priority"] == []


async def test_facet_decoration_matches_the_facet_kind(client, corpus):
    """Regression: a catch-all branch handed every non-item facet rune icons.

    Skill slots are 1-4, so decorating them as runes produced silent nonsense
    rather than an error.
    """
    from app.api.routes.champions import _facet_entry
    from app.services.static_data import static_data

    class Row:
        facet_ids = [1, 3, 2]
        games = 5
        wins = 3
        win_rate = 0.6
        pick_rate = 0.5

    skills = _facet_entry(Row(), static_data, "skill_priority")
    assert skills.ids == [1, 3, 2]
    assert skills.runes == [] and skills.items == [] and skills.spells == []

    path = _facet_entry(Row(), static_data, "build_path")
    assert len(path.items) == 3, "an ordered build path is items, not runes"
