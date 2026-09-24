import type { Analytics, MatchHistory, MatchSummary, Profile } from '@/lib/api'

/**
 * One made-up player's answers, typed against the API's own schema, so a
 * change to a response model breaks the fixtures at compile time rather than
 * letting a test pass against a shape the API no longer sends.
 */

export const PLAYER = { platform: 'euw1', name: 'Hydra', tag: 'EUW' } as const

export const profile = {
  puuid: 'hydra',
  game_name: 'Hydra',
  tag_line: 'EUW',
  riot_id: 'Hydra#EUW',
  platform: 'euw1',
  platform_label: 'EUW',
  shard: 'home',
  home_platform: 'euw1',
  home_platform_label: 'EUW',
  summoner_level: 120,
  profile_icon_url: null,
  ranks: [],
  plays_on: null,
  plays_on_label: null,
  identity_from_plays_on: false,
  updated_at: 1_790_000_000_000,
  ladder: null,
  source: 'live',
} satisfies Profile

export const storedProfile = { ...profile, source: 'stored' } satisfies Profile

export const emptyHistory = {
  puuid: 'hydra',
  matches: [],
  start: 0,
  count: 20,
  has_more: false,
  source: 'riot',
  stored_total: null,
  scope: 'ranked',
} satisfies MatchHistory

export const storedHistory = { ...emptyHistory, source: 'stored', stored_total: 0 } satisfies MatchHistory

export const emptyAnalytics = {
  puuid: 'hydra',
  game_name: 'Hydra',
  tag_line: 'EUW',
  platform: 'euw1',
  scope: 'ranked',
  queues: [420, 440],
  window: 1000,
  stored_total: 0,
  scope_games: [],
  basis: 'stored_matches',
  games_analysed: 0,
  roles: [],
  classes: [],
  activity_utc: [],
  champions: [],
  totals: {
    win_rate: 0,
    kda: 0,
    avg_kills: 0,
    avg_deaths: 0,
    avg_assists: 0,
    cs_per_min: 0,
    vision_per_game: 0,
    damage_per_min: 0,
  },
  score_profile: [],
  review: [],
  lanes: [],
} satisfies Analytics

const components = [
  { id: 'damage', label: 'Damage', measures: 'Damage to champions per minute', avg_percentile: 0.72 },
  { id: 'vision', label: 'Vision', measures: 'Vision score per minute', avg_percentile: 0.31 },
  { id: 'kda', label: 'KDA', measures: 'Kills and assists per death', avg_percentile: 0.55 },
]

/**
 * A ranked mid laner with enough stored games for every panel of the profile
 * to draw: two scored roles, a review, lanes, two champions (one never scored,
 * so its score is the dash) and a day of games mostly in the evening.
 */
export const filledAnalytics = {
  ...emptyAnalytics,
  stored_total: 40,
  scope_games: [
    { scope: 'ranked', label: 'Ranked', games: 40 },
    { scope: 'all', label: 'All', games: 55 },
  ],
  games_analysed: 40,
  roles: [
    { position: 'MIDDLE', games: 30, share: 0.75, win_rate: 0.57 },
    { position: 'TOP', games: 10, share: 0.25, win_rate: 0.4 },
  ],
  classes: [
    { tag: 'Mage', games: 30, share: 0.75 },
    { tag: 'Fighter', games: 10, share: 0.25 },
  ],
  // 36 games from 19:00 to 23:00 UTC and 4 at noon: the busiest three hours
  // are 19:00 to 22:00, the earliest of two equal runs.
  activity_utc: Array.from({ length: 24 }, (_, hour) => (hour >= 19 && hour <= 22 ? 9 : hour === 12 ? 4 : 0)),
  champions: [
    {
      champion: { id: 103, name: 'Ahri', icon_url: null, slug: 'ahri' },
      games: 30,
      wins: 17,
      win_rate: 17 / 30,
      kda: 3.4,
      cs_per_min: 7.8,
      avg_kills: 6.1,
      avg_deaths: 3.9,
      avg_assists: 7.2,
      damage_per_min: 820,
      main_position: 'MIDDLE',
      last_played: 1_790_000_000_000 - 3_600_000,
      scored_games: 28,
      avg_score: 6.4,
      timeline_games: 25,
      avg_gold_diff_14: 210,
    },
    {
      champion: { id: 86, name: 'Garen', icon_url: null, slug: 'garen' },
      games: 10,
      wins: 4,
      win_rate: 0.4,
      kda: 2.1,
      cs_per_min: 6.9,
      avg_kills: 4.2,
      avg_deaths: 4.8,
      avg_assists: 5.9,
      damage_per_min: 610,
      main_position: 'TOP',
      last_played: 1_790_000_000_000 - 86_400_000,
      scored_games: 0,
      avg_score: null,
      timeline_games: 0,
      avg_gold_diff_14: null,
    },
  ],
  totals: {
    win_rate: 0.525,
    kda: 3.1,
    avg_kills: 5.6,
    avg_deaths: 4.1,
    avg_assists: 6.9,
    cs_per_min: 7.5,
    vision_per_game: 21,
    damage_per_min: 768,
  },
  score_profile: [
    {
      position: 'MIDDLE',
      scored_games: 28,
      enough: true,
      avg_score: 6.4,
      avg_placement: 4.2,
      mvp: 4,
      ace: 2,
      components,
      sample: 4_000,
      min_scored: 10,
    },
    {
      position: 'TOP',
      scored_games: 10,
      enough: true,
      avg_score: 5.1,
      avg_placement: 5.6,
      mvp: 0,
      ace: 1,
      components,
      sample: 3_000,
      min_scored: 10,
    },
  ],
  review: [
    {
      position: 'MIDDLE',
      games: 25,
      min_games: 10,
      withheld: null,
      metrics: [
        {
          metric: 'solo_deaths',
          label: 'Solo deaths',
          measures: 'Deaths with no ally near',
          value: 1.2,
          better_than: 0.64,
          lower_is_better: true,
          games: 25,
        },
      ],
      contests: 12,
      contests_won: 7,
    },
  ],
  lanes: [{ position: 'MIDDLE', games: 25, won_big: 3, won: 7, even: 8, lost: 5, lost_big: 2 }],
} satisfies Analytics

