"""Groups: keys, members, filling them in from Riot, and the table.

Riot is mocked at the transport, as everywhere. `FakeRiot` below plays a small
Riot: accounts named after their Riot ID, a match history per player that the
list endpoint pages through with ``start``, ``count``, ``startTime`` and
``endTime`` as Riot does, and ranks per player.
"""

from __future__ import annotations

import copy
import hashlib
import time
from datetime import timedelta
from urllib.parse import unquote

import httpx
import pytest
import respx
from sqlalchemy import select, update

from app.config import get_settings
from app.db.base import SessionLocal
from app.db.models import GroupMember, HistoryCursor, PlayerGroup, utcnow
from app.riot.limiter import SEARCH_RESERVE
from app.services import groups as groups_service
from app.services.groups import CREATES, Budget, Warmer, WarmTarget, delete_empty_groups
from tests import fixtures as fx

KEY = "X-Group-Key"


def puuid_for(name: str) -> str:
    return f"grp-{name.lower().replace(' ', '-')}-".ljust(78, "x")


def league(tier: str, division: str, lp: int, puuid: str) -> list[dict]:
    return [{
        "leagueId": "x", "puuid": puuid, "queueType": "RANKED_SOLO_5x5",
        "tier": tier, "rank": division, "leaguePoints": lp, "wins": 30, "losses": 25,
        "hotStreak": False, "veteran": False, "freshBlood": False, "inactive": False,
    }]


def game(match_id: str, sides: dict[str, int], *, queue: int = 420, blue_won: bool = True,
         hours_ago: float = 5.0) -> dict:
    """A match with these players on these teams (100 or 200), the rest strangers."""
    payload = copy.deepcopy(fx.match(match_id, queue=queue))
    created = int((time.time() - hours_ago * 3600) * 1000)
    payload["info"]["gameCreation"] = created
    payload["info"]["gameEndTimestamp"] = created + payload["info"]["gameDuration"] * 1000
    participants = payload["info"]["participants"]
    free = {100: [0, 1, 2, 3, 4], 200: [5, 6, 7, 8, 9]}
    # Every seat a stranger first, so a fixture puuid never collides with
    # another test's player.
    for i, p in enumerate(participants):
        p["puuid"] = f"stranger-{match_id}-{i}".ljust(78, "0")
    for puuid, team in sides.items():
        seat = free[team].pop(0)
        participants[seat]["puuid"] = puuid
    for i, p in enumerate(participants):
        team = 100 if i < 5 else 200
        p["teamId"] = team
        p["win"] = blue_won if team == 100 else not blue_won
    payload["info"]["teams"][0]["win"] = blue_won
    payload["info"]["teams"][1]["win"] = not blue_won
    payload["metadata"]["participants"] = [p["puuid"] for p in participants]
    return payload


