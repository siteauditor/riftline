import { useEffect } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'

import { api, ApiError } from './api'
import { canonicalPlatform, movedFrom, profileRedirect } from './profileAddress'
import { queries } from './queries'
import { useHydrated } from './searchParams'
import { rememberSearch } from './storage'
import { useMatchHistory } from './useMatchHistory'

/** The analytics endpoint's ceiling, and the key the champions tab and the
 *  mastery page already use, so the three share one stored-games answer. */
export const PLAYED_LIMIT = 1000

/**
 * Everything the profile page reads, and when it reads it.
 *
 * - A prerendered profile carries the answers storage gave the prerenderer
 *   (`queries.*Stored`), and each live query shows its stored answer until
 *   Riot's arrives, so the page is complete on first render.
 * - The live history is asked only once the page has hydrated and Riot has
 *   answered for the profile. Before hydration the URL's filters read as
 *   empty (`useHydratedSearchParams`), so a link to `?queue=420` fetched the
 *   unfiltered history and then the filtered one; and before the answer the
 *   page may still move to another address (`profileRedirect`).
 * - When Riot cannot be asked (an expired key, an outage, a busy key) the page
 *   reads storage instead, the way a prerendered page already could: every
 *   profile we hold shows its stored games under a line that says so, rather
 *   than an error over data we have. A "no such player" is an answer, not an
 *   outage, and is shown as one.
 */
