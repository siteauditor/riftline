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
    # Two finished items is a game that ended early, not a completed build:
    # most listed "builds" were one or two items under a label that said "the
    # full set".
    assert builds["complete"] == []
    assert {b["ids"][0] for b in builds["boots"]} == {BOOTS}
    assert {i["ids"][0] for i in builds["items"]} == {LEGENDARY_A, LEGENDARY_B}
    assert {i["items"][0]["name"] for i in builds["items"]} == {"Infinity Edge", "Runaan's Hurricane"}
    # Every facet carries the range its sample supports.
    item = builds["items"][0]
    assert item["range_low"] <= item["win_rate"] <= item["range_high"]


async def test_runes_and_spells_are_resolved_for_rendering(client, corpus):
    body = (await client.get(f"/api/champions/{SUBJECT}?patch={PATCH}&min_games=1")).json()

    keystone = body["runes"]["keystones"][0]
    assert keystone["ids"] == [8005]
    assert keystone["runes"][0]["icon_url"], "keystone must carry an icon"
    assert keystone["runes"][0]["name"] == "Press the Attack"

    page = body["runes"]["pages"][0]
    # style + 4 primary + style + 2 sub + 3 shards
    assert len(page["ids"]) == 11
    # The shards are named and drawn too: they were grey dots with no name.
    shards = page["runes"][-3:]
    assert [s["name"] for s in shards] == ["Adaptive Force", "Move Speed", "Health Scaling"]
    assert all(s["icon_url"] for s in shards)
    assert all(r["name"] for r in page["runes"])

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
    # Worst first: "weak against" is the question people arrive with, read as
    # the gap from Ahri's own rate at the team strength.
    lifts = [p["lift"] for p in body["counters"]["team"]]
    assert lifts == sorted(lifts)
    assert all(p["own_rate"] == pytest.approx(0.5) for p in body["counters"]["team"])


async def test_matchups_are_read_against_the_champions_own_rate_as_the_draft_reads_them(client):
    """Ordered by the gap from the champion's own rate, pulled toward it by the
    lane prior: a 14-26 record is the hard one, a 3-3 sits at the champion's
    rate whatever its range, and a 31-29 is not hard however many games back
    it. The list is not cut at 15, or most opponents could not be looked up.
    Ranked by the raw record, the hardest five on each of the 31 busiest local
    pages were all level by this reading (2026-09-24)."""
    from sqlalchemy import func, select

    from app.db.models import Match, MatchupStat

    patch = "C1.50"
    async with SessionLocal() as session:
        seeded = (
            await session.execute(select(func.count(Match.match_id)).where(Match.patch == patch))
        ).scalar()
    if not seeded:
        positions = ("MIDDLE", "JUNGLE", "TOP", "BOTTOM", "UTILITY")
        await seed(patch, [
            [participant(c, p, 100, i % 2 == 0) for c, p in zip(BLUE, positions, strict=True)]
            + [participant(c, p, 200, i % 2 == 1) for c, p in zip(RED, positions, strict=True)]
            for i in range(6)
        ])
        thin, solid, big = 112, 7, 99  # Viktor, LeBlanc, Lux
        fillers = [1, 3, 4, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21]
        rows = [(thin, 6, 3), (solid, 40, 14), (big, 60, 31)] + [(f, 20, 12) for f in fillers]
        async with SessionLocal() as session:
            await rebuild_champion_stats(session, patch=patch, queue_id=420, rank_bracket=ALL_BRACKETS)
            for enemy, games, wins in rows:
                session.add(MatchupStat(
                    patch=patch, queue_id=420, rank_bracket=ALL_BRACKETS, scope="LANE",
                    team_position="MIDDLE", champion_id=SUBJECT, enemy_champion_id=enemy,
                    games=games, wins=wins,
                ))
            await session.commit()

    body = (await client.get(f"/api/champions/{SUBJECT}?patch={patch}&min_games=5")).json()
    lane = body["counters"]["lane"]
    order = [p["champion"]["id"] for p in lane]

    assert len(lane) == 20, "every matchup over the floor, not the first 15"
    assert order[0] == 7, "14-26 is the hardest matchup"
    assert order.index(112) < order.index(99)
    by_id = {p["champion"]["id"]: p for p in lane}
    hardest = by_id[7]
    assert hardest["own_rate"] == pytest.approx(0.5)
    assert hardest["lift"] == pytest.approx((14 - 40 * 0.5) / (40 + 100))
    assert hardest["patches"] == [patch]
    # A 3-3 at the champion's own rate moves nothing and calls nothing.
    assert (by_id[112]["lift"], by_id[112]["call"]) == (0.0, "level")
    assert [p["lift"] for p in lane] == sorted(p["lift"] for p in lane)