class FakeRiot:
    def __init__(self) -> None:
        self.payloads: dict[str, dict] = {}
        # puuid -> ids newest first
        self.histories: dict[str, list[str]] = {}
        self.ranks: dict[str, list[dict]] = {}
        self.id_calls: list[tuple[str, dict]] = []
        self.fetched: list[str] = []

    def add_game(self, payload: dict) -> None:
        mid = payload["metadata"]["matchId"]
        self.payloads[mid] = payload
        for p in payload["info"]["participants"]:
            ids = self.histories.setdefault(p["puuid"], [])
            ids.append(mid)
            ids.sort(key=lambda m: -self.payloads[m]["info"]["gameCreation"])

    def install(self) -> None:
        respx.get(url__regex=r".*/riot/account/v1/accounts/by-riot-id/(?P<name>[^/]+)/(?P<tag>[^/?]+)$").mock(
            side_effect=self._account
        )
        respx.get(url__regex=r".*/lol/summoner/v4/summoners/by-puuid/(?P<puuid>[^/?]+)$").mock(
            side_effect=lambda request, puuid: httpx.Response(
                200, json={"puuid": puuid, "profileIconId": 1, "summonerLevel": 100}
            )
        )
        respx.get(url__regex=r".*/lol/league/v4/entries/by-puuid/(?P<puuid>[^/?]+)$").mock(
            side_effect=lambda request, puuid: httpx.Response(200, json=self.ranks.get(puuid, []))
        )
        respx.get(url__regex=r".*/lol/match/v5/matches/by-puuid/(?P<puuid>[^/]+)/ids.*").mock(
            side_effect=self._ids
        )
        respx.get(url__regex=r".*/lol/match/v5/matches/(?P<mid>[A-Z0-9]+_[0-9]+)/timeline$").mock(
            return_value=httpx.Response(404)
        )
        respx.get(url__regex=r".*/lol/match/v5/matches/(?P<mid>[A-Z0-9]+_[0-9]+)$").mock(
            side_effect=self._match
        )

    def _account(self, request, name, tag):
        name, tag = unquote(name), unquote(tag)
        if name.lower().startswith("nobody"):
            return httpx.Response(404)
        return httpx.Response(200, json={"puuid": puuid_for(name), "gameName": name, "tagLine": tag})

    def _ids(self, request, puuid):
        params = dict(request.url.params)
        self.id_calls.append((puuid, params))
        ids = self.histories.get(puuid, [])
        start_time = int(params["startTime"]) if "startTime" in params else None
        end_time = int(params["endTime"]) if "endTime" in params else None

        def when(mid: str) -> int:
            return self.payloads[mid]["info"]["gameCreation"] // 1000

        if start_time is not None:
            ids = [m for m in ids if when(m) >= start_time]
        if end_time is not None:
            ids = [m for m in ids if when(m) <= end_time]
        start, count = int(params.get("start", 0)), int(params.get("count", 20))
        return httpx.Response(200, json=ids[start:start + count])

    def _match(self, request, mid):
        self.fetched.append(mid)
        payload = self.payloads.get(mid)
        return httpx.Response(200, json=payload) if payload else httpx.Response(404)


async def make_group(client, name: str = "Test group") -> tuple[str, str]:
    response = await client.post("/api/groups", json={"name": name})
    assert response.status_code == 201, response.text
    body = response.json()
    return body["slug"], body["key"]


async def add(client, slug: str, key: str, riot_id: str, platform: str = "euw1", **extra):
    return await client.post(
        f"/api/groups/{slug}/members",
        json={"riot_id": riot_id, "platform": platform, **extra},
        headers={KEY: key},
    )


@pytest.fixture
def cap(monkeypatch):
    def set_cap(value: int) -> None:
        monkeypatch.setattr(get_settings(), "group_history_cap", value)
    return set_cap


# ------------------------------------------------------------------- keys


async def test_the_database_keeps_only_a_hash_of_the_edit_key(client):
    slug, key = await make_group(client, "  Hash   check  ")
    assert len(slug) == 10 and len(key) >= 32
    async with SessionLocal() as session:
        group = (await session.execute(select(PlayerGroup).where(PlayerGroup.slug == slug))).scalar_one()
    assert group.name == "Hash check", "whitespace collapsed"
    assert group.edit_key_hash == hashlib.sha256(key.encode()).hexdigest()
    assert key not in group.edit_key_hash


async def test_only_the_edit_key_changes_a_group(client):
    slug, key = await make_group(client)

    viewer = (await client.get(f"/api/groups/{slug}")).json()
    assert viewer["can_edit"] is False
    assert (await client.get(f"/api/groups/{slug}", headers={KEY: key})).json()["can_edit"] is True

    assert (await client.patch(f"/api/groups/{slug}", json={"name": "New"})).status_code == 403
    wrong = await client.patch(f"/api/groups/{slug}", json={"name": "New"}, headers={KEY: "nope"})
    assert wrong.status_code == 403
    right = await client.patch(f"/api/groups/{slug}", json={"name": "New"}, headers={KEY: key})
    assert right.status_code == 204
    assert (await client.get(f"/api/groups/{slug}")).json()["name"] == "New"


async def test_a_new_edit_key_retires_the_old_one(client):
    slug, old = await make_group(client)
    rotated = await client.post(f"/api/groups/{slug}/key", headers={KEY: old})
    new = rotated.json()["key"]
    assert new != old
    assert (await client.patch(f"/api/groups/{slug}", json={"name": "x"}, headers={KEY: old})).status_code == 403
    assert (await client.patch(f"/api/groups/{slug}", json={"name": "x"}, headers={KEY: new})).status_code == 204


