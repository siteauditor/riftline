# Feature gap analysis: op.gg, masterychart.com, itero.gg

Researched live on 2026-09-17 by walking each site. This is what they actually
ship, what we ship, and what it would cost us to close the distance.

**The headline finding:** our gap is not mostly *features*. It is three things,
in order of importance:

1. **Derived metrics we never compute**, above all the laning phase score. Both
   op.gg and itero build their whole identity on it, and it comes from the match
   timeline, which we do not fetch.
2. **Aggregations of data we already hold and throw away.** We store every
   participant's items, runes and summoner spells and then render none of it as
   a build guide. This costs zero extra Riot calls.
3. **Scale.** op.gg's tier list runs on 11,625,222 games refreshed every ~11
   minutes. Ours runs on 119. No amount of code fixes that.

---

## 1. op.gg

The biggest by far. Product surface: web, desktop app, mobile (iOS/Android),
streamer overlay, duo finder, esports, 20+ languages.

LoL nav: Home, Champions, Game modes, Leaderboards, Pro spectate, Stats,
Multi-search, Information, Lessons, My page.

### 1.1 Summoner profile

Header carries more than ours: profile icon with level, Riot ID, region,
**ladder position ("Ladder Rank 1 (0% of top)")**, Riot account linking (RSO),
a manual **Update** button, a **Tier graph** (LP over time), and a
"last updated N minutes ago" stamp.

Tabs: **Summary | Style | Champions | Mastery | Live game | Teamfight Tactics**.

Left rail:
- Rank cards with **tier emblem art**, LP, W/L, win rate, plus peak rank badged
  "Top tier".
- **Season history table**: S2023 S1 Diamond 2, S2024 S1 Grandmaster, S2024 S2/S3
  Challenger, S2025 Challenger, each with final LP.
- **Play style panel**: role share as percentages across all five roles
  (Top 9% / Jungle 4% / Mid 73% / Bot 8% / Support 6%) and **preferred classes**
  (Mage 63%, Marksman 13%, Fighter 11%).
- **Activity time overview**: a 24-hour grid highlighting the hours you play.
- Season aggregate: KDA, CS/min, total games, win rate, per queue.

Main column:
- Recent-20 summary: W/L donut, average K/D/A, KDA ratio, kill participation,
  per-champion mini-cards, and a **preferred-role bar chart**.
- **AI prompt chips**: "Analyze my recent matches", "What is my skill level?",
  "How is my team luck lately?"
- **Personalized patch notes (beta)**: patch changes filtered to the champions
  you play and the ones you have recently faced.

### 1.2 Match row

Ours has about half of these fields. Theirs:

| Field | Have? |
| --- | --- |
| Queue, time ago, result, duration | yes |
| Champion + level, runes, summoner spells | yes |
| K/D/A + KDA ratio, kill participation, CS + CS/min | yes |
| Items + trinket, multikill badge | yes |
| Both teams with player names | yes |
| **Laning score ("Laning 48 : 52")** | no |
| **Lobby average rank ("Challenger 2,565")** | no |
| **Placement in lobby (1st to 10th)** | no |
| **Performance badges: ACE, MVP, Rollercoaster, Late bloomer, Struggle, Average** | no |

### 1.3 Expanded match detail

Tabs: **Overview | OP Score | Team analysis | Build | Etc.**

Full scoreboard, per player: champion + level + runes, name **with that player's
own rank**, **OP Score with placement badge (MVP / 3rd / 9th)**, KDA with KP%,
damage dealt and taken as comparative bars, wards placed/killed/control, CS and
CS/min, full item set. Plus a team objective bar: total kills, total gold, and
baron / dragon / herald / tower / inhibitor counts.

### 1.4 Champion pages

`/lol/champions/<champion>/build/<role>` is a whole product on its own.

Filters: **rank bracket** (Emerald+), **region** (All Servers), **patch**, class,
vs-counter. Game modes: Ranked Solo/Duo, ARAM, Classic, Arena, Today's hot.

Tabs: **Build | Counters | Items | Champion synergies | Runes | Masters build |
Skills | Tips | Trends | Pro builds**.

Contents:
- Header: tier, win/pick/ban rate each with trend arrows, skill-order badges.
- **User-written champion tips** (community submitted, beta).
- **Runes**: the entire tree rendered as a grid, every single rune annotated with
  pick rate, win rate and sample size. Plus an **Export rune build** button that
  writes the page into the League client.
