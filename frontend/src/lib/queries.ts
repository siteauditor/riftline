import { queryOptions } from '@tanstack/react-query'

import { api, type SliceQuery } from './api'

/**
 * Every query a prerendered page reads, defined once.
 *
 * A page and the prerenderer must agree on the query key to the byte, or the
 * page hydrates with an empty cache and fetches everything again on top of
 * the HTML it was given. Defining the key and the fetch together here, and
 * having both sides call the same function, makes agreement a property of
 * the code rather than a thing to remember.
 */

export interface ItemSlice {
  patch: string | null
  queueId: number
  bracket: string | null
}

export interface LeaderboardSlice {
  queueId: number
  tier: string
  division: string
  page: number
  perPage: number
}

/** The ladder the page opens on with nothing in the URL, and the one the
 *  prerenderer renders. Apex ignores the division, so it is fixed at I. */
export const DEFAULT_LADDER = {
  platform: 'euw1',
  queueId: 420,
  tier: 'CHALLENGER',
  division: 'I',
  page: 1,
  perPage: 50,
}

export const queries = {
  meta: (opts: SliceQuery) =>
    queryOptions({ queryKey: ['meta', opts], queryFn: () => api.meta(opts) }),
  corpus: () => queryOptions({ queryKey: ['corpus'], queryFn: api.corpus }),
  bestGames: () => queryOptions({ queryKey: ['best-games'], queryFn: api.bestGames }),
  champions: () => queryOptions({ queryKey: ['champions'], queryFn: api.champions }),
  topSkins: () => queryOptions({ queryKey: ['top-skins'], queryFn: api.topSkins }),
  items: () => queryOptions({ queryKey: ['items'], queryFn: api.items }),
  item: (ref: string, slice: ItemSlice) =>
    queryOptions({ queryKey: ['item', ref, slice], queryFn: () => api.item(ref, slice) }),
  champion: (ref: string, slice: SliceQuery) =>
    queryOptions({ queryKey: ['champion', ref, slice], queryFn: () => api.champion(ref, slice) }),
  championProfile: (ref: string) =>
    queryOptions({ queryKey: ['champion-profile', ref], queryFn: () => api.championProfile(ref) }),
  championPlayers: (ref: string) =>
    queryOptions({ queryKey: ['champion-players', ref], queryFn: () => api.championPlayers(ref) }),
  method: () => queryOptions({ queryKey: ['method'], queryFn: api.method }),
  leaderboardSlices: () =>
    queryOptions({ queryKey: ['leaderboard-slices'], queryFn: api.leaderboardSlices }),
  leaderboard: (platform: string, slice: LeaderboardSlice) =>
    queryOptions({
      queryKey: ['leaderboard', platform, slice.queueId, slice.tier, slice.division, slice.page],
      queryFn: () => api.leaderboard(platform, slice),
    }),
}
