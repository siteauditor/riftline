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
    MIN_TIMELINE_GAMES,
    DraftAdvisor,
    DraftContext,
    recency,
)

PATCH = "D1.00"
POSITION = "BOTTOM"


async def seed_stat(champion_id, games, wins, *, patch=PATCH, bracket=ALL_BRACKETS, queue=420,
                    position=POSITION, timeline_games=0, gold_diff=None, cs_diff=None):
    async with SessionLocal() as session:
        session.add(
            ChampionStat(
                patch=patch, queue_id=queue, rank_bracket=bracket,
                team_position=position, champion_id=champion_id,
                games=games, wins=wins, bans=0, pool_games=max(games, 100),
                avg_kills=6.0, avg_deaths=5.0, avg_assists=9.0,
                avg_cs_per_min=8.0, avg_gold=12000, avg_damage=20000, avg_vision=20,
                timeline_games=timeline_games, avg_gold_diff_14=gold_diff, avg_cs_diff_14=cs_diff,
                avg_laning_score=0.55 if timeline_games else None,
            )
        )
        await session.commit()


async def seed_matchup(champion_id, enemy_id, games, wins, *,
                       patch=PATCH, bracket=ALL_BRACKETS, scope="LANE",
                       timeline_games=0, gold_diff=None, queue=420, position=POSITION):
    async with SessionLocal() as session:
        session.add(
            MatchupStat(
                patch=patch, queue_id=queue, rank_bracket=bracket, scope=scope,
                team_position=position, champion_id=champion_id,
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
    assert high[0].win_rate == pytest.approx(0.9)
    assert low[0].win_rate == pytest.approx(0.1)


async def test_allies_enemies_and_bans_are_off_the_table():
    patch = "D4.00"
    for champion in (510, 511, 512, 513):
        await seed_stat(champion, 50, 30, patch=patch)

    picks = await suggest(patch=patch, allies=[510], enemies=[511], bans=[512])
    assert [s.champion_id for s in picks] == [513]


async def test_the_list_is_ranked_on_the_low_end_and_shows_the_whole_range():
    """As the tier list: a 70% over 20 games does not top a 55% over 300."""
    patch = "D5.00"
    await seed_stat(520, 20, 14, patch=patch)
    await seed_stat(521, 300, 165, patch=patch)

    picks = await suggest(patch=patch)

    assert [p.champion_id for p in picks] == [521, 520]
    thin = picks[1]
    assert thin.win_rate == pytest.approx(0.7)
    assert thin.range_low < thin.win_rate < thin.range_high
    assert thin.expected == pytest.approx(thin.win_rate)
    assert thin.rank_score == pytest.approx(thin.range_low)


async def test_two_games_against_the_laner_barely_move_a_pick_and_are_not_called():
    """A 2-0 lane record moved Cassiopeia from fifth to fourth (2026-09-24)."""
    patch = "D6.00"
    await seed_stat(522, 200, 100, patch=patch)
    await seed_matchup(522, 999, games=2, wins=2, patch=patch)

    pick = (await suggest(patch=patch, enemy_laner=999))[0]

    lane = pick.evidence[0]
    assert (lane.kind, lane.games, lane.wins, lane.call, lane.scored) == ("lane", 2, 2, "level", True)
    assert 0 < lane.lift < 0.01
    assert pick.context_lift == pytest.approx(lane.lift)
    assert pick.expected == pytest.approx(0.5 + lane.lift)


async def test_a_record_at_the_champions_own_rate_moves_nothing():
    """Measured against the Wilson lower bound, a record exactly at the
    champion's usual rate lifted it by several points."""
    patch = "D7.00"
    await seed_stat(523, 200, 110, patch=patch)                 # 55%
    await seed_matchup(523, 998, games=40, wins=22, patch=patch)  # 55% in lane

    pick = (await suggest(patch=patch, enemy_laner=998))[0]

    assert pick.evidence[0].lift == pytest.approx(0.0)
    assert pick.expected == pytest.approx(pick.win_rate)


async def test_team_scope_matchups_do_not_leak_into_the_lane_adjustment():
    """A TEAM row says 'this champion was somewhere on the enemy side', which is
    a different question from 'you laned against them'."""
    patch = "D8.00"
    await seed_stat(530, 200, 100, patch=patch)
    await seed_matchup(530, 997, games=60, wins=60, patch=patch, scope="TEAM")

    pick = (await suggest(patch=patch, enemy_laner=997))[0]
    assert pick.evidence == []
    assert pick.context_lift == 0


async def test_min_games_keeps_a_one_game_champion_out_of_the_draft():
    patch = "D9.00"
    await seed_stat(540, 1, 1, patch=patch)
    await seed_stat(541, 40, 22, patch=patch)

    ctx = DraftContext(position=POSITION, patch=patch, min_games=20)
    async with SessionLocal() as session:
        picks = await DraftAdvisor(session).suggest(ctx)
    assert [s.champion_id for s in picks] == [541]


# ------------------------------------------------- what the evidence supports


async def test_a_lucky_small_record_does_not_outrank_a_better_champion():
    """Ekko (53.7% at mid) took +3.3 points, the board's biggest boost, from one
    7-1 record over eight games against a champion anywhere on the enemy team,
    while three records of 8-13 counted nothing (2026-09-24). Team records are
    shown now, not scored."""
    patch = "D10.00"
    await seed_stat(550, 82, 44, patch=patch)                  # 53.7%
    await seed_matchup(550, 996, games=8, wins=7, patch=patch, scope="TEAM")
    await seed_stat(551, 300, 162, patch=patch)                # 54% over 300

    picks = await suggest(patch=patch, enemies=[996])

    assert [p.champion_id for p in picks] == [551, 550]
    lucky = picks[1]
    assert lucky.context_lift == 0
    team = lucky.evidence[0]
    assert (team.kind, team.scored, team.games, team.wins) == ("enemy", False, 8, 7)


async def test_a_thin_lane_record_does_not_outrank_a_bigger_baseline():
    """Live on 2026-09-21 this list put Yone first on a 10-2 over twelve games,
    ahead of champions with hundreds behind them."""
    patch = "D11.00"
    await seed_stat(570, 200, 100, patch=patch)   # even, with a hot lane record
    await seed_matchup(570, 995, games=12, wins=10, patch=patch)
    await seed_stat(571, 300, 165, patch=patch)   # 55% over three hundred games

    picks = await suggest(patch=patch, enemy_laner=995)

    assert [p.champion_id for p in picks] == [571, 570]
    thin = next(p for p in picks if p.champion_id == 570)
    # It still argues for the pick, a few points, and is not called on 12 games.
    assert 0 < thin.context_lift < 0.05
    assert thin.evidence[0].call == "level"


async def test_the_lane_opponent_is_not_counted_twice():
    patch = "D12.00"
    await seed_stat(572, 200, 100, patch=patch)
    await seed_matchup(572, 994, games=20, wins=15, patch=patch)
    await seed_matchup(572, 994, games=60, wins=60, patch=patch, scope="TEAM")

    pick = (await suggest(patch=patch, enemy_laner=994, enemies=[994]))[0]

    assert [e.kind for e in pick.evidence] == ["lane"]


async def test_enemy_and_ally_records_are_shown_but_do_not_move_a_pick():
    """No repeatable effect was found for them on this corpus (2026-09-24)."""
    patch = "D13.00"
    await seed_stat(573, 200, 100, patch=patch)
    await seed_matchup(573, 993, games=50, wins=40, patch=patch, scope="TEAM")
    await seed_synergy(573, 992, games=50, wins=40, patch=patch)

    pick = (await suggest(patch=patch, enemies=[993], allies=[992]))[0]

    kinds = {e.kind: e for e in pick.evidence}
    assert set(kinds) == {"enemy", "ally"}
    assert kinds["enemy"].games == 50 and not kinds["enemy"].scored
    assert kinds["ally"].games == 50 and not kinds["ally"].scored
    # 40-10 is a lot for 50 games, so the record is called, and still not scored.
    assert kinds["enemy"].call == "level" or kinds["enemy"].lift > 0
    assert pick.context_lift == 0
    assert pick.rank_score == pytest.approx(pick.range_low)


async def test_an_ally_seen_in_two_roles_is_one_record():
    """SynergyStat is keyed by the ally's role, and an ally who plays two was
    counted as two records."""
    patch = "D14.00"
    await seed_stat(574, 200, 100, patch=patch)
    await seed_synergy(574, 991, games=20, wins=12, patch=patch, ally_position="UTILITY")
    await seed_synergy(574, 991, games=10, wins=5, patch=patch, ally_position="MIDDLE")

    pick = (await suggest(patch=patch, allies=[991]))[0]

    assert [(e.kind, e.games, e.wins) for e in pick.evidence] == [("ally", 30, 17)]


async def test_a_champion_we_hold_no_rows_for_moves_nothing():
    patch = "D15.00"
    await seed_stat(575, 200, 100, patch=patch)

    pick = (await suggest(patch=patch, enemies=[888], allies=[889]))[0]

    assert pick.evidence == []
    assert pick.rank_score == pytest.approx(pick.range_low)


async def test_the_board_cannot_move_a_pick_past_the_cap():
    patch = "D16.00"
    await seed_stat(576, 400, 200, patch=patch)
    await seed_matchup(576, 990, games=400, wins=400, patch=patch)

    pick = (await suggest(patch=patch, enemy_laner=990))[0]

    assert pick.evidence[0].lift > CONTEXT_LIFT_CAP
    assert pick.context_lift == pytest.approx(CONTEXT_LIFT_CAP)


async def test_a_lane_shows_its_gold_lead_only_once_enough_games_have_timelines():
    patch = "D17.00"
    await seed_stat(577, 200, 100, patch=patch)
    await seed_matchup(577, 987, games=30, wins=18, patch=patch,
                       timeline_games=MIN_TIMELINE_GAMES - 1, gold_diff=400.0)
    await seed_stat(578, 200, 100, patch=patch)
    await seed_matchup(578, 987, games=30, wins=18, patch=patch,
                       timeline_games=MIN_TIMELINE_GAMES, gold_diff=400.0)

    picks = {p.champion_id: p for p in await suggest(patch=patch, enemy_laner=987)}

    assert picks[577].evidence[0].gold_diff_14 is None
    assert picks[578].evidence[0].gold_diff_14 == 400.0
    assert picks[578].evidence[0].timeline_games == MIN_TIMELINE_GAMES


def _held(monkeypatch, queue, *patches):
    """The patches the advisor sees as held: slices come from stored matches,
    which these tests do not write."""
    async def slices(_session):
        return [{"patch": p, "queue_id": queue, "matches": 600} for p in patches]

    monkeypatch.setattr("app.services.draft.aggregated_slices", slices)


async def test_records_pool_a_close_earlier_patch_each_against_its_own_rate(monkeypatch):
    """A champion at 60% on one patch and 40% on the one before, with each
    patch's lane record at that patch's rate, has no matchup effect to find.
    Against its rate over both patches (50%) the same rows read as +6 points."""
    queue, newer, older = 99_420, "5.2", "5.1"
    _held(monkeypatch, queue, newer, older)
    await seed_stat(579, 100, 60, patch=newer, queue=queue)
    await seed_stat(579, 100, 40, patch=older, queue=queue)
    await seed_matchup(579, 986, games=20, wins=12, patch=newer, queue=queue)
    await seed_matchup(579, 986, games=5, wins=2, patch=older, queue=queue)

    ctx = DraftContext(position=POSITION, patch=newer, queue_id=queue, enemy_laner=986, min_games=1)
    async with SessionLocal() as session:
        pick = (await DraftAdvisor(session).suggest(ctx))[0]

    lane = pick.evidence[0]
    assert (lane.games, lane.wins, lane.patches) == (25, 14, (newer, older))
    assert lane.lift == pytest.approx(0.0, abs=1e-9)


async def test_a_patch_without_the_champions_own_rate_is_left_out_of_the_record(monkeypatch):
    queue, newer, older = 99_421, "6.2", "6.1"
    _held(monkeypatch, queue, newer, older)
    await seed_stat(582, 100, 50, patch=newer, queue=queue)
    await seed_stat(583, 100, 50, patch=older, queue=queue)   # keeps the older patch held
    await seed_matchup(582, 985, games=10, wins=5, patch=newer, queue=queue)
    await seed_matchup(582, 985, games=10, wins=10, patch=older, queue=queue)

    ctx = DraftContext(position=POSITION, patch=newer, queue_id=queue, enemy_laner=985, min_games=1)
    async with SessionLocal() as session:
        pick = next(p for p in await DraftAdvisor(session).suggest(ctx) if p.champion_id == 582)

    assert (pick.evidence[0].games, pick.evidence[0].patches) == (10, (newer,))


async def test_ban_records_come_from_the_candidates_main_role_and_do_not_reorder_it():
    patch = "D18.00"
    await seed_stat(580, 100, 58, patch=patch)
    await seed_stat(581, 100, 60, patch=patch)
    # Against the ally we locked in: one record in 581's main role, one in a
    # role it hardly plays. Only the first belongs to the candidate shown.
    await seed_matchup(581, 979, games=60, wins=48, patch=patch, scope="TEAM")
    await seed_matchup(581, 979, games=30, wins=30, patch=patch, scope="TEAM", position="TOP")
    await seed_matchup(580, 979, games=60, wins=12, patch=patch, scope="TEAM")

    ranked = await bans(patch=patch, allies=[979])

    assert [c.champion_id for c in ranked] == [581, 580]
    top = ranked[0]
    assert [(e.games, e.scored) for e in top.evidence] == [(60, False)]
    assert top.score == pytest.approx(top.range_low)


async def test_the_champion_you_are_facing_is_not_offered_as_a_pick():
    """Seen locally on 2026-09-21: asking for mid into Ahri suggested Ahri."""
    patch = "D19.00"
    await seed_stat(585, 200, 110, patch=patch)   # the enemy laner
    await seed_stat(586, 200, 100, patch=patch)

    picks = await suggest(patch=patch, enemy_laner=585)

    assert [p.champion_id for p in picks] == [586]
    assert [c.champion_id for c in await bans(patch=patch, enemy_laner=585)] == [586]


async def test_mastery_counts_less_the_longer_ago_the_champion_was_played():
    """Mastery points never decay, and a champion untouched for two years
    counted as fully comfortable."""
    from app.db.models import ChampionMastery, Player

    patch = "D20.00"
    await seed_stat(587, 200, 100, patch=patch)
    await seed_stat(588, 200, 100, patch=patch)
    puuid = "draft-recency".ljust(78, "0")
    now = 1_790_000_000.0
    day = 86_400_000
    async with SessionLocal() as session:
        session.add(Player(puuid=puuid, game_name="Recent", tag_line="EUW", platform="euw1"))
        session.add(ChampionMastery(puuid=puuid, champion_id=587, champion_level=40,
                                    champion_points=200_000, last_play_time=int(now * 1000) - 5 * day))
        session.add(ChampionMastery(puuid=puuid, champion_id=588, champion_level=40,
                                    champion_points=200_000, last_play_time=int(now * 1000) - 400 * day))
        await session.commit()

    picks = {p.champion_id: p for p in await suggest(patch=patch, puuid=puuid, comfort_weight=0.4, now=now)}

    assert picks[587].comfort == pytest.approx(1.0)
    assert picks[588].comfort == pytest.approx(0.25)
    assert picks[587].rank_score > picks[588].rank_score
    assert any("last played 13 months ago" in r for r in picks[588].reasons)
    assert recency(90) == pytest.approx(0.8)


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


async def test_the_response_carries_the_range_the_records_and_the_model(client):
    """What the page reads, end to end. The browser smoke test skips the draft
    on CI's empty corpus, so the shape is pinned here."""
    patch = "D29.00"
    await seed_stat(732, 200, 110, patch=patch)
    # The enemies have rows too, which is what makes their ids known here.
    await seed_stat(733, 100, 50, patch=patch)
    await seed_stat(734, 100, 50, patch=patch)
    await seed_matchup(732, 733, games=30, wins=20, patch=patch)
    await seed_matchup(732, 734, games=30, wins=12, patch=patch, scope="TEAM")

    response = await client.post(
        "/api/draft/suggest",
        json={
            "position": POSITION, "patch": patch, "min_games": 1,
            "enemies": [733, 734], "enemy_laner": 733,
        },
    )

    assert response.status_code == 200, response.text[:300]
    body = response.json()
    assert body["patches"] == [patch]
    pick = body["suggestions"][0]
    assert pick["range_low"] < pick["expected"] < pick["range_high"]
    assert pick["rank_score"] == pytest.approx(pick["range_low"])
    lane, team = pick["evidence"]
    assert (lane["kind"], lane["scored"], lane["patches"]) == ("lane", True, [patch])
    assert (team["kind"], team["scored"]) == ("enemy", False)
    assert lane["call"] in {"favoured", "unfavoured", "level"}
    assert pick["context_lift"] == pytest.approx(lane["lift"])
    assert body["model"]["lane_strength"] == 100
    assert body["model"]["team_strength"] == 500
    # The fields pages loaded before this model read, still filled for a release.
    assert pick["score"] == pytest.approx(pick["rank_score"])
    assert pick["adjusted_win_rate"] == pytest.approx(pick["expected"])
    assert body["model"]["lane_shrinkage"] == 100



# ------------------------------------------------------------ reading the board


def _roles(monkeypatch, counts):
    """Role priors for these champions: champion -> {position: games}."""
    from app.services.roles import RolePriors

    async def priors(_session):
        return RolePriors(champion=counts, spell={}, participants=sum(sum(c.values()) for c in counts.values()))

    monkeypatch.setattr("app.services.draft.load_priors", priors)


async def board_and_picks(**kw):
    ctx = DraftContext(position=kw.pop("position", POSITION), patch=kw.pop("patch", PATCH), min_games=1, **kw)
    async with SessionLocal() as session:
        advisor = DraftAdvisor(session)
        board = await advisor.read_board(ctx)
        picks, pinned = await advisor.suggest_and_check(ctx, board=board, include=kw.get("include"))
    return board, picks, pinned


async def test_the_lane_opponent_is_inferred_from_the_enemy_picks(monkeypatch):
    """An enemy who plays nothing but your role is your laner; the record
    against them counts in full."""
    patch = "D30.00"
    _roles(monkeypatch, {760: {"BOTTOM": 500}, 761: {"JUNGLE": 500}})
    await seed_stat(762, 200, 100, patch=patch)
    await seed_matchup(762, 760, games=40, wins=30, patch=patch)

    board, picks, _ = await board_and_picks(patch=patch, enemies=[760, 761])

    assert (board.lane_opponent, board.lane_source) == (760, "inferred")
    assert board.lane_probability > 0.99
    assert not board.blind
    lane = picks[0].evidence[0]
    assert (lane.kind, lane.champion_id) == ("lane", 760)
    assert picks[0].context_lift == pytest.approx(lane.weight * lane.lift)


async def test_a_flex_enemy_counts_in_proportion_to_the_chance_it_is_your_laner(monkeypatch):
    patch = "D31.00"
    _roles(monkeypatch, {763: {"BOTTOM": 250, "TOP": 250}})
    await seed_stat(764, 200, 100, patch=patch)
    await seed_matchup(764, 763, games=40, wins=30, patch=patch)

    board, picks, _ = await board_and_picks(patch=patch, enemies=[763])

    assert board.lane_weights[763] == pytest.approx(0.5, abs=0.01)
    assert board.blind is False or board.lane_probability < 0.5
    lane = picks[0].evidence[0]
    assert picks[0].context_lift == pytest.approx(lane.weight * lane.lift)
    assert lane.weight == pytest.approx(0.5, abs=0.01)


async def test_a_marked_laner_overrides_the_guess_and_no_inference_means_blind(monkeypatch):
    patch = "D32.00"
    _roles(monkeypatch, {765: {"BOTTOM": 500}, 766: {"MIDDLE": 500}})
    await seed_stat(767, 200, 100, patch=patch)

    marked, _, _ = await board_and_picks(patch=patch, enemies=[765, 766], enemy_laner=766)
    unknown, _, _ = await board_and_picks(patch=patch, enemies=[765, 766], infer_lane=False)

    assert (marked.lane_opponent, marked.lane_source, marked.lane_weights) == (766, "marked", {766: 1.0})
    assert unknown.lane_weights == {}
    assert unknown.lane_opponent is None and unknown.blind


async def test_bot_lane_finds_the_other_enemy_in_the_lane_and_a_clash_is_flagged(monkeypatch):
    patch = "D33.00"
    _roles(monkeypatch, {
        768: {"BOTTOM": 500}, 769: {"UTILITY": 500},
        770: {"BOTTOM": 470, "MIDDLE": 30},   # an ally who is almost always the ADC
    })
    await seed_stat(771, 200, 100, patch=patch)

    board, _, _ = await board_and_picks(patch=patch, enemies=[768, 769], allies=[770])

    assert board.lane_opponent == 768
    assert board.duo == 769
    assert board.role_clash is not None and board.role_clash[0] == 770
    assert board.role_clash[1] == pytest.approx(0.94)
    assert [r.position for r in board.ally_roles] == ["MIDDLE"]


async def test_a_champion_checked_by_hand_keeps_its_rank_or_says_it_is_under_the_floor(monkeypatch):
    patch = "D34.00"
    _roles(monkeypatch, {})
    await seed_stat(772, 300, 165, patch=patch)
    await seed_stat(773, 200, 100, patch=patch)
    await seed_stat(774, 3, 3, patch=patch)

    ctx = DraftContext(position=POSITION, patch=patch, min_games=20)
    async with SessionLocal() as session:
        advisor = DraftAdvisor(session)
        top, pinned = await advisor.suggest_and_check(ctx, include=[773, 774], limit=1)

    assert [p.champion_id for p in top] == [772]
    assert [(p.champion_id, p.rank, p.below_min) for p in pinned] == [(773, 2, False), (774, None, True)]


async def test_a_blind_pick_lists_the_lanes_it_is_known_to_lose(monkeypatch):
    """Only records the posterior calls unfavoured, not the worst of many thin ones."""
    patch = "D35.00"
    _roles(monkeypatch, {})
    await seed_stat(775, 400, 200, patch=patch)
    await seed_stat(776, 300, 150, patch=patch)    # the common opponent
    await seed_stat(777, 20, 10, patch=patch)      # a rare one
    await seed_matchup(775, 776, games=80, wins=24, patch=patch)   # 30%: called
    await seed_matchup(775, 777, games=3, wins=0, patch=patch)     # 0-3: not called

    board, picks, _ = await board_and_picks(patch=patch)
    pick = next(p for p in picks if p.champion_id == 775)

    assert board.blind
    assert [(r.champion_id, r.call, r.scored) for r in pick.blind_risks] == [(776, "unfavoured", False)]
    assert pick.blind_risks[0].weight == pytest.approx(300 / 720)


async def test_a_champions_own_laning_figures_need_ten_games_with_timelines(monkeypatch):
    patch = "D36.00"
    _roles(monkeypatch, {})
    await seed_stat(778, 200, 100, patch=patch, timeline_games=12, gold_diff=180.0, cs_diff=6.5)
    await seed_stat(779, 200, 100, patch=patch, timeline_games=9, gold_diff=900.0, cs_diff=20.0)

    _, picks, _ = await board_and_picks(patch=patch)
    by_id = {p.champion_id: p for p in picks}

    assert (by_id[778].laning.gold_diff_14, by_id[778].laning.timeline_games) == (180.0, 12)
    assert by_id[779].laning is None
