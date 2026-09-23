"""The home page's three reads: player suggestions, the week's best games, and
how fresh the corpus is. None of them calls Riot, so nothing here is mocked.

The suite shares one database, so every player here is named with a ``Qzx``
prefix no other test uses, and the matches sit in queues 7301 and 7302.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

from app.api.routes import meta
from app.config import get_settings
from app.db.base import SessionLocal
from app.db.models import Match, MatchParticipant, Player, RankedEntry
from app.services import aggregate
from app.services.highlights import best_games
from app.services.suggest import clear_suggest_cache

ROLES = ("TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY")
QUEUE = 7301
EMPTY_QUEUE = 7302
DAY_MS = 86_400_000


async def add_player(
    name: str,
    tag: str,
    platform: str = "euw1",
    *,
    puuid: str | None = None,
    tier: str | None = None,
    division: str | None = "I",
    confirmed: bool = True,
    icon: int | None = None,
) -> None:
    async with SessionLocal() as session:
        puuid = puuid or f"qzx-{name}-{tag}-{platform}".ljust(78, "0")
        session.add(
            Player(
                puuid=puuid,
                game_name=name,
                tag_line=tag,
                platform=platform,
                profile_icon_id=icon,
                account_fetched_at=datetime.now(UTC) if confirmed else None,
            )
        )
        if tier:
            session.add(
                RankedEntry(
                    puuid=puuid,
                    queue_type="RANKED_SOLO_5x5",
                    tier=tier,
                    division=division,
                    league_points=50,
                )
            )
        await session.commit()


async def suggest(client, q: str, **params) -> list[dict]:
    clear_suggest_cache()
    response = await client.get("/api/players/suggest", params={"q": q, **params})
    assert response.status_code == 200, response.text
    return response.json()["players"]


# ------------------------------------------------------------- suggestions


async def test_suggestions_fold_accents_case_and_spaces(client):
    await add_player("Qzx Cäps", "EUW")

    for typed in ("qzxcaps", "QZX CA", "Qzx Cä"):
        found = await suggest(client, typed)
        assert [p["riot_id"] for p in found] == ["Qzx Cäps#EUW"], typed


async def test_one_hangul_syllable_is_enough_to_suggest(client):
    # A syllable folds to two or three jamo, so it clears the two-character
    # floor that a single Latin letter does not.
    await add_player("큐즈엑스", "KR1", "kr")

    assert [p["riot_id"] for p in await suggest(client, "큐")] == ["큐즈엑스#KR1"]


async def test_exact_name_then_selected_region_then_rank(client):
    await add_player("Qzxrank", "KR1", "kr")
    await add_player("Qzxrankz", "EUW", tier="SILVER")
    await add_player("Qzxranker", "EUW", tier="CHALLENGER", division=None)
    await add_player("Qzxrankest", "KR1", "kr", tier="GOLD")

    found = await suggest(client, "qzxrank", platform="euw1")

    assert [p["riot_id"] for p in found] == [
        "Qzxrank#KR1",
        "Qzxranker#EUW",
        "Qzxrankz#EUW",
        "Qzxrankest#KR1",
    ]
    challenger = found[1]
    assert (challenger["tier"], challenger["platform_label"]) == ("CHALLENGER", "EUW")
    # No solo entry held is not the same claim as unranked.
    assert found[0]["tier"] is None


async def test_a_typed_tag_narrows_by_prefix(client):
    await add_player("Qzxtagged", "EUW")
    await add_player("Qzxtagged", "NA1", "na1")

    assert [p["riot_id"] for p in await suggest(client, "qzxtagged#e")] == ["Qzxtagged#EUW"]
    assert len(await suggest(client, "qzxtagged#")) == 2


async def test_short_queries_suggest_nothing_and_the_limit_holds(client):
    for i in range(6):
        await add_player(f"Qzxmany{i}", "EUW")

    assert await suggest(client, "q") == []
    assert await suggest(client, "   ") == []
    assert len(await suggest(client, "qzxmany", limit=3)) == 3


async def test_a_stale_row_for_the_same_riot_id_is_not_suggested_twice(client):
    # Somebody gave the name up and somebody else took it. The row read from an
    # old match must not sit beside the account account-v1 confirmed.
    await add_player("Qzxrenamed", "EUW", puuid="qzx-stale".ljust(78, "0"), confirmed=False, icon=1)
    await add_player("Qzxrenamed", "EUW", puuid="qzx-owner".ljust(78, "0"), icon=2)

    found = await suggest(client, "qzxrenamed")

    assert len(found) == 1
    assert found[0]["profile_icon_url"].endswith("/2.png")


async def test_a_merged_shard_suggests_the_shard_it_merged_into(client):
    # th2 no longer resolves at Riot. A link to it would fail on click.
    await add_player("Qzxmerged", "TH2", "th2")

    found = await suggest(client, "qzxmerged")

    assert [(p["platform"], p["platform_label"]) for p in found] == [("sg2", "SG")]


# -------------------------------------------------------------- best games


async def seed_lobby(
    match_id: str,
    scores: dict[int, float | None],
    *,
    queue_id: int = QUEUE,
    age_days: float = 1,
    remake: bool = False,
    puuids: dict[int, str] | None = None,
    badges: dict[int, list[str]] | None = None,
) -> None:
    """Ten players, slots 0-4 blue and 5-9 red, in role order on each side."""
    now = int(time.time() * 1000)
    async with SessionLocal() as session:
        session.add(
            Match(
                match_id=match_id,
                platform_id="EUW1",
                queue_id=queue_id,
                patch="S1.00",
                game_creation=now - int(age_days * DAY_MS),
                game_duration=1800,
                is_remake=remake,
                teams=[],
            )
        )
        for slot in range(10):
            score = scores.get(slot)
            session.add(
                MatchParticipant(
                    match_id=match_id,
                    participant_index=slot + 1,
                    puuid=(puuids or {}).get(slot, f"{match_id}_p{slot}"),
                    riot_id_game_name=f"Qzx{slot}",
                    riot_id_tagline="EUW",
                    champion_id=100 + slot,
                    team_id=100 if slot < 5 else 200,
                    team_position=ROLES[slot % 5],
                    win=slot < 5,
                    kills=5,
                    deaths=2,
                    assists=7,
                    damage_to_champions=20_000,
                    damage_taken=20_000,
                    performance_score=score,
                    performance_rank=1 if score is not None else None,
                    performance_detail=(
                        {"badges": (badges or {}).get(slot, [])} if score is not None else None
                    ),
                )
            )
        await session.commit()


async def test_best_games_pick_one_player_per_role_inside_the_window():
    star = "qzx-star".ljust(78, "0")
    # The star tops TOP in one game and MIDDLE in another. They are shown once,
    # in the role they scored higher in, and MIDDLE falls to its next best.
    await seed_lobby(
        "QZX_1",
        {0: 9.9, 1: 7.0, 2: 6.0, 3: 8.0, 4: 8.5, 5: 5.0, 6: 7.5, 7: 8.8, 8: 4.0, 9: None},
        puuids={0: star},
    )
    await seed_lobby("QZX_2", {2: 9.5, 7: 3.0}, puuids={2: star})
    # Higher, but a remake, then higher again but eight days old.
    await seed_lobby("QZX_REMAKE", dict.fromkeys(range(10), 9.99), remake=True)
    await seed_lobby("QZX_OLD", dict.fromkeys(range(10), 9.98), age_days=8)

    async with SessionLocal() as session:
        found = await best_games(session, queue_id=QUEUE)

    picked = [(p.team_position, p.match_id, p.performance_score) for p in found.picks]
    assert picked == [
        ("TOP", "QZX_1", 9.9),
        ("JUNGLE", "QZX_1", 7.5),
        ("MIDDLE", "QZX_1", 8.8),
        ("BOTTOM", "QZX_1", 8.0),
        ("UTILITY", "QZX_1", 8.5),
    ]
    assert len({p.puuid for p in found.picks}) == 5
    # Nine scored players in QZX_1 and two in QZX_2; the remake and the old
    # game are outside what was chosen from.
    assert (found.scored_players, found.scored_games) == (11, 2)


async def test_best_games_are_empty_for_a_week_with_no_scored_games():
    await seed_lobby("QZX_UNSCORED", {}, queue_id=EMPTY_QUEUE)

    async with SessionLocal() as session:
        found = await best_games(session, queue_id=EMPTY_QUEUE)

    assert (found.picks, found.scored_players, found.scored_games) == ([], 0, 0)


async def test_best_games_endpoint_carries_the_player_the_game_and_its_badges(client):
    await seed_lobby("QZX_API", {3: 9.4}, queue_id=7303, badges={3: ["mvp"]})

    response = await client.get("/api/highlights/best-games", params={"queue_id": 7303})

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["days"], body["scored_players"], body["scored_games"]) == (7, 1, 1)
    [game] = body["games"]
    assert (game["match_id"], game["platform"], game["position"]) == ("QZX_API", "euw1", "BOTTOM")
    assert (game["game_name"], game["tag_line"], game["score"]) == ("Qzx3", "EUW", 9.4)
    assert (game["kills"], game["deaths"], game["assists"], game["win"]) == (5, 2, 7, True)
    assert [b["id"] for b in game["badges"]] == ["mvp"]
    assert "9.4" in game["badges"][0]["detail"]


# ------------------------------------------------------------------ corpus


async def test_corpus_says_how_new_its_newest_game_is(client):
    await seed_lobby("QZX_FRESH", {}, queue_id=7304, age_days=0)
    before = int(time.time() * 1000) - 60_000

    body = (await client.get("/api/meta/corpus")).json()

    assert body["latest_game_at"] >= before
    assert body["latest_ingest_at"] >= before


async def test_the_corpus_is_kept_for_its_ttl_and_then_read_again(client, monkeypatch):
    """Every slice control asks for it, and it took 0.57 s on production
    (2026-09-24): kept for `ttl_corpus`, a new game shows once that passes."""
    settings = get_settings()
    monkeypatch.setattr(settings, "ttl_corpus", 300)
    monkeypatch.setattr(meta, "_corpus_held", None)
    monkeypatch.setattr(aggregate, "_slices_held", None)

    first = (await client.get("/api/meta/corpus")).json()
    await seed_lobby("QZX_KEPT", {}, queue_id=7306, age_days=-10)
    assert (await client.get("/api/meta/corpus")).json() == first
    assert aggregate._slices_held is not None

    monkeypatch.setattr(settings, "ttl_corpus", 0)
    fresh = (await client.get("/api/meta/corpus")).json()
    assert fresh["latest_game_at"] > first["latest_game_at"]