async def test_synergies_list_allies_best_first(client, corpus):
    body = (await client.get(f"/api/champions/{SUBJECT}?patch={PATCH}&min_games=1")).json()
    allies = {p["champion"]["id"] for p in body["synergies"]}

    assert allies == set(BLUE) - {SUBJECT}
    assert SUBJECT not in allies
    # Each ally says the lane it was in most, and is read like the draft's.
    assert all(p["position"] for p in body["synergies"])
    assert all(p["call"] == "level" for p in body["synergies"]), "a dozen games calls nothing at 500"
    lifts = [p["lift"] for p in body["synergies"]]
    assert lifts == sorted(lifts, reverse=True)


async def test_an_ally_seen_in_two_roles_is_one_record_on_the_page(client):
    """Listed per role, one ally's games split into thin halves; the draft
    reads an ally once, and so does the page, under the role it played most."""
    from app.db.models import ChampionStat, Match, SynergyStat

    patch, champion, ally = "C1.70", 9711, 9712
    async with SessionLocal() as session:
        if not await session.get(Match, "ALLY_TWO_ROLES"):
            session.add(Match(
                match_id="ALLY_TWO_ROLES", platform_id="EUW1", queue_id=420, patch=patch,
                game_creation=1, game_duration=1800, is_remake=False, teams=[],
            ))
            session.add(ChampionStat(
                patch=patch, queue_id=420, rank_bracket=ALL_BRACKETS, champion_id=champion,
                team_position="MIDDLE", games=60, wins=30, bans=0, pool_games=100,
            ))
            for role, games, wins in (("JUNGLE", 8, 6), ("TOP", 5, 4)):
                session.add(SynergyStat(
                    patch=patch, queue_id=420, rank_bracket=ALL_BRACKETS, team_position="MIDDLE",
                    champion_id=champion, ally_position=role, ally_champion_id=ally,
                    games=games, wins=wins,
                ))
            await session.commit()

    body = (await client.get(f"/api/champions/{champion}?patch={patch}&min_games=10")).json()

    (entry,) = [p for p in body["synergies"] if p["champion"]["id"] == ally]
    assert (entry["games"], entry["wins"], entry["position"]) == (13, 10, "JUNGLE")


async def test_a_role_without_games_serves_the_main_role_and_says_so(client, corpus):
    """A 404 here opened the page on its story with no word of why. The main
    role is served instead, with what was asked, so the page can say so."""
    response = await client.get(
        f"/api/champions/{SUBJECT}?patch={PATCH}&position=UTILITY&min_games=1"
    )
    assert response.status_code == 200
    body = response.json()
    assert (body["fallback"], body["requested_position"]) == ("role", "UTILITY")
    assert body["position"] == body["positions"][0]["position"] != "UTILITY"


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


# ------------------------------------------------------------- tier letters


