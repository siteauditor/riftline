# Riftline

A League of Legends analytics site: summoner profiles and match history with a
per-game performance score, a champion mastery dashboard, live games, champion tier
lists and pages, ranked leaderboards, and a draft assistant.

Live at <https://riftline.rhasta.space>. FastAPI + SQLAlchemy on the backend,
React + Vite + Tailwind on the front.

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

# Score every stored lobby: the Riftline score, placements and badges
.venv/Scripts/python.exe -m scripts.ingest score
```

Run them in that order: each stage works on what the earlier ones found.
`aggregate` and `score` read only the stored corpus and make no Riot calls, so they
can be rerun as often as you like.

`lobbyranks` costs far less than it looks. It is one Riot call per *player*,
not ten per match, and players repeat: measured on 2026-09-19, the corpus held
2,591 matches but only 5,822 distinct players, so a backfill from scratch is 5,822
calls, about two hours on a development key, rather than the 25,910 (over eight
hours) that a naive count suggests. Be aware of what it measures,
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
    services/      players, matches, ranks, live, ladders, ingest, timelines,
                   aggregate, scores, profile_stats, suggest, highlights, draft,
                   item_taxonomy, static_data
    api/           FastAPI routes and response schemas
  scripts/ingest.py    Crawler, timeline and rank backfills, ladders, aggregation,
                       scoring
  scripts/migrate.py   Additive SQLite migration (until Alembic)
  tests/               No network required
frontend/
  src/lib/         Typed API client and formatters
  src/components/  Search, form strip, match row and scoreboard, rank card,
                   strengths panel, champion picker, play-style panel, champion
                   build/rune/pair panels
  src/routes/      Home, Profile, PlayerChampions, Mastery, LiveGame, Match,
                   Tierlist, Champion, Draft, Leaderboard, NotFound
deploy/            Production deploy entry points, systemd units, firewall
docs/deploy.md     How production runs, and how to operate it
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
back to `asia` for `account-v1`. A Riot ID resolves across a whole region, but the
account itself lives on one platform, so the platform calls go through
`PlayerService.effective_platform()`, which reads that platform from the prefix of
the account's latest match id (see "Things that bite").

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

No network access needed: Riot is mocked at the transport layer, so
routing, rate limiting, retries, error translation, match normalisation and the cache
are all exercised against the real code paths. Several are regression tests pinning
bugs that only live traffic exposed (see "Things that bite" below).

```bash
cd frontend
pnpm build      # typecheck + production build
pnpm lint       # oxlint
```

CI runs all of the above, inside the images that get deployed, on every push and
pull request.

---

## Running it in production

It runs at <https://riftline.rhasta.space> on a shared VPS. A push to `main` runs
the tests on GitHub-hosted runners and then deploys that exact commit over SSH.
There is no self-hosted runner, because the repository is public and a pull request
could otherwise run code on the server. The corpus lives in a Docker volume and
grows nightly, and the development key is rotated by hand every 24 hours.

`docs/deploy.md` is the runbook: how the site fits on the shared box, first-time
setup, rotating the key, the nightly pipeline, CI/CD and the firewall.

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

The same endpoint feeds the profile's other stored-data views:

- **How they play**: per role, the average score and placement, MVP and ACE
  counts, and the six score components averaged, strongest first. Withheld below
  10 scored games in a role (`MIN_SCORED_FOR_PROFILE`), where one game moves an
  average by ten points.
- **The Champions tab**: every champion held, with win rate, KDA, CS and damage
  per minute, average score and gold lead at 14. Each average carries its own
  count, because scores and timelines do not cover every game.

The profile header also shows the player's **ladder position** ("#355 EUW"),
read from stored apex ladder snapshots with no Riot call, and hidden when the
snapshot is over 48 hours old or the player has changed tier since. The nightly
job refreshes the apex ladders for `LADDER_PLATFORMS` so it stays current.

**Rank history.** Riot keeps none, so an LP graph can only come from readings
we take. Every rank fetch that finds a change writes a row to `rank_history`
(and a first reading for a player with none), so the graph starts on the day a
player is first seen and fills in from there. The profile's **Update** button
re-asks Riot, but only once the cached answer is a minute old
(`REFRESH_FLOOR_SECONDS`): before that floor, `?refresh=true` skipped every
cache and one public URL could spend the key's budget.

## The Riftline score

Every player in a stored lobby gets a score from 0 to 10 for that game, a placement
from 1 to 10 in the lobby, and badges. The match row shows the score, the placement
and up to two badges; expanding it opens the scoreboard for all ten players
(`/api/matches/{match_id}`). All of it is computed from stored matches, so it costs
no Riot calls.

A game is scored the moment it is fetched, in the same request that stores it.
It used to wait for the nightly run, so a player's newest games were exactly the
ones with no score: 19 of 20 on one Grandmaster profile on 2026-09-19. The Lane
lead badge needs the timeline, which arrives later, so storing a timeline sends
an already-scored lobby back through the next scoring pass.

**How it is measured.** Six components: kill participation, share of the team's
damage to champions, gold per minute, share of the game spent alive, objectives
(towers, plates and epic monsters) and vision score per minute. Each becomes a
percentile within the player's own queue and role across the matches we hold, and
the six are combined with published per-role weights (`WEIGHTS` in
`app/services/scores.py`, shown in the UI under "How the Riftline score is
measured"). Percentiles rather than z-scores, because damage and gold have long
tails and one stomp should not dominate a distribution. Role-relative, so a support
is not judged on farm, and the ten scores in a lobby share one scale, which is what
makes a placement mean anything.

**When it is withheld.** A lobby without ten players in lane roles (ARAM, Arena), a
remake, or a queue and role with fewer than 200 games in the corpus gets no score.
The row shows a dash and the reason, never a guess.

**Whether it measures anything.** On the live corpus (2,440 scored lobbies,
2026-09-19): winners average 5.75 and losers 4.35, the top scorer in a lobby is on
the winning team 87.7% of the time, and the lowest scorer is on the losing team
83.0% of the time. Every role averages 5.05, which is the check that a support and a
mid laner are being measured on the same scale. It is our number, not Riot's, and
the scoreboard says so.

Badges, rarest first. The last column is how often each fired per game when the
thresholds were set, and the thresholds were swept against the corpus rather than
picked.

| Badge | Rule | Per game |
| --- | --- | --- |
| Steal | Stole a dragon, herald or baron from the enemy | 0.14 |
| Deathless | Finished a game of 15 minutes or more without dying | 0.29 |
| Frontline | Took the largest share of the team's damage, and at least 30% of it | 0.39 |
| Lifeline | Most healing and shielding that landed on allies in the lobby, and at least 5,000 | 0.52 |
| Lane lead | Biggest gold lead at 14 minutes in the lobby, and at least 2,000 gold | 0.58 |
| MVP | Highest Riftline score on the winning team | 1.00 |
| ACE | Highest Riftline score on the losing team | 1.00 |
| Damage carry | Largest share of the team's damage to champions, and at least 30% of it | 1.00 |
| Duelist | Three or more solo kills | 1.41 |

Frontline and Lifeline are there on purpose. A tank who soaks a third of the team's
damage and an enchanter who shields thousands both look mediocre by KDA, which is
exactly what the usual badges miss.

`scripts.ingest score` scores new lobbies and `--rebuild-distributions` re-measures
the percentiles. Changing a weight means bumping `WEIGHTS_VERSION` and running
`score --rescore`, which recomputes every score made under the old weights.

## The home page and search

Nothing on the home page calls Riot. The best pick in each role comes from the
tier list's own rows. The best game in each role over the last seven days
(`/api/highlights/best-games`) reads the stored scores and shows one game per
player; each game opens on its own page at `/match/{match_id}`, because a
week-old game is usually not in the player's latest twenty. One per role, not
the top five overall, because the overall top is all carries: on 2026-09-19 the
eight highest scores of the week were all top, mid and bot laners.

The search box suggests Riot IDs as you type (`/api/players/suggest`), **only
from players already stored**. Asking Riot would cost an account-v1 call per
keystroke on a budget of 100 per two minutes. Suggestions come from an
in-process index of every named player, not from the `search_name` cache key:
that column is left empty on rows built from match data, since a name read
from an old game may be stale and must never answer a Riot ID lookup. A
suggestion only fills in the field, and the profile lookup still goes through
Riot. The last region used and the profiles recently opened stay in the
browser's `localStorage` and are never sent anywhere.

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

**A Riot ID resolves across a region; the account lives on one platform.** An OCE
Riot ID resolves through `sea` and its matches load, while the account itself is on
SG2. Measured on one such account: on `oc1`, summoner-v4 says 404, league-v4 returns
no entries and champion-mastery-v4 returns no champions; on `sg2`, the same account
is Bronze III with 100 champions. Only the 404 admits anything is wrong. The other
two answer 200 with nothing, which rendered a ranked player with a deep champion
pool as unranked and new. So the platform calls ask the platform the account's
latest match was played on, and every per-platform cache records which platform it
was filled from, so an empty answer from the wrong one is never served for the
right one.

**PH2 and TH2 no longer exist.** Riot folded both into SG2, and
`ph2.api.riotgames.com` and `th2.api.riotgames.com` no longer resolve. Listed as
platforms, they put a TH choice on the leaderboard that answered 502 while the page
said Riot was down. They are aliases for `sg2` now, so old links and searches still
land where those accounts live.

---

## Not affiliated with Riot Games

Riftline isn't endorsed by Riot Games and doesn't reflect the views or opinions of
Riot Games or anyone officially involved in producing or managing League of Legends.
League of Legends and Riot Games are trademarks or registered trademarks of Riot
Games, Inc.

If you run your own copy, read Riot's developer policies first: production keys
require an application and approval, and there are rules about what you may display
and how you may monetise it.
