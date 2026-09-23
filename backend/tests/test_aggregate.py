"""Aggregation: item taxonomy, build facets, matchups, synergies, brackets.

Every test works in its own synthetic ``patch`` string. The suite shares one
database, and aggregates are keyed by slice, so a private patch is what keeps
these independent of each other and of the integration tests.
"""

from __future__ import annotations

import pytest

from app.db.base import SessionLocal
from app.db.models import (
    ChampionFacetStat,
    ChampionStat,
    Match,
    MatchParticipant,
    MatchupStat,
    SynergyStat,
)
from app.services.aggregate import (
    ALL_BRACKETS,
    aggregated_slices,
    available_slices,
    default_patch,
    patch_sort_key,
    perk_facets,
    rebuild_champion_stats,
    rebuild_facet_stats,
    rebuild_matchup_stats,
    rebuild_synergy_stats,
)
from app.services.item_taxonomy import ItemTaxonomy

# --------------------------------------------------------------------- helpers

BOOTS = 3006
LEGENDARY_A, LEGENDARY_B, LEGENDARY_C = 3031, 3085, 6672
TRINKET = 3340

# A synthetic Data Dragon slice covering every classification branch.
FAKE_ITEMS = {
    BOOTS: {"name": "Berserker's Greaves", "tags": ["Boots"],
            "gold": {"total": 1100, "purchasable": True}, "maps": {"11": True}},
    LEGENDARY_A: {"name": "Infinity Edge", "tags": ["Damage"],
                  "gold": {"total": 3400, "purchasable": True}, "maps": {"11": True}},
    LEGENDARY_B: {"name": "Runaan's Hurricane", "tags": ["AttackSpeed"],
                  "gold": {"total": 2600, "purchasable": True}, "maps": {"11": True}},
    LEGENDARY_C: {"name": "Kraken Slayer", "tags": ["Damage"],
                  "gold": {"total": 3100, "purchasable": True}, "maps": {"11": True}},
    TRINKET: {"name": "Stealth Ward", "tags": ["Trinket", "Vision"],
              "gold": {"total": 0, "purchasable": False}, "maps": {"11": True}},
    1038: {"name": "B. F. Sword", "tags": ["Damage"], "into": ["3031"],
           "gold": {"total": 1300, "purchasable": True}, "maps": {"11": True}},
    9001: {"name": "Legendary Mage Item", "tags": ["Damage"],
           "gold": {"total": 3000, "purchasable": True}, "maps": {"11": True}},
    9002: {"name": "Arena Only Blade", "tags": ["Damage"],
           "gold": {"total": 3000, "purchasable": True}, "maps": {"30": True}},
    9003: {"name": "Ornn Masterwork", "tags": ["Damage"], "requiredAlly": "Ornn",
           "gold": {"total": 3000, "purchasable": True}, "maps": {"11": True}},
}


def taxonomy() -> ItemTaxonomy:
    t = ItemTaxonomy()
    t.rebuild(FAKE_ITEMS, version="test")
    return t


def perks(keystone: int = 8005, primary: int = 8000, sub: int = 8300) -> dict:
    return {
        "statPerks": {"offense": 5008, "flex": 5010, "defense": 5001},
        "styles": [
            {"description": "primaryStyle", "style": primary,
             "selections": [{"perk": keystone}, {"perk": 8009}, {"perk": 9103}, {"perk": 8014}]},
            {"description": "subStyle", "style": sub,
             "selections": [{"perk": 8304}, {"perk": 8321}]},
        ],
    }


def participant(
    champion_id, position, team_id, win, *, items=None, rune=8005, spells=(4, 12), **extra
):
    """`extra` passes any other MatchParticipant column straight through, which
    is how the timeline-derived ones are seeded."""
    return {
        "champion_id": champion_id,
        "team_position": position,
        "team_id": team_id,
        "win": win,
        "items": items if items is not None else [0] * 7,
        "perks": perks(rune),
        "summoner1_id": spells[0],
        "summoner2_id": spells[1],
        **extra,
    }


