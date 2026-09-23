"""The draft advisor: candidate selection, bracket isolation, matchup shrinkage.

These work directly against seeded rollup rows rather than through a crawl, so
they exercise the advisor's own logic without depending on what a corpus happens
to contain.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.db.base import SessionLocal
from app.db.models import ChampionStat, MatchupStat, SynergyStat
from app.services.aggregate import ALL_BRACKETS
from app.services.draft import (
    CONTEXT_LIFT_CAP,
    MATCHUP_SHRINKAGE,
    MIN_TIMELINE_GAMES,
    DraftAdvisor,
    DraftContext,
    credible_lift,
)

PATCH = "D1.00"
POSITION = "BOTTOM"


async def seed_stat(champion_id, games, wins, *, patch=PATCH, bracket=ALL_BRACKETS):
    async with SessionLocal() as session:
        session.add(
            ChampionStat(
                patch=patch, queue_id=420, rank_bracket=bracket,
                team_position=POSITION, champion_id=champion_id,
                games=games, wins=wins, bans=0, pool_games=max(games, 100),
                avg_kills=6.0, avg_deaths=5.0, avg_assists=9.0,
                avg_cs_per_min=8.0, avg_gold=12000, avg_damage=20000, avg_vision=20,
                timeline_games=0,
            )
        )
        await session.commit()


async def seed_matchup(champion_id, enemy_id, games, wins, *,
                       patch=PATCH, bracket=ALL_BRACKETS, scope="LANE",
                       timeline_games=0, gold_diff=None):
    async with SessionLocal() as session:
        session.add(
            MatchupStat(
                patch=patch, queue_id=420, rank_bracket=bracket, scope=scope,
                team_position=POSITION, champion_id=champion_id,
                enemy_champion_id=enemy_id, games=games, wins=wins,
                timeline_games=timeline_games, avg_gold_diff_14=gold_diff,
                avg_laning_score=0.53 if timeline_games else None,
            )
        )
        await session.commit()


async def seed_synergy(champion_id, ally_id, games, wins, *, patch=PATCH,
                       ally_position="UTILITY"):
    async with SessionLocal() as session:
        session.add(
            SynergyStat(
                patch=patch, queue_id=420, rank_bracket=ALL_BRACKETS,
                team_position=POSITION, champion_id=champion_id,
                ally_position=ally_position, ally_champion_id=ally_id,
                games=games, wins=wins,
            )
        )
        await session.commit()


async def bans(**kw):
    ctx = DraftContext(position=POSITION, patch=kw.pop("patch", PATCH), min_games=1, **kw)
    async with SessionLocal() as session:
        return await DraftAdvisor(session).ban_candidates(ctx)


async def suggest(**kw):
    ctx = DraftContext(position=POSITION, patch=kw.pop("patch", PATCH), min_games=1, **kw)
    async with SessionLocal() as session:
        return await DraftAdvisor(session).suggest(ctx)


async def test_a_champion_in_two_brackets_is_suggested_once():
    """ALL overlaps every per-tier slice, so an unfiltered query returns the
    same champion once per bracket it appears in."""
    patch = "D2.00"
    await seed_stat(501, 100, 55, patch=patch, bracket=ALL_BRACKETS)
    await seed_stat(501, 98, 54, patch=patch, bracket="CHALLENGER")

    picks = await suggest(patch=patch)
    assert [s.champion_id for s in picks] == [501]


async def test_the_bracket_asked_for_is_the_bracket_scored():
    patch = "D3.00"
    await seed_stat(502, 100, 90, patch=patch, bracket=ALL_BRACKETS)
    await seed_stat(502, 100, 10, patch=patch, bracket="IRON")

    high = await suggest(patch=patch, rank_bracket=ALL_BRACKETS)
    low = await suggest(patch=patch, rank_bracket="IRON")
    assert high[0].base_win_rate > 0.8
    assert low[0].base_win_rate < 0.2


async def test_allies_enemies_and_bans_are_off_the_table():
    patch = "D4.00"
    for champion in (510, 511, 512, 513):
        await seed_stat(champion, 50, 30, patch=patch)

    picks = await suggest(patch=patch, allies=[510], enemies=[511], bans=[512])
    assert [s.champion_id for s in picks] == [513]


async def test_a_thin_matchup_barely_moves_the_baseline():
    """Two games against someone is not evidence. Without shrinkage a 2-0 would
    top the list over a champion with a hundred games behind it."""
    patch = "D5.00"
    await seed_stat(520, 200, 100, patch=patch)       # dead even baseline
    await seed_matchup(520, 999, games=2, wins=2, patch=patch)

    picks = await suggest(patch=patch, enemy_laner=999)
    pick = picks[0]
    assert pick.matchup_games == 2
    assert pick.matchup_win_rate == 1.0

    weight = 2 / (2 + MATCHUP_SHRINKAGE)
    expected = pick.base_win_rate + weight * (1.0 - pick.base_win_rate)
    assert pick.adjusted_win_rate == pytest.approx(expected)
    # The point of the shrinkage: nowhere near the observed 100%.
    assert pick.adjusted_win_rate < 0.65


async def test_team_scope_matchups_do_not_leak_into_the_lane_adjustment():
    """A TEAM row says 'this champion was somewhere on the enemy side', which is
    a different question from 'you laned against them'."""
    patch = "D6.00"
    await seed_stat(530, 200, 100, patch=patch)
    await seed_matchup(530, 998, games=60, wins=60, patch=patch, scope="TEAM")

    pick = (await suggest(patch=patch, enemy_laner=998))[0]
    assert pick.matchup_games == 0
    assert pick.adjusted_win_rate == pytest.approx(pick.base_win_rate)


async def test_min_games_keeps_a_one_game_champion_out_of_the_draft():
    patch = "D7.00"
    await seed_stat(540, 1, 1, patch=patch)
    await seed_stat(541, 40, 22, patch=patch)

    ctx = DraftContext(position=POSITION, patch=patch, min_games=20)
    async with SessionLocal() as session:
        picks = await DraftAdvisor(session).suggest(ctx)
    assert [s.champion_id for s in picks] == [541]


async def test_an_unadjusted_pick_does_not_restate_its_own_score():
    """The row prints the score; a reason line printing the identical figure
    underneath reads as a template filling itself in."""
    patch = "D9.00"
    await seed_stat(560, 100, 48, patch=patch)

    pick = (await suggest(patch=patch))[0]
    assert pick.adjusted_win_rate == pick.base_win_rate
    assert pick.reasons[0] == "baseline over 100 games"


async def test_an_adjusted_pick_still_shows_what_the_baseline_was():
    """Here the two numbers genuinely differ, so the baseline has to be named.

    The figure is read back off the suggestion rather than written out: it is a
    Wilson lower bound, not wins over games, so a literal here would be
    asserting the confidence maths a second time and in the wrong place.
    """
    patch = "D10.00"
    await seed_stat(561, 200, 100, patch=patch)
    await seed_matchup(561, 998, games=40, wins=30, patch=patch)

    pick = (await suggest(patch=patch, enemy_laner=998))[0]
    assert pick.adjusted_win_rate != pick.base_win_rate
    assert pick.reasons[0] == (
        f"{pick.base_win_rate * 100:.1f}% baseline over 200 games"
    )


# ------------------------------------------------- what the evidence supports


def test_a_record_gives_up_what_its_own_sample_cannot_support():
    """The measured case: a 10-2 lane record claimed +11 points and now argues
    about +5 of them, while a 55% over twenty games argues for nothing."""
    claimed, supported = credible_lift(10 / 12, 0.4313, 12, MATCHUP_SHRINKAGE)
    assert 0 < supported < claimed / 2

    claimed, supported = credible_lift(0.55, 0.505, 20, MATCHUP_SHRINKAGE)
    assert claimed > 0
    assert supported == 0.0


async def test_a_thin_lane_record_no_longer_outranks_a_bigger_baseline():
    """Live on 2026-09-21 this list put Yone first on a 10-2 over twelve games,
    ahead of champions with hundreds behind them."""
    patch = "D11.00"
    await seed_stat(570, 200, 100, patch=patch)   # even, with a hot lane record
    await seed_matchup(570, 997, games=12, wins=10, patch=patch)
    await seed_stat(571, 300, 165, patch=patch)   # 55% over three hundred games

    picks = await suggest(patch=patch, enemy_laner=997)

    assert [p.champion_id for p in picks] == [571, 570]
    thin = next(p for p in picks if p.champion_id == 570)
    lane = thin.evidence[0]
    # It still argues for the pick, but for a fraction of what it claims.
    assert 0 < thin.context_lift < (lane.win_rate - thin.base_win_rate) / 3
    # The unrestrained reading is still there to show.
    assert thin.adjusted_win_rate > thin.score


async def test_the_lane_opponent_is_not_counted_twice():
    patch = "D12.00"
    await seed_stat(572, 200, 100, patch=patch)
    await seed_matchup(572, 996, games=20, wins=15, patch=patch)
    await seed_matchup(572, 996, games=60, wins=60, patch=patch, scope="TEAM")

    pick = (await suggest(patch=patch, enemy_laner=996, enemies=[996]))[0]

    assert [e.kind for e in pick.evidence] == ["lane"]


async def test_the_enemy_team_and_the_allies_each_move_a_pick():
    patch = "D13.00"
    await seed_stat(573, 200, 100, patch=patch)
    await seed_matchup(573, 995, games=50, wins=40, patch=patch, scope="TEAM")
    await seed_synergy(573, 994, games=50, wins=40, patch=patch)

    pick = (await suggest(patch=patch, enemies=[995], allies=[994]))[0]

    kinds = {e.kind: e for e in pick.evidence}
    assert set(kinds) == {"enemy", "ally"}
    assert kinds["enemy"].games == 50 and kinds["enemy"].credible_lift > 0
    assert kinds["ally"].games == 50 and kinds["ally"].credible_lift > 0
    assert pick.score > pick.base_win_rate


async def test_a_champion_we_hold_no_rows_for_moves_nothing():
    patch = "D14.00"
    await seed_stat(574, 200, 100, patch=patch)

    pick = (await suggest(patch=patch, enemies=[888], allies=[889]))[0]

    assert pick.evidence == []
    assert pick.score == pytest.approx(pick.base_win_rate)


async def test_the_board_cannot_stack_past_the_cap():
    """Four lopsided records pulling the same way is still only a draft."""
    patch = "D15.00"
    await seed_stat(575, 200, 100, patch=patch)
    enemies = [990, 991, 992, 993]
    for enemy in enemies:
        await seed_matchup(575, enemy, games=100, wins=90, patch=patch, scope="TEAM")

    pick = (await suggest(patch=patch, enemies=enemies))[0]

    assert sum(e.credible_lift for e in pick.evidence) > CONTEXT_LIFT_CAP
    assert pick.context_lift == pytest.approx(CONTEXT_LIFT_CAP)


async def test_a_lane_shows_its_gold_lead_only_once_enough_games_have_timelines():
    patch = "D16.00"
    await seed_stat(576, 200, 100, patch=patch)
    await seed_matchup(576, 987, games=30, wins=18, patch=patch,
                       timeline_games=MIN_TIMELINE_GAMES - 1, gold_diff=400.0)
    await seed_stat(577, 200, 100, patch=patch)
    await seed_matchup(577, 987, games=30, wins=18, patch=patch,
                       timeline_games=MIN_TIMELINE_GAMES, gold_diff=400.0)

    picks = {p.champion_id: p for p in await suggest(patch=patch, enemy_laner=987)}

    assert picks[576].evidence[0].gold_diff_14 is None
    assert picks[577].evidence[0].gold_diff_14 == 400.0
    assert any("gold by 14" in r for r in picks[577].reasons)
    assert not any("gold by 14" in r for r in picks[576].reasons)


async def test_bans_are_ranked_by_what_beats_the_allies_already_picked():
    patch = "D17.00"
    await seed_stat(580, 100, 60, patch=patch)
    await seed_stat(581, 100, 60, patch=patch)
    # 581 has a record against the ally we locked in; 580 has none.
    await seed_matchup(581, 979, games=60, wins=48, patch=patch, scope="TEAM")

    with_ally = await bans(patch=patch, allies=[979])
    assert [c.champion_id for c in with_ally] == [581, 580]
    assert with_ally[0].score > with_ally[0].base_win_rate
    assert any("against one of your picks" in r for r in with_ally[0].reasons)

    # With nothing locked in there is no draft to read, so this is just the
    # patch's strongest, and neither candidate is lifted.
    blind = await bans(patch=patch)
    assert all(c.score == pytest.approx(c.base_win_rate) for c in blind)


async def test_the_champion_you_are_facing_is_not_offered_as_a_pick():
    """Seen locally on 2026-09-21: asking for mid into Ahri suggested Ahri."""
    patch = "D18.00"
    await seed_stat(585, 200, 110, patch=patch)   # the enemy laner
    await seed_stat(586, 200, 100, patch=patch)

    picks = await suggest(patch=patch, enemy_laner=585)

    assert [p.champion_id for p in picks] == [586]
    assert [c.champion_id for c in await bans(patch=patch, enemy_laner=585)] == [586]


# ------------------------------------------------------------ personalisation


@respx.mock
async def test_personalisation_reads_mastery_on_the_shard_the_account_is_on(client):
    """champion-mastery-v4 answers 200 with an empty list on the wrong shard.
    The draft asked the shard in the request, so an OCE Riot ID whose account
    lives on SG2 was reported as personalised with no mastery behind it."""
    patch = "D9.00"
    await seed_stat(701, 100, 55, patch=patch)
    await seed_stat(702, 100, 55, patch=patch)
    puuid = "draft-oce-sg2".ljust(78, "0")
    respx.get(url__regex=r".*/riot/account/v1/accounts/by-riot-id/.*").mock(
        return_value=httpx.Response(
            200, json={"puuid": puuid, "gameName": "Drafter", "tagLine": "OCE"}
        )
    )
    respx.get(url__regex=r".*oc1\.api\.riotgames\.com/lol/summoner/v4/.*").mock(
        return_value=httpx.Response(404, json={"status": {"status_code": 404}})
    )
    respx.get(url__regex=r".*/lol/match/v5/matches/by-puuid/.*/ids.*").mock(
        return_value=httpx.Response(200, json=["SG2_7400000001"])
    )
    wrong_shard = respx.get(
        url__regex=r".*oc1\.api\.riotgames\.com/lol/champion-mastery/v4/.*"
    ).mock(return_value=httpx.Response(200, json=[]))
    right_shard = respx.get(
        url__regex=r".*sg2\.api\.riotgames\.com/lol/champion-mastery/v4/.*"
    ).mock(
        return_value=httpx.Response(
            200,
            json=[{"championId": 702, "championLevel": 30, "championPoints": 400_000}],
        )
    )

    response = await client.post(
        "/api/draft/suggest",
        json={
            "position": POSITION, "patch": patch, "min_games": 1,
            "platform": "oc1", "game_name": "Drafter", "tag_line": "OCE",
        },
    )

    assert response.status_code == 200, response.text[:300]
    assert right_shard.called
    assert not wrong_shard.called
    body = response.json()
    assert body["personalised"] is True
    assert body["personalisation"] == {
        "status": "used", "riot_id": "Drafter#OCE", "platform": "sg2", "champions": 1,
    }
    by_id = {s["champion"]["id"]: s for s in body["suggestions"]}
    assert by_id[702]["mastery_points"] == 400_000, "the mastery behind the word"


# ------------------------------------------------ what personalisation costs


@pytest.fixture
def _fresh_misses():
    from app.services.players import clear_miss_cache

    clear_miss_cache()
    yield
    clear_miss_cache()


def _draft_body(patch, **kw):
    return {"position": POSITION, "patch": patch, "min_games": 1, **kw}


ACCOUNT_ROUTE = r".*/riot/account/v1/accounts/by-riot-id/.*"


@respx.mock
async def test_a_riot_id_riot_does_not_know_is_asked_about_once(client, _fresh_misses):
    """A mistyped saved Riot ID cost an account-v1 call on every board change
    (measured 2026-09-24: three calls for three changes). The spellings Riot
    treats as one account are one question."""
    patch = "D20.00"
    await seed_stat(720, 100, 55, patch=patch)
    lookup = respx.get(url__regex=ACCOUNT_ROUTE).mock(
        return_value=httpx.Response(404, json={"status": {"status_code": 404}})
    )

    for name in ("Nobody Here", "nobodyhere", "Nöbody Here"):
        response = await client.post(
            "/api/draft/suggest",
            json=_draft_body(patch, platform="euw1", game_name=name, tag_line="ZZ9"),
        )
        assert response.status_code == 200, response.text[:300]
        body = response.json()
        assert body["personalisation"]["status"] == "not_found"
        assert body["personalised"] is False

    assert lookup.call_count == 1


@respx.mock
async def test_a_refusal_from_riot_is_not_remembered_as_a_missing_account(client, _fresh_misses):
    """Only a 404 says the account does not exist. A refusal says nothing about
    it, so the next board change asks again."""
    patch = "D21.00"
    await seed_stat(721, 100, 55, patch=patch)
    lookup = respx.get(url__regex=ACCOUNT_ROUTE).mock(
        return_value=httpx.Response(403, json={"status": {"status_code": 403}})
    )

    for _ in range(2):
        response = await client.post(
            "/api/draft/suggest",
            json=_draft_body(patch, platform="euw1", game_name="Refused", tag_line="EUW"),
        )
        assert response.json()["personalisation"]["status"] == "busy"

    assert lookup.call_count == 2


@respx.mock
async def test_a_riot_id_that_cannot_exist_is_never_asked_about(client, _fresh_misses):
    """Riot's tags are three to five letters or digits. "Caps#E" is someone
    still typing, and it used to be an account-v1 call."""
    patch = "D22.00"
    await seed_stat(722, 100, 55, patch=patch)
    lookup = respx.get(url__regex=ACCOUNT_ROUTE).mock(
        return_value=httpx.Response(404, json={"status": {"status_code": 404}})
    )

    response = await client.post(
        "/api/draft/suggest",
        json=_draft_body(patch, platform="euw1", game_name="Caps", tag_line="E"),
    )

    assert response.json()["personalisation"] == {
        "status": "not_found", "riot_id": "Caps#E", "platform": "euw1", "champions": 0,
    }
    assert not lookup.called


@respx.mock
async def test_mastery_switched_off_costs_no_lookup(client, _fresh_misses):
    patch = "D23.00"
    await seed_stat(723, 100, 55, patch=patch)
    lookup = respx.get(url__regex=ACCOUNT_ROUTE).mock(
        return_value=httpx.Response(404, json={"status": {"status_code": 404}})
    )

    response = await client.post(
        "/api/draft/suggest",
        json=_draft_body(
            patch, platform="euw1", game_name="Caps", tag_line="EUW", comfort_weight=0
        ),
    )

    assert response.json()["personalisation"]["status"] == "off"
    assert not lookup.called


async def _store_player(puuid, name, tag, *, mastery=None):
    from app.db.models import ChampionMastery, Player
    from app.services.players import normalize_riot_name

    async with SessionLocal() as session:
        session.add(
            Player(
                puuid=puuid, game_name=name, tag_line=tag, platform="euw1",
                search_name=normalize_riot_name(name),
            )
        )
        for champion_id, points in (mastery or {}).items():
            session.add(
                ChampionMastery(
                    puuid=puuid, champion_id=champion_id, champion_level=20,
                    champion_points=points,
                )
            )
        await session.commit()


def _slow_account(puuid, name, tag):
    import time

    def answer(request):
        # Blocks the loop past the budget, the way a slow Riot answer outlasts
        # it; the timeout fires at the next await.
        time.sleep(0.3)
        return httpx.Response(200, json={"puuid": puuid, "gameName": name, "tagLine": tag})

    return answer


@respx.mock
async def test_a_slow_riot_answer_uses_the_mastery_already_stored(
    client, monkeypatch, _fresh_misses
):
    """The limiter lets a request wait 40 seconds for a slot and the nightly
    crawl shares the key. Past the budget the board answers with what it holds."""
    from app.api.routes import draft as draft_route

    patch = "D24.00"
    await seed_stat(724, 100, 55, patch=patch)
    await seed_stat(725, 100, 55, patch=patch)
    puuid = "draft-stale-mastery".ljust(78, "0")
    await _store_player(puuid, "Stale", "EUW", mastery={725: 250_000})
    monkeypatch.setattr(draft_route, "PERSONALISE_BUDGET_SECONDS", 0.05)
    respx.get(url__regex=ACCOUNT_ROUTE).mock(side_effect=_slow_account(puuid, "Stale", "EUW"))

    response = await client.post(
        "/api/draft/suggest",
        json=_draft_body(patch, platform="euw1", game_name="Stale", tag_line="EUW"),
    )

    assert response.status_code == 200, response.text[:300]
    body = response.json()
    assert body["personalisation"] == {
        "status": "stale", "riot_id": "Stale#EUW", "platform": "euw1", "champions": 1,
    }
    by_id = {s["champion"]["id"]: s for s in body["suggestions"]}
    assert by_id[725]["mastery_points"] == 250_000


@respx.mock
async def test_a_slow_riot_answer_with_nothing_stored_is_busy(client, monkeypatch, _fresh_misses):
    from app.api.routes import draft as draft_route

    patch = "D25.00"
    await seed_stat(726, 100, 55, patch=patch)
    monkeypatch.setattr(draft_route, "PERSONALISE_BUDGET_SECONDS", 0.05)
    respx.get(url__regex=ACCOUNT_ROUTE).mock(
        side_effect=_slow_account("draft-busy".ljust(78, "0"), "Busy", "EUW")
    )

    response = await client.post(
        "/api/draft/suggest",
        json=_draft_body(patch, platform="euw1", game_name="Busy", tag_line="EUW"),
    )

    assert response.status_code == 200, response.text[:300]
    assert response.json()["personalisation"]["status"] == "busy"
    assert response.json()["personalised"] is False


# ------------------------------------------------------- what a board may be


@pytest.mark.parametrize(
    ("change", "where"),
    [
        ({"position": "SIDELANE"}, ["body", "position"]),
        ({"allies": [1, 2, 3, 4, 5]}, ["body", "allies"]),
        ({"enemies": [1, 2, 3, 4, 5, 6]}, ["body", "enemies"]),
        ({"bans": list(range(1, 12))}, ["body", "bans"]),
        ({"min_games": 0}, ["body", "min_games"]),
        ({"min_games": 501}, ["body", "min_games"]),
        ({"queue_id": 999}, ["body", "queue_id"]),
        ({"patch": "16.18; drop"}, ["body", "patch"]),
        ({"allies": [720], "enemies": [720]}, ["body"]),
        ({"enemies": [720], "enemy_laner": 721}, ["body"]),
    ],
)
async def test_a_board_that_cannot_be_a_draft_is_refused_with_its_place(client, change, where):
    response = await client.post("/api/draft/suggest", json={"position": POSITION, **change})

    assert response.status_code == 422, response.text[:300]
    assert response.json()["detail"][0]["loc"] == where


async def test_a_repeated_champion_is_counted_once_and_said_so(client):
    patch = "D26.00"
    await seed_stat(727, 100, 55, patch=patch)
    await seed_stat(728, 100, 55, patch=patch)

    response = await client.post(
        "/api/draft/suggest",
        json={"position": "bottom", "patch": patch, "min_games": 1, "allies": [728, 728]},
    )

    assert response.status_code == 200, response.text[:300]
    body = response.json()
    assert [a["id"] for a in body["allies"]] == [728]
    assert body["warnings"] == ["allies: repeated champions were counted once"]
    assert body["position"] == POSITION, "the role is read in any case"


async def test_a_champion_nobody_plays_is_refused(client, monkeypatch):
    from types import SimpleNamespace

    from app.api import deps

    patch = "D27.00"
    await seed_stat(729, 100, 55, patch=patch)
    monkeypatch.setattr(
        deps.static_data, "all_champions", lambda: [SimpleNamespace(id=729)]
    )

    unknown = await client.post(
        "/api/draft/suggest",
        json={"position": POSITION, "patch": patch, "min_games": 1, "enemies": [99_999]},
    )
    held = await client.post(
        "/api/draft/suggest",
        json={"position": POSITION, "patch": patch, "min_games": 1, "enemies": [729]},
    )

    assert unknown.status_code == 422
    assert "99999" in unknown.json()["detail"]
    assert held.status_code == 200, held.text[:300]


async def test_a_floor_above_the_corpus_is_an_answer_with_a_way_out(client):
    """It was a 404 reading "Ingest more matches or lower min_games", which the
    page showed as "Something went wrong"."""
    patch = "D28.00"
    await seed_stat(730, 140, 70, patch=patch)
    await seed_stat(731, 60, 30, patch=patch)

    response = await client.post(
        "/api/draft/suggest", json={"position": POSITION, "patch": patch, "min_games": 500}
    )

    assert response.status_code == 200, response.text[:300]
    body = response.json()
    assert body["suggestions"] == []
    assert body["empty_reason"] == "min_games"
    assert body["most_games"] == 140


async def test_a_queue_with_nothing_held_says_so_in_plain_words(client):
    response = await client.post("/api/draft/suggest", json={"position": POSITION, "queue_id": 440})

    assert response.status_code == 404
    assert response.json()["detail"] == "Riftline holds no ranked games for this queue yet."
