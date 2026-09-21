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


# ------------------------------------------------- patch change and level one

# A queue nobody else seeds, so the list of patches held is exactly ours and
# "the patch before" is not some other test's private patch.
QUEUE = 4420
CHANGER = 9_101
Q_FIRST = [1, 3, 2, 1, 1, 4, 1, 3, 1, 3, 4, 3, 3, 2, 2, 4, 2, 2]
E_FIRST = [3, 1, 2, 1, 1, 4, 1, 3, 1, 3, 4, 3, 3, 2, 2, 4, 2, 2]


async def _two_patches() -> None:
    from sqlalchemy import func, select

    from app.db.models import Match

    async with SessionLocal() as session:
        if await session.scalar(select(func.count()).where(Match.queue_id == QUEUE)):
            return

    def games(wins: int, total: int) -> list[list[dict]]:
        return [
            [participant(CHANGER, "MIDDLE", 100, i < wins,
                         skill_order=Q_FIRST if i % 4 else E_FIRST)]
            for i in range(total)
        ]

    # 8 of 40 then 32 of 40: the 95% Wilson intervals are about 0.11 to 0.35
    # and 0.65 to 0.90, so this is a move the page is allowed to report.
    await seed("7.1", games(8, 40), queue_id=QUEUE)
    await seed("7.2", games(32, 40), queue_id=QUEUE)
    async with SessionLocal() as session:
        for patch in ("7.1", "7.2"):
            kwargs = {"patch": patch, "queue_id": QUEUE, "rank_bracket": ALL_BRACKETS}
            await rebuild_champion_stats(session, **kwargs)
            await rebuild_facet_stats(session, **kwargs, min_games=1, taxonomy=taxonomy())


async def test_a_change_since_last_patch_is_reported_only_when_it_is_real(client):
    await _two_patches()
    body = (
        await client.get(f"/api/champions/{CHANGER}?patch=7.2&queue_id={QUEUE}&min_games=1")
    ).json()
    previous = body["overview"]["previous"]
    assert previous["patch"] == "7.1"
    assert previous["games"] == 40
    assert previous["win_rate"] == pytest.approx(0.2)
    assert previous["win_rate_moved"] is True
    # Picked in every game on both patches: a pick rate that did not move.
    assert previous["pick_rate_moved"] is False


async def test_the_oldest_patch_held_has_nothing_to_compare_with(client):
    await _two_patches()
    body = (
        await client.get(f"/api/champions/{CHANGER}?patch=7.1&queue_id={QUEUE}&min_games=1")
    ).json()
    assert body["overview"]["previous"] is None


async def test_the_level_one_pick_is_its_own_facet(client):
    await _two_patches()
    body = (
        await client.get(f"/api/champions/{CHANGER}?patch=7.2&queue_id={QUEUE}&min_games=1")
    ).json()
    first = body["skills"]["first"]
    assert [(f["ids"], f["games"]) for f in first] == [([1], 30), ([3], 10)]


# ---------------------------------------------------------------- the profile

# Not a real champion, so the profile is checked against data these tests
# wrote rather than against whatever Data Dragon says this week.
TESTY = 9_201