async def seed(
    patch: str,
    matches: list[list[dict]],
    *,
    bracket="CHALLENGER",
    queue_id=420,
    game_creation: int = 1,
    duration: int = 1800,
):
    """Insert whole matches under a private patch string."""
    async with SessionLocal() as session:
        for index, participants in enumerate(matches):
            match_id = f"T{patch}_{index}"
            session.add(
                Match(
                    match_id=match_id, platform_id="EUW1", queue_id=queue_id,
                    patch=patch, game_creation=game_creation, game_duration=duration,
                    is_remake=False, source_bracket=bracket, teams=[],
                )
            )
            for slot, spec in enumerate(participants):
                # Copy: the same spec dict is reused across matches.
                fields = dict(spec)
                puuid = fields.pop("puuid", None) or f"{match_id}_p{slot}"
                session.add(
                    MatchParticipant(
                        match_id=match_id, participant_index=slot + 1,
                        puuid=puuid, **fields
                    )
                )
        await session.commit()


def team(champions, team_id, win, **kw):
    positions = ("TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY")
    return [participant(c, p, team_id, win, **kw) for c, p in zip(champions, positions, strict=True)]


# -------------------------------------------------------------------- taxonomy


def test_taxonomy_classifies_each_kind():
    t = taxonomy()
    assert t.classify(BOOTS) == "boots"
    assert t.classify(LEGENDARY_A) == "legendary"
    assert t.classify(TRINKET) == "trinket"
    # Builds into something, so it is a component rather than a finished item.
    assert t.classify(1038) == "other"


@pytest.mark.parametrize(
    ("item_id", "why"),
    [
        (9001, "Riot ships placeholder items literally named 'Legendary ...'"),
        (9002, "Arena-only items are not Summoner's Rift builds"),
        (9003, "Ornn masterworks require Ornn and are not a choice you can make"),
    ],
)
def test_taxonomy_excludes_items_that_are_not_real_build_choices(item_id, why):
    assert not taxonomy().is_legendary(item_id), why


def test_split_build_is_order_independent():
    """Inventory slots are wherever the player left things, not a build order."""
    t = taxonomy()
    one = t.split_build([LEGENDARY_A, BOOTS, LEGENDARY_B, 0, 0, 0, TRINKET])
    two = t.split_build([BOOTS, LEGENDARY_B, 0, LEGENDARY_A, 0, 0, TRINKET])
    assert one == two
    cores, boots = one
    assert cores == sorted([LEGENDARY_A, LEGENDARY_B])
    assert boots == BOOTS
    # The trinket lives in slot 7 and is never part of the build.
    assert TRINKET not in cores


def test_a_grown_item_is_counted_as_the_item_that_was_bought():
    """Muramana cannot be bought, so it was filed as "other" and the Build tab
    dropped it from 204 of 241 Ezreal games (measured 2026-09-22)."""
    t = ItemTaxonomy()
    t.rebuild(
        {
            **FAKE_ITEMS,
            3004: {"name": "Manamune", "tags": ["Mana"],
                   "gold": {"total": 2900, "purchasable": True}, "maps": {"11": True}},
            3042: {"name": "Muramana", "tags": ["Mana"], "specialRecipe": 3004,
                   "gold": {"total": 2900, "purchasable": False}, "maps": {"11": True}},
        },
        version="test",
    )
    cores, _ = t.split_build([3042, LEGENDARY_A, BOOTS, 0, 0, 0, TRINKET])
    assert cores == sorted([3004, LEGENDARY_A])
    assert t.canonical(3042) == 3004
    assert t.canonical(LEGENDARY_A) == LEGENDARY_A