async def test_deleting_a_group_removes_it_and_its_members(client):
    riot = FakeRiot()
    with respx.mock:
        riot.install()
        slug, key = await make_group(client)
        assert (await add(client, slug, key, "DelMe#EUW")).status_code == 201
        assert (await client.delete(f"/api/groups/{slug}")).status_code == 403
        assert (await client.delete(f"/api/groups/{slug}", headers={KEY: key})).status_code == 204
    assert (await client.get(f"/api/groups/{slug}")).status_code == 404
    async with SessionLocal() as session:
        left = (await session.execute(
            select(GroupMember).where(GroupMember.puuid == puuid_for("DelMe"))
        )).scalars().all()
    assert left == []


async def test_an_unknown_group_is_a_404(client):
    assert (await client.get("/api/groups/NoSuchSlug")).status_code == 404


# ----------------------------------------------------------------- members


@respx.mock
async def test_adding_players_resolves_them_and_refuses_repeats(client):
    FakeRiot().install()
    slug, key = await make_group(client)

    first = await add(client, slug, key, "Adder One#EUW", label="  Top  ")
    assert first.status_code == 201, first.text
    assert first.json()["riot_id"] == "Adder One#EUW"
    assert first.json()["platform"] == "euw1"

    again = await add(client, slug, key, "adder one#euw")
    assert again.status_code == 409
    assert "already" in again.json()["detail"]

    assert (await add(client, slug, key, "NobodyHere#EUW")).status_code == 404
    assert (await add(client, slug, key, "No tag at all")).status_code == 400
    assert (await add(client, slug, "wrong-key", "Adder Two#EUW")).status_code == 403

    body = (await client.get(f"/api/groups/{slug}")).json()
    (member,) = body["members"]
    assert member["label"] == "Top"
    assert member["history"]["pending"] is True, "nothing fetched yet"


@respx.mock
async def test_a_group_holds_twenty_players_at_most(client):
    FakeRiot().install()
    slug, key = await make_group(client)
    for i in range(20):
        response = await add(client, slug, key, f"Full{i}#EUW")
        assert response.status_code == 201, response.text
    over = await add(client, slug, key, "Full20#EUW")
    assert over.status_code == 409
    assert "full" in over.json()["detail"]


@respx.mock
async def test_labels_and_removal(client):
    FakeRiot().install()
    slug, key = await make_group(client)
    await add(client, slug, key, "Labelled#EUW")
    puuid = puuid_for("Labelled")

    response = await client.patch(
        f"/api/groups/{slug}/members/{puuid}", json={"label": "Sub"}, headers={KEY: key}
    )
    assert response.status_code == 204
    assert (await client.get(f"/api/groups/{slug}")).json()["members"][0]["label"] == "Sub"

    assert (await client.delete(f"/api/groups/{slug}/members/{puuid}")).status_code == 403
    assert (await client.delete(f"/api/groups/{slug}/members/{puuid}", headers={KEY: key})).status_code == 204
    assert (await client.get(f"/api/groups/{slug}")).json()["members"] == []
    assert (await client.delete(f"/api/groups/{slug}/members/{puuid}", headers={KEY: key})).status_code == 404


# ------------------------------------------------------------------ warming


@respx.mock
async def test_warming_reads_the_history_back_to_the_cap_and_no_further(client, cap):
    cap(5)
    riot = FakeRiot()
    riot.install()
    me = puuid_for("Capped")
    for n in range(8):
        riot.add_game(game(f"EUW1_9501{n:06d}", {me: 100}, hours_ago=3 + n))
    slug, key = await make_group(client)
    await add(client, slug, key, "Capped#EUW")

    body = (await client.post(f"/api/groups/{slug}/warm")).json()
    assert body["pending"] == 0, body
    assert sorted(riot.fetched) == sorted(riot.histories[me][:5]), "the newest five, and only them"

    history_calls = [params for puuid, params in riot.id_calls if puuid == me and "endTime" in params]
    assert history_calls and all(int(p["count"]) <= 5 for p in history_calls)

    table = (await client.get(f"/api/groups/{slug}")).json()
    (member,) = table["members"]
    assert member["games"] == 5
    assert member["history"] == {
        "stored": 5, "oldest": member["history"]["oldest"], "read": 5,
        "exhausted": False, "pending": False,
    }

    # A second pass costs nothing: the history is read and the new games were
    # looked for within the last ten minutes.
    before = len(riot.id_calls) + len(riot.fetched)
    await client.post(f"/api/groups/{slug}/warm")
    assert len(riot.id_calls) + len(riot.fetched) == before