/** One game as a history row shows it: a ranked Ahri game, the nth newest. */
export function game(n: number, over: Partial<MatchSummary> = {}): MatchSummary {
  return {
    match_id: `EUW1_${9_000_000_000 + n}`,
    queue_id: 420,
    queue_name: 'Ranked Solo/Duo',
    patch: '16.18',
    game_creation: 1_790_000_000_000 - n * 3_600_000,
    game_duration: 1800,
    is_remake: false,
    win: n % 2 === 0,
    champion: { id: 103, name: 'Ahri', icon_url: null, slug: 'ahri' },
    champ_level: 16,
    position: 'MIDDLE',
    kills: 6,
    deaths: 3,
    assists: 9,
    kda: 5,
    kill_participation: 0.6,
    cs: 220,
    cs_per_min: 7.3,
    gold_earned: 12_000,
    vision_score: 20,
    damage_to_champions: 25_000,
    damage_per_min: 833,
    items: [],
    trinket: null,
    spells: [],
    keystone: null,
    secondary_tree: null,
    multi_kill: null,
    laning_score: null,
    laning_opponent: null,
    laning_label: null,
    gold_diff_14: null,
    cs_diff_14: null,
    lobby_rank_points: null,
    lobby_rank_tier: null,
    lobby_rank_division: null,
    lobby_ranked_players: null,
    lobby_players_total: null,
    lobby_rank_measured_at: null,
    lobby_queue_matches_game: true,
    score: 6.5,
    placement: 3,
    score_withheld: null,
    badges: [],
    score_components: [],
    score_sample: 4_000,
    teams: [],
    ...over,
  }
}

// Served by the site itself, so a browser test draws every icon without
// reaching Data Dragon.
const ICON = '/favicon.svg'
const POSITIONS = ['TOP', 'JUNGLE', 'MIDDLE', 'BOTTOM', 'UTILITY']

/**
 * A game with everything a history row can draw: items, spells, runes, the
 * lane at 14 minutes, the lobby's rank, a badge, a multi kill and both teams.
 * `game()` leaves them empty, which is how a row once kept a title per item
 * that no test could see.
 */
export function fullGame(n: number, over: Partial<MatchSummary> = {}): MatchSummary {
  const base = game(n)
  const member = (team: 100 | 200, i: number): MatchSummary['teams'][number][number] => ({
    puuid: `${team}-${i}`.padEnd(78, '0'),
    riot_id: `Player${team}${i}#EUW`,
    champion: { id: 10 + i + (team === 200 ? 5 : 0), name: `Champion ${team}-${i}`, icon_url: ICON, slug: null },
    team_id: team,
    position: POSITIONS[i],
    kills: 4,
    deaths: 3,
    assists: 6,
    win: team === 100 ? base.win : !base.win,
    score: 5 + i / 2,
    placement: i + 1 + (team === 200 ? 5 : 0),
    badges: [],
  })
  return {
    ...base,
    items: [
      { id: 3157, name: "Zhonya's Hourglass", icon_url: ICON, slug: 'zhonyas-hourglass' },
      { id: 3020, name: "Sorcerer's Shoes", icon_url: ICON, slug: 'sorcerers-shoes' },
    ],
    trinket: { id: 3364, name: 'Oracle Lens', icon_url: ICON, slug: 'oracle-lens' },
    spells: [
      { id: 4, name: 'Flash', icon_url: ICON },
      { id: 14, name: 'Ignite', icon_url: ICON },
    ],
    keystone: { id: 8112, name: 'Electrocute', icon_url: ICON },
    secondary_tree: { id: 8300, name: 'Inspiration', icon_url: ICON },
    multi_kill: 'Double Kill',
    laning_score: 0.62,
    laning_opponent: { id: 238, name: 'Zed', icon_url: ICON, slug: 'zed' },
    laning_label: 'won',
    gold_diff_14: 450,
    cs_diff_14: 8,
    lobby_rank_points: 2_400,
    lobby_rank_tier: 'DIAMOND',
    lobby_rank_division: 'II',
    lobby_ranked_players: 10,
    lobby_players_total: 10,
    lobby_rank_measured_at: base.game_creation + 7_200_000,
    badges: [{ id: 'mvp', label: 'MVP', detail: 'The best score in the lobby.' }],
    teams: [
      POSITIONS.map((_, i) => member(100, i)),
      POSITIONS.map((_, i) => member(200, i)),
    ],
    ...over,
  }
}