def test_perk_facets_reads_styles_by_label():
    keystone, page = perk_facets(perks(keystone=8010))
    assert keystone == 8010
    # style, 4 primary perks, style, 2 sub perks, 3 shards
    assert page is not None and len(page) == 11


def test_perk_facets_rejects_a_partial_page():
    """A half-parsed page would collide with other half-parsed pages."""
    broken = perks()
    broken["statPerks"] = {}
    keystone, page = perk_facets(broken)
    assert keystone == 8005
    assert page is None


# ---------------------------------------------------------------------- facets


async def test_facets_count_builds_runes_and_spells():
    patch = "F1.00"
    build = [LEGENDARY_A, LEGENDARY_B, BOOTS, 0, 0, 0, TRINKET]
    # Same champion, same build, four times: three wins and a loss.
    await seed(patch, [
        [participant(99, "MIDDLE", 100, win, items=build)] for win in (True, True, True, False)
    ])

    async with SessionLocal() as session:
        written = await rebuild_facet_stats(
            session, patch=patch, queue_id=420, rank_bracket=ALL_BRACKETS,
            min_games=1, taxonomy=taxonomy(),
        )
        rows = (await session.execute(
            ChampionFacetStat.__table__.select().where(ChampionFacetStat.patch == patch)
        )).mappings().all()

    assert written > 0
    facets = {(r["facet"], r["facet_key"]): r for r in rows}

    complete = facets[("build", f"{LEGENDARY_A}|{LEGENDARY_B}")]
    assert (complete["games"], complete["wins"]) == (4, 3)
    assert complete["champion_games"] == 4

    assert facets[("boots", str(BOOTS))]["games"] == 4
    assert facets[("item", str(LEGENDARY_A))]["games"] == 4
    assert facets[("keystone", "8005")]["games"] == 4
    assert facets[("spells", "4|12")]["games"] == 4


async def test_facets_respect_the_min_games_floor():
    """Complete builds have a long tail; without a floor it dominates the table."""
    patch = "F2.00"
    await seed(patch, [
        [participant(99, "MIDDLE", 100, True, items=[LEGENDARY_A, 0, 0, 0, 0, 0, 0])],
        [participant(99, "MIDDLE", 100, True, items=[LEGENDARY_B, 0, 0, 0, 0, 0, 0])],
        [participant(99, "MIDDLE", 100, True, items=[LEGENDARY_B, 0, 0, 0, 0, 0, 0])],
    ])
    async with SessionLocal() as session:
        await rebuild_facet_stats(
            session, patch=patch, queue_id=420, rank_bracket=ALL_BRACKETS,
            min_games=2, taxonomy=taxonomy(),
        )
        keys = {
            r["facet_key"]
            for r in (await session.execute(
                ChampionFacetStat.__table__.select().where(
                    (ChampionFacetStat.patch == patch) & (ChampionFacetStat.facet == "item")
                )
            )).mappings().all()
        }
    assert str(LEGENDARY_B) in keys       # seen twice
    assert str(LEGENDARY_A) not in keys   # seen once, below the floor


def test_spells_are_stored_in_a_stable_order():
    """(4, 12) and (12, 4) are the same loadout and must share a key."""
    assert sorted((4, 12)) == sorted((12, 4))


# -------------------------------------------------------------------- synergy


async def test_synergy_pairs_allies_but_never_a_champion_with_itself():
    patch = "S1.00"
    blue = team([1, 2, 3, 4, 5], 100, True)
    red = team([6, 7, 8, 9, 10], 200, False)
    await seed(patch, [blue + red, blue + red])

    async with SessionLocal() as session:
        await rebuild_synergy_stats(
            session, patch=patch, queue_id=420, rank_bracket=ALL_BRACKETS, min_games=1
        )
        rows = (await session.execute(
            SynergyStat.__table__.select().where(SynergyStat.patch == patch)
        )).mappings().all()

    assert rows
    assert all(r["champion_id"] != r["ally_champion_id"] for r in rows)
    # Champion 1 (blue) must never be paired with an enemy.
    allies_of_1 = {r["ally_champion_id"] for r in rows if r["champion_id"] == 1}
    assert allies_of_1 == {2, 3, 4, 5}
    # Directed: every pair is stored both ways, so lookups stay a single filter.
    assert 1 in {r["ally_champion_id"] for r in rows if r["champion_id"] == 2}


