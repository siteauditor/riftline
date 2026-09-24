import { useMemo } from 'react'
import { useInfiniteQuery } from '@tanstack/react-query'

import { api, type MatchHistory, type MatchSummary, type QueueScope } from './api'

/** Twenty is what Riot's match-v5 hands back in one call, and what a page of
 *  history costs in rate limit. */
export const MATCH_PAGE = 20

/**
 * A player's match history, shared by every page that wants it.
 *
 * The profile and the live page read the same list, and the cache key is the
 * same object: a second `useQuery` on `['matches', ...]` with a different
 * `count` would not be a second list, it would be the same cache entry with two
 * configurations, and whichever page mounted second would win. So there is one
 * hook, one key and one page size.
 *
 * Loading history is also what stores it, which is why the profile's analytics
 * are keyed on when this last resolved.
 */
export function useMatchHistory(
  platform: string,
  name: string,
  tag: string,
  {
    scope = 'all',
    champion = null,
    source,
    enabled = true,
    placeholder,
  }: {
    /** The queues listed; every queue unless the page asks for fewer. */
    scope?: QueueScope
    champion?: number | null
    /** `stored` reads storage alone: the profile's fallback while Riot
     *  cannot be asked. Its own key, so it never stands in for Riot's list. */
    source?: 'stored'
    enabled?: boolean
    /** A first page to show until the real one loads: the prerendered
     *  profile's stored page, so the list is there before the fetch. */
    placeholder?: () => MatchHistory | undefined
  } = {},
) {
  const query = useInfiniteQuery({
    // The champion is last, so the unfiltered history keeps the key the live
    // page shares.
    queryKey: [
      'matches',
      platform,
      name,
      tag,
      scope,
      ...(champion ? [champion] : []),
      ...(source ? [source] : []),
    ],
    initialPageParam: 0,
    queryFn: ({ pageParam }) =>
      api.matches(platform, name, tag, {
        start: pageParam,
        count: MATCH_PAGE,
        scope: scope === 'all' ? null : scope,
        champion,
        source,
      }),
    getNextPageParam: (last, pages) =>
      last.has_more ? pages.length * MATCH_PAGE : undefined,
    enabled,
    placeholderData: placeholder
      ? () => {
          const page = placeholder()
          return page ? { pages: [page], pageParams: [0] } : undefined
        }
      : undefined,
  })

  const matches: MatchSummary[] = useMemo(
    () => query.data?.pages.flatMap((p) => p.matches) ?? [],
    [query.data],
  )

  return { query, matches }
}
