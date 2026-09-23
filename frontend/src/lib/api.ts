/**
 * Typed client for the analytics API.
 *
 * Field names are snake_case because that is what FastAPI serialises; keeping
 * them identical on both sides removes a whole class of "why is this undefined"
 * bugs that mapping layers introduce.
 */

import type { components } from './api.gen'

/**
 * The response types are the API's own: `api.gen.d.ts` is generated from
 * FastAPI's OpenAPI document (`pnpm api:types`), and CI regenerates it and
 * fails on any difference, so a field added or renamed on the backend shows
 * up here as a type error rather than as `undefined` in a page. The aliases
 * keep the names the pages have always used.
 */
type S = components['schemas']

export type ChampionRef = S['ChampionRef']

export type ItemRef = S['ItemRef']

export type SpellRef = S['SpellRef']

export type RuneRef = S['RuneRef']

export type RankInfo = S['RankInfo']

/**
 * What we know about one player in a live game.
 *
 * `state` is the honest part. Since 2025 players can hide their identity from
 * third-party tools, and roughly a third of a lobby does: those come back
 * `hidden` with no name, no rank and nothing to link to. `unknown` is different
 * again, meaning the rank lookup did not finish, which is not the same claim as
 * `unranked`.
 */
export type LiveState = 'ranked' | 'unranked' | 'hidden' | 'bot' | 'unknown'

export type LiveParticipant = S['LiveParticipantOut']

export type Position = 'TOP' | 'JUNGLE' | 'MIDDLE' | 'BOTTOM' | 'UTILITY'

/** A player's own record from the games Riftline has stored. Withheld rather
 *  than zeroed: `stored_games` on the participant says how little we hold. */
export type PlayedRecord = S['PlayedRecordOut']

export type PlayerRecord = S['PlayerRecordOut']

export type LiveMastery = S['LiveMasteryOut']

/** Which step of the lane fallback produced a record. A record always carries
 *  its size, and anything below `lane` also carries its basis. Anything below `lane`
 *  Anything below `lane` must be labelled where it is shown: a team scope
 *  record rendered as a lane record is a claim the data does not support. */
export type RecordBasis = 'role' | 'lane' | 'lane_pooled' | 'team'

export type CorpusRecord = S['CorpusRecordOut']

export type LiveBan = S['LiveBanOut']

/** How far an inferred position can be trusted. Measured on held-out games. */
export type PositionModel = S['PositionModelOut']

export type LobbyRank = S['LobbyRankOut']

/** Earlier stored games a player and the searched player were both in.
 *  Counts only, at any sample size: these are single digit numbers. The wins
 *  are always the searched player's. */
export type SharedGames = S['SharedGamesOut']

/** Two players in this lobby who keep landing on the same side in stored games.
 *  Not a duo: two players in one small ranked pool meet constantly without ever
 *  pressing invite, and the crawler walks outward from matches it already holds,
 *  so this is a pattern rather than a census. */
export type SameTeamPair = S['SameTeamPairOut']

/** One side of a live lobby, summed from what the lobby already shows. */
export type SideRead = S['SideReadOut']

/** The two sides beside each other. Carries no win probability and no verdict:
 *  the site holds no model that predicts a game, and a third of every lobby
 *  hides its identity in a way that is not missing at random. */
export type LobbyCompare = S['LobbyCompareOut']

export type LiveGame = S['LiveGameOut']

/** The newest game Riftline holds for a player, for the page they see when they
 *  are not playing. Not the newest game they played: the corpus is crawled, and
 *  for a player with 5+ stored games the newest is a median of 4 days old. */
export type LastStoredGame = S['LastStoredGameOut']

export type IdleSummary = S['IdleSummaryOut']

export type LiveGameResponse = S['LiveGameResponse']

/** Whether a finished live game has reached storage yet. Always 200 with a
 *  status: the match will exist, so "not yet" is an answer rather than a 404. */
export type MatchResolve = S['MatchResolveResponse']

export type LeaderboardRow = S['LeaderboardRow']

export type LeaderboardResponse = S['LeaderboardResponse']

export type LeaderboardSlices = S['LeaderboardSlices']

export type Profile = S['ProfileResponse']

/** A badge, with the rule that earned it and this player's own figure. */
export type Badge = S['BadgeOut']

/** One of the six things the Riftline score is made of. */
export type ScoreComponent = S['ScoreComponentOut']

export type ParticipantBrief = S['ParticipantBrief']

export type MatchSummary = S['MatchSummary']