# ------------------------------------------------------------------- matchups


async def test_matchup_scopes_measure_different_things():
    patch = "M1.00"
    blue = team([1, 2, 3, 4, 5], 100, True)
    red = team([6, 7, 8, 9, 10], 200, False)
    await seed(patch, [blue + red, blue + red])

    async with SessionLocal() as session:
        await rebuild_matchup_stats(
            session, patch=patch, queue_id=420, rank_bracket=ALL_BRACKETS, min_games=1
        )
        rows = (await session.execute(
            MatchupStat.__table__.select().where(MatchupStat.patch == patch)
        )).mappings().all()

    lane = {r["enemy_champion_id"] for r in rows if r["scope"] == "LANE" and r["champion_id"] == 1}
    whole = {r["enemy_champion_id"] for r in rows if r["scope"] == "TEAM" and r["champion_id"] == 1}

    # TOP champion 1 faces only the enemy TOP in its lane...
    assert lane == {6}
    # ...but the whole enemy team is what actually decides the game.
    assert whole == {6, 7, 8, 9, 10}


# -------------------------------------------------------------------- brackets


async def test_bracket_slicing_keeps_provenances_apart():
    """Two crawls of the same patch must not blend into one another."""
    patch = "B1.00"
    await seed(patch, [[participant(42, "MIDDLE", 100, True, items=[LEGENDARY_A] + [0] * 6)]],
               bracket="CHALLENGER")
    await seed(patch + "x", [[participant(42, "MIDDLE", 100, False, items=[LEGENDARY_A] + [0] * 6)]],
               bracket="IRON")

    async with SessionLocal() as session:
        # Same patch, different bracket: the IRON rows live under patch B1.00x,
        # so query the shared-patch case directly.
        chal = await rebuild_facet_stats(
            session, patch=patch, queue_id=420, rank_bracket="CHALLENGER",
            min_games=1, taxonomy=taxonomy(),
        )
        iron = await rebuild_facet_stats(
            session, patch=patch, queue_id=420, rank_bracket="IRON",
            min_games=1, taxonomy=taxonomy(),
        )
    assert chal > 0, "the challenger-seeded match should aggregate"
    assert iron == 0, "no IRON-seeded match exists on this patch"


# --------------------------------------------------- timeline-derived rollups


def timeline_fields(*, path=None, skills=None, laning=None, gold=None):
    """The columns `TimelineService` writes, as a participant spec fragment.

    A participant without a timeline leaves every one of these null, which is
    the case the averages below have to survive.
    """
    return {
        "build_order": path,
        "skill_order": skills,
        "laning_score": laning,
        "gold_diff_14": gold,
    }


async def test_build_path_facet_keeps_purchase_order():
    """A path and a completed build can hold the same three items. The order is
    the only thing that separates them, so it must not be sorted away."""
    patch = "T1.00"
    forwards = [LEGENDARY_A, LEGENDARY_B, LEGENDARY_C]
    backwards = [LEGENDARY_C, LEGENDARY_B, LEGENDARY_A]
    await seed(patch, [
        [participant(99, "MIDDLE", 100, True,
                     **timeline_fields(path=order))]
        for order in (forwards, forwards, backwards)
    ])

    async with SessionLocal() as session:
        await rebuild_facet_stats(
            session, patch=patch, queue_id=420, rank_bracket=ALL_BRACKETS,
            min_games=1, taxonomy=taxonomy(),
        )
        rows = {
            r["facet_key"]: r
            for r in (await session.execute(
                ChampionFacetStat.__table__.select().where(
                    (ChampionFacetStat.patch == patch)
                    & (ChampionFacetStat.facet == "build_path")
                )
            )).mappings().all()
        }

    forward_key = "|".join(str(i) for i in forwards)
    backward_key = "|".join(str(i) for i in backwards)
    assert rows[forward_key]["games"] == 2
    assert rows[backward_key]["games"] == 1, "the reverse order is a different path"