async def test_a_champion_carries_the_same_letter_as_on_the_tier_list(client):
    """Measured on 2026-09-22: the champion page ranked against its own facet
    floor of 5 games, the tier list against 20, and 82 of 174 rows showed a
    different letter one click apart."""
    from app.db.models import ChampionStat
    from app.services.aggregate import TIER_MIN_GAMES

    patch, queue = "T7.77", 4777
    # Twelve champions over the floor, spread from strong to weak, and three
    # under it that the looser field used to rank above some of them.
    field = [(9400 + i, 200 - i * 10, 0.62 - i * 0.02) for i in range(12)]
    thin = [(9450 + i, 8, 0.75) for i in range(3)]
    async with SessionLocal() as session:
        for champion_id, games, rate in field + thin:
            session.add(
                ChampionStat(
                    patch=patch, queue_id=queue, rank_bracket=ALL_BRACKETS,
                    champion_id=champion_id, team_position="MIDDLE",
                    games=games, wins=round(games * rate), pool_games=1000, bans=0,
                    avg_kills=5, avg_deaths=5, avg_assists=5, avg_cs_per_min=7,
                    avg_gold=11000, avg_damage=20000, avg_vision=20, timeline_games=0,
                )
            )
        await session.commit()

    meta = (
        await client.get(f"/api/meta/champions?patch={patch}&queue_id={queue}&position=MIDDLE")
    ).json()
    listed = {r["champion"]["id"]: r["tier"] for r in meta["rows"]}
    assert len(listed) == len(field), "the list shows the champions over its floor"

    for champion_id, _, _ in field + thin:
        page = (
            await client.get(
                f"/api/champions/{champion_id}?patch={patch}&queue_id={queue}"
                "&position=MIDDLE&min_games=5"
            )
        ).json()
        assert page["overview"]["tier"] == listed.get(champion_id), champion_id
    assert meta["min_games"] == TIER_MIN_GAMES


# ------------------------------------------------------ fallbacks and floors


async def test_a_patch_that_is_not_held_serves_the_default_and_says_so(client):
    """An old link names a patch the site no longer holds: the page served a
    404 and its Patch select went blank. The default patch comes back, named."""
    from app.db.models import ChampionStat, Match

    queue, held, champion = 4888, "F1.10", 9701
    async with SessionLocal() as session:
        if not await session.get(Match, "FALLBACK_PATCH_1"):
            session.add(Match(
                match_id="FALLBACK_PATCH_1", platform_id="EUW1", queue_id=queue, patch=held,
                game_creation=1, game_duration=1800, is_remake=False, teams=[],
            ))
            session.add(ChampionStat(
                patch=held, queue_id=queue, rank_bracket=ALL_BRACKETS, champion_id=champion,
                team_position="MIDDLE", games=30, wins=15, bans=0, pool_games=100,
            ))
            await session.commit()

    response = await client.get(f"/api/champions/{champion}?patch=F1.05&queue_id={queue}")

    assert response.status_code == 200, response.text[:300]
    body = response.json()
    assert (body["fallback"], body["requested_patch"], body["patch"]) == ("patch", "F1.05", held)


async def test_thin_timeline_figures_are_withheld(client):
    """One stomp is not a lane: a lane's gold at 14 needs five games with a
    timeline, and the champion's own laning figures ten."""
    from sqlalchemy import select, update

    from app.db.models import ChampionStat, Match, MatchupStat
    from app.services.aggregate import MIN_LANE_TIMELINES, MIN_LANING_TIMELINES

    patch = "C1.60"
    async with SessionLocal() as session:
        seeded = await session.get(Match, f"{patch}_0")
    if not seeded:
        positions = ("MIDDLE", "JUNGLE", "TOP", "BOTTOM", "UTILITY")
        await seed(patch, [
            [participant(c, p, 100, i % 2 == 0) for c, p in zip(BLUE, positions, strict=True)]
            + [participant(c, p, 200, i % 2 == 1) for c, p in zip(RED, positions, strict=True)]
            for i in range(6)
        ])
        async with SessionLocal() as session:
            await rebuild_champion_stats(session, patch=patch, queue_id=420, rank_bracket=ALL_BRACKETS)
            for enemy, timelines in ((112, MIN_LANE_TIMELINES - 1), (7, MIN_LANE_TIMELINES)):
                session.add(MatchupStat(
                    patch=patch, queue_id=420, rank_bracket=ALL_BRACKETS, scope="LANE",
                    team_position="MIDDLE", champion_id=SUBJECT, enemy_champion_id=enemy,
                    games=20, wins=10, timeline_games=timelines, avg_gold_diff_14=-640.0,
                    avg_laning_score=0.41,
                ))
            await session.commit()

    async def page(laning_timelines: int) -> dict:
        async with SessionLocal() as session:
            await session.execute(
                update(ChampionStat)
                .where(ChampionStat.patch == patch, ChampionStat.champion_id == SUBJECT,
                       ChampionStat.team_position == "MIDDLE")
                .values(timeline_games=laning_timelines, avg_laning_score=0.55,
                        avg_gold_diff_14=310.0, avg_cs_diff_14=4.5)
            )
            await session.commit()
            assert (await session.execute(select(ChampionStat.id).where(ChampionStat.patch == patch))).first()
        return (await client.get(f"/api/champions/{SUBJECT}?patch={patch}&position=MIDDLE&min_games=5")).json()

    body = await page(MIN_LANING_TIMELINES - 1)
    gold = {p["champion"]["id"]: p["avg_gold_diff_14"] for p in body["counters"]["lane"]}
    assert gold[112] is None and gold[7] == -640.0
    assert body["laning"]["games"] == MIN_LANING_TIMELINES - 1
    assert (body["laning"]["avg_score"], body["laning"]["avg_gold_diff"]) == (None, None)
    assert body["laning"]["min_games"] == MIN_LANING_TIMELINES

    body = await page(MIN_LANING_TIMELINES)
    assert (body["laning"]["avg_score"], body["laning"]["avg_gold_diff"]) == (0.55, 310.0)