export type ScoreboardPlayer = S['ScoreboardPlayer']

export type TeamObjectives = S['TeamObjectives']

/** How the score is computed, published with every scoreboard. */
export type ScoreModel = S['ScoreModelOut']

export type MatchDetail = S['MatchDetailResponse']

export type MatchHistory = S['MatchHistoryResponse']

export type MasteryEntry = S['MasteryEntry']

export type MasteryResponse = S['MasteryResponse']

export type Health = S['HealthResponse']

export type ChampionStatic = S['ChampionInfo']

/**
 * An API failure the UI can act on.
 *
 * `kind` matters: a 429 on a development key is an expected, temporary state
 * with a known wait, and an expired key is a fixable configuration problem.
 * Neither should surface as "something went wrong".
 */
export type TierListChampion = S['TierListChampion']

export type ChampionMetaRow = S['ChampionMetaRow']

export type MetaResponse = S['MetaResponse']

export type CorpusResponse = S['CorpusResponse']

// --- home page -----------------------------------------------------------------

/** A Riot ID we already hold, offered while somebody types. */
export type PlayerSuggestion = S['PlayerSuggestion']

export type SuggestResponse = S['SuggestResponse']

/** The highest Riftline score in one role over the window. */
export type BestGame = S['BestGameOut']

export type BestGamesResponse = S['BestGamesResponse']

// --- champion detail -------------------------------------------------------

export type ChampionInfo = S['ChampionInfo']

export type PositionShare = S['PositionShare']

/** One thing a champion took: an item set, a rune page, a spell pair. */
export type FacetEntry = S['FacetEntry']

export type PairEntry = S['PairEntry']

export type ChampionDetail = S['ChampionDetail']

/**
 * The same champion, role and bracket on the patch before. A change is only
 * drawn where `*_moved` is true: the two 95% intervals no longer overlap.
 */
export type PatchChange = S['PatchChange']

// --- champion profile ------------------------------------------------------

export interface ChampionRating {
  key: string
  label: string
  /** Riot's own 0 to 10. */
  value: number
}

export type ChampionBaseStat = S['BaseStat']

export type ChampionAbility = S['AbilityOut']

export type ChampionSkin = S['SkinOut']

export type ChampionProfile = S['ChampionProfile']

export type ChampionPlayer = S['ChampionPlayer']

export type ChampionPlayers = S['ChampionPlayers']

export type TopSkin = S['TopSkin']

export type TopSkins = S['TopSkins']

// --- item guide ------------------------------------------------------------

export interface ItemStatLine {
  value: string
  label: string
}

export type ItemEffect = S['ItemEffectOut']

export type ItemRefCost = S['ItemRefOut']

export type ItemSummary = S['ItemSummary']

export type ItemSection = S['ItemSection']

export type ItemList = S['ItemList']

export type ItemSlot = S['ItemSlotOut']

export type ItemChampion = S['ItemChampionOut']

export type ItemFigures = S['ItemFigures']

export type ItemDetail = S['ItemDetail']

// --- player analytics ------------------------------------------------------

export type Analytics = S['AnalyticsResponse']

export type LaneLabel = 'won_big' | 'won' | 'even' | 'lost' | 'lost_big'

export type ReviewMetric = S['ReviewMetricOut']

export type RoleReview = S['RoleReviewOut']

export type LaneRecord = S['LaneRecordOut']

// --- a game's story ---------------------------------------------------------

export type StoryPlayerRef = S['StoryPlayerRef']

export type StoryDeath = S['DeathOut']

export type StoryTakedown = S['TakedownOut']

export type StoryPlayer = S['PlayerStoryOut']

export type StoryMoment = S['MomentOut']

export type GameStory = S['GameStoryResponse']

// --- the method page --------------------------------------------------------

export type AuditRole = S['AuditRoleOut']

export type ScoreAudit = S['ScoreAuditOut']

export type WinModelMethod = S['WinModelMethod']

export type MethodReport = S['MethodResponse']

/** One champion over the stored games. Each average is over its own count. */
export type ChampionPlayed = S['ChampionPlayed']

/** What a player's scored games in one role add up to. */
export type RoleScoreProfile = S['RoleScoreProfileOut']

export type RankHistory = S['RankHistoryResponse']

export interface SliceQuery {
  patch?: string | null
  queueId?: number
  position?: string | null
  bracket?: string | null
  minGames?: number
}

/** One record behind a suggestion, with the sample it rests on. */
export type DraftEvidence = S['EvidenceOut']