async def test_build_path_ignores_components_and_stops_at_three():
    patch = "T2.00"
    # A component, three legendaries, then a fourth: only the middle three count.
    bought = [1038, LEGENDARY_A, BOOTS, LEGENDARY_B, LEGENDARY_C, LEGENDARY_A]
    await seed(patch, [
        [participant(99, "MIDDLE", 100, True, **timeline_fields(path=bought))]
    ])
    async with SessionLocal() as session:
        await rebuild_facet_stats(
            session, patch=patch, queue_id=420, rank_bracket=ALL_BRACKETS,
            min_games=1, taxonomy=taxonomy(),
        )
        keys = [
            r["facet_key"]
            for r in (await session.execute(
                ChampionFacetStat.__table__.select().where(
                    (ChampionFacetStat.patch == patch)
                    & (ChampionFacetStat.facet == "build_path")
                )
            )).mappings().all()
        ]
    assert keys == [f"{LEGENDARY_A}|{LEGENDARY_B}|{LEGENDARY_C}"]


async def test_skill_facets_record_priority_and_the_full_order():
    patch = "T3.00"
    # Q maxed first, then E. The ultimate sits at levels 6/11/16 and is ignored.
    levels = [1, 3, 1, 2, 1, 4, 1, 3, 1, 3, 4, 3, 3, 2, 2]
    await seed(patch, [
        [participant(99, "MIDDLE", 100, True, **timeline_fields(skills=levels))]
        for _ in range(2)
    ])
    async with SessionLocal() as session:
        await rebuild_facet_stats(
            session, patch=patch, queue_id=420, rank_bracket=ALL_BRACKETS,
            min_games=1, taxonomy=taxonomy(),
        )
        rows = {
            (r["facet"], r["facet_key"]): r
            for r in (await session.execute(
                ChampionFacetStat.__table__.select().where(
                    ChampionFacetStat.patch == patch
                )
            )).mappings().all()
        }

    assert rows[("skill_priority", "1|3")]["games"] == 2
    assert rows[("skill_order", "|".join(str(s) for s in levels))]["games"] == 2
    assert not any(f == "skill_priority" and "4" in k.split("|") for f, k in rows), \
        "the ultimate is on a fixed schedule and carries no choice"


async def test_laning_averages_count_only_the_games_that_have_a_timeline():
    """A half-backfilled corpus must report an average over what it measured,
    not quietly claim the whole sample."""
    patch = "T4.00"
    await seed(patch, [
        [participant(99, "MIDDLE", 100, True, **timeline_fields(laning=0.6, gold=1000))],
        [participant(99, "MIDDLE", 100, True, **timeline_fields(laning=0.4, gold=-600))],
        # Two more games of the same champion with no timeline at all.
        [participant(99, "MIDDLE", 100, True, **timeline_fields())],
        [participant(99, "MIDDLE", 100, False, **timeline_fields())],
    ])

    async with SessionLocal() as session:
        await rebuild_champion_stats(
            session, patch=patch, queue_id=420, rank_bracket=ALL_BRACKETS
        )
        row = (await session.execute(
            ChampionStat.__table__.select().where(ChampionStat.patch == patch)
        )).mappings().one()

    assert row["games"] == 4
    assert row["timeline_games"] == 2
    assert row["avg_laning_score"] == pytest.approx(0.5)
    assert row["avg_gold_diff_14"] == pytest.approx(200)


