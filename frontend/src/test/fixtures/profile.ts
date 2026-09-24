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
