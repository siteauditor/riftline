import { useEffect } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'

import { ApiError, type QueueScope } from './api'
import { canonicalPlatform, movedFrom, profileRedirect } from './profileAddress'
import { queries } from './queries'
import { useHydrated } from './searchParams'
import { rememberSearch } from './storage'
import { useMatchHistory } from './useMatchHistory'

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
  { scope, champion }: { scope: QueueScope; champion: number | null },
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
    ...queries.analyticsStored(platform, name, tag, scope),
    enabled: storedMode,
    staleTime: Infinity,
    retry: false,
  }).data
  const heldMatches = () =>
    queryClient.getQueryData(queries.matchesStored(platform, name, tag, scope).queryKey)

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

  // The live page reads the same history, so the query lives in one hook: two
  // configurations of one cache key is a race between whichever page mounts
  // first. In stored mode the same hook reads storage, filters included.
  const { query: matchesQuery, matches } = useMatchHistory(platform, name, tag, {
    scope,
    champion,
    source: storedMode ? 'stored' : undefined,
    enabled: hydrated && (storedMode || liveAnswered),
    // The stored page is the one without a champion filter.
    placeholder: champion === null ? heldMatches : undefined,
  })
  const storedList = matchesQuery.data?.pages[0]?.source === 'stored'
  const storedTotal = matchesQuery.data?.pages[0]?.stored_total ?? null

  // When the live history fails and the profile did not, the games held for
  // the page stay on screen under a line that says so, rather than an error
  // where the games were. Only without a champion filter, which is the list
  // that was stored.
  const storedPage =
    !storedMode && matchesQuery.isError && matches.length === 0 && champion === null
      ? heldMatches()
      : undefined
  const rows = storedPage?.matches ?? matches

  // Every number on the page, the champion filter's list and the champions
  // tab read this one answer, over one window of games in the scope. It is
  // read after the history, not beside it: loading history is what stores the
  // games, and on a first visit, asked in parallel, it described nothing. Each
  // later page of history stores more, so the answer is asked again then,
  // with the previous one shown meanwhile.
  const analyticsQuery = useQuery({
    ...queries.analytics(platform, name, tag, scope),
    enabled: !storedMode && matchesQuery.isSuccess && !matchesQuery.isPlaceholderData,
    placeholderData: () =>
      queryClient.getQueryData(queries.analyticsStored(platform, name, tag, scope).queryKey),
    retry: false,
  })
  const historyStoredAt = matchesQuery.isPlaceholderData ? 0 : matchesQuery.dataUpdatedAt
  useEffect(() => {
    if (!historyStoredAt || storedMode) return
    const key = queries.analytics(platform, name, tag, scope).queryKey
    // The first page enabled the query, which then asks by itself; an answer
    // older than a later page is asked again.
    const answeredAt = queryClient.getQueryState(key)?.dataUpdatedAt ?? 0
    if (answeredAt > 0 && answeredAt < historyStoredAt) {
      void queryClient.invalidateQueries({ queryKey: key, exact: true })
    }
  }, [historyStoredAt, storedMode, platform, name, tag, scope, queryClient])
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
    analytics,
  }
}