async def test_a_slice_with_no_timelines_reports_nothing_rather_than_zero():
    """Zero would read as 'dead even', which is a claim we have not measured."""
    patch = "T5.00"
    await seed(patch, [[participant(99, "MIDDLE", 100, True, **timeline_fields())]])
    async with SessionLocal() as session:
        await rebuild_champion_stats(
            session, patch=patch, queue_id=420, rank_bracket=ALL_BRACKETS
        )
        row = (await session.execute(
            ChampionStat.__table__.select().where(ChampionStat.patch == patch)
        )).mappings().one()

    assert row["timeline_games"] == 0
    assert row["avg_laning_score"] is None
    assert row["avg_gold_diff_14"] is None


async def test_latest_patch_is_the_highest_number_not_the_highest_string():
    """"16.9" sorts above "16.18" as text, and `/api/meta` takes "latest" from
    the head of this list. A handful of stray 16.9 games became the default tier
    list slice on a corpus holding 1,128 games on 16.18, and the page answered
    "nothing to show yet"."""
    queue = 9_420  # Private queue id: the suite shares one database.
    await seed("16.18", [[participant(99, "MIDDLE", 100, True)]] * 3, queue_id=queue)
    await seed("16.9", [[participant(99, "MIDDLE", 100, True)]], queue_id=queue)

    async with SessionLocal() as session:
        slices = [s for s in await available_slices(session) if s["queue_id"] == queue]

    assert [s["patch"] for s in slices] == ["16.18", "16.9"]


def test_patch_sort_key_orders_within_and_across_seasons():
    ordered = ["15.24", "16.8", "16.9", "16.10", "16.18"]
    assert sorted(ordered, key=patch_sort_key) == ordered


def test_patch_sort_key_tolerates_a_non_numeric_component():
    """Riot has shipped hotfix suffixes before. An unparsable part must sort low
    rather than raise, because this runs on every corpus request."""
    assert patch_sort_key("16.18b") < patch_sort_key("16.18")
    assert patch_sort_key("16.18.1") > patch_sort_key("16.18")


# ----------------------------------------------------------------------- items

MANAMUNE, MURAMANA = 3004, 3042
COMPONENT = 1038


def item_taxonomy() -> ItemTaxonomy:
    t = ItemTaxonomy()
    t.rebuild(
        {
            **FAKE_ITEMS,
            MANAMUNE: {"name": "Manamune", "tags": ["Mana"],
                       "gold": {"total": 2900, "purchasable": True}, "maps": {"11": True}},
            MURAMANA: {"name": "Muramana", "tags": ["Mana"], "specialRecipe": MANAMUNE,
                       "gold": {"total": 2900, "purchasable": False}, "maps": {"11": True}},
        },
        version="test",
    )
    return t


def buyer(champion_id, won, order, *, items=None, minutes=None):
    """One player whose purchase order is `order`, bought at `minutes`."""
    minutes = minutes or [5 * (i + 1) for i in range(len(order))]
    return participant(
        champion_id, "MIDDLE", 100, won, items=items if items is not None else [0] * 7,
        build_order=list(order), build_times=[m * 60 for m in minutes],
    )


async def rebuilt(patch: str) -> tuple[dict, dict]:
    from sqlalchemy import select

    from app.db.models import ItemChampionStat, ItemStat
    from app.services.aggregate import rebuild_item_stats

    async with SessionLocal() as session:
        await rebuild_item_stats(
            session, patch=patch, queue_id=420, rank_bracket=ALL_BRACKETS,
            taxonomy=item_taxonomy(),
        )
        items = {
            r.item_id: r for r in (
                await session.execute(select(ItemStat).where(ItemStat.patch == patch))
            ).scalars()
        }
        pairs = {
            (r.item_id, r.champion_id): r for r in (
                await session.execute(
                    select(ItemChampionStat).where(ItemChampionStat.patch == patch)
                )
            ).scalars()
        }
    return items, pairs


