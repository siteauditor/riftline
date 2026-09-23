# Riftline

A League of Legends analytics site: summoner profiles and match history with a
per-game performance score, a champion mastery dashboard, live games, champion tier
lists and pages, ranked leaderboards, and a draft assistant.

Live at <https://www.rhasta.space>. FastAPI + SQLAlchemy on the backend,
React 19 + Vite + Tailwind v4 on the front, with Radix primitives (via shadcn/ui) for the controls.

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

**A web request never waits on the limiter for long.** The limiter is shared,
and when the two-minute window is spent (by traffic, or by the nightly ingest,
which runs on the same key) a request that needs a slot used to sit until one
freed: a leaderboard page was measured waiting 102 to 108 seconds, and
Cloudflare abandons an origin at 100. Each web request now has a waiting budget
(`RIOT_WAIT_BUDGET_SECONDS`, 40 by default). A call that could only go out past
it answers 429 with a `Retry-After` at once, which the page shows as a
countdown, while a ladder serves the snapshot it holds and the names it already
knows. The ingest CLI has no budget and still waits for the key.

### Spectator-V5

Riot announced in **October 2025** that Spectator-V5 is being deactivated, to stop
third-party apps de-anonymising players. It is still live and still documented, with
no published shutdown date. Live-game lookup therefore sits behind
`ENABLE_SPECTATOR` and the draft assistant is manual-input-first, so its removal
costs a convenience rather than a feature.

Everything the live page adds on top of the lobby is read from storage, so the
day spectator goes dark the page loses the roster and nothing else. The one
exception is resolving a finished game into its match, which spends at most
three Riot calls per match id however many people are watching it
(`LIVE_RESULT_COOLDOWN_SECONDS`, `LIVE_RESULT_MAX_ATTEMPTS`).

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

# Bring stored timelines up to the fields the newer features read
.venv/Scripts/python.exe -m scripts.ingest reextract