async def test_a_few_good_games_do_not_top_a_long_record(client):
    """Ranked on the raw average, 13 of the 15 best Lee Sin players had under
    ten games. Pulled toward the champion's average by nine games, a 6.2 over
    twenty games ranks above a 6.5 over five."""
    champion = 9730

    def games(name: str, n: int, score: float):
        return [
            [participant(champion, "MIDDLE", 100, True, puuid=_puuid(f"shrink-{name}"),
                         performance_score=score, riot_id_game_name=name, riot_id_tagline="EUW")]
            for _ in range(n)
        ]

    from sqlalchemy import func, select

    from app.db.models import MatchParticipant

    async with SessionLocal() as session:
        seeded = await session.scalar(select(func.count()).where(MatchParticipant.champion_id == champion))
    if not seeded:
        await seed("BOARD_SHRINK", games("few", 5, 6.5) + games("many", 20, 6.2) + games("low", 10, 4.0))

    body = (await client.get(f"/api/champions/{champion}/players")).json()

    order = [r["game_name"] for r in body["players"]]
    assert order.index("many") < order.index("few")
    assert body["score_strength"] == 9
    assert body["champion_score"] == pytest.approx((5 * 6.5 + 20 * 6.2 + 10 * 4.0) / 35)
    few = next(r for r in body["players"] if r["game_name"] == "few")
    assert few["avg_score"] == pytest.approx(6.5)
    assert few["ranked_score"] < few["avg_score"]


async def test_an_item_is_set_against_its_slot_once_the_item_guide_has_the_buyers(client, corpus):
    """A final inventory favours winners, so an item's own win rate ran 2.3
    points above its champion. The item guide's figure against the same
    champion's other items in the slot is the one worth reading."""
    from app.db.models import ItemChampionStat

    async with SessionLocal() as session:
        for item, buyers, wins, expected in ((LEGENDARY_A, 25, 15, 12.5), (LEGENDARY_B, 12, 8, 6.0)):
            session.add(ItemChampionStat(
                patch=PATCH, queue_id=420, rank_bracket=ALL_BRACKETS, item_id=item,
                champion_id=SUBJECT, champion_players=40, buyers=buyers, buyer_wins=wins,
                expected_wins=expected, slot_games=[0, buyers, 0, 0],
            ))
        await session.commit()

    body = (await client.get(f"/api/champions/{SUBJECT}?patch={PATCH}&min_games=1")).json()

    by_item = {i["ids"][0]: i for i in body["builds"]["items"]}
    assert by_item[LEGENDARY_A]["slot_delta"] == pytest.approx((15 - 12.5) / 25)
    assert by_item[LEGENDARY_A]["slot_buyers"] == 25
    # Twelve buyers is under the item guide's floor of twenty: said, not shown.
    assert (by_item[LEGENDARY_B]["slot_delta"], by_item[LEGENDARY_B]["slot_buyers"]) == (None, 12)
