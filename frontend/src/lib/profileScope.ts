import { useEffect } from 'react'

import type { QueueScope } from './api'
import { useHydrated, useHydratedSearchParams, withParams } from './searchParams'

export type { QueueScope }

/**
 * Which queues a profile's games and numbers cover.
 *
 * One word per choice, shared by the chips, the URL (`?queue=solo`) and the API
 * (`scope`), whose list is `backend/app/services/queues.py`. A profile used to
 * pool every queue into one set of numbers: one player read 62% and a 4.47 KDA
 * over all their stored games, and 50% and 3.85 over the ranked ones
 * (2026-09-24). The page opens on ranked, and every figure says which games it
 * covers.
 */

export const DEFAULT_SCOPE: QueueScope = 'ranked'

export const SCOPES: readonly { id: QueueScope; label: string }[] = [
  { id: 'ranked', label: 'Ranked' },
  { id: 'solo', label: 'Solo/Duo' },
  { id: 'flex', label: 'Flex' },
  { id: 'normal', label: 'Normal' },
  { id: 'swiftplay', label: 'Swiftplay' },
  { id: 'aram', label: 'ARAM' },
  { id: 'all', label: 'All' },
]

// Links from before the words named one queue id (`?queue=420`).
const LEGACY: Record<string, QueueScope> = {
  '420': 'solo',
  '440': 'flex',
  '400': 'normal',
  '430': 'normal',
  '490': 'normal',
  '480': 'swiftplay',
  '450': 'aram',
  '2400': 'aram',
}

const isScope = (value: string): value is QueueScope => SCOPES.some((s) => s.id === value)

/** The scope a URL's `queue` asks for: a word, an older link's queue id, or the default. */
export function scopeFromParam(value: string | null): QueueScope {
  if (value === null) return DEFAULT_SCOPE
  if (isScope(value)) return value
  return legacyScope(value) ?? DEFAULT_SCOPE
}

/** An older link's queue id, as the word the page now writes, or null. */
export function legacyScope(value: string | null): QueueScope | null {
  return value !== null && Object.hasOwn(LEGACY, value) ? LEGACY[value] : null
}

/** The URL's `queue` for a scope: none for the default, so the bare path is ranked. */
export function scopeParam(scope: QueueScope): string | null {
  return scope === DEFAULT_SCOPE ? null : scope
}

/**
 * The scope the URL asks for. Read through `useHydratedSearchParams`, so the
 * page hydrates on the default its HTML was rendered with; an older link's
 * queue id is rewritten to its word once, after hydration.
 */
export function useScope(): QueueScope {
  const [search, setSearch] = useHydratedSearchParams()
  const hydrated = useHydrated()
  const raw = search.get('queue')
  useEffect(() => {
    if (!hydrated) return
    const word = legacyScope(raw)
    if (word !== null) setSearch((prev) => withParams(prev, { queue: scopeParam(word) }), { replace: true })
  }, [hydrated, raw, setSearch])
  return scopeFromParam(raw)
}

const NOUNS: Record<QueueScope, string> = {
  ranked: 'ranked',
  solo: 'solo queue',
  flex: 'flex',
  normal: 'normal',
  swiftplay: 'Swiftplay',
  aram: 'ARAM',
  all: '',
}

/** "ranked", "ARAM", or nothing for every queue: the word before "games". */
export function scopeNoun(scope: QueueScope | null | undefined): string {
  return scope ? NOUNS[scope] : ''
}

const n = (value: number) => value.toLocaleString('en-US')

/**
 * The games a figure covers, in words: "182 ranked games", "1 ARAM game",
 * "the newest 1,000 of 1,306 ranked games" when the window is smaller than
 * what is held.
 */
export function gamesCovered({
  games,
  total,
  scope,
}: {
  games: number
  total?: number | null
  scope: QueueScope | null | undefined
}): string {
  const noun = scopeNoun(scope)
  const kind = noun ? `${noun} ` : ''
  if (total != null && total > games) return `the newest ${n(games)} of ${n(total)} ${kind}games`
  return `${n(games)} ${kind}${games === 1 ? 'game' : 'games'}`
}
