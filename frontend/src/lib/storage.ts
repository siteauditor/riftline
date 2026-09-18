import { useSyncExternalStore } from 'react'

import { PLATFORMS } from './api'

/**
 * What one browser remembers between visits: the region last searched and the
 * profiles recently opened. Nothing here leaves the browser.
 *
 * Every access is guarded. A private window, blocked site data or an embedded
 * frame can make `localStorage` throw rather than return null, and a search box
 * that crashes because it could not remember a region is worse than one that
 * forgets.
 */

const REGION_KEY = 'riftline.region'
const RECENT_KEY = 'riftline.recent'
const MAX_RECENT = 6

function readRaw(key: string): string | null {
  try {
    return window.localStorage.getItem(key)
  } catch {
    return null
  }
}

function writeRaw(key: string, value: string | null) {
  try {
    if (value === null) window.localStorage.removeItem(key)
    else window.localStorage.setItem(key, value)
  } catch {
    // Storage refused. The page works the same, it just forgets.
  }
}

// --- region -----------------------------------------------------------------

/** The region last used, or null. A stored id this build no longer offers is ignored. */
export function lastRegion(): string | null {
  const id = readRaw(REGION_KEY)
  return PLATFORMS.some((p) => p.id === id) ? id : null
}

export function rememberRegion(id: string) {
  if (PLATFORMS.some((p) => p.id === id)) writeRaw(REGION_KEY, id)
}

// --- recent profiles ----------------------------------------------------------

export interface RecentSearch {
  platform: string
  gameName: string
  tagLine: string
  iconUrl: string | null
  at: number
}

/** The same folding the server applies to Riot IDs: accents, case and spaces. */
export function foldRiotName(name: string): string {
  return name.normalize('NFKD').replace(/\p{M}/gu, '').replace(/\s/g, '').toLowerCase()
}

function sameAccount(a: Omit<RecentSearch, 'at'>, b: Omit<RecentSearch, 'at'>) {
  return (
    a.platform === b.platform &&
    foldRiotName(a.gameName) === foldRiotName(b.gameName) &&
    a.tagLine.toLowerCase() === b.tagLine.toLowerCase()
  )
}

function parseRecent(raw: string | null): RecentSearch[] {
  if (!raw) return []
  try {
    const value: unknown = JSON.parse(raw)
    if (!Array.isArray(value)) return []
    // Written by an older build, or by hand: keep only entries that still have
    // the shape a link needs.
    return value.filter(
      (e): e is RecentSearch =>
        typeof e?.platform === 'string' &&
        typeof e?.gameName === 'string' &&
        typeof e?.tagLine === 'string' &&
        typeof e?.at === 'number',
    )
  } catch {
    return []
  }
}

const listeners = new Set<() => void>()
const EMPTY: RecentSearch[] = []
let cachedRaw: string | null = null
let cachedList: RecentSearch[] = EMPTY

// useSyncExternalStore needs the same array back until the data changes, or it
// renders forever. So the parsed list is kept against the raw string it came from.
function snapshot(): RecentSearch[] {
  const raw = readRaw(RECENT_KEY)
  if (raw !== cachedRaw) {
    cachedRaw = raw
    cachedList = parseRecent(raw)
  }
  return cachedList
}

function subscribe(onChange: () => void) {
  listeners.add(onChange)
  // Another tab opening a profile updates this one too.
  window.addEventListener('storage', onChange)
  return () => {
    listeners.delete(onChange)
    window.removeEventListener('storage', onChange)
  }
}

function saveRecent(list: RecentSearch[]) {
  writeRaw(RECENT_KEY, list.length ? JSON.stringify(list) : null)
  listeners.forEach((notify) => notify())
}

/** Newest first. */
export function useRecentSearches(): RecentSearch[] {
  return useSyncExternalStore(subscribe, snapshot, () => EMPTY)
}

export function rememberSearch(entry: Omit<RecentSearch, 'at'>) {
  const rest = snapshot().filter((e) => !sameAccount(e, entry))
  saveRecent([{ ...entry, at: Date.now() }, ...rest].slice(0, MAX_RECENT))
}

export function clearRecentSearches() {
  saveRecent([])
}