# Fit and grade the win-chance model, weigh every game's deaths, audit the score
.venv/Scripts/python.exe -m scripts.ingest winmodel
.venv/Scripts/python.exe -m scripts.ingest reviews
.venv/Scripts/python.exe -m scripts.ingest audit
```

Run them in that order: each stage works on what the earlier ones found.
Everything from `aggregate` on reads only the stored corpus and makes no Riot
calls, so it can be rerun as often as you like.

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
Each name is one `account-v1` call, and naming never spends the last 20 calls
of the key's two-minute window, which stay free for player searches. On a
development key that is at most 80 names every two minutes, so an open page
asks again on its own, at the moment the server says the key will have room.
A few ladder entries have no account behind them at all (two of the first 200
in EUW Bronze IV): Riot's 404 is remembered for a week and the row reads "No
Riot ID" instead of waiting for a name that is not coming.

`timelines` is what produces the laning score on match rows, the Laning tab, the
skill order, and the ordered build path. Without it the champion page falls back
to describing final inventories, which is why it says so when it does. The
command is resumable in the simplest way there is: "which matches lack a
timeline" is itself the cursor, so an interrupted run just picks up the rest.
Budget roughly **73 KB of database per match** (a ~13 KB extract of what the
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
pushes thin samples down instead of letting them top the list. The page shows the raw
win rate with the whole interval drawn under it, because the lower bound on its own
put most S tiers below 50% (Kalista S at 48.3% on 16.18) and read as losing picks.
Tiers are percentile bands rather than fixed win-rate thresholds, because win rates
cluster near 50% and "above 52%" means different things on different patches, and
they are banded within each role, so S means the top of that role even when all
roles are listed together.

**A letter is a place, not a measured gap, and the page says so.** Letters are
banded among the champions with 20 or more games in the role, whatever the page's
"Min games" shows: banded inside the display floor, 81 of 175 rows changed letter at
5 games instead of 20 and disagreed with the champion page. On production's 16.18,
only 8 of 247 rows had a range wholly above 50% and 8 wholly below, while the letters
gave 28 an S, and the true spread of champion win rates came to about 1.6 points, so
a record needs roughly 950 games before it is half signal. The tier list states those
counts above the rows. Ranking another way does not fix it: ordered by the low end, by
a shrunk estimate or by raw rate, the top tenth of 16.17 won 52% on 16.18 and the
bottom tenth 48%, whichever rule chose them.

The tier list also says how its games were ranked: each lobby's measured median
rank, bucketed, with Master and above merged because apex cutoffs are live and per
region. On 16.18, 95% were Master+ lobbies. That replaced the "Crawled from" filter
there, which recorded where the crawler started rather than a rank, and filtered
almost nothing (Challenger was 1,403 of 1,593 games).

**The look is broadcast black, and it was researched rather than invented.**
Riot's own League and Valorant sites and LoL Esports all share one language: a
near-black ground, sharp-cornered rectangles with hairline outlines, condensed
upper-case display type, and the game's art carrying the colour. Blitz and
Lolalytics do the rounded version and let dense grids of Riot's item and rune
icons be the texture. This site used to draw flat panels on a lit teal ground
with the art in 48px thumbnails, which read as a spreadsheet. Now every page
header runs the subject's own splash art behind the type (`ArtHeader`), ranks
show Riot's crests (`lib/rankArt.ts`), the corner radius is zero everywhere
through one token, and colour has three sources only: hextech teal for the
interface, gold for what was earned, and the rank being described.

**The mastery page shows the shape of a pool, not a wall of squares.** Riot's
2024 rework removed the level cap, so levels now run past 200: measured on three
real accounts, the tops were 232, 152 and 45, while the old page's colour ramp
stopped at "10 or above" and put 41 of one player's 166 champions in a single
colour. The grid is now banded by share of lifetime points, because three to
eleven champions hold the first half of a career and a hundred or more sit in
the last fifteen percent. Colour still means level, rebanded to 1-4, 5-9, 10-24,
25-49 and 50 and up. Champions we hold stored games for carry a mark and show
their win rate and Riftline average when opened, which is 10 of 166 champions on
one account but 5 of the 8 in its core. `chest_granted` is gone from the
response: Riot removed chests in 2024 and it was false on every entry we have
ever seen.

**The live game page is about the players, not only the champions.** Every
identified player in a lobby carries what the corpus holds about them: their W-L
and average Riftline score with the sample stated, their usual role and whether
this game is off it, and their record on the champion they are on. A median of 9
of 10 players in a stored lobby clear the three game floor. A lane record falls
back in a stated order, this patch, then the previous one pooled in, then games
where both champions were in the lobby rather than in the same lane, and the bar
says which, because only 26% of lanes have a record on the newest patch alone.
The page also says who has met before, as counts of stored games rather than a
percentage, and it never predicts the game: about a third of every lobby hides
its identity, which is not a third missing at random, and a test keeps any
"win probability" off the wire. Zero of 31 production lookups found anybody in a
game, so the idle state carries their last stored game, their form and what they
have been playing rather than an empty box.

**Draft suggestions are ranked by what the records support, and only the records that
measurably repeat are scored.** Each champion starts from its own win rate in the role,
shown as the range its sample supports, and the list is ranked by the low end of that
range, plus mastery, as the tier list ranks. A record then moves it by a posterior
reading (`app/services/evidence.py`): the context's effect has a prior centred on zero
worth `LANE_STRENGTH` games, each patch of the record is read against the champion's
own rate on that patch, and wins and losses move a pick by the same amount. A record is
called favoured or unfavoured only when that posterior is 90% on one side.

The strengths are measured, not chosen, and `python -m scripts.ingest draftpriors`
measures them again. On 2026-09-24 a lane record's deviation from the champion's own
rate repeated from 16.17 to 16.18 (r = +0.23 over 112 pairs with five or more games,
which puts the prior between 10 and 146 games; 100 is used). A time split agrees on the
direction and asks for more: read at 100 games, the 16.17 records predict 16.18's with a
slope of 1.85, which points to a strength nearer 50. 100 stays, as the careful end, until
a larger corpus narrows it. Records against the other
enemies and beside allies did not repeat at all (every interval spanning zero), so they
are returned and shown with their samples but do not move the list. The old reading
measured records against the champion's Wilson lower bound and gave a 2-0 lane record
1.2 points: Ekko took the board's biggest boost from one 7-1 record over eight games.
Over 150 boards rebuilt from stored games the new ranking keeps the same first pick
three times in four. Lane records pool the patch before when it is close
(`aggregate.poolable_patches`), which doubles the lane pairs with ten or more games.

The Riot ID that weighs mastery costs nothing until it is committed, a 404 is
remembered for ten minutes, and the lookup has a two-second budget after which the
stored mastery is used; the response says which of those happened.

**The team damage mix is shown, not scored.** Each champion's damage to champions by
type is lifted from the stored payloads, so it costs no Riot call, and ten games make a
profile: two separate ten-game samples of the same champion in the same role differ by
1.2 points of physical share at the median. A profile is read in the champion's role
when it has the games there, because a few champions change type with the role (Twisted
Fate dealt 12% physical damage in mid and 56% in bot). A side is its champions' average
damage summed, so a support counts less than a carry, and it is called one-sided at 70%
of one type, which 3.7% of real teams reach. On 2026-09-24 the 89 teams whose champions
usually dealt 70 to 80% of one type won 39.3% (a range of 29.8% to 49.7%): a hint, too
thin to score, which `draftpriors` reports again as the corpus grows.

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

It runs at <https://www.rhasta.space> on a shared VPS. A push to `main` runs
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

Matchups are ordered by the **middle** of the Wilson interval, which is the record
pulled toward 50% by about four games, and read either way (hardest or easiest
first). Both ends were tried and both failed on the live Jinx page: by the bottom,
Viktor at 3-3 was the 4th hardest lane, because a six-game range reaches low
whatever the record; by the top, Yunara at 10-9 (52.6%) came 2nd, because more
games made its range the narrowest. Every matchup above the floor is returned,
not the first 15, so any opponent can be searched for.

Every list keeps its filters, sort, search and page in the URL, so a reload, a
shared link or the back button returns the same view (the tier list used to fall
back to All roles on the way back from a champion). Filter changes replace the
history entry and page changes add one, so back steps through pages but not
through every tweak. Match history filters by champion from **stored games
only**: Riot's history endpoint filters by queue and time, never by champion, so
the list says how many games it holds and costs no Riot call.

### The champion, not just the numbers

The page has two groups of tabs. **The numbers** (Build, Runes, Laning,
Counters, Synergies, Players) are a slice of our games. **The champion** (Story,
Abilities, Skins) is who the champion is, which no sample size changes, and it
comes from `GET /api/champions/{id}/profile`: its own endpoint, because the
detail endpoint is a 404 on any patch where the champion has no games (one
champion on 16.17, and every new release on its first day), and a story does
not depend on a sample. On such a patch the page opens on the story instead of
an error.

- **Story and abilities** come from Data Dragon's `championFull.json`, 0.41 MB
  gzipped for all 173 champions, fetched on the static refresh as an optional
  source. Without it a page loses only the long lore, the tips and the ability
  names: the ratings and base stats come from `champion.json`, which is
  required. Ability text is `description`, never `tooltip` (the tooltip is
  written against `{{ }}` placeholders only the client resolves), with Riot's
  markup stripped server side so the page never renders Riot's HTML. A cost is
  printed only where its template resolves; 37 of 692 are withheld rather than
  half filled.
- **Data Dragon ships `attackdamageperlevel: 0` for all 173 champions** on
  16.18.1. A growth field that is zero across the whole roster is treated as
  unpublished, so level 18 attack damage reads "not published" rather than
  equal to level 1. Real zeros are never roster wide (28 champions have no mana).
- **Skins come from Community Dragon, not Data Dragon**, because Data Dragon
  lists every chroma as a skin: Ahri has 95 "skins" there and 21 real ones, and
  74 of the 95 have no art (their tile URL is a 404). The file was already
  downloaded for the live tab's chroma map; the catalogue is the rest of it.
- **The skill figures** beside each ability (taken at level 1, maxed first) are
  our own, from the `skill_first` and `skill_priority` facets, sliced like the
  rest of the numbers.
- **Players** ranks everyone with 5 or more Summoner's Rift games on the
  champion (3 of them scored) by average Riftline score, over every game we
  hold rather than the patch slice: who is good on a champion is not a patch
  question, and the slice costs a third of the sample (399 qualifying pairs
  against 621). The board is withheld below 3 players, and the record sits
  beside the score because a score rates play, not results.
- **The change since last patch** is drawn only where this patch's and the
  last one's 95% Wilson intervals stop overlapping. From 16.17 to 16.18, 293 of
  760 win rates moved 20 points or more and 2 of those moves passed.

**Skin popularity cannot be backfilled.** No stored match or timeline carries a
skin: not one of a match payload's 156 participant keys mentions one. The only
place Riot says what anyone wears is spectator's `lastSelectedSkinIndex`, so
every live lookup records its lobby in `skin_sightings`, once the game is under
way (a skin can change in champion select), once per player however often the
page polls, with chromas counted as their parent skin and no puuid stored. Per
skin counts appear on a champion at 20 sightings, and the home page's "Most
worn skins" appears once 3 skins have 5 sightings each. Until then both say
nothing, which is the honest state of a table that started empty.

## The item guide

`/items` lists everything sold on Summoner's Rift in sections (finished items,
boots, starters, support items, components, consumables, trinkets), and
`/items/{id}` is a page per item: what it gives, what it is built from and
into, when it is bought, who buys it, and how it does. Every item icon on the
site links to its page. `GET /api/items` and `GET /api/items/{id}` serve it and
make no Riot calls.

What an item **is** comes from Riot's item file, with three corrections:

- **Other modes' copies are left out.** Riot marks copies from other modes
  (ids 322065 and up) as Summoner's Rift items: 33 of the 138 "finished items"
  the build rules found never appear in a ranked game. Every real one has an id
  under 10,000.
- **Stats are read from the description**, because the file's `stats` object
  understates 98 of 138 finished items: it has no ability haste, no lethality
  and no crit damage. Passives and actives are the description's named blocks,
  with Riot's markup stripped server side; a heading is a tag that opens a
  line, because Riot also wraps keywords such as "Glory" mid-sentence.
- **Grown items count as the item that was bought.** Seraph's Embrace,
  Muramana and Fimbulwinter cannot be bought, so the build rules filed them as
  "other" and the champion Build tab dropped them: Muramana from 204 of 241
  Ezreal games. `ItemTaxonomy.canonical` follows Riot's own `specialRecipe` link
  back to the bought item, so builds, the guide and every count use it.

How an item is **used** is measured nightly by `aggregate` into `item_stats` and
`item_champion_stats`, on three separate bases: held at the end of a game
(final inventories), bought (first purchase in a timeline's purchase order,
with its minute), and, for finished items, **against the same slot**. That last
one exists because a raw item win rate mostly measures how late an item is
bought: win rate rises from 28% for players who finished no items to 62% for
six. So every purchase of an item as a player's k-th finished item is scored
against the same champion's k-th items in the slice, and the figure is the
average of (won minus that baseline). Zhonya's Hourglass, 55% raw, is within
two points of zero against its slot. Figures are withheld below 30 purchases in
a slot and 20 on one champion.

Purchase times need `build_times`, a column beside `build_order` written with
every timeline and filled for older ones by `scripts.ingest buytimes`, which
reads the raw timelines already on disk. The nightly job runs it before
`aggregate`.

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

**How it is measured.** Seven components: kill participation, share of the team's
damage to champions, damage to champions per 1,000 gold, gold per minute, share of
the game spent alive, objectives (towers, plates and epic monsters) and vision
score per minute. Each becomes a percentile within the player's own queue and role
across the matches we hold, and the seven are combined with published per-role
weights (`WEIGHTS` in
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
`score --rescore`, which recomputes every score made under the old weights. Every
deploy runs it, so a weights change applies on release rather than at 03:20.

**Version 2: damage per gold.** Kill participation and damage share are both
shares of a team total, so a player on a team that does little looks good on them
for doing little more. Damage per gold is the player's own. It took its weight from
damage share, the component it overlaps. On the same 1,849 ranked games, against
version 1: AUC 0.731 against 0.720, the lobby's top scorer on the winning team
88.3% against 88.0%, the bottom scorer on the losing team 84.0% against 83.6%, and
every role's AUC higher (top 0.684 to 0.700, bottom 0.738 to 0.749). One number did
not move up: bottom's winners averaged 5.885 against 5.887, a gap far inside the
noise of that mean. Spreading the weight across four components instead lowered
the top-scorer figure to 87.6%, so that table was not shipped.

**The audit** (`scripts.ingest audit`, published on `/method`) grades the score in
public, per role: winners' and losers' means, the AUC, win rate by score tenth,
each component's own AUC, and a logistic fit of winning on the component
percentiles set beside the hand-set weights. The fit is not adopted: it puts kill
participation, damage share and vision at nothing and objectives, economy and
survival at nearly everything, because winners take objectives and stay alive
partly because they are already winning. A fit to wins rewards being on the
winning team; it is a check on the weights, not a replacement for them.

## A game's story

`/match/{id}` opens with each side's chance to win, minute by minute, the three
moments that decided the game, and every player's deaths and takedowns weighed
(`/api/matches/{id}/story`). No competitor we checked explains which moments won
or lost a game, and none publishes how its numbers are made; this page links to
`/method`, which does.

**The win-chance model** (`app/services/winchance.py`) is a logistic regression on
the game state, blue minus red: gold, kills, towers, inhibitors down, dragons,
soul, the Elder and Baron buffs, Voidgrubs, Herald, Atakhan and levels. Each
feature has a weight at minute 0 and at minute 40 with a straight line between, so
a gold lead can matter differently at 8 and at 35 minutes without phase models
jumping at a boundary. No weight may count against the side holding the lead:
fitted freely it read a tower at 10 minutes as -2.9 points and a Baron buff at 20
as -4.1, harmless to the curve and absurd as the effect of an event. It is fitted
nightly on stored ranked solo timelines (`scripts.ingest winmodel`, about two
seconds) and graded on five folds split by game, never by minute, because the
minutes of one game are near copies. On 1,678 local games, held out: 71.9% of
winners called, Brier 0.179 against 0.250 for always guessing blue's win rate,
calibration error 0.8 points, 61.7% in the first ten minutes and 79.8% from 20
to 30. Game pages show it only while it removes 10% of the guess's error and the
calibration error stays under 5 points; below that the curve is withheld, the way
a thin sample is.

**Moments.** Events closer than 15 seconds are one sequence, and a sequence is
measured on the curve from just before it to a minute after its last event. The
model credits a Baron or a tower mostly through the gold and buildings that follow
(a Baron buff alone is worth 1 to 3 points), so adding up events' own effects made
the fights that decided games look small. The biggest three, described from their
events: "Red won a fight 4 for 1 and took Baron, -35.8".

**The timeline on demand.** Profile games get their timeline at the nightly run.
Opening a story without one fetches it: one Riot call, once, under the request's
wait budget. It never takes the key's last 20 calls in a two-minute window
(`SEARCH_RESERVE`, shared with ladder naming): those are for Riot ID searches, and
opening stories one after another, or a bot doing it, would otherwise starve them.
On a busy key the section says so and offers a retry.

## The death review

Every death is traded or not, every takedown converted or not, and each carries
the win chance it cost or gained (`app/services/reviews.py`).

- **Traded**: the dying player's team gains a kill, an epic monster, a tower, an
  inhibitor or a plate within 60 seconds. It follows PandaSkill's "worthless
  death", which a 2025 study of 37,388 professional games found among the measures
  that best separated players. On 1,678 local games 74.5% of deaths were traded.
- **Converted**: the player's team takes an epic monster or a building within 60
  seconds of a takedown. 44.2% were.
- **Cost and gain**: the model's reading of the event itself, the kill's bounty
  included. Maymin (2020) found kills and deaths weighed this way track team
  results far more closely than a plain K/D.
- **Contested objective**: an epic monster credited to players from both teams.

`scripts.ingest reviews` weighs every stored game the current model version has
not, into `participant_reviews`. A profile places each player's four rates
(untraded deaths, win chance lost, converted takedowns, win chance gained) against
the same role as a percentile per game, averaged, and only from 10 reviewed games
in that role.

## Lane labels

A lane's share of the pair's gold, experience and CS at 14 minutes becomes won,
even, lost, won big or lost big by how far it sits from even against the same role
(`app/services/lanes.py`): the closest 30% are even and the widest 10% big, the
split STRATZ uses for Dota. On our corpus that lands about 0.02 and 0.09 from even.
A role with fewer than 200 measured lanes gets no labels. The breakpoints are
rebuilt with the score.

## Groups

`/groups` makes a group of up to 20 players (a team, a Clash roster, friends)
and `/g/{slug}` shows them side by side: official rank, record, KDA, the
Riftline score and its seven components, the death review, lane labels, recent
form, and the games they played on the same team. Every queue together, or one
at a time: ranked solo, flex, normal, Swiftplay, ARAM, Arena.

**No login.** A group is two links. The view link (`/g/{slug}`, ten random
characters) shows it to anyone who has it. The edit link adds `#key=...`, a
192-bit random key: the part after `#` never reaches a server, so it cannot
land in an access log, and the page moves it into `localStorage` and out of the
address bar at once, so an address copied from the bar is the view link. The
key travels as an `X-Group-Key` header; the database holds only its SHA-256.
A new edit link can be made at any time, and the old one stops working.
"Your groups" is that browser's memory of both. Group pages send `noindex`.

