# Riftline

A League of Legends analytics site: summoner profiles and match history, a champion
mastery dashboard, champion tier lists, and a draft assistant.

FastAPI + SQLAlchemy on the backend, React + Vite + Tailwind on the front.

---

## Quick start

You need a Riot API key. Get one at <https://developer.riotgames.com> (sign in, the
development key is on the dashboard).

```bash
# backend
cd backend
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt   # Windows
# source .venv/bin/activate && pip install -r requirements-dev.txt   # macOS/Linux

cp .env.example .env
# put your key in .env as RIOT_API_KEY=RGAPI-...

.venv/Scripts/python.exe -m uvicorn app.main:app --reload
```

```bash
# frontend, in a second terminal
cd frontend
pnpm install
pnpm dev
```

Open <http://localhost:5173>. The Vite dev server proxies `/api` to the backend, so
there is no CORS to configure while developing.

Check everything is wired up at <http://localhost:8000/api/health>, and browse the
API at <http://localhost:8000/docs>.

---

## What the development key can and cannot do

This is the single most important constraint on the project, so it is worth being
blunt about it.

A **development key** allows **20 requests per second and 100 per two minutes**, and
**expires every 24 hours**. The two-minute window is the one that binds: it works out
to 0.83 requests per second sustained.

| Feature | On a dev key | Notes |
| --- | --- | --- |
| Profile, rank, mastery | Works well | 3 calls cold, 0 warm |
| Match history | Works | Each *new* match is 1 call; cached forever after |
| Tier lists | Thin | Needs a corpus; ~3,000 matches/hour ceiling |
| Draft matchups | Very thin | Needs tens of thousands of games per patch |
| Live game / spectator | At risk | See below |

Nothing in the code changes when you get a production key. Set `APP_RATE_LIMITS` in
`.env` to whatever Riot grants you and the limiter adapts.

### Spectator-V5

Riot announced in **October 2025** that Spectator-V5 is being deactivated, to stop
third-party apps de-anonymising players. It is still live and still documented, with
no published shutdown date. Live-game lookup therefore sits behind
`ENABLE_SPECTATOR` and the draft assistant is manual-input-first, so its removal
costs a convenience rather than a feature.

---

## Collecting data for tier lists and draft

Tier lists and matchups are aggregates, so they need a corpus of matches first.

```bash
cd backend

# Walk the ladder collecting matches. Resumable: stop anytime, it saves progress.
.venv/Scripts/python.exe -m scripts.ingest crawl --target 500 --tier challenger

# See what you have
.venv/Scripts/python.exe -m scripts.ingest status

# Fetch per-minute timelines for matches already stored. One extra call each.
.venv/Scripts/python.exe -m scripts.ingest timelines --target 500

# Measure the median rank of the players in stored matches
.venv/Scripts/python.exe -m scripts.ingest lobbyranks --target 2000

# Snapshot ranked ladders for the leaderboards
.venv/Scripts/python.exe -m scripts.ingest ladders --platform euw1

# Build the rollups the tier list and draft assistant read
.venv/Scripts/python.exe -m scripts.ingest aggregate
```

`lobbyranks` costs far less than it looks. It is one Riot call per *player*,
not ten per match, and players repeat: the current corpus holds 1,695 matches
but only 2,830 distinct players, so the whole backfill is under an hour rather
than the 16,950 calls a naive count suggests. Be aware of what it measures,
though. Riot exposes no historical rank anywhere, so this is every player's rank
**on the day you run it**, not their rank when the game was played. The
measurement date is stored beside the number and shown in the UI for exactly
that reason.

`ladders` is optional: the leaderboard page snapshots a ladder itself the first
time somebody opens it. Run it to pre-warm one. Names are the interesting cost
there, because league-v4 returns none at all: a ladder in a region you have
crawled is almost entirely named for free from stored matches (99% of EUW
Challenger), and one you have not is named a page at a time as people browse.

`timelines` is what produces the laning score on match rows, the Laning tab, the
skill order, and the ordered build path. Without it the champion page falls back
to describing final inventories, which is why it says so when it does. The
command is resumable in the simplest way there is: "which matches lack a
timeline" is itself the cursor, so an interrupted run just picks up the rest.
Budget roughly **64 KB of database per match** (a ~4 KB extract of what the
features read, plus the raw payload gzipped) and one Riot call each.