@pytest.fixture
def testy(monkeypatch):
    from app.services.static_data import (
        Ability,
        Champion,
        ChampionLore,
        Skin,
        static_data,
    )

    monkeypatch.setitem(
        static_data.champions_by_id,
        TESTY,
        Champion(
            id=TESTY, key="Testy", name="Testy", title="the Fixture", tags=["Mage"],
            partype="Mana", blurb="A short story.",
            info={"attack": 3, "defense": 4, "magic": 8, "difficulty": 5},
            stats={
                "hp": 590, "hpperlevel": 104, "mp": 418, "mpperlevel": 25,
                "attackspeed": 0.668, "attackspeedperlevel": 2.2, "movespeed": 330,
            },
        ),
    )
    monkeypatch.setitem(
        static_data.lore_by_id,
        TESTY,
        ChampionLore(
            lore="A long story.",
            ally_tips=["Stay back."],
            passive=Ability(slot="P", name="Heal", description="Heals.", image="P.png"),
            spells=[
                Ability(slot=s, name=f"Spell {s}", description="Does it.", image=f"{s}.png")
                for s in "QWER"
            ],
        ),
    )
    monkeypatch.setitem(
        static_data.skins_by_champion,
        TESTY,
        [
            Skin(id=TESTY * 1000, num=0, name="Testy"),
            Skin(id=TESTY * 1000 + 1, num=1, name="Gilded Testy", rarity="Epic",
                 lines=[1], chromas=3),
            Skin(id=TESTY * 1000 + 2, num=2, name="Plain Testy"),
        ],
    )
    monkeypatch.setitem(static_data.skin_lines, 1, "Gilded")
    return TESTY


async def test_the_profile_answers_where_the_numbers_cannot(client, testy):
    """The detail is a 404 on a patch with no games, which is every new
    champion's first day. The story must not share that fate."""
    assert (await client.get(f"/api/champions/{testy}?patch={PATCH}")).status_code == 404

    response = await client.get(f"/api/champions/{testy}/profile")
    assert response.status_code == 200, response.text[:300]
    body = response.json()
    assert body["champion"]["name"] == "Testy"
    assert body["lore"] == "A long story."
    assert body["resource"] == "Mana"
    assert body["detail_loaded"] is True
    assert [r["value"] for r in body["ratings"]] == [3, 4, 8, 5]
    assert [a["slot"] for a in body["abilities"]] == ["Q", "W", "E", "R"]
    assert body["passive"]["icon_url"].endswith("/img/passive/P.png")


async def test_base_stats_at_level_eighteen(client, testy):
    stats = {s["key"]: s for s in (await client.get(f"/api/champions/{testy}/profile")).json()["stats"]}
    assert stats["hp"]["level18"] == pytest.approx(590 + 104 * 17)
    assert stats["mp"]["label"] == "Mana", "the resource row takes the champion's own name"
    # Attack speed grows by a percentage of its base, not by a flat amount.
    assert stats["attackspeed"]["level18"] == pytest.approx(0.668 * (1 + 0.022 * 17))
    assert stats["movespeed"]["level18"] is None
    assert stats["movespeed"]["growth_published"] is True, "it does not grow; that is known"


def test_an_unpublished_growth_is_withheld_not_printed_as_level_one():
    from app.api.routes.champions import _base_stats

    stats = {s.key: s for s in _base_stats(
        {"attackdamage": 53, "attackdamageperlevel": 0, "hp": 590, "hpperlevel": 104},
        "Mana",
        {"attackdamageperlevel"},
    )}
    assert stats["attackdamage"].level18 is None
    assert stats["attackdamage"].growth_published is False
    assert stats["hp"].level18 == pytest.approx(590 + 104 * 17)


async def test_the_skins_carry_their_line_and_art(client, testy):
    skins = (await client.get(f"/api/champions/{testy}/profile")).json()["skins"]
    assert [s["num"] for s in skins] == [0, 1, 2]
    gilded = skins[1]
    assert (gilded["line"], gilded["rarity"], gilded["chromas"]) == ("Gilded", "Epic", 3)
    assert gilded["splash_url"].endswith(f"/{testy}/splash-art/centered/skin/1")
    assert all(s["sightings"] is None for s in skins), "no sightings yet, not zero sightings"