@respx.mock
async def test_a_short_history_is_marked_as_all_there_is(client, cap):
    cap(50)
    riot = FakeRiot()
    riot.install()
    me = puuid_for("Shorty")
    for n in range(3):
        riot.add_game(game(f"EUW1_9502{n:06d}", {me: 100}, hours_ago=3 + n))
    slug, key = await make_group(client)
    await add(client, slug, key, "Shorty#EUW")

    body = (await client.post(f"/api/groups/{slug}/warm")).json()
    assert body["pending"] == 0
    history = (await client.get(f"/api/groups/{slug}")).json()["members"][0]["history"]
    assert (history["read"], history["exhausted"]) == (3, True)


@respx.mock
async def test_the_history_pages_under_a_fixed_end_time(client, cap, monkeypatch):
    """Riot's offsets shift with every game played; under a fixed end time they
    do not, so a game played between two pages cannot shift the second."""
    cap(10)
    monkeypatch.setattr(groups_service, "PAGE", 3)
    riot = FakeRiot()
    riot.install()
    me = puuid_for("Pager")
    for n in range(7):
        riot.add_game(game(f"EUW1_9503{n:06d}", {me: 100}, hours_ago=3 + n))
    slug, key = await make_group(client)
    await add(client, slug, key, "Pager#EUW")

    await client.post(f"/api/groups/{slug}/warm")
    pages = [p for puuid, p in riot.id_calls if puuid == me and "endTime" in p]
    assert [int(p["start"]) for p in pages] == [0, 3, 6]
    assert len({p["endTime"] for p in pages}) == 1, "one end time for the whole walk"
    assert len(set(riot.fetched)) == 7


@respx.mock
async def test_new_games_are_read_from_the_last_look_on(client, cap):
    cap(5)
    riot = FakeRiot()
    riot.install()
    me = puuid_for("Newgames")
    riot.add_game(game("EUW1_9504000001", {me: 100}, hours_ago=5))
    slug, key = await make_group(client)
    await add(client, slug, key, "Newgames#EUW")
    await client.post(f"/api/groups/{slug}/warm")

    # A game finished since, and the last look made long enough ago to look again.
    riot.add_game(game("EUW1_9504000002", {me: 100}, hours_ago=0.2))
    async with SessionLocal() as session:
        await session.execute(
            update(HistoryCursor).where(HistoryCursor.puuid == me).values(checked_at=None)
        )
        await session.commit()
    await client.post(f"/api/groups/{slug}/warm")
    assert "EUW1_9504000002" in riot.fetched
    assert (await client.get(f"/api/groups/{slug}")).json()["members"][0]["games"] == 2


@respx.mock
async def test_warming_leaves_the_keys_last_calls_for_searches(client, monkeypatch):
    from app.main import app

    riot = FakeRiot()
    riot.install()
    slug, key = await make_group(client)
    await add(client, slug, key, "Reserved#EUW")
    calls_before = len(riot.id_calls)

    limiter = app.state.riot.limiter
    monkeypatch.setattr(limiter, "spare", lambda: SEARCH_RESERVE)
    monkeypatch.setattr(limiter, "seconds_until_free", lambda slots: 12.0)
    body = (await client.post(f"/api/groups/{slug}/warm")).json()
    assert body["key_busy"] is True
    assert body["retry_after"] == 12.0
    assert body["calls"] == 0 and body["pending"] == 1
    assert len(riot.id_calls) == calls_before


async def test_a_pass_stops_at_its_time_budget():
    budget = Budget(limiter=None, deadline=time.monotonic() - 1)  # type: ignore[arg-type]
    assert await budget.take(5) == 0
    assert budget.stopped == "time"


@respx.mock
async def test_history_is_read_a_chunk_per_player_in_turn(client, cap, monkeypatch):
    """One long history must not starve the rest of the group."""
    cap(10)
    monkeypatch.setattr(groups_service, "CHUNK", 2)
    riot = FakeRiot()
    riot.install()
    a, b = puuid_for("Turn A"), puuid_for("Turn B")
    for n in range(4):
        riot.add_game(game(f"EUW1_9505{n:06d}", {a: 100}, hours_ago=3 + n))
        riot.add_game(game(f"EUW1_9506{n:06d}", {b: 200}, hours_ago=3 + n))
    slug, key = await make_group(client)
    await add(client, slug, key, "Turn A#EUW")
    await add(client, slug, key, "Turn B#EUW")

    async with SessionLocal() as session:
        from app.main import app

        budget = Budget(app.state.riot.limiter)
        warmer = Warmer(session, app.state.riot, get_settings(), budget)
        await warmer.run([WarmTarget(a, "euw1"), WarmTarget(b, "euw1")])
    owners = ["a" if m.startswith("EUW1_9505") else "b" for m in riot.fetched]
    assert owners == ["a", "a", "b", "b", "a", "a", "b", "b"]