The crawler snowballs: it seeds from a ranked ladder, pulls each player's recent
ranked games, and every match yields ten more players to walk.

**Expect thin results on a dev key.** 500 matches gives you a rough read on popular
champions and essentially nothing per-matchup. That is a data problem, not a code
problem. `min_games` on the tier list exists so you can see honestly how thin a slice
is rather than being shown noise.

---

## How it is put together

```
backend/
  app/
    riot/          Riot API client: routing, rate limiting, error translation
    db/            SQLAlchemy models and engine
    services/      players, matches, mastery, ingest, aggregate, draft,
                   item_taxonomy
    api/           FastAPI routes and response schemas
  scripts/ingest.py    Crawler, timeline and rank backfills, ladders, aggregation
  scripts/migrate.py   Additive SQLite migration (until Alembic)
  tests/               335 tests, no network required
frontend/
  src/lib/         Typed API client and formatters
  src/components/  Search, form strip, match row, rank card, champion picker,
                   play-style panel, champion build/rune/pair panels
  src/routes/      Home, Profile, Mastery, Tierlist, Champion, Draft
```

### Decisions worth knowing

**PUUID is the only identifier.** Riot removed `name` and `accountId` from
`summoner-v4` and deleted the by-name lookups; `league-v4` moved from
`by-summoner/{summonerId}` to `by-puuid`. Display names live only in `account-v1` as
`gameName#tagLine`. Most tutorials online are still written against the old shapes.

**Platform vs regional routing.** `summoner-v4`, `league-v4`, `champion-mastery-v4`
and `spectator-v5` use platform hosts (`euw1`, `kr`). `account-v1` and `match-v5` use
regional hosts (`americas`, `europe`, `asia`, `sea`). Mixing them up produces silent
404s. `app/riot/routing.py` holds the mapping, including that SEA shards must fall
back to `asia` for `account-v1`.

**The rate limiter is proactive.** It blocks locally before sending rather than
learning from 429s, because Riot tracks violations and suspends keys over them. It
enforces application limits from config and learns per-method limits from
`X-Method-Rate-Limit` on the first response.

**Matches are stored whole.** Each match keeps its full raw JSON next to the
normalised columns. Storage is cheap; the rate limit is not. Re-fetching 50,000
matches because a field was not normalised would take weeks.

**Tier lists rank by Wilson lower bound, not win rate.** A champion at 3-0 is not the
best in the game. Wilson asks what win rate the sample can actually defend, which
pushes thin samples down instead of letting them top the list. Tiers are percentile
bands rather than fixed win-rate thresholds, because win rates cluster near 50% and
"above 52%" means different things on different patches.

**Draft suggestions explain themselves.** Every suggestion returns its baseline, its
head-to-head record and sample size, and the mastery weighting. Matchup records are
shrunk toward the champion's own baseline in proportion to sample size, so a 4-game
75% matchup does not outrank a 400-game 53% one.

---

## Tests

```bash
cd backend
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m ruff check app scripts tests
```

71 tests, no network access needed: Riot is mocked at the transport layer, so
routing, rate limiting, retries, error translation, match normalisation and the cache
are all exercised against the real code paths. Several are regression tests pinning
bugs that only live traffic exposed (see "Things that bite" below).

```bash
cd frontend
pnpm build      # typecheck + production build
```

---

## Moving to Postgres

SQLite is the default so the project runs with nothing installed. To switch:

```bash
pip install asyncpg
# .env
DATABASE_URL=postgresql+asyncpg://user:pass@localhost/riftline
```

No schema changes. The aggregation SQL deliberately avoids two constructs that work
on SQLite and break on Postgres:

* `func.max(a, b)` is a scalar function in SQLite but an *aggregate* in Postgres.
* `CAST(boolean AS INTEGER)` is fine in SQLite and an outright error in Postgres
  ("cannot cast type boolean to integer"), which would break every win count.

Both are written as `CASE` expressions instead, and a test compiles the win-counting
SQL against the Postgres dialect to keep it that way.