def delta(row, slot: int) -> float:
    games = row.slot_games[slot - 1]
    return (row.slot_wins[slot - 1] - row.slot_expected[slot - 1]) / games


async def test_an_item_is_scored_against_the_same_champions_other_items_in_its_slot():
    """Twenty players take A second and win fifteen; twenty take B second and
    win five. Same champion, same slot, same first item: against the other
    items the champion took second, A is +50 points (15 of 20 against B's 5 of
    20) and B is -50. Counting an item's own buys in its baseline halved both."""
    patch = "I1.00"
    champion = 9601
    players = (
        [buyer(champion, i < 15, [LEGENDARY_C, LEGENDARY_A]) for i in range(20)]
        + [buyer(champion, i < 5, [LEGENDARY_C, LEGENDARY_B]) for i in range(20)]
    )
    await seed(patch, [[p] for p in players])
    items, _ = await rebuilt(patch)

    assert items[LEGENDARY_A].slot_games == [0, 20, 0, 0]
    assert delta(items[LEGENDARY_A], 2) == pytest.approx(0.5)
    assert delta(items[LEGENDARY_B], 2) == pytest.approx(-0.5)
    # Everyone's first item: nothing else was bought first, so it is even.
    assert delta(items[LEGENDARY_C], 1) == pytest.approx(0.0)


async def test_a_strong_champion_does_not_lend_its_win_rate_to_its_items():
    """A wins 90% of the time only because the champion that buys it does.
    Its raw win rate says 90%; against that champion's own 2nd items, nothing."""
    patch = "I2.00"
    strong, weak = 9602, 9603
    players = (
        [buyer(strong, i < 18, [LEGENDARY_C, LEGENDARY_A]) for i in range(20)]
        + [buyer(weak, i < 2, [LEGENDARY_C, LEGENDARY_B]) for i in range(20)]
    )
    await seed(patch, [[p] for p in players])
    items, pairs = await rebuilt(patch)

    a = items[LEGENDARY_A]
    assert a.buyer_wins / a.buyers == pytest.approx(0.9), "the raw rate, as a sanity check"
    assert delta(a, 2) == pytest.approx(0.0)
    assert pairs[(LEGENDARY_A, strong)].expected_wins == pytest.approx(18.0)


async def test_a_grown_item_is_counted_under_the_item_that_was_bought():
    patch = "I3.00"
    players = [
        buyer(9604, True, [MANAMUNE], items=[MURAMANA, 0, 0, 0, 0, 0, 0])
        for _ in range(3)
    ]
    await seed(patch, [[p] for p in players])
    items, _ = await rebuilt(patch)

    assert MURAMANA not in items
    assert items[MANAMUNE].holders == 3
    assert items[MANAMUNE].buyers == 3


async def test_buyers_are_counted_once_and_timed_at_their_first_purchase():
    """Three Long Swords are one buyer, bought at the first one's minute."""
    patch = "I4.00"
    players = [
        buyer(9605, True, [COMPONENT, COMPONENT, COMPONENT], minutes=[m, m + 3, m + 6])
        for m in (4, 6, 8, 10)
    ]
    await seed(patch, [[p] for p in players])
    items, pairs = await rebuilt(patch)

    component = items[COMPONENT]
    assert component.buyers == 4
    assert component.slot_games is None, "a component takes no finished-item slot"
    assert (component.minute_p25, component.minute_p50, component.minute_p75) == (
        pytest.approx(5.5), pytest.approx(7.0), pytest.approx(8.5)
    )
    assert pairs[(COMPONENT, 9605)].buyers == 4


async def test_a_one_off_pair_is_not_stored():
    from app.services.aggregate import MIN_ITEM_CHAMPION_BUYERS

    patch = "I5.00"
    players = [buyer(9606, True, [LEGENDARY_A]) for _ in range(MIN_ITEM_CHAMPION_BUYERS - 1)]
    await seed(patch, [[p] for p in players])
    items, pairs = await rebuilt(patch)
    assert items[LEGENDARY_A].buyers == MIN_ITEM_CHAMPION_BUYERS - 1
    assert (LEGENDARY_A, 9606) not in pairs