# -------------------------------------------------------------------- table


@respx.mock
async def test_the_table_orders_by_official_rank(client, cap):
    cap(5)
    riot = FakeRiot()
    riot.install()
    gold, diamond = puuid_for("Rank Gold"), puuid_for("Rank Diamond")
    riot.ranks[gold] = league("GOLD", "I", 90, gold)
    riot.ranks[diamond] = league("DIAMOND", "IV", 3, diamond)
    slug, key = await make_group(client)
    for name in ("Rank None", "Rank Gold", "Rank Diamond"):
        await add(client, slug, key, f"{name}#EUW")
    await client.post(f"/api/groups/{slug}/warm")

    members = (await client.get(f"/api/groups/{slug}")).json()["members"]
    assert [m["riot_id"] for m in members] == ["Rank Diamond#EUW", "Rank Gold#EUW", "Rank None#EUW"]
    assert members[0]["ranks"][0]["tier"] == "DIAMOND"
    assert members[2]["ranks"] == [] and members[2]["rank_read_at"] is not None, (
        "unranked is a reading, not a gap"
    )


@respx.mock
async def test_queue_filters_and_the_five_game_floor(client, cap):
    cap(50)
    riot = FakeRiot()
    riot.install()
    me = puuid_for("Filters")
    n = 0
    for queue, count in ((420, 6), (450, 3), (1700, 2), (490, 1)):
        for _ in range(count):
            riot.add_game(game(f"EUW1_9507{n:06d}", {me: 100}, queue=queue, hours_ago=3 + n))
            n += 1
    slug, key = await make_group(client)
    await add(client, slug, key, "Filters#EUW")
    await client.post(f"/api/groups/{slug}/warm")

    async def row(queue: str) -> tuple[dict, dict]:
        body = (await client.get(f"/api/groups/{slug}?queue={queue}")).json()
        return body, body["members"][0]

    body, everything = await row("all")
    assert everything["games"] == 12 and body["scored_mode"] is True
    body, solo = await row("solo")
    assert solo["games"] == 6 and solo["win_rate"] is not None
    body, aram = await row("aram")
    assert aram["games"] == 3
    assert aram["win_rate"] is None and "figures need 5" in aram["withheld"]
    assert body["scored_mode"] is False
    assert aram["score_profile"] == [] and aram["lanes"] == [] and aram["review"] == []
    body, arena = await row("arena")
    assert arena["games"] == 2
    body, normal = await row("normal")
    assert normal["games"] == 1 and normal["recent"] == [True]

    assert (await client.get(f"/api/groups/{slug}?queue=urf")).status_code == 400


@respx.mock
async def test_played_together_counts_teammates_not_opponents(client, cap):
    cap(50)
    riot = FakeRiot()
    riot.install()
    a, b = puuid_for("Duo A"), puuid_for("Duo B")
    for n in range(3):
        riot.add_game(game(f"EUW1_9508{n:06d}", {a: 100, b: 100}, blue_won=n != 2, hours_ago=3 + n))
    riot.add_game(game("EUW1_9508000009", {a: 100, b: 200}, hours_ago=9))
    slug, key = await make_group(client)
    await add(client, slug, key, "Duo A#EUW")
    await add(client, slug, key, "Duo B#EUW")
    await client.post(f"/api/groups/{slug}/warm")

    together = (await client.get(f"/api/groups/{slug}")).json()["together"]
    assert (together["games"], together["wins"]) == (3, 2)
    (pair,) = together["pairs"]
    assert {pair["a"], pair["b"]} == {a, b}
    assert (pair["games"], pair["wins"]) == (3, 2)
    assert [g["match_id"] for g in together["recent"]] == [
        "EUW1_9508000000", "EUW1_9508000001", "EUW1_9508000002",
    ]
    assert len(together["recent"][0]["players"]) == 2