export type DraftSuggestion = S['SuggestionOut']

export type DraftBanCandidate = S['BanCandidateOut']

/** The constants behind the score, so the page states them rather than guessing. */
export type DraftModel = S['DraftModelOut']

export type DraftResponse = S['DraftResponse']

/** Whether the list was weighted by a player's mastery, and if not, why. */
export type DraftPersonalisation = S['PersonalisationOut']

export type DraftRequest = S['DraftRequest']

// --- groups -------------------------------------------------------------------

export type GroupQueue = S['GroupQueueOut']

export type GroupChampion = S['GroupChampionOut']

/** How much of one player's history is stored, and whether more is coming. */
export type GroupHistory = S['GroupHistoryOut']

export type GroupMember = S['GroupMemberOut']

export type GroupPair = S['GroupPairOut']

export type TogetherGame = S['TogetherGameOut']

export type GroupTogether = S['GroupTogetherOut']

export type Group = S['GroupResponse']

/** One bounded pass of fetching a group's missing games. */
export type GroupWarm = S['GroupWarmResponse']

export type GroupCreated = S['GroupCreatedResponse']

export type GroupMemberAdded = S['GroupMemberAddedResponse']

export class ApiError extends Error {
  status: number
  kind:
    | 'not_found'
    | 'rate_limited'
    | 'expired_key'
    | 'gone'
    /** The endpoint is unavailable to our key. Nothing the user can fix. */
    | 'unavailable'
    | 'upstream'
    | 'unknown'
  retryAfter?: number

  constructor(status: number, detail: string, extra: Record<string, unknown> = {}) {
    super(detail)
    this.name = 'ApiError'
    this.status = status
    this.retryAfter = typeof extra.retry_after === 'number' ? extra.retry_after : undefined
    if (status === 404) this.kind = 'not_found'
    else if (status === 429) this.kind = 'rate_limited'
    else if (extra.hint === 'expired_api_key') this.kind = 'expired_key'
    else if (status === 410) this.kind = 'gone'
    else if (extra.hint === 'endpoint_unavailable') this.kind = 'unavailable'
    // 504 from nginx and 524 from Cloudflare are a slow origin, not a bug in
    // the page: the same honest "try again" as a Riot outage.
    else if ([502, 503, 504, 524].includes(status)) this.kind = 'upstream'
    else this.kind = 'unknown'
  }
}

/**
 * The server's own words for a failure. Usually a string, but a request
 * FastAPI rejects as malformed (422) carries a list of field errors, which
 * printed as "[object Object]" when handed to `Error` as it was.
 */
function errorDetail(detail: unknown): string | null {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    const messages = detail
      .map((d) => (d && typeof d === 'object' && 'msg' in d ? String(d.msg) : null))
      .filter(Boolean)
    return messages.length ? messages.join('; ') : null
  }
  return null
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init)
  if (!response.ok) {
    let detail = `Request failed (${response.status})`
    let extra: Record<string, unknown> = {}
    try {
      const body = await response.json()
      detail = errorDetail(body?.detail) ?? detail
      extra = body ?? {}
    } catch {
      // Non-JSON error body (an edge timeout page, say); the status alone
      // will have to do.
    }
    throw new ApiError(response.status, detail, extra)
  }
  // A change with nothing to say back (renaming a group, say) is a 204, and
  // an empty body is not JSON.
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

const JSON_HEADERS = { 'Content-Type': 'application/json' }

/** The edit key travels as a header, never in a URL a server would log. */
function groupHeaders(key: string | null, json = false): Record<string, string> {
  return { ...(json ? JSON_HEADERS : {}), ...(key ? { 'X-Group-Key': key } : {}) }
}

const enc = encodeURIComponent

/** Shared query string for every slice-filtered endpoint. */
function sliceParams(opts: SliceQuery, defaultMinGames: number): string {
  const params = new URLSearchParams()
  if (opts.patch) params.set('patch', opts.patch)
  params.set('queue_id', String(opts.queueId ?? 420))
  if (opts.position) params.set('position', opts.position)
  if (opts.bracket) params.set('bracket', opts.bracket)
  params.set('min_games', String(opts.minGames ?? defaultMinGames))
  return params.toString()
}