There is no migration tool yet. `create_all` creates missing tables but never ALTERs an
existing one, so `python -m scripts.migrate` covers the gap: it adds new columns to
tables whose contents are expensive (`matches` is one Riot call per row) and drops the
derived rollups for `ingest aggregate` to rebuild. Add Alembic once the schema settles.

---

## Champion pages

Builds, runes, summoner spells, counters and synergies, at
`/champions/{id}`. All of it is computed from participant rows we already store,
so it costs **no additional Riot API calls**. Rebuild the rollups with
`python -m scripts.ingest aggregate`.

Two things are deliberately honest rather than impressive:

**Build order needs a timeline; without one you get the final inventory.**
Riot's match payload records the six item slots as they stood at the end, and the
slots carry no purchase order: across the corpus the same boots appear in slot 0
through slot 5 at roughly equal rates. So a slice with no timelines reports the
sets players *finished* with, and says so in `builds.basis = "final_inventory"`.
Run `scripts.ingest timelines` and the same field flips to `"purchase_order"`,
`builds.path` carries the first three completed items in the order they were
actually bought, and the caveat in the UI disappears with it. The two are shown
side by side on purpose: a path and a completed build can contain the same three
items, and only the order separates them.

**Rank bracket is crawl provenance; lobby rank is the measurement.** These are
two different fields making two different claims. `source_bracket` records which
ladder the crawler was seeded from, and the ten players in a Challenger-seeded
game are not all Challenger, so it is never described as a rank.
`lobby_rank_points` *is* measured, by `scripts.ingest lobbyranks`, but it is
measured late: Riot keeps no historical rank, so it is where those players sit
on the day you ran it. The date travels with the number everywhere it appears,
and the UI says which one it is rather than letting the two blur together.

It is a **median**, not a mean, and that is not pedantry. The rank scale is
ordinal with wildly unequal steps: one point separates Diamond I from Master and
six figures separate the apex tiers. Averaging over it reports nine Gold players
and one Challenger as "Diamond III", and a smurf in a low-elo game is exactly
what anybody looks at this number for. The median is a rank somebody in the
lobby actually holds, and one outlier cannot move it.

Counters come in two scopes. `LANE` is the opponent in your lane, which is what
"counters" usually means. `TEAM` is the champion against all five enemies, which
is what actually decides games and what the draft assistant was missing.

## Play style

`/api/summoner/{platform}/{name}/{tag}/analytics` returns role share, champion
class mix, a 24-hour activity histogram and per-champion aggregates. It reads
**stored matches only**, so it spends no Riot budget and can never be rate
limited. The trade is that it describes the games we have fetched rather than a
whole season, which `basis = "stored_matches"` states rather than implying.

---

## Things that bite

Notes from debugging this against the live API, all now covered by tests.

**Riot matches Riot IDs loosely.** Searching `Caps#EUW` returns the account that
displays as `Cäps#EUW`. Store what Riot returns and look it up by exact match and the
cache never hits, so every page view spends an account-v1 call. Names are folded
through NFKD with combining marks stripped before being used as a cache key.

**Riot's rate-limit counters can report a full window alongside a 200.** Live, an
`x-app-rate-limit-count: 100:120` arrived with a successful response. A limiter that
treats those unseen requests as having happened *now* concludes nothing frees for a
further two minutes and stalls itself. They are spread across the window instead.

**The wrong regional host returns `200 []`, not an error.** Ask `asia` for an OCE
player's matches and you get an empty list, which reads as "this player has no games".
`sea` is a valid match-v5 host but *not* an account-v1 host (403), which is why
`Platform` carries both `regional` and `account_region`.

**A match that fails to fetch must not end pagination.** `has_more` keys off the number
of ids Riot returned, not the number of matches that rendered.

---

## Not affiliated with Riot Games

Riftline isn't endorsed by Riot Games and doesn't reflect the views or opinions of
Riot Games or anyone officially involved in producing or managing League of Legends.
League of Legends and Riot Games are trademarks or registered trademarks of Riot
Games, Inc.

If you make this public, read Riot's developer policies first: production keys
require an application and approval, and there are rules about what you may display
and how you may monetise it.