# -------------------------------------------------------------------- abuse


async def test_one_address_can_make_ten_groups_an_hour(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "group_creates_per_hour", 2)
    CREATES.reset()
    try:
        assert (await client.post("/api/groups", json={"name": "a"})).status_code == 201
        assert (await client.post("/api/groups", json={"name": "b"})).status_code == 201
        third = await client.post("/api/groups", json={"name": "c"})
        assert third.status_code == 429
        assert int(third.headers["Retry-After"]) > 0

        # Counted per visitor as Cloudflare names them, not per the address a
        # visitor can write into X-Forwarded-For themselves.
        other = {"CF-Connecting-IP": "203.0.113.7", "X-Forwarded-For": "198.51.100.1"}
        assert (await client.post("/api/groups", json={"name": "d"}, headers=other)).status_code == 201
        spoof = {"CF-Connecting-IP": "203.0.113.7", "X-Forwarded-For": "198.51.100.2"}
        assert (await client.post("/api/groups", json={"name": "e"}, headers=spoof)).status_code == 201
        assert (await client.post("/api/groups", json={"name": "f"}, headers=spoof)).status_code == 429
    finally:
        CREATES.reset()


# -------------------------------------------------------------- housekeeping


@respx.mock
async def test_empty_groups_are_removed_after_a_week(client):
    FakeRiot().install()
    empty_old, _ = await make_group(client, "empty old")
    empty_new, _ = await make_group(client, "empty new")
    full_old, key = await make_group(client, "full old")
    await add(client, full_old, key, "Keeper#EUW")
    async with SessionLocal() as session:
        await session.execute(
            update(PlayerGroup)
            .where(PlayerGroup.slug.in_([empty_old, full_old]))
            .values(updated_at=utcnow() - timedelta(days=8))
        )
        await session.commit()
        removed = await delete_empty_groups(session)
    assert removed >= 1
    assert (await client.get(f"/api/groups/{empty_old}")).status_code == 404
    assert (await client.get(f"/api/groups/{empty_new}")).status_code == 200
    assert (await client.get(f"/api/groups/{full_old}")).status_code == 200


# ------------------------------------------------------------------ nightly


@respx.mock
async def test_the_nightly_pass_reads_a_shared_player_once(client, cap):
    from app.main import app
    from app.services.groups import warm_all_groups

    cap(5)
    riot = FakeRiot()
    riot.install()
    shared = puuid_for("Nightly Shared")
    riot.add_game(game("EUW1_9509000001", {shared: 100}, hours_ago=3))
    first, first_key = await make_group(client)
    second, second_key = await make_group(client)
    await add(client, first, first_key, "Nightly Shared#EUW")
    await add(client, second, second_key, "Nightly Shared#EUW")

    async with SessionLocal() as session:
        await warm_all_groups(session, app.state.riot, get_settings(), calls=10_000)
    history = [p for puuid, p in riot.id_calls if puuid == shared and "endTime" in p]
    assert len(history) == 1
    assert riot.fetched.count("EUW1_9509000001") == 1


async def test_a_pass_stops_at_its_call_budget():
    class Roomy:
        def spare(self) -> int:
            return 1000

    budget = Budget(limiter=Roomy(), calls=2)  # type: ignore[arg-type]
    assert await budget.take(5) == 2
    budget.spend(2)
    assert await budget.take(1) == 0
    assert budget.stopped == "calls"


@respx.mock
async def test_one_players_failure_does_not_stop_the_pass(client, cap):
    """A Riot error on one player rolls the session back, which expires every
    loaded row; the pass must still reach the next player and answer."""
    cap(5)
    broken, fine = puuid_for("Broken One"), puuid_for("Fine One")
    # Registered first: respx answers with the first route that matches.
    respx.get(url__regex=rf".*/by-puuid/{broken}/ids.*").mock(return_value=httpx.Response(400))
    riot = FakeRiot()
    riot.install()
    riot.add_game(game("EUW1_9510000001", {fine: 100}, hours_ago=3))
    slug, key = await make_group(client)
    await add(client, slug, key, "Broken One#EUW")
    await add(client, slug, key, "Fine One#EUW")

    response = await client.post(f"/api/groups/{slug}/warm")
    assert response.status_code == 200
    assert response.json()["pending"] == 1, "only the broken player is left"
    assert "EUW1_9510000001" in riot.fetched