export const api = {
  health: () => request<Health>('/api/health'),

  champions: () =>
    request<{ version: string; champions: ChampionStatic[] }>('/api/static/champions'),

  queues: () => request<{ queues: { id: number; name: string }[] }>('/api/static/queues'),

  /** The full scoreboard for one stored match. Fetched when a row is expanded. */
  matchDetail: (matchId: string) => request<MatchDetail>(`/api/matches/${enc(matchId)}`),

  matchStory: (matchId: string) => request<GameStory>(`/api/matches/${enc(matchId)}/story`),

  method: () => request<MethodReport>('/api/method'),

  /** `source: 'stored'` answers from storage alone, with no Riot call and no
   *  refresh: what the prerenderer asks for. */
  profile: (
    platform: string,
    name: string,
    tag: string,
    opts: { refresh?: boolean; source?: 'stored' } = {},
  ) => {
    const params = new URLSearchParams()
    if (opts.refresh) params.set('refresh', 'true')
    if (opts.source) params.set('source', opts.source)
    const qs = params.toString()
    return request<Profile>(
      `/api/summoner/${enc(platform)}/${enc(name)}/${enc(tag)}${qs ? `?${qs}` : ''}`,
    )
  },

  matches: (
    platform: string,
    name: string,
    tag: string,
    opts: {
      start?: number
      count?: number
      queue?: number | null
      champion?: number | null
      source?: 'stored'
    } = {},
  ) => {
    const params = new URLSearchParams()
    if (opts.start) params.set('start', String(opts.start))
    if (opts.count) params.set('count', String(opts.count))
    if (opts.queue) params.set('queue', String(opts.queue))
    if (opts.champion) params.set('champion', String(opts.champion))
    if (opts.source) params.set('source', opts.source)
    const qs = params.toString()
    return request<MatchHistory>(
      `/api/summoner/${enc(platform)}/${enc(name)}/${enc(tag)}/matches${qs ? `?${qs}` : ''}`,
    )
  },

  mastery: (platform: string, name: string, tag: string) =>
    request<MasteryResponse>(
      `/api/summoner/${enc(platform)}/${enc(name)}/${enc(tag)}/mastery`,
    ),

  corpus: () => request<CorpusResponse>('/api/meta/corpus'),

  /** Players we already hold whose Riot ID starts with `q`. Never calls Riot. */
  suggest: (q: string, platform: string, signal?: AbortSignal) =>
    request<SuggestResponse>(
      `/api/players/suggest?${new URLSearchParams({ q, platform }).toString()}`,
      { signal },
    ),

  bestGames: () => request<BestGamesResponse>('/api/highlights/best-games'),

  meta: (opts: SliceQuery = {}) =>
    request<MetaResponse>(`/api/meta/champions?${sliceParams(opts, 20)}`),

  /** By slug ("aatrox") or, from older links, by id. */
  champion: (championId: string | number, opts: SliceQuery = {}) =>
    request<ChampionDetail>(`/api/champions/${championId}?${sliceParams(opts, 5)}`),

  championProfile: (championId: string | number) =>
    request<ChampionProfile>(`/api/champions/${championId}/profile`),

  championPlayers: (championId: string | number) =>
    request<ChampionPlayers>(`/api/champions/${championId}/players`),

  topSkins: () => request<TopSkins>('/api/skins/top'),

  items: () => request<ItemList>('/api/items'),

  item: (itemId: string | number, opts: { patch?: string | null; queueId?: number; bracket?: string | null } = {}) => {
    const params = new URLSearchParams()
    if (opts.patch) params.set('patch', opts.patch)
    params.set('queue_id', String(opts.queueId ?? 420))
    if (opts.bracket) params.set('bracket', opts.bracket)
    return request<ItemDetail>(`/api/items/${itemId}?${params}`)
  },

  analytics: (
    platform: string,
    name: string,
    tag: string,
    opts: { queue?: number | null; limit?: number; source?: 'stored' } = {},
  ) => {
    const params = new URLSearchParams()
    if (opts.queue) params.set('queue', String(opts.queue))
    if (opts.limit) params.set('limit', String(opts.limit))
    if (opts.source) params.set('source', opts.source)
    const qs = params.toString()
    return request<Analytics>(
      `/api/summoner/${enc(platform)}/${enc(name)}/${enc(tag)}/analytics${qs ? `?${qs}` : ''}`,
    )
  },

  rankHistory: (platform: string, name: string, tag: string, queue: string) =>
    request<RankHistory>(
      `/api/summoner/${enc(platform)}/${enc(name)}/${enc(tag)}/rank-history?queue=${enc(queue)}`,
    ),

  live: (platform: string, name: string, tag: string) =>
    request<LiveGameResponse>(
      `/api/summoner/${enc(platform)}/${enc(name)}/${enc(tag)}/live`,
    ),

  /** Ask whether a game that just ended has reached storage. The server bounds
   *  the Riot spend at three calls per match id, whoever is asking. */
  liveResult: (platform: string, name: string, tag: string, matchId: string) =>
    request<MatchResolve>(
      `/api/summoner/${enc(platform)}/${enc(name)}/${enc(tag)}/live/result/${enc(matchId)}`,
    ),

  leaderboardSlices: () =>
    request<LeaderboardSlices>('/api/leaderboard/slices'),

  leaderboard: (
    platform: string,
    opts: {
      queueId?: number
      tier?: string
      division?: string
      page?: number
      perPage?: number
    } = {},
  ) => {
    const params = new URLSearchParams()
    params.set('queue_id', String(opts.queueId ?? 420))
    params.set('tier', opts.tier ?? 'CHALLENGER')
    params.set('division', opts.division ?? 'I')
    params.set('page', String(opts.page ?? 1))
    params.set('per_page', String(opts.perPage ?? 50))
    return request<LeaderboardResponse>(
      `/api/leaderboard/${enc(platform)}?${params.toString()}`,
    )
  },

  draft: (body: DraftRequest, signal?: AbortSignal) =>
    request<DraftResponse>('/api/draft/suggest', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal,
    }),

  createGroup: (name: string) =>
    request<GroupCreated>('/api/groups', {
      method: 'POST',
      headers: JSON_HEADERS,
      body: JSON.stringify({ name }),
    }),

  /** Storage only: fetching from Riot is `warmGroup`. */
  group: (slug: string, queue: string, key: string | null) =>
    request<Group>(`/api/groups/${enc(slug)}?queue=${enc(queue)}`, {
      headers: groupHeaders(key),
    }),

  warmGroup: (slug: string) =>
    request<GroupWarm>(`/api/groups/${enc(slug)}/warm`, { method: 'POST' }),

  renameGroup: (slug: string, key: string, name: string) =>
    request<void>(`/api/groups/${enc(slug)}`, {
      method: 'PATCH',
      headers: groupHeaders(key, true),
      body: JSON.stringify({ name }),
    }),

  deleteGroup: (slug: string, key: string) =>
    request<void>(`/api/groups/${enc(slug)}`, { method: 'DELETE', headers: groupHeaders(key) }),

  rotateGroupKey: (slug: string, key: string) =>
    request<{ key: string }>(`/api/groups/${enc(slug)}/key`, {
      method: 'POST',
      headers: groupHeaders(key),
    }),

  addGroupMember: (
    slug: string,
    key: string,
    member: { riot_id: string; platform: string; label?: string | null },
  ) =>
    request<GroupMemberAdded>(`/api/groups/${enc(slug)}/members`, {
      method: 'POST',
      headers: groupHeaders(key, true),
      body: JSON.stringify(member),
    }),

  setGroupMemberLabel: (slug: string, key: string, puuid: string, label: string | null) =>
    request<void>(`/api/groups/${enc(slug)}/members/${enc(puuid)}`, {
      method: 'PATCH',
      headers: groupHeaders(key, true),
      body: JSON.stringify({ label }),
    }),

  removeGroupMember: (slug: string, key: string, puuid: string) =>
    request<void>(`/api/groups/${enc(slug)}/members/${enc(puuid)}`, {
      method: 'DELETE',
      headers: groupHeaders(key),
    }),
}

export const POSITIONS = [
  { id: 'TOP', label: 'Top' },
  { id: 'JUNGLE', label: 'Jungle' },
  { id: 'MIDDLE', label: 'Mid' },
  { id: 'BOTTOM', label: 'Bot' },
  { id: 'UTILITY', label: 'Support' },
] as const

export const PLATFORMS = [
  { id: 'euw1', label: 'EUW' },
  { id: 'na1', label: 'NA' },
  { id: 'kr', label: 'KR' },
  { id: 'eun1', label: 'EUNE' },
  { id: 'br1', label: 'BR' },
  { id: 'jp1', label: 'JP' },
  { id: 'la1', label: 'LAN' },
  { id: 'la2', label: 'LAS' },
  { id: 'oc1', label: 'OCE' },
  { id: 'tr1', label: 'TR' },
  { id: 'ru', label: 'RU' },
  { id: 'me1', label: 'ME' },
  { id: 'sg2', label: 'SG' },
  { id: 'tw2', label: 'TW' },
  { id: 'vn2', label: 'VN' },
] as const