async def test_skin_counts_appear_once_the_champion_clears_the_floor(client, testy):
    from types import SimpleNamespace

    from app.services.skins import MIN_CHAMPION_SIGHTINGS, record_sightings

    await record_sightings(
        platform="EUW1", game_id=881_000_001, queue_id=420, in_progress=True,
        participants=[
            SimpleNamespace(champion_id=testy, skin_index=1, state="unknown")
            for _ in range(MIN_CHAMPION_SIGHTINGS)
        ],
        chroma_parent={},
    )
    body = (await client.get(f"/api/champions/{testy}/profile")).json()
    assert body["skin_sightings"] == MIN_CHAMPION_SIGHTINGS
    counts = {s["num"]: s["sightings"] for s in body["skins"]}
    assert counts == {0: 0, 1: MIN_CHAMPION_SIGHTINGS, 2: 0}, "zero is now a real answer"


async def test_an_unknown_champion_has_no_profile(client):
    assert (await client.get("/api/champions/987654/profile")).status_code == 404


# ---------------------------------------------------------------- the players

BOARD = 9_301
THIN_BOARD = 9_302


def _puuid(name: str) -> str:
    return f"champ-board-{name}".ljust(78, "0")


async def _board() -> None:
    from sqlalchemy import func, select

    from app.db.models import MatchParticipant

    async with SessionLocal() as session:
        if await session.scalar(
            select(func.count()).where(MatchParticipant.champion_id == BOARD)
        ):
            return

    def games(name: str, champion: int, n: int, *, score: float, scored: int, wins: int,
              riot_name: str):
        return [
            [participant(champion, "MIDDLE", 100, i < wins, puuid=_puuid(name),
                         performance_score=score if i < scored else None,
                         riot_id_game_name=riot_name, riot_id_tagline="EUW")]
            for i in range(n)
        ]

    early = (
        games("ace", BOARD, 6, score=8.0, scored=6, wins=2, riot_name="OldAce")
        + games("bee", BOARD, 6, score=6.0, scored=6, wins=5, riot_name="Bee")
        + games("cat", BOARD, 7, score=7.0, scored=7, wins=4, riot_name="Cat")
        + games("dog", BOARD, 5, score=5.0, scored=5, wins=1, riot_name="Dog")
        # Four games: one short of the floor.
        + games("elk", BOARD, 4, score=9.9, scored=4, wins=4, riot_name="Elk")
        # Six games, two of them scored: short of the scored floor.
        + games("fox", BOARD, 6, score=9.5, scored=2, wins=6, riot_name="Fox")
        + games("gnu", THIN_BOARD, 6, score=7.0, scored=6, wins=3, riot_name="Gnu")
        + games("hen", THIN_BOARD, 6, score=6.0, scored=6, wins=3, riot_name="Hen")
    )
    await seed("BOARD_EARLY", early, game_creation=1_000)
    # A later game on another champion renames the first player. The profile
    # link has to use the name they go by now.
    await seed(
        "BOARD_LATE",
        [[participant(1, "MIDDLE", 100, True, puuid=_puuid("ace"),
                      riot_id_game_name="NewAce", riot_id_tagline="EUW")]],
        game_creation=2_000,
    )


async def test_the_board_ranks_by_score_and_keeps_the_record_beside_it(client):
    await _board()
    body = (await client.get(f"/api/champions/{BOARD}/players")).json()
    assert body["qualified"] == 4
    rows = body["players"]
    assert [r["puuid"] for r in rows] == [_puuid(n) for n in ("ace", "cat", "bee", "dog")]
    ace = rows[0]
    assert (ace["games"], ace["wins"], ace["avg_score"]) == (6, 2, pytest.approx(8.0))
    assert ace["game_name"] == "NewAce", "the name they go by now"
    assert ace["platform"] == "euw1"


async def test_players_under_either_floor_stay_off_the_board(client):
    await _board()
    rows = (await client.get(f"/api/champions/{BOARD}/players")).json()["players"]
    names = {r["puuid"] for r in rows}
    assert _puuid("elk") not in names, "four games is one short"
    assert _puuid("fox") not in names, "two scored games is one short"


async def test_a_board_of_two_is_withheld(client):
    await _board()
    body = (await client.get(f"/api/champions/{THIN_BOARD}/players")).json()
    assert body["qualified"] == 2
    assert body["players"] == []