- **Summoner spell combos** with pick rate and win rate.
- **Skill order**: priority (Q > W > E) plus the full 18-level sequence, with win rate.
- **Item builds**: starter items, boots, and 3-item core paths, each with pick
  rate, games and win rate.
- **Synergies**: which duo partners this champion wins with, by role.
- **Champion mastery ranking per region**: the top players on that champion.
- **Skins ranking**: most played skins.
- **Counters**: "weak against" with win rate and sample size per matchup.

### 1.5 Tier list

- **Total analyzed samples: 11,625,222. Last updated: 11 minutes ago.**
- Filters: server, rank bracket, patch, game mode, role.
- Columns: Rank, Champion, **Tier (OP / 1 / 2 / 3)**, Role, Win rate, Pick rate,
  Ban rate, **Weak against** (inline counter portraits).

Note they have an **"OP" tier above tier 1**, and tiers are per role.

### 1.6 Everything else

Leaderboards, **Pro spectate** (watch pro players' live games), **Multi-search**
(paste a lobby, get all ten profiles), duo finder, esports hub, desktop app with
automatic rune import, streamer overlay.

---

## 2. masterychart.com

Much narrower and much sharper. The entire product is *one dataset rendered six
ways*, and it is better at that one thing than we are.

- Search by Riot ID, **Riot Sign On**, **favourites**, **multi-search up to 5
  profiles side by side**.
- Profile header: level, rank + LP, **mastery score (801)**, total points (5.8M),
  and counts by mastery level (137 | 48 | 27).
- Cross-links out to OP.GG and DeepLoL.
- Tabs: Profile | More Charts | Live Game | Statistics.

**The six visualisations**, each with 3 modes except the table:

| Chart | What it is |
| --- | --- |
| **Bubbles** ("the classic") | Packed circles, each champion's **splash art** as the fill, radius by mastery points, with a size legend (5K / 25K / 50K / 100K / 250K / 500K). Draggable. |
| **Voronoi** | Tessellated regions by points |
| **Treemap** | Nested rectangles |
| **Sunburst** | Radial hierarchy |
| **Icicle** | Horizontal hierarchy |
| **Table** | The plain numbers |

Controls: layout **Packed / Ordered / Seasonal**, fill **Default / Level / Class**,
and **Save** (export the chart as an image). The export is the growth loop: it is
a shareable object.

Menu also has: Champions, Leaderboards, **Meta Stats**, **Discover**,
**Live Games**, **Custom Chart**.

**Our mastery page is a flat grid.** Functional, honest, and far less compelling
than a physics-packed bubble chart of splash art that people screenshot.

---

## 3. itero.gg

A coaching product. Desktop app first (1M+ downloads, 4.4 stars, "Fully Riot
Compliant"). Web tools: **Drafting Simulator, Champion Pool Builder, Quiz,
Champions, Articles**.

### 3.1 Drafting Simulator

- Pick your **role** and your **side (Blue / Red)**.
- **Use Elo Bracket** (choose a rank) or **Use My Account** (personalised).
- Region selector.
- A real **5v5 draft board**: ten slots, each tagged with a role, filled in draft
  order. Plus **Randomize Draft** for practice.
- **Get Recommendations**.

### 3.2 Model Customization (they expose the model to the user)

This is the most directly useful thing I found, because it is our draft scorer
with a better interface:

| Control | Detail |
| --- | --- |
| **Consider my Champion Mastery** | 0-100% slider, default 30%. Copy: "For short-term results we recommend setting this to 100%, and reducing it when learning new Champions." |
| **Show Laning Phase Score** | Toggle, plus **Sort by Laning Phase Score** |
| **Minimum Laning Score** | Refuse to recommend anything below a threshold |
| **Minimum Pick Rate** | Default 0.25%, "increasing it will reduce recommendations to meta-only Champions" |

Ours has `comfort_weight` doing the same job as the first one, hardcoded in a
request body with no UI.

### 3.3 Their stated model factors

From the Champion Pool Builder's own explainer, verbatim in substance:

1. **Mastery**: how many games you have on the champion.
2. **Win rate**: how it is performing this patch.
3. **Counter win rates**: strong against **the whole enemy team**, not just your lane.
4. **Synergy win rates**: works well with **your team**.
5. **Predicted Gold @ 14 minutes**: how the laning phase is expected to go, and
   how effective the champion is when ahead or behind.
6. **Team-wide statistics**: does the team have enough damage, and a sensible
   AP/AD mix.

We implement 1, 2, and a narrow version of 3 (single opposing laner only).
**We do not implement 4, 5, or 6 at all.**

### 3.4 Champion detail

Laning Phase, Champion Laning Strength, Counter Average, Synergy Average, Team
Stats, Early/Mid/Late Strength Advantage, AD Ratio, Total Damage, Tankiness,
"Matchup vs Self" (level, playstyle, trading, kill threat, each flagged Safe or
Danger), and Best Matchups with win rate **and gold differential**.

---

## 4. What this costs us to close

Grouped by the only thing that actually constrains us: Riot API budget.

### Group A: free. Aggregate data we already store.

We keep the full raw match JSON plus normalised participant rows including
`items`, `perks` and `summoner1/2_id`. We render almost none of it.

- **Item builds**: starter / boots / core 3-item paths with pick and win rates.
- **Rune pages**: keystone and full tree, with win rates. `perks` is already stored.
- **Summoner spell combos** with win rates.
- **Synergy stats**: same self-join as `matchup_stats`, but same team instead of
  opposing team.
- **Counters vs the whole enemy team**, not just the lane opponent.
- **Champion detail pages**: the container all of the above belongs in.
- **Player analytics**: role share, class distribution, activity-hour heatmap,
  season aggregates. All derivable from rows we hold.
- **Rank-bracket and region slicing**: `ChampionStat.rank_bracket` exists and is
  hardcoded to "ALL"; we know the seed tier at ingest and `platform_id` per match.

### Group B: one extra Riot call per match. Unlocks the headline metrics.

Fetching `/lol/match/v5/matches/{id}/timeline` doubles ingest cost but gives:

- **Laning phase score** (gold / CS / XP differential at 14 minutes). This is the
  single most valuable missing metric, and both competitors lead with it.
- **Gold / XP / CS differential graphs** over the game.
- **Skill order** (which we cannot compute without it).
- Early / mid / late performance splits, objective timings, ward maps.

### Group C: expensive per view.

- **Lobby average rank**: 10 `league-v4` calls per match. At 100 requests per 2
  minutes this is unaffordable on a dev key; viable with production access plus
  aggressive caching of player ranks.
- **Live game**: `spectator-v5`, which Riot announced it is deactivating.
- **Leaderboards**: `league-v4` apex and paged entries. Affordable if cached.

### Group D: we have to invent it.

- An **OP Score equivalent**: a per-player, per-game performance rating. This is
  what drives their placement badges and much of their perceived intelligence.
- **Performance badges** (ACE, MVP, Struggle, Rollercoaster) derived from it.
- Any **AI analysis** layer.

### Group E: unreachable without scale.

11.6M-sample tier lists, credible per-matchup tables, pro builds. Honest answer:
these stay thin until the key changes, and `min_games` plus withheld tiers is the
right way to say so.

### Group F: product surface, not analytics.

Multi-search, favourites, RSO login, shareable chart export, leaderboards,
per-champion mastery leaderboards, skins ranking, i18n, desktop app, overlay.

---

## 5. Recommended order

Ranked by perceived depth gained per unit of Riot budget spent.

1. **Group A in full.** Zero API cost, and it is most of what makes op.gg's
   champion pages feel deep. Biggest win available.
2. **Match timelines (Group B).** Doubles ingest cost, but the laning score is
   the metric both competitors are built on, and it makes the draft assistant
   credible rather than a win-rate lookup.
3. **Draft model completion**: synergy with allies, counters against all five
   enemies, team damage mix. All Group A data. Plus expose the weights in the UI
   the way itero does.
4. **A performance score.** Needed before badges or placements mean anything.
5. **Mastery visualisation.** Our grid works; a packed bubble chart with splash
   art and an image export is the shareable artefact masterychart is built on.
6. **Multi-search and favourites.** Cheap, and multi-search is how people
   actually use these sites (paste the lobby).
7. **Leaderboards.** Cacheable, and gives the site a reason to exist when you are
   not looking someone up.