**Riot's rules decide the order.** Riot does not allow alternatives to its
ranked ladder, so the default order is the official rank and LP, every other
figure is a column to sort by, and nothing combines them into one rating.

**Filling a group** (`app/services/groups.py`). A new player costs about one
call per game of history, so twenty strangers are thousands of calls: hours on
a development key. The page asks for a bounded pass (`POST
/api/groups/{slug}/warm`, five seconds at most) and asks again when it ends,
and the nightly `groups` stage does the rest. Every pass stops at the same
reserve of 20 calls that ladder naming and game stories leave for searches.
A pass reads ranks first (the table's default order), then new games, then one
chunk of older history per player in turn, so one long history cannot starve
the rest. Timelines are fetched only for each player's newest 20 ranked games,
which is what the death review and the lane labels read.

History is paged backwards under a fixed `endTime` rather than by offset
alone: match-v5's offsets count from the newest game, so a game finished
between two pages shifts every offset by one. `GROUP_HISTORY_CAP` (300 by
default) is how far back each player is read. Reading the table
(`app/services/group_table.py`) never calls Riot, and every figure needs 5
games in the chosen queues before it is shown, with the count beside it.

**Abuse.** Without accounts, the limits are per visitor address, per hour: 10
new groups and 60 players added (`GROUP_CREATES_PER_HOUR`,
`GROUP_ADDS_PER_HOUR`). The address is Cloudflare's `CF-Connecting-IP`, not
`X-Forwarded-For`: uvicorn trusts every proxy here and so takes that header's
first entry, which the visitor writes. Empty groups are removed after a week.

## Search engines

Every page is served as real HTML with its own title, description, canonical
link, social card and, where it means something, JSON-LD, and the app hydrates
over it. Not because Google cannot render a client-side app (it can, and the
research behind this measured it rendering every page it fetched), but because
Bing and the social unfurlers do not, Google caches fetched resources for up to
a month so a client-rendered tier list can be indexed a patch stale, and a site
whose every URL shared one title had nothing to rank on.

**One page per path, prerendered.** `frontend/prerender/run.mjs` asks the API
for the manifest of pages (`GET /api/meta/pages`, `app/services/seo.py`),
renders each through the same route table and components the browser uses
(`frontend/src/routes.tsx`, `frontend/src/entry-server.tsx`), and writes one
file per path. The queries a page needs are declared once in
`frontend/src/lib/queries.ts`, prefetched into a QueryClient on the server and
dehydrated into the page, so the browser hydrates from the same cache rather
than fetching everything again. The head is decided by pure functions in
`frontend/src/lib/seo.ts`, written by the prerenderer and updated in place by
the client (`frontend/src/lib/head.ts`), so the document never holds two
titles and the canonical a crawler read is the one the app keeps. It runs at
every deploy and every night; on this corpus, about 420 pages in 13 seconds.

**Indexable means prerendered.** nginx serves the prerendered file when one
exists and the app shell otherwise, and the shell carries `X-Robots-Tag:
noindex`. So a URL that has no page (a typo, a profile nobody has opened)
never enters an index as an empty document, and there is no user-agent branch
anywhere: everyone gets the same HTML. A page is written for every champion
and item, but marked `noindex, follow` when the corpus is thin behind it:
`TIER_MIN_GAMES` (20) in some role for a champion, 30 buyers for an item,
measured on a patch with at least 500 ranked games so pages do not flip to
noindex on patch day. The sitemap (`/sitemap.xml`, proxied to `/api/meta/
sitemap.xml`) lists the indexable pages from the same manifest, with
`lastmod` only where the data behind a page carries a time.

**Profiles are allowlisted, and rendered from storage alone.** A player's
page is prerendered once they have `MIN_SCORED_FOR_PROFILE` (10) scored games
in storage and a Riot ID we know, which is when the page has a score
breakdown to show and not only the rank and games every other site has. The
prerenderer asks the summoner routes with `?source=stored`: the player row
as the last visit left it, the ranks as last read, the games we hold, and
not one Riot call, so a thousand profile pages cost the key nothing. The
page hydrates from those answers and its live queries then replace them, so
a visitor gets Riot's fresher rank a moment later while a crawler gets a
complete page. The file is the fallback, though, not what is served: a
stored rank moves only when someone opens the page, so a file's title said
Bronze I in link previews for a day after the player reached Silver IV. A
profile that has a file is therefore rendered on request by
`frontend/prerender/live.mjs`, the same render with the header's profile
asked live (within the API's five-minute league cache). That costs a Riot
call only on a cold cache, gets three seconds and at most two at a time, and
past either renders from storage; nginx serves the file whenever the
renderer cannot answer. A profile below the floor, or one nobody has looked up by
name, reaches the shell and stays out of the index; it still works. Match
pages stay out too (a third have no timeline, so the page would lack its
main content), and group pages are private by design.

**Slugs.** Champions and items are addressed by name: `/champions/aatrox`,
`/items/blade-of-the-ruined-king`. A champion slug is its Data Dragon key
lowercased (`kaisa`, `leesin`, `ksante`), with Wukong the one override; an
item slug is its name, with the id appended where two items share one. Ids
keep working forever and redirect to the slug in the browser.

**The four explainers** at `/method/score`, `/method/win-chance`,
`/method/death-review` and `/method/lane-labels` are the pages competitors
cannot copy from the same Riot API: each says how a number is made, what it
was measured against and where it fails, with the nightly figures set into the
sentences. Champion and item pages carry a paragraph built from their own
numbers, so a reader who does not know the game, and anything that reads the
page without clicking a tab, gets the table in sentences.

To check a prerender by hand without Docker: `pnpm build`, then `pnpm
prerender --api http://127.0.0.1:8000 --out /tmp/pages --build-id local`, then
`node prerender/serve.mjs --pages /tmp/pages/local` and open a page: it serves
the files in nginx's `try_files` order.

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