export function useProfileData(
  platform: string,
  name: string,
  tag: string,
  { queue, champion }: { queue: number | null; champion: number | null },
) {
  const queryClient = useQueryClient()
  const hydrated = useHydrated()
  const location = useLocation()
  const navigate = useNavigate()

  const profileQuery = useQuery({
    ...queries.profile(platform, name, tag),
    placeholderData: () =>
      queryClient.getQueryData(queries.profileStored(platform, name, tag).queryKey),
  })
  // Riot's answer, not the stored one standing in for it.
  const live = profileQuery.isPlaceholderData ? undefined : profileQuery.data

  const notFound = profileQuery.error instanceof ApiError && profileQuery.error.kind === 'not_found'
  // Storage instead of Riot: the live profile failed for any reason but "no
  // such player", or answered from storage because the key was busy.
  const storedMode = (profileQuery.isError && !notFound) || live?.source === 'stored'

  // Held from the prerender, or asked for now that Riot cannot be. Never
  // asked while Riot answers: storage is what the live answers replace.
  const storedProfileQuery = useQuery({
    ...queries.profileStored(platform, name, tag),
    enabled: storedMode,
    staleTime: Infinity,
    retry: false,
  })
  const storedProfile = storedProfileQuery.data
  const storedAnalytics = useQuery({
    ...queries.analyticsStored(platform, name, tag),
    enabled: storedMode,
    staleTime: Infinity,
    retry: false,
  }).data
  const heldMatches = () =>
    queryClient.getQueryData(queries.matchesStored(platform, name, tag).queryKey)

  // One address per player. A shard the account holds nothing on moves to
  // its home (a view of NA for a EUW player used to be the page that deleted
  // their rank), and an alias or another spelling moves to the canonical
  // address. After hydration, so a prerendered page hydrates as the HTML it
  // was served, and on Riot's answer only. The answer is seeded under the new
  // address, so the page there does not ask again.
  const moving =
    hydrated &&
    live !== undefined &&
    profileRedirect({ params: { platform, name, tag }, search: location.search, profile: live, state: location.state }) !== null
  useEffect(() => {
    if (!hydrated || !live) return
    const next = profileRedirect({
      params: { platform, name, tag },
      search: location.search,
      profile: live,
      state: location.state,
    })
    if (!next) return
    const { seed } = next
    queryClient.setQueryData(queries.profile(seed.platform, seed.name, seed.tag).queryKey, seed.profile)
    navigate(next.to, { replace: true, state: next.state })
  }, [hydrated, live, platform, name, tag, location.search, location.state, queryClient, navigate])
  // History state is the browser's alone, so it is read once the page is hydrated.
  const movedFromLabel = hydrated ? movedFrom(location.state) : null

  // Remembered only once Riot has answered, so a mistyped ID never becomes a
  // "recent" search: the stored answer a prerendered page opens with is not
  // one. Stored with the name as Riot spells it, not as typed, and under the
  // address the page settles on.
  useEffect(() => {
    if (!live?.game_name || !live.tag_line || live.source === 'stored') return
    rememberSearch({
      platform: canonicalPlatform(live),
      gameName: live.game_name,
      tagLine: live.tag_line,
      iconUrl: live.profile_icon_url,
    })
  }, [live])

  // Anything but a stored answer is Riot's: an API from before `source`
  // existed (a rollback) answers without it.
  const liveAnswered = live !== undefined && live.source !== 'stored' && !moving
  const unfiltered = queue === null && champion === null

  // The live page reads the same history, so the query lives in one hook: two
  // configurations of one cache key is a race between whichever page mounts
  // first. In stored mode the same hook reads storage, filters included.
  const { query: matchesQuery, matches } = useMatchHistory(platform, name, tag, {
    queue,
    champion,
    source: storedMode ? 'stored' : undefined,
    enabled: hydrated && (storedMode || liveAnswered),
    // The stored page is the unfiltered one.
    placeholder: unfiltered ? heldMatches : undefined,
  })
  const storedList = matchesQuery.data?.pages[0]?.source === 'stored'
  const storedTotal = matchesQuery.data?.pages[0]?.stored_total ?? null

  // When the live history fails and the profile did not, the games held for
  // the page stay on screen under a line that says so, rather than an error
  // where the games were. Only for the unfiltered list, which is the one that
  // was stored.
  const storedPage =
    !storedMode && matchesQuery.isError && matches.length === 0 && unfiltered ? heldMatches() : undefined
  const rows = storedPage?.matches ?? matches

  // The champions this player has stored games on, for the champion filter.
  // Storage only, so it costs no Riot call.
  const playedQuery = useQuery({
    // The live key is the one the champions tab and the mastery page share.
    queryKey: storedMode
      ? ['analytics', platform, name, tag, { queue: null, limit: PLAYED_LIMIT }, 'stored']
      : ['analytics', platform, name, tag, { queue: null, limit: PLAYED_LIMIT }],
    queryFn: () =>
      api.analytics(platform, name, tag, {
        queue: null,
        limit: PLAYED_LIMIT,
        source: storedMode ? 'stored' : undefined,
      }),
    enabled: storedMode || liveAnswered,
    retry: false,
  })

  // Read after the history, not beside it. The analytics describe stored games,
  // and loading history is what stores them: on a first visit, asked in
  // parallel, they described nothing. Keyed on when the history last loaded,
  // so every new page is reflected, with the previous answer held meanwhile.
  //
  // Not while the history is still the placeholder: that would describe the
  // stored games before the live page has been stored, and ask again a
  // moment later. The stored analytics stand in until then.
  const analyticsQuery = useQuery({
    queryKey: ['analytics', platform, name, tag, matchesQuery.dataUpdatedAt],
    queryFn: () => api.analytics(platform, name, tag),
    enabled: !storedMode && matchesQuery.isSuccess && !matchesQuery.isPlaceholderData,
    placeholderData: (previous) =>
      previous ?? queryClient.getQueryData(queries.analyticsStored(platform, name, tag).queryKey),
    retry: false,
  })
  const analytics = storedMode ? storedAnalytics : analyticsQuery.data

  return {
    profileQuery,
    live,
    notFound,
    storedMode,
    storedProfile,
    // Asked of storage and not answered yet: a skeleton, not an error.
    storedProfilePending: storedMode && storedProfileQuery.isPending,
    movedFromLabel,
    moving,
    matchesQuery,
    matches,
    rows,
    storedList,
    storedTotal,
    storedPage,
    playedQuery,
    analytics,
  }
}
