import { useQuery } from '@tanstack/react-query'

import { api } from './api'

/**
 * Centred splash art for a champion, for the page header behind the type.
 *
 * Every page's art is the subject it is about, so each one has a different way
 * of naming that champion: the strongest pick, the player's most played, the
 * lane opponent. They all need the same lookup, and the static champion list is
 * already cached for six hours, so this is one shared read rather than a query
 * repeated in nine files.
 */
export function useChampionArt(championId: number | null | undefined): string | null {
  const { data } = useQuery({
    queryKey: ['champions'],
    queryFn: api.champions,
    staleTime: 6 * 60 * 60 * 1000,
  })
  if (!championId) return null
  return data?.champions.find((c) => c.id === championId)?.art_url ?? null
}
