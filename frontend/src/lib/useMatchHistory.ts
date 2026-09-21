import { useMemo } from 'react'
import { useInfiniteQuery } from '@tanstack/react-query'

import { api, type MatchSummary } from './api'

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
  { queue = null, enabled = true }: { queue?: number | null; enabled?: boolean } = {},
) {
  const query = useInfiniteQuery({
    queryKey: ['matches', platform, name, tag, queue],
    initialPageParam: 0,
    queryFn: ({ pageParam }) =>
      api.matches(platform, name, tag, { start: pageParam, count: MATCH_PAGE, queue }),
    getNextPageParam: (last, pages) =>
      last.has_more ? pages.length * MATCH_PAGE : undefined,
    enabled,
  })

  const matches: MatchSummary[] = useMemo(
    () => query.data?.pages.flatMap((p) => p.matches) ?? [],
    [query.data],
  )

  return { query, matches }
}
