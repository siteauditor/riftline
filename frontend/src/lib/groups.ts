import { useSyncExternalStore } from 'react'

import { parseRiotId } from './format'

/**
 * The groups this browser has made or opened, and their edit keys.
 *
 * There are no accounts, so this is where "your groups" live: in this browser
 * and nowhere else. An edit key arrives in a link's `#key=` part, which the
 * browser never sends to a server, and is moved here and out of the address
 * bar, so the address a visitor copies is the view link.
 *
 * Every access is guarded, as in `storage.ts`: a private window or blocked
 * site data can make `localStorage` throw.
 */

const STORE_KEY = 'riftline.groups'
const MAX_SAVED = 30

export interface SavedGroup {
  slug: string
  name: string
  /** The edit key, when this browser holds one. */
  key: string | null
  at: number
}

function readRaw(): string | null {
  try {
    return window.localStorage.getItem(STORE_KEY)
  } catch {
    return null
  }
}

function writeRaw(value: string | null) {
  try {
    if (value === null) window.localStorage.removeItem(STORE_KEY)
    else window.localStorage.setItem(STORE_KEY, value)
  } catch {
    // Storage refused. The group still works; this browser just forgets it.
  }
}

function parse(raw: string | null): SavedGroup[] {
  if (!raw) return []
  try {
    const value: unknown = JSON.parse(raw)
    if (!Array.isArray(value)) return []
    return value.filter(
      (g): g is SavedGroup =>
        typeof g?.slug === 'string' &&
        typeof g?.name === 'string' &&
        (g.key === null || typeof g.key === 'string') &&
        typeof g?.at === 'number',
    )
  } catch {
    return []
  }
}

const listeners = new Set<() => void>()
const EMPTY: SavedGroup[] = []
let cachedRaw: string | null = null
let cachedList: SavedGroup[] = EMPTY

// The same array back until the data changes, or useSyncExternalStore renders forever.
function snapshot(): SavedGroup[] {
  const raw = readRaw()
  if (raw !== cachedRaw) {
    cachedRaw = raw
    cachedList = parse(raw)
  }
  return cachedList
}

function subscribe(onChange: () => void) {
  listeners.add(onChange)
  window.addEventListener('storage', onChange)
  return () => {
    listeners.delete(onChange)
    window.removeEventListener('storage', onChange)
  }
}

function save(list: SavedGroup[]) {
  writeRaw(list.length ? JSON.stringify(list.slice(0, MAX_SAVED)) : null)
  listeners.forEach((notify) => notify())
}

/** Newest first. */
export function useSavedGroups(): SavedGroup[] {
  return useSyncExternalStore(subscribe, snapshot, () => EMPTY)
}

/**
 * Remember a group. A `key` of undefined keeps the one already held, so
 * opening a group by its view link never forgets an edit key.
 */
export function rememberGroup(entry: { slug: string; name?: string; key?: string | null }) {
  const list = snapshot()
  const old = list.find((g) => g.slug === entry.slug)
  const next: SavedGroup = {
    slug: entry.slug,
    name: entry.name ?? old?.name ?? 'Group',
    key: entry.key === undefined ? (old?.key ?? null) : entry.key,
    at: Date.now(),
  }
  const unchanged =
    old && old.name === next.name && old.key === next.key && list[0]?.slug === entry.slug
  if (unchanged) return
  save([next, ...list.filter((g) => g.slug !== entry.slug)])
}

export function forgetGroup(slug: string) {
  save(snapshot().filter((g) => g.slug !== slug))
}

/** The edit key in an address's `#key=` part, if there is one. */
export function keyInHash(hash: string): string | null {
  const match = /(?:^#|&)key=([^&]+)/.exec(hash)
  if (!match) return null
  try {
    return decodeURIComponent(match[1])
  } catch {
    return null
  }
}

export function viewLink(slug: string): string {
  return `${window.location.origin}/g/${slug}`
}

export function editLink(slug: string, key: string): string {
  return `${viewLink(slug)}#key=${encodeURIComponent(key)}`
}

/**
 * Riot IDs in pasted text: one per line, comma-separated, or the client's
 * lobby lines ("Name#TAG joined the lobby"). Repeats are dropped, folded the
 * way the server folds names.
 */
export function riotIdsIn(text: string): string[] {
  const found: string[] = []
  const seen = new Set<string>()
  for (const chunk of text.split(/[\n,;]+/)) {
    const line = chunk
      .replace(/\s+(joined|left)\s+the\s+lobby.*$/i, '')
      .replace(/\s+/g, ' ')
      .trim()
    // The tag is the first run after the last '#', so trailing words go.
    const match = /^(.*)#([^\s#]+)/.exec(line)
    if (!match) continue
    const parsed = parseRiotId(`${match[1].trim()}#${match[2]}`)
    if (!parsed) continue
    const id = `${parsed.name}#${parsed.tag}`
    const folded = id.normalize('NFKD').replace(/\p{M}/gu, '').replace(/\s/g, '').toLowerCase()
    if (seen.has(folded)) continue
    seen.add(folded)
    found.push(id)
  }
  return found
}
