import { useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { useSearchParams } from 'react-router-dom'

import type { SliceValue } from '../components/SliceFilters'
import { foldRiotName } from './storage'
import { useDebounced } from './useDebounced'

/**
 * Filter state kept in the URL.
 *
 * Every list on the site used to hold its filters in component state, so they
 * were gone after a reload, a shared link or the back button: measured on the
 * tier list, pick Jungle, open a champion, press back, and the list was on All
 * again. The URL survives all three.
 *
 * The rule each page follows: a filter, sort or search change replaces the
 * history entry, so back leaves the page instead of stepping through every
 * tweak, and a page number pushes one, so back returns to the previous page.
 */

const subscribeNever = () => () => {}

/**
 * False while React hydrates a prerendered page; true from the render after,
 * and at once on a page React renders itself (a client navigation, the shell).
 */
export function useHydrated(): boolean {
  return useSyncExternalStore(subscribeNever, () => true, () => false)
}

// Never mutated: every writer copies before it changes anything (`withParams`).
const NO_PARAMS = new URLSearchParams()

/**
 * `useSearchParams`, except empty while the page hydrates.
 *
 * nginx serves the file prerendered for the bare path whatever the query
 * string, so `/tierlist?position=TOP` arrives as the HTML of `/tierlist`. A
 * first render that read the URL drew the Top list over the All list's HTML,
 * and React threw the page away with error #418 (measured on production on
 * 2026-09-24 on the tier list, the leaderboards, a champion page and the
 * draft). Reading nothing until hydration has finished makes the first render
 * match the HTML; the render straight after is the view the link asked for.
 * Every route that reads URL state in render goes through this.
 */
export function useHydratedSearchParams(): ReturnType<typeof useSearchParams> {
  const [search, setSearch] = useSearchParams()
  return [useHydrated() ? search : NO_PARAMS, setSearch]
}

/** Case, accents, spaces and punctuation folded: "kaisa" finds Kai'Sa and
 *  "rabadons" finds Rabadon's Deathcap. */
export const foldName = (name: string) => foldRiotName(name).replace(/[^\p{L}\p{N}]/gu, '')

/**
 * A positive whole number from the URL, or the fallback.
 *
 * URL params are user input. `Number('abc')` is NaN, `Math.max(1, NaN)` is NaN,
 * and `String(NaN)` once went on the wire as `page=NaN` for FastAPI to reject
 * with a 422 that surfaced as "Something went wrong".
 */
export function intParam(search: URLSearchParams, key: string, fallback: number): number {
  const value = Number(search.get(key))
  return Number.isFinite(value) && value > 0 ? Math.floor(value) : fallback
}

/** The first of several names a parameter has had, so links already shared
 *  keep working after a rename. */
export function firstParam(search: URLSearchParams, ...keys: string[]): string | null {
  for (const key of keys) {
    const value = search.get(key)
    if (value !== null && value !== '') return value
  }
  return null
}

export type ParamValue = string | number | boolean | null | undefined | readonly string[]

/**
 * A copy of `search` with `patch` applied.
 *
 * Null, empty, false and a value equal to its default are removed rather than
 * written, so the default view keeps a clean URL and a link to it stays short.
 */
export function withParams(
  search: URLSearchParams,
  patch: Record<string, ParamValue>,
  defaults: Record<string, string> = {},
): URLSearchParams {
  const next = new URLSearchParams(search)
  for (const [key, raw] of Object.entries(patch)) {
    const value = Array.isArray(raw)
      ? raw.join(',')
      : raw === null || raw === undefined || raw === false
        ? ''
        : raw === true
          ? '1'
          : String(raw)
    if (value === '' || value === defaults[key]) next.delete(key)
    else next.set(key, value)
  }
  return next
}

/**
 * Text typed into a box that lives in the URL.
 *
 * The box follows every keystroke; the URL, and whatever filters on it, only
 * once typing settles, so a word is one history write rather than one per
 * letter. A change from outside (back, forward, a link) is copied into the box.
 */
export function useSearchText(key = 'q', ms = 200): [string, (value: string) => void] {
  const [search, setSearch] = useHydratedSearchParams()
  const inUrl = search.get(key) ?? ''
  const [text, setText] = useState(inUrl)
  const settled = useDebounced(text, ms)
  // What this hook last put in the URL, to tell its own writes from a
  // navigation. Comparing against the box instead reset it mid-word, because
  // the URL trails the box by the debounce.
  const written = useRef(inUrl)

  useEffect(() => {
    if (inUrl !== written.current) {
      written.current = inUrl
      setText(inUrl)
    }
  }, [inUrl])

  useEffect(() => {
    const value = settled.trim()
    if (value === written.current) return
    written.current = value
    setSearch((prev) => withParams(prev, { [key]: value }), { replace: true })
  }, [settled, key, setSearch])

  return [text, setText]
}

/** Defaults every slice page shares. The sample floor is each page's own. */
export const SLICE_DEFAULTS = { queue: '420', bracket: 'ALL' }

/**
 * The slice the tier list, champion and item pages are keyed by, from the URL.
 *
 * `queue_id` is what the champion and item pages wrote before the names were
 * made one per concept; it is still read so links already shared keep working.
 */
export function sliceFromParams(search: URLSearchParams, minGames: number): SliceValue {
  const queue = Number(firstParam(search, 'queue', 'queue_id'))
  return {
    patch: search.get('patch') || null,
    queueId: SLICE_QUEUES.includes(queue) ? queue : 420,
    position: positionParam(search.get('position')),
    bracket: search.get('bracket'),
    minGames: Math.min(MAX_MIN_GAMES, intParam(search, 'min_games', minGames)),
  }
}

/** The queues the rollups are built for: ranked solo and ranked flex. */
const SLICE_QUEUES = [420, 440]
const SLICE_POSITIONS = ['TOP', 'JUNGLE', 'MIDDLE', 'BOTTOM', 'UTILITY']
/** The highest sample floor a page accepts, as the API does. */
export const MAX_MIN_GAMES = 500

/**
 * A role from the URL in any case, or null for one the API would refuse. A
 * link with `position=top` or `position=banana` used to reach the API as it
 * was and come back as an error page.
 */
export function positionParam(value: string | null): string | null {
  const upper = value?.toUpperCase() ?? ''
  return SLICE_POSITIONS.includes(upper) ? upper : null
}

/**
 * The query string a slice page should be at, or null when it already is: the
 * one it was given with every value the page could not use put right (a role
 * in the wrong case, a queue or floor out of range, a renamed parameter).
 * The patch is left alone: only the API knows which patches it holds, and a
 * page answers an unheld one with a notice.
 */
export function sliceCorrections(search: URLSearchParams, minGames: number): URLSearchParams | null {
  const slice = sliceFromParams(search, minGames)
  const next = withParams(search, sliceParams({ ...slice, patch: search.get('patch') }), {
    ...SLICE_DEFAULTS,
    min_games: String(minGames),
  })
  return next.toString() === search.toString() ? null : next
}

/**
 * Rewrites a slice page's address once, after hydration, when it holds values
 * the page corrected, so the address, the controls and the numbers agree. The
 * draft board does the same with its own URL.
 */
export function useSliceCorrections(minGames: number): void {
  const [search, setSearch] = useHydratedSearchParams()
  const hydrated = useHydrated()
  useEffect(() => {
    if (!hydrated) return
    const fixed = sliceCorrections(search, minGames)
    if (fixed) setSearch(fixed, { replace: true })
  }, [hydrated, search, minGames, setSearch])
}

/** A slice change as URL parameters, for `withParams`. */
export function sliceParams(next: Partial<SliceValue>): Record<string, ParamValue> {
  const out: Record<string, ParamValue> = {}
  if ('patch' in next) out.patch = next.patch
  if ('queueId' in next) {
    out.queue = next.queueId
    out.queue_id = null
  }
  if ('position' in next) out.position = next.position
  if ('bracket' in next) out.bracket = next.bracket
  if ('minGames' in next) out.min_games = next.minGames
  return out
}

/**
 * The query string that carries a slice to another page: role, patch, queue
 * and bracket. Not the sample floor, which each page sets for itself (20 on the
 * tier list, 5 on a champion). Links used to carry the role at most, so a
 * Flex or older-patch view opened its champion on the defaults.
 */
export function sliceLink(slice: {
  patch?: string | null
  queueId?: number | null
  position?: string | null
  bracket?: string | null
}): string {
  const params = withParams(
    new URLSearchParams(),
    {
      position: slice.position,
      patch: slice.patch,
      queue: slice.queueId,
      bracket: slice.bracket,
    },
    SLICE_DEFAULTS,
  )
  const text = params.toString()
  return text ? `?${text}` : ''
}