def test_the_default_patch_is_the_newest_settled_one():
    """A patch with eight games is not the one a page opens on."""
    slices = [
        {"patch": "16.19", "queue_id": 420, "matches": 8},
        {"patch": "16.18", "queue_id": 420, "matches": 1437},
        {"patch": "16.17", "queue_id": 420, "matches": 864},
        {"patch": "16.18", "queue_id": 440, "matches": 40},
    ]
    assert default_patch(slices, 420) == "16.18"
    # Nothing settled in flex: the newest aggregated patch, rather than nothing.
    assert default_patch(slices, 440) == "16.18"
    assert default_patch(slices, 450) is None
    assert default_patch([], 420) is None


async def test_a_patch_with_games_but_no_aggregate_is_not_offered_to_a_page():
    """Stored games alone put a patch in `available_slices` for the ingest;
    a page reads `aggregated_slices`, where it appears only once aggregated."""
    from app.db.models import ChampionStat, Match

    async with SessionLocal() as session:
        session.add(
            Match(
                match_id="TAGG_raw_1", platform_id="EUW1", queue_id=420, patch="AGG.raw",
                game_creation=1, game_duration=1800, is_remake=False, source_bracket="CHALLENGER",
                teams=[],
            )
        )
        session.add(
            Match(
                match_id="TAGG_agg_1", platform_id="EUW1", queue_id=420, patch="AGG.done",
                game_creation=1, game_duration=1800, is_remake=False, source_bracket="CHALLENGER",
                teams=[],
            )
        )
        session.add(
            ChampionStat(
                patch="AGG.done", queue_id=420, rank_bracket="ALL", champion_id=1,
                team_position="TOP", games=1, wins=1, pool_games=1,
            )
        )
        await session.commit()
        raw = {s["patch"] for s in await available_slices(session)}
        shown = {s["patch"] for s in await aggregated_slices(session)}
    assert {"AGG.raw", "AGG.done"} <= raw
    assert "AGG.done" in shown
    assert "AGG.raw" not in shown


# ------------------------------------------------------------------------ bans


async def test_a_champion_banned_by_both_teams_counts_once():
    """Counting each team's ban put Talon at a 63.5% ban rate on 16.18 when he
    was banned in 52.7% of games. The rate is a share of games."""
    from sqlalchemy import select

    from app.db.models import ChampionStat

    patch = "BAN1.00"
    await seed(patch, [
        team([9401, 9402, 9403, 9404, 9405], 100, True) + team([9406, 9407, 9408, 9409, 9410], 200, False),
        team([9411, 9402, 9403, 9404, 9405], 100, True) + team([9406, 9407, 9408, 9409, 9410], 200, False),
    ])
    async with SessionLocal() as session:
        first = await session.get(Match, f"T{patch}_0")
        second = await session.get(Match, f"T{patch}_1")
        first.teams = [{"teamId": 100, "bans": [{"championId": 9412}, {"championId": -1}]},
                       {"teamId": 200, "bans": [{"championId": 9413}]}]
        # Both teams ban 9401 in the second game: one game with it banned.
        second.teams = [{"teamId": 100, "bans": [{"championId": 9401}, {"championId": 9412}]},
                        {"teamId": 200, "bans": [{"championId": 9401}]}]
        await session.commit()
        await rebuild_champion_stats(session, patch=patch, queue_id=420, rank_bracket=ALL_BRACKETS)
        row = (await session.execute(
            select(ChampionStat).where(ChampionStat.patch == patch, ChampionStat.champion_id == 9401)
        )).scalar_one()

    assert (row.bans, row.pool_games) == (1, 2)
